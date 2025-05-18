from typing import (
    Any,
)


class BaseLibp2pError(Exception):
    pass


class ValidationError(BaseLibp2pError):
    """Raised when something does not pass a validation check."""


class ParseError(BaseLibp2pError):
    pass


class MultiError(BaseLibp2pError):
    """Raised with multiple exceptions."""

    def __init__(self, errors: list[Any]) -> None:
        super().__init__(errors)
        self.errors = errors  # Storing list of errors

    def __str__(self) -> str:
        return "\n".join(
            f"Error {i + 1}: {error}" for i, error in enumerate(self.errors)
        )
