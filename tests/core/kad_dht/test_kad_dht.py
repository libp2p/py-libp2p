"""
Tests for the Kademlia DHT implementation.

This module tests core functionality of the Kademlia DHT including:
- Node discovery (find_node)
- Value storage and retrieval (put_value, get_value)
- Content provider advertisement and discovery (provide, find_providers)
"""

from collections.abc import Awaitable
import hashlib
import logging
import os
import random
from typing import TypeVar
from unittest.mock import patch
import uuid

import pytest
import multiaddr
import trio

from libp2p.crypto.rsa import create_new_key_pair
from libp2p.kad_dht.kad_dht import (
    DHTMode,
    KadDHT,
)
from libp2p.peer.envelope import Envelope, seal_record
from libp2p.peer.id import ID
from libp2p.peer.peer_record import PeerRecord
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import create_signed_peer_record
from libp2p.records.pubkey import PublicKeyValidator
from libp2p.records.utils import InvalidRecordType
from libp2p.records.validator import NamespacedValidator, Validator
from libp2p.tools.async_service import (
    background_trio_service,
)
from tests.utils.factories import (
    host_pair_factory,
)

# Configure logger
logger = logging.getLogger("test.kad_dht")

# Constants for the tests
TEST_TIMEOUT = 5  # Timeout in seconds


T = TypeVar("T")


async def retry(coro: Awaitable[T], retries: int = 3, delay: float = 0.5) -> T:
    """
    Retry a coroutine a few times to avoid flakiness on CI.
    Useful for async race conditions where routing tables
    may not be populated fast enough.
    """
    for i in range(retries):
        try:
            return await coro
        except AssertionError:
            if i == retries - 1:
                raise
            await trio.sleep(delay)

    # This should never be reached, but satisfies type checker
    raise RuntimeError("Retry function should not reach this point")


async def wait_for_peer_record(
    dht: KadDHT, peer_id: ID, timeout: float = TEST_TIMEOUT, delay: float = 0.1
) -> Envelope:
    """
    Wait for a peer record to become available in the peerstore.

    This is useful for handling timing issues on different platforms where
    peer records may not be immediately available after DHT operations.

    Parameters
    ----------
    dht : KadDHT
        The DHT node to check for the peer record.
    peer_id : ID
        The peer ID to wait for.
    timeout : float
        Maximum time to wait in seconds.
    delay : float
        Delay between retry attempts in seconds.

    Returns
    -------
    Envelope
        The peer record envelope once it becomes available.

    Raises
    ------
    TimeoutError
        If the peer record is not available within the timeout period.

    """
    start_time = trio.current_time()
    while True:
        envelope = dht.host.get_peerstore().get_peer_record(peer_id)
        if envelope is not None:
            return envelope

        if trio.current_time() - start_time > timeout:
            raise TimeoutError(
                f"Peer record for {peer_id} not available after {timeout} seconds"
            )

        await trio.sleep(delay)

    # add unreachable raise to satisfy Pyright
    raise TimeoutError("Unreachable code path")


class BlankValidator(Validator):
    def validate(self, key: str, value: bytes) -> None:
        return

    def select(self, key: str, values: list[bytes]) -> int:
        return 0


