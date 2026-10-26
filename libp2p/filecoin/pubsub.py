from __future__ import annotations

from collections.abc import Sequence

from libp2p.abc import IHost
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import PeerInfo
from libp2p.pubsub.gossipsub import (
    PROTOCOL_ID,
    PROTOCOL_ID_V11,
    PROTOCOL_ID_V12,
    PROTOCOL_ID_V20,
    GossipSub,
)
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.score import ScoreParams

from .constants import (
    ACCEPT_PX_SCORE_THRESHOLD,
    GOSSIP_SCORE_THRESHOLD,
    GRAYLIST_SCORE_THRESHOLD,
    OPPORTUNISTIC_GRAFT_SCORE_THRESHOLD,
    PUBLISH_SCORE_THRESHOLD,
    filecoin_message_id,
)

FILECOIN_GOSSIPSUB_PROTOCOLS: tuple[TProtocol, ...] = (
    PROTOCOL_ID_V20,
    PROTOCOL_ID_V12,
    PROTOCOL_ID_V11,
    PROTOCOL_ID,
)

FILECOIN_TOPIC_SCORE_REFERENCE: dict[str, dict[str, float]] = {
    "blocks": {
        "topic_weight": 0.1,
        "time_in_mesh_weight": 0.00027,
        "first_message_deliveries_weight": 5.0,
        "invalid_message_deliveries_weight": -1000.0,
    },
    "messages": {
        "topic_weight": 0.1,
        "time_in_mesh_weight": 0.0002778,
        "first_message_deliveries_weight": 0.5,
        "invalid_message_deliveries_weight": -1000.0,
    },
    "drand": {
        "topic_weight": 0.5,
        "time_in_mesh_weight": 0.00027,
        "first_message_deliveries_weight": 5.0,
        "invalid_message_deliveries_weight": -1000.0,
    },
}

FILECOIN_PEER_SCORE_REFERENCE: dict[str, float] = {
    "gossip_threshold": GOSSIP_SCORE_THRESHOLD,
    "publish_threshold": PUBLISH_SCORE_THRESHOLD,
    "graylist_threshold": GRAYLIST_SCORE_THRESHOLD,
    "accept_px_threshold": ACCEPT_PX_SCORE_THRESHOLD,
    "opportunistic_graft_threshold": OPPORTUNISTIC_GRAFT_SCORE_THRESHOLD,
}


def build_filecoin_score_params(mode: str = "thresholds_only") -> ScoreParams:
    if mode != "thresholds_only":
        raise ValueError(f"unsupported score mode '{mode}'. expected 'thresholds_only'")

    return ScoreParams(
        publish_threshold=PUBLISH_SCORE_THRESHOLD,
        gossip_threshold=GOSSIP_SCORE_THRESHOLD,
        graylist_threshold=GRAYLIST_SCORE_THRESHOLD,
        accept_px_threshold=ACCEPT_PX_SCORE_THRESHOLD,
    )


def build_filecoin_gossipsub(
    network_name: str,
    bootstrapper: bool = False,
    direct_peers: Sequence[PeerInfo] | None = None,
    score_mode: str = "thresholds_only",
    protocols: Sequence[TProtocol] | None = None,
) -> GossipSub:
    if not network_name:
        raise ValueError("network_name must not be empty")

    score_params = build_filecoin_score_params(mode=score_mode)
    selected_protocols = list(protocols or FILECOIN_GOSSIPSUB_PROTOCOLS)

    degree = 0 if bootstrapper else 8
    degree_low = 0 if bootstrapper else 6
    degree_high = 0 if bootstrapper else 12
    do_px = bootstrapper
    prune_back_off = 300 if bootstrapper else 60

    return GossipSub(
        protocols=selected_protocols,
        degree=degree,
        degree_low=degree_low,
        degree_high=degree_high,
        direct_peers=direct_peers,
        time_to_live=60,
        gossip_window=3,
        gossip_history=10,
        heartbeat_initial_delay=0.1,
        heartbeat_interval=1,
        direct_connect_initial_delay=30.0,
        direct_connect_interval=300,
        do_px=do_px,
        px_peers_count=16,
        prune_back_off=prune_back_off,
        unsubscribe_back_off=10,
        score_params=score_params,
    )


def build_filecoin_pubsub(
    host: IHost,
    network_name: str,
    bootstrapper: bool = False,
    gossipsub: GossipSub | None = None,
    score_mode: str = "thresholds_only",
    strict_signing: bool = True,
    direct_peers: Sequence[PeerInfo] | None = None,
) -> Pubsub:
    router = gossipsub or build_filecoin_gossipsub(
        network_name=network_name,
        bootstrapper=bootstrapper,
        direct_peers=direct_peers,
        score_mode=score_mode,
    )
    return Pubsub(
        host=host,
        router=router,
        strict_signing=strict_signing,
        msg_id_constructor=filecoin_message_id,
    )
