import multiaddr
from libp2p import new_host, generate_new_ed25519_identity

host = new_host(
    key_pair=generate_new_ed25519_identity(),
    listen_addrs=[multiaddr.Multiaddr("/ip4/0.0.0.0/udp/4001/quic-v1")],
    enable_quic=True,
    enable_autotls=True,
)
t = host.get_network().transport
print("transport =", type(t).__name__)
print("quic_enable_autotls =", getattr(t, "_enable_autotls", None))
