import pytest

from py_ipfs_lite import default_bootstrap_peers, setup_libp2p


@pytest.mark.trio
async def test_setup_libp2p():
    host, routing = await setup_libp2p(
        host_key="dummy_key",
        secret=None,
        listen_addrs=["/ip4/0.0.0.0/tcp/0"],
        datastore=None
    )
    assert host is not None
    assert routing is not None

def test_default_bootstrap_peers():
    peers = default_bootstrap_peers()
    assert isinstance(peers, list)
    assert len(peers) > 0

