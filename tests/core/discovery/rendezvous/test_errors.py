"""
Tests for rendezvous protocol error handling.
"""

import pytest

from libp2p.discovery.rendezvous.errors import (
    InternalError,
    InvalidCookieError,
    InvalidNamespaceError,
    InvalidPeerInfoError,
    InvalidTTLError,
    NotAuthorizedError,
    RendezvousError,
    UnavailableError,
    status_to_exception,
)
from libp2p.discovery.rendezvous.pb.rendezvous_pb2 import Message


class TestRendezvousError:
    """Test cases for base RendezvousError."""

    def test_init_with_status_only(self):
        """Test error initialization with status only."""
        error = RendezvousError(Message.ResponseStatus.E_INTERNAL_ERROR)
        assert error.status == Message.ResponseStatus.E_INTERNAL_ERROR
        assert error.message == ""
        assert "300" in str(error)  # Status code is 300 for E_INTERNAL_ERROR

    def test_init_with_status_and_message(self):
        """Test error initialization with status and message."""
        error = RendezvousError(
            Message.ResponseStatus.E_INVALID_NAMESPACE, "Custom message"
        )
        assert error.status == Message.ResponseStatus.E_INVALID_NAMESPACE
        assert error.message == "Custom message"
        assert "Custom message" in str(error)

    def test_inheritance(self):
        """Test that RendezvousError is an Exception."""
        error = RendezvousError(Message.ResponseStatus.E_INTERNAL_ERROR)
        assert isinstance(error, Exception)


class TestSpecificErrors:
    """Test cases for specific error types."""

    def test_invalid_namespace_error(self):
        """Test InvalidNamespaceError."""
        error = InvalidNamespaceError()
        assert error.status == Message.ResponseStatus.E_INVALID_NAMESPACE
        assert error.message == "Invalid namespace"
        assert isinstance(error, RendezvousError)

    def test_invalid_namespace_error_custom_message(self):
        """Test InvalidNamespaceError with custom message."""
        error = InvalidNamespaceError("Namespace too long")
        assert error.status == Message.ResponseStatus.E_INVALID_NAMESPACE
        assert error.message == "Namespace too long"

    def test_invalid_peer_info_error(self):
        """Test InvalidPeerInfoError."""
        error = InvalidPeerInfoError()
        assert error.status == Message.ResponseStatus.E_INVALID_PEER_INFO
        assert error.message == "Invalid peer info"
        assert isinstance(error, RendezvousError)

    def test_invalid_peer_info_error_custom_message(self):
        """Test InvalidPeerInfoError with custom message."""
        error = InvalidPeerInfoError("No addresses provided")
        assert error.status == Message.ResponseStatus.E_INVALID_PEER_INFO
        assert error.message == "No addresses provided"

    def test_invalid_ttl_error(self):
        """Test InvalidTTLError."""
        error = InvalidTTLError()
        assert error.status == Message.ResponseStatus.E_INVALID_TTL
        assert error.message == "Invalid TTL"
        assert isinstance(error, RendezvousError)

    def test_invalid_ttl_error_custom_message(self):
        """Test InvalidTTLError with custom message."""
        error = InvalidTTLError("TTL too large")
        assert error.status == Message.ResponseStatus.E_INVALID_TTL
        assert error.message == "TTL too large"

    def test_invalid_cookie_error(self):
        """Test InvalidCookieError."""
        error = InvalidCookieError()
        assert error.status == Message.ResponseStatus.E_INVALID_COOKIE
        assert error.message == "Invalid cookie"
        assert isinstance(error, RendezvousError)

    def test_invalid_cookie_error_custom_message(self):
        """Test InvalidCookieError with custom message."""
        error = InvalidCookieError("Cookie expired")
        assert error.status == Message.ResponseStatus.E_INVALID_COOKIE
        assert error.message == "Cookie expired"

    def test_not_authorized_error(self):
        """Test NotAuthorizedError."""
        error = NotAuthorizedError()
        assert error.status == Message.ResponseStatus.E_NOT_AUTHORIZED
        assert error.message == "Not authorized"
        assert isinstance(error, RendezvousError)

    def test_not_authorized_error_custom_message(self):
        """Test NotAuthorizedError with custom message."""
        error = NotAuthorizedError("Peer not allowed")
        assert error.status == Message.ResponseStatus.E_NOT_AUTHORIZED
        assert error.message == "Peer not allowed"

    def test_internal_error(self):
        """Test InternalError."""
        error = InternalError()
        assert error.status == Message.ResponseStatus.E_INTERNAL_ERROR
        assert error.message == "Internal server error"
        assert isinstance(error, RendezvousError)

    def test_internal_error_custom_message(self):
        """Test InternalError with custom message."""
        error = InternalError("Database failure")
        assert error.status == Message.ResponseStatus.E_INTERNAL_ERROR
        assert error.message == "Database failure"

    def test_unavailable_error(self):
        """Test UnavailableError."""
        error = UnavailableError()
        assert error.status == Message.ResponseStatus.E_UNAVAILABLE
        assert error.message == "Service unavailable"
        assert isinstance(error, RendezvousError)

    def test_unavailable_error_custom_message(self):
        """Test UnavailableError with custom message."""
        error = UnavailableError("Server overloaded")
        assert error.status == Message.ResponseStatus.E_UNAVAILABLE
        assert error.message == "Server overloaded"


