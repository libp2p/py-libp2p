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

logger = logging.getLogger(__name__)


class PingEvent:
    peer_id: PeerID
    rtts: list[int] | None
    failure_error: Exception | None

    def __init__(
        self, peer_id: PeerID, rtts: list[int] | None, failure_error: Exception | None
    ):
        self.peer_id = peer_id
        self.rtts = rtts
        self.failure_error = failure_error


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
    except (StreamReset, Exception) as error:
        logger.debug("Error while waiting for ping from %s: %s", peer_id, error)
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
    Perform a single ping and return the RTT in **milliseconds**.

    Matches go-libp2p's Result.RTT.Milliseconds() convention.
    Raises ValueError if the pong payload does not match the sent ping.
    Raises trio.TooSlowError if the peer takes longer than RESP_TIMEOUT seconds.
    """
    ping_bytes = secrets.token_bytes(PING_LENGTH)

    start = time.monotonic()
    await stream.write(ping_bytes)
    with trio.fail_after(RESP_TIMEOUT):
        pong_bytes = await stream.read(PING_LENGTH)

    rtt = int((time.monotonic() - start) * 1000)  # in milliseconds

    if ping_bytes != pong_bytes:
        logger.debug("invalid pong response")
        raise ValueError(
            f"Ping payload mismatch: sent {ping_bytes.hex()!r}, "
            f"got {pong_bytes.hex()!r}"
        )

    return rtt


class PingService:
    """PingService executes pings and returns RTT in milliseconds (ms).

    Matches go-libp2p convention: Result.RTT.Milliseconds().
    """

    def __init__(self, host: IHost):
        self._host = host

    async def ping(self, peer_id: PeerID, ping_amt: int = 1) -> list[int]:
        if ping_amt < 1:
            raise ValueError(f"ping_amt must be >= 1, got {ping_amt!r}")
        stream = await self._host.new_stream(peer_id, [ID])

        rtts: list[int]
        event: PingEvent

        try:
            rtts = [await _ping(stream) for _ in range(ping_amt)]
            event = PingEvent(
                peer_id=peer_id,
                rtts=rtts,
                failure_error=None,
            )

        except Exception as error:
            event = PingEvent(peer_id=peer_id, rtts=None, failure_error=error)
            raise

        finally:
            await stream.close()
            if stream.metric_send_channel is not None:
                await stream.metric_send_channel.send(event)

        return rtts
