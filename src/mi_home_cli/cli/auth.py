"""`mi auth` / `mi profile` 命令。"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import webbrowser
from typing import Annotated, Optional

import typer

from ..i18n import t
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

app = typer.Typer(help=t("登录与凭据管理"), no_args_is_help=True)
profile_app = typer.Typer(help=t("多账号/多区域配置"), no_args_is_help=True)


def _ctx(ctx: typer.Context) -> AppContext:
    return ctx.obj


def _fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 0:
        return t("已过期")
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return t("{days} 天 {hours} 小时", days=days, hours=hours)
    if hours:
        return t("{hours} 小时 {minutes} 分", hours=hours, minutes=minutes)
    return t("{minutes} 分", minutes=minutes)


_STDIN_EOF = "__stdin_eof__"


def _collect_code(
    *,
    server: CallbackServer | None,
    result_queue: "queue.Queue[object]",
    expected_state: str,
    wait_seconds: float,
) -> CallbackResult:
    """等回调或等用户粘贴，谁先来算谁。"""
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
                render.info(t("再试一次，或按 Ctrl-C 退出："))

    threading.Thread(target=read_stdin, name="mi-paste", daemon=True).start()

    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stop.set()
            raise MiCliError(
                t("等待授权超时（{v0} 秒）", v0=int(wait_seconds)),
                hint=t("用 `mi auth login --manual` 手工粘贴回调地址"),
            )
        try:
            item = result_queue.get(timeout=min(1.0, remaining))
        except queue.Empty:
            continue
        if item is _STDIN_EOF:
            if server is None:
                stop.set()
                raise UsageError(
                    t("标准输入已结束，也没有本地回调可用；请在交互式终端里运行，或用管道传入回调地址")
                )
            # 还有本地回调这条路，继续等。
            continue
        result: CallbackResult = item  # type: ignore[assignment]
        stop.set()
        if result.source == "server":
            # 本地回调一定带 state，不匹配就是别人打过来的请求，直接拒。
            if result.state != expected_state:
                raise MiCliError(
                    t("回调的 state 与本次登录不符，已忽略"),
                    hint=t("请重新执行 `mi auth login`"),
                )
        elif result.state and result.state != expected_state:
            raise MiCliError(t("state 不匹配，可能不是本次登录的回调，请重新登录"))
        elif not result.state:
            render.warn(t("粘贴的内容里没有 state，跳过校验"))
        return result


@app.command()
def login(
    ctx: typer.Context,
    region: Annotated[
        Optional[str], typer.Option("--region", "-r", help=t("区域：") + "/".join(const.CLOUD_SERVERS))
    ] = None,
    scan: Annotated[
        bool,
        typer.Option(
            "--scan", help=t("用小米账号扫码登录（终端显示二维码，无需浏览器）")
        ),
    ] = False,
    manual: Annotated[
        bool, typer.Option("--manual", help=t("不监听端口，只手工粘贴回调地址"))
    ] = False,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help=t("不自动打开浏览器"))
    ] = False,
    no_mdns: Annotated[
        bool, typer.Option("--no-mdns", help=t("不广播 mDNS"))
    ] = False,
    redirect_url: Annotated[
        Optional[str],
        typer.Option(
            "--redirect-url",
            help=t("自定义 redirect_uri（host 必须是 homeassistant.local:8123）"),
        ),
    ] = None,
    device_id: Annotated[
        Optional[str], typer.Option("--device-id", help=t("自定义 device_id（排查用）"))
    ] = None,
    wait: Annotated[
        float, typer.Option("--wait", help=t("等待授权的秒数"))
    ] = 300.0,
    skip_confirm: Annotated[
        bool, typer.Option("--skip-confirm", help=t("已授权过则跳过确认页"))
    ] = False,
) -> None:
    """用小米账号登录。"""
    app_ctx = _ctx(ctx)
    region = region or app_ctx.resolved_region()
    if region not in const.CLOUD_SERVERS:
        raise UsageError(
            t("未知区域 `{region}`，可选：{v0}", region=region, v0=t('、').join(const.CLOUD_SERVERS))
        )

    profile = app_ctx.profile
    identity = profile.identity(region)
    redirect = redirect_url or identity.redirect_url
    if not redirect.startswith(const.REDIRECT_ORIGIN):
        render.warn(
            t(
                "redirect_uri 的 host 不是 {REDIRECT_HOST}:{REDIRECT_PORT}，小米服务端会拒绝（invalid redirect uri）",
                REDIRECT_HOST=const.REDIRECT_HOST,
                REDIRECT_PORT=const.REDIRECT_PORT,
            )
        )
    device_id = device_id or identity.device_id
    # state 用 HA 的算法，纯粹是为了少一个和上游不一致的变量。
    state = state_for_device(device_id)
    # 先落盘，换 token 失败时还能用 `mi auth exchange` 拿同一个 code 重试。
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
        render.info(t("[bold]1.[/bold] 在浏览器里打开下面的链接，用小米账号登录并授权："))
        render.raw(auth_url)
        if not no_browser and not _open_browser(auth_url):
            render.warn(t("没能自动打开浏览器，请手工复制上面的链接"))
        if server:
            render.info(
                t(
                    "[bold]2.[/bold] 授权后浏览器会跳回 {redirect}，本机已在 8123 端口等着接收。",
                    redirect=redirect,
                )
            )
            render.info(
                t(
                    "[bold]3.[/bold] 如果那个页面打不开（说明 homeassistant.local 没指向本机），把浏览器地址栏里的整段地址粘到这里回车：",
                )
            )
        else:
            render.info(
                t("[bold]2.[/bold] 授权后浏览器会跳到 {redirect}，这个地址多半打不开——没关系，", redirect=redirect)
            )
            render.info(
                t("[bold]3.[/bold] 直接把浏览器地址栏里的整段地址粘到这里回车：")
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
        t(
            "拿到授权码（来自{v0}），正在换取 token…",
            v0=t('本地回调') if result.source == 'server' else t('粘贴'),
        )
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
        # 换 token 失败时授权码通常还没被消耗，别让用户白跑一遍浏览器。
        render.error(err.message)
        if err.hint:
            render.info(t("[dim]提示：{hint}[/dim]", hint=err.hint))
        render.info(t("授权码还在有效期内的话可以直接重试："))
        render.raw(f"  mi -v auth exchange {result.code}")
        raise typer.Exit(code=err.exit_code) from err


def _exchange_and_save(
    app_ctx: AppContext, *, region: str, redirect: str, device_id: str, code: str
) -> None:
    """用授权码换 token 并落盘。

    授权、换 token 两步里的 client_id / redirect_uri / device_id 必须完全一致，
    否则服务端返回 96002 invalid request。
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
            render.warn(t("账号信息获取失败（不影响登录）：{message}", message=err.message))

    profile.write_auth(auth)
    profile.clear_pending()
    render.success(
        t(
            "登录成功：{v0}（uid {v1}，区域 {region}，profile {name}）",
            v0=auth.nickname or t('未知昵称'),
            v1=auth.uid or t('未知'),
            region=region,
            name=profile.name,
        )
    )
    render.info(t("凭据已保存到 {auth_path}（权限 0600）", auth_path=profile.auth_path))
    render.info(
        t("有效期约 {v0}，到期前会自动续期", v0=_fmt_duration(auth.expires_at - time.time()))
    )


