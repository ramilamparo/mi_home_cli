"""The `mi auth` / `mi profile` commands."""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import webbrowser
from typing import Annotated, Optional

import typer

from .. import render
from ..core import const
from ..core.callback import (
    CallbackResult,
    CallbackServer,
    MdnsPublisher,
    local_ips,
    parse_pasted,
    port_available,
    resolve_redirect_host,
)
from ..core.oauth import OAuthClient, build_auth_url, state_for_device
from ..core.qrlogin import QrLoginClient, render_qr
from ..errors import MiCliError, NotAuthenticated, UsageError
from ..render import OutputFormat, mask
from ..store import Profile, config_dir, list_profiles, read_config, write_config
from .context import AppContext, OutputOption, pick_output

app = typer.Typer(help="Login and credential management", no_args_is_help=True)
profile_app = typer.Typer(help="Multiple accounts / regions", no_args_is_help=True)


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 0:
        return "expired"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"


_STDIN_EOF = "__stdin_eof__"


def _collect_code(
    *,
    server: CallbackServer | None,
    result_queue: "queue.Queue[object]",
    expected_state: str,
    wait_seconds: float,
) -> CallbackResult:
    """Wait for the callback or for the user to paste, whichever comes first."""
    stop = threading.Event()

    def read_stdin() -> None:
        while not stop.is_set():
            try:
                line = sys.stdin.readline()
            except (OSError, ValueError):
                return
            if not line:
                result_queue.put(_STDIN_EOF)
                return
            if not line.strip():
                continue
            try:
                result_queue.put(parse_pasted(line, expected_state=expected_state))
                return
            except MiCliError as err:
                render.error(err.message)
                render.info("Try again, or press Ctrl-C to quit:")

    threading.Thread(target=read_stdin, name="mi-paste", daemon=True).start()

    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stop.set()
            raise MiCliError(
                f"Timed out waiting for authorization ({int(wait_seconds)} seconds)",
                hint="Use `mi auth login --manual` to paste the callback URL by hand",
            )
        try:
            item = result_queue.get(timeout=min(1.0, remaining))
        except queue.Empty:
            continue
        if item is _STDIN_EOF:
            if server is None:
                stop.set()
                raise UsageError(
                    "Standard input is closed and no local callback is available; run "
                    "in an interactive terminal, or pipe the callback URL in"
                )
            # The local callback path is still open, keep waiting.
            continue
        result: CallbackResult = item  # type: ignore[assignment]
        stop.set()
        if result.source == "server":
            # A local callback always carries state; a mismatch means someone else sent
            # the request, so reject it.
            if result.state != expected_state:
                raise MiCliError(
                    "The callback's state does not match this login; ignored",
                    hint="Run `mi auth login` again",
                )
        elif result.state and result.state != expected_state:
            raise MiCliError("state mismatch; this may not be the callback of this "
                             "login. Please log in again")
        elif not result.state:
            render.warn("The pasted text has no state; skipping the check")
        return result