@pytest.fixture
async def dht_pair(security_protocol):
    """Create a pair of connected DHT nodes for testing."""
    async with host_pair_factory(security_protocol=security_protocol) as (
        host_a,
        host_b,
    ):
        # Get peer info for bootstrapping
        peer_b_info = PeerInfo(host_b.get_id(), host_b.get_addrs())
        peer_a_info = PeerInfo(host_a.get_id(), host_a.get_addrs())

        # Create a validator with 'test' namespace for testing
        # and 'pk' namespace for public key validation
        test_validator = NamespacedValidator(
            {
                "pk": PublicKeyValidator(),
                "test": BlankValidator(),
            }
        )

        # Create DHT nodes from the hosts with bootstrap peers as multiaddr strings
        dht_a: KadDHT = KadDHT(host_a, mode=DHTMode.SERVER, validator=test_validator)
        dht_b: KadDHT = KadDHT(host_b, mode=DHTMode.SERVER, validator=test_validator)
        await dht_a.peer_routing.routing_table.add_peer(peer_b_info)
        await dht_b.peer_routing.routing_table.add_peer(peer_a_info)

        # Start both DHT services
        async with background_trio_service(dht_a), background_trio_service(dht_b):
            # Allow time for bootstrap to complete and connections to establish
            await trio.sleep(0.1)

            # Force a connection between nodes to ensure routing table is populated
            # This eliminates the race condition by ensuring both nodes
            # know about each other
            try:
                await dht_a.find_peer(dht_b.host.get_id())
                await dht_b.find_peer(dht_a.host.get_id())
            except Exception as e:
                logger.warning(f"Initial peer discovery failed: {e}")
                # Continue anyway, the retry mechanism will handle it

            # Verify both nodes know about each other in their routing tables
            # This ensures the test won't have race conditions
            assert dht_a.routing_table.peer_in_table(dht_b.host.get_id()), (
                "Node A should know about Node B"
            )
            assert dht_b.routing_table.peer_in_table(dht_a.host.get_id()), (
                "Node B should know about Node A"
            )

            logger.debug(
                "After bootstrap: Node A peers: %s", dht_a.routing_table.get_peer_ids()
            )
            logger.debug(
                "After bootstrap: Node B peers: %s", dht_b.routing_table.get_peer_ids()
            )

            # Return the DHT pair
            yield (dht_a, dht_b)


@pytest.mark.trio
@pytest.mark.flaky(reruns=3, reruns_delay=1)
async def test_find_node(dht_pair: tuple[KadDHT, KadDHT]):
    """Test that nodes can find each other in the DHT."""
    dht_a, dht_b = dht_pair

    # An extra FIND_NODE req is sent between the 2 nodes while dht creation,
    # so both the nodes will have records of each other before the next FIND_NODE
    # req is sent. However, on some platforms (e.g., Windows), peer records may
    # not be immediately available due to timing differences. We wait for them
    # to become available, or trigger find_peer operations to exchange them if needed.
    with trio.fail_after(TEST_TIMEOUT):
        # Try to get peer records, waiting up to 1 second
        try:
            envelope_a = await wait_for_peer_record(
                dht_a, dht_b.host.get_id(), timeout=1.0
            )
            envelope_b = await wait_for_peer_record(
                dht_b, dht_a.host.get_id(), timeout=1.0
            )
        except TimeoutError:
            # If peer records aren't available yet, trigger find_peer to exchange them
            await dht_a.find_peer(dht_b.host.get_id())
            await dht_b.find_peer(dht_a.host.get_id())
            # Now wait for the records with the full timeout
            envelope_a = await wait_for_peer_record(dht_a, dht_b.host.get_id())
            envelope_b = await wait_for_peer_record(dht_b, dht_a.host.get_id())

    assert isinstance(envelope_a, Envelope)
    assert isinstance(envelope_b, Envelope)

    record_a = envelope_a.record()
    record_b = envelope_b.record()

    # Node A should be able to find Node B with retry mechanism
    with trio.fail_after(TEST_TIMEOUT):
        found_info = await retry(dht_a.find_peer(dht_b.host.get_id()))

    # Verifies if the senderRecord in the FIND_NODE request is correctly processed
    assert isinstance(
        dht_b.host.get_peerstore().get_peer_record(dht_a.host.get_id()), Envelope
    )

    # Verifies if the senderRecord in the FIND_NODE response is correctly processed
    assert isinstance(
        dht_a.host.get_peerstore().get_peer_record(dht_b.host.get_id()), Envelope
    )

    # These are the records that were sent between the peers during the FIND_NODE req
    envelope_a_find_peer = dht_a.host.get_peerstore().get_peer_record(
        dht_b.host.get_id()
    )
    envelope_b_find_peer = dht_b.host.get_peerstore().get_peer_record(
        dht_a.host.get_id()
    )

    assert isinstance(envelope_a_find_peer, Envelope)
    assert isinstance(envelope_b_find_peer, Envelope)

    record_a_find_peer = envelope_a_find_peer.record()
    record_b_find_peer = envelope_b_find_peer.record()

    # This proves that both the records are same, and a latest cached signed record
    # was passed between the peers during FIND_NODE execution, which proves the
    # signed-record transfer/re-issuing works correctly in FIND_NODE executions.
    assert record_a.seq == record_a_find_peer.seq
    assert record_b.seq == record_b_find_peer.seq

    # Verify that the found peer has the correct peer ID
    assert found_info is not None, "Failed to find the target peer"
    assert found_info.peer_id == dht_b.host.get_id(), "Found incorrect peer ID"


