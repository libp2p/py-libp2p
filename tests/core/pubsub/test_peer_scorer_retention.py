"""Regression coverage for PeerScorer topic-state retention."""

from libp2p.pubsub.score import PeerScorer, ScoreParams, TopicScoreParams
from tests.utils.factories import IDFactory


def _topic_entry_count(scorer: PeerScorer) -> int:
    return sum(
        len(peer_topics)
        for name in (
            "time_in_mesh",
            "first_message_deliveries",
            "mesh_message_deliveries",
            "invalid_messages",
        )
        for peer_topics in getattr(scorer, name).values()
    )


def test_scoring_arbitrary_topics_does_not_retain_state():
    """
    Read-only scoring must not materialize defaultdict entries.

    A peer can attach arbitrary extra topic IDs to a publish message that also
    contains a topic we subscribe to.  Scoring those IDs used to create four
    entries per topic and keep them until the peer disconnected.
    """
    peer = IDFactory()
    scorer = PeerScorer(ScoreParams())
    topics = [f"attacker-topic-{i}" for i in range(500)]

    scorer.allow_publish(peer, topics)
    assert _topic_entry_count(scorer) == 0

    scorer.score(peer, topics)
    assert _topic_entry_count(scorer) == 0

    stats = scorer.get_score_stats(peer, "never-seen-topic")
    assert stats["time_in_mesh"] == 0.0
    assert stats["total_score"] == 0.0
    assert _topic_entry_count(scorer) == 0


def test_decayed_topic_state_is_pruned_on_heartbeat():
    """Long-lived peers must not keep every topic they ever joined."""
    params = ScoreParams(
        p1_time_in_mesh=TopicScoreParams(weight=1.0, cap=10.0, decay=0.5)
    )
    scorer = PeerScorer(params)
    peer = IDFactory()

    for i in range(100):
        scorer.on_join_mesh(peer, f"historical-topic-{i}")
    assert _topic_entry_count(scorer) == 100

    for _ in range(100):
        scorer.on_heartbeat()

    assert _topic_entry_count(scorer) == 0
    assert peer not in scorer.time_in_mesh


def test_explicit_topic_events_still_record_state():
    """The non-mutating reads must not disable legitimate score tracking."""
    peer = IDFactory()
    scorer = PeerScorer(ScoreParams())

    scorer.on_join_mesh(peer, "real-topic")
    scorer.on_first_delivery(peer, "real-topic")
    scorer.on_mesh_delivery(peer, "real-topic")
    scorer.on_invalid_message(peer, "real-topic")

    assert scorer.time_in_mesh[peer]["real-topic"] == 1.0
    assert scorer.first_message_deliveries[peer]["real-topic"] == 1.0
    assert scorer.mesh_message_deliveries[peer]["real-topic"] == 1.0
    assert scorer.invalid_messages[peer]["real-topic"] == 1.0

    scorer.remove_peer(peer)
    assert _topic_entry_count(scorer) == 0
