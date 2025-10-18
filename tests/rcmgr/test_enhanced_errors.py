"""
Tests for enhanced error types implementation.

This module contains comprehensive tests for the enhanced error types,
including error codes, categories, severity levels, and error context building.
"""

import time

import pytest

from libp2p.peer.id import ID
from libp2p.rcmgr.enhanced_errors import (
    ConfigurationError,
    ErrorCategory,
    ErrorCode,
    ErrorContext,
    ErrorSeverity,
    OperationalError,
    ResourceLimitExceededError,
    SystemResourceError,
    create_configuration_error,
    create_connection_limit_error,
    create_memory_limit_error,
    create_operational_error,
)


class TestErrorEnums:
    """Test error enums."""

    def test_error_severity_values(self) -> None:
        """Test ErrorSeverity enum values."""
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"

    def test_error_category_values(self) -> None:
        """Test ErrorCategory enum values."""
        assert ErrorCategory.CONNECTION_LIMIT.value == "connection_limit"
        assert ErrorCategory.MEMORY_LIMIT.value == "memory_limit"
        assert ErrorCategory.STREAM_LIMIT.value == "stream_limit"
        assert ErrorCategory.PEER_LIMIT.value == "peer_limit"
        assert ErrorCategory.PROTOCOL_LIMIT.value == "protocol_limit"
        assert ErrorCategory.SYSTEM_ERROR.value == "system_error"
        assert ErrorCategory.NETWORK_ERROR.value == "network_error"
        assert ErrorCategory.TRANSPORT_ERROR.value == "transport_error"
        assert ErrorCategory.PROTOCOL_ERROR.value == "protocol_error"
        assert ErrorCategory.CONFIG_ERROR.value == "config_error"
        assert ErrorCategory.VALIDATION_ERROR.value == "validation_error"
        assert ErrorCategory.OPERATIONAL_ERROR.value == "operational_error"
        assert ErrorCategory.MONITORING_ERROR.value == "monitoring_error"
        assert ErrorCategory.LIFECYCLE_ERROR.value == "lifecycle_error"

    def test_error_code_values(self) -> None:
        """Test ErrorCode enum values."""
        assert ErrorCode.CONNECTION_LIMIT_EXCEEDED.value == "CONN_001"
        assert ErrorCode.CONNECTION_PENDING_LIMIT_EXCEEDED.value == "CONN_002"
        assert ErrorCode.CONNECTION_ESTABLISHED_LIMIT_EXCEEDED.value == "CONN_003"
        assert ErrorCode.CONNECTION_PER_PEER_LIMIT_EXCEEDED.value == "CONN_004"
        assert ErrorCode.CONNECTION_TOTAL_LIMIT_EXCEEDED.value == "CONN_005"
        assert ErrorCode.MEMORY_LIMIT_EXCEEDED.value == "MEM_001"
        assert ErrorCode.MEMORY_PROCESS_LIMIT_EXCEEDED.value == "MEM_002"
        assert ErrorCode.MEMORY_SYSTEM_LIMIT_EXCEEDED.value == "MEM_003"
        assert ErrorCode.MEMORY_MONITORING_FAILED.value == "MEM_004"
        assert ErrorCode.STREAM_LIMIT_EXCEEDED.value == "STR_001"
        assert ErrorCode.STREAM_PER_CONNECTION_LIMIT_EXCEEDED.value == "STR_002"
        assert ErrorCode.STREAM_PER_PEER_LIMIT_EXCEEDED.value == "STR_003"
        assert ErrorCode.STREAM_TOTAL_LIMIT_EXCEEDED.value == "STR_004"
        assert ErrorCode.PEER_LIMIT_EXCEEDED.value == "PEER_001"
        assert ErrorCode.PEER_CONNECTION_LIMIT_EXCEEDED.value == "PEER_002"
        assert ErrorCode.PEER_STREAM_LIMIT_EXCEEDED.value == "PEER_003"
        assert ErrorCode.PROTOCOL_LIMIT_EXCEEDED.value == "PROT_001"
        assert ErrorCode.PROTOCOL_STREAM_LIMIT_EXCEEDED.value == "PROT_002"
        assert ErrorCode.PROTOCOL_RATE_LIMIT_EXCEEDED.value == "PROT_003"
        assert ErrorCode.SYSTEM_ERROR.value == "SYS_001"
        assert ErrorCode.SYSTEM_MONITORING_FAILED.value == "SYS_002"
        assert ErrorCode.SYSTEM_RESOURCE_UNAVAILABLE.value == "SYS_003"
        assert ErrorCode.NETWORK_ERROR.value == "NET_001"
        assert ErrorCode.NETWORK_CONNECTION_FAILED.value == "NET_002"
        assert ErrorCode.NETWORK_TIMEOUT.value == "NET_003"
        assert ErrorCode.NETWORK_UNREACHABLE.value == "NET_004"
        assert ErrorCode.TRANSPORT_ERROR.value == "TRANS_001"
        assert ErrorCode.TRANSPORT_CONNECTION_FAILED.value == "TRANS_002"
        assert ErrorCode.TRANSPORT_STREAM_FAILED.value == "TRANS_003"
        assert ErrorCode.TRANSPORT_PROTOCOL_ERROR.value == "TRANS_004"
        assert ErrorCode.CONFIG_ERROR.value == "CFG_001"
        assert ErrorCode.CONFIG_VALIDATION_FAILED.value == "CFG_002"
        assert ErrorCode.CONFIG_INVALID_LIMITS.value == "CFG_003"
        assert ErrorCode.CONFIG_MISSING_REQUIRED.value == "CFG_004"
        assert ErrorCode.OPERATIONAL_ERROR.value == "OP_001"
        assert ErrorCode.OPERATIONAL_MONITORING_FAILED.value == "OP_002"
        assert ErrorCode.OPERATIONAL_LIFECYCLE_FAILED.value == "OP_003"
        assert ErrorCode.OPERATIONAL_EVENT_FAILED.value == "OP_004"


