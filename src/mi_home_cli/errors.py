"""Unified error types and exit codes.

For the exit code conventions see docs/design.md §5.
"""
from __future__ import annotations


class MiCliError(Exception):
    """Base class of all expected errors; carries an exit code.

    The exit code travels with the exception itself; main() in cli/app.py prints the
    error and exits with it. (It does not inherit from click's exceptions: since typer
    0.27 click is vendored as a private module.)
    """

    exit_code: int = 1

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class UsageError(MiCliError):
    exit_code = 2


class DeviceNotFound(MiCliError):
    exit_code = 3


class AmbiguousReference(MiCliError):
    exit_code = 4


class DeviceOffline(MiCliError):
    exit_code = 5


class SpecNotFound(MiCliError):
    exit_code = 6


class InvalidValue(MiCliError):
    exit_code = 7


class NetworkError(MiCliError):
    exit_code = 8


class CloudError(MiCliError):
    """The cloud returned a non-zero code."""

    exit_code = 9

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        description: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message, hint=hint)
        self.code = code
        self.description = description


class NotAuthenticated(MiCliError):
    exit_code = 10

    def __init__(
        self,
        message: str = "Not logged in, or the login has expired",
        *,
        hint: str | None = "Run `mi auth login` to log in again",
    ) -> None:
        super().__init__(message, hint=hint)
