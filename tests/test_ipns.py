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


@pytest.mark.trio
async def test_ipns_validation_failures():
    from py_ipfs_lite.exceptions import RoutingError

    keypair = create_new_key_pair()
    peer_id = ID.from_pubkey(keypair.public_key)
    routing = MockRouting()

    # 1. Test expired record
    expired_bytes = create_ipns_record(
        keypair.private_key, "expired", 1, lifetime_hours=-1
    )
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
