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
    blockstore_type: BlockStoreType | str = "filesystem"
    blockstore_path: str | None = ".py_ipfs_lite/blocks"
    use_ipni: bool = False
    ipni_endpoint: str = "https://cid.contact"
    default_timeout: float = 30.0
    max_upload_size: int = 104857600  # 100MB
    max_download_size: int = 104857600  # 100MB

    def __post_init__(self) -> None:
        if self.reprovide_interval_seconds == 0:
            raise ValueError(
                "reprovide_interval_seconds cannot be 0. Use < 0 to disable."
            )
        if self.reprovider_strategy not in ("all", "pinned", "roots"):
            raise ValueError(
                f"Unknown reprovider_strategy: '{self.reprovider_strategy}'"
            )
        if self.conn_mgr_low_water < 0 or self.conn_mgr_high_water < 0:
            raise ValueError("Connection watermarks cannot be negative.")
        if self.conn_mgr_low_water > self.conn_mgr_high_water:
            raise ValueError(
                "conn_mgr_low_water cannot be greater than " "conn_mgr_high_water."
            )

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

    def __post_init__(self) -> None:
        if not self.chunker.startswith("size-"):
            raise ValueError(
                f"Invalid chunker '{self.chunker}'. Must start with 'size-'."
            )
        chunk_size_str = self.chunker[5:]
        if not chunk_size_str.isdigit() or int(chunk_size_str) <= 0:
            raise ValueError(
                f"Invalid chunker '{self.chunker}'. Size must be a positive integer."
            )


@dataclass(slots=True)
class CLIConfig:
    port: int = 4001
    api_port: int = 5001
    seed: str | None = None
    debug: bool = False
