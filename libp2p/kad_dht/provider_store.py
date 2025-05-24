"""
Provider record storage for Kademlia DHT.

This module implements the storage for content provider records in the Kademlia DHT.
"""

import logging
import time
from typing import (
    Any,
    Optional,
)

from multiaddr import (
    Multiaddr,
)

from libp2p.abc import (
    IHost,
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

from .pb.kademlia_pb2 import (
    Message,
)

# logger = logging.getLogger("libp2p.kademlia.provider_store")
logger = logging.getLogger("kademlia-example.provider_store")

# Constants for provider records (based on IPFS standards)
PROVIDER_RECORD_REPUBLISH_INTERVAL = 22 * 60 * 60  # 22 hours in seconds
PROVIDER_RECORD_EXPIRATION_INTERVAL = 48 * 60 * 60  # 48 hours in seconds
PROVIDER_ADDRESS_TTL = 30 * 60  # 30 minutes in seconds
PROTOCOL_ID = TProtocol("/ipfs/kad/1.0.0")


class ProviderRecord:
    """
    A record for a content provider in the DHT.

    Contains the peer ID, network addresses (optional), and timestamp.
    """

    def __init__(
        self,
        peer_id: ID,
        addresses: Optional[list[Multiaddr]] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """
        Initialize a new provider record.

        :param peer_id: The ID of the provider peer
        :param addresses: Optional network addresses of the provider peer
        :param timestamp: Time this record was created/updated
                          (defaults to current time)

        """
        self.peer_id = peer_id
        self.addresses = addresses or []
        self.timestamp = timestamp or time.time()
        self.addresses_expiry = self.timestamp + PROVIDER_ADDRESS_TTL


class ProviderStore:
    """
    Store for content provider records in the Kademlia DHT.

    Maps content keys to provider records, with support for expiration.
    """

    def __init__(self, host: IHost = None, peer_routing: Any = None) -> None:
        """
        Initialize a new provider store.

        :param host: The libp2p host instance (optional)
        :param peer_routing: The peer routing instance (optional)
        """
        # Maps content keys to a dict of provider records (peer_id -> record)
        self.providers: dict[bytes, dict[str, ProviderRecord]] = {}
        self.host = host
        self.peer_routing = peer_routing
        self.providing_keys: set[bytes] = set()
        self.local_peer_id = host.get_id() if host else None

    async def _republish_provider_records(self) -> None:
        """Republish all provider records for content this node is providing."""
        for key in self.providing_keys:
            logger.info(f"Republishing provider record for key {key.hex()}")
            await self.provide(key)

    async def provide(self, key: bytes) -> bool:
        """
        Advertise that this node can provide a piece of content.

        Finds the k closest peers to the key and sends them ADD_PROVIDER messages.

        :param key: The content key (multihash) to advertise

        Returns
        -------
        bool
            True if the advertisement was successful

        """
        if not self.host or not self.peer_routing:
            logger.error("Host or peer_routing not initialized, cannot provide content")
            return False

        # Add to local provider store
        local_addrs = []
        for addr in self.host.get_addrs():
            local_addrs.append(addr)

        local_peer_info = PeerInfo(self.host.get_id(), local_addrs)
        self.add_provider(key, local_peer_info)

        # Track that we're providing this key
        self.providing_keys.add(key)

        # Find the k closest peers to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key)
        logger.info(
            "Found %d peers close to key %s for provider advertisement",
            len(closest_peers),
            key.hex(),
        )

        # Send ADD_PROVIDER messages to these peers
        success_count = 0
        for peer_id in closest_peers:
            if peer_id == self.local_peer_id:
                continue

            try:
                success = await self._send_add_provider(peer_id, key)
                if success:
                    success_count += 1
            except Exception as e:
                logger.warning(f"Failed to send ADD_PROVIDER to {peer_id}: {e}")

        return success_count > 0

    async def _send_add_provider(self, peer_id: ID, key: bytes) -> bool:
        """
        Send ADD_PROVIDER message to a specific peer.

        :param peer_id: The peer to send the message to
        :param key: The content key being provided

        Returns
        -------
        bool
            True if the message was successfully sent and acknowledged

        """
        try:
            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [TProtocol(PROTOCOL_ID)])

            try:
                # Get our addresses to include in the message
                addrs = []
                for addr in self.host.get_addrs():
                    addrs.append(addr.to_bytes())

                # Create the ADD_PROVIDER message
                message = Message()
                message.type = Message.MessageType.ADD_PROVIDER
                message.key = key

                # Add our provider info
                provider = message.providerPeers.add()
                provider.id = self.local_peer_id.to_bytes()
                provider.addrs.extend(addrs)

                # Serialize and send the message
                proto_bytes = message.SerializeToString()
                await stream.write(len(proto_bytes).to_bytes(4, byteorder="big"))
                await stream.write(proto_bytes)

                # Read response (length prefix)
                length_bytes = await stream.read(4)
                if len(length_bytes) < 4:
                    return False

                response_length = int.from_bytes(length_bytes, byteorder="big")

                # Read response data
                response_bytes = await stream.read(response_length)
                if len(response_bytes) < response_length:
                    return False

                # Parse response
                response = Message()
                response.ParseFromString(response_bytes)

                # Check response type
                return response.type == Message.MessageType.ADD_PROVIDER

            finally:
                await stream.close()

        except Exception as e:
            logger.warning(f"Error sending ADD_PROVIDER to {peer_id}: {e}")
            return False

    async def find_providers(self, key: bytes, count: int = 20) -> list[PeerInfo]:
        """
        Find content providers for a given key.

        :param key: The content key to look for
        :param count: Maximum number of providers to return

        Returns
        -------
        List[PeerInfo]
            List of content providers

        """
        if not self.host or not self.peer_routing:
            logger.error("Host or peer_routing not initialized, cannot find providers")
            return []

        # Check local provider store first
        local_providers = self.get_providers(key)
        if local_providers:
            logger.info(
                f"Found {len(local_providers)} providers locally for {key.hex()}"
            )
            return local_providers[:count]
        logger.info("local providers are %s", local_providers)

        # Find the closest peers to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key)
        logger.info(
            f"Searching {len(closest_peers)} peers for providers of {key.hex()}"
        )

        # Query these peers for providers
        all_providers = []
        for peer_id in closest_peers:
            if peer_id == self.local_peer_id:
                continue

            try:
                providers = await self._get_providers_from_peer(peer_id, key)
                if providers:
                    # Add providers to our local store
                    for provider in providers:
                        self.add_provider(key, provider)

                    # Add to our result list
                    all_providers.extend(providers)

                    # Stop if we've found enough providers
                    if len(all_providers) >= count:
                        break
            except Exception as e:
                logger.warning(f"Failed to get providers from {peer_id}: {e}")

        return all_providers[:count]

    async def _get_providers_from_peer(self, peer_id: ID, key: bytes) -> list[PeerInfo]:
        """
        Get content providers from a specific peer.

        :param peer_id: The peer to query
        :param key: The content key to look for

        Returns
        -------
        List[PeerInfo]
            List of provider information

        """
        try:
            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [TProtocol(PROTOCOL_ID)])

            try:
                # Create the GET_PROVIDERS message
                message = Message()
                message.type = Message.MessageType.GET_PROVIDERS
                message.key = key

                # Serialize and send the message
                proto_bytes = message.SerializeToString()
                await stream.write(len(proto_bytes).to_bytes(4, byteorder="big"))
                await stream.write(proto_bytes)

                # Read response (length prefix)
                length_bytes = b""
                remaining = 4
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        return []

                    length_bytes += chunk
                    remaining -= len(chunk)

                response_length = int.from_bytes(length_bytes, byteorder="big")

                # Read response data
                response_bytes = b""
                remaining = response_length
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        return []

                    response_bytes += chunk
                    remaining -= len(chunk)

                # Parse response
                response = Message()
                response.ParseFromString(response_bytes)

                # Check response type
                if response.type != Message.MessageType.GET_PROVIDERS:
                    return []

                # Extract provider information
                providers = []
                for provider_proto in response.providerPeers:
                    try:
                        # Create peer ID from bytes
                        provider_id = ID(provider_proto.id)

                        # Convert addresses to Multiaddr
                        addrs = []
                        for addr_bytes in provider_proto.addrs:
                            try:
                                addrs.append(Multiaddr(addr_bytes))
                            except Exception:
                                pass  # Skip invalid addresses

                        # Create PeerInfo and add to result
                        providers.append(PeerInfo(provider_id, addrs))
                    except Exception as e:
                        logger.warning(f"Failed to parse provider info: {e}")

                return providers

            finally:
                await stream.close()

        except Exception as e:
            logger.warning(f"Error getting providers from {peer_id}: {e}")
            return []

    def add_provider(self, key: bytes, provider: PeerInfo) -> None:
        """
        Add a provider for a given content key.

        :param key: The content key
        :param provider: The provider's peer information

        Returns
        -------
        None

        """
        # Initialize providers for this key if needed
        if key not in self.providers:
            self.providers[key] = {}

        # Add or update the provider record
        peer_id_str = str(provider.peer_id)  # Use string representation as dict key
        self.providers[key][peer_id_str] = ProviderRecord(
            peer_id=provider.peer_id, addresses=provider.addrs, timestamp=time.time()
        )
        logger.debug(f"Added provider {provider.peer_id} for key {key.hex()}")

    def get_providers(self, key: bytes) -> list[PeerInfo]:
        """
        Get all providers for a given content key.

        :param key: The content key

        Returns
        -------
        List[PeerInfo]
            List of providers for the key

        """
        if key not in self.providers:
            return []

        # Collect valid provider records (not expired)
        result = []
        current_time = time.time()
        expired_peers = []

        for peer_id_str, record in self.providers[key].items():
            # Check if the record has expired
            if current_time - record.timestamp > PROVIDER_RECORD_EXPIRATION_INTERVAL:
                expired_peers.append(peer_id_str)
                continue

            # Use addresses only if they haven't expired
            addresses = []
            if current_time - record.timestamp <= PROVIDER_ADDRESS_TTL:
                addresses = record.addresses

            # Create PeerInfo and add to results
            result.append(PeerInfo(record.peer_id, addresses))

        # Clean up expired records
        for peer_id in expired_peers:
            del self.providers[key][peer_id]

        # Remove the key if no providers left
        if not self.providers[key]:
            del self.providers[key]

        return result

    def cleanup_expired(self) -> None:
        """Remove expired provider records."""
        current_time = time.time()
        expired_keys = []

        for key, providers in self.providers.items():
            expired_providers = []

            for peer_id_str, record in providers.items():
                if (
                    current_time - record.timestamp
                    > PROVIDER_RECORD_EXPIRATION_INTERVAL
                ):
                    expired_providers.append(peer_id_str)
                    logger.debug(
                        f"Removing expired provider {peer_id_str} for key {key.hex()}"
                    )

            # Remove expired providers
            for peer_id in expired_providers:
                del providers[peer_id]

            # Track empty keys for removal
            if not providers:
                expired_keys.append(key)

        # Remove empty keys
        for key in expired_keys:
            del self.providers[key]
            logger.debug(f"Removed key with no providers: {key.hex()}")

    def get_provided_keys(self, peer_id: ID) -> list[bytes]:
        """
        Get all content keys provided by a specific peer.

        :param peer_id: The peer ID to look for

        Returns
        -------
        List[bytes]
            List of content keys provided by the peer

        """
        peer_id_str = str(peer_id)
        result = []

        for key, providers in self.providers.items():
            if peer_id_str in providers:
                result.append(key)

        return result

    def size(self) -> int:
        """
        Get the number of content keys in the provider store.

        Returns
        -------
        int
            Number of content keys

        """
        return len(self.providers)
