from collections.abc import (
    Sequence,
)


class BaseLibp2pError(Exception):
    pass


class ValidationError(BaseLibp2pError):
    """Raised when something does not pass a validation check."""


class ParseError(BaseLibp2pError):
    pass


class MultiError(BaseLibp2pError):
    r"""
    A combined error that wraps multiple exceptions into a single error object.
    This error is raised when multiple exceptions need to be reported together,
    typically in scenarios where parallel operations or multiple validations fail.

    Example\:
    ---------
        >>> from libp2p.exceptions import MultiError
        >>> errors = [
        ...     ValueError("Invalid input"),
        ...     TypeError("Wrong type"),
        ...     RuntimeError("Operation failed")
        ... ]
        >>> multi_error = MultiError(errors)
        >>> print(multi_error)
        Error 1: Invalid input
        Error 2: Wrong type
        Error 3: Operation failed

    Note\:
    ------
        The string representation of this error will number and list all contained
        errors sequentially, making it easier to identify individual issues in
        complex error scenarios.

    """

    def __init__(self, errors: Sequence[Exception]) -> None:
        super().__init__(errors)
        self.errors = errors  # Storing list of errors

    def __str__(self) -> str:
        return "\n".join(
            f"Error {i + 1}: {error}" for i, error in enumerate(self.errors)
        )
