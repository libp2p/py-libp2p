import os

SERVICE_PROTOCOL_ID = "/service-discovery/1.0.0"
DHT_NAMESPACE = b"service-discovery:"
RECORD_VERSION = 1
RECORD_MAX_AGE_SECONDS = 300
RECORD_REFRESH_INTERVAL = 120
DHT_GET_TIMEOUT = 10
MAX_RESOLVED_PEERS = 5
DEFAULT_LISTEN_ADDRS = ["/ip4/0.0.0.0/tcp/0"]

def get_eth_config():
    rpc_url = os.getenv("RPC_URL")
    private_key = os.getenv("PRIVATE_KEY")
    default_service_id = os.getenv("SERVICE_ID_STR")
    if not private_key:
        raise ValueError("PRIVATE_KEY env var required")
    return {
        "rpc_url": rpc_url,
        "private_key": private_key,
        "default_service_id": default_service_id
    }
