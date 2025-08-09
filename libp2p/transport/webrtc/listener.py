import json
import logging
from typing import (
    Any,
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
    IHost,
    IListener,
    TProtocol,
)
from libp2p.custom_types import (
    THandler,
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
    """
    WebRTC Listener Implementation.
    Handles incoming WebRTC connections for both WebRTC and WebRTC-Direct protocols.
    """

    def __init__(self) -> None:
        self.host: IHost | None = None
        self.handler: THandler | None = None
        self.transport: Any = None
        self.peer_id: ID | None = None
        self._processed_connections: set[str] = set()
        self.accept_queue: Any = None
        self._is_listening = False
        self.conn_send_channel: MemorySendChannel[WebRTCRawConnection]
        self.conn_receive_channel: MemoryReceiveChannel[WebRTCRawConnection]
        self.conn_send_channel, self.conn_receive_channel = trio.open_memory_channel(50)
        self._listen_addrs: list[Multiaddr] = []

    def set_host(self, host: IHost) -> None:
        self.host = host
        self.peer_id = host.get_id()

    async def listen(self, maddr: Any, nursery: trio.Nursery) -> bool:
        """Listen for both direct and signaled connections"""
        if "webrtc-direct" in str(maddr):
            await self._listen_direct(maddr)
        else:
            await self.listen_signaled(maddr)
        return True

    async def _listen_direct(self, maddr: Multiaddr) -> None:
        """Listen for direct WebRTC connections"""
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        if self.peer_id is None:
            raise RuntimeError("peer_id is not set in WebRTCListener")

        def on_datachannel(channel: RTCDataChannel) -> None:
            if self.peer_id is None:
                raise RuntimeError("peer_id is not set in WebRTCListener (datachannel)")
            conn = WebRTCRawConnection(self.peer_id, pc, channel)
            self.conn_send_channel.send_nowait(conn)

        # Register datachannel handler
        pc.on("datachannel", on_datachannel)

        async def on_connectionstatechange() -> None:
            if pc.connectionState == "failed":
                await pc.close()

        # Register connection state handler
        pc.on("connectionstatechange", on_connectionstatechange)

    async def listen_signaled(self, maddr: Multiaddr) -> bool:
        if not self.host:
            raise RuntimeError("Host is not initialized in WebRTCListener")
        self.host.set_stream_handler(
            SIGNAL_PROTOCOL,
            self._handle_stream_wrapper,  # type: ignore
        )
        await self.host.get_network().listen(maddr)
        if maddr not in self._listen_addrs:
            self._listen_addrs.append(maddr)
        return True

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        return tuple(self._listen_addrs)

    async def accept(self) -> WebRTCRawConnection:
        return await self.conn_receive_channel.receive()

    async def _accept_loop(self) -> None:
        """Accept incoming connections"""
        while self._is_listening:
            try:
                await trio.sleep(0.1)
                if self.transport is not None:
                    for peer_id, channel in getattr(
                        self.transport.connection_pool, "channels", {}
                    ).items():
                        if (
                            getattr(channel, "readyState", None) == "open"
                            and peer_id not in self._processed_connections
                        ):
                            self._processed_connections.add(peer_id)
                            if self.peer_id is None:
                                logger.error(
                                    "peer_id is not set, cannot create connection"
                                )
                                continue
                            raw_conn = WebRTCRawConnection(
                                self.peer_id, self.transport, channel
                            )
                            if self.accept_queue is not None:
                                await self.accept_queue.put(raw_conn)
            except Exception as e:
                logger.error(f"[Listener] Error in accept loop: {e}")
                await trio.sleep(1.0)

    async def close(self) -> None:
        await self.conn_send_channel.aclose()
        await self.conn_receive_channel.aclose()
        logger.info("[Listener] Closed")

    async def _handle_stream_wrapper(self, stream: Any) -> None:
        try:
            await self._handle_stream_logic(stream)
        except Exception as e:
            logger.exception(f"Error in stream handler: {e}")
        finally:
            await stream.aclose()

    async def _handle_stream_logic(self, stream: Any) -> None:
        pc = RTCPeerConnection()
        channel_ready = Event()
        if self.host is None:
            raise RuntimeError("Host is not initialized in WebRTCListener")

        def on_datachannel(channel: RTCDataChannel) -> None:
            logger.info(f"DataChannel received: {channel.label}")

            def on_open() -> None:
                logger.info("DataChannel opened.")
                channel_ready.set()

            # Register channel open handler
            channel.on("open", on_open)

            host_id = self.host.get_id() if self.host is not None else None
            if host_id is None:
                raise RuntimeError("Host ID is not set in WebRTCListener (datachannel)")
            self.conn_send_channel.send_nowait(
                WebRTCRawConnection(host_id, pc, channel)
            )

        # Register datachannel handler
        pc.on("datachannel", on_datachannel)

        async def on_ice_candidate(candidate: RTCIceCandidate | None) -> None:
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

        # Register ICE candidate handler
        pc.on("icecandidate", on_ice_candidate)
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
