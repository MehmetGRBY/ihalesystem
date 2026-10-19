class CollectionError(Exception):
    """Expected source failure with a safe, secret-free error category."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
