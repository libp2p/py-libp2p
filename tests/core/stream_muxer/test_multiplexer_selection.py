import logging

import pytest
from multiaddr.multiaddr import Multiaddr
import trio

from libp2p import (
    MUXER_MPLEX,
    MUXER_YAMUX,
    create_mplex_muxer_option,
    create_yamux_muxer_option,
    new_host,
    set_default_muxer,
)
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import PeerInfo

# Enable logging for debugging
logging.basicConfig(level=logging.DEBUG)


# Fixture to create hosts with a specified muxer preference
@pytest.fixture
async def host_pair(muxer_preference=None, muxer_opt=None):
    """Create a pair of connected hosts with the given muxer settings."""
    host_a = new_host(muxer_preference=muxer_preference, muxer_opt=muxer_opt)
    host_b = new_host(muxer_preference=muxer_preference, muxer_opt=muxer_opt)

    # Start both hosts
    await host_a.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
    await host_b.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

    # Connect hosts with a timeout
    listen_addrs_a = host_a.get_addrs()
    with trio.move_on_after(5):  # 5 second timeout
        peer_info_a = PeerInfo(host_a.get_id(), listen_addrs_a)
        await host_b.connect(peer_info_a)

    yield host_a, host_b

    # Cleanup
    try:
        await host_a.close()
    except Exception as e:
        logging.warning(f"Error closing host_a: {e}")

    try:
        await host_b.close()
    except Exception as e:
        logging.warning(f"Error closing host_b: {e}")


@pytest.mark.trio
@pytest.mark.parametrize("muxer_preference", [MUXER_YAMUX, MUXER_MPLEX])
async def test_multiplexer_preference_parameter(muxer_preference):
    """Test that muxer_preference parameter works correctly."""
    # Set a timeout for the entire test
    with trio.move_on_after(10):
        host_a = new_host(muxer_preference=muxer_preference)
        host_b = new_host(muxer_preference=muxer_preference)

        try:
            # Start both hosts
            await host_a.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
            await host_b.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

            # Connect hosts with timeout
            listen_addrs_a = host_a.get_addrs()
            with trio.move_on_after(5):  # 5 second timeout
                peer_info_a = PeerInfo(host_a.get_id(), listen_addrs_a)
                await host_b.connect(peer_info_a)
            # Check if connection was established
            connections = host_b.get_network().connections
            assert len(connections) > 0, "Connection not established"

            # Get the first connection
            conn = list(connections.values())[0]
            muxed_conn = conn.muxed_conn

            # Define a simple echo protocol
            ECHO_PROTOCOL = TProtocol("/echo/1.0.0")

            # Setup echo handler on host_a
            async def echo_handler(stream):
                try:
                    data = await stream.read(1024)
                    await stream.write(data)
                    await stream.close()
                except Exception as e:
                    print(f"Error in echo handler: {e}")

            host_a.set_stream_handler(ECHO_PROTOCOL, echo_handler)

            # Open a stream with timeout
            with trio.move_on_after(5):
                stream = await muxed_conn.open_stream()

            # Check stream type
            if muxer_preference == MUXER_YAMUX:
                assert "YamuxStream" in stream.__class__.__name__
            else:
                assert "MplexStream" in stream.__class__.__name__

            # Close the stream
            await stream.close()

        finally:
            # Close hosts with error handling
            try:
                await host_a.close()
            except Exception as e:
                logging.warning(f"Error closing host_a: {e}")

            try:
                await host_b.close()
            except Exception as e:
                logging.warning(f"Error closing host_b: {e}")


