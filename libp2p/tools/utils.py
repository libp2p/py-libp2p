from collections.abc import (
    Awaitable,
    Callable,
)
import logging

import trio

from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.network.stream.exceptions import (
    StreamError,
)
from libp2p.network.swarm import (
    Swarm,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

from .constants import (
    MAX_READ_LEN,
)


async def connect_swarm(swarm_0: Swarm, swarm_1: Swarm) -> None:
    peer_id = swarm_1.get_peer_id()
    addrs = tuple(
        addr
        for transport in swarm_1.listeners.values()
        for addr in transport.get_addrs()
    )
    swarm_0.peerstore.add_addrs(peer_id, addrs, 10000)

    # Add retry logic for more robust connection
    max_retries = 3
    retry_delay = 0.2
    last_error = None

    for attempt in range(max_retries):
        try:
            await swarm_0.dial_peer(peer_id)

            # Verify connection is established in both directions
            if (
                swarm_0.get_peer_id() in swarm_1.connections
                and swarm_1.get_peer_id() in swarm_0.connections
            ):
                return

            # Connection partially established, wait a bit for it to complete
            await trio.sleep(0.1)

            if (
                swarm_0.get_peer_id() in swarm_1.connections
                and swarm_1.get_peer_id() in swarm_0.connections
            ):
                return

            logging.debug(
                "Swarm connection verification failed on attempt"
                + f" {attempt + 1}, retrying..."
            )

        except Exception as e:
            last_error = e
            logging.debug(f"Swarm connection attempt {attempt + 1} failed: {e}")
            await trio.sleep(retry_delay)

    # If we got here, all retries failed
    if last_error:
        raise RuntimeError(
            f"Failed to connect swarms after {max_retries} attempts"
        ) from last_error
    else:
        err_msg = (
            "Failed to establish bidirectional swarm connection"
            + f" after {max_retries} attempts"
        )
        raise RuntimeError(err_msg)


async def connect(node1: IHost, node2: IHost) -> None:
    """Connect node1 to node2."""
    addr = node2.get_addrs()[0]
    info = info_from_p2p_addr(addr)

    # Add retry logic for more robust connection with timeout
    max_retries = 3
    retry_delay = 0.2
    last_error = None

    for attempt in range(max_retries):
        try:
            # Use timeout for each connection attempt
            with trio.move_on_after(5):  # 5 second timeout
                await node1.connect(info)

            # Verify connection is established in both directions
            if (
                node2.get_id() in node1.get_network().connections
                and node1.get_id() in node2.get_network().connections
            ):
                return

            # Connection partially established, wait a bit for it to complete
            await trio.sleep(0.1)

            if (
                node2.get_id() in node1.get_network().connections
                and node1.get_id() in node2.get_network().connections
            ):
                return

            logging.debug(
                f"Connection verification failed on attempt {attempt + 1}, retrying..."
            )

        except Exception as e:
            last_error = e
            logging.debug(f"Connection attempt {attempt + 1} failed: {e}")
            await trio.sleep(retry_delay)

    # If we got here, all retries failed
    if last_error:
        raise RuntimeError(
            f"Failed to connect after {max_retries} attempts"
        ) from last_error
    else:
        err_msg = (
            f"Failed to establish bidirectional connection after {max_retries} attempts"
        )
        raise RuntimeError(err_msg)


def create_echo_stream_handler(
    ack_prefix: str,
) -> Callable[[INetStream], Awaitable[None]]:
    async def echo_stream_handler(stream: INetStream) -> None:
        while True:
            try:
                read_string = (await stream.read(MAX_READ_LEN)).decode()
            except StreamError:
                break

            resp = ack_prefix + read_string
            try:
                await stream.write(resp.encode())
            except StreamError:
                break

    return echo_stream_handler
