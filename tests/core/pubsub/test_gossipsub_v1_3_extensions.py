from unittest.mock import AsyncMock

import pytest

from libp2p.peer.id import ID
from libp2p.pubsub.extensions import (
    ExtensionsState,
    PeerExtensions,
    TopicObservationState,
)
from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID_V13,
    GossipSub,
)
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.score import ScoreParams
from libp2p.tools.constants import GOSSIPSUB_PARAMS
from tests.utils.factories import (
    GossipsubFactory,
    IDFactory,
)

# ---------------------------------------------------------------------------
# PeerExtensions tests
# ---------------------------------------------------------------------------


def test_peer_extensions_encode_decode_roundtrip() -> None:
    """PeerExtensions should roundtrip via ControlExtensions."""
    ext = PeerExtensions(topic_observation=True, test_extension=True)
    wire = ext.to_control_extensions()

    decoded = PeerExtensions.from_control_extensions(wire)

    assert decoded.topic_observation is True
    assert decoded.test_extension is True


def test_peer_extensions_has_any() -> None:
    """has_any() reflects whether at least one feature is enabled."""
    ext = PeerExtensions()
    assert not ext.has_any()

    ext.topic_observation = True
    assert ext.has_any()

    ext.topic_observation = False
    ext.test_extension = True
    assert ext.has_any()


# ---------------------------------------------------------------------------
# ExtensionsState tests
# ---------------------------------------------------------------------------


def _make_rpc_with_extensions(
    *, topic_observation: bool = False, test_extension: bool = False
) -> rpc_pb2.RPC:
    rpc = rpc_pb2.RPC()
    control = rpc_pb2.ControlMessage()
    wire = PeerExtensions(
        topic_observation=topic_observation,
        test_extension=test_extension,
    ).to_control_extensions()
    control.extensions.CopyFrom(wire)
    rpc.control.CopyFrom(control)
    return rpc


def test_build_hello_extensions_attaches_control_extensions() -> None:
    """build_hello_extensions should attach ControlExtensions and mark peer as sent."""
    peer_id = IDFactory()
    hello = rpc_pb2.RPC()

    state = ExtensionsState(
        my_extensions=PeerExtensions(topic_observation=True, test_extension=True)
    )

    mutated = state.build_hello_extensions(peer_id, hello)

    assert mutated is hello
    assert mutated.HasField("control")
    assert mutated.control.HasField("extensions")

    ext = mutated.control.extensions
    assert ext.topicObservation is True
    assert ext.testExtension is True
    assert state.sent_extensions_to(peer_id) is True


def test_build_hello_extensions_marks_sent_even_without_features() -> None:
    """Even with no local extensions, sent_extensions should be tracked."""
    peer_id = IDFactory()
    hello = rpc_pb2.RPC()

    state = ExtensionsState(my_extensions=PeerExtensions())

    mutated = state.build_hello_extensions(peer_id, hello)

    assert mutated is hello
    # No control.extensions should be present when we advertise nothing.
    assert not mutated.HasField("control")
    assert state.sent_extensions_to(peer_id) is True


def test_handle_rpc_records_peer_extensions_on_first_message() -> None:
    """First RPC with extensions should record peer's advertised extensions."""
    peer_id = IDFactory()
    state = ExtensionsState(my_extensions=PeerExtensions())

    rpc = _make_rpc_with_extensions(topic_observation=True, test_extension=False)

    state.handle_rpc(rpc, peer_id)

    peer_ext = state.get_peer_extensions(peer_id)
    assert isinstance(peer_ext, PeerExtensions)
    assert peer_ext.topic_observation is True
    assert peer_ext.test_extension is False
    assert state.peer_supports_topic_observation(peer_id) is True
    assert state.peer_supports_test_extension(peer_id) is False


def test_handle_rpc_duplicate_extensions_calls_misbehaviour_callback() -> None:
    """Second RPC carrying extensions should trigger misbehaviour callback."""
    peer_id = IDFactory()
    state = ExtensionsState(my_extensions=PeerExtensions())

    calls: list[ID] = []

    def report_misbehaviour(p: ID) -> None:
        calls.append(p)

    state.set_report_misbehaviour(report_misbehaviour)

    rpc = _make_rpc_with_extensions(topic_observation=True)

    # First RPC: records extensions.
    state.handle_rpc(rpc, peer_id)
    assert calls == []

    # Second RPC: duplicate extensions -> misbehaviour.
    state.handle_rpc(rpc, peer_id)
    assert calls == [peer_id]


def test_extensions_state_remove_peer_clears_state() -> None:
    """remove_peer should clear both sent and received extension state."""
    peer_id = IDFactory()
    state = ExtensionsState(my_extensions=PeerExtensions(topic_observation=True))
    rpc = _make_rpc_with_extensions(topic_observation=True)

    state.build_hello_extensions(peer_id, rpc_pb2.RPC())
    state.handle_rpc(rpc, peer_id)

    assert state.sent_extensions_to(peer_id)
    assert state.get_peer_extensions(peer_id) is not None

    state.remove_peer(peer_id)

    assert not state.sent_extensions_to(peer_id)
    assert state.get_peer_extensions(peer_id) is None