class TestStatusToException:
    """Test cases for status_to_exception function."""

    def test_status_to_exception_invalid_namespace(self):
        """Test mapping E_INVALID_NAMESPACE to InvalidNamespaceError."""
        error = status_to_exception(Message.ResponseStatus.E_INVALID_NAMESPACE)
        assert isinstance(error, InvalidNamespaceError)
        assert error.status == Message.ResponseStatus.E_INVALID_NAMESPACE

    def test_status_to_exception_invalid_peer_info(self):
        """Test mapping E_INVALID_PEER_INFO to InvalidPeerInfoError."""
        error = status_to_exception(Message.ResponseStatus.E_INVALID_PEER_INFO)
        assert isinstance(error, InvalidPeerInfoError)
        assert error.status == Message.ResponseStatus.E_INVALID_PEER_INFO

    def test_status_to_exception_invalid_ttl(self):
        """Test mapping E_INVALID_TTL to InvalidTTLError."""
        error = status_to_exception(Message.ResponseStatus.E_INVALID_TTL)
        assert isinstance(error, InvalidTTLError)
        assert error.status == Message.ResponseStatus.E_INVALID_TTL

    def test_status_to_exception_invalid_cookie(self):
        """Test mapping E_INVALID_COOKIE to InvalidCookieError."""
        error = status_to_exception(Message.ResponseStatus.E_INVALID_COOKIE)
        assert isinstance(error, InvalidCookieError)
        assert error.status == Message.ResponseStatus.E_INVALID_COOKIE

    def test_status_to_exception_not_authorized(self):
        """Test mapping E_NOT_AUTHORIZED to NotAuthorizedError."""
        error = status_to_exception(Message.ResponseStatus.E_NOT_AUTHORIZED)
        assert isinstance(error, NotAuthorizedError)
        assert error.status == Message.ResponseStatus.E_NOT_AUTHORIZED

    def test_status_to_exception_internal_error(self):
        """Test mapping E_INTERNAL_ERROR to InternalError."""
        error = status_to_exception(Message.ResponseStatus.E_INTERNAL_ERROR)
        assert isinstance(error, InternalError)
        assert error.status == Message.ResponseStatus.E_INTERNAL_ERROR

    def test_status_to_exception_unavailable(self):
        """Test mapping E_UNAVAILABLE to UnavailableError."""
        error = status_to_exception(Message.ResponseStatus.E_UNAVAILABLE)
        assert isinstance(error, UnavailableError)
        assert error.status == Message.ResponseStatus.E_UNAVAILABLE

    def test_status_to_exception_ok_status(self):
        """Test that OK status returns None."""
        error = status_to_exception(Message.ResponseStatus.OK)
        assert error is None

    def test_status_to_exception_with_message(self):
        """Test status_to_exception with custom message."""
        error = status_to_exception(
            Message.ResponseStatus.E_INVALID_NAMESPACE, "Custom error message"
        )
        assert isinstance(error, InvalidNamespaceError)
        assert error.message == "Custom error message"

    def test_status_to_exception_unknown_status(self):
        """Test handling of unknown status codes."""
        # Use a high number that's unlikely to be a valid status
        unknown_status = Message.ResponseStatus.ValueType(9999)
        error = status_to_exception(unknown_status)
        assert isinstance(error, RendezvousError)
        assert error.status == unknown_status


class TestErrorInheritance:
    """Test error inheritance and polymorphism."""

    def test_all_errors_inherit_from_rendezvous_error(self):
        """Test that all specific errors inherit from RendezvousError."""
        errors = [
            InvalidNamespaceError(),
            InvalidPeerInfoError(),
            InvalidTTLError(),
            InvalidCookieError(),
            NotAuthorizedError(),
            InternalError(),
            UnavailableError(),
        ]

        for error in errors:
            assert isinstance(error, RendezvousError)
            assert isinstance(error, Exception)

    def test_error_catching_polymorphism(self):
        """Test that specific errors can be caught as RendezvousError."""
        try:
            raise InvalidNamespaceError("Test error")
        except RendezvousError as e:
            assert e.status == Message.ResponseStatus.E_INVALID_NAMESPACE
            assert e.message == "Test error"
        except Exception:
            pytest.fail("Should have caught as RendezvousError")

    def test_error_status_codes_unique(self):
        """Test that each error type has a unique status code."""
        errors_and_statuses = [
            (InvalidNamespaceError(), Message.ResponseStatus.E_INVALID_NAMESPACE),
            (InvalidPeerInfoError(), Message.ResponseStatus.E_INVALID_PEER_INFO),
            (InvalidTTLError(), Message.ResponseStatus.E_INVALID_TTL),
            (InvalidCookieError(), Message.ResponseStatus.E_INVALID_COOKIE),
            (NotAuthorizedError(), Message.ResponseStatus.E_NOT_AUTHORIZED),
            (InternalError(), Message.ResponseStatus.E_INTERNAL_ERROR),
            (UnavailableError(), Message.ResponseStatus.E_UNAVAILABLE),
        ]

        statuses = [status for _, status in errors_and_statuses]
        assert len(statuses) == len(set(statuses)), "Status codes should be unique"