@pytest.mark.trio
async def test_put_and_get_value(dht_pair: tuple[KadDHT, KadDHT]):
    """Test storing and retrieving values in the DHT."""
    dht_a, dht_b = dht_pair
    # dht_a.peer_routing.routing_table.add_peer(dht_b.pe)
    peer_b_info = PeerInfo(dht_b.host.get_id(), dht_b.host.get_addrs())
    # Generate a random key and value (use namespaced key for API)
    key = "/test/random_key"
    key_bytes = key.encode("utf-8")
    value = b"test-value"

    # First add the value directly to node A's store to verify storage works
    dht_a.value_store.put(key_bytes, value)
    logger.debug("Local value store: %s", dht_a.value_store.store)
    local_value_record = dht_a.value_store.get(key_bytes)
    assert local_value_record is not None
    assert local_value_record.value == value, "Local value storage failed"
    print("number of nodes in peer store", dht_a.host.get_peerstore().peer_ids())
    await dht_a.routing_table.add_peer(peer_b_info)
    print("Routing table of a has ", dht_a.routing_table.get_peer_ids())

    # An extra FIND_NODE req is sent between the 2 nodes while dht creation,
    # so both the nodes will have records of each other before PUT_VALUE req is sent
    envelope_a = dht_a.host.get_peerstore().get_peer_record(dht_b.host.get_id())
    envelope_b = dht_b.host.get_peerstore().get_peer_record(dht_a.host.get_id())

    assert isinstance(envelope_a, Envelope)
    assert isinstance(envelope_b, Envelope)

    record_a = envelope_a.record()
    record_b = envelope_b.record()

    # Store the value using the first node (this will also store locally)
    with trio.fail_after(TEST_TIMEOUT):
        await dht_a.put_value(key, value)

    # These are the records that were sent between the peers during the PUT_VALUE req
    envelope_a_put_value = dht_a.host.get_peerstore().get_peer_record(
        dht_b.host.get_id()
    )
    envelope_b_put_value = dht_b.host.get_peerstore().get_peer_record(
        dht_a.host.get_id()
    )

    assert isinstance(envelope_a_put_value, Envelope)
    assert isinstance(envelope_b_put_value, Envelope)

    record_a_put_value = envelope_a_put_value.record()
    record_b_put_value = envelope_b_put_value.record()

    # This proves that both the records are same, and a latest cached signed record
    # was passed between the peers during PUT_VALUE execution, which proves the
    # signed-record transfer/re-issuing works correctly in PUT_VALUE executions.
    assert record_a.seq == record_a_put_value.seq
    assert record_b.seq == record_b_put_value.seq

    # # Log debugging information
    logger.debug("Put value with key %s...", key[:10])
    logger.debug("Node A value store: %s", dht_a.value_store.store)

    # # Allow more time for the value to propagate
    await trio.sleep(0.5)

    # # Try direct connection between nodes to ensure they're properly linked
    logger.debug("Node A peers: %s", dht_a.routing_table.get_peer_ids())
    logger.debug("Node B peers: %s", dht_b.routing_table.get_peer_ids())

    # Retrieve the value using the second node
    with trio.fail_after(TEST_TIMEOUT):
        retrieved_value = await dht_b.get_value(key)
        print("the value stored in node b is", dht_b.get_value_store_size())
        logger.debug("Retrieved value: %s", retrieved_value)

    # These are the records that were sent between the peers during the PUT_VALUE req
    envelope_a_get_value = dht_a.host.get_peerstore().get_peer_record(
        dht_b.host.get_id()
    )
    envelope_b_get_value = dht_b.host.get_peerstore().get_peer_record(
        dht_a.host.get_id()
    )

    assert isinstance(envelope_a_get_value, Envelope)
    assert isinstance(envelope_b_get_value, Envelope)

    record_a_get_value = envelope_a_get_value.record()
    record_b_get_value = envelope_b_get_value.record()

    # This proves that there was no record exchange between the nodes during GET_VALUE
    # execution, as dht_b already had the key/value pair stored locally after the
    # PUT_VALUE execution.
    assert record_a_get_value.seq == record_a_put_value.seq
    assert record_b_get_value.seq == record_b_put_value.seq

    # Verify that the retrieved value matches the original
    assert retrieved_value == value, "Retrieved value does not match the stored value"

    # TEST PUB-KEY VALIDATORS

    # VALID KEY PAIR
    keypair = create_new_key_pair()
    peer_id = ID.from_pubkey(keypair.public_key)
    key = f"/pk/{peer_id.to_bytes().hex()}"
    value = keypair.public_key.serialize()

    with trio.fail_after(TEST_TIMEOUT):
        await dht_a.put_value(key, value)  # Now accepts string directly

    # INVALID KEY PAIR
    key = "/pk/abcdef1234567890"  # Not a valid multihash
    value = b"not-a-real-key"

    with trio.fail_after(TEST_TIMEOUT):
        with pytest.raises(InvalidRecordType, match="valid multihash"):
            await dht_a.put_value(key, value)  # Now accepts string directly


