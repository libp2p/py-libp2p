from collections.abc import (
    Sequence,
)


class BaseLibp2pError(Exception):
    """
    Base exception for all libp2p errors.
    
    This exception serves as the root of the exception hierarchy,
    allowing users to catch all libp2p-specific errors with a single
    exception type.
    
    Example::
        >>> try:
        ...     # some libp2p operation
        ... except BaseLibp2pError as e:
        ...     print(f"Libp2p error: {e}")
    """
    
    def __init__(self, message: str = "", *args, **kwargs):
        """
        Initialize the exception.
        
        Args:
            message: Error message
            *args: Additional positional arguments
            **kwargs: Additional keyword arguments (e.g., error_code, context)
        """
        super().__init__(message, *args)
        self.message = message
        self.error_code = kwargs.get('error_code')
        self.context = kwargs.get('context', {})
    
    def __str__(self) -> str:
        """Return string representation of the error."""
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message
    
    def __repr__(self) -> str:
        """Return detailed representation of the error."""
        return f"{self.__class__.__name__}(message={self.message!r}, error_code={self.error_code!r})"


class ValidationError(BaseLibp2pError):
    """Raised when something does not pass a validation check."""


class ParseError(BaseLibp2pError):
    """Raised when parsing fails."""
    pass


# Intermediate base classes for logical grouping of exceptions

class NetworkError(BaseLibp2pError):
    """
    Base exception for network-related errors.
    
    This includes errors related to connections, streams, transport,
    and network operations.
    """
    pass


class ProtocolError(BaseLibp2pError):
    """
    Base exception for protocol-related errors.
    
    This includes errors related to protocol negotiation, protocol
    violations, and protocol-specific errors.
    """
    pass


class PeerError(BaseLibp2pError):
    """
    Base exception for peer-related errors.
    
    This includes errors related to peer store, peer data, peer
    addresses, and peer serialization.
    """
    pass


class ResourceError(BaseLibp2pError):
    """
    Base exception for resource management errors.
    
    This includes errors related to resource limits, resource
    allocation, and resource monitoring.
    """
    pass


class ServiceError(BaseLibp2pError):
    """
    Base exception for service lifecycle errors.
    
    This includes errors related to service management, service
    lifecycle, and service operations.
    """
    pass


class DiscoveryError(BaseLibp2pError):
    """
    Base exception for discovery-related errors.
    
    This includes errors related to peer discovery, rendezvous,
    and routing table operations.
    """
    pass


class PubsubError(BaseLibp2pError):
    """
    Base exception for pubsub-related errors.
    
    This includes errors related to pubsub routers, pubsub
    operations, and pubsub protocols.
    """
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
