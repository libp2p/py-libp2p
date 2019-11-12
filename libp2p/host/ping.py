import asyncio
import logging

from libp2p.network.stream.exceptions import StreamEOF, StreamReset
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.id import ID as PeerID
from libp2p.typing import TProtocol

ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60

logger = logging.getLogger("libp2p.host.ping")


async def _handle_ping(stream: INetStream, peer_id: PeerID) -> bool:
    """Return a boolean indicating if we expect more pings from the peer at
    ``peer_id``."""
    try:
        payload = await asyncio.wait_for(stream.read(PING_LENGTH), RESP_TIMEOUT)
    except asyncio.TimeoutError as error:
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

    await stream.write(payload)
    return True


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
