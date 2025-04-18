import json
import logging
from typing import (
    Any,
    Tuple,
)
from aiortc import (
    RTCDataChannel,
    RTCPeerConnection,
    RTCSessionDescription,
)
from multiaddr import (
    Multiaddr,
)
from trio import (
    Nursery,
    Event,
    MemoryReceiveChannel,
    MemorySendChannel
)
import trio

from libp2p.abc import (
    IListener,
    TProtocol
)
from libp2p.host.basic_host import (
    BasicHost,
)
from libp2p.peer.id import (
    ID,
)
from .connection import (
    WebRTCRawConnection
) 

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)
SIGNAL_PROTOCOL: TProtocol =  TProtocol("/libp2p/webrtc/signal/1.0.0")


class WebRTCListener(IListener):
    def __init__(self, host: BasicHost, peer_id: ID):
        self.host = host
        self.peer_id = peer_id
        self.conn_send_channel: MemorySendChannel[WebRTCRawConnection]
        self.conn_receive_channel: MemoryReceiveChannel[WebRTCRawConnection]
        self.conn_send_channel, self.conn_receive_channel = trio.open_memory_channel(0)

    async def listen(self, maddr: Multiaddr, nursery: Nursery) -> bool:
        self.host.set_stream_handler(SIGNAL_PROTOCOL, lambda stream: nursery.start_soon(self._handle_stream, stream))
        await self.host.get_network().listen(maddr)
        return True

    async def accept(self) -> WebRTCRawConnection:
        return await self.conn_receive_channel.receive()

    async def close(self) -> None:
        await self.conn_send_channel.aclose()
        await self.conn_receive_channel.aclose()

    async def _handle_stream(self, stream: Any) -> None:
        pc = RTCPeerConnection()
        channel_ready = Event()

        @pc.on("datachannel")
        def on_datachannel(channel: RTCDataChannel) -> None:
            @channel.on("open")
            def opened() -> None:
                channel_ready.set()
            self.conn_send_channel.send_nowait(WebRTCRawConnection(self.peer_id, channel))

        @pc.on("icecandidate")
        def on_ice_candidate(candidate: Any) -> None:
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
                trio.lowlevel.spawn_system_task(stream.write, json.dumps(msg).encode())

        offer_data = await stream.read()
        offer_msg = json.loads(offer_data.decode())
        offer = RTCSessionDescription(**offer_msg)
        await pc.setRemoteDescription(offer)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await stream.write(json.dumps({"sdp": answer.sdp, "type": answer.type}).encode())
        await channel_ready.wait()
        await stream.close()

    def get_addrs(self) -> Tuple[Multiaddr, ...]:
        return (
            Multiaddr(f"/ip4/127.0.0.1/tcp/4001/ws/p2p/{self.peer_id}/p2p-circuit/webrtc"),
        )
