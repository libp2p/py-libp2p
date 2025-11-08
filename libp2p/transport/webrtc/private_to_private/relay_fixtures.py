"""
Test fixtures for WebRTC transport with circuit relay infrastructure.
"""

from collections.abc import AsyncIterator
import logging
from typing import Any

import pytest
import trio

from libp2p.host.basic_host import BasicHost
from libp2p.relay.circuit_v2.config import RelayLimits
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol
from libp2p.tools.async_service.trio_service import background_trio_service
from tests.utils.factories import HostFactory

logger = logging.getLogger(__name__)

# Default relay limits for tests
DEFAULT_RELAY_LIMITS = RelayLimits(
    duration=60 * 60,  # 1 hour
    data=1024 * 1024 * 10,  # 10 MB
    max_circuit_conns=8,
    max_reservations=4,
)


@pytest.fixture
def relay_limits() -> RelayLimits:
    """Fixture providing default relay limits."""
    return DEFAULT_RELAY_LIMITS


@pytest.fixture
async def relay_host() -> AsyncIterator[BasicHost]:
    """
    Create a host configured as a circuit relay server.

    Returns:
        BasicHost: Host configured as relay

    """
    async with HostFactory.create_batch_and_listen(1) as hosts:
        relay_host = hosts[0]

        # Set up circuit relay protocol as server
        limits = DEFAULT_RELAY_LIMITS
        relay_protocol = CircuitV2Protocol(relay_host, limits, allow_hop=True)

        # Start the relay protocol using background_trio_service
        # This properly initializes the Service manager
        async with background_trio_service(relay_protocol):
            await trio.sleep(0.1)  # Give it time to start

            try:
                yield relay_host
            finally:
                # Cleanup is handled by background_trio_service context manager
                pass


@pytest.fixture
async def client_host(relay_host: BasicHost) -> AsyncIterator[BasicHost]:
    """
    Create a client host that can connect to the relay.

    Args:
        relay_host: The relay host fixture

    Returns:
        BasicHost: Client host configured to use relay

    """
    async with HostFactory.create_batch_and_listen(1) as hosts:
        client_host = hosts[0]

        # Connect client to relay
        relay_id = relay_host.get_id()
        relay_addrs = relay_host.get_addrs()

        if relay_addrs:
            try:
                # Use network to dial peer
                network = client_host.get_network()
                await network.dial_peer(relay_id)
                logger.info(f"Client connected to relay {relay_id}")
            except Exception as e:
                logger.warning(f"Failed to connect client to relay: {e}")

        yield client_host


@pytest.fixture
async def listener_host(relay_host: BasicHost) -> AsyncIterator[BasicHost]:
    """
    Create a listener host that makes a reservation on the relay.

    Args:
        relay_host: The relay host fixture

    Returns:
        BasicHost: Listener host with circuit relay reservation

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
            relay_addrs = relay_host.get_addrs()

            if relay_addrs:
                try:
                    # Use network to dial peer
                    network = listener_host.get_network()
                    await network.dial_peer(relay_id)
                    logger.info(f"Listener connected to relay {relay_id}")

                    # Wait for reservation to be made
                    await trio.sleep(2.0)

                except Exception as e:
                    logger.warning(f"Failed to connect listener to relay: {e}")

            try:
                yield listener_host
            finally:
                # Cleanup is handled by background_trio_service context manager
                pass


async def echo_stream_handler(stream: Any) -> None:
    """Simple echo handler for testing."""
    try:
        while True:
            data = await stream.read(1024)
            if not data:
                break
            await stream.write(data)
    except Exception as e:
        logger.debug(f"Echo handler error: {e}")
    finally:
        await stream.close()