class TestErrorContext:
    """Test ErrorContext dataclass."""

    def test_error_context_creation(self) -> None:
        """Test ErrorContext creation."""
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
            timestamp=time.time(),
        )
        assert context.error_code == ErrorCode.CONNECTION_LIMIT_EXCEEDED
        assert context.error_category == ErrorCategory.CONNECTION_LIMIT
        assert context.severity == ErrorSeverity.HIGH
        assert context.message == "Connection limit exceeded"
        assert context.timestamp > 0

    def test_error_context_with_optional_fields(self) -> None:
        """Test ErrorContext creation with optional fields."""
        peer_id = ID.from_base58("QmTest123")
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
            resource_type="connection",
            resource_id="conn_123",
            resource_scope="peer",
            connection_id="conn_123",
            peer_id=peer_id,
            limit_type="established",
            limit_value=100,
            current_value=150,
            limit_percentage=150.0,
            system_memory_total=8 * 1024 * 1024 * 1024,
            system_memory_available=4 * 1024 * 1024 * 1024,
            system_memory_percent=50.0,
            process_memory_bytes=1024 * 1024 * 1024,
            process_memory_percent=12.5,
            metadata={"key": "value"},
        )
        assert context.resource_type == "connection"
        assert context.resource_id == "conn_123"
        assert context.resource_scope == "peer"
        assert context.connection_id == "conn_123"
        assert context.peer_id == peer_id
        assert context.limit_type == "established"
        assert context.limit_value == 100
        assert context.current_value == 150
        assert context.limit_percentage == 150.0
        assert context.system_memory_total == 8 * 1024 * 1024 * 1024
        assert context.system_memory_available == 4 * 1024 * 1024 * 1024
        assert context.system_memory_percent == 50.0
        assert context.process_memory_bytes == 1024 * 1024 * 1024
        assert context.process_memory_percent == 12.5
        assert context.metadata == {"key": "value"}

    def test_error_context_default_timestamp(self) -> None:
        """Test ErrorContext with default timestamp."""
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
        )
        assert context.timestamp > 0
        assert context.timestamp <= time.time()


class TestResourceLimitExceededError:
    """Test ResourceLimitExceededError exception."""

    def test_resource_limit_exceeded_error_creation(self) -> None:
        """Test ResourceLimitExceededError creation."""
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
        )
        error = ResourceLimitExceededError(context)
        assert error.error_context == context
        assert str(error) == "Connection limit exceeded"

    def test_resource_limit_exceeded_error_inheritance(self) -> None:
        """Test ResourceLimitExceededError inheritance."""
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
        )
        error = ResourceLimitExceededError(context)
        assert isinstance(error, Exception)
        assert isinstance(error, ResourceLimitExceededError)


class TestSystemResourceError:
    """Test SystemResourceError exception."""

    def test_system_resource_error_creation(self) -> None:
        """Test SystemResourceError creation."""
        context = ErrorContext(
            error_code=ErrorCode.MEMORY_LIMIT_EXCEEDED,
            error_category=ErrorCategory.MEMORY_LIMIT,
            severity=ErrorSeverity.CRITICAL,
            message="Memory limit exceeded",
        )
        error = SystemResourceError(context)
        assert error.error_context == context
        assert str(error) == "Memory limit exceeded"

    def test_system_resource_error_inheritance(self) -> None:
        """Test SystemResourceError inheritance."""
        context = ErrorContext(
            error_code=ErrorCode.MEMORY_LIMIT_EXCEEDED,
            error_category=ErrorCategory.MEMORY_LIMIT,
            severity=ErrorSeverity.CRITICAL,
            message="Memory limit exceeded",
        )
        error = SystemResourceError(context)
        assert isinstance(error, Exception)
        assert isinstance(error, SystemResourceError)