@app.command()
def login(
    ctx: typer.Context,
    region: Annotated[
        Optional[str], typer.Option("--region", "-r", help="Region: " + "/".join(const.CLOUD_SERVERS))
    ] = None,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan", help="Log in by scanning a QR code with your Xiaomi account (QR "
                           "code shown in the terminal, no browser needed)"
        ),
    ] = False,
    manual: Annotated[
        bool, typer.Option("--manual", help="Do not listen on a port; only paste the "
                                            "callback URL by hand")
    ] = False,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a browser automatically")
    ] = False,
    no_mdns: Annotated[
        bool, typer.Option("--no-mdns", help="Do not advertise via mDNS")
    ] = False,
    redirect_url: Annotated[
        Optional[str],
        typer.Option(
            "--redirect-url",
            help="Custom redirect_uri (the host must be homeassistant.local:8123)",
        ),
    ] = None,
    device_id: Annotated[
        Optional[str], typer.Option("--device-id", help="Custom device_id (for "
                                                        "troubleshooting)")
    ] = None,
    wait: Annotated[
        float, typer.Option("--wait", help="Seconds to wait for authorization")
    ] = 300.0,
    skip_confirm: Annotated[
        bool, typer.Option("--skip-confirm", help="Skip the confirmation page if "
                                                  "already authorized")
    ] = False,
) -> None:
    """Log in with a Xiaomi account."""
    app_ctx = _ctx(ctx)
    region = region or app_ctx.resolved_region()
    if region not in const.CLOUD_SERVERS:
        raise UsageError(
            f"Unknown region `{region}`; choose from: {', '.join(const.CLOUD_SERVERS)}"
        )

    profile = app_ctx.profile
    identity = profile.identity(region)
    redirect = redirect_url or identity.redirect_url
    if not redirect.startswith(const.REDIRECT_ORIGIN):
        render.warn(
            f"The redirect_uri host is not {const.REDIRECT_HOST}:{const.REDIRECT_PORT}"
            "; Xiaomi's server will reject it (invalid redirect uri)"
        )
    device_id = device_id or identity.device_id
    # state uses HA's algorithm purely to have one variable fewer that differs from
    # upstream.
    state = state_for_device(device_id)
    # Persist first, so a failed token exchange can be retried with the same code via
    # `mi auth exchange`.
    profile.write_pending(
        {
            "region": region,
            "device_id": device_id,
            "redirect_url": redirect,
            "state": state,
            "created_at": int(time.time()),
        }
    )

    if scan:
        _scan_login(
            app_ctx,
            region=region,
            redirect=redirect,
            device_id=device_id,
            state=state,
            wait=wait,
        )
        return

    auth_url = build_auth_url(
        redirect_url=redirect,
        device_id=device_id,
        state=state,
        skip_confirm=skip_confirm,
    )

    result_queue: "queue.Queue[object]" = queue.Queue()
    server: CallbackServer | None = None
    mdns: MdnsPublisher | None = None

    if not manual:
        server, mdns = _try_auto_capture(result_queue, no_mdns=no_mdns)

    try:
        render.info("")
        render.info("[bold]1.[/bold] Open the link below in a browser, sign in with "
                    "your Xiaomi account and authorize:")
        render.raw(auth_url)
        if not no_browser and not _open_browser(auth_url):
            render.warn("Could not open a browser automatically; copy the link above "
                        "by hand")
        if server:
            render.info(
                "[bold]2.[/bold] After authorizing, the browser is redirected to "
                f"{redirect}; this machine is listening on port 8123 to receive it."
            )
            render.info(
                "[bold]3.[/bold] If that page does not load (homeassistant.local does "
                "not point at this machine), paste the full address from the "
                "browser's address bar here and press Enter:"
            )
        else:
            render.info(
                "[bold]2.[/bold] After authorizing, the browser is redirected to "
                f"{redirect}; that address will most likely fail to load, which is "
                "fine."
            )
            render.info(
                "[bold]3.[/bold] Paste the full address from the browser's address "
                "bar here and press Enter:"
            )
        render.info("")

        result = _collect_code(
            server=server,
            result_queue=result_queue,
            expected_state=state,
            wait_seconds=wait,
        )
        if server:
            _drain(server, result_queue, result)
    finally:
        if server:
            server.close()
        if mdns:
            mdns.close()

    render.info(
        "Got the authorization code (from "
        f"{'the local callback' if result.source == 'server' else 'pasted input'}), "
        "exchanging it for a token…"
    )
    try:
        _exchange_and_save(
            app_ctx,
            region=region,
            redirect=redirect,
            device_id=device_id,
            code=result.code,
        )
    except MiCliError as err:
        # When the token exchange fails the authorization code is usually not consumed
        # yet; do not make the user go through the browser again for nothing.
        render.error(err.message)
        if err.hint:
            render.info(f"[dim]Hint: {err.hint}[/dim]")
        render.info("If the authorization code is still valid you can retry directly:")
        render.raw(f"  mi -v auth exchange {result.code}")
        raise typer.Exit(code=err.exit_code) from err


