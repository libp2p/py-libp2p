import logging
import secrets
import time
from collections.abc import AsyncIterator

import trio

from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.io.exceptions import (
    IncompleteReadError,
)
from libp2p.io.utils import (
    read_exactly,
)
from libp2p.network.stream.exceptions import (
    StreamClosed,
    StreamEOF,
    StreamReset,
)
from libp2p.peer.id import ID as PeerID

ID = TProtocol("/ipfs/ping/1.0.0")
SERVICE_NAME = "libp2p.ping"
PING_LENGTH = 32
RESP_TIMEOUT = 10

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
            # NOTE: stream.read(n) is a *short read* -- both the Mplex and
            # Yamux muxed-stream implementations document/return "up to n
            # bytes currently available", not "exactly n bytes". A 32-byte
            # ping that a peer (or the OS/transport) delivers in more than
            # one chunk would otherwise be silently truncated here. Use
            # read_exactly() (already relied on by msgio/varint/yamux's own
            # frame parsing) to block until the full PING_LENGTH is in hand.
            payload = await read_exactly(stream, PING_LENGTH)
    except trio.TooSlowError as error:
        logger.debug("Timed out waiting for ping from %s: %s", peer_id, error)
        raise
    except StreamEOF:
        logger.debug("Other side closed while waiting for ping from %s", peer_id)
        return False
    except IncompleteReadError as error:
        if error.is_clean_close:
            # Peer closed the stream cleanly between pings; same as StreamEOF.
            logger.debug(
                "Other side closed while waiting for ping from %s", peer_id
            )
            return False
        logger.debug(
            "Truncated ping from %s: expected %d bytes, got %d: %s",
            peer_id,
            error.expected_bytes,
            error.received_bytes,
            error,
        )
        raise
    except (StreamReset, Exception) as error:
        logger.debug("Error while waiting for ping from %s: %s", peer_id, error)
        raise

    logger.debug("Received ping from %s with data: 0x%s", peer_id, payload.hex())

    try:
        with trio.fail_after(RESP_TIMEOUT):
            await stream.write(payload)
    except trio.TooSlowError:
        logger.debug("Timed out writing ping response to %s", peer_id)
        raise
    except StreamClosed:
        logger.debug("Fail to respond to ping from %s: stream closed", peer_id)
        raise
    return True


async def _ping(stream: INetStream, cancel_scope: trio.CancelScope | None = None) -> int:
    """
    Perform a single ping and return the RTT in **milliseconds**.

    Matches go-libp2p's Result.RTT.Milliseconds() convention.
    Raises ValueError if the pong payload does not match the sent ping.
    Raises trio.TooSlowError if the peer takes longer than RESP_TIMEOUT seconds.
    """
    ping_bytes = secrets.token_bytes(PING_LENGTH)

    start = time.monotonic()
    
    with cancel_scope or trio.CancelScope():
        with trio.fail_after(RESP_TIMEOUT):
            await stream.write(ping_bytes)
            # See the matching note in _handle_ping: stream.read(n) may return
            # fewer than n bytes even on a healthy connection, so a naive
            # single read() here can misreport a short-but-correct pong as a
            # payload mismatch. read_exactly() blocks until PING_LENGTH bytes
            # are collected (or the connection genuinely closes/resets).
            pong_bytes = await read_exactly(stream, PING_LENGTH)

    rtt = int((time.monotonic() - start) * 1000)  # in milliseconds

    if ping_bytes != pong_bytes:
        logger.debug("invalid pong response")
        await stream.reset()
        raise ValueError(
            f"Ping payload mismatch: sent {ping_bytes.hex()!r}, "
            f"got {pong_bytes.hex()!r}"
        )

    return rtt


class PingService:
    """PingService executes pings and returns RTT in milliseconds (ms).

    Matches go-libp2p convention: Result.RTT.Milliseconds().
    """

    def __init__(self, host: IHost, rcmgr=None):
        self._host = host
        self._rcmgr = rcmgr
        self._outbound_streams: dict[PeerID, INetStream] = {}
        self._inbound_streams: dict[PeerID, set[INetStream]] = {}
        self._lock = trio.Lock()

    async def handle_ping(self, stream: INetStream) -> None:
        """
        Respond to incoming ping requests until one side errors
        or closes the ``stream``.
        """
        peer_id = stream.muxed_conn.peer_id

        async with self._lock:
            peer_streams = self._inbound_streams.setdefault(peer_id, set())
            if len(peer_streams) >= 2:
                logger.debug("Rejecting ping stream from %s: max 2 reached", peer_id)
                await stream.reset()
                return
            peer_streams.add(stream)

        try:
            while True:
                try:
                    should_continue = await _handle_ping(stream, peer_id)
                    if not should_continue:
                        await stream.close()
                        return
                except trio.TooSlowError:
                    # The peer simply stopped pinging within RESP_TIMEOUT -- this is
                    # not a protocol violation. go-libp2p's handler closes the
                    # stream when its own idle timer fires (rather than resetting),
                    # so match that: Reset signals an abnormal/error termination to
                    # the remote peer, which an idle timeout is not.
                    logger.debug(
                        "Idle timeout waiting for ping from %s, closing stream", peer_id
                    )
                    try:
                        await stream.close()
                    except Exception as close_error:
                        logger.debug(
                            "Error closing idle ping stream to %s: %s",
                            peer_id,
                            close_error,
                        )
                    return
                except Exception:
                    await stream.reset()
                    return
        finally:
            async with self._lock:
                self._inbound_streams.get(peer_id, set()).discard(stream)


    async def ping_iter(self, peer_id: PeerID, ping_amt: int = 1, cancel_scope: trio.CancelScope | None = None) -> AsyncIterator[int]:
        if ping_amt < 1:
            raise ValueError(f"ping_amt must be >= 1, got {ping_amt!r}")

        async with self._lock:
            stream = self._outbound_streams.get(peer_id)
            if stream is None or stream.is_closed():
                stream = await self._host.new_stream(peer_id, [ID])
                self._outbound_streams[peer_id] = stream

        event: PingEvent | None = None
        rtts: list[int] = []

        try:
            for _ in range(ping_amt):
                rtt = await _ping(stream, cancel_scope=cancel_scope)
                rtts.append(rtt)
                yield rtt
            event = PingEvent(peer_id=peer_id, rtts=rtts, failure_error=None)
        except Exception as error:
            event = PingEvent(peer_id=peer_id, rtts=None, failure_error=error)
            raise
        finally:
            if event is not None and getattr(stream, 'metric_send_channel', None) is not None:
                with trio.move_on_after(1):
                    await stream.metric_send_channel.send(event)

    async def ping(self, peer_id: PeerID, ping_amt: int = 1) -> list[int]:
        """
        Legacy support for callers expecting a list of RTTs.
        """
        rtts = []
        async for rtt in self.ping_iter(peer_id, ping_amt=ping_amt):
            rtts.append(rtt)
        return rtts
