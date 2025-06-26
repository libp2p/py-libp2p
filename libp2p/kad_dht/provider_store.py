"""
Provider record storage for Kademlia DHT.

This module implements the storage for content provider records in the Kademlia DHT.
"""

import logging
import time
from typing import (
    Any,
)

from multiaddr import (
    Multiaddr,
)
import trio
import varint

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

from .common import (
    ALPHA,
    PROTOCOL_ID,
    QUERY_TIMEOUT,
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


class ProviderRecord:
    """
    A record for a content provider in the DHT.

    Contains the peer information and timestamp.
    """

    def __init__(
        self,
        provider_info: PeerInfo,
        timestamp: float | None = None,
    ) -> None:
        """
        Initialize a new provider record.

        :param provider_info: The provider's peer information
        :param timestamp: Time this record was created/updated
                          (defaults to current time)

        """
        self.provider_info = provider_info
        self.timestamp = timestamp or time.time()

    def is_expired(self) -> bool:
        """
        Check if this provider record has expired.

        Returns
        -------
        bool
            True if the record has expired

        """
        current_time = time.time()
        return (current_time - self.timestamp) >= PROVIDER_RECORD_EXPIRATION_INTERVAL

    def should_republish(self) -> bool:
        """
        Check if this provider record should be republished.

        Returns
        -------
        bool
            True if the record should be republished

        """
        current_time = time.time()
        return (current_time - self.timestamp) >= PROVIDER_RECORD_REPUBLISH_INTERVAL

    @property
    def peer_id(self) -> ID:
        """Get the provider's peer ID."""
        return self.provider_info.peer_id

    @property
    def addresses(self) -> list[Multiaddr]:
        """Get the provider's addresses."""
        return self.provider_info.addrs


class ProviderStore:
    """
    Store for content provider records in the Kademlia DHT.

    Maps content keys to provider records, with support for expiration.
    """

    def __init__(self, host: IHost, peer_routing: Any = None) -> None:
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
        self.local_peer_id = host.get_id()

    async def _republish_provider_records(self) -> None:
        """Republish all provider records for content this node is providing."""
        # First, republish keys we're actively providing
        for key in self.providing_keys:
            logger.debug(f"Republishing provider record for key {key.hex()}")
            await self.provide(key)

        # Also check for any records that should be republished
        time.time()
        for key, providers in self.providers.items():
            for peer_id_str, record in providers.items():
                # Only republish records for our own peer
                if self.local_peer_id and str(self.local_peer_id) == peer_id_str:
                    if record.should_republish():
                        logger.debug(
                            f"Republishing old provider record for key {key.hex()}"
                        )
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
        logger.debug(
            "Found %d peers close to key %s for provider advertisement",
            len(closest_peers),
            key.hex(),
        )

        # Send ADD_PROVIDER messages to these ALPHA peers in parallel.
        success_count = 0
        for i in range(0, len(closest_peers), ALPHA):
            batch = closest_peers[i : i + ALPHA]
            results: list[bool] = [False] * len(batch)

            async def send_one(
                idx: int, peer_id: ID, results: list[bool] = results
            ) -> None:
                if peer_id == self.local_peer_id:
                    return
                try:
                    with trio.move_on_after(QUERY_TIMEOUT):
                        success = await self._send_add_provider(peer_id, key)
                        results[idx] = success
                        if not success:
                            logger.warning(f"Failed to send ADD_PROVIDER to {peer_id}")
                except Exception as e:
                    logger.warning(f"Error sending ADD_PROVIDER to {peer_id}: {e}")

            async with trio.open_nursery() as nursery:
                for idx, peer_id in enumerate(batch):
                    nursery.start_soon(send_one, idx, peer_id, results)
            success_count += sum(results)

        logger.info(f"Successfully advertised to {success_count} peers")
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
            result = False
            # Open a stream to the peer
            stream = await self.host.new_stream(peer_id, [TProtocol(PROTOCOL_ID)])

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
            await stream.write(varint.encode(len(proto_bytes)))
            await stream.write(proto_bytes)
            logger.debug(f"Sent ADD_PROVIDER to {peer_id} for key {key.hex()}")
            # Read response length prefix
            length_bytes = b""
            while True:
                logger.debug("Reading response length prefix in add provider")
                b = await stream.read(1)
                if not b:
                    return False
                length_bytes += b
                if b[0] & 0x80 == 0:
                    break

            response_length = varint.decode_bytes(length_bytes)
            # Read response data
            response_bytes = b""
            remaining = response_length
            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    return False
                response_bytes += chunk
                remaining -= len(chunk)

            # Parse response
            response = Message()
            response.ParseFromString(response_bytes)

            # Check response type
            response.type == Message.MessageType.ADD_PROVIDER
            if response.type:
                result = True

        except Exception as e:
            logger.warning(f"Error sending ADD_PROVIDER to {peer_id}: {e}")

        finally:
            await stream.close()
            return result

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
            logger.debug(
                f"Found {len(local_providers)} providers locally for {key.hex()}"
            )
            return local_providers[:count]
        logger.debug("local providers are %s", local_providers)

        # Find the closest peers to the key
        closest_peers = await self.peer_routing.find_closest_peers_network(key)
        logger.debug(
            f"Searching {len(closest_peers)} peers for providers of {key.hex()}"
        )

        # Query these peers for providers in batches of ALPHA, in parallel, with timeout
        all_providers = []
        for i in range(0, len(closest_peers), ALPHA):
            batch = closest_peers[i : i + ALPHA]
            batch_results: list[list[PeerInfo]] = [[] for _ in batch]

            async def get_one(
                idx: int,
                peer_id: ID,
                batch_results: list[list[PeerInfo]] = batch_results,
            ) -> None:
                if peer_id == self.local_peer_id:
                    return
                try:
                    with trio.move_on_after(QUERY_TIMEOUT):
                        providers = await self._get_providers_from_peer(peer_id, key)
                        if providers:
                            for provider in providers:
                                self.add_provider(key, provider)
                            batch_results[idx] = providers
                        else:
                            logger.debug(f"No providers found at peer {peer_id}")
                except Exception as e:
                    logger.warning(f"Failed to get providers from {peer_id}: {e}")

            async with trio.open_nursery() as nursery:
                for idx, peer_id in enumerate(batch):
                    nursery.start_soon(get_one, idx, peer_id, batch_results)

            for providers in batch_results:
                all_providers.extend(providers)
                if len(all_providers) >= count:
                    return all_providers[:count]

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
        providers: list[PeerInfo] = []
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
                await stream.write(varint.encode(len(proto_bytes)))
                await stream.write(proto_bytes)

                # Read response length prefix
                length_bytes = b""
                while True:
                    b = await stream.read(1)
                    if not b:
                        return []
                    length_bytes += b
                    if b[0] & 0x80 == 0:
                        break

                response_length = varint.decode_bytes(length_bytes)
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

            finally:
                await stream.close()
                return providers

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
            provider_info=provider, timestamp=time.time()
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
        Get the total number of provider records in the store.

        Returns
        -------
        int
            Total number of provider records across all keys

        """
        total = 0
        for providers in self.providers.values():
            total += len(providers)
        return total
