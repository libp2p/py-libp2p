import multiaddr


FLOODSUB_PROTOCOL_ID = "/floodsub/1.0.0"
SUPPORTED_PROTOCOLS = [FLOODSUB_PROTOCOL_ID]

LISTEN_MADDR = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
