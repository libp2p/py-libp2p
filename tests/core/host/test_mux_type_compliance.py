from unittest.mock import AsyncMock, MagicMock

import pytest

# Import the interfaces
from libp2p.abc import (
    IMultiselectMuxer,
    INetworkService,
    IPeerStore,
)
from libp2p.custom_types import StreamHandlerFn, TProtocol

# Import the concrete classes for instantiation and specific type checks
from libp2p.host.basic_host import BasicHost

# For expected errors in negotiation tests
from libp2p.protocol_muxer.exceptions import MultiselectError
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import (
    MultiselectClient,
)  # Needed for mock calls
from libp2p.protocol_muxer.multiselect_communicator import (
    MultiselectCommunicator,
)  # Needed for mock calls

# --- Fixtures for setting up the test environment ---


@pytest.fixture
def mock_peer_id():
    """Provides a mock PeerID for testing purposes."""
    mock = MagicMock()
    mock.__str__.return_value = "QmMockPeerId"
    return mock


@pytest.fixture
def mock_peerstore():
    """Provides a mocked IPeerStore instance."""
    mock = MagicMock(spec=IPeerStore)
    mock.pubkey.return_value = MagicMock()  # Mock PublicKey
    mock.privkey.return_value = MagicMock()  # Mock PrivateKey
    mock.add_addrs = AsyncMock()  # Ensure add_addrs is an AsyncMock if called
    mock.peer_info.return_value = MagicMock()  # Mock PeerInfo
    return mock


@pytest.fixture
def mock_network_service(mock_peer_id, mock_peerstore):
    """
    Provides a mocked INetworkService instance with necessary sub-mocks.
    This simulates the network environment for the BasicHost.
    """
    mock_network = AsyncMock(spec=INetworkService)
    mock_network.peerstore = mock_peerstore
    mock_network.get_peer_id.return_value = mock_peer_id
    mock_network.connections = {}  # Simulate no active connections initially
    mock_network.listeners = {}  # Simulate no active listeners initially
    mock_network.set_stream_handler = (
        MagicMock()
    )  # Mock setting stream handler if called during init
    mock_network.new_stream = AsyncMock()  # Mock for new_stream calls in BasicHost

    return mock_network


@pytest.fixture
def basic_host(mock_network_service):
    """
    Provides an instance of BasicHost initialized with mocked dependencies.
    """
    # BasicHost.__init__ calls set_stream_handler, so mock_network_service needs it.
    # It also initializes self.multiselect and self.multiselect_client internally.
    return BasicHost(network=mock_network_service, enable_mDNS=False)


@pytest.fixture
def mock_communicator():
    """
    Provides a mock for IMultiselectCommunicator for negotiation tests.
    By default, it will provide responses for a successful handshake and a protocol proposal.
    Reset side_effect in specific tests if different behavior is needed.
    """
    mock = AsyncMock(
        spec=MultiselectCommunicator
    )  # Use concrete spec for more accurate method mocks
    mock.read = AsyncMock()
    mock.write = AsyncMock()
    return mock


# --- Runtime Type Checking Tests ---


def test_get_mux_return_type_runtime(basic_host):
    """
    Verifies at runtime that BasicHost.get_mux() returns an object
    that is an instance of both the IMultiselectMuxer interface and
    the concrete Multiselect class.
    """
    mux = basic_host.get_mux()

    # 1. Assert it's an instance of the interface
    assert isinstance(mux, IMultiselectMuxer), (
        f"Expected mux to be an instance of IMultiselectMuxer, but got {type(mux)}"
    )

    # 2. Assert it's an instance of the concrete implementation
    assert isinstance(mux, Multiselect), (
        f"Expected mux to be an instance of Multiselect, but got {type(mux)}"
    )

    # Optional: Verify that the object returned is the one stored internally
    assert mux is basic_host.multiselect, (
        "The returned muxer should be the internal multiselect instance"
    )


def test_get_mux_interface_compliance(basic_host):
    """
    Ensures that the object returned by BasicHost.get_mux() has all
    the expected attributes and methods defined by IMultiselectMuxer.
    """
    mux = basic_host.get_mux()

    # Check presence of required attributes/methods
    assert hasattr(mux, "handlers"), "IMultiselectMuxer must have 'handlers' attribute"
    assert isinstance(mux.handlers, dict), "'handlers' attribute must be a dictionary"

    assert hasattr(mux, "add_handler"), (
        "IMultiselectMuxer must have 'add_handler' method"
    )
    assert callable(mux.add_handler), "'add_handler' must be callable"

    assert hasattr(mux, "get_protocols"), (
        "IMultiselectMuxer must have 'get_protocols' method"
    )
    assert callable(mux.get_protocols), "'get_protocols' must be callable"

    assert hasattr(mux, "negotiate"), "IMultiselectMuxer must have 'negotiate' method"
    assert callable(mux.negotiate), "'negotiate' must be callable"


