import py_ipfs_lite


def test_public_exports_present() -> None:
    assert hasattr(py_ipfs_lite, "AddParams")
    assert hasattr(py_ipfs_lite, "Config")
    assert hasattr(py_ipfs_lite, "AddParams")
    assert hasattr(py_ipfs_lite, "setup_libp2p")
    assert hasattr(py_ipfs_lite, "default_bootstrap_peers")
    assert hasattr(py_ipfs_lite, "new_in_memory_datastore")


def test_version_string() -> None:
    assert py_ipfs_lite.__version__ == "0.1.0"

