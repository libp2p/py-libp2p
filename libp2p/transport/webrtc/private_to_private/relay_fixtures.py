"""
Test fixtures for WebRTC transport with circuit relay infrastructure.
"""

from collections.abc import AsyncIterator
import logging
from typing import Any, cast

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import IHost
from libp2p.io.abc import ReadWriteCloser
from libp2p.peer.id import ID
from libp2p.relay.circuit_v2.config import RelayLimits
from libp2p.relay.circuit_v2.protocol import (
    PROTOCOL_ID as RELAY_HOP_PROTOCOL_ID,
    STOP_PROTOCOL_ID as RELAY_STOP_PROTOCOL_ID,
    CircuitV2Protocol,
)
from libp2p.stream_muxer.yamux.yamux import YamuxStream
from libp2p.tools.async_service.trio_service import background_trio_service
from libp2p.tools.utils import connect
from tests.utils.factories import HostFactory

logger = logging.getLogger(__name__)

# Default relay limits for tests
DEFAULT_RELAY_LIMITS = RelayLimits(
    duration=60 * 60,  # 1 hour
    data=1024 * 1024 * 10,  # 10 MB
    max_circuit_conns=8,
    max_reservations=4,
)


def store_relay_addrs(peer_id: ID, addrs: list[Multiaddr], peerstore: Any) -> None:
    """Normalise relay addresses before storing them in the peerstore."""
    if not addrs:
        return

    suffix = Multiaddr(f"/p2p/{peer_id.to_base58()}")
    normalised: list[Multiaddr] = []

    for addr in addrs:
        base_addr = addr
        try:
            base_addr = addr.decapsulate(suffix)
        except ValueError:
            # Address might already be normalised (no /p2p component)
            base_addr = addr
        if str(base_addr) == "":
            logger.debug("Skipping empty relay addr derived from %s", addr)
            continue
        print(f"Normalised relay addr {addr} -> {base_addr}")
        normalised.append(base_addr)

    try:
        peerstore.add_addrs(peer_id, normalised, 3600)
    except Exception as exc:
        logger.debug("Failed to store relay addrs for %s: %s", peer_id, exc)

    try:
        peerstore.add_protocols(
            peer_id,
            [
                str(RELAY_HOP_PROTOCOL_ID),
                str(RELAY_STOP_PROTOCOL_ID),
            ],
        )
    except Exception as exc:
        logger.debug("Failed to mark relay protocols for %s: %s", peer_id, exc)


@pytest.fixture
def relay_limits() -> RelayLimits:
    """Fixture providing default relay limits."""
    return DEFAULT_RELAY_LIMITS


@pytest.fixture
async def relay_host() -> AsyncIterator[IHost]:
    """
    Create a host configured as a circuit relay server.

    Returns:
        IHost: Host configured as relay

    """
    async with HostFactory.create_batch_and_listen(1) as hosts:
        relay_host = hosts[0]

        # Set up circuit relay protocol as server
        limits = DEFAULT_RELAY_LIMITS
        relay_protocol = CircuitV2Protocol(relay_host, limits, allow_hop=True)

        # Start the relay protocol using background_trio_service
        # This properly initializes the Service manager
        async with background_trio_service(relay_protocol):
            await trio.sleep(0.1)

            try:
                yield relay_host
            finally:
                pass


@pytest.fixture
async def client_host(relay_host: IHost) -> AsyncIterator[IHost]:
    """
    Create a client host that can connect to the relay.

    Args:
        relay_host: The relay host fixture

    Returns:
        IHost: Client host configured to use relay

    """
    async with HostFactory.create_batch_and_listen(1) as hosts:
        client_host = hosts[0]

        # Connect client to relay
        relay_id = relay_host.get_id()
        relay_addrs = list(relay_host.get_addrs())

        if relay_addrs:
            store_relay_addrs(relay_id, relay_addrs, client_host.get_peerstore())

            try:
                await connect(client_host, relay_host)
                await trio.sleep(0.1)
                logger.info(f"Client connected to relay {relay_id}")
            except Exception as e:
                logger.warning(f"Failed to connect client to relay: {e}")

        yield client_host


@pytest.fixture
async def listener_host(relay_host: IHost) -> AsyncIterator[IHost]:
    """
    Create a listener host that makes a reservation on the relay.

    Args:
        relay_host: The relay host fixture

    Returns:
        IHost: Listener host with circuit relay reservation

    """
    async with HostFactory.create_batch_and_listen(1) as hosts:
        listener_host = hosts[0]

        # Set up circuit relay transport with auto-reserve
        # Enable CLIENT role to allow using relays
        # relay_config = RelayConfig(roles=RelayRole.CLIENT)

        limits = DEFAULT_RELAY_LIMITS
        relay_protocol = CircuitV2Protocol(listener_host, limits, allow_hop=False)

        # Start the protocol service properly
        async with background_trio_service(relay_protocol):
            # Connect to relay
            relay_id = relay_host.get_id()
            relay_addrs = list(relay_host.get_addrs())

            if relay_addrs:
                store_relay_addrs(relay_id, relay_addrs, listener_host.get_peerstore())

                try:
                    # Use utility helper to establish the connection to the relay
                    await connect(listener_host, relay_host)
                    logger.info(f"Listener connected to relay {relay_id}")

                    # Wait for reservation to be made
                    await trio.sleep(2.0)

                except Exception as e:
                    logger.warning(f"Failed to connect listener to relay: {e}")

            try:
                yield listener_host
            finally:
                pass


async def echo_stream_handler(stream: ReadWriteCloser) -> None:
    """Simple echo handler for testing."""
    yamux_stream = cast(YamuxStream, stream)
    try:
        while True:
            data = await yamux_stream.read(1024)
            if not data:
                break
            await yamux_stream.write(data)
    except Exception as e:
        logger.debug(f"Echo handler error: {e}")
    finally:
        await yamux_stream.close()
