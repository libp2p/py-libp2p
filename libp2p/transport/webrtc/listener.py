import json
import logging
from typing import (
    Optional,
)

from aiortc import (
    RTCConfiguration,
    RTCDataChannel,
    RTCIceCandidate,
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
    TProtocol,
)

# from .webrtc import (
#     WebRTCTransport,
# )
from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.peer.id import (
    ID,
)

from .connection import (
    WebRTCRawConnection,
)

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)
SIGNAL_PROTOCOL: TProtocol = TProtocol("/libp2p/webrtc/signal/1.0.0")


class WebRTCListener(IListener):
    def __init__(self):
        self.host: BasicHost = None
        key_pair = create_new_key_pair()
        self.peer_id = ID.from_pubkey(key_pair.public_key)
        # self.transport = WebRTCTransport()
        self.conn_send_channel: MemorySendChannel[WebRTCRawConnection]
        self.conn_receive_channel: MemoryReceiveChannel[WebRTCRawConnection]
        self.conn_send_channel, self.conn_receive_channel = trio.open_memory_channel(10)
        self.certificate = str
        self._listen_addrs: list[
            Multiaddr
        ] = []  # ['/ip4/127.0.0.1/tcp/4001', '/ip4/127.0.0.1/tcp/4034/ws/p2p-circuit']

    def set_host(self, host: BasicHost) -> None:
        self.host = host

    async def listen(self, maddr: Multiaddr) -> None:
        """Listen for both direct and signaled connections"""
        # print(f"Listening on {maddr} + {maddr.protocols}")
        if "webrtc-direct" in maddr:
            await self._listen_direct(maddr)
        else:
            await self.listen_signaled(maddr)

    async def _listen_direct(self, maddr: Multiaddr) -> None:
        """Listen for direct WebRTC connections"""
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))

        @pc.on("datachannel")
        def on_datachannel(channel):
            conn = WebRTCRawConnection(self.peer_id, channel)
            self.conn_send_channel.send_nowait(conn)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            if pc.connectionState == "failed":
                await pc.close()

    async def listen_signaled(self, maddr: Multiaddr) -> bool:
        if not self.host:
            raise RuntimeError("Host is not initialized in WebRTCListener")

        self.host.set_stream_handler(
            SIGNAL_PROTOCOL,
            self._handle_stream_wrapper,
        )
        await self.host.get_network().listen(maddr)
        if maddr not in self._listen_addrs:
            self._listen_addrs.append(maddr)
        return True

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        return tuple(self._listen_addrs)

    async def accept(self) -> WebRTCRawConnection:
        return await self.conn_receive_channel.receive()

    async def _accept_loop(self):
        """Accept incoming connections"""
        while self._listening:
            try:
                # Wait for incoming connections from the transport
                await trio.sleep(0.1)  # Prevent busy waiting

                # Check connection pool for new connections
                for peer_id, channel in self.transport.connection_pool.channels.items():
                    if (
                        channel.readyState == "open"
                        and peer_id not in self._processed_connections
                    ):
                        self._processed_connections.add(peer_id)
                        raw_conn = WebRTCRawConnection(self.transport.peer_id, channel)
                        await self.accept_queue.put(raw_conn)

            except Exception as e:
                logger.error(f"[Listener] Error in accept loop: {e}")
                await trio.sleep(1.0)

    async def close(self) -> None:
        await self.conn_send_channel.aclose()
        await self.conn_receive_channel.aclose()
        logger.info("[Listener] Closed")

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
        async def on_ice_candidate(candidate: Optional[RTCIceCandidate]) -> None:
            if candidate:
                msg = {
                    "type": "ice",
                    "candidateType": candidate.type,
                    "component": candidate.component,
                    "foundation": candidate.foundation,
                    "priority": candidate.priority,
                    "ip": candidate.ip,
                    "port": candidate.port,
                    "protocol": candidate.protocol,
                    "sdpMid": candidate.sdpMid,
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
