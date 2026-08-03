"""
Test to confirm bug: _get_from_peer and _store_at_peer have unbounded varint
read loops without a max byte limit, making them vulnerable to DoS.

The handle_stream method in kad_dht.py has a max_varint_bytes=10 check,
but the response reading methods in value_store.py don't.
"""

import inspect

from libp2p.kad_dht.peer_routing import PeerRouting
from libp2p.kad_dht.value_store import ValueStore


def test_max_varint_check_in_response_reading():
    """
    Verify that _get_from_peer and _query_peer_for_closest have max varint
    byte limits to prevent DoS from malicious peers that send endless
    continuation bytes in the varint length prefix.
    """
    # Check _get_from_peer source for max varint check
    vs_source = inspect.getsource(ValueStore._get_from_peer)
    has_max_varint = "max_varint" in vs_source or "max_varint_bytes" in vs_source

    # Check _query_peer_for_closest source for max varint check
    pr_source = inspect.getsource(PeerRouting._query_peer_for_closest)
    has_max_varint_pr = "max_varint" in pr_source or "max_varint_bytes" in pr_source

    issues = []
    if not has_max_varint:
        issues.append("_get_from_peer (value_store.py) has no max varint byte check")
    if not has_max_varint_pr:
        issues.append(
            "_query_peer_for_closest (peer_routing.py) has no max varint byte check"
        )

    if issues:
        raise AssertionError(
            "BUG: Missing max varint byte check in response reading:\n"
            + "\n".join(issues)
            + "\n\nA malicious peer could send endless continuation bytes "
            "in the varint length prefix, causing the read loop to consume "
            "memory/CPU indefinitely."
        )
    else:
        print("PASS: All response reading methods have max varint byte checks")


if __name__ == "__main__":
    test_max_varint_check_in_response_reading()