@pytest.mark.trio
@pytest.mark.flaky(reruns=3, reruns_delay=1)
async def test_provide_and_find_providers(dht_pair: tuple[KadDHT, KadDHT]):
    """Test advertising and finding content providers."""
    dht_a, dht_b = dht_pair

    # Generate a random content ID
    content = f"test-content-{uuid.uuid4()}".encode()
    content_id = "/test/random_content"  # Namespaced key for API
    content_id_bytes = content_id.encode("utf-8")  # Bytes for internal storage

    # Store content on the first node
    dht_a.value_store.put(content_id_bytes, content)

    # An extra FIND_NODE req is sent between the 2 nodes while dht creation,
    # so both the nodes will have records of each other before PUT_VALUE req is sent
    envelope_a = dht_a.host.get_peerstore().get_peer_record(dht_b.host.get_id())
    envelope_b = dht_b.host.get_peerstore().get_peer_record(dht_a.host.get_id())

    assert isinstance(envelope_a, Envelope)
    assert isinstance(envelope_b, Envelope)

    record_a = envelope_a.record()
    record_b = envelope_b.record()

    # Advertise the first node as a provider
    with trio.fail_after(TEST_TIMEOUT):
        success = await dht_a.provide(content_id)
        assert success, "Failed to advertise as provider"

    # These are the records that were sent between the peers during
    # the ADD_PROVIDER req
    envelope_a_add_prov = dht_a.host.get_peerstore().get_peer_record(
        dht_b.host.get_id()
    )
    envelope_b_add_prov = dht_b.host.get_peerstore().get_peer_record(
        dht_a.host.get_id()
    )

    assert isinstance(envelope_a_add_prov, Envelope)
    assert isinstance(envelope_b_add_prov, Envelope)

    record_a_add_prov = envelope_a_add_prov.record()
    record_b_add_prov = envelope_b_add_prov.record()

    # This proves that both the records are same, the latest cached signed record
    # was passed between the peers during ADD_PROVIDER execution, which proves the
    # signed-record transfer/re-issuing of the latest record works correctly in
    # ADD_PROVIDER executions.
    assert record_a.seq == record_a_add_prov.seq
    assert record_b.seq == record_b_add_prov.seq

    # Allow time for the provider record to propagate
    await trio.sleep(0.5)

    # Find providers using the second node with retry logic for CI robustness
    # Retry to handle potential race conditions where provider hasn't propagated yet
    with trio.fail_after(TEST_TIMEOUT):

        async def find_and_verify_providers() -> list[PeerInfo]:
            providers = await dht_b.find_providers(content_id)
            # Verify that we found the first node as a provider
            assert providers, "No providers found"
            assert any(p.peer_id == dht_a.local_peer_id for p in providers), (
                "Expected provider not found"
            )
            return providers

        # Retry with verification to handle race conditions
        await retry(find_and_verify_providers(), retries=5, delay=0.3)

    # These are the records in each peer after the find_provider execution
    envelope_a_find_prov = dht_a.host.get_peerstore().get_peer_record(
        dht_b.host.get_id()
    )
    envelope_b_find_prov = dht_b.host.get_peerstore().get_peer_record(
        dht_a.host.get_id()
    )

    assert isinstance(envelope_a_find_prov, Envelope)
    assert isinstance(envelope_b_find_prov, Envelope)

    record_a_find_prov = envelope_a_find_prov.record()
    record_b_find_prov = envelope_b_find_prov.record()

    # This proves that both the records are same, as the dht_b already
    # has the provider record for the content_id, after the ADD_PROVIDER
    # advertisement by dht_a
    assert record_a_find_prov.seq == record_a_add_prov.seq
    assert record_b_find_prov.seq == record_b_add_prov.seq

    # Retrieve the content using the provider information
    with trio.fail_after(TEST_TIMEOUT):
        retrieved_value = await dht_b.get_value(content_id)
        assert retrieved_value == content, (
            "Retrieved content does not match the original"
        )

    # These are the record state of each peer aftet the GET_VALUE execution
    envelope_a_get_value = dht_a.host.get_peerstore().get_peer_record(
        dht_b.host.get_id()
    )
    envelope_b_get_value = dht_b.host.get_peerstore().get_peer_record(
        dht_a.host.get_id()
    )

    assert isinstance(envelope_a_get_value, Envelope)
    assert isinstance(envelope_b_get_value, Envelope)

    record_a_get_value = envelope_a_get_value.record()
    record_b_get_value = envelope_b_get_value.record()

    # This proves that both the records are same, meaning that the latest cached
    # signed-record tranfer happened during the GET_VALUE execution by dht_b,
    # which means the signed-record transfer/re-issuing works correctly
    # in GET_VALUE executions.
    assert record_a_find_prov.seq == record_a_get_value.seq
    assert record_b_find_prov.seq == record_b_get_value.seq

    # Create a new provider record in dht_a
    provider_key_pair = create_new_key_pair()
    provider_peer_id = ID.from_pubkey(provider_key_pair.public_key)
    provider_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/123")
    provider_peer_info = PeerInfo(peer_id=provider_peer_id, addrs=[provider_addr])

    # Generate a random content ID
    content_2 = f"random-content-{uuid.uuid4()}".encode()
    content_id_2 = str(hashlib.sha256(content_2).digest()).encode()

    provider_signed_envelope = create_signed_peer_record(
        provider_peer_id, [provider_addr], provider_key_pair.private_key
    )
    assert (
        dht_a.host.get_peerstore().consume_peer_record(provider_signed_envelope, 7200)
        is True
    )

    # Store this provider record in dht_a
    dht_a.provider_store.add_provider(content_id_2, provider_peer_info)

    # Fetch the provider-record via peer-discovery at dht_b's end
    peerinfo = await dht_b.provider_store.find_providers(content_id_2)

    assert len(peerinfo) == 1
    assert peerinfo[0].peer_id == provider_peer_id
    provider_envelope = dht_b.host.get_peerstore().get_peer_record(provider_peer_id)

    # This proves that the signed-envelope of provider is consumed on dht_b's end
    assert provider_envelope is not None
    assert (
        provider_signed_envelope.marshal_envelope()
        == provider_envelope.marshal_envelope()
    )