@pytest.mark.trio
@pytest.mark.parametrize(
    "muxer_option_func,expected_stream_class",
    [
        (create_yamux_muxer_option, "YamuxStream"),
        (create_mplex_muxer_option, "MplexStream"),
    ],
)
async def test_explicit_muxer_options(muxer_option_func, expected_stream_class):
    """Test that explicit muxer options work correctly."""
    # Set a timeout for the entire test
    with trio.move_on_after(10):
        # Create hosts with specified muxer options
        muxer_opt = muxer_option_func()
        host_a = new_host(muxer_opt=muxer_opt)
        host_b = new_host(muxer_opt=muxer_opt)

        try:
            # Start both hosts
            await host_a.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
            await host_b.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

            # Connect hosts with timeout
            listen_addrs_a = host_a.get_addrs()
            with trio.move_on_after(5):  # 5 second timeout
                peer_info_a = PeerInfo(host_a.get_id(), listen_addrs_a)
                await host_b.connect(peer_info_a)

            # Check if connection was established
            connections = host_b.get_network().connections
            assert len(connections) > 0, "Connection not established"

            # Get the first connection
            conn = list(connections.values())[0]
            muxed_conn = conn.muxed_conn

            # Define a simple echo protocol
            ECHO_PROTOCOL = TProtocol("/echo/1.0.0")

            # Setup echo handler on host_a
            async def echo_handler(stream):
                try:
                    data = await stream.read(1024)
                    await stream.write(data)
                    await stream.close()
                except Exception as e:
                    print(f"Error in echo handler: {e}")

            host_a.set_stream_handler(ECHO_PROTOCOL, echo_handler)

            # Open a stream with timeout
            with trio.move_on_after(5):
                stream = await muxed_conn.open_stream()

            # Check stream type
            assert expected_stream_class in stream.__class__.__name__

            # Close the stream
            await stream.close()

        finally:
            # Close hosts with error handling
            try:
                await host_a.close()
            except Exception as e:
                logging.warning(f"Error closing host_a: {e}")

            try:
                await host_b.close()
            except Exception as e:
                logging.warning(f"Error closing host_b: {e}")


@pytest.mark.trio
@pytest.mark.parametrize("global_default", [MUXER_YAMUX, MUXER_MPLEX])
async def test_global_default_muxer(global_default):
    """Test that global default muxer setting works correctly."""
    # Set a timeout for the entire test
    with trio.move_on_after(10):
        # Set global default
        set_default_muxer(global_default)

        # Create hosts with default settings
        host_a = new_host()
        host_b = new_host()

        try:
            # Start both hosts
            await host_a.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))
            await host_b.get_network().listen(Multiaddr("/ip4/127.0.0.1/tcp/0"))

            # Connect hosts with timeout
            listen_addrs_a = host_a.get_addrs()
            with trio.move_on_after(5):  # 5 second timeout
                peer_info_a = PeerInfo(host_a.get_id(), listen_addrs_a)
                await host_b.connect(peer_info_a)

            # Check if connection was established
            connections = host_b.get_network().connections
            assert len(connections) > 0, "Connection not established"

            # Get the first connection
            conn = list(connections.values())[0]
            muxed_conn = conn.muxed_conn

            # Define a simple echo protocol
            ECHO_PROTOCOL = TProtocol("/echo/1.0.0")

            # Setup echo handler on host_a
            async def echo_handler(stream):
                try:
                    data = await stream.read(1024)
                    await stream.write(data)
                    await stream.close()
                except Exception as e:
                    print(f"Error in echo handler: {e}")

            host_a.set_stream_handler(ECHO_PROTOCOL, echo_handler)

            # Open a stream with timeout
            with trio.move_on_after(5):
                stream = await muxed_conn.open_stream()

            # Check stream type based on global default
            if global_default == MUXER_YAMUX:
                assert "YamuxStream" in stream.__class__.__name__
            else:
                assert "MplexStream" in stream.__class__.__name__

            # Close the stream
            await stream.close()

        finally:
            # Close hosts with error handling
            try:
                await host_a.close()
            except Exception as e:
                logging.warning(f"Error closing host_a: {e}")

            try:
                await host_b.close()
            except Exception as e:
                logging.warning(f"Error closing host_b: {e}")