_SCAN_MAX_ATTEMPTS = 3


def _scan_user_agent(app_ctx: AppContext) -> str:
    """扫码登录用的 User-Agent，决定小米「登录设备」里显示的名字。

    优先级：环境变量 MI_SCAN_DEVICE_NAME > 配置 scan_device_name > 默认工具名。
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
        # HTTP 头只能 Latin-1，带不了中文；回退默认，别让登录直接崩。
        render.warn(
            t("scan_device_name `{name}` 含非 ASCII 字符，无法作为设备名，已用默认名", name=name)
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
    """扫码登录：终端显示二维码，用小米 App 扫码确认后自动拿 code 换 token。

    首次授权常因为要手动点「同意并关联」而自动拿不到 code / 换 token 失败；这时
    退回到用**原始授权链接**（浏览器打开，或手机扫二维码）手动登录授权一次，完成
    后既可以把浏览器回调地址粘回来直接换 token，也可以直接回车重新扫码（此时授权
    已记住，`skip_confirm` 生效，不用再点）。
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
                render.info(t("[dim]提示：{hint}[/dim]", hint=err.hint))
            # 非交互（管道里）或重试次数用尽：只打印手动授权引导，然后退出。
            if not render.is_tty() or attempt >= _SCAN_MAX_ATTEMPTS:
                _scan_guide_manual(
                    redirect=redirect, device_id=device_id, state=state, prompt=False
                )
                raise typer.Exit(code=err.exit_code) from err
            # 交互式恢复：引导手动授权。粘回调 → 直接换 token；回车 → 重新扫码。
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
            render.info(t("好，重新生成扫码二维码…"))


def _scan_capture_code(
    app_ctx: AppContext,
    *,
    redirect: str,
    device_id: str,
    state: str,
    wait: float,
    trace,
) -> CallbackResult:
    """走一次扫码：显示二维码 → 等手机确认 → 从跳转链取出 code。"""
    render.info("")
    render.info(t("[bold]正在获取二维码…[/bold]"))
    with QrLoginClient(
        redirect_url=redirect,
        device_id=device_id,
        state=state,
        # 固定的 web deviceId：避免每次扫码都在小米账号里多登记一台设备。
        web_device_id=app_ctx.profile.web_device_id(),
        # 决定小米「登录设备」里显示的名字（默认工具名，可自定义）。
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
            # 半块二维码若有横纹/发虚，通常是终端「行距(line spacing)」留了缝，
            # 调到 1.0 即为实心；实在不行用下面的图片链接，一样扫。
            render.info(
                t("[dim]二维码有横纹或发虚？把终端行距（line spacing）调到 1.0 就实心了；或直接用下面的图片链接。[/dim]")
            )
        else:
            render.warn(t("无法在终端里渲染二维码，请改用下面的图片链接扫码。"))
        render.info("")
        render.info(
            t("[bold]用小米 App 扫码：[/bold]我的 → 点右上角扫一扫（或设置 → 小米账号），扫码后在手机上点「确认登录」。")
        )
        render.info(
            t("[dim]首次登录还会弹一个授权页，点「同意并关联 / Agree and link」授权即可（以后再扫就免了）；点完这里会自动继续。[/dim]")
        )
        # 终端渲染受字体/行距影响不一定扫得出，始终附上图片链接兜底，别让人卡死。
        if challenge.qr_image_url:
            render.info(
                t("[dim]终端里的二维码扫不出？用浏览器打开这个地址看图再扫：[/dim]")
            )
            render.raw(challenge.qr_image_url)
        render.info(
            t("[dim]也可以把下面这段地址自行转成二维码后扫：[/dim]")
        )
        render.raw(challenge.login_url)
        render.info(
            t("[dim]二维码有效期约 {v0} 秒，正在等待确认…[/dim]", v0=int(challenge.timeout))
        )

        deadline = time.monotonic() + min(wait, float(challenge.timeout))
        location = client.poll(challenge, deadline=deadline)
        render.info(t("扫码已确认，正在换取 token…"))
        return client.resolve_code(location)


def _scan_guide_manual(
    *, redirect: str, device_id: str, state: str, prompt: bool
) -> Optional[CallbackResult]:
    """扫码没走通时的兜底：给出**原始授权链接**（+二维码）让用户手动登录授权。

    `prompt=True`（交互式）会等用户输入：粘贴浏览器回调地址就解析出 code 返回；
    直接回车返回 None（表示回去重新扫码）。`prompt=False` 只打印引导、返回 None。
    授权链接用 `skip_confirm=false`，确保首次能看到并点掉「同意并关联」。
    """
    auth_url = build_auth_url(
        redirect_url=redirect, device_id=device_id, state=state, skip_confirm=False
    )
    render.info("")
    render.warn(t("没能自动完成扫码授权（首次登录往往要手动点一次「同意并关联」）。"))
    render.info(t("用浏览器打开下面这个地址，登录小米账号并点「同意并关联」完成授权："))
    render.raw(auth_url)
    qr = render_qr(auth_url)
    if qr:
        render.info(t("[dim]或用手机扫这个二维码打开上面的页面：[/dim]"))
        render.raw(qr)

    if not prompt:
        render.info("")
        render.info(t("授权完成后，重新运行 `mi auth login --scan` 即可（这次不用再授权）。"))
        return None

    render.info("")
    render.info(
        t("完成后二选一：把浏览器跳转后地址栏里的整段地址粘到这里回车立刻换 token，或直接回车让我重新生成扫码二维码（Ctrl-C 取消）：")
    )
    while True:
        try:
            line = sys.stdin.readline()
        except (OSError, ValueError):
            return None
        if not line:  # EOF
            return None
        line = line.strip()
        if not line:  # 直接回车 → 回去重新扫码
            return None
        try:
            return parse_pasted(line, expected_state=state)
        except MiCliError as err:
            render.error(err.message)
            render.info(t("再粘一次，或直接回车重新扫码："))


@app.command()
def exchange(
    ctx: typer.Context,
    code_or_url: Annotated[
        str, typer.Argument(help=t("授权码，或浏览器回调地址（整段粘贴）"))
    ],
) -> None:
    """用授权码换 token。

    登录时换 token 那一步失败（比如网络抖动）而授权码还没过期时，可以用这个
    命令重试，不必再走一遍浏览器；参数取自上一次 `mi auth login` 的记录。
    """
    app_ctx = _ctx(ctx)
    profile = app_ctx.profile
    pending = profile.read_pending()
    if not pending:
        raise UsageError(
            t("没有找到上一次登录的记录，先执行 `mi auth login`"),
        )
    result = parse_pasted(code_or_url, expected_state=pending.get("state"))
    age = int(time.time()) - int(pending.get("created_at", 0))
    if age > 600:
        render.warn(t("上一次登录是 {v0} 分钟前发起的，授权码可能已过期", v0=age // 60))
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
    """本地回调和粘贴可能同时到达，丢掉多余的那份。"""
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
    """尽力让 homeassistant.local:8123 落到本机。失败就静默回退到粘贴。"""
    if not port_available(const.REDIRECT_PORT):
        render.warn(
            t(
                "{REDIRECT_PORT} 端口被占用（本机在跑 Home Assistant？），只能用粘贴方式登录",
                REDIRECT_PORT=const.REDIRECT_PORT,
            )
        )
        return None, None

    server: CallbackServer | None = None
    try:
        server = CallbackServer(result_queue=result_queue)
    except OSError as err:
        render.warn(
            t(
                "监听 {REDIRECT_PORT} 失败：{err}",
                REDIRECT_PORT=const.REDIRECT_PORT,
                err=err,
            )
        )
        return None, None
    server.start()

    resolved = resolve_redirect_host()
    mine = set(local_ips())
    if resolved and set(resolved) & mine:
        render.info(
            t(
                "[dim]{REDIRECT_HOST} 已解析到本机（{v0}）[/dim]",
                REDIRECT_HOST=const.REDIRECT_HOST,
                v0=', '.join(resolved),
            )
        )
        return server, None
    if resolved:
        render.warn(
            t(
                "{REDIRECT_HOST} 解析到 {v0}，不是本机；回调会落到那台机器上",
                REDIRECT_HOST=const.REDIRECT_HOST,
                v0=', '.join(resolved),
            )
        )
        return server, None

    if no_mdns:
        return server, None
    address = next((ip for ip in local_ips() if ip != "127.0.0.1"), "127.0.0.1")
    publisher = MdnsPublisher(address)
    failure = publisher.start()
    if failure:
        render.info(t("[dim]mDNS 不可用（{failure}），可以直接用粘贴方式[/dim]", failure=failure))
        return server, None
    render.info(
        t(
            "[dim]已通过 mDNS 把 {REDIRECT_HOST} 指向 {address}[/dim]",
            REDIRECT_HOST=const.REDIRECT_HOST,
            address=address,
        )
    )
    return server, publisher


@app.command()
def status(
    ctx: typer.Context,
    check: Annotated[
        bool, typer.Option("--check", help=t("调用一次云端接口验证 token 是否真的有效"))
    ] = False,
    output: OutputOption = None,
) -> None:
    """查看当前登录状态。"""
    app_ctx = _ctx(ctx)
    profile = app_ctx.profile
    auth = profile.read_auth()
    if auth is None:
        raise NotAuthenticated(t("profile `{name}` 尚未登录", name=profile.name))

    now = time.time()
    data = {
        "profile": profile.name,
        "region": t(
            "{region}（{v0}）",
            region=auth.region,
            v0=const.CLOUD_SERVERS.get(auth.region, t('未知')),
        ),
        "nickname": auth.nickname or "-",
        "uid": auth.uid or "-",
        "device_id": auth.device_id,
        "access_token": mask(auth.access_token),
        "expires_in": _fmt_duration(auth.expires_at - now),
        "refresh_due": t("是") if auth.needs_refresh else t("否"),
        "path": str(profile.auth_path),
    }
    if check:
        with app_ctx.session() as session:
            info = session.user_profile()
            data["check"] = t("有效（{v0}）", v0=info.get('miliaoNick', ''))
    render.output(data, pick_output(app_ctx, output))


@app.command()
def refresh(ctx: typer.Context) -> None:
    """立刻刷新 access_token。"""
    app_ctx = _ctx(ctx)
    with app_ctx.session() as session:
        auth = session.refresh_token(force=True)
    render.success(
        t("已刷新，有效期约 {v0}", v0=_fmt_duration(auth.expires_at - time.time()))
    )


@app.command()
def whoami(ctx: typer.Context, output: OutputOption = None) -> None:
    """打印当前账号信息（实时查询）。"""
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
        bool, typer.Option("--purge", help=t("连同设备清单、spec 缓存一起删除"))
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help=t("不询问"))] = False,
) -> None:
    """退出登录，删除本地凭据。"""
    app_ctx = _ctx(ctx)
    profile = app_ctx.profile
    if not profile.exists():
        render.info(t("本来就没有登录信息"))
        return
    if not yes and render.is_tty():
        target = t("整个 profile 目录") if purge else t("登录凭据")
        typer.confirm(
            t("确认删除 {name} 的{target}？", name=profile.name, target=target),
            abort=True,
        )
    if purge:
        profile.purge()
    else:
        profile.clear_auth()
    render.success(t("已清除 profile `{name}` 的凭据", name=profile.name))


