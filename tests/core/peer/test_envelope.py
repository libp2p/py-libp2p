from multiaddr import Multiaddr

from libp2p.crypto.rsa import (
    create_new_key_pair,
)
from libp2p.peer.envelope import (
    PEER_RECORD_CODEC,
    Envelope,
    consume_envelope,
    make_unsigned,
    seal_record,
    unmarshal_envelope,
)
from libp2p.peer.id import ID
import libp2p.peer.pb.crypto_pb2 as crypto_pb
import libp2p.peer.pb.envelope_pb2 as env_pb
from libp2p.peer.peer_record import PeerRecord

DOMAIN = "libp2p-peer-record"


def test_basic_protobuf_serialization_deserialization():
    pubkey = crypto_pb.PublicKey()
    pubkey.Type = crypto_pb.KeyType.Ed25519
    pubkey.Data = b"\x01\x02\x03"

    env = env_pb.Envelope()
    env.public_key.CopyFrom(pubkey)
    env.payload_type = PEER_RECORD_CODEC
    env.payload = b"test-payload"
    env.signature = b"signature-bytes"

    serialized = env.SerializeToString()

    new_env = env_pb.Envelope()
    new_env.ParseFromString(serialized)

    assert new_env.public_key.Type == crypto_pb.KeyType.Ed25519
    assert new_env.public_key.Data == b"\x01\x02\x03"
    assert new_env.payload_type == PEER_RECORD_CODEC
    assert new_env.payload == b"test-payload"
    assert new_env.signature == b"signature-bytes"


def test_enevelope_marshal_unmarshal_roundtrip():
    keypair = create_new_key_pair()
    pubkey = keypair.public_key
    private_key = keypair.private_key

    payload_type = PEER_RECORD_CODEC
    payload = b"test-record"
    sig = private_key.sign(make_unsigned(DOMAIN, payload_type, payload))

    env = Envelope(pubkey, payload_type, payload, sig)
    serialized = env.marshal_envelope()
    new_env = unmarshal_envelope(serialized)

    assert new_env.public_key == pubkey
    assert new_env.payload_type == payload_type
    assert new_env.raw_payload == payload
    assert new_env.signature == sig


def test_seal_and_consume_envelope_roundtrip():
    keypair = create_new_key_pair()
    priv_key = keypair.private_key
    pub_key = keypair.public_key

    peer_id = ID.from_pubkey(pub_key)
    addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001"), Multiaddr("/ip4/127.0.0.1/tcp/4002")]
    seq = 12345

    record = PeerRecord(peer_id=peer_id, addrs=addrs, seq=seq)

    # Seal
    envelope = seal_record(record, priv_key)
    serialized = envelope.marshal_envelope()

    # Consume
    env, rec = consume_envelope(serialized, record.domain())

    # Assertions
    assert env.public_key == pub_key
    assert rec.peer_id == peer_id
    assert rec.seq == seq
    assert rec.addrs == addrs


def test_envelope_equal():
    # Create a new keypair
    keypair = create_new_key_pair()
    private_key = keypair.private_key

    # Create a mock PeerRecord
    record = PeerRecord(
        peer_id=ID.from_base58("QmNM23MiU1Kd7yfiKVdUnaDo8RYca8By4zDmr7uSaVV8Px"),
        seq=1,
        addrs=[Multiaddr("/ip4/127.0.0.1/tcp/4001")],
    )

    # Seal it into an Envelope
    env1 = seal_record(record, private_key)

    # Create a second identical envelope
    env2 = Envelope(
        public_key=env1.public_key,
        payload_type=env1.payload_type,
        raw_payload=env1.raw_payload,
        signature=env1.signature,
    )

    # They should be equal
    assert env1.equal(env2)

    # Now change something — payload type
    # Change the underlying Code on env2 to a different one
    env2.payload_type_code = env1.payload_type_code
    env2.payload_type_code = type(env1.payload_type_code)(0x99)
    assert not env1.equal(env2)

    # Restore payload_type but change signature
    env2.payload_type_code = env1.payload_type_code
    env2.signature = b"wrong-signature"
    assert not env1.equal(env2)

    # Restore signature but change payload
    env2.signature = env1.signature
    env2.raw_payload = b"tampered"
    assert not env1.equal(env2)

    # Finally, test with a non-envelope object
    assert not env1.equal("not-an-envelope")
