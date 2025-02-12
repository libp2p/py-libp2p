import logging
import secrets
import time

import trio

from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)
from libp2p.peer.id import ID as PeerID

ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60

logger = logging.getLogger("libp2p.host.ping")


async def _handle_ping(stream: INetStream, peer_id: PeerID) -> bool:
    """
    Return a boolean indicating if we expect more pings from the peer at ``peer_id``.
    """
    try:
        with trio.fail_after(RESP_TIMEOUT):
            payload = await stream.read(PING_LENGTH)
    except trio.TooSlowError as error:
        logger.debug("Timed out waiting for ping from %s: %s", peer_id, error)
        raise
    except StreamEOF:
        logger.debug("Other side closed while waiting for ping from %s", peer_id)
        return False
    except StreamReset as error:
        logger.debug(
            "Other side reset while waiting for ping from %s: %s", peer_id, error
        )
        raise
    except Exception as error:
        logger.debug("Error while waiting to read ping for %s: %s", peer_id, error)
        raise

    logger.debug("Received ping from %s with data: 0x%s", peer_id, payload.hex())

    try:
        await stream.write(payload)
    except StreamClosed:
        logger.debug("Fail to respond to ping from %s: stream closed", peer_id)
        raise
    return True


async def handle_ping(stream: INetStream) -> None:
    """
    Respond to incoming ping requests until one side errors
    or closes the ``stream``.
    """
    peer_id = stream.muxed_conn.peer_id

    while True:
        try:
            should_continue = await _handle_ping(stream, peer_id)
            if not should_continue:
                await stream.close()
                return
        except Exception:
            await stream.reset()
            return


async def _ping(stream: INetStream) -> int:
    """
    Helper function to perform a single ping operation on a given stream,
    returns integer value rtt - which denotes round trip time for a ping request in ms
    """
    ping_bytes = secrets.token_bytes(PING_LENGTH)
    before = time.time()
    await stream.write(ping_bytes)
    pong_bytes = await stream.read(PING_LENGTH)
    rtt = int((time.time() - before) * (10**6))
    if ping_bytes != pong_bytes:
        logger.debug("invalid pong response")
        raise
    return rtt


class PingService:
    """PingService executes pings and returns RTT in miliseconds."""

    def __init__(self, host: IHost):
        self._host = host

    async def ping(self, peer_id: PeerID, ping_amt: int = 1) -> list[int]:
        stream = await self._host.new_stream(peer_id, [ID])

        try:
            rtts = [await _ping(stream) for _ in range(ping_amt)]
            await stream.close()
            return rtts
        except Exception:
            await stream.close()
            raise