class TestConfigurationError:
    """Test ConfigurationError exception."""

    def test_configuration_error_creation(self) -> None:
        """Test ConfigurationError creation."""
        context = ErrorContext(
            error_code=ErrorCode.CONFIG_ERROR,
            error_category=ErrorCategory.CONFIG_ERROR,
            severity=ErrorSeverity.MEDIUM,
            message="Configuration error",
        )
        error = ConfigurationError(context)
        assert error.error_context == context
        assert str(error) == "Configuration error"

    def test_configuration_error_inheritance(self) -> None:
        """Test ConfigurationError inheritance."""
        context = ErrorContext(
            error_code=ErrorCode.CONFIG_ERROR,
            error_category=ErrorCategory.CONFIG_ERROR,
            severity=ErrorSeverity.MEDIUM,
            message="Configuration error",
        )
        error = ConfigurationError(context)
        assert isinstance(error, Exception)
        assert isinstance(error, ConfigurationError)


class TestOperationalError:
    """Test OperationalError exception."""

    def test_operational_error_creation(self) -> None:
        """Test OperationalError creation."""
        context = ErrorContext(
            error_code=ErrorCode.OPERATIONAL_ERROR,
            error_category=ErrorCategory.OPERATIONAL_ERROR,
            severity=ErrorSeverity.MEDIUM,
            message="Operational error",
        )
        error = OperationalError(context)
        assert error.error_context == context
        assert str(error) == "Operational error"

    def test_operational_error_inheritance(self) -> None:
        """Test OperationalError inheritance."""
        context = ErrorContext(
            error_code=ErrorCode.OPERATIONAL_ERROR,
            error_category=ErrorCategory.OPERATIONAL_ERROR,
            severity=ErrorSeverity.MEDIUM,
            message="Operational error",
        )
        error = OperationalError(context)
        assert isinstance(error, Exception)
        assert isinstance(error, OperationalError)


class TestErrorFactoryFunctions:
    """Test error factory functions."""

    def test_create_connection_limit_error(self) -> None:
        """Test create_connection_limit_error function."""
        peer_id = ID.from_base58("QmTest123")
        error = create_connection_limit_error(
            limit_type="established",
            limit_value=100,
            current_value=150,
            connection_id="conn_123",
            peer_id=peer_id,
            message="Connection limit exceeded",
            metadata={"key": "value"},
        )
        assert isinstance(error, ResourceLimitExceededError)
        assert error.error_context.limit_type == "established"
        assert error.error_context.limit_value == 100
        assert error.error_context.current_value == 150
        assert error.error_context.connection_id == "conn_123"
        assert error.error_context.peer_id == peer_id
        assert error.error_context.message == "Connection limit exceeded"
        assert error.error_context.metadata == {"key": "value"}

    def test_create_memory_limit_error(self) -> None:
        """Test create_memory_limit_error function."""
        error = create_memory_limit_error(
            limit_type="process",
            limit_value=1024 * 1024 * 1024,
            current_value=2 * 1024 * 1024 * 1024,
            system_memory_total=8 * 1024 * 1024 * 1024,
            system_memory_available=4 * 1024 * 1024 * 1024,
            process_memory_bytes=2 * 1024 * 1024 * 1024,
            message="Memory limit exceeded",
            metadata={"key": "value"},
        )
        assert isinstance(error, SystemResourceError)
        assert error.error_context.limit_type == "process"
        assert error.error_context.limit_value == 1024 * 1024 * 1024
        assert error.error_context.current_value == 2 * 1024 * 1024 * 1024
        assert error.error_context.system_memory_total == 8 * 1024 * 1024 * 1024
        assert error.error_context.system_memory_available == 4 * 1024 * 1024 * 1024
        assert error.error_context.process_memory_bytes == 2 * 1024 * 1024 * 1024
        assert error.error_context.message == "Memory limit exceeded"
        assert error.error_context.metadata == {"key": "value"}

    def test_create_configuration_error(self) -> None:
        """Test create_configuration_error function."""
        error = create_configuration_error(
            config_key="max_connections",
            config_value=100,
            message="Invalid configuration",
            metadata={"key": "value"},
        )
        assert isinstance(error, ConfigurationError)
        assert error.error_context.error_code == ErrorCode.CONFIG_ERROR
        assert error.error_context.error_category == ErrorCategory.CONFIG_ERROR
        assert error.error_context.severity == ErrorSeverity.MEDIUM
        assert error.error_context.message == "Invalid configuration"
        assert error.error_context.metadata["config_key"] == "max_connections"
        assert error.error_context.metadata["config_value"] == "100"
        assert error.error_context.metadata["key"] == "value"

    def test_create_operational_error(self) -> None:
        """Test create_operational_error function."""
        error = create_operational_error(
            operation="connection_establishment",
            component="swarm",
            message="Operational error",
            metadata={"key": "value"},
        )
        assert isinstance(error, OperationalError)
        assert error.error_context.error_code == ErrorCode.OPERATIONAL_ERROR
        assert error.error_context.error_category == ErrorCategory.OPERATIONAL_ERROR
        assert error.error_context.severity == ErrorSeverity.MEDIUM
        assert error.error_context.message == "Operational error"
        assert error.error_context.metadata["operation"] == "connection_establishment"
        assert error.error_context.metadata["component"] == "swarm"
        assert error.error_context.metadata["key"] == "value"


