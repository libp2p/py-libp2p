import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import Optional

load_dotenv()

RECORD_VERSION = 1
RECORD_MAX_AGE_SECONDS = 300
DHT_GET_TIMEOUT = 10
MAX_RESOLVED_PEERS = 5
DEFAULT_LISTEN_ADDRS = ["/ip4/127.0.0.1/tcp/0"]
DEPLOY_JSON = "./deploy_output.json"
KEYS_DIR = "./keys"

@dataclass
class Config:
    rpc_url: str
    private_key: str
    default_service_id: Optional[str]
    listen_addrs: list[str]

def get_eth_config() -> Config:
    rpc_url = os.getenv("RPC_URL")
    private_key = os.getenv("PRIVATE_KEY")
    default_service_id = os.getenv("SERVICE_ID_STR")
    listen_addrs_env = os.getenv("LISTEN_ADDRS")
    
    listen_addrs = DEFAULT_LISTEN_ADDRS
    if listen_addrs_env:
        listen_addrs = listen_addrs_env.split(",")
    if not private_key:
        raise ValueError("PRIVATE_KEY env var required")
        
    return Config(
        rpc_url=rpc_url if rpc_url else "",
        private_key=private_key,
        default_service_id=default_service_id,
        listen_addrs=listen_addrs
    )
