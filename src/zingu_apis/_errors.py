"""Exception types for zingu-apis."""


class FetchError(Exception):
    """Raised by fetch() when strict=True and errors are encountered."""

    def __init__(self, errors: list[str], result: dict):
        self.errors = errors
        self.result = result
        super().__init__("; ".join(errors))
