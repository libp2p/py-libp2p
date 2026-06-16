from py_ipfs_lite.config import AddParams, Config


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.offline is False
    assert cfg.reprovide_interval_seconds == 43200
    assert cfg.uncached_blockstore is False
    assert cfg.bitswap_broadcast_max_random_peers == 64
    assert cfg.bitswap_broadcast_control_send_to_pending_peers is False


def test_add_params_defaults() -> None:
    params = AddParams()
    assert params.layout == "balanced"
    assert params.chunker == "size-262144"
    assert params.raw_leaves is True
    assert params.max_links == 174

