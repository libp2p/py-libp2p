import pytest
import trio

from libp2p.pubsub.gossipsub import (
    MAX_EQUIVOCATION_ENTRIES,
    PROTOCOL_ID_V20,
    GossipSub,
    _message_fingerprint,
)
from libp2p.pubsub.pb import rpc_pb2
from tests.utils.factories import PubsubFactory


@pytest.mark.trio
async def test_seen_message_cache_is_stopped_with_service():
    """
    Closing a Pubsub must stop the sweeper thread and free its cache.

    The seen-message cache owns a background thread; leaving it running kept
    the cache (and the Pubsub's message IDs) alive for the rest of the
    process, one thread per host ever created.
    """
    async with PubsubFactory.create_batch_with_gossipsub(1) as pubsubs:
        pubsub = pubsubs[0]
        await pubsub.subscribe("topic")
        await pubsub.publish("topic", b"payload")
        await trio.sleep(0.2)
        cache = pubsub.seen_messages
        assert cache.length() > 0
        assert cache._thread.is_alive()

    assert not cache._thread.is_alive()
    assert cache.length() == 0


def test_equivocation_detection_is_bounded_on_insert():
    """
    Equivocation tracking must not grow between heartbeats.

    Each entry used to hold the full first message, and the table was only
    trimmed during the heartbeat sweep, so a peer could park megabytes of
    payloads in it for a whole heartbeat interval.
    """
    gossipsub = GossipSub(
        protocols=[PROTOCOL_ID_V20],
        degree=6,
        degree_low=4,
        degree_high=12,
    )
    peer = b"\x11" * 8

    for seqno in range(MAX_EQUIVOCATION_ENTRIES + 500):
        msg = rpc_pb2.Message(
            data=b"x" * 1024,
            topicIDs=["topic"],
            from_id=peer,
            seqno=seqno.to_bytes(8, "big"),
        )
        assert gossipsub._check_equivocation(msg)

    assert len(gossipsub.equivocation_detection) == MAX_EQUIVOCATION_ENTRIES
    assert all(
        isinstance(value, bytes) and len(value) <= 64
        for value in gossipsub.equivocation_detection.values()
    )


def test_equivocation_still_detected_after_bounding():
    gossipsub = GossipSub(
        protocols=[PROTOCOL_ID_V20],
        degree=6,
        degree_low=4,
        degree_high=12,
    )
    peer = b"\x22" * 8
    original = rpc_pb2.Message(
        data=b"original",
        topicIDs=["topic"],
        from_id=peer,
        seqno=b"1",
    )
    conflicting = rpc_pb2.Message(
        data=b"conflicting",
        topicIDs=["topic"],
        from_id=peer,
        seqno=b"1",
    )

    assert gossipsub._check_equivocation(original)
    assert gossipsub._check_equivocation(original)
    assert not gossipsub._check_equivocation(conflicting)
    assert gossipsub.equivocation_detection[peer + b"1"] == _message_fingerprint(
        original
    )


def test_observe_tracking_is_capped_per_peer():
    """
    A peer cannot register unlimited topics via OBSERVE.

    The observer set was keyed by peer-supplied topic strings and only cleared
    on UNOBSERVE or disconnect, so one connected peer could grow it without
    bound for as long as the connection lived.
    """
    from libp2p.pubsub.extensions import (
        MAX_OBSERVED_TOPICS_PER_PEER,
        TopicObservationState,
    )

    state = TopicObservationState()
    peer = b"\x33" * 8

    for i in range(MAX_OBSERVED_TOPICS_PER_PEER + 50):
        state.add_observer(f"topic-{i}", peer)

    tracked = sum(len(peers) for peers in state._observers.values())
    assert tracked == MAX_OBSERVED_TOPICS_PER_PEER
    assert state.get_observers("topic-0") == {peer}
    assert state.get_observers(f"topic-{MAX_OBSERVED_TOPICS_PER_PEER + 49}") == set()

    state.remove_peer(peer)
    assert state._observers == {}
    assert state._topics_by_observer == {}