# --- Functionality / Integration Tests ---


async def test_get_mux_add_handler_and_get_protocols(basic_host):
    """
    Tests the functional behavior of add_handler and get_protocols methods
    on the muxer returned by get_mux().
    """
    mux = basic_host.get_mux()

    # Initial state check - ensure default protocols are present
    initial_protocols = mux.get_protocols()
    assert (
        TProtocol("/multistream/1.0.0") in initial_protocols
    )  # BasicHost adds default

    # Ensure our test protocols aren't there yet
    assert TProtocol("/test/1.0.0") not in initial_protocols
    assert TProtocol("/another/protocol/1.0.0") not in initial_protocols

    # Define a dummy handler
    def dummy_handler(stream: AsyncMock) -> None:
        pass

    # Add first protocol
    protocol_a = TProtocol("/test/1.0.0")
    mux.add_handler(protocol_a, dummy_handler)

    # Verify first protocol was added
    updated_protocols_a = mux.get_protocols()
    assert protocol_a in updated_protocols_a
    assert mux.handlers[protocol_a] is dummy_handler

    # Add second protocol
    protocol_b = TProtocol("/another/protocol/1.0.0")
    mux.add_handler(protocol_b, lambda s: None)  # Another dummy handler

    # Verify second protocol was added
    updated_protocols_b = mux.get_protocols()
    assert protocol_b in updated_protocols_b
    assert (
        len(updated_protocols_b) >= len(initial_protocols) + 2
    )  # Should have added two new custom ones


async def test_get_mux_negotiate_success(basic_host, mock_communicator):
    """
    Tests the successful negotiation flow using the muxer's negotiate method.
    """
    mux = basic_host.get_mux()

    # Define a protocol and its handler that `negotiate` should successfully find
    selected_protocol_str = "/app/my-protocol/1.0.0"
    selected_protocol = TProtocol(selected_protocol_str)
    dummy_negotiate_handler = AsyncMock(
        spec=StreamHandlerFn
    )  # Handler for the selected protocol
    mux.add_handler(selected_protocol, dummy_negotiate_handler)

    # Configure the mock_communicator to simulate a successful negotiation sequence
    mock_communicator.read.side_effect = [
        "/multistream/1.0.0",  # First read: Client sends its multistream protocol (handshake)
        selected_protocol_str,  # Second read: Client proposes the app protocol
    ]

    # Perform the negotiation
    protocol, handler = await mux.negotiate(mock_communicator)

    # Assert the returned protocol and handler are correct
    assert protocol == selected_protocol
    assert handler is dummy_negotiate_handler

    # Verify calls to the mock communicator (handshake and protocol acceptance)
    mock_communicator.write.assert_has_calls(
        [
            # Handshake response
            pytest.call("/multistream/1.0.0"),
            # Protocol acceptance
            pytest.call(selected_protocol_str),
        ]
    )
    # Ensure no other writes occurred
    assert mock_communicator.write.call_count == 2
    assert mock_communicator.read.call_count == 2


async def test_get_mux_negotiate_protocol_not_found(basic_host, mock_communicator):
    """
    Tests the negotiation flow when the proposed protocol is not found.
    """
    mux = basic_host.get_mux()

    # Ensure the protocol we propose isn't actually registered (beyond defaults)
    non_existent_protocol = TProtocol("/non-existent/protocol")
    assert non_existent_protocol not in mux.get_protocols()  # Ensure it's not present

    # Configure the mock_communicator to simulate a handshake followed by a non-existent protocol
    mock_communicator.read.side_effect = [
        "/multistream/1.0.0",  # Handshake response
        str(non_existent_protocol),  # Client proposes a non-existent protocol
    ]

    # Expect a MultiselectError as the protocol won't be found
    with pytest.raises(MultiselectError):
        await mux.negotiate(mock_communicator)

    # Verify handshake write and "na" (not available) write
    mock_communicator.write.assert_has_calls(
        [
            pytest.call("/multistream/1.0.0"),
            pytest.call("na"),  # Muxer should respond with "na"
        ]
    )
    assert mock_communicator.write.call_count == 2
    assert mock_communicator.read.call_count == 2
