"""
Micro-benchmarks for MessageCache (issue #1333).

Run with:
    pytest tests/core/pubsub/bench_mcache.py --benchmark-only -v

These benchmarks document the before/after throughput improvement from
replacing the O(history_size) list rotation and O(W×E×T) topic scan with
a deque-based O(1) rotation and an O(1) topic index.
"""

import pytest

from libp2p.pubsub.mcache import MessageCache
from libp2p.pubsub.pb import rpc_pb2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

HISTORY_SIZE = 120   # high-throughput node (2-min window at 1 hbeat/s)
WINDOW_SIZE = 6
N_TOPICS = 10
MSGS_PER_SLOT = 50


def _build_loaded_cache(
    history_size: int = HISTORY_SIZE,
    window_size: int = WINDOW_SIZE,
    n_topics: int = N_TOPICS,
    msgs_per_slot: int = MSGS_PER_SLOT,
) -> MessageCache:
    """Return a MessageCache pre-loaded with msgs_per_slot messages per slot."""
    mc = MessageCache(window_size, history_size)
    topics = [f"topic-{i}" for i in range(n_topics)]
    seq = 0
    for slot in range(window_size):
        for _ in range(msgs_per_slot):
            msg = rpc_pb2.Message(
                from_id=b"bench-peer",
                seqno=seq.to_bytes(4, "big"),
                topicIDs=topics,
            )
            mc.put(msg)
            seq += 1
        if slot < window_size - 1:
            mc.shift()
    return mc


# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------


@pytest.mark.benchmark(group="mcache")
def test_bench_shift(benchmark: pytest.FixtureRequest) -> None:
    """
    Benchmark shift() — expected O(evicted_msgs), was O(history_size).

    At history_size=120 the old code performed 119 slot-reference copies;
    the new code does one deque.appendleft().
    """
    mc = _build_loaded_cache()

    def _run() -> None:
        # Re-add one message so eviction always has something to do,
        # then shift to keep the cache size stable.
        mc.put(
            rpc_pb2.Message(
                from_id=b"bench-peer",
                seqno=b"\xff\xff\xff\xff",
                topicIDs=["topic-0"],
            )
        )
        mc.shift()

    benchmark(_run)


@pytest.mark.benchmark(group="mcache")
def test_bench_window_single_topic(benchmark: pytest.FixtureRequest) -> None:
    """
    Benchmark window(topic) for one topic — expected O(W + results).

    Old code: W × msgs_per_slot × n_topics iterations.
    New code: W dict.get() calls.
    """
    mc = _build_loaded_cache()

    benchmark(mc.window, "topic-0")


@pytest.mark.benchmark(group="mcache")
def test_bench_window_all_topics(benchmark: pytest.FixtureRequest) -> None:
    """
    Benchmark a full GossipSub heartbeat: call window() for every topic.

    This reflects the real call pattern — gossipsub calls window(topic)
    once per subscribed topic per heartbeat to build IHAVE messages.
    """
    mc = _build_loaded_cache()
    topics = [f"topic-{i}" for i in range(N_TOPICS)]

    def _run() -> None:
        for topic in topics:
            mc.window(topic)

    benchmark(_run)


@pytest.mark.benchmark(group="mcache")
def test_bench_put(benchmark: pytest.FixtureRequest) -> None:
    """Benchmark put() — should remain O(T) (topics per message)."""
    mc = MessageCache(WINDOW_SIZE, HISTORY_SIZE)
    topics = [f"topic-{i}" for i in range(N_TOPICS)]
    counter = [0]

    def _run() -> None:
        seq = counter[0].to_bytes(4, "big")
        counter[0] += 1
        mc.put(
            rpc_pb2.Message(from_id=b"bench-peer", seqno=seq, topicIDs=topics)
        )

    benchmark(_run)


@pytest.mark.benchmark(group="mcache")
def test_bench_full_heartbeat(benchmark: pytest.FixtureRequest) -> None:
    """
    Benchmark a complete heartbeat: shift() + window() × N_TOPICS.

    This is the worst-case per-second cost on a high-throughput GossipSub
    node and directly represents the improvement from this optimization.
    """
    mc = _build_loaded_cache()
    topics = [f"topic-{i}" for i in range(N_TOPICS)]
    counter = [0]

    def _run() -> None:
        seq = counter[0].to_bytes(4, "big")
        counter[0] += 1
        mc.put(
            rpc_pb2.Message(from_id=b"bench-peer", seqno=seq, topicIDs=topics)
        )
        mc.shift()
        for topic in topics:
            mc.window(topic)

    benchmark(_run)
