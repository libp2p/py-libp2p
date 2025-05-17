import json
import logging
from typing import (
    Any,
)

from aiortc import (
    RTCDataChannel,
    RTCPeerConnection,
    RTCSessionDescription,
)
from multiaddr import (
    Multiaddr,
)
import trio
from trio import (
    Event,
    MemoryReceiveChannel,
    MemorySendChannel,
)

from libp2p.abc import (
    IListener,
    THandler,
    TProtocol,
)
from libp2p.host.basic_host import (
    BasicHost,
)

from .connection import (
    WebRTCRawConnection,
)
from .gen_certhash import (
    CertificateManager,
)

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)
SIGNAL_PROTOCOL: TProtocol = TProtocol("/libp2p/webrtc/signal/1.0.0")


class WebRTCListener(IListener):
    def __init__(self, handler: THandler):
        self._handle_stream = handler
        # self.peer_id = peer_id , peer_id: ID
        self.host: BasicHost = None
        self.conn_send_channel: MemorySendChannel[WebRTCRawConnection]
        self.conn_receive_channel: MemoryReceiveChannel[WebRTCRawConnection]
        self.conn_send_channel, self.conn_receive_channel = trio.open_memory_channel(5)
        self.certificate = str

    def set_host(self, host: BasicHost) -> None:
        self.host = host

    async def listen(self, maddr: Multiaddr) -> bool:
        if not self.host:
            raise RuntimeError("Host is not initialized in WebRTCListener")

        self.host.set_stream_handler(
            SIGNAL_PROTOCOL,
            self._handle_stream_wrapper,
        )
        await self.host.get_network().listen(maddr)
        return True

    async def accept(self) -> WebRTCRawConnection:
        return await self.conn_receive_channel.receive()

    async def close(self) -> None:
        await self.conn_send_channel.aclose()
        await self.conn_receive_channel.aclose()

    async def _handle_stream_wrapper(self, stream: trio.SocketStream) -> None:
        try:
            await self._handle_stream_logic(stream)
        except Exception as e:
            logger.exception(f"Error in stream handler: {e}")
        finally:
            await stream.aclose()

    async def _handle_stream_logic(self, stream: trio.SocketStream) -> None:
        pc = RTCPeerConnection()
        channel_ready = Event()

        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel) -> None:
            logger.info(f"DataChannel received: {channel.label}")

            @channel.on("open")
            def on_open() -> None:
                logger.info("DataChannel opened.")
                channel_ready.set()

            self.conn_send_channel.send_nowait(
                WebRTCRawConnection(self.host.get_id(), channel)
            )

        @pc.on("icecandidate")
        async def on_ice_candidate(candidate: Any) -> None:
            if candidate:
                msg = {
                    "type": "ice",
                    "candidateType": candidate.type,
                    "component": candidate.component,
                    "foundation": candidate.foundation,
                    "priority": candidate.priority,
                    "ip": candidate.address,
                    "port": candidate.port,
                    "protocol": candidate.protocol,
                }
                try:
                    await stream.send_all(json.dumps(msg).encode())
                except Exception as e:
                    logger.warning(f"Failed to send ICE candidate: {e}")

        offer_data = await stream.receive_some(4096)
        offer_msg = json.loads(offer_data.decode())
        offer = RTCSessionDescription(**offer_msg)
        await pc.setRemoteDescription(offer)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await stream.send_all(
            json.dumps(
                {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
            ).encode()
        )

        await channel_ready.wait()
        await pc.close()

    def get_addrs(self) -> list[Multiaddr]:
        peer_id = self.host.get_id()
        certhash = CertificateManager()._compute_certhash(self.certificate.x509)

        base = "/ip4/127.0.0.1/tcp/0"
        maddr_str = f"{base}/webrtc-direct/certhash/{certhash}/p2p/{peer_id}"

        try:
            maddr = Multiaddr(maddr_str)
            return [maddr]
        except Exception as e:
            logger.error(f"[WebRTCTransport] Failed to create listen Multiaddr: {e}")
            return []
