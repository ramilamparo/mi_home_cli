"""Global context shared between commands."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..core import const
from ..core.session import Session
from ..render import OutputFormat
from ..store import Profile, config_dir, read_config


@dataclass
class AppContext:
    profile_name: str
    output: OutputFormat
    timeout: float
    verbose: bool
    quiet: bool
    region: str | None
    root: Path
    dry_run: bool = False
    all_homes: bool = False
    verify: bool = False
    # Default to the cloud: the LAN needs a liveness probe first and a fallback on
    # failure, and the wait of the first hit would all land on the user. Those who
    # want low latency pick auto/lan explicitly, or `mi config set channel auto`.
    channel: str = "cloud"

    @property
    def profile(self) -> Profile:
        return Profile(self.profile_name, root=self.root)

    def session(self) -> Session:
        return Session(self.profile, region=self.region, timeout=self.timeout)

    def default_home(self) -> dict[str, str] | None:
        """The default home set in the config; `--all-homes` ignores it temporarily."""
        if self.all_homes:
            return None
        home = read_config(self.root).get("home")
        if isinstance(home, dict) and home.get("id"):
            return home
        return None

    def home_filter(self) -> dict[str, str]:
        """The home filter fed to Registry.filter / resolve."""
        home = self.default_home()
        return {"home_id": home["id"]} if home else {}

    def resolved_region(self) -> str:
        """Command line > logged-in profile > config file > cn."""
        if self.region:
            return self.region
        auth = self.profile.read_auth()
        if auth:
            return auth.region
        return read_config(self.root).get("region", const.DEFAULT_REGION)


def default_profile_name(root: Path | None = None) -> str:
    return read_config(root or config_dir()).get("profile", "default")


# -o on subcommands: when omitted, the global value is used. click groups only
# accept global options before the subcommand, but `mi auth status -o json` is
# the more natural way to write it, so it is declared once more here.
OutputOption = Annotated[
    Optional[OutputFormat],
    typer.Option("--output", "-o", envvar="MI_OUTPUT", help="Output format"),
]


def pick_output(
    ctx: AppContext,
    override: OutputFormat | None,
    default: OutputFormat | None = None,
) -> OutputFormat:
    """-o on the subcommand wins; without it the global value is used.

    default is for commands where a table makes no sense (such as spec dump); there
    the global value is only respected if the user explicitly passed a global -o.
    """
    if override:
        return override
    if default and ctx.output is OutputFormat.table:
        return default
    return ctx.output


# The two write switches are likewise declared again on subcommands.
# `mi set lamp on=true --dry-run` is what anyone (and any agent) would naturally
# write; only allowing them before the subcommand would be counter-intuitive.
DryRunOption = Annotated[
    Optional[bool],
    typer.Option("--dry-run/--no-dry-run", help="Parse and validate only; do not send "
                                                "anything"),
]
VerifyOption = Annotated[
    Optional[bool],
    typer.Option("--verify/--no-verify", help="Read back after writing to confirm the "
                                              "real state"),
]


def apply_write_flags(
    ctx: AppContext, dry_run: bool | None = None, verify: bool | None = None
) -> AppContext:
    """Switches on the subcommand override the global values."""
    if dry_run is not None:
        ctx.dry_run = dry_run
    if verify is not None:
        ctx.verify = verify
    return ctx