def test_both_support_topic_observation_query() -> None:
    """both_support_topic_observation returns True only when both sides advertise it."""
    state = ExtensionsState(my_extensions=PeerExtensions(topic_observation=True))

    # Peer that did not advertise topicObservation (we only accept first
    # Extensions per peer).
    peer_no = IDFactory()
    rpc_no = _make_rpc_with_extensions(topic_observation=False)
    state.handle_rpc(rpc_no, peer_no)
    assert not state.both_support_topic_observation(peer_no)

    # Different peer that does advertise topicObservation.
    peer_yes = IDFactory()
    rpc_yes = _make_rpc_with_extensions(topic_observation=True)
    state.handle_rpc(rpc_yes, peer_yes)
    assert state.both_support_topic_observation(peer_yes)


def test_gossipsub_report_extensions_misbehaviour_penalizes_behavior() -> None:
    """GossipSub._report_extensions_misbehaviour must call scorer.penalize_behavior."""
    score_params = ScoreParams(
        p5_behavior_penalty_weight=2.0,
        p5_behavior_penalty_threshold=0.0,
        p5_behavior_penalty_decay=1.0,
    )
    router = GossipSub(
        protocols=[PROTOCOL_ID_V13],
        degree=GOSSIPSUB_PARAMS.degree,
        degree_low=GOSSIPSUB_PARAMS.degree_low,
        degree_high=GOSSIPSUB_PARAMS.degree_high,
        score_params=score_params,
    )
    assert isinstance(router, GossipSub)
    assert router.scorer is not None

    peer_id = IDFactory()
    assert peer_id not in router.scorer.behavior_penalty

    router._report_extensions_misbehaviour(peer_id)

    # _report_extensions_misbehaviour must call scorer.penalize_behavior(peer_id, 1.0)
    assert router.scorer.behavior_penalty[peer_id] == 1.0


# ---------------------------------------------------------------------------
# TopicObservationState tests
# ---------------------------------------------------------------------------


def test_topic_observation_state_observing_and_observers() -> None:
    """TopicObservationState should track observing topics and observers correctly."""
    state = TopicObservationState()
    topic = "test-topic"
    observer = IDFactory()
    subscriber = IDFactory()

    # Outbound observing.
    assert not state.is_observing(topic)
    state.add_observing(topic, subscriber)
    assert state.is_observing(topic)
    assert state.get_subscriber_peers_for_topic(topic) == {subscriber}

    state.remove_observing(topic, subscriber)
    assert not state.is_observing(topic)
    assert state.get_subscriber_peers_for_topic(topic) == set()

    # Inbound observers.
    assert state.get_observers(topic) == set()
    state.add_observer(topic, observer)
    assert state.get_observers(topic) == {observer}

    state.remove_observer(topic, observer)
    assert state.get_observers(topic) == set()


def test_topic_observation_state_remove_peer_clears_all_state() -> None:
    """remove_peer should drop a peer from both observing and observer maps."""
    state = TopicObservationState()
    topic1 = "topic-1"
    topic2 = "topic-2"
    peer = IDFactory()

    state.add_observing(topic1, peer)
    state.add_observer(topic2, peer)

    state.remove_peer(peer)

    assert state.get_observing_topics() == set()
    assert state.get_observers(topic1) == set()
    assert state.get_observers(topic2) == set()


# ---------------------------------------------------------------------------
# GossipSub v1.3 wiring tests (topic observation + notify observers)
# ---------------------------------------------------------------------------


def test_supports_v13_features_based_on_protocol() -> None:
    """supports_v13_features should be true only for v1.3+ peers."""
    router = GossipsubFactory()
    assert isinstance(router, GossipSub)

    v13_peer = IDFactory()
    v12_peer = IDFactory()

    router.add_peer(v13_peer, PROTOCOL_ID_V13)
    # Reuse PROTOCOL_ID_V13 constant to ensure we don't regress the set of
    # supported protocols in _get_in_topic_gossipsub_peers_from_minus.
    from libp2p.pubsub.gossipsub import PROTOCOL_ID_V12

    router.add_peer(v12_peer, PROTOCOL_ID_V12)

    assert router.supports_v13_features(v13_peer) is True
    assert router.supports_v13_features(v12_peer) is False


@pytest.mark.trio
async def test_handle_observe_and_unobserve_manage_observers() -> None:
    """handle_observe / handle_unobserve should add and remove observers."""
    router = GossipsubFactory()
    assert isinstance(router, GossipSub)

    topic = "obs-topic"
    observer_peer = IDFactory()

    # Simulate that the peer advertised topicObservation support via extensions.
    router.extensions_state._peer_extensions[observer_peer] = PeerExtensions(
        topic_observation=True
    )

    observe_msg = rpc_pb2.ControlObserve(topicID=topic)
    await router.handle_observe(observe_msg, observer_peer)

    assert observer_peer in router.topic_observation.get_observers(topic)

    unobserve_msg = rpc_pb2.ControlUnobserve(topicID=topic)
    await router.handle_unobserve(unobserve_msg, observer_peer)

    assert observer_peer not in router.topic_observation.get_observers(topic)


