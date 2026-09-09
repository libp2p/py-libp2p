"""
Per-connection ping probe for connection health monitoring.

Opens a stream on a specific ``INetConn``, negotiates ``/ipfs/ping/1.0.0``,
and measures RTT. Used by :class:`ConnectionHealthMonitor` instead of
``PingService.ping(peer_id)``, which selects the best connection per peer.
"""

from dataclasses import dataclass
import logging

import trio

from libp2p.abc import INetConn, INetStream
from libp2p.host.ping import (
    ID as PING_PROTOCOL,
    perform_ping_roundtrip,
)
from libp2p.protocol_muxer.exceptions import ProtocolNotSupportedError
from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.protocol_muxer.multiselect_communicator import MultiselectCommunicator

logger = logging.getLogger("libp2p.network.health.ping_probe")


@dataclass(frozen=True)
class ConnectionPingResult:
    """Outcome of a health ping against one connection."""

    success: bool
    rtt_ms: float = 0.0
    protocol_supported: bool = False
    skipped: bool = False


async def _close_stream(stream: INetStream) -> None:
    try:
        await stream.close()
    except Exception:
        try:
            await stream.reset()
        except Exception:
            pass


async def ping_connection(
    conn: INetConn,
    *,
    ping_timeout: float,
    negotiate_timeout: int | None = None,
    skip_when_streams_open: bool = False,
) -> ConnectionPingResult:
    """
    Ping a specific connection using ``/ipfs/ping/1.0.0``.

    Parameters
    ----------
    conn:
        The connection to probe (not load-balanced across peers).
    ping_timeout:
        Overall timeout in seconds for the probe.
    negotiate_timeout:
        Multiselect negotiation timeout in seconds. Defaults to ``ping_timeout``.
    skip_when_streams_open:
        When ``True``, skip probing if the connection already has open streams
        and return ``success=True`` with ``skipped=True``.

    """
    if skip_when_streams_open and len(conn.get_streams()) > 0:
        return ConnectionPingResult(success=True, skipped=True)

    if negotiate_timeout is None:
        negotiate_timeout = max(1, int(ping_timeout))

    with trio.move_on_after(ping_timeout) as scope:
        stream: INetStream | None = None
        try:
            stream = await conn.new_stream()
            negotiate_start = trio.current_time()
            communicator = MultiselectCommunicator(stream)
            client = MultiselectClient()
            try:
                await client.select_one_of(
                    [PING_PROTOCOL],
                    communicator,
                    negotiate_timeout,
                )
            except ProtocolNotSupportedError:
                negotiation_rtt_ms = (trio.current_time() - negotiate_start) * 1000
                return ConnectionPingResult(
                    success=True,
                    rtt_ms=negotiation_rtt_ms,
                    protocol_supported=False,
                )

            rtt_ms = float(await perform_ping_roundtrip(stream))
            return ConnectionPingResult(
                success=True,
                rtt_ms=rtt_ms,
                protocol_supported=True,
            )
        except trio.Cancelled:
            raise
        except Exception as error:
            logger.debug("Ping probe failed: %s", error)
            return ConnectionPingResult(success=False)
        finally:
            if stream is not None:
                await _close_stream(stream)

    if scope.cancelled_caught:
        logger.debug("Ping probe timed out after %ss", ping_timeout)
    return ConnectionPingResult(success=False)
