"""
WebRTC Direct listener.

Runs a lightweight HTTP signaling server on TCP (same port number as the
WebRTC UDP endpoint) that accepts SDP offers and returns answers.  After
the SDP exchange each incoming connection completes ICE/DTLS, a Noise XX
handshake over data-channel 0 (the listener is the Noise *initiator*, per
spec), and then hands the fully-authenticated :class:`WebRTCConnection` to
the registered handler on the trio side.

Threading model: aiortc runs on the :class:`AsyncioBridge` thread; the Noise
handshake and the handler run on trio inside a listener-owned nursery
(started as a system task, like the TCP listener). The asyncio → trio hop is
``trio.from_thread.run_sync(nursery.start_soon, ...)`` — non-blocking, so
the asyncio loop keeps servicing the data-channel callbacks the handshake
needs.

Published multiaddr format::

    /ip4/<bound-ip>/udp/<bound-port>/webrtc-direct/certhash/<hash>/p2p/<peer-id>

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc-direct.md
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any

from multiaddr import Multiaddr
import trio

from libp2p.abc import IListener
from libp2p.crypto.keys import PrivateKey
from libp2p.custom_types import THandler
from libp2p.peer.id import ID

from .certificate import WebRTCCertificate
from .config import WebRTCTransportConfig
from .connection import WebRTCConnection
from .exceptions import WebRTCConnectionError
from .multiaddr_utils import (
    build_webrtc_direct_multiaddr,
    parse_webrtc_direct_multiaddr,
)

if TYPE_CHECKING:
    from ._asyncio_bridge import AsyncioBridge

logger = logging.getLogger(__name__)


class WebRTCDirectListener(IListener):
    """
    Listens for incoming WebRTC Direct connections.

    Created by :meth:`WebRTCDirectTransport.create_listener`.
    """

    def __init__(
        self,
        handler_function: THandler,
        private_key: PrivateKey,
        certificate: WebRTCCertificate,
        config: WebRTCTransportConfig,
        bridge_factory: Callable[[], Awaitable[Any]],
        local_peer_id: ID,
    ) -> None:
        self._handler = handler_function
        self._private_key = private_key
        self._certificate = certificate
        self._config = config
        self._bridge_factory = bridge_factory
        self._local_peer_id = local_peer_id

        self._listening_addrs: list[Multiaddr] = []
        self._closed = False
        self._signaling_server: asyncio.Server | None = None
        self._bridge: AsyncioBridge | None = None

        # trio side: long-lived nursery for inbound handshakes/handlers.
        self._trio_token: trio.lowlevel.TrioToken | None = None
        self._nursery: trio.Nursery | None = None
        self._nursery_ready = trio.Event()
        self._nursery_done = trio.Event()
        # Bound the number of not-yet-authenticated inbound connections.
        # ponytail: soft cap — updated from both the asyncio and trio threads
        # (GIL-atomic int ops); use a lock if it ever needs to be exact.
        self._in_flight = 0

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Start listening for incoming WebRTC Direct connections.

        Starts an HTTP signaling server on TCP that accepts SDP offers.
        The published multiaddr advertises the same port on UDP (for
        WebRTC data channels) and includes the DTLS certificate hash.

        :param maddr: A ``/webrtc-direct`` multiaddr.
        :raises WebRTCConnectionError: If binding fails.
        """
        host, port, _certhash, _peer_id = parse_webrtc_direct_multiaddr(maddr)
        bridge = await self._bridge_factory()
        self._bridge = bridge

        rtc_cert = getattr(self._certificate, "_rtc_certificate", None)
        if rtc_cert is None:
            raise WebRTCConnectionError(
                "WebRTC certificate was not generated via aiortc"
            )

        await self._start_trio_nursery()

        from ._aiortc_helpers import run_signaling_server

        # Start HTTP signaling server on asyncio thread.
        # Binds TCP on the same port as the WebRTC UDP endpoint.
        self._signaling_server = await bridge.run_coro(
            run_signaling_server(
                host=host if host != "0.0.0.0" else "0.0.0.0",
                port=port,
                on_offer=self._make_offer_handler(bridge, rtc_cert),
            )
        )

        # Determine the actual bound port (if port was 0).
        bound_port = port
        if self._signaling_server.sockets:
            sock = self._signaling_server.sockets[0]
            bound_port = sock.getsockname()[1]

        # Build advertised multiaddr with certhash and peer ID.
        certhash_mb = self._certificate.fingerprint_to_multibase()
        advertised_host = host if host != "0.0.0.0" else "127.0.0.1"
        advertised = build_webrtc_direct_multiaddr(
            host=advertised_host,
            port=bound_port,
            certhash_multibase=certhash_mb,
            peer_id=self._local_peer_id.to_base58(),
        )
        self._listening_addrs.append(advertised)
        logger.info("WebRTC Direct listener on %s", advertised)

    async def _start_trio_nursery(self) -> None:
        """
        Open a listener-owned nursery in a trio system task.

        ``IListener.listen`` takes no nursery, so (like the TCP listener) we
        spawn a system task that holds one open until :meth:`close`.
        """
        if self._nursery is not None:
            return
        self._trio_token = trio.lowlevel.current_trio_token()

        async def _run() -> None:
            try:
                async with trio.open_nursery() as nursery:
                    self._nursery = nursery
                    self._nursery_ready.set()
                    await trio.sleep_forever()
            finally:
                self._nursery = None
                self._nursery_done.set()

        trio.lowlevel.spawn_system_task(_run)
        await self._nursery_ready.wait()

    def _make_offer_handler(
        self,
        bridge: AsyncioBridge,
        rtc_cert: Any,
    ) -> Callable[..., Any]:
        """Build the async handler called for each incoming SDP offer."""

        async def _handle_offer(offer_sdp: str) -> str:
            from aiortc import RTCSessionDescription

            from ._aiortc_helpers import (
                create_noise_channel,
                create_peer_connection,
                make_noise_channel_callbacks,
            )

            if self._in_flight >= self._config.max_in_flight_connections:
                raise WebRTCConnectionError(
                    "Too many in-flight inbound WebRTC connections"
                )
            self._in_flight += 1

            try:
                # Create PC, set remote (offer), create answer.
                pc = await create_peer_connection(rtc_cert)
                noise_ch = await create_noise_channel(pc)
                noise_send, noise_recv, _ = make_noise_channel_callbacks(noise_ch)

                offer = RTCSessionDescription(sdp=offer_sdp, type="offer")
                await pc.setRemoteDescription(offer)

                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                answer_sdp = pc.localDescription.sdp
            except BaseException:
                self._in_flight -= 1
                raise

            # Spawn background task to complete the connection after ICE.
            asyncio.ensure_future(
                self._complete_inbound(pc, bridge, noise_send, noise_recv)
            )

            return answer_sdp

        return _handle_offer

    async def _complete_inbound(
        self,
        pc: Any,
        bridge: AsyncioBridge,
        noise_send: Any,
        noise_recv: Any,
    ) -> None:
        """
        Finish an inbound connection after the SDP answer has been sent.

        Runs on the asyncio thread: waits for ICE/DTLS, reads the dialer's
        DTLS fingerprint, then hands off to :meth:`_finish_inbound` on trio
        without blocking the loop.
        """
        try:
            from ._aiortc_helpers import get_remote_fingerprint, wait_for_connected

            await wait_for_connected(pc, timeout=self._config.handshake_timeout)
            dialer_fp = get_remote_fingerprint(pc)

            nursery, token = self._nursery, self._trio_token
            if self._closed or nursery is None or token is None:
                raise WebRTCConnectionError("listener closed")
            trio.from_thread.run_sync(
                nursery.start_soon,
                self._finish_inbound,
                pc,
                bridge,
                dialer_fp,
                noise_send,
                noise_recv,
                trio_token=token,
            )
        except BaseException:
            self._in_flight -= 1
            logger.debug("Failed to complete inbound WebRTC connection", exc_info=True)
            try:
                await pc.close()
            except Exception:
                pass

    async def _finish_inbound(
        self,
        pc: Any,
        bridge: AsyncioBridge,
        dialer_fp: bytes,
        noise_send: Any,
        noise_recv: Any,
    ) -> None:
        """
        Trio side of an inbound connection: Noise handshake, then handler.

        Must run on trio: :class:`WebRTCConnection` captures the trio token
        in its constructor, and the Noise pattern code is trio-async.
        """
        from libp2p.crypto.x25519 import create_new_key_pair as create_x25519_keypair

        from ._aiortc_helpers import wire_pc_to_connection
        from .noise_handshake import DataChannelReadWriter, perform_noise_handshake

        conn: WebRTCConnection | None = None
        try:
            conn = WebRTCConnection(
                peer_id=ID(b"\x00" * 32),  # updated after Noise
                bridge=bridge,
                is_initiator=False,
                config=self._config,
            )
            wire_pc_to_connection(pc, conn)

            async def _trio_noise_send(data: bytes) -> None:
                await bridge.run_coro(noise_send(data))

            async def _trio_noise_recv() -> bytes:
                return await bridge.run_coro(noise_recv())

            noise_rw = DataChannelReadWriter(
                send_cb=_trio_noise_send,
                recv_cb=_trio_noise_recv,
                is_initiator=True,
            )
            with trio.fail_after(self._config.handshake_timeout):
                # Server = Noise initiator (spec); we do not know the dialer's
                # peer ID up front, so remote_peer=None.
                authenticated_peer = await perform_noise_handshake(
                    conn=noise_rw,
                    local_peer=self._local_peer_id,
                    libp2p_privkey=self._private_key,
                    noise_static_key=create_x25519_keypair().private_key,
                    dialer_fingerprint=dialer_fp,
                    server_fingerprint=self._certificate.fingerprint,
                    is_initiator=True,
                    remote_peer=None,
                )
            conn.peer_id = authenticated_peer
            await conn.start()
            self._in_flight -= 1
            logger.info("Inbound WebRTC connection from %s", authenticated_peer)
        except BaseException:
            self._in_flight -= 1
            logger.debug("Inbound WebRTC handshake failed", exc_info=True)
            try:
                if conn is not None:
                    await conn.close()
                else:
                    await bridge.run_coro(pc.close())
            except Exception:
                pass
            return

        await self._handler(conn)

    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """Return the listening multiaddrs (includes certhash and peer ID)."""
        return tuple(self._listening_addrs)

    async def close(self) -> None:
        """Stop listening and close all accepted connections."""
        if self._closed:
            return
        self._closed = True

        if self._signaling_server is not None and self._bridge is not None:
            try:
                await self._bridge.run_coro(_close_server(self._signaling_server))
            except Exception:
                logger.debug("Error closing signaling server", exc_info=True)
            self._signaling_server = None

        if self._nursery is not None:
            self._nursery.cancel_scope.cancel()
            await self._nursery_done.wait()

        self._listening_addrs.clear()
        logger.debug("WebRTC Direct listener closed")


async def _close_server(server: asyncio.Server) -> None:
    """Close an asyncio.Server (runs on asyncio thread)."""
    server.close()
    await server.wait_closed()