@pytest.mark.trio
async def test_handle_observe_ignored_when_peer_did_not_advertise_extension() -> None:
    """Peers that did not advertise topicObservation must not become observers."""
    router = GossipsubFactory()
    assert isinstance(router, GossipSub)

    topic = "obs-topic"
    observer_peer = IDFactory()

    # Peer exists, but its advertised extensions do NOT include topicObservation.
    router.extensions_state._peer_extensions[observer_peer] = PeerExtensions(
        topic_observation=False
    )

    observe_msg = rpc_pb2.ControlObserve(topicID=topic)
    await router.handle_observe(observe_msg, observer_peer)

    assert router.topic_observation.get_observers(topic) == set()


@pytest.mark.trio
async def test_emit_observe_and_unobserve_update_observing_state() -> None:
    """emit_observe / emit_unobserve should update TopicObservationState (outbound)."""
    router = GossipsubFactory()
    assert isinstance(router, GossipSub)

    topic = "obs-topic"
    subscriber_peer = IDFactory()

    # Stub pubsub.peers so emit_control_message sees the peer as connected.
    class DummyPubsub:
        def __init__(self) -> None:
            self.peers: dict[ID, object] = {subscriber_peer: object()}

    router.pubsub = DummyPubsub()  # type: ignore[assignment]

    # Avoid writing to a real stream; we only care about state updates.
    router.emit_control_message = AsyncMock()  # type: ignore[assignment]

    assert not router.topic_observation.is_observing(topic)

    await router.emit_observe(topic, subscriber_peer)
    assert router.topic_observation.is_observing(topic)
    assert router.topic_observation.get_subscriber_peers_for_topic(topic) == {
        subscriber_peer
    }

    await router.emit_unobserve(topic, subscriber_peer)
    assert not router.topic_observation.is_observing(topic)
    assert router.topic_observation.get_subscriber_peers_for_topic(topic) == set()


@pytest.mark.trio
async def test_notify_observers_sends_ihave_to_each_observer() -> None:
    """_notify_observers should call emit_ihave for each observer with the msg_id."""
    router = GossipsubFactory()
    assert isinstance(router, GossipSub)

    topic = "obs-topic"
    observer_peer = IDFactory()
    msg_id = b"message-id"

    # Configure TopicObservationState with a single observer.
    router.topic_observation.add_observer(topic, observer_peer)

    # Stub pubsub with peers map so observers are considered connected.
    class DummyPubsub:
        def __init__(self) -> None:
            self.peers: dict[ID, object] = {observer_peer: object()}

    router.pubsub = DummyPubsub()  # type: ignore[assignment]

    # Capture IHAVE emissions.
    router.emit_ihave = AsyncMock()  # type: ignore[assignment]

    await router._notify_observers([topic], msg_id)

    # emit_ihave(topic, [str(msg_id)], observer_peer) is expected.
    router.emit_ihave.assert_awaited_once()
    called_topic, called_msg_ids, called_peer = router.emit_ihave.call_args.args
    assert called_topic == topic
    assert called_peer == observer_peer
    assert called_msg_ids == [str(msg_id)]


@pytest.mark.trio
async def test_start_and_stop_observing_topic_high_level_api() -> None:
    """start_observing_topic / stop_observing_topic delegate to OBSERVE/UNOBSERVE."""
    router = GossipsubFactory()
    assert isinstance(router, GossipSub)

    topic = "obs-topic"
    subscriber_peer = IDFactory()

    # Simulate pubsub state: subscriber_peer is subscribed to topic.
    class DummyPubsub:
        def __init__(self) -> None:
            self.peer_topics = {topic: {subscriber_peer}}

    router.pubsub = DummyPubsub()  # type: ignore[assignment]

    # Ensure the peer negotiated v1.3 and both sides support topicObservation.
    router.peer_protocol[subscriber_peer] = PROTOCOL_ID_V13
    router.extensions_state.my_extensions.topic_observation = True
    router.extensions_state._peer_extensions[subscriber_peer] = PeerExtensions(
        topic_observation=True
    )

    # Avoid touching real network; just record control messages.
    router.emit_control_message = AsyncMock()  # type: ignore[assignment]

    assert not router.topic_observation.is_observing(topic)

    await router.start_observing_topic(topic)
    # After OBSERVE, we should be tracking the topic as "observing".
    assert router.topic_observation.is_observing(topic)
    assert router.topic_observation.get_subscriber_peers_for_topic(topic) == {
        subscriber_peer
    }

    await router.stop_observing_topic(topic)
    assert not router.topic_observation.is_observing(topic)
    assert router.topic_observation.get_subscriber_peers_for_topic(topic) == set()
