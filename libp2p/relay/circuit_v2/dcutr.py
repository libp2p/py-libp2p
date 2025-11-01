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
from libp2p.peer.peerinfo import (
    PeerInfo,
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
from libp2p.tools.async_service import (
    Service,
)

logger = logging.getLogger(__name__)

# Protocol ID for DCUtR
PROTOCOL_ID = TProtocol("/libp2p/dcutr")

# Maximum message size for DCUtR (4KiB as per spec)
MAX_MESSAGE_SIZE = 4 * 1024

# DCUtR protocol constants
# Maximum number of hole punch attempts per peer
MAX_HOLE_PUNCH_ATTEMPTS = 5

# Delay between retry attempts
HOLE_PUNCH_RETRY_DELAY = 30  # seconds

# Maximum observed addresses to exchange
MAX_OBSERVED_ADDRS = 20


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
        self._reachability_checker = ReachabilityChecker(host)
        self._nursery: trio.Nursery | None = None

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

                # Wait for service to be stopped
                await self.manager.wait_finished()
        finally:
            # Clean up
            try:
                # Use empty async lambda instead of None for stream handler
                async def empty_handler(_: INetStream) -> None:
                    pass

                self.host.set_stream_handler(PROTOCOL_ID, empty_handler)
                logger.debug("DCUtR protocol handler unregistered")
            except Exception as e:
                logger.error("Error unregistering DCUtR protocol handler: %s", str(e))

            # Clear state
            self._hole_punch_attempts.clear()
            self._direct_connections.clear()
            self._in_progress.clear()
            self._nursery = None

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
            logger.debug("Received DCUtR stream from peer %s", remote_peer_id)

            # Check if we already have a direct connection
            if await self._have_direct_connection(remote_peer_id):
                logger.debug(
                    "Already have direct connection to %s, closing stream",
                    remote_peer_id,
                )
                await stream.close()
                return

            # Check if there's already an active hole punch attempt
            if remote_peer_id in self._in_progress:
                logger.debug("Hole punch already in progress with %s", remote_peer_id)
                # Let the existing attempt continue
                await stream.close()
                return

            # Mark as in progress
            self._in_progress.add(remote_peer_id)

            try:
                # Read the CONNECT message
                with trio.fail_after(self.read_timeout):
                    msg_bytes = await stream.read(MAX_MESSAGE_SIZE)

                # Parse the message
                connect_msg = HolePunch()
                connect_msg.ParseFromString(msg_bytes)

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
                    await stream.write(response.SerializeToString())

                logger.debug(
                    "Sent CONNECT response to %s with %d addresses",
                    remote_peer_id,
                    len(our_addrs),
                )

                # Wait for SYNC message
                with trio.fail_after(self.read_timeout):
                    sync_bytes = await stream.read(MAX_MESSAGE_SIZE)

                # Parse the SYNC message
                sync_msg = HolePunch()
                sync_msg.ParseFromString(sync_bytes)

                # Verify it's a SYNC message
                if sync_msg.type != HolePunch.SYNC:
                    logger.warning("Expected SYNC message, got %s", sync_msg.type)
                    await stream.close()
                    return

                logger.debug("Received SYNC message from %s", remote_peer_id)

                # Perform hole punch
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
                # Send our CONNECT message with our observed addresses
                our_addrs = await self._get_observed_addrs()
                connect_msg = HolePunch()
                connect_msg.type = HolePunch.CONNECT
                connect_msg.ObsAddrs.extend(our_addrs)

                start_time = time.time()
                with trio.fail_after(self.write_timeout):
                    await stream.write(connect_msg.SerializeToString())

                logger.debug(
                    "Sent CONNECT message to %s with %d addresses",
                    peer_id,
                    len(our_addrs),
                )

                # Receive the peer's CONNECT message
                with trio.fail_after(self.read_timeout):
                    resp_bytes = await stream.read(MAX_MESSAGE_SIZE)

                # Calculate RTT
                rtt = time.time() - start_time

                # Parse the response
                resp = HolePunch()
                resp.ParseFromString(resp_bytes)

                # Verify it's a CONNECT message
                if resp.type != HolePunch.CONNECT:
                    logger.warning("Expected CONNECT message, got %s", resp.type)
                    return False

                logger.debug(
                    "Received CONNECT response from %s with %d addresses",
                    peer_id,
                    len(resp.ObsAddrs),
                )

                # Process observed addresses from the peer
                peer_addrs = self._decode_observed_addrs(list(resp.ObsAddrs))
                logger.debug("Decoded %d valid addresses from peer", len(peer_addrs))

                # Store the addresses in the peerstore
                if peer_addrs:
                    self.host.get_peerstore().add_addrs(
                        peer_id, peer_addrs, 10 * 60
                    )  # 10 minute TTL

                # Send SYNC message with timing information
                # We'll use a future time that's 2*RTT from now to ensure both sides
                # are ready
                punch_time = time.time() + (2 * rtt) + 1  # Add 1 second buffer

                sync_msg = HolePunch()
                sync_msg.type = HolePunch.SYNC

                with trio.fail_after(self.write_timeout):
                    await stream.write(sync_msg.SerializeToString())

                logger.debug("Sent SYNC message to %s", peer_id)

                # Perform the synchronized hole punch
                success = await self._perform_hole_punch(
                    peer_id, peer_addrs, punch_time
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

        # This should never be reached, but add explicit return for type checking
        return False

    async def _perform_hole_punch(
        self, peer_id: ID, addrs: list[Multiaddr], punch_time: float | None = None
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
        direct_addrs = [
            addr for addr in addrs if not str(addr).startswith("/p2p-circuit")
        ]

        if not direct_addrs:
            logger.warning("No direct addresses found for peer %s", peer_id)
            return False

        # Start dialing attempts in parallel
        async with trio.open_nursery() as nursery:
            for addr in direct_addrs[
                :5
            ]:  # Limit to 5 addresses to avoid too many connections
                nursery.start_soon(self._dial_peer, peer_id, addr)

        # Check if we established a direct connection
        return await self._have_direct_connection(peer_id)

    async def _dial_peer(self, peer_id: ID, addr: Multiaddr) -> None:
        """
        Attempt to dial a peer at a specific address.

        Parameters
        ----------
        peer_id : ID
            The peer to dial
        addr : Multiaddr
            The address to dial

        """
        try:
            logger.debug("Attempting to dial %s at %s", peer_id, addr)

            # Create peer info
            peer_info = PeerInfo(peer_id, [addr])

            # Try to connect with timeout
            with trio.fail_after(self.dial_timeout):
                await self.host.connect(peer_info)

            logger.info("Successfully connected to %s at %s", peer_id, addr)

            # Add to direct connections set
            self._direct_connections.add(peer_id)

        except trio.TooSlowError:
            logger.debug("Timeout dialing %s at %s", peer_id, addr)
        except Exception as e:
            logger.debug("Error dialing %s at %s: %s", peer_id, addr, str(e))

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
        if peer_id in self._direct_connections:
            return True

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
            # Get the transport addresses
            addrs = conn.get_transport_addresses()

            # If any address doesn't start with /p2p-circuit, it's a direct connection
            if any(not str(addr).startswith("/p2p-circuit") for addr in addrs):
                # Cache this result
                self._direct_connections.add(peer_id)
                return True

        return False

    async def _get_observed_addrs(self) -> list[bytes]:
        """
        Get our observed addresses to share with the peer.

        Returns
        -------
        List[bytes]
            List of observed addresses as bytes

        """
        # Get all listen addresses
        addrs = self.host.get_addrs()

        # Filter out relay addresses
        direct_addrs = [
            addr for addr in addrs if not str(addr).startswith("/p2p-circuit")
        ]

        # Limit the number of addresses
        if len(direct_addrs) > MAX_OBSERVED_ADDRS:
            direct_addrs = direct_addrs[:MAX_OBSERVED_ADDRS]

        # Convert to bytes
        addr_bytes = [addr.to_bytes() for addr in direct_addrs]

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
                # Validate the address (basic check)
                if str(addr).startswith("/ip"):
                    result.append(addr)
            except Exception as e:
                logger.debug("Error decoding multiaddr: %s", str(e))

        return result
