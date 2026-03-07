import hashlib
from types import SimpleNamespace

import pytest

from libp2p.filecoin.constants import (
    ACCEPT_PX_SCORE_THRESHOLD,
    GOSSIP_SCORE_THRESHOLD,
    GRAYLIST_SCORE_THRESHOLD,
    PUBLISH_SCORE_THRESHOLD,
    filecoin_message_id,
)
from libp2p.filecoin.pubsub import (
    FILECOIN_GOSSIPSUB_PROTOCOLS,
    build_filecoin_gossipsub,
    build_filecoin_score_params,
)


def test_build_filecoin_score_params_threshold_values() -> None:
    score_params = build_filecoin_score_params(mode="thresholds_only")
    assert score_params.gossip_threshold == GOSSIP_SCORE_THRESHOLD
    assert score_params.publish_threshold == PUBLISH_SCORE_THRESHOLD
    assert score_params.graylist_threshold == GRAYLIST_SCORE_THRESHOLD
    assert score_params.accept_px_threshold == ACCEPT_PX_SCORE_THRESHOLD


def test_build_filecoin_score_params_rejects_unsupported_mode() -> None:
    with pytest.raises(ValueError):
        build_filecoin_score_params(mode="full")


def test_build_filecoin_gossipsub_default_params() -> None:
    gossipsub = build_filecoin_gossipsub(network_name="testnetnet")
    assert gossipsub.protocols == list(FILECOIN_GOSSIPSUB_PROTOCOLS)
    assert gossipsub.degree == 8
    assert gossipsub.degree_low == 6
    assert gossipsub.degree_high == 12
    assert gossipsub.direct_connect_initial_delay == 30.0
    assert gossipsub.mcache.history_size == 10
    assert gossipsub.do_px is False


def test_build_filecoin_gossipsub_bootstrapper_params() -> None:
    gossipsub = build_filecoin_gossipsub(
        network_name="testnetnet",
        bootstrapper=True,
    )
    assert gossipsub.degree == 0
    assert gossipsub.degree_low == 0
    assert gossipsub.degree_high == 0
    assert gossipsub.do_px is True
    assert gossipsub.prune_back_off == 300


def test_filecoin_message_id_is_deterministic_blake2b() -> None:
    msg = SimpleNamespace(data=b"lotus-parity")
    expected = hashlib.blake2b(b"lotus-parity", digest_size=32).digest()
    assert filecoin_message_id(msg) == expected
