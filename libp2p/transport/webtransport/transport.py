"""
WebTransport transport (``/quic-v1/webtransport``).

Provides native stream multiplexing after Noise XX on the first client-opened
WebTransport stream. Sets ``provides_native_muxing = True``.

Spec: https://github.com/libp2p/specs/blob/master/webtransport/README.md
"""

from __future__ import annotations

import logging

from aioquic.quic.connection import QuicConnection
from multiaddr import Multiaddr
import trio

from libp2p.abc import ITransport
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import THandler
from libp2p.peer.id import ID

from .certificate import multihash_from_multibase
from .config import WebTransportConfig
from .connection import WebTransportConnection, make_client_quic_config
from .exceptions import WebTransportConnectionError
from .listener import WebTransportListener
from .multiaddr_utils import is_webtransport_multiaddr, parse_webtransport_multiaddr
from .noise_session import perform_noise_handshake

logger = logging.getLogger(__name__)


class WebTransportTransport(ITransport):
    """libp2p transport for WebTransport over HTTP/3."""

    provides_native_muxing: bool = True

    def __init__(
        self,
        private_key: PrivateKey,
        config: WebTransportConfig | None = None,
    ) -> None:
        self._private_key = private_key
        self._config = config or WebTransportConfig()
        self._local_peer_id = ID.from_pubkey(private_key.get_public_key())
        self._closed = False
        self._listeners: list[WebTransportListener] = []
        self._nursery: trio.Nursery | None = None
        self._nursery_ready = trio.Event()
        self._connections: list[WebTransportConnection] = []

    def set_background_nursery(self, nursery: trio.Nursery) -> None:
        """Optional: reuse a swarm-owned nursery for dial pumps."""
        self._nursery = nursery
        self._nursery_ready.set()

    async def _ensure_nursery(self) -> trio.Nursery:
        if self._nursery is not None:
            return self._nursery

        async def _run() -> None:
            async with trio.open_nursery() as nursery:
                self._nursery = nursery
                self._nursery_ready.set()
                await trio.sleep_forever()

        trio.lowlevel.spawn_system_task(_run)
        await self._nursery_ready.wait()
        assert self._nursery is not None
        return self._nursery

    def can_dial(self, maddr: Multiaddr) -> bool:
        return is_webtransport_multiaddr(maddr)

    def can_listen(self, maddr: Multiaddr) -> bool:
        return is_webtransport_multiaddr(maddr)

    def protocols(self) -> list[str]:
        return ["webtransport"]

    def listen_order(self) -> int:
        return 1

    def create_listener(self, handler_function: THandler) -> WebTransportListener:
        listener = WebTransportListener(
            handler_function=handler_function,
            private_key=self._private_key,
            config=self._config,
            local_peer_id=self._local_peer_id,
        )
        self._listeners.append(listener)
        return listener

    async def dial(self, maddr: Multiaddr) -> WebTransportConnection:
        if not is_webtransport_multiaddr(maddr):
            raise WebTransportConnectionError(f"Not a WebTransport multiaddr: {maddr}")
        if self._closed:
            raise WebTransportConnectionError("Transport is closed")

        host, port, certhash_mbs, peer_id_str = parse_webtransport_multiaddr(maddr)
        if not certhash_mbs:
            raise WebTransportConnectionError(
                f"WebTransport multiaddr missing certhash: {maddr}"
            )
        dial_hashes = [multihash_from_multibase(h) for h in certhash_mbs]
        remote_peer: ID | None = ID.from_base58(peer_id_str) if peer_id_str else None

        nursery = await self._ensure_nursery()
        conf = make_client_quic_config(self._config)
        conf.server_name = host
        quic = QuicConnection(configuration=conf)

        sock = trio.socket.socket(
            trio.socket.AF_INET6 if ":" in host else trio.socket.AF_INET,
            trio.socket.SOCK_DGRAM,
        )
        # Bind ephemeral local port
        await sock.bind(("" if ":" not in host else "::", 0))

        remote_addr = (host, port)
        conn = WebTransportConnection(
            quic=quic,
            socket=sock,
            remote_addr=remote_addr,
            local_peer_id=self._local_peer_id,
            remote_peer_id=remote_peer,
            is_initiator=True,
            config=self._config,
            maddr=maddr,
            owns_socket=True,
            nursery=nursery,
        )
        self._connections.append(conn)
        conn.attach_nursery(nursery)
        await conn.start_pump()

        try:
            import time as _time

            quic.connect(remote_addr, now=_time.time())
            await conn.transmit()

            noise_stream = await conn.client_open_session(authority=f"{host}:{port}")

            used = conn.used_cert_multihash
            if used is None:
                # Wait a tick for cert extraction after handshake
                await conn.wait_handshake()
                used = conn.used_cert_multihash
            if used is None:
                raise WebTransportConnectionError(
                    "Could not extract peer TLS certificate"
                )
            if used not in dial_hashes:
                raise WebTransportConnectionError(
                    "Peer TLS certificate hash does not match multiaddr certhash"
                )

            authenticated = await perform_noise_handshake(
                noise_stream,
                local_peer=self._local_peer_id,
                libp2p_privkey=self._private_key,
                is_initiator=True,
                remote_peer=remote_peer,
                used_cert_multihash=used,
                dial_certhashes=dial_hashes,
            )
            conn.set_remote_peer_id(authenticated)
            await conn.start()
            logger.info("WebTransport dial succeeded to %s", authenticated)
            return conn
        except Exception:
            try:
                await conn.close()
            except Exception:
                pass
            raise

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        async with trio.open_nursery() as nursery:
            for conn in self._connections:
                nursery.start_soon(conn.close)
            for listener in self._listeners:
                nursery.start_soon(listener.close)
        self._connections.clear()
        self._listeners.clear()
        if self._nursery is not None:
            self._nursery.cancel_scope.cancel()
            self._nursery = None
