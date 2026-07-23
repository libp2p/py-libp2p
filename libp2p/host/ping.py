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
        # See the matching note in _handle_ping: stream.read(n) may return
        # fewer than n bytes even on a healthy connection, so a naive
        # single read() here can misreport a short-but-correct pong as a
        # payload mismatch. read_exactly() blocks until PING_LENGTH bytes
        # are collected (or the connection genuinely closes/resets).
        pong_bytes = await read_exactly(stream, PING_LENGTH)

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
        # `event` must be assigned *before* the try block. `except Exception`
        # below deliberately does not catch trio.Cancelled (a BaseException,
        # by design, so structured concurrency can't be accidentally
        # swallowed) -- if a cancellation fires before `_ping` returns,
        # execution jumps straight to `finally` without ever assigning
        # `event`. finally still runs, though, and referencing an unbound
        # `event` there raises UnboundLocalError *in place of* the
        # propagating Cancelled, which corrupts the enclosing cancel scope's
        # bookkeeping (Trio never sees its own cancellation delivered).
        event: PingEvent | None = None

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
            try:
                await stream.close()
            except Exception as close_error:
                # A failure here must never replace/mask whatever exception
                # (or lack thereof) is already propagating out of this
                # `finally` -- swallow it, but still log it for visibility.
                logger.debug(
                    "Error closing ping stream to %s after ping: %s",
                    peer_id,
                    close_error,
                )
            if event is not None and stream.metric_send_channel is not None:
                await stream.metric_send_channel.send(event)

        return rtts
