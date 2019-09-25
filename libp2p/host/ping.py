import logging

from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.peer.id import ID

ID = "/ipfs/ping/1.0.0"
PING_LENGTH = 32
RESP_TIMEOUT = 60

logger = logging.getLogger("libp2p.host.ping")


async def _handle_ping(stream: INetStream, peer_id: ID) -> None:
    try:
        payload = await asyncio.wait_for(stream.read(PING_LENGTH), RESP_TIMEOUT)
    except asyncio.TimeoutError as error:
        logger.debug("Timed out waiting for ping from %s: %s", peer_id, error)
        raise
    # TODO: handle the other end closing the stream
    except Exception as error:
        logger.debug("Error while waiting to read ping for %s: %s", peer_id, error)
        raise

    logger.debug("Received ping from %s with data: 0x%s", peer_id, payload.hex())

    await stream.write(payload)


async def handle_ping(self, stream: INetStream) -> None:
    """
    ``handle_ping`` responds to incoming ping requests until one side
    errors or closes the ``stream``.
    """
    peer_id = stream.muxed_conn.peer_id

    while True:
        try:
            await _handle_ping(stream, peer_id)
        except Exception:
            await stream.reset()
            return
