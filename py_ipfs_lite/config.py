from dataclasses import dataclass


@dataclass(slots=True)
class Config:
    offline: bool = False
    reprovide_interval_seconds: int = 43200
    reprovider_strategy: str = "all"
    conn_mgr_high_water: int = 900
    conn_mgr_low_water: int = 600
    blockstore_type: str = "filesystem"
    blockstore_path: str | None = ".py_ipfs_lite/blocks"
    use_ipni: bool = True
    ipni_endpoint: str = "https://cid.contact"
    default_timeout: float = 30.0


@dataclass(slots=True)
class AddParams:
    chunker: str = "size-262144"
    raw_leaves: bool = True
    hash_fun: str = "sha2-256"

@dataclass(slots=True)
class CLIConfig:
    port: int = 0
    seed: str | None = None
    debug: bool = False
