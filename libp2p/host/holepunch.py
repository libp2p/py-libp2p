import logging
from libp2p.abc import IHost, INetStream
from libp2p.custom_types import TProtocol
import trio

logger = logging.getLogger("libp2p.host.holepunch")

HOLEPUNCH_PROTOCOL_ID = TProtocol("/libp2p/holepunch/1.0.0")

class HolePunchService:
    """
    Service for libp2p hole punching protocol (/libp2p/holepunch/1.0.0).
    Implements the basic handler and coordination logic for NAT traversal.
    """
    def __init__(self, host: IHost):
        self.host = host
        self.running = False

    async def handle_stream(self, stream: INetStream) -> None:
        """
        Handle an incoming hole punch stream.
        """
        try:
            logger.info("Received hole punch stream from %s", stream.muxed_conn.peer_id)
            # For now, just echo back a message to acknowledge
            data = await stream.read()
            await stream.write(data)
        except Exception as e:
            logger.error("Error in hole punch handler: %s", e)
        finally:
            await stream.close()

    async def start(self) -> None:
        """
        Register the protocol handler and start the service.
        """
        self.host.set_stream_handler(HOLEPUNCH_PROTOCOL_ID, self.handle_stream)
        self.running = True
        logger.info("HolePunchService started and handler registered.")

    async def stop(self) -> None:
        self.host.remove_stream_handler(HOLEPUNCH_PROTOCOL_ID)
        self.running = False
        logger.info("HolePunchService stopped.") 