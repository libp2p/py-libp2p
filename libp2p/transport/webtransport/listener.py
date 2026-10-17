"""
WebTransport listener — UDP accept + H3 CONNECT + Noise responder.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aioquic.quic.connection import QuicConnection
from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import THandler
from libp2p.peer.id import ID

from .config import WebTransportConfig
from .connection import (
    WebTransportConnection,
    make_server_quic_config,
    parse_dest_cid,
)
from .multiaddr_utils import build_webtransport_multiaddr, parse_webtransport_multiaddr
from .noise_session import perform_noise_handshake

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _advertised_hosts(listen_host: str, bound_port: int) -> list[str]:
    if listen_host not in ("0.0.0.0", "::"):
        return [listen_host]
    from libp2p.utils.address_validation import get_available_interfaces

    hosts: list[str] = []
    seen: set[str] = set()
    for maddr in get_available_interfaces(bound_port, "udp"):
        ip = (
            maddr.value_for_protocol("ip4")
            if "/ip4/" in str(maddr)
            else maddr.value_for_protocol("ip6")
            if "/ip6/" in str(maddr)
            else None
        )
        if ip is None or ip in seen or ip in ("0.0.0.0", "::"):
            continue
        seen.add(ip)
        hosts.append(ip)
    return hosts or ["127.0.0.1"]


class WebTransportListener(IListener):
    """Listens for inbound libp2p WebTransport sessions."""

    def __init__(
        self,
        handler_function: THandler,
        private_key: PrivateKey,
        config: WebTransportConfig,
        local_peer_id: ID,
    ) -> None:
        self._handler = handler_function
        self._private_key = private_key
        self._config = config
        self._local_peer_id = local_peer_id
        self._cert_manager = config.get_or_create_cert_manager()

        self._listening_addrs: list[Multiaddr] = []
        self._closed = False
        self._socket: trio.socket.SocketType | None = None
        self._connections: dict[bytes, WebTransportConnection] = {}
        self._nursery: trio.Nursery | None = None
        self._nursery_ready = trio.Event()
        self._listen_host = "127.0.0.1"
        self._bound_port = 0

    async def listen(self, maddr: Multiaddr) -> None:
        host, port, _, _ = parse_webtransport_multiaddr(maddr)
        self._listen_host = host

        sock = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
        if host == "::":
            sock = trio.socket.socket(trio.socket.AF_INET6, trio.socket.SOCK_DGRAM)
        await sock.bind((host if host not in ("0.0.0.0", "::") else host, port))
        # Re-read bound port for port 0
        bound = sock.getsockname()
        self._bound_port = int(bound[1])
        self._socket = sock

        async def _run() -> None:
            async with trio.open_nursery() as nursery:
                self._nursery = nursery
                self._nursery_ready.set()
                nursery.start_soon(self._recv_loop)
                await trio.sleep_forever()

        trio.lowlevel.spawn_system_task(_run)
        await self._nursery_ready.wait()

        certhashes = self._cert_manager.advertised_multibase()
        peer_id_str = self._local_peer_id.to_base58()
        for adv_host in _advertised_hosts(host, self._bound_port):
            self._listening_addrs.append(
                build_webtransport_multiaddr(
                    adv_host,
                    self._bound_port,
                    certhashes,
                    peer_id=peer_id_str,
                )
            )
        logger.info(
            "WebTransport listening on %s (peer=%s)",
            self._listening_addrs,
            self._local_peer_id,
        )

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        # Refresh certhashes on advertise in case of rotation
        if not self._listening_addrs:
            return ()
        certhashes = self._cert_manager.advertised_multibase()
        peer_id_str = self._local_peer_id.to_base58()
        refreshed: list[Multiaddr] = []
        for addr in self._listening_addrs:
            host, port, _, _ = parse_webtransport_multiaddr(addr)
            refreshed.append(
                build_webtransport_multiaddr(
                    host, port, certhashes, peer_id=peer_id_str
                )
            )
        self._listening_addrs = refreshed
        return tuple(self._listening_addrs)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for conn in list(self._connections.values()):
            try:
                await conn.close()
            except Exception:
                pass
        self._connections.clear()
        if self._nursery is not None:
            self._nursery.cancel_scope.cancel()
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    async def _recv_loop(self) -> None:
        sock = self._socket
        if sock is None:
            return
        while not self._closed:
            try:
                data, addr = await sock.recvfrom(65535)
            except (OSError, trio.ClosedResourceError):
                break
            try:
                await self._route_datagram(data, addr)
            except Exception:
                logger.debug("Error routing datagram", exc_info=True)

    async def _route_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        dest_cid = parse_dest_cid(data)
        if dest_cid is None:
            return

        conn = self._connections.get(dest_cid)
        if conn is None:
            # Match against known host CIDs
            for existing in self._connections.values():
                if dest_cid in existing.host_cids:
                    conn = existing
                    self._connections[dest_cid] = existing
                    break

        if conn is None:
            # New inbound connection (Initial)
            conn = await self._accept_new_connection(data, addr, dest_cid)
            if conn is None:
                return

        await conn.handle_datagram(data, addr)
        for cid in conn.host_cids:
            self._connections[cid] = conn

    async def _accept_new_connection(
        self,
        data: bytes,
        addr: tuple[str, int],
        dest_cid: bytes,
    ) -> WebTransportConnection | None:
        if self._socket is None or self._nursery is None:
            return None
        self._cert_manager.rotate_if_needed()
        conf = make_server_quic_config(self._config)
        # Client destination CID becomes original_destination_connection_id
        quic = QuicConnection(
            configuration=conf,
            original_destination_connection_id=dest_cid,
        )
        conn = WebTransportConnection(
            quic=quic,
            socket=self._socket,
            remote_addr=addr,
            local_peer_id=self._local_peer_id,
            remote_peer_id=None,
            is_initiator=False,
            config=self._config,
            owns_socket=False,
            nursery=self._nursery,
        )
        conn.host_cids.add(bytes(quic.host_cid))
        self._connections[dest_cid] = conn
        self._connections[bytes(quic.host_cid)] = conn
        conn.attach_nursery(self._nursery)
        await conn.start_pump()
        self._nursery.start_soon(self._handle_inbound, conn)
        return conn

    async def _handle_inbound(self, conn: WebTransportConnection) -> None:
        try:
            noise_stream = await conn.server_wait_session_and_noise_stream()
            remote_peer = await perform_noise_handshake(
                noise_stream,
                local_peer=self._local_peer_id,
                libp2p_privkey=self._private_key,
                is_initiator=False,
                responder_certhashes=self._cert_manager.advertised_multihash_bytes(),
            )
            conn.set_remote_peer_id(remote_peer)
            await conn.start()
            await self._handler(conn)
        except Exception as e:
            logger.warning("Inbound WebTransport handshake failed: %s", e)
            try:
                await conn.close()
            except Exception:
                pass
            # Drop from registry
            for cid, c in list(self._connections.items()):
                if c is conn:
                    self._connections.pop(cid, None)