def _exchange_and_save(
    app_ctx: AppContext, *, region: str, redirect: str, device_id: str, code: str
) -> None:
    """Exchange an authorization code for a token and persist it.

    The client_id / redirect_uri / device_id of the authorization step and the token
    exchange step must be exactly identical, otherwise the server returns
    96002 invalid request.
    """
    profile = app_ctx.profile
    trace = render.raw if app_ctx.verbose else None
    with OAuthClient(
        region, redirect_url=redirect, timeout=app_ctx.timeout, trace=trace
    ) as client:
        token = client.exchange_code(code, device_id)
        auth = token.to_auth(region, device_id)
        try:
            info = client.user_profile(token.access_token)
            auth.uid = str(info.get("userId") or "") or None
            auth.nickname = info.get("miliaoNick") or info.get("nickname")
        except MiCliError as err:
            render.warn("Could not fetch account info (login is unaffected): "
                        f"{err.message}")

    profile.write_auth(auth)
    profile.clear_pending()
    render.success(
        f"Logged in: {auth.nickname or 'unknown nickname'} (uid "
        f"{auth.uid or 'unknown'}, region {region}, profile {profile.name})"
    )
    render.info(f"Credentials saved to {profile.auth_path} (mode 0600)")
    render.info(
        f"Valid for about {_fmt_duration(auth.expires_at - time.time())}; it is "
        "renewed automatically before it expires"
    )


_SCAN_MAX_ATTEMPTS = 3


def _scan_user_agent(app_ctx: AppContext) -> str:
    """User-Agent for QR-code login; it decides the name shown under Xiaomi's "logged-in devices".

    Priority: the MI_SCAN_DEVICE_NAME environment variable > the scan_device_name
    config key > the default tool name.
    """
    name = os.environ.get("MI_SCAN_DEVICE_NAME") or read_config(app_ctx.root).get(
        "scan_device_name"
    )
    name = (name or "").strip() if isinstance(name, str) else ""
    if not name:
        return const.WEB_USER_AGENT
    try:
        name.encode("latin-1")
    except UnicodeEncodeError:
        # HTTP headers can only be Latin-1 and cannot carry e.g. CJK characters; fall
        # back to the default instead of letting login crash.
        render.warn(
            f"scan_device_name `{name}` contains non-ASCII characters and cannot be "
            "used as a device name; using the default name"
        )
        return const.WEB_USER_AGENT
    return name


def _scan_login(
    app_ctx: AppContext,
    *,
    region: str,
    redirect: str,
    device_id: str,
    state: str,
    wait: float,
) -> None:
    """QR-code login: show a QR code in the terminal; after it is scanned and confirmed
    with a Xiaomi app, get the code automatically and exchange it for a token.

    A first authorization often fails to get the code / exchange the token
    automatically because "Agree and link" has to be tapped by hand; in that case fall
    back to the **original authorization link** (opened in a browser, or scanned as a QR
    code with a phone) to log in and authorize manually once. Afterwards the browser
    callback address can be pasted back to exchange the token directly, or Enter can be
    pressed to scan again (the authorization is remembered by then, `skip_confirm`
    takes effect, and no more tapping is needed).
    """
    trace = render.raw if app_ctx.verbose else None
    for attempt in range(1, _SCAN_MAX_ATTEMPTS + 1):
        try:
            result = _scan_capture_code(
                app_ctx,
                redirect=redirect,
                device_id=device_id,
                state=state,
                wait=wait,
                trace=trace,
            )
            _exchange_and_save(
                app_ctx,
                region=region,
                redirect=redirect,
                device_id=device_id,
                code=result.code,
            )
            return
        except MiCliError as err:
            render.error(err.message)
            if err.hint:
                render.info(f"[dim]Hint: {err.hint}[/dim]")
            # Non-interactive (in a pipe) or retries exhausted: only print the manual
            # authorization guide, then exit.
            if not render.is_tty() or attempt >= _SCAN_MAX_ATTEMPTS:
                _scan_guide_manual(
                    redirect=redirect, device_id=device_id, state=state, prompt=False
                )
                raise typer.Exit(code=err.exit_code) from err
            # Interactive recovery: guide a manual authorization. Pasted callback →
            # exchange the token directly; Enter → scan again.
            pasted = _scan_guide_manual(
                redirect=redirect, device_id=device_id, state=state, prompt=True
            )
            if pasted is not None:
                _exchange_and_save(
                    app_ctx,
                    region=region,
                    redirect=redirect,
                    device_id=device_id,
                    code=pasted.code,
                )
                return
            render.info("OK, generating a new QR code…")


