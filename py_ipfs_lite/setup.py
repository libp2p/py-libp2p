from __future__ import annotations

from typing import Any


def default_bootstrap_peers() -> list[Any]:
    return []


def new_in_memory_datastore() -> dict[str, bytes]:
    return {}


async def setup_libp2p(
    *,
    host_key: Any,
    secret: bytes | None,
    listen_addrs: list[Any],
    datastore: Any | None,
    extra_options: list[Any] | None = None,
) -> tuple[Any, Any]:
    raise NotImplementedError("Planned for Phase 3 networking setup")

