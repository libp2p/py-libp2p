import time

from multiaddr import Multiaddr

from libp2p.peer.id import ID
import libp2p.peer.pb.peer_record_pb2 as pb
from libp2p.peer.peer_record import (
    PeerRecord,
    addrs_from_protobuf,
    peer_record_from_protobuf,
    unmarshal_record,
)

# Testing methods from PeerRecord base class and PeerRecord protobuf:


def test_basic_protobuf_serializatrion_deserialization():
    record = pb.PeerRecord()
    record.seq = 1

    serialized = record.SerializeToString()
    new_record = pb.PeerRecord()
    new_record.ParseFromString(serialized)

    assert new_record.seq == 1


def test_timestamp_seq_monotonicity():
    rec1 = PeerRecord()
    time.sleep(1)
    rec2 = PeerRecord()

    assert isinstance(rec1.seq, int)
    assert isinstance(rec2.seq, int)
    assert rec2.seq > rec1.seq, f"Expected seq2 ({rec2.seq}) > seq1 ({rec1.seq})"


def test_addrs_from_protobuf_multiple_addresses():
    ma1 = Multiaddr("/ip4/127.0.0.1/tcp/4001")
    ma2 = Multiaddr("/ip4/127.0.0.1/tcp/4002")

    addr_info1 = pb.PeerRecord.AddressInfo()
    addr_info1.multiaddr = ma1.to_bytes()

    addr_info2 = pb.PeerRecord.AddressInfo()
    addr_info2.multiaddr = ma2.to_bytes()

    result = addrs_from_protobuf([addr_info1, addr_info2])
    assert result == [ma1, ma2]


def test_peer_record_from_protobuf():
    peer_id = ID.from_base58("QmNM23MiU1Kd7yfiKVdUnaDo8RYca8By4zDmr7uSaVV8Px")
    record = pb.PeerRecord()
    record.peer_id = peer_id.to_bytes()
    record.seq = 42

    for addr_str in ["/ip4/127.0.0.1/tcp/4001", "/ip4/127.0.0.1/tcp/4002"]:
        ma = Multiaddr(addr_str)
        addr_info = pb.PeerRecord.AddressInfo()
        addr_info.multiaddr = ma.to_bytes()
        record.addresses.append(addr_info)

    result = peer_record_from_protobuf(record)

    assert result.peer_id == peer_id
    assert result.seq == 42
    assert len(result.addrs) == 2
    assert str(result.addrs[0]) == "/ip4/127.0.0.1/tcp/4001"
    assert str(result.addrs[1]) == "/ip4/127.0.0.1/tcp/4002"


def test_to_protobuf_generates_correct_message():
    peer_id = ID.from_base58("QmNM23MiU1Kd7yfiKVdUnaDo8RYca8By4zDmr7uSaVV8Px")
    addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
    seq = 12345

    record = PeerRecord(peer_id, addrs, seq)
    proto = record.to_protobuf()

    assert isinstance(proto, pb.PeerRecord)
    assert proto.peer_id == peer_id.to_bytes()
    assert proto.seq == seq
    assert len(proto.addresses) == 1
    assert proto.addresses[0].multiaddr == addrs[0].to_bytes()


def test_unmarshal_record_roundtrip():
    record = PeerRecord(
        peer_id=ID.from_base58("QmNM23MiU1Kd7yfiKVdUnaDo8RYca8By4zDmr7uSaVV8Px"),
        addrs=[Multiaddr("/ip4/127.0.0.1/tcp/4001")],
        seq=999,
    )

    serialized = record.to_protobuf().SerializeToString()
    deserialized = unmarshal_record(serialized)

    assert deserialized.peer_id == record.peer_id
    assert deserialized.seq == record.seq
    assert len(deserialized.addrs) == 1
    assert deserialized.addrs[0] == record.addrs[0]


def test_marshal_record_and_equal():
    peer_id = ID.from_base58("QmNM23MiU1Kd7yfiKVdUnaDo8RYca8By4zDmr7uSaVV8Px")
    addrs = [Multiaddr("/ip4/127.0.0.1/tcp/4001")]
    original = PeerRecord(peer_id, addrs)

    serialized = original.marshal_record()
    deserailzed = unmarshal_record(serialized)

    assert original.equal(deserailzed)
