from py_ipfs_lite.config import AddParams, Config


def test_config_defaults() -> None:
    cfg = Config()
    assert cfg.offline is False
    assert cfg.reprovide_interval_seconds == 43200
    assert cfg.use_ipni is False


def test_add_params_defaults() -> None:
    params = AddParams()
    assert params.chunker == "size-262144"
    assert params.raw_leaves is True


def test_config_blockstore_type_validation() -> None:
    import pytest

    with pytest.raises(ValueError, match="Unsupported blockstore_type"):
        Config(blockstore_type="FILESYSTEM")

    with pytest.raises(ValueError, match="Unsupported blockstore_type"):
        Config(blockstore_type="invalid")

    cfg = Config(blockstore_type="filesystem")
    from py_ipfs_lite.config import BlockStoreType

    assert cfg.blockstore_type == BlockStoreType.FILESYSTEM
