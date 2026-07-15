import pytest
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.records.pb.ipns_pb2 import IpnsEntry

from py_ipfs_lite.ipns import create_ipns_record, publish_name, resolve_name


class MockRouting:
    def __init__(self):
        self.store = {}

    async def put_value(self, key: bytes, value: bytes) -> None:
        self.store[key] = value

    async def get_value(self, key: bytes) -> bytes:
        return self.store.get(key)

    async def provide(self, key: str) -> bool:
        pass

    async def find_providers(self, key: str, count: int):
        pass


@pytest.mark.trio
async def test_ipns_create_and_parse():
    keypair = create_new_key_pair()
    val = "/ipfs/QmTest"
    seq = 1

    record_bytes = create_ipns_record(keypair.private_key, val, seq)
    assert record_bytes is not None

    entry = IpnsEntry()
    entry.ParseFromString(record_bytes)
    assert entry.value.decode() == val
    assert entry.sequence == seq


@pytest.mark.trio
async def test_ipns_publish_resolve():
    keypair = create_new_key_pair()
    peer_id = ID.from_pubkey(keypair.public_key)

    routing = MockRouting()

    val = "/ipfs/QmTest123"
    await publish_name(routing, keypair.private_key, peer_id, val, 1)

    resolved = await resolve_name(routing, peer_id)
    assert resolved == val


def _create_expired_ipns_record(private_key, value: str, sequence: int) -> bytes:
    from datetime import datetime, timedelta, timezone

    import cbor2

    from py_ipfs_lite.ipns import SIGNATURE_PREFIX, IpnsEntry, _format_rfc3339

    value_bytes = value.encode("utf-8")
    now = datetime.now(timezone.utc)
    validity_dt = now - timedelta(hours=1)
    validity_bytes = _format_rfc3339(validity_dt).encode("utf-8")

    cbor_data_dict = {
        "Value": value_bytes,
        "Validity": validity_bytes,
        "ValidityType": 0,
        "Sequence": sequence,
    }
    cbor_bytes = cbor2.dumps(cbor_data_dict)
    signature_v2 = private_key.sign(SIGNATURE_PREFIX + cbor_bytes)
    signature_v1 = private_key.sign(value_bytes + validity_bytes + b"0")

    entry = IpnsEntry()
    entry.value = value_bytes
    entry.validity = validity_bytes
    entry.validityType = 0
    entry.signatureV1 = signature_v1
    entry.signatureV2 = signature_v2
    entry.sequence = sequence
    entry.data = cbor_bytes
    entry.pubKey = private_key.get_public_key().serialize()

    return entry.SerializeToString()


@pytest.mark.trio
async def test_ipns_validation_failures():
    from py_ipfs_lite.exceptions import RoutingError

    keypair = create_new_key_pair()
    peer_id = ID.from_pubkey(keypair.public_key)
    routing = MockRouting()

    # 1. Test expired record
    expired_bytes = _create_expired_ipns_record(keypair.private_key, "expired", 1)
    await routing.put_value(f"/ipns/{peer_id.to_base58()}", expired_bytes)
    with pytest.raises(RoutingError, match="expired"):
        await resolve_name(routing, peer_id)

    # 2. Test tampered signature
    valid_bytes = create_ipns_record(keypair.private_key, "valid", 1)
    entry = IpnsEntry()
    entry.ParseFromString(valid_bytes)
    # Tamper with the value
    entry.value = b"tampered"
    tampered_bytes = entry.SerializeToString()

    await routing.put_value(f"/ipns/{peer_id.to_base58()}", tampered_bytes)
    with pytest.raises(RoutingError, match="signature is invalid"):
        await resolve_name(routing, peer_id)

    # 3. Test wrong pubkey for peer ID
    keypair2 = create_new_key_pair()
    wrong_key_bytes = create_ipns_record(keypair2.private_key, "wrong_key", 1)
    # Put it under peer_id 1's DHT key
    await routing.put_value(f"/ipns/{peer_id.to_base58()}", wrong_key_bytes)
    with pytest.raises(RoutingError, match="pubKey does not match"):
        await resolve_name(routing, peer_id)


from httpx import ASGITransport, AsyncClient

from py_ipfs_lite.api import app
from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer


@pytest.fixture
def memory_config():
    return Config(blockstore_type="memory", reprovide_interval_seconds=-1)


@pytest.fixture
async def client(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    try:
        # Mock the routing to avoid network delays
        peer.routing = MockRouting()
        app.state.peer = peer
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await peer.close()


def test_ipns_sequence_bounds():
    from libp2p.crypto.ed25519 import create_new_key_pair

    from py_ipfs_lite.ipns import create_ipns_record

    keypair = create_new_key_pair()
    private_key = keypair.private_key

    # Negative
    with pytest.raises(
        ValueError, match="Sequence number must be a 64-bit unsigned integer"
    ):
        create_ipns_record(private_key, "/ipfs/QmTest", -1)

    # Overflow
    with pytest.raises(
        ValueError, match="Sequence number must be a 64-bit unsigned integer"
    ):
        create_ipns_record(private_key, "/ipfs/QmTest", 0xFFFFFFFFFFFFFFFF + 1)

    # Valid edge cases should not raise
    create_ipns_record(private_key, "/ipfs/QmTest", 0)
    create_ipns_record(private_key, "/ipfs/QmTest", 0xFFFFFFFFFFFFFFFF)


def test_ipns_lifetime_bounds():
    from libp2p.crypto.ed25519 import create_new_key_pair

    from py_ipfs_lite.ipns import create_ipns_record

    keypair = create_new_key_pair()
    private_key = keypair.private_key

    with pytest.raises(ValueError, match="lifetime_hours must be between 1 and 876000"):
        create_ipns_record(private_key, "/ipfs/QmTest", 1, lifetime_hours=0)

    with pytest.raises(ValueError, match="lifetime_hours must be between 1 and 876000"):
        create_ipns_record(private_key, "/ipfs/QmTest", 1, lifetime_hours=10**18)


@pytest.mark.trio
async def test_ipns_peer_methods(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    try:
        val = "/ipfs/QmSomething"
        # we need to mock routing for peer to test without real dht
        peer.routing = MockRouting()

        name = await peer.publish_name(val)
        assert name == peer.host.id().to_base58()

        resolved = await peer.resolve_name(name)
        assert resolved == val
    finally:
        await peer.close()


@pytest.mark.trio
async def test_ipns_endpoints(client):
    val = "/ipfs/QmApiTest"
    res1 = await client.post(f"/api/v0/name/publish?arg={val}")
    assert res1.status_code == 200
    data = res1.json()
    name = data["Name"]
    assert data["Value"] == val

    res2 = await client.get(f"/api/v0/name/resolve?arg={name}")
    assert res2.status_code == 200
    assert res2.json()["Path"] == val