@profile_app.command("list")
def profile_list(ctx: typer.Context, output: OutputOption = None) -> None:
    """列出所有 profile。"""
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
                "已登录": t("是") if auth else t("否"),
            }
        )
    render.output(rows, pick_output(app_ctx, output))


@profile_app.command("use")
def profile_use(ctx: typer.Context, name: str) -> None:
    """设置默认 profile。"""
    app_ctx = _ctx(ctx)
    config = read_config(app_ctx.root)
    config["profile"] = name
    write_config(config, app_ctx.root)
    render.success(t("默认 profile 已设为 `{name}`", name=name))


@profile_app.command("remove")
def profile_remove(
    ctx: typer.Context,
    name: str,
    yes: Annotated[bool, typer.Option("--yes", "-y", help=t("不询问"))] = False,
) -> None:
    """删除一个 profile 的全部本地数据。"""
    app_ctx = _ctx(ctx)
    profile = Profile(name, root=app_ctx.root)
    if not profile.path.exists():
        raise UsageError(t("profile `{name}` 不存在", name=name))
    if not yes and render.is_tty():
        typer.confirm(t("确认删除 profile `{name}` 的全部数据？", name=name), abort=True)
    profile.purge()
    render.success(t("已删除 profile `{name}`", name=name))


@profile_app.command("path")
def profile_path(ctx: typer.Context) -> None:
    """打印配置目录位置。"""
    print(_ctx(ctx).root or config_dir())
