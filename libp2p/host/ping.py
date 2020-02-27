import logging
import math
import secrets
import time
from typing import Union

import trio

from libp2p.exceptions import ValidationError
from libp2p.host.host_interface import IHost
from libp2p.network.stream.exceptions import StreamClosed, StreamEOF, StreamReset
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.id import ID as PeerID
from libp2p.typing import TProtocol

ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60

logger = logging.getLogger("libp2p.host.ping")


async def handle_ping(stream: INetStream) -> None:
    """``handle_ping`` responds to incoming ping requests until one side errors
    or closes the ``stream``."""
    peer_id = stream.muxed_conn.peer_id

    while True:
        try:
            should_continue = await _handle_ping(stream, peer_id)
            if not should_continue:
                return
        except Exception:
            await stream.reset()
            return


async def _handle_ping(stream: INetStream, peer_id: PeerID) -> bool:
    """Return a boolean indicating if we expect more pings from the peer at
    ``peer_id``."""
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


class PingService:
    """PingService executes pings and returns RTT in miliseconds."""

    def __init__(self, host: IHost):
        self._host = host

    async def ping(self, peer_id: PeerID) -> int:
        stream = await self._host.new_stream(peer_id, (ID,))
        try:
            rtt = await _ping(stream)
            await _close_stream(stream)
            return rtt
        except Exception:
            await _close_stream(stream)
            raise

    async def ping_loop(
        self, peer_id: PeerID, ping_amount: Union[int, float] = math.inf
    ) -> "PingIterator":
        stream = await self._host.new_stream(peer_id, (ID,))
        ping_iterator = PingIterator(stream, ping_amount)
        return ping_iterator


class PingIterator:
    def __init__(self, stream: INetStream, ping_amount: Union[int, float]):
        self._stream = stream
        self._ping_limit = ping_amount
        self._ping_counter = 0

    def __aiter__(self) -> "PingIterator":
        return self

    async def __anext__(self) -> int:
        if self._ping_counter > self._ping_limit:
            await _close_stream(self._stream)
            raise StopAsyncIteration

        self._ping_counter += 1
        try:
            return await _ping(self._stream)
        except trio.EndOfChannel:
            await _close_stream(self._stream)
            raise StopAsyncIteration


async def _ping(stream: INetStream) -> int:
    ping_bytes = secrets.token_bytes(PING_LENGTH)
    before = int(time.time() * 10 ** 6)  # convert float of seconds to int miliseconds
    await stream.write(ping_bytes)
    pong_bytes = await stream.read(PING_LENGTH)
    rtt = int(time.time() * 10 ** 6) - before
    if ping_bytes != pong_bytes:
        raise ValidationError("Invalid PING response")
    return rtt


async def _close_stream(stream: INetStream) -> None:
    try:
        await stream.close()
    except Exception:
        pass
