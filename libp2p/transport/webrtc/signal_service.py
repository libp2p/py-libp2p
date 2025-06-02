from collections.abc import (
    Awaitable,
)
import json
from typing import (
    Callable,
)

from aiortc import (
    RTCIceCandidate,
)

from libp2p.abc import (
    IHost,
    INetStream,
    INotifee,
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)

SIGNAL_PROTOCOL: TProtocol = TProtocol("/libp2p/webrtc/signal/1.0.0")


class SignalService(INotifee):
    def __init__(self, host: IHost):
        self.host = host
        self.signal_protocol = SIGNAL_PROTOCOL
        self._handlers: dict[str, Callable[[dict, str], Awaitable[None]]] = {}

    def set_handler(
        self, msg_type: str, handler: Callable[[dict, str], Awaitable[None]]
    ):
        self._handlers[msg_type] = handler

    async def listen(self):
        self.host.set_stream_handler(self.signal_protocol, self.handle_signal)

    async def handle_signal(self, stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id
        reader = stream

        while True:
            try:
                data = await reader.read(4096)
                if not data:
                    break
                msg = json.loads(data.decode())
                msg_type = msg.get("type")
                if msg_type in self._handlers:
                    await self._handlers[msg_type](msg, str(peer_id))
                else:
                    print(f"No handler for msg type: {msg_type}")
            except Exception as e:
                print(f"Error in signal handler for {peer_id}: {e}")
                break

    async def send_signal(self, peer_id: ID, message: dict):
        try:
            stream = await self.host.new_stream(peer_id, [self.signal_protocol])
            await stream.write(json.dumps(message).encode())
            await stream.close()
        except Exception as e:
            print(f"Failed to send signal to {peer_id}: {e}")

    async def send_offer(self, peer_id: ID, sdp: str, sdp_type: str, certhash: str):
        await self.send_signal(
            peer_id,
            {"type": "offer", "sdp": sdp, "sdpType": sdp_type, "certhash": certhash},
        )

    async def send_answer(self, peer_id: ID, sdp: str, sdp_type: str, certhash: str):
        await self.send_signal(
            peer_id,
            {"type": "answer", "sdp": sdp, "sdpType": sdp_type, "certhash": certhash},
        )

    async def send_ice_candidate(self, peer_id: ID, candidate: RTCIceCandidate):
        await self.send_signal(
            peer_id,
            {
                "type": "ice",
                "candidateType": candidate.type,
                "component": candidate.component,
                "foundation": candidate.foundation,
                "priority": candidate.priority,
                "ip": candidate.ip,
                "port": candidate.port,
                "protocol": candidate.protocol,
                "sdpMid": candidate.sdpMid,
            },
        )

    async def connected(self, network, conn):
        pass

    async def disconnected(self, network, conn):
        pass

    async def opened_stream(self, network, stream):
        pass

    async def closed_stream(self, network, stream):
        pass

    async def listen_close(self, network, multiaddr):
        pass
