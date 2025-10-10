"""
Tests for resource manager exceptions.
"""

import pytest

from libp2p.rcmgr.exceptions import (
    InvalidResourceManagerState,
    ResourceLimitExceeded,
    ResourceManagerException,
    ScopeClosedException,
)


def test_resource_manager_exception():
    """Test base ResourceManagerException."""
    msg = "Test error message"
    exc = ResourceManagerException(msg)

    assert str(exc) == msg
    assert isinstance(exc, Exception)


def test_resource_limit_exceeded():
    """Test ResourceLimitExceeded exception."""
    scope_name = "test_scope"
    resource_type = "memory"
    requested = 2048
    available = 1024

    # Test with all parameters
    exc = ResourceLimitExceeded(scope_name, resource_type, requested, available)

    assert exc.scope_name == scope_name
    assert exc.resource_type == resource_type
    assert exc.requested == requested
    assert exc.available == available

    # Check message format
    expected_msg = f"Resource limit exceeded in scope '{scope_name}': requested {requested} {resource_type}, available {available}"
    assert str(exc) == expected_msg

    # Test inheritance
    assert isinstance(exc, ResourceManagerException)


def test_resource_limit_exceeded_simple():
    """Test ResourceLimitExceeded with simple message."""
    msg = "Stream limit exceeded"
    exc = ResourceLimitExceeded(message=msg)

    assert str(exc) == msg
    assert exc.scope_name is None
    assert exc.resource_type is None
    assert exc.requested is None
    assert exc.available is None


def test_scope_closed_exception():
    """Test ScopeClosedException."""
    scope_name = "closed_scope"
    exc = ScopeClosedException(scope_name)

    assert exc.scope_name == scope_name

    expected_msg = f"Operation attempted on closed scope: {scope_name}"
    assert str(exc) == expected_msg

    # Test inheritance
    assert isinstance(exc, ResourceManagerException)


def test_scope_closed_exception_simple():
    """Test ScopeClosedException with simple message."""
    msg = "Scope is closed"
    exc = ScopeClosedException(message=msg)

    assert str(exc) == msg
    assert exc.scope_name is None


def test_invalid_resource_manager_state():
    """Test InvalidResourceManagerState exception."""
    msg = "ResourceManager is in invalid state"
    exc = InvalidResourceManagerState(msg)

    assert str(exc) == msg

    # Test inheritance
    assert isinstance(exc, ResourceManagerException)


def test_exception_chaining():
    """Test exception chaining and context."""
    original_error = ValueError("Original error")

    try:
        raise original_error
    except ValueError as e:
        # Chain with resource manager exception
        rm_error = ResourceManagerException("Resource manager error")
        rm_error.__cause__ = e

        assert rm_error.__cause__ is e
        assert str(rm_error.__cause__) == "Original error"


def test_resource_limit_exceeded_usage_pattern():
    """Test typical usage pattern for ResourceLimitExceeded."""
    def check_memory_limit(scope_name: str, requested: int, available: int):
        if requested > available:
            raise ResourceLimitExceeded(
                scope_name=scope_name,
                resource_type="memory",
                requested=requested,
                available=available
            )

    # Should not raise
    check_memory_limit("test", 1024, 2048)

    # Should raise
    with pytest.raises(ResourceLimitExceeded) as exc_info:
        check_memory_limit("test", 2048, 1024)

    exc = exc_info.value
    assert exc.scope_name == "test"
    assert exc.resource_type == "memory"
    assert exc.requested == 2048
    assert exc.available == 1024


def test_scope_closed_usage_pattern():
    """Test typical usage pattern for ScopeClosedException."""
    class MockScope:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def close(self):
            self.closed = True

        def reserve_memory(self, amount):
            if self.closed:
                raise ScopeClosedException(self.name)
            return amount

    scope = MockScope("test_scope")

    # Should work normally
    assert scope.reserve_memory(1024) == 1024

    # Close scope
    scope.close()

    # Should raise exception
    with pytest.raises(ScopeClosedException) as exc_info:
        scope.reserve_memory(1024)

    assert exc_info.value.scope_name == "test_scope"


def test_exception_attributes():
    """Test exception attribute access."""
    # ResourceLimitExceeded with all attributes
    exc1 = ResourceLimitExceeded("scope1", "streams", 10, 5)
    assert hasattr(exc1, 'scope_name')
    assert hasattr(exc1, 'resource_type')
    assert hasattr(exc1, 'requested')
    assert hasattr(exc1, 'available')

    # ScopeClosedException with scope name
    exc2 = ScopeClosedException("scope2")
    assert hasattr(exc2, 'scope_name')

    # Base exception
    exc3 = ResourceManagerException("test")
    assert str(exc3) == "test"


def test_exception_representation():
    """Test exception string representation."""
    # Test ResourceLimitExceeded repr
    exc1 = ResourceLimitExceeded("test_scope", "connections", 100, 50)
    repr_str = repr(exc1)
    assert "ResourceLimitExceeded" in repr_str
    assert "test_scope" in repr_str

    # Test ScopeClosedException repr
    exc2 = ScopeClosedException("closed_scope")
    repr_str = repr(exc2)
    assert "ScopeClosedException" in repr_str
    assert "closed_scope" in repr_str


def test_exception_equality():
    """Test exception equality comparison."""
    # Same exceptions should be equal
    exc1a = ResourceLimitExceeded("scope", "memory", 1024, 512)
    exc1b = ResourceLimitExceeded("scope", "memory", 1024, 512)

    # Note: Exception equality typically compares by identity, not content
    # This test documents the behavior
    assert exc1a is not exc1b

    # But they should have same string representation
    assert str(exc1a) == str(exc1b)


def test_multiple_exception_types():
    """Test catching different exception types."""
    def problematic_function(error_type):
        if error_type == "limit":
            raise ResourceLimitExceeded("scope", "streams", 10, 5)
        elif error_type == "closed":
            raise ScopeClosedException("scope")
        elif error_type == "state":
            raise InvalidResourceManagerState("Bad state")
        else:
            raise ResourceManagerException("Generic error")

    # Test catching specific exceptions
    with pytest.raises(ResourceLimitExceeded):
        problematic_function("limit")

    with pytest.raises(ScopeClosedException):
        problematic_function("closed")

    with pytest.raises(InvalidResourceManagerState):
        problematic_function("state")

    # Test catching base exception
    with pytest.raises(ResourceManagerException):
        problematic_function("generic")

    # Test catching all resource manager exceptions
    for error_type in ["limit", "closed", "state", "generic"]:
        with pytest.raises(ResourceManagerException):
            problematic_function(error_type)


def test_exception_context_manager():
    """Test exceptions in context managers."""
    class ResourceScope:
        def __init__(self, name):
            self.name = name
            self.closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.closed = True

        def use_resource(self):
            if self.closed:
                raise ScopeClosedException(self.name)

    # Normal usage should work
    with ResourceScope("test") as scope:
        pass  # Scope is automatically closed

    # Using closed scope should raise
    scope = ResourceScope("test")
    with scope:
        pass

    with pytest.raises(ScopeClosedException):
        scope.use_resource()
