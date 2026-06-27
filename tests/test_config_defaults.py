from py_ipfs_lite.config import AddParams, Config


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.offline is False
    assert cfg.reprovide_interval_seconds == 43200


def test_add_params_defaults() -> None:
    params = AddParams()
    assert params.chunker == "size-262144"
    assert params.raw_leaves is True