def _scan_capture_code(
    app_ctx: AppContext,
    *,
    redirect: str,
    device_id: str,
    state: str,
    wait: float,
    trace,
) -> CallbackResult:
    """One scan attempt: show the QR code → wait for the phone to confirm → take the code from the redirect chain."""
    render.info("")
    render.info("[bold]Fetching the QR code…[/bold]")
    with QrLoginClient(
        redirect_url=redirect,
        device_id=device_id,
        state=state,
        # A fixed web deviceId: avoids registering one more device in the Xiaomi account
        # on every scan.
        web_device_id=app_ctx.profile.web_device_id(),
        # Decides the name shown under Xiaomi's "logged-in devices" (the tool name by
        # default, customisable).
        user_agent=_scan_user_agent(app_ctx),
        timeout=app_ctx.timeout,
        trace=trace,
    ) as client:
        challenge = client.start()

        qr = render_qr(challenge.login_url)
        render.info("")
        if qr:
            render.raw(qr)
            render.info("")
            # If the half-block QR code is striped or blurry, the terminal's line spacing
            # usually leaves gaps; at 1.0 it is solid. Failing that, the image link below
            # scans just as well.
            render.info(
                "[dim]QR code striped or blurry? Set the terminal line spacing to 1.0 "
                "to make it solid, or use the image link below.[/dim]"
            )
        else:
            render.warn("Cannot render the QR code in this terminal; scan it from the "
                        "image link below.")
        render.info("")
        render.info(
            "[bold]Scan with a Xiaomi app:[/bold] Profile → the scan icon in the "
            "top-right corner (or Settings → Xiaomi Account), then tap \"Confirm "
            "login\" on the phone."
        )
        render.info(
            "[dim]The first login also shows an authorization page: tap \"Agree and "
            "link\" (not needed for later scans); this command continues "
            "automatically afterwards.[/dim]"
        )
        # Terminal rendering depends on font and line spacing and may not scan, so
        # always attach the image link as a fallback; never leave the user stuck.
        if challenge.qr_image_url:
            render.info(
                "[dim]Cannot scan the QR code in the terminal? Open this address in a "
                "browser and scan the image:[/dim]"
            )
            render.raw(challenge.qr_image_url)
        render.info(
            "[dim]Or turn the address below into a QR code yourself and scan "
            "that:[/dim]"
        )
        render.raw(challenge.login_url)
        render.info(
            f"[dim]The QR code is valid for about {int(challenge.timeout)} seconds; "
            "waiting for confirmation…[/dim]"
        )

        deadline = time.monotonic() + min(wait, float(challenge.timeout))
        location = client.poll(challenge, deadline=deadline)
        render.info("Scan confirmed, exchanging for a token…")
        return client.resolve_code(location)


def _scan_guide_manual(
    *, redirect: str, device_id: str, state: str, prompt: bool
) -> Optional[CallbackResult]:
    """Fallback when scanning did not work: give the **original authorization link**
    (+ QR code) so the user can log in and authorize manually.

    `prompt=True` (interactive) waits for input: a pasted browser callback address is
    parsed and its code returned; a bare Enter returns None (meaning: go back and scan
    again). `prompt=False` only prints the guide and returns None. The authorization
    link uses `skip_confirm=false` so that "Agree and link" is shown and can be tapped
    the first time.
    """
    auth_url = build_auth_url(
        redirect_url=redirect, device_id=device_id, state=state, skip_confirm=False
    )
    render.info("")
    render.warn("Could not finish the QR authorization automatically (the first login "
                "usually needs one manual tap on \"Agree and link\").")
    render.info("Open the address below in a browser, sign in to your Xiaomi account "
                "and click \"Agree and link\" to authorize:")
    render.raw(auth_url)
    qr = render_qr(auth_url)
    if qr:
        render.info("[dim]Or scan this QR code with your phone to open the page "
                    "above:[/dim]")
        render.raw(qr)

    if not prompt:
        render.info("")
        render.info("Once authorized, run `mi auth login --scan` again (no "
                    "authorization needed this time).")
        return None

    render.info("")
    render.info(
        "When done, either paste the full address from the browser's address bar "
        "(after the redirect) here and press Enter to exchange the token right away, "
        "or just press Enter to generate a new QR code (Ctrl-C to cancel):"
    )
    while True:
        try:
            line = sys.stdin.readline()
        except (OSError, ValueError):
            return None
        if not line:  # EOF
            return None
        line = line.strip()
        if not line:  # bare Enter → go back and scan again
            return None
        try:
            return parse_pasted(line, expected_state=state)
        except MiCliError as err:
            render.error(err.message)
            render.info("Paste again, or press Enter to scan again:")