@pytest.mark.trio
async def test_reissue_when_listen_addrs_change(dht_pair: tuple[KadDHT, KadDHT]):
    dht_a, dht_b = dht_pair

    # Warm-up: A stores B's current record
    with trio.fail_after(10):
        await dht_a.find_peer(dht_b.host.get_id())

    env0 = dht_a.host.get_peerstore().get_peer_record(dht_b.host.get_id())
    assert isinstance(env0, Envelope)
    seq0 = env0.record().seq

    # Simulate B's listen addrs changing (different port)
    # Pick a port unlikely to be used, or increment existing port
    new_addr = multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{random.randint(20000, 40000)}")

    # Patch just for the duration we force B to respond:
    with patch.object(dht_b.host, "get_addrs", return_value=[new_addr]):
        # Force B to send a response (which should include a fresh SPR)
        with trio.fail_after(10):
            await dht_a.peer_routing._query_peer_for_closest(
                dht_b.host.get_id(), os.urandom(32)
            )

    # A should now hold B's new record with a bumped seq
    env1 = dht_a.host.get_peerstore().get_peer_record(dht_b.host.get_id())
    assert isinstance(env1, Envelope)
    seq1 = env1.record().seq

    # This proves that upon the change in listen_addrs, we issue new records
    assert seq1 > seq0, f"Expected seq to bump after addr change, got {seq0} -> {seq1}"


