import random

import pytest
import multiaddr

from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    InvalidAddrError,
    PeerInfo,
    info_from_p2p_addr,
)

ALPHABETS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
VALID_MULTI_ADDR_STR = "/ip4/127.0.0.1/tcp/8000/p2p/3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ"  # noqa: E501


def test_init_():
    random_addrs = [
        multiaddr.Multiaddr(f"/ip4/127.0.0.1/tcp/{1000 + i}") for i in range(4)
    ]

    random_id_string = ""
    for _ in range(10):
        random_id_string += random.SystemRandom().choice(ALPHABETS)

    peer_id = ID(random_id_string.encode())
    peer_info = PeerInfo(peer_id, random_addrs)

    assert peer_info.peer_id == peer_id
    assert peer_info.addrs == random_addrs


@pytest.mark.parametrize(
    "addr",
    (
        pytest.param(multiaddr.Multiaddr("/"), id="empty multiaddr"),
        pytest.param(
            multiaddr.Multiaddr("/ip4/127.0.0.1"),
            id="multiaddr without peer_id(p2p protocol)",
        ),
    ),
)
def test_info_from_p2p_addr_invalid(addr):
    with pytest.raises(InvalidAddrError):
        info_from_p2p_addr(addr)


def test_info_from_p2p_addr_valid():
    m_addr = multiaddr.Multiaddr(VALID_MULTI_ADDR_STR)
    info = info_from_p2p_addr(m_addr)
    assert (
        info.peer_id.pretty()
        == "3YgLAeMKSAPcGqZkAt8mREqhQXmJT8SN8VCMN4T6ih4GNX9wvK8mWJnWZ1qA2mLdCQ"
    )
    assert len(info.addrs) == 1
    assert str(info.addrs[0]) == "/ip4/127.0.0.1/tcp/8000"
