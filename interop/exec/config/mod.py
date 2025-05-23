from dataclasses import (
    dataclass,
)
import os
from typing import (
    Optional,
)


def str_to_bool(val: str) -> bool:
    return val.lower() in ("true", "1")


class ConfigError(Exception):
    """Raised when the required environment variables are missing or invalid"""


@dataclass
class Config:
    transport: str
    sec_protocol: Optional[str]
    muxer: Optional[str]
    ip: str
    is_dialer: bool
    test_timeout: int
    redis_addr: str
    port: str

    @classmethod
    def from_env(cls) -> "Config":
        try:
            transport = os.environ["transport"]
            ip = os.environ["ip"]
        except KeyError as e:
            raise ConfigError(f"{e.args[0]} env variable not set") from None

        try:
            is_dialer = str_to_bool(os.environ.get("is_dialer", "true"))
            test_timeout = int(os.environ.get("test_timeout", "180"))
        except ValueError as e:
            raise ConfigError(f"Invalid value in env: {e}") from None

        redis_addr = os.environ.get("redis_addr", 6379)
        sec_protocol = os.environ.get("security")
        muxer = os.environ.get("muxer")
        port = os.environ.get("port", "8000")

        return cls(
            transport=transport,
            sec_protocol=sec_protocol,
            muxer=muxer,
            ip=ip,
            is_dialer=is_dialer,
            test_timeout=test_timeout,
            redis_addr=redis_addr,
            port=port,
        )
