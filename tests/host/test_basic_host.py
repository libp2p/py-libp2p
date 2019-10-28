from libp2p import initialize_default_swarm
from libp2p.crypto.rsa import create_new_key_pair
from libp2p.host.basic_host import BasicHost
from libp2p.host.defaults import get_default_protocols


def test_default_protocols():
    key_pair = create_new_key_pair()
    swarm = initialize_default_swarm(key_pair)
    host = BasicHost(key_pair.public_key, swarm)

    mux = host.get_mux()
    handlers = mux.handlers
    assert handlers == get_default_protocols(host)
