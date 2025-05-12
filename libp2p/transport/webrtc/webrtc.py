import json
import logging
from typing import (
    Any,
    Optional,
)

from aiortc import (
    RTCDataChannel,
    RTCIceCandidate,
    RTCPeerConnection,
    RTCSessionDescription,
)
import anyio.from_thread
from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.abc import (
    ITransport,
    THandler,
    TProtocol,
)
from libp2p.crypto.ed25519 import (
    create_new_key_pair,
)
from libp2p.host.basic_host import (
    IHost,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.pubsub.gossipsub import (
    GossipSub,
)
from libp2p.pubsub.pubsub import (
    Pubsub,
)

from .connection import (
    WebRTCRawConnection,
)
from .gen_certhash import (
    CertificateManager,
    parse_webrtc_maddr,
)
from .listener import (
    WebRTCListener,
)
from .signal_service import (
    SignalService,
)

# from upgrader import TransportUpgrader

logger = logging.getLogger("webrtc")
logging.basicConfig(level=logging.INFO)
SIGNAL_PROTOCOL: TProtocol = TProtocol("/libp2p/webrtc/signal/1.0.0")


class WebRTCTransport(ITransport):
    def __init__(
        self, host: IHost, pubsub: Pubsub, config: Optional[dict[str, Any]] = None
    ):
        self.host = host
        key_pair = create_new_key_pair()
        self.peer_id = ID.from_pubkey(key_pair.public_key)
        self.config = config or {}
        self.certificate = CertificateManager().certificate
        self.data_channel: Optional[RTCDataChannel] = None
        self.connected_peers: dict[str, RTCDataChannel] = {}
        self.pubsub = pubsub
        self._listeners: list[Multiaddr] = []
        self.peer_connection: RTCPeerConnection
        config = {"iceServers": [...], "upgrader": Any}
        self.ice_servers = self.config.get(
            "iceServers",
            [
                {"urls": "stun:stun.l.google.com:19302"},
                {"urls": "stun:stun1.l.google.com:19302"},
            ],
        )

        self.signal_service = SignalService(self.host)
        self.upgrader = self.config.get("upgrader")

    def _create_peer_connection(self) -> RTCPeerConnection:
        return RTCPeerConnection(
            configuration={"iceServers": self.ice_servers},
            certificates=[self.certificate],
        )

    async def start(self) -> None:
        await self.start_peer_discovery()

        async with trio.open_nursery() as nursery:
            nursery.start_soon(self.handle_offer)
        logger.info("[WebRTC] WebRTCTransport started and listening for direct offers")

    async def start_peer_discovery(self) -> None:
        if not self.pubsub:
            gossipsub = GossipSub(
                protocols=[SIGNAL_PROTOCOL], degree=10, degree_low=3, degree_high=15
            )
            self.pubsub = Pubsub(self.host, gossipsub, None)

            topic = await self.pubsub.subscribe("webrtc-peer-discovery")

            async def handle_message() -> None:
                async for msg in topic:
                    logger.info(f"Discovered Peer: {msg.data.decode()}")

            async with trio.open_nursery() as nursery:
                nursery.start_soon(handle_message)
                nursery.start_soon(self.handle_offer)
                logger.info(
                    "[WebRTC] WebRTCTransport started and listening for direct offers"
                )

            await self.pubsub.publish(
                "webrtc-peer-discovery", str(self.peer_id).encode()
            )

    def verify_peer_certificate(self, remote_cert, expected_certhash: str):
        """
        Compute the certhash of the remote certificate and compare to expected.
        """
        cert_mgr = CertificateManager()
        actual_certhash = cert_mgr._compute_certhash(remote_cert)
        if actual_certhash != expected_certhash:
            raise ValueError(
                f"Certhash: expected {expected_certhash}, got {actual_certhash}"
            )

    def verify_peer_id(self, remote_peer_id: str, expected_peer_id: str):
        if remote_peer_id != expected_peer_id:
            raise ValueError(
                f"Peer ID mismatch: expected {expected_peer_id}, got {remote_peer_id}"
            )

    async def create_data_channel(
        self, pc: RTCPeerConnection, label: str = "libp2p-webrtc"
    ) -> RTCDataChannel:
        channel = pc.createDataChannel(label)

        @channel.on("open")
        def on_open() -> None:
            logger.info("[WebRTC] Data channel open with peer")

        @channel.on("message")
        def on_message(message: Any) -> None:
            logger.info(f"[WebRTC] Message received: {message}")

        return channel

    def relay_message(self, message: Any, exclude_peer: Optional[str] = None) -> None:
        """
        Relay incoming message to all other connected peers, excluding the sender.
        """
        for pid, channel in list(self.connected_peers.items()):
            if pid == exclude_peer:
                continue
            if channel.readyState != "open":
                logger.warning(f"[Relay] Channel to {pid} not open. Removing.")
                self.connected_peers.pop(pid, None)
                continue
            try:
                channel.send(message)
                logger.info(f"[Relay] Forwarded message to {pid}")
            except Exception as e:
                logger.exception(f"[Relay] Error sending to {pid}: {e}")
                self.connected_peers.pop(pid, None)

    async def _handle_signal_message(self, peer_id: str, data: dict[str, Any]):
        self.host.get_id()
        msg_type = data.get("type")
        if msg_type == "offer":
            await self._handle_signal_offer(peer_id, data)
        elif msg_type == "answer":
            await self._handle_signal_answer(peer_id, data)
        elif msg_type == "ice":
            await self._handle_signal_ice(peer_id, data)

    async def _handle_signal_offer(self, peer_id: str, data: dict[str, Any]):
        pc = self._create_peer_connection()
        self.peer_connection = pc

        channel_ready = trio.Event()

        @pc.on("datachannel")
        def on_datachannel(channel):
            self.connected_peers[peer_id] = channel

            @channel.on("open")
            def on_open():
                channel_ready.set()

            @channel.on("message")
            def on_message(msg):
                self.relay_message(msg, exclude_peer=peer_id)

        offer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
        await pc.setRemoteDescription(offer)

        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        await self.signal_service.send_answer(
            peer_id,
            {
                "sdp": pc.localDescription.sdp,
                "sdpType": pc.localDescription.type,
                "certhash": CertificateManager()._compute_certhash(
                    self.certificate.x509
                ),
            },
        )
        await channel_ready.wait()

    async def _handle_signal_answer(self, peer_id: str, data: dict[str, Any]):
        answer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
        await self.peer_connection.setRemoteDescription(answer)

    async def _handle_signal_ice(self, peer_id: str, data: dict[str, Any]):
        candidate = RTCIceCandidate(
            component=data["component"],
            foundation=data["foundation"],
            priority=data["priority"],
            ip=data["ip"],
            protocol=data["protocol"],
            port=data["port"],
            type=data["candidateType"],
            sdpMid=data["sdpMid"],
        )
        await self.peer_connection.addIceCandidate(candidate)

    async def handle_answer_from_peer(self, data: dict[str, Any]) -> None:
        answer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
        await self.peer_connection.setRemoteDescription(answer)

    async def handle_ice_candidate(self, data: dict[str, Any]) -> None:
        candidate = RTCIceCandidate(
            component=data["component"],
            foundation=data["foundation"],
            priority=data["priority"],
            ip=data["ip"],
            protocol=data["protocol"],
            port=data["port"],
            type=data["candidateType"],
            sdpMid=data["sdpMid"],
        )
        await self.peer_connection.addIceCandidate(candidate)

    async def create_listener(self, handler_func: THandler) -> WebRTCListener:
        def on_new_stream(stream):
            handler_func(stream)

        pc = self._create_peer_connection()
        channel = await self.create_data_channel(pc, "webrtc-dial")
        channel_ready = trio.Event()

        @channel.on("open")
        def on_open():
            channel_ready.set()

        raw_conn = WebRTCRawConnection(self.peer_id, channel)
        raw_conn.on_stream(on_new_stream)
        if not self.host:
            raise RuntimeError("Host not initialized")
        return WebRTCListener(handler=handler_func)

    async def handle_incoming_candidates(
        self, stream: Any, peer_connection: RTCPeerConnection
    ) -> None:
        while True:
            try:
                raw = await stream.read()
                data: dict[str, Any] = json.loads(raw.decode())
                if data.get("type") == "ice":
                    candidate = RTCIceCandidate(
                        component=data["component"],
                        foundation=data["foundation"],
                        priority=data["priority"],
                        ip=data["ip"],
                        protocol=data["protocol"],
                        port=data["port"],
                        type=data["candidateType"],
                        sdpMid=data["sdpMid"],
                    )
                    await peer_connection.addIceCandidate(candidate)
            except Exception as e:
                logger.error(f"[ICE Trickling] Error reading ICE candidate: {e}")
                await stream.close()
                break

    async def dial(self, maddr: Multiaddr) -> WebRTCRawConnection:
        _, peer_id, certhash = parse_webrtc_maddr(maddr)
        stream = await self.host.new_stream(peer_id, [SIGNAL_PROTOCOL])

        pc = self._create_peer_connection()
        channel = await self.create_data_channel(pc, "webrtc-dial")
        channel_ready = trio.Event()
        self.connected_peers[peer_id] = channel
        # cert_pem= CertificateManager()
        # cert: CertificateManager = cert_pem.generate_self_signed_cert()
        # print(f"Certificate PEM: {cert}")

        @channel.on("open")
        def on_open():
            channel_ready.set()

        @channel.on("message")
        def on_message(msg):
            logger.info(f"[Relay] Received from {peer_id}: {msg}")
            self.relay_message(msg, exclude_peer=peer_id)

        @pc.on("icecandidate")
        def on_ice_candidate(candidate: Optional[RTCIceCandidate]) -> None:
            if candidate:
                msg = {
                    "type": "ice",
                    "candidateType": candidate.type,
                    "component": candidate.component,
                    "foundation": candidate.foundation,
                    "priority": candidate.priority,
                    "port": candidate.port,
                    "protocol": candidate.protocol,
                    "ip": candidate.ip,
                    "sdpMid": candidate.sdpMid,
                }
                trio.lowlevel.spawn_system_task(stream.write, json.dumps(msg).encode())

        trio.lowlevel.spawn_system_task(self.handle_incoming_candidates, stream, pc)

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        try:
            #   await self.signal_service.send_offer(peer_id, offer)
            await self.signal_service.send_offer(
                peer_id,
                {
                    "sdp": pc.localDescription.sdp,
                    "sdpType": pc.localDescription.type,
                    "certhash": CertificateManager()._compute_certhash(
                        self.certificate.x509
                    ),
                },
            )
        except Exception as e:
            logger.error(f"[Signaling] Failed to send offer to {peer_id}: {e}")
            await stream.close()
            raise

        await channel_ready.wait()
        remote_cert = CertificateManager.getFingerprints()  # remote cert for comparison
        if not remote_cert:
            raise ValueError("No remote certificate received")
        remote_cert = remote_cert[0]
        self.verify_peer_certificate(remote_cert, certhash)
        self.verify_peer_id(peer_id, str(self.peer_id))

        await stream.write(
            json.dumps(
                {
                    "type": "offer",
                    "peer_id": self.peer_id,
                    "sdp": offer.sdp,
                    "sdpType": offer.type,
                    "certhash": CertificateManager()._compute_certhash(
                        self.certificate.x509
                    ),
                }
            ).encode()
        )

        try:
            answer_data = await stream.read()
            answer_msg: dict[str, Any] = json.loads(answer_data.decode())
            answer = RTCSessionDescription(**answer_msg)
            await pc.setRemoteDescription(answer)
        except Exception as e:
            logger.error(
                f"[Signaling] Failed to receive or process answer from {peer_id}: {e}"
            )
            await stream.close()
            raise

        await channel_ready.wait()
        raw_conn = WebRTCRawConnection(self.peer_id, channel)
        logical_stream = await raw_conn.open_stream()
        if self.upgrader:
            upgraded_conn = await self.upgrader.upgrade_connection(logical_stream)
            return upgraded_conn
        else:
            return logical_stream

    async def webrtc_direct_dial(self, maddr: Multiaddr) -> WebRTCRawConnection:
        protocols = [p.name for p in maddr.protocols()]
        if "webrtc-direct" in protocols:
            logger.info("[Dial] Detected /webrtc-direct multiaddr....")

            ip, peer_id, certhash = parse_webrtc_maddr(maddr)
            if not ip or not peer_id:
                raise ValueError("Missing IP or Peer ID in webrtc-direct multiaddr")
            logger.info(
                f"Parsed IP={ip}, PeerID={peer_id}, Certhash={certhash or 'None'}"
            )

            pc = self._create_peer_connection()
            channel = await self.create_data_channel(
                pc, label="py-libp2p-webrtc-direct"
            )
            channel_ready = trio.Event()
            self.connected_peers[peer_id] = channel

            @channel.on("open")
            def on_open() -> None:
                logger.info(f"[webrtc-direct] Channel open with {peer_id}")
                channel_ready.set()

            @channel.on("message")
            def on_message(msg: Any) -> None:
                logger.info(f"[Relay] Received from {peer_id}: {msg}")
                self.relay_message(msg, exclude_peer=peer_id)

            offer = await anyio.from_thread.run_sync(pc.createOffer)
            await anyio.from_thread.run_sync(pc.setLocalDescription, offer)

            if self.pubsub is None:
                await self.start_peer_discovery()
            await self.pubsub.publish(
                f"webrtc-offer-{peer_id}",
                json.dumps(
                    {
                        "peer_id": self.peer_id,
                        "sdp": offer.sdp,
                        "sdpType": offer.type,
                        "certhash": CertificateManager()._compute_certhash(
                            self.certificate.x509
                        ),
                    }
                ).encode(),
            )

            logger.info(f"[webrtc-direct] Sent offer to peer {self.peer_id} via pubsub")

            topic = await self.pubsub.subscribe(f"webrtc-answer-{self.peer_id}")
            async for msg in topic:
                answer_data = json.loads(msg.data.decode())
                answer = RTCSessionDescription(**answer_data)
                # await pc.setRemoteDescription(answer)
                await anyio.from_thread.run_sync(pc.setRemoteDescription, answer)
                break

            await channel_ready.wait()
            raw_conn = WebRTCRawConnection(peer_id, channel)
            if self.upgrader:
                upgraded_conn = await self.upgrader.upgrade_connection(raw_conn)
                return upgraded_conn
            else:
                return raw_conn
        else:
            logger.info("[Dial] Falling back to regular signal-based WebRTC")
            return await self.dial(maddr)

    async def handle_offer(self):
        logger.info("[signal] Listening for incoming offers via SignalService")
        # await self.signal_service.listen()

        async def _on_offer(msg):
            try:
                data = json.loads(msg.data.decode())
                remote_peer_id = data["peer_id"]
                offer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])

                pc = self._create_peer_connection()
                logger.info(
                    f"[webrtc-direct] Received offer from peer {remote_peer_id}"
                )
                channel_ready = trio.Event()

                @pc.on("datachannel")
                def on_datachannel(channel):
                    logger.info(
                        f"[webrtc-direct] Datachannel received from {remote_peer_id}"
                    )
                    self.connected_peers[remote_peer_id] = channel

                    @channel.on("open")
                    def on_open():
                        logger.info(
                            f"[webrtc-direct] Channel open with {remote_peer_id}"
                        )
                        channel_ready.set()

                    @channel.on("message")
                    def on_message(msg):
                        logger.info(f"[Relay] Received from {remote_peer_id}: {msg}")
                        self.relay_message(msg, exclude_peer=remote_peer_id)

                offer = RTCSessionDescription(sdp=data["sdp"], type=data["sdpType"])
                await pc.setRemoteDescription(offer)
                remote_cert = self.peer_connection.getRemoteCertificates()[0]
                expected_certhash = data.get("certhash")
                self.verify_peer_certificate(remote_cert, expected_certhash)
                self.verify_peer_id(remote_peer_id, str(self.peer_id))

                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)

                response_topic = f"webrtc-answer-{remote_peer_id}"
                await self.pubsub.publish(
                    response_topic,
                    json.dumps(
                        {
                            "peer_id": str(self.peer_id),
                            "sdp": pc.localDescription.sdp,
                            "sdpType": pc.localDescription.type,
                            "certhash": CertificateManager()._compute_certhash(
                                self.certificate.x509
                            ),
                        }
                    ).encode(),
                )
                logger.info(f"ans sent to peer {remote_peer_id} via {response_topic}")
                await channel_ready.wait()

            except Exception as e:
                logger.error(f"[webrtc-direct] Error handling offer: {e}")

            offer_topic = f"webrtc-offer-{remote_peer_id}"
            logger.info(f"[webrtc-direct] Subscribing to topic: {offer_topic}")
            topic = await self.pubsub.subscribe(offer_topic)

            async for msg in topic:
                await _on_offer(msg)
