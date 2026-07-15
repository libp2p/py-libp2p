from dataclasses import dataclass
from enum import Enum


class BlockStoreType(str, Enum):
    FILESYSTEM = "filesystem"
    MEMORY = "memory"


@dataclass(slots=True)
class Config:
    offline: bool = False
    reprovide_interval_seconds: int = 43200
    reprovider_strategy: str = "all"
    conn_mgr_high_water: int = 900
    conn_mgr_low_water: int = 600
    blockstore_type: BlockStoreType | str = BlockStoreType.FILESYSTEM
    blockstore_path: str | None = ".py_ipfs_lite/blocks"
    use_ipni: bool = False
    ipni_endpoint: str = "https://cid.contact"
    default_timeout: float = 30.0

    def __post_init__(self) -> None:
        try:
            self.blockstore_type = BlockStoreType(self.blockstore_type)
        except ValueError:
            valid = [e.value for e in BlockStoreType]
            raise ValueError(
                f"Unsupported blockstore_type: '{self.blockstore_type}'. "
                f"Must be one of {valid}"
            )


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