@app.command()
def exchange(
    ctx: typer.Context,
    code_or_url: Annotated[
        str, typer.Argument(help="Authorization code, or the browser callback URL "
                                 "(paste it whole)")
    ],
) -> None:
    """Exchange an authorization code for a token.

    If the token exchange step of a login failed (e.g. a network glitch) and the
    authorization code has not expired yet, retry with this command instead of
    going through the browser again; parameters come from the last `mi auth login`.
    """
    app_ctx = _ctx(ctx)
    profile = app_ctx.profile
    pending = profile.read_pending()
    if not pending:
        raise UsageError(
            "No record of a previous login attempt; run `mi auth login` first",
        )
    result = parse_pasted(code_or_url, expected_state=pending.get("state"))
    age = int(time.time()) - int(pending.get("created_at", 0))
    if age > 600:
        render.warn(f"The previous login was started {age // 60} minutes ago; the "
                    "authorization code may have expired")
    _exchange_and_save(
        app_ctx,
        region=pending["region"],
        redirect=pending["redirect_url"],
        device_id=pending["device_id"],
        code=result.code,
    )


def _drain(
    server: CallbackServer,
    result_queue: "queue.Queue[object]",
    used: CallbackResult,
) -> None:
    """The local callback and a paste may arrive at the same time; drop the extra one."""
    while True:
        try:
            result_queue.get_nowait()
        except queue.Empty:
            return


