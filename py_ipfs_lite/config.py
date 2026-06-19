from dataclasses import dataclass


@dataclass(slots=True)
class Config:
    offline: bool = False
    reprovide_interval_seconds: int = 43200
    reprovider_strategy: str = "all"
    conn_mgr_high_water: int = 900
    conn_mgr_low_water: int = 600
    uncached_blockstore: bool = False
    bitswap_broadcast_max_random_peers: int = 64
    bitswap_broadcast_control_send_to_pending_peers: bool = False
    blockstore_type: str = "filesystem"
    blockstore_path: str | None = ".py_ipfs_lite/blocks"
    use_ipni: bool = True
    ipni_endpoint: str = "https://cid.contact"


@dataclass(slots=True)
class AddParams:
    layout: str = "balanced"
    chunker: str = "size-262144"
    raw_leaves: bool = True
    hidden: bool = False
    shard: bool = False
    no_copy: bool = False
    hash_fun: str = "sha2-256"
    max_links: int = 174

@dataclass(slots=True)
class CLIConfig:
    port: int = 0
    seed: str | None = None
    debug: bool = False