@pytest.mark.trio
async def test_dht_req_fail_with_invalid_record_transfer(
    dht_pair: tuple[KadDHT, KadDHT],
):
    """
    Testing showing failure of storing and retrieving values in the DHT,
    if invalid signed-records are sent.
    """
    dht_a, dht_b = dht_pair
    peer_b_info = PeerInfo(dht_b.host.get_id(), dht_b.host.get_addrs())

    # Generate a random key and value (use namespaced key)
    key = "/test/random_key"  # Namespaced key for API
    key_bytes = key.encode("utf-8")  # Bytes for internal storage
    value = b"test-value"

    # First add the value directly to node A's store to verify storage works
    dht_a.value_store.put(key_bytes, value)
    local_value = dht_a.value_store.get(key_bytes)
    assert local_value is not None
    assert local_value.value == value, "Local value storage failed"
    await dht_a.routing_table.add_peer(peer_b_info)

    # Corrupt dht_a's local peer_record
    envelope = dht_a.host.get_peerstore().get_local_record()
    if envelope is not None:
        true_record = envelope.record()
    key_pair = create_new_key_pair()

    if envelope is not None:
        envelope.public_key = key_pair.public_key
        dht_a.host.get_peerstore().set_local_record(envelope)

    await dht_a.put_value(key, value)
    retrieved_value_record = dht_b.value_store.get(key_bytes)

    # This proves that DHT_B rejected DHT_A PUT_RECORD req upon receiving
    # the corrupted invalid record
    assert retrieved_value_record is None

    # Create a corrupt envelope with correct signature but false peer_id
    false_record = PeerRecord(ID.from_pubkey(key_pair.public_key), true_record.addrs)
    false_envelope = seal_record(false_record, dht_a.host.get_private_key())

    dht_a.host.get_peerstore().set_local_record(false_envelope)

    await dht_a.put_value(key, value)
    retrieved_value_record = dht_b.value_store.get(key_bytes)

    # This proves that DHT_B rejected DHT_A PUT_RECORD req upon receving
    # the record with a different peer_id regardless of a valid signature
    assert retrieved_value_record is None


@pytest.mark.trio
async def test_register_validator(dht_pair: tuple[KadDHT, KadDHT]):
    """Test that custom validators can be registered and used."""
    dht_a, dht_b = dht_pair

    # Create a custom validator that only accepts values starting with "valid:"
    class CustomValidator(Validator):
        def validate(self, key: str, value: bytes) -> None:
            if not value.startswith(b"valid:"):
                raise ValueError("Value must start with 'valid:'")

        def select(self, key: str, values: list[bytes]) -> int:
            return 0

    # Register the custom validator for "custom" namespace
    dht_a.register_validator("custom", CustomValidator())
    dht_b.register_validator("custom", CustomValidator())

    # Test 1: Valid value should be stored successfully
    key = "/custom/my-key"
    valid_value = b"valid:test-data"

    with trio.fail_after(TEST_TIMEOUT):
        await dht_a.put_value(key, valid_value)

    # Value should be stored locally
    key_bytes = key.encode("utf-8")
    stored = dht_a.value_store.get(key_bytes)
    assert stored is not None
    assert stored.value == valid_value

    # Test 2: Invalid value should raise an error
    invalid_value = b"invalid-data"
    with pytest.raises(ValueError, match="Value must start with 'valid:'"):
        await dht_a.put_value(key, invalid_value)

    # Test 3: Key with unregistered namespace should raise InvalidRecordType
    unregistered_key = "/unknown/some-key"
    with pytest.raises(InvalidRecordType):
        await dht_a.put_value(unregistered_key, b"some-value")