def _open_browser(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def _try_auto_capture(
    result_queue: "queue.Queue[object]", *, no_mdns: bool
) -> tuple[CallbackServer | None, MdnsPublisher | None]:
    """Make a best effort to have homeassistant.local:8123 land on this machine. On failure, silently fall back to pasting."""
    if not port_available(const.REDIRECT_PORT):
        render.warn(
            f"{const.REDIRECT_PORT} (the callback port) is in use (is Home Assistant "
            "running on this machine?); login is only possible by pasting"
        )
        return None, None

    server: CallbackServer | None = None
    try:
        server = CallbackServer(result_queue=result_queue)
    except OSError as err:
        render.warn(f"Failed to listen on {const.REDIRECT_PORT}: {err}")
        return None, None
    server.start()

    resolved = resolve_redirect_host()
    mine = set(local_ips())
    if resolved and set(resolved) & mine:
        render.info(
            f"[dim]{const.REDIRECT_HOST} resolves to this machine ("
            f"{', '.join(resolved)})[/dim]"
        )
        return server, None
    if resolved:
        render.warn(
            f"{const.REDIRECT_HOST} resolves to {', '.join(resolved)}, which is not "
            "this machine; the callback will land on that machine"
        )
        return server, None

    if no_mdns:
        return server, None
    address = next((ip for ip in local_ips() if ip != "127.0.0.1"), "127.0.0.1")
    publisher = MdnsPublisher(address)
    failure = publisher.start()
    if failure:
        render.info(f"[dim]mDNS unavailable ({failure}); you can simply paste "
                    "instead[/dim]")
        return server, None
    render.info(f"[dim]Pointed {const.REDIRECT_HOST} at {address} via mDNS[/dim]")
    return server, publisher


@app.command()
def status(
    ctx: typer.Context,
    check: Annotated[
        bool, typer.Option("--check", help="Call the cloud API once to verify the "
                                           "token really works")
    ] = False,
    output: OutputOption = None,
) -> None:
    """Show the current login status."""
    app_ctx = _ctx(ctx)
    profile = app_ctx.profile
    auth = profile.read_auth()
    if auth is None:
        raise NotAuthenticated(f"Profile `{profile.name}` is not logged in")

    now = time.time()
    data = {
        "profile": profile.name,
        "region": f"{auth.region} ({const.CLOUD_SERVERS.get(auth.region, 'unknown')})",
        "nickname": auth.nickname or "-",
        "uid": auth.uid or "-",
        "device_id": auth.device_id,
        "access_token": mask(auth.access_token),
        "expires_in": _fmt_duration(auth.expires_at - now),
        "refresh_due": "yes" if auth.needs_refresh else "no",
        "path": str(profile.auth_path),
    }
    if check:
        with app_ctx.session() as session:
            info = session.user_profile()
            data["check"] = f"valid ({info.get('miliaoNick', '')})"
    render.output(data, pick_output(app_ctx, output))


@app.command()
def refresh(ctx: typer.Context) -> None:
    """Refresh the access_token now."""
    app_ctx = _ctx(ctx)
    with app_ctx.session() as session:
        auth = session.refresh_token(force=True)
    render.success(
        f"Refreshed; valid for about {_fmt_duration(auth.expires_at - time.time())}"
    )


@app.command()
def whoami(ctx: typer.Context, output: OutputOption = None) -> None:
    """Print the current account info (queried live)."""
    app_ctx = _ctx(ctx)
    with app_ctx.session() as session:
        info = session.user_profile()
        auth = session.auth
    render.output(
        {
            "nickname": info.get("miliaoNick") or "-",
            "uid": str(info.get("userId") or auth.uid or "-"),
            "region": auth.region,
            "profile": app_ctx.profile_name,
        },
        pick_output(app_ctx, output),
    )


@app.command()
def logout(
    ctx: typer.Context,
    purge: Annotated[
        bool, typer.Option("--purge", help="Also delete the device list and spec cache")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation")] = False,
) -> None:
    """Log out and delete the local credentials."""
    app_ctx = _ctx(ctx)
    profile = app_ctx.profile
    if not profile.exists():
        render.info("There were no login credentials to begin with")
        return
    if not yes and render.is_tty():
        target = "entire profile directory" if purge else "login credentials"
        typer.confirm(f"Delete {profile.name}'s {target}?", abort=True)
    if purge:
        profile.purge()
    else:
        profile.clear_auth()
    render.success(f"Removed the credentials of profile `{profile.name}`")


@profile_app.command("list")
def profile_list(ctx: typer.Context, output: OutputOption = None) -> None:
    """List all profiles."""
    app_ctx = _ctx(ctx)
    default = read_config(app_ctx.root).get("profile", "default")
    rows = []
    for name in list_profiles(app_ctx.root) or [default]:
        auth = Profile(name, root=app_ctx.root).read_auth()
        rows.append(
            {
                "profile": name + (" *" if name == default else ""),
                "region": auth.region if auth else "-",
                "nickname": (auth.nickname if auth else None) or "-",
                "Logged in": "yes" if auth else "no",
            }
        )
    render.output(rows, pick_output(app_ctx, output))


@profile_app.command("use")
def profile_use(ctx: typer.Context, name: str) -> None:
    """Set the default profile."""
    app_ctx = _ctx(ctx)
    config = read_config(app_ctx.root)
    config["profile"] = name
    write_config(config, app_ctx.root)
    render.success(f"Default profile set to `{name}`")


@profile_app.command("remove")
def profile_remove(
    ctx: typer.Context,
    name: str,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation")] = False,
) -> None:
    """Delete all local data of a profile."""
    app_ctx = _ctx(ctx)
    profile = Profile(name, root=app_ctx.root)
    if not profile.path.exists():
        raise UsageError(f"Profile `{name}` does not exist")
    if not yes and render.is_tty():
        typer.confirm(f"Delete all data of profile `{name}`?", abort=True)
    profile.purge()
    render.success(f"Deleted profile `{name}`")


@profile_app.command("path")
def profile_path(ctx: typer.Context) -> None:
    """Print the location of the config directory."""
    print(_ctx(ctx).root or config_dir())