class TestErrorIntegration:
    """Test error integration scenarios."""

    def test_error_context_serialization(self) -> None:
        """Test ErrorContext serialization."""
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
            metadata={"key": "value"},
        )
        # Should be able to access attributes
        assert context.error_code.value == "CONN_001"
        assert context.error_category.value == "connection_limit"
        assert context.severity.value == "high"
        assert context.message == "Connection limit exceeded"
        assert context.metadata == {"key": "value"}

    def test_error_exception_handling(self) -> None:
        """Test error exception handling."""
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
        )
        error = ResourceLimitExceededError(context)

        # Should be able to catch and handle
        try:
            raise error
        except ResourceLimitExceededError as e:
            assert e.error_context == context
            assert str(e) == "Connection limit exceeded"
        except Exception:
            pytest.fail("Should have caught ResourceLimitExceededError")

    def test_error_factory_with_minimal_params(self) -> None:
        """Test error factory functions with minimal parameters."""
        # Test connection limit error with minimal params
        error1 = create_connection_limit_error(
            limit_type="established",
            limit_value=100,
            current_value=150,
        )
        assert isinstance(error1, ResourceLimitExceededError)
        assert error1.error_context.limit_type == "established"
        assert error1.error_context.limit_value == 100
        assert error1.error_context.current_value == 150

        # Test memory limit error with minimal params
        error2 = create_memory_limit_error(
            limit_type="process",
            limit_value=1024 * 1024 * 1024,
            current_value=2 * 1024 * 1024 * 1024,
        )
        assert isinstance(error2, SystemResourceError)
        assert error2.error_context.limit_type == "process"
        assert error2.error_context.limit_value == 1024 * 1024 * 1024
        assert error2.error_context.current_value == 2 * 1024 * 1024 * 1024

        # Test configuration error with minimal params
        error3 = create_configuration_error(
            config_key="max_connections",
            config_value=100,
        )
        assert isinstance(error3, ConfigurationError)
        assert error3.error_context.metadata["config_key"] == "max_connections"
        assert error3.error_context.metadata["config_value"] == "100"

        # Test operational error with minimal params
        error4 = create_operational_error(
            operation="connection_establishment",
            component="swarm",
        )
        assert isinstance(error4, OperationalError)
        assert error4.error_context.metadata["operation"] == "connection_establishment"
        assert error4.error_context.metadata["component"] == "swarm"

    def test_error_context_edge_cases(self) -> None:
        """Test ErrorContext edge cases."""
        # Test with None values
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
            resource_type=None,
            resource_id=None,
            resource_scope=None,
            connection_id=None,
            peer_id=None,
            limit_type=None,
            limit_value=None,
            current_value=None,
            limit_percentage=None,
            system_memory_total=None,
            system_memory_available=None,
            system_memory_percent=None,
            process_memory_bytes=None,
            process_memory_percent=None,
            metadata={},
        )
        assert context.resource_type is None
        assert context.resource_id is None
        assert context.resource_scope is None
        assert context.connection_id is None
        assert context.peer_id is None
        assert context.limit_type is None
        assert context.limit_value is None
        assert context.current_value is None
        assert context.limit_percentage is None
        assert context.system_memory_total is None
        assert context.system_memory_available is None
        assert context.system_memory_percent is None
        assert context.process_memory_bytes is None
        assert context.process_memory_percent is None
        assert context.metadata is None

    def test_error_context_with_complex_metadata(self) -> None:
        """Test ErrorContext with complex metadata."""
        metadata = {
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "number": 42,
            "boolean": True,
            "null": None,
        }
        context = ErrorContext(
            error_code=ErrorCode.CONNECTION_LIMIT_EXCEEDED,
            error_category=ErrorCategory.CONNECTION_LIMIT,
            severity=ErrorSeverity.HIGH,
            message="Connection limit exceeded",
            metadata=metadata,
        )
        assert context.metadata == metadata
        assert context.metadata["nested"]["key"] == "value"
        assert context.metadata["list"] == [1, 2, 3]
        assert context.metadata["number"] == 42
        assert context.metadata["boolean"] is True
        assert context.metadata["null"] is None
