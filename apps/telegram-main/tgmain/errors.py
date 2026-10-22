"""Error type shared by the presentation helpers and the Core client (kept apart to avoid an import cycle)."""


class CoreError(Exception):
    """A Core 4xx answer (or a user-level validation problem) that is shown to the user instead of being retried."""

    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code
