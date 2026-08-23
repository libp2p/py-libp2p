"""
WebRTC Direct listener.

Spec path (default): one shared UDP socket (:class:`UdpMux`). A dialer's
first STUN BINDING REQUEST carries ``USERNAME = server_ufrag:client_ufrag``;
the version prefix on ``server_ufrag`` (``libp2p+webrtc+v1/`` /
``libp2p+webrtc+v2/``) selects the flow. The listener infers the dialer's
SDP offer from that packet (credentials + source address), answers over the
muxed ICE agent, completes DTLS (as DTLS server, without verifying the
dialer's fingerprint — it cannot know it yet), then runs the Noise XX
handshake over data-channel 0 as the Noise *initiator* and hands the
authenticated :class:`WebRTCConnection` to the handler on the trio side.

Experimental harness (``config.enable_sdp_http_harness``): additionally
serves ``POST /sdp`` on TCP (same port number) for py↔py debugging. Not
interoperable with other implementations.

Published multiaddr format::

    /ip4/<bound-ip>/udp/<bound-port>/webrtc-direct/certhash/<hash>/p2p/<peer-id>

Threading model: aiortc runs on the :class:`AsyncioBridge` thread; the Noise
handshake and the handler run on trio inside a listener-owned nursery
(started as a system task, like the TCP listener). The asyncio → trio hop is
``trio.from_thread.run_sync(nursery.start_soon, ...)`` — non-blocking, so
the asyncio loop keeps servicing the data-channel callbacks the handshake
needs.

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
from .sdp import build_inferred_offer, parse_direct_username

if TYPE_CHECKING:
    from ._asyncio_bridge import AsyncioBridge
    from ._udp_mux import UdpMux

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
        self._mux: UdpMux | None = None
        self._rtc_cert: Any = None
        # Host used for the muxed connections' single host candidate.
        self._candidate_host = "127.0.0.1"

        # trio side: long-lived nursery for inbound handshakes/handlers.
        self._trio_token: trio.lowlevel.TrioToken | None = None
        self._nursery: trio.Nursery | None = None
        self._nursery_ready = trio.Event()
        self._nursery_done = trio.Event()
        # asyncio tasks driving inbound PCs (spec path); cancelled on close.
        self._accept_tasks: set[asyncio.Future[Any]] = set()
        # Bound the number of not-yet-authenticated inbound connections.
        # ponytail: soft cap — updated from both the asyncio and trio threads
        # (GIL-atomic int ops); use a lock if it ever needs to be exact.
        self._in_flight = 0

    async def listen(self, maddr: Multiaddr) -> None:
        """
        Start listening for incoming WebRTC Direct connections.

        Binds one shared UDP socket and dispatches inbound STUN by ufrag (spec
        path). If ``config.enable_sdp_http_harness`` is set, also starts the
        experimental HTTP ``POST /sdp`` signaling server on TCP with the same
        port number. The published multiaddr advertises the UDP port and the
        DTLS certificate hash.

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
        self._rtc_cert = rtc_cert

        from ._udp_mux import UdpMux

        # Shared UDP socket + STUN dispatch (runs on the asyncio thread).
        # Bind before spawning anything so a bind failure leaves no orphans.
        try:
            mux, bound_port = await bridge.run_coro(UdpMux.create(host, port))
        except OSError as e:
            raise WebRTCConnectionError(
                f"Failed to bind WebRTC Direct listener on {host}:{port}: {e}"
            ) from e
        self._mux = mux
        await self._start_trio_nursery()
        advertised_host = host if host != "0.0.0.0" else "127.0.0.1"
        self._candidate_host = advertised_host
        mux.set_unknown_stun_handler(self._on_unknown_stun)

        if self._config.enable_sdp_http_harness:
            from ._aiortc_helpers import run_signaling_server

            # Experimental py<->py harness: TCP, same port number as the UDP
            # socket so one multiaddr describes both.
            self._signaling_server = await bridge.run_coro(
                run_signaling_server(
                    host=host,
                    port=bound_port,
                    on_offer=self._make_offer_handler(bridge, rtc_cert),
                )
            )

        # Build advertised multiaddr with certhash and peer ID.
        certhash_mb = self._certificate.fingerprint_to_multibase()
        advertised = build_webrtc_direct_multiaddr(
            host=advertised_host,
            port=bound_port,
            certhash_multibase=certhash_mb,
            peer_id=self._local_peer_id.to_base58(),
        )
        self._listening_addrs.append(advertised)
        logger.info("WebRTC Direct listener on %s", advertised)

    # ------------------------------------------------------------------
    # Spec path: STUN first contact -> inferred offer -> muxed PC
    # ------------------------------------------------------------------

    def _on_unknown_stun(
        self, username: str, data: bytes, addr: tuple[str, int]
    ) -> None:
        """
        First inbound BINDING REQUEST from a new dialer (asyncio thread, sync).

        Validates the ``USERNAME``, registers a mux-backed ICE connection for
        the server ufrag (so every following packet routes without coming
        back here), replays the packet into it, and schedules the async
        acceptance. Anything malformed is dropped silently — this is an
        unauthenticated network input.
        """
        mux, bridge = self._mux, self._bridge
        if self._closed or mux is None or bridge is None:
            return
        # ponytail: in-flight cap only; add a per-source-IP token bucket if
        # STUN floods from one address become a problem (spec: SHOULD rate-limit).
        if self._in_flight >= self._config.max_in_flight_connections:
            logger.debug("WebRTC Direct: in-flight cap reached, dropping %s", addr)
            return
        try:
            version, server_ufrag, _client_ufrag = parse_direct_username(username)
            if version != 1:
                logger.debug(
                    "WebRTC Direct: v%d not supported yet, dropping %s", version, addr
                )
                return
            # v1: the dialer set ufrag == pwd on both offer and answer, so the
            # server credential *is* the password.
            conn = mux.add_ice_connection(
                server_ufrag, server_ufrag, host=self._candidate_host
            )
        except (WebRTCConnectionError, ValueError):
            logger.debug("WebRTC Direct: rejected first contact from %s", addr)
            return

        self._in_flight += 1
        # Re-dispatch: the ufrag is registered now, so this reaches the aioice
        # protocol (which answers the check and queues it) and teaches the
        # mux the peer's address.
        mux.datagram_received(data, addr)
        task = asyncio.ensure_future(self._accept_v1(conn, server_ufrag, addr))
        self._accept_tasks.add(task)
        task.add_done_callback(self._accept_tasks.discard)

    async def _accept_v1(
        self, conn: Any, server_ufrag: str, addr: tuple[str, int]
    ) -> None:
        """Build the muxed PC for a v1 first contact and drive it to connected."""
        from aiortc import RTCSessionDescription

        from ._aiortc_helpers import (
            attach_muxed_connection,
            close_peer_connection,
            create_noise_channel,
            create_peer_connection,
            make_noise_channel_callbacks,
        )

        mux, bridge = self._mux, self._bridge
        assert mux is not None and bridge is not None
        pc: Any = None
        try:
            # The listener never needs STUN servers: it is reachable on the
            # advertised address by construction.
            pc = await create_peer_connection(self._rtc_cert, ice_servers=[])
            noise_ch = await create_noise_channel(pc)
            noise_send, noise_recv, _ = make_noise_channel_callbacks(noise_ch)
            attach_muxed_connection(pc, mux, conn)
            # Spec step 6.2/7: B cannot know A's DTLS fingerprint, so it must
            # not verify it during DTLS; the Noise handshake authenticates.
            pc.sctp.transport._validate_peer_identity = lambda _params: None

            offer_sdp = build_inferred_offer(
                client_ufrag=server_ufrag,
                client_pwd=server_ufrag,
                remote_host=addr[0],
                remote_port=addr[1],
                max_message_size=self._config.max_message_size,
            )
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=offer_sdp, type="offer")
            )
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
        except BaseException:
            self._in_flight -= 1
            logger.debug("WebRTC Direct: inbound setup failed", exc_info=True)
            mux.unregister(server_ufrag)
            if pc is not None:
                try:
                    await close_peer_connection(pc)
                except Exception:
                    pass
            return

        await self._complete_inbound(pc, bridge, noise_send, noise_recv)

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
            from ._aiortc_helpers import (
                close_peer_connection,
                get_remote_fingerprint,
                wait_for_connected,
            )

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
                await close_peer_connection(pc)
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

        from ._aiortc_helpers import close_peer_connection, wire_pc_to_connection
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
                    await bridge.run_coro(close_peer_connection(pc))
            except Exception:
                pass
            return

        # The nursery lives in a trio system task: an exception escaping here
        # would take down the whole trio run, not just this connection.
        try:
            await self._handler(conn)
        except Exception:
            logger.exception("WebRTC Direct handler failed for %s", conn.peer_id)
            try:
                await conn.close()
            except Exception:
                pass

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

        if self._mux is not None and self._bridge is not None:
            mux, self._mux = self._mux, None
            mux.set_unknown_stun_handler(None)

            async def _shutdown_mux() -> None:
                # Cancel in-flight inbound setups so their PCs close now
                # rather than after handshake_timeout, then drop the socket.
                for task in list(self._accept_tasks):
                    task.cancel()
                if self._accept_tasks:
                    await asyncio.gather(*self._accept_tasks, return_exceptions=True)
                await mux.close()

            try:
                await self._bridge.run_coro(_shutdown_mux())
            except Exception:
                logger.debug("Error closing UdpMux", exc_info=True)

        if self._nursery is not None:
            self._nursery.cancel_scope.cancel()
            await self._nursery_done.wait()

        self._listening_addrs.clear()
        logger.debug("WebRTC Direct listener closed")


async def _close_server(server: asyncio.Server) -> None:
    """Close an asyncio.Server (runs on asyncio thread)."""
    server.close()
    await server.wait_closed()
