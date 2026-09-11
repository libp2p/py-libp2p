"""
Direct Connection Upgrade through Relay (DCUtR) protocol implementation.

This module implements the DCUtR protocol as specified in:
https://github.com/libp2p/specs/blob/master/relay/DCUtR.md

DCUtR enables peers behind NAT to establish direct connections
using hole punching techniques.
"""

import logging
import time
from typing import Any

from multiaddr import Multiaddr
import trio

from libp2p.abc import (
    IHost,
    INetConn,
    INetStream,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.relay.circuit_v2.config import (
    DEFAULT_DCUTR_READ_TIMEOUT,
    DEFAULT_DCUTR_WRITE_TIMEOUT,
    DEFAULT_DIAL_TIMEOUT,
)
from libp2p.relay.circuit_v2.nat import (
    ReachabilityChecker,
)
from libp2p.relay.circuit_v2.pb.dcutr_pb2 import (
    HolePunch,
)
from libp2p.relay.circuit_v2.utils import (
    write_delimited_msg,
)
from libp2p.utils.varint import (
    read_varint_prefixed_bytes_limited,
)
from libp2p.tools.anyio_service import (
    Service,
)

logger = logging.getLogger(__name__)

# Protocol ID for DCUtR
PROTOCOL_ID = TProtocol("/libp2p/dcutr")

# Maximum message size for DCUtR (4KiB as per spec)
MAX_MESSAGE_SIZE = 4 * 1024

# DCUtR protocol constants
# Maximum number of hole punch attempts per peer.
# Spec: inbound peers SHOULD retry twice (total 3 attempts) before giving up.
MAX_HOLE_PUNCH_ATTEMPTS = 3

# Delay between retry attempts
HOLE_PUNCH_RETRY_DELAY = 30  # seconds

# Maximum observed addresses to exchange
MAX_OBSERVED_ADDRS = 20


async def read_dcutr_msg(stream: Any, msg_cls: type[HolePunch]) -> HolePunch:
    """
    Read one DCUtR message, enforcing the 4 KiB spec limit.

    Spec: implementations SHOULD refuse encoded RPC messages
    (length prefix excluded) larger than 4 KiB.
    """
    data = await read_varint_prefixed_bytes_limited(stream, MAX_MESSAGE_SIZE)
    msg = msg_cls()
    msg.ParseFromString(data)
    return msg


def _tcp_ip_port(addr: Multiaddr) -> tuple[int, str, int] | None:
    """Extract (family, ip, tcp_port) from a multiaddr, or None."""
    try:
        port_str = addr.value_for_protocol("tcp")
    except Exception:
        return None
    if port_str is None:
        return None
    for family, proto in ((4, "ip4"), (6, "ip6")):
        try:
            ip = addr.value_for_protocol(proto)
        except Exception:
            continue
        if ip is not None:
            try:
                return (family, ip, int(port_str))
            except ValueError:
                return None
    return None


def _local_tcp_listen_addrs(host: Any) -> list[tuple[int, str, int]]:
    """Our non-relay TCP listen addresses as (family, ip, port)."""
    result: list[tuple[int, str, int]] = []
    try:
        addrs = host.get_addrs()
    except Exception:
        return result
    for addr in addrs:
        if not isinstance(addr, Multiaddr):
            try:
                addr = Multiaddr(str(addr))
            except Exception:
                continue
        if "/p2p-circuit" in str(addr):
            continue
        parsed = _tcp_ip_port(addr)
        if parsed is not None:
            result.append(parsed)
    return result


def _external_ips(addrs: Any) -> list[tuple[int, str]]:
    """External IPs (family, ip) from observed addresses."""
    result: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for addr in addrs:
        if not isinstance(addr, Multiaddr):
            try:
                addr = Multiaddr(str(addr))
            except Exception:
                continue
        for family, proto in ((4, "ip4"), (6, "ip6")):
            try:
                ip = addr.value_for_protocol(proto)
            except Exception:
                continue
            if ip is not None and (family, ip) not in seen:
                seen.add((family, ip))
                result.append((family, ip))
    return result


class DCUtRProtocol(Service):
    """
    DCUtRProtocol implements the Direct Connection Upgrade through Relay protocol.

    This protocol allows two NATed peers to establish direct connections through
    hole punching, after they have established an initial connection through a relay.
    """

    def __init__(
        self,
        host: IHost,
        read_timeout: int = DEFAULT_DCUTR_READ_TIMEOUT,
        write_timeout: int = DEFAULT_DCUTR_WRITE_TIMEOUT,
        dial_timeout: int = DEFAULT_DIAL_TIMEOUT,
    ):
        """
        Initialize the DCUtR protocol.

        Parameters
        ----------
        host : IHost
            The libp2p host this protocol is running on
        read_timeout : int
            Timeout for stream read operations, in seconds
        write_timeout : int
            Timeout for stream write operations, in seconds
        dial_timeout : int
            Timeout for dial operations, in seconds

        """
        super().__init__()
        self.host = host
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self.dial_timeout = dial_timeout
        self.event_started = trio.Event()
        self._hole_punch_attempts: dict[ID, int] = {}
        self._direct_connections: set[ID] = set()
        self._in_progress: set[ID] = set()
        # Per-peer initiation locks: serialize concurrent hole-punch
        # attempts to the same peer (auto-drive loop vs explicit calls).
        # Strict implementations (e.g. nim-libp2p) reject concurrent
        # inbound DCUtR sessions ("Already expecting an incoming
        # connection"), so at most one outbound session may exist.
        self._initiate_locks: dict[ID, trio.Lock] = {}
        self._reachability_checker = ReachabilityChecker(host)
        self._nursery: trio.Nursery | None = None

    def _initiate_lock_for(self, peer_id: ID) -> trio.Lock:
        """Return (creating if needed) the initiation lock for a peer."""
        lock = self._initiate_locks.get(peer_id)
        if lock is None:
            lock = trio.Lock()
            self._initiate_locks[peer_id] = lock
        return lock

    async def run(self, *, task_status: Any = trio.TASK_STATUS_IGNORED) -> None:
        """Run the protocol service."""
        try:
            # Register the DCUtR protocol handler
            logger.debug("Registering DCUtR protocol handler")
            self.host.set_stream_handler(PROTOCOL_ID, self._handle_dcutr_stream)

            # Signal that we're ready
            self.event_started.set()

            # Start the service
            async with trio.open_nursery() as nursery:
                self._nursery = nursery
                task_status.started()
                logger.debug("DCUtR protocol service started")

                # Proactively upgrade relayed connections: some peers only
                # ever react (never initiate), so without driving we would
                # deadlock waiting for each other.
                nursery.start_soon(self._auto_drive_loop)

                # Wait for service to be stopped
                await self.manager.wait_finished()
        finally:
            # Clean up
            try:
                self.host.remove_stream_handler(PROTOCOL_ID)
                logger.debug("DCUtR protocol handler unregistered")
            except Exception as e:
                logger.error("Error unregistering DCUtR protocol handler: %s", str(e))

            # Clear state
            self._hole_punch_attempts.clear()
            self._direct_connections.clear()
            self._in_progress.clear()
            self._initiate_locks.clear()
            self._nursery = None

    async def _auto_drive_loop(self) -> None:
        """
        Initiate hole punches toward newly seen relayed peers.

        Covers peers that never initiate themselves: without driving, two
        reactive-only peers would wait for each other forever. Dedupe via
        initiate_hole_punch (skips peers with sessions, direct connections
        or exhausted attempt budgets).
        """
        while True:
            await trio.sleep(2.0)
            try:
                network = self.host.get_network()
                connections = getattr(network, "connections", {}) or {}
                for peer_id in list(connections.keys()):
                    if peer_id == self.host.get_id():
                        continue
                    if (
                        peer_id in self._in_progress
                        or peer_id in self._direct_connections
                    ):
                        continue
                    attempts = self._hole_punch_attempts.get(peer_id, 0)
                    if attempts >= MAX_HOLE_PUNCH_ATTEMPTS:
                        continue
                    conns = connections.get(peer_id)
                    if not conns:
                        continue
                    if not isinstance(conns, list):
                        conns = [conns]
                    relayed = False
                    for conn in conns:
                        try:
                            addrs = conn.get_transport_addresses()
                        except Exception:
                            continue
                        if addrs and any("/p2p-circuit" in str(addr) for addr in addrs):
                            relayed = True
                            break
                    if not relayed:
                        continue
                    logger.debug("Auto-driving hole punch to %s", peer_id)
                    await self.initiate_hole_punch(peer_id)
            except trio.Cancelled:
                raise
            except Exception as e:
                logger.debug("Auto-drive loop error: %s", e)

    async def _handle_dcutr_stream(self, stream: INetStream) -> None:
        """
        Handle incoming DCUtR streams.

        Parameters
        ----------
        stream : INetStream
            The incoming stream

        """
        try:
            # Get the remote peer ID
            remote_peer_id = stream.muxed_conn.peer_id

            # Check if we already have a direct connection
            if await self._have_direct_connection(remote_peer_id):
                logger.debug(
                    "Already have direct connection to %s, closing stream",
                    remote_peer_id,
                )
                await stream.close()
                return

            # Check if there's already an active hole punch attempt. Run
            # concurrent sessions instead of closing: the peer may be
            # driving its own session (as rust-libp2p does), and closing
            # its stream aborts the handshake on their side.
            if remote_peer_id in self._in_progress:
                logger.debug("Concurrent hole punch session with %s", remote_peer_id)

            # Mark as in progress
            self._in_progress.add(remote_peer_id)

            try:
                # Read the CONNECT message (4 KiB limited per spec)
                with trio.fail_after(self.read_timeout):
                    connect_msg = await read_dcutr_msg(stream, HolePunch)

                # Verify it's a CONNECT message
                if connect_msg.type != HolePunch.CONNECT:
                    logger.warning("Expected CONNECT message, got %s", connect_msg.type)
                    await stream.close()
                    return

                logger.debug(
                    "Received CONNECT message from %s with %d addresses",
                    remote_peer_id,
                    len(connect_msg.ObsAddrs),
                )

                # Process observed addresses from the peer
                peer_addrs = self._decode_observed_addrs(list(connect_msg.ObsAddrs))
                logger.debug("Decoded %d valid addresses from peer", len(peer_addrs))

                # Store the addresses in the peerstore
                if peer_addrs:
                    self.host.get_peerstore().add_addrs(
                        remote_peer_id, peer_addrs, 10 * 60
                    )  # 10 minute TTL

                # Send our CONNECT message with our observed addresses
                our_addrs = await self._get_observed_addrs()
                response = HolePunch()
                response.type = HolePunch.CONNECT
                response.ObsAddrs.extend(our_addrs)

                with trio.fail_after(self.write_timeout):
                    await write_delimited_msg(stream, response)

                logger.debug(
                    "Sent CONNECT response to %s with %d addresses",
                    remote_peer_id,
                    len(our_addrs),
                )

                # Wait for SYNC message (4 KiB limited per spec)
                with trio.fail_after(self.read_timeout):
                    sync_msg = await read_dcutr_msg(stream, HolePunch)

                # Verify it's a SYNC message
                if sync_msg.type != HolePunch.SYNC:
                    logger.warning("Expected SYNC message, got %s", sync_msg.type)
                    await stream.close()
                    return

                logger.debug("Received SYNC message from %s", remote_peer_id)

                # Perform hole punch as the dialer/client (spec: the peer
                # that receives SYNC dials immediately and is the client).
                success = await self._perform_hole_punch(remote_peer_id, peer_addrs)

                if success:
                    logger.info(
                        "Successfully established direct connection with %s",
                        remote_peer_id,
                    )
                else:
                    logger.warning(
                        "Failed to establish direct connection with %s", remote_peer_id
                    )

            except trio.TooSlowError:
                logger.warning("Timeout in DCUtR protocol with peer %s", remote_peer_id)
            except Exception as e:
                logger.error(
                    "Error in DCUtR protocol with peer %s: %s", remote_peer_id, str(e)
                )
            finally:
                # Clean up
                self._in_progress.discard(remote_peer_id)
                await stream.close()

        except Exception as e:
            logger.error("Error handling DCUtR stream: %s", str(e))
            await stream.close()

    async def initiate_hole_punch(self, peer_id: ID) -> bool:
        """
        Initiate a hole punch with a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to hole punch with

        Returns
        -------
        bool
            True if hole punch was successful, False otherwise

        """
        # Check if we already have a direct connection
        if await self._have_direct_connection(peer_id):
            logger.debug("Already have direct connection to %s", peer_id)
            return True

        # Serialize concurrent initiations to the same peer behind one
        # lock: the check-then-add below spans awaits, so without the lock
        # the auto-drive loop and explicit callers could open duplicate
        # simultaneous sessions (rejected by strict peers).
        async with self._initiate_lock_for(peer_id):
            return await self._initiate_hole_punch_locked(peer_id)

    async def _initiate_hole_punch_locked(self, peer_id: ID) -> bool:
        """Hole-punch initiation body; caller must hold the peer's lock."""
        # Check if there's already an active hole punch attempt
        if peer_id in self._in_progress:
            logger.debug("Hole punch already in progress with %s", peer_id)
            return False

        # Check if we've exceeded the maximum number of attempts
        attempts = self._hole_punch_attempts.get(peer_id, 0)
        if attempts >= MAX_HOLE_PUNCH_ATTEMPTS:
            logger.warning("Maximum hole punch attempts reached for peer %s", peer_id)
            return False

        # Mark as in progress and increment attempt counter
        self._in_progress.add(peer_id)
        self._hole_punch_attempts[peer_id] = attempts + 1

        try:
            # Open a DCUtR stream to the peer
            logger.debug("Opening DCUtR stream to peer %s", peer_id)
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
            if not stream:
                logger.warning("Failed to open DCUtR stream to peer %s", peer_id)
                return False

            try:
                # Send our CONNECT message with our observed addresses.
                # Start RTT timer per spec: measure time between sending
                # initial CONNECT and receiving the response.
                our_addrs = await self._get_observed_addrs()
                connect_msg = HolePunch()
                connect_msg.type = HolePunch.CONNECT
                connect_msg.ObsAddrs.extend(our_addrs)

                connect_sent_at = time.monotonic()
                with trio.fail_after(self.write_timeout):
                    await write_delimited_msg(stream, connect_msg)

                logger.debug(
                    "Sent CONNECT message to %s with %d addresses",
                    peer_id,
                    len(our_addrs),
                )

                # Receive the peer's CONNECT message
                with trio.fail_after(self.read_timeout):
                    resp = await read_dcutr_msg(stream, HolePunch)

                # Verify it's a CONNECT message
                if resp.type != HolePunch.CONNECT:
                    logger.warning("Expected CONNECT message, got %s", resp.type)
                    return False

                rtt = time.monotonic() - connect_sent_at
                # Clamp: relay RTT can spike; waiting too long misses the
                # window on the responder side which dials on SYNC receipt.
                # Spec wants RTT/2, cap at 2s to stay simultaneous enough.
                sync_delay = min(max(rtt / 2.0, 0.0), 2.0)
                logger.debug(
                    "Received CONNECT response from %s with %d addresses "
                    "(rtt=%.3fs, sync-delay=%.3fs)",
                    peer_id,
                    len(resp.ObsAddrs),
                    rtt,
                    sync_delay,
                )

                # Process observed addresses from the peer
                peer_addrs = self._decode_observed_addrs(list(resp.ObsAddrs))
                logger.debug("Decoded %d valid addresses from peer", len(peer_addrs))

                # Store the addresses in the peerstore
                if peer_addrs:
                    self.host.get_peerstore().add_addrs(
                        peer_id, peer_addrs, 10 * 60
                    )  # 10 minute TTL

                # Send SYNC message per spec, then wait half the measured
                # RTT so both sides dial simultaneously (responder dials
                # immediately on SYNC receipt; we dial after RTT/2).
                sync_msg = HolePunch()
                sync_msg.type = HolePunch.SYNC

                with trio.fail_after(self.write_timeout):
                    await write_delimited_msg(stream, sync_msg)

                logger.debug("Sent SYNC message to %s", peer_id)

                if sync_delay > 0:
                    await trio.sleep(sync_delay)

                # Perform the hole punch after the sync delay. We are the
                # DCUtR initiator, i.e. the spec's server side: upgrade our
                # dials as responder so the security handshake roles match
                # on a merged simultaneous-open connection.
                success = await self._perform_hole_punch(
                    peer_id, peer_addrs, as_responder=True
                )

                if success:
                    logger.info(
                        "Successfully established direct connection with %s", peer_id
                    )
                    return True
                else:
                    logger.warning(
                        "Failed to establish direct connection with %s", peer_id
                    )
                    return False

            except trio.TooSlowError:
                logger.warning("Timeout in DCUtR protocol with peer %s", peer_id)
                return False
            except Exception as e:
                logger.error(
                    "Error in DCUtR protocol with peer %s: %s", peer_id, str(e)
                )
                return False
            finally:
                await stream.close()

        except Exception as e:
            logger.error(
                "Error initiating hole punch with peer %s: %s", peer_id, str(e)
            )
            return False
        finally:
            self._in_progress.discard(peer_id)

        return False

    async def _perform_hole_punch(
        self,
        peer_id: ID,
        addrs: list[Multiaddr],
        punch_time: float | None = None,
        as_responder: bool = False,
    ) -> bool:
        """
        Perform a hole punch attempt with a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to hole punch with
        addrs : list[Multiaddr]
            List of addresses to try
        punch_time : Optional[float]
            Time to perform the punch (if None, do it immediately)
        as_responder : bool
            Upgrade hole-punch dials as inbound/responder. Set when we are
            the DCUtR initiator (spec's server side): our dial may merge
            with the peer's simultaneous dial into one connection whose
            handshake roles are fixed by the spec (dialer = client). Dialing
            as initiator on both ends breaks the security handshake.

        Returns
        -------
        bool
            True if hole punch was successful

        """
        if not addrs:
            logger.warning("No addresses to try for hole punch with %s", peer_id)
            return False

        # If punch_time is specified, wait until that time
        if punch_time is not None:
            now = time.time()
            if punch_time > now:
                wait_time = punch_time - now
                logger.debug("Waiting %.2f seconds before hole punch", wait_time)
                await trio.sleep(wait_time)

        # Try to dial each address
        logger.debug(
            "Starting hole punch with peer %s using %d addresses", peer_id, len(addrs)
        )

        # Filter to only include non-relay addresses
        direct_addrs = [addr for addr in addrs if "/p2p-circuit" not in str(addr)]

        # Also filter out the relay's own address: if we're connected to
        # this peer via a relay, the peer's ObsAddrs may incorrectly
        # contain the relay's address (observed by the relay). Extract
        # the relay peer ID from our relayed connection to this peer,
        # then drop any address that belongs to that relay.
        try:
            network = self.host.get_network()
            conns = network.connections.get(peer_id, [])
            if not isinstance(conns, list):
                conns = [conns]
            for conn in conns:
                try:
                    addrs_list = conn.get_transport_addresses()
                except Exception:
                    continue
                for addr in addrs_list:
                    if "/p2p-circuit" in str(addr):
                        # Extract relay peer ID from /p2p-circuit/p2p/<relay-peer>
                        parts = str(addr).split("/p2p-circuit/p2p/")
                        if len(parts) > 1:
                            relay_pid_str = parts[1].split("/")[0]
                            relay_pid = ID.from_string(relay_pid_str)
                            # Get relay's addresses to filter them out
                            relay_addrs = self.host.get_peerstore().addrs(relay_pid)
                            relay_addr_set = {str(a) for a in relay_addrs}
                            # Include relay's listen addresses from its peer info
                            try:
                                relay_info = (
                                    self.host.get_peerstore().get_peer_info(relay_pid)
                                )
                                for ra in relay_info.addrs:
                                    relay_addr_set.add(str(ra))
                            except Exception:
                                pass
                            # Filter out relay addresses
                            direct_addrs = [
                                a for a in direct_addrs if str(a) not in relay_addr_set
                            ]
                            logger.debug(
                                "Filtered out %d relay addresses for peer %s",
                                len(relay_addr_set),
                                peer_id,
                            )
                            break
        except Exception as e:
            logger.debug("Failed to filter relay addresses for %s: %s", peer_id, e)

        # Augment with peerstore addresses (e.g. from the certified address
        # book): a peer's DCUtR ObsAddrs may be missing or unusable while
        # identify provided good direct addresses. This mirrors what
        # go/rust implementations dial.
        try:
            known = {str(a) for a in direct_addrs}
            for addr in self.host.get_peerstore().addrs(peer_id):
                s = str(addr)
                if "/p2p-circuit" in s or s in known:
                    continue
                direct_addrs.append(addr)
                known.add(s)
        except Exception as e:
            logger.debug("Failed to read peerstore addrs for %s: %s", peer_id, e)

        if not direct_addrs:
            logger.warning("No direct addresses found for peer %s", peer_id)
            return False

        # Bind hole-punch dials to our listen address so the NAT mapping
        # matches the external address we advertised (TCP simultaneous
        # open). Falls back to ephemeral source when we have no TCP
        # listen address.
        source: tuple[str, int] | None = None
        for _family, lip, lport in _local_tcp_listen_addrs(self.host):
            source = (lip, lport)
            break
        if source is not None:
            logger.debug("Hole-punch dials will bind source %s:%d", *source)

        # Start dialing attempts in parallel. Retry a few rounds: hole
        # punching is timing-sensitive (both sides must dial within the
        # same window for NAT mappings to line up), so a single mistimed
        # round must not doom the attempt. Per spec step 5, dial every
        # address from the CONNECT message in parallel.
        logger.debug(
            "Starting parallel dial attempts to %s using %d addresses",
            peer_id,
            len(direct_addrs),
        )
        for _round in range(3):
            async with trio.open_nursery() as nursery:
                for addr in direct_addrs:
                    nursery.start_soon(
                        self._dial_peer, peer_id, addr, source, as_responder
                    )

            # Wait a bit for connections to establish and settle
            await trio.sleep(0.5)

            # Check if we established a direct connection (verify, don't trust cache)
            is_direct = await self._verify_direct_connection(peer_id)
            if is_direct:
                logger.debug(
                    "Verified direct connection to %s after hole punch", peer_id
                )
                return True
            logger.debug(
                "No direct connection verified to %s after hole punch round",
                peer_id,
            )
            await trio.sleep(2.0)

        return False

    async def _dial_peer(
        self,
        peer_id: ID,
        addr: Multiaddr,
        source: tuple[str, int] | None = None,
        as_responder: bool = False,
    ) -> None:
        """
        Attempt to dial a peer at a specific address.

        Parameters
        ----------
        peer_id : ID
            The peer to dial
        addr : Multiaddr
            The address to dial
        source : tuple[str, int] | None
            Optional (ip, port) to bind the outbound socket to. For TCP
            hole punching this is our listen address: the SYN must leave
            from the listen port so the NAT mapping matches the external
            address we advertised.
        as_responder : bool
            Upgrade as inbound/responder (we are the DCUtR initiator /
            spec server side). See :meth:`_perform_hole_punch`.

        """
        try:
            logger.debug("Attempting to dial %s at %s", peer_id, addr)

            # Snapshot peerstore addresses: a wrong address (e.g. a relay
            # address a peer advertised as its own) fails the dial with a
            # peer-ID mismatch, and the swarm clears the peer's addresses
            # on mismatch. Restore them so one bad address cannot wipe out
            # the good ones we still need to try.
            try:
                known_addrs = list(self.host.get_peerstore().addrs(peer_id))
            except Exception:
                known_addrs = []

            # Force a fresh direct dial to this address. host.connect() is
            # not usable here: it returns the existing relayed connection
            # as "connected" without dialing anything.
            network = self.host.get_network()
            with trio.fail_after(self.dial_timeout):
                if as_responder:
                    await network.dial_addr_as_responder(addr, peer_id, source)
                else:
                    await network.dial_addr(addr, peer_id, source)

            logger.debug("Connection established to %s at %s", peer_id, addr)

            # Wait a bit for the connection to be fully established
            await trio.sleep(0.1)

            # Verify the connection is actually direct before adding to cache
            if await self._verify_direct_connection(peer_id):
                logger.info(
                    "Successfully established direct connection to %s at %s",
                    peer_id,
                    addr,
                )
                # Only add to direct connections set if verified
                self._direct_connections.add(peer_id)
            else:
                logger.debug(
                    "Connection to %s is not direct (likely still relayed)", peer_id
                )

        except trio.TooSlowError:
            logger.debug("Timeout dialing %s at %s", peer_id, addr)
        except Exception as e:
            logger.debug("Error dialing %s at %s: %s", peer_id, addr, str(e))
            if "mismatch" in str(e).lower() and known_addrs:
                try:
                    self.host.get_peerstore().add_addrs(peer_id, known_addrs, 600)
                except Exception:
                    pass

    async def _verify_direct_connection(self, peer_id: ID) -> bool:
        """
        Verify that we have a direct (non-relayed) connection to a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to check

        Returns
        -------
        bool
            True if we have a verified direct connection, False otherwise

        """
        # Check if the peer is connected
        network = self.host.get_network()
        conn_or_conns = network.connections.get(peer_id)
        if not conn_or_conns:
            return False

        # Handle both single connection and list of connections
        if isinstance(conn_or_conns, list):
            connections: list[INetConn] = conn_or_conns
        else:
            connections = [conn_or_conns]

        # Check if any connection is direct (not relayed)
        for conn in connections:
            try:
                # Use actual transport addresses only: falling back to
                # peerstore addresses here would report relayed-only peers
                # as directly connected (false positive), since the
                # peerstore also holds the addresses we learned to reach
                # them at all.
                actual = getattr(conn, "_actual_transport_addresses", None)
                if actual is not None:
                    addrs = actual
                else:
                    addrs = conn.get_transport_addresses()

                # If we got addresses, check if any is direct: an address
                # without a /p2p-circuit component anywhere is direct.
                if addrs:
                    if any("/p2p-circuit" not in str(addr) for addr in addrs):
                        return True
                else:
                    # If no addresses returned, check the connection type another way
                    # Check if this is a SwarmConn and inspect its properties
                    conn_str = str(conn)
                    if "SwarmConn" in conn_str:
                        # For SwarmConn, we need to check the underlying connection
                        # If it's a circuit connection, it will have circuit in the path
                        try:
                            # Try to get the raw connection
                            # raw_conn is implementation-specific, not in IMuxedConn
                            if hasattr(conn, "muxed_conn") and hasattr(
                                conn.muxed_conn, "raw_conn"
                            ):
                                raw_conn = conn.muxed_conn.raw_conn  # type: ignore[attr-defined]
                                raw_addrs = raw_conn.get_transport_addresses()
                                if raw_addrs:
                                    if any(
                                        "/p2p-circuit" not in str(addr)
                                        for addr in raw_addrs
                                    ):
                                        return True
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(
                    "Error verifying connection type for %s: %s", peer_id, str(e)
                )
                # If we can't verify, assume it's not direct
                continue

        return False

    async def _have_direct_connection(self, peer_id: ID) -> bool:
        """
        Check if we already have a direct connection to a peer.

        Parameters
        ----------
        peer_id : ID
            The peer to check

        Returns
        -------
        bool
            True if we have a direct connection, False otherwise

        """
        # Check our direct connections cache first
        # Trust the cache for fast path - this allows early return when we know
        # we have a direct connection. Verification happens when connections are
        # established (in _dial_peer) to ensure cache accuracy.
        if peer_id in self._direct_connections:
            return True

        # Check if the peer is connected and verify it's direct
        return await self._verify_direct_connection(peer_id)

    async def _get_observed_addrs(self) -> list[bytes]:
        """
        Get our observed addresses to share with the peer.

        Prefers externally observed (NAT-mapped) addresses tracked by the
        host's observed-address manager — even with a single observer, since
        hole punching typically coordinates through exactly one relay and
        the default confirmation threshold would otherwise hide the only
        dialable address. Falls back to listen addresses.

        NAT port prediction: a relay observes us at (WAN_IP:mapped_port),
        but the mapped port belongs to the relay connection's ephemeral
        socket — dialing it reaches the wrong socket. Since hole-punch
        dials leave FROM our listen port (see ``_dial_peer``) and NATs
        typically preserve ports, the dialable address is
        (WAN_IP:listen_port). When external observations exist, advertise
        those predictions (spec allows predicted addresses); otherwise
        fall back to listen addresses (direct/LAN case).

        Returns
        -------
        List[bytes]
            List of observed addresses as bytes

        """
        listen_tcp = _local_tcp_listen_addrs(self.host)
        predicted: list[Multiaddr] = []

        manager = getattr(self.host, "_observed_addr_manager", None)
        if manager is not None:
            try:
                wan_ips = _external_ips(
                    a
                    for a in manager.addrs(min_observers=1)
                    if "/p2p-circuit" not in str(a)
                )
                for family, wan_ip in wan_ips:
                    for lfamily, _lip, lport in listen_tcp:
                        if lfamily == family:
                            predicted.append(
                                Multiaddr(f"/ip{family}/{wan_ip}/tcp/{lport}")
                            )
            except Exception as e:
                logger.debug("Failed to read observed addresses: %s", e)

        if predicted:
            seen: set[str] = set()
            direct_addrs = []
            for addr in predicted:
                s = str(addr)
                if s not in seen:
                    seen.add(s)
                    direct_addrs.append(addr)
            logger.debug("Advertising predicted NAT addresses: %s", seen)
        else:
            # No external observations (direct connection or no relay yet):
            # advertise listen addresses.
            addrs = self.host.get_addrs()
            direct_addrs = [
                addr for addr in addrs if "/p2p-circuit" not in str(addr)
            ]

        # Limit the number of addresses
        if len(direct_addrs) > MAX_OBSERVED_ADDRS:
            direct_addrs = direct_addrs[:MAX_OBSERVED_ADDRS]

        # Convert to bytes. DCUtR peers parse ObsAddrs strictly: send bare
        # multiaddrs without a /p2p/ suffix (the responder already knows our
        # peer ID from the connection), matching go/rust implementations.
        addr_bytes = []
        for addr in direct_addrs:
            try:
                p2p_value = addr.value_for_protocol("p2p")
            except Exception:
                p2p_value = None
            if p2p_value:
                addr = addr.decapsulate(Multiaddr(f"/p2p/{p2p_value}"))
            addr_bytes.append(addr.to_bytes())

        return addr_bytes

    def _decode_observed_addrs(self, addr_bytes: list[bytes]) -> list[Multiaddr]:
        """
        Decode observed addresses received from a peer.

        Parameters
        ----------
        addr_bytes : List[bytes]
            The encoded addresses

        Returns
        -------
        List[Multiaddr]
            The decoded multiaddresses

        """
        result = []

        for addr_byte in addr_bytes:
            try:
                addr = Multiaddr(addr_byte)
                # Accept any valid multiaddr; relayed addresses are
                # filtered later in _perform_hole_punch. Restricting to
                # /ip* here drops valid /dns* observed addrs that
                # go/rust peers send.
                if len(str(addr)) > 0:
                    result.append(addr)
            except Exception as e:
                logger.debug("Error decoding multiaddr: %s", str(e))

        return result
