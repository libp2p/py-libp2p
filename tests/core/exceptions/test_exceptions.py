from libp2p.exceptions import (
    BaseLibp2pError,
    DiscoveryError,
    NetworkError,
    PeerError,
    ProtocolError,
    PubsubError,
    ResourceError,
    ServiceError,
    MultiError,
)


def test_multierror_str_and_storage():
    errors = [
        ValueError("bad value"),
        KeyError("missing key"),
        RuntimeError("custom error"),
    ]
    multi_error = MultiError(errors)
    # Check for storage
    assert multi_error.errors == errors
    # Check for representation
    expected = "Error 1: bad value\nError 2: 'missing key'\nError 3: custom error"
    assert str(multi_error) == expected


def test_base_libp2p_error_inheritance():
    """Test that BaseLibp2pError is properly set up."""
    error = BaseLibp2pError("test message")
    assert isinstance(error, Exception)
    assert error.message == "test message"
    assert str(error) == "test message"


def test_base_libp2p_error_with_error_code():
    """Test BaseLibp2pError with error code."""
    error = BaseLibp2pError("test message", error_code="ERR001")
    assert error.error_code == "ERR001"
    assert str(error) == "[ERR001] test message"


def test_quic_error_inheritance():
    """Test that QUIC exceptions inherit from BaseLibp2pError."""
    from libp2p.transport.quic.exceptions import (
        QUICError,
        QUICConnectionError,
        QUICStreamError,
    )
    
    assert issubclass(QUICError, NetworkError)
    assert issubclass(QUICError, BaseLibp2pError)
    assert issubclass(QUICConnectionError, QUICError)
    assert issubclass(QUICStreamError, QUICError)
    
    # Test instance
    error = QUICError("test", error_code=1)
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, NetworkError)


def test_bitswap_error_inheritance():
    """Test that Bitswap exceptions inherit from BaseLibp2pError."""
    from libp2p.bitswap.errors import (
        BitswapError,
        BitswapTimeoutError,
        InvalidBlockError,
    )
    
    assert issubclass(BitswapError, ProtocolError)
    assert issubclass(BitswapError, BaseLibp2pError)
    assert issubclass(BitswapTimeoutError, BitswapError)
    assert issubclass(InvalidBlockError, BitswapError)
    
    # Test instance
    error = BitswapError("test")
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, ProtocolError)


def test_rendezvous_error_inheritance():
    """Test that Rendezvous exceptions inherit from BaseLibp2pError."""
    from libp2p.discovery.rendezvous.errors import (
        RendezvousError,
        InvalidNamespaceError,
    )
    
    assert issubclass(RendezvousError, DiscoveryError)
    assert issubclass(RendezvousError, BaseLibp2pError)
    assert issubclass(InvalidNamespaceError, RendezvousError)
    
    # Test instance
    from libp2p.discovery.rendezvous.errors import Message
    error = RendezvousError(Message.ResponseStatus.E_INVALID_NAMESPACE, "test")
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, DiscoveryError)


def test_peer_error_inheritance():
    """Test that peer exceptions inherit from BaseLibp2pError."""
    from libp2p.peer.peerstore import PeerStoreError
    from libp2p.peer.peerdata import PeerDataError
    from libp2p.peer.peerinfo import InvalidAddrError
    from libp2p.peer.persistent.serialization import SerializationError
    
    # Test inheritance
    assert issubclass(PeerStoreError, PeerError)
    assert issubclass(PeerStoreError, BaseLibp2pError)
    assert issubclass(PeerDataError, PeerError)
    assert issubclass(PeerDataError, BaseLibp2pError)
    assert issubclass(InvalidAddrError, PeerError)
    assert issubclass(InvalidAddrError, BaseLibp2pError)
    assert issubclass(SerializationError, PeerError)
    assert issubclass(SerializationError, BaseLibp2pError)
    
    # Test multiple inheritance for backwards compatibility
    assert issubclass(PeerStoreError, KeyError)
    assert issubclass(PeerDataError, KeyError)
    assert issubclass(InvalidAddrError, ValueError)
    
    # Test instances
    error = PeerStoreError("test")
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, PeerError)
    assert isinstance(error, KeyError)


def test_resource_error_inheritance():
    """Test that resource manager exceptions inherit from BaseLibp2pError."""
    from libp2p.rcmgr.exceptions import (
        ResourceManagerException,
        ResourceLimitExceeded,
    )
    from libp2p.rcmgr.circuit_breaker import CircuitBreakerError
    from libp2p.rcmgr.enhanced_errors import (
        ResourceLimitExceededError,
        SystemResourceError,
    )
    
    assert issubclass(ResourceManagerException, ResourceError)
    assert issubclass(ResourceManagerException, BaseLibp2pError)
    assert issubclass(ResourceLimitExceeded, ResourceManagerException)
    assert issubclass(CircuitBreakerError, ResourceError)
    assert issubclass(ResourceLimitExceededError, ResourceError)
    assert issubclass(SystemResourceError, ResourceError)
    
    # Test instances
    error = ResourceManagerException("test")
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, ResourceError)


def test_network_error_inheritance():
    """Test that network exceptions inherit from BaseLibp2pError."""
    from libp2p.network.exceptions import SwarmException
    from libp2p.network.stream.exceptions import StreamError
    
    assert issubclass(SwarmException, NetworkError)
    assert issubclass(SwarmException, BaseLibp2pError)
    assert issubclass(StreamError, BaseLibp2pError)  # StreamError inherits from IOException
    
    # Test instances
    error = SwarmException("test")
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, NetworkError)


def test_pubsub_error_inheritance():
    """Test that pubsub exceptions inherit from BaseLibp2pError."""
    from libp2p.pubsub.exceptions import (
        PubsubRouterError,
        NoPubsubAttached,
    )
    
    assert issubclass(PubsubRouterError, PubsubError)
    assert issubclass(PubsubRouterError, BaseLibp2pError)
    assert issubclass(NoPubsubAttached, PubsubRouterError)
    
    # Test instances
    error = PubsubRouterError("test")
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, PubsubError)


def test_crypto_error_inheritance():
    """Test that crypto exceptions inherit from BaseLibp2pError."""
    from libp2p.crypto.exceptions import CryptographyError
    from libp2p.crypto.authenticated_encryption import InvalidMACException
    
    assert issubclass(CryptographyError, BaseLibp2pError)
    assert issubclass(InvalidMACException, CryptographyError)
    assert issubclass(InvalidMACException, BaseLibp2pError)
    
    # Test instances
    error = InvalidMACException("test")
    assert isinstance(error, BaseLibp2pError)
    assert isinstance(error, CryptographyError)


def test_catch_all_libp2p_errors():
    """Test that we can catch all libp2p errors with BaseLibp2pError."""
    from libp2p.transport.quic.exceptions import QUICError
    from libp2p.bitswap.errors import BitswapError
    from libp2p.network.exceptions import SwarmException
    from libp2p.rcmgr.exceptions import ResourceManagerException
    
    exceptions = [
        QUICError("quic error"),
        BitswapError("bitswap error"),
        SwarmException("swarm error"),
        ResourceManagerException("resource error"),
    ]
    
    for exc in exceptions:
        try:
            raise exc
        except BaseLibp2pError:
            # Should catch all libp2p errors
            pass
        except Exception:
            # Should not reach here
            assert False, f"{exc} should be caught by BaseLibp2pError"
