"""Custom errors for a JVC Projector."""


class JvcProjectorError(Exception):
    """Projector Error."""


class JvcProjectorConnectError(JvcProjectorError):
    """Projector could not be reached (refused, unreachable, closed, DNS)."""


class JvcProjectorCommandError(JvcProjectorError):
    """Projector answered with something unexpected."""


class JvcProjectorTimeoutError(JvcProjectorCommandError):
    """Projector did not answer a command in time.

    The connection is dropped when this is raised, so a late answer can never be
    read as the reply to the next command.
    """


class JvcProjectorAuthError(JvcProjectorError):
    """Projector Password Invalid Error."""

    def __init__(self, message: str | None = None) -> None:
        """Initialize the auth error with a helpful message."""
        if message is None:
            message = "Projector rejected the password"
        super().__init__(message)
