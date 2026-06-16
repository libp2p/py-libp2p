from __future__ import annotations

from typing import Any


class DummyHost:
    def __init__(self, key: Any, addrs: list[Any]) -> None:
        self.key = key
        self.addrs = addrs

    def get_id(self) -> str:
        return "dummy_id"


class DummyRouting:
    def __init__(self, datastore: Any | None) -> None:
        self.datastore = datastore

    async def bootstrap(self) -> None:
        pass


def default_bootstrap_peers() -> list[Any]:
    return [
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
        "/dnsaddr/bootstrap.libp2p.io/p2p/QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
    ]


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
    host = DummyHost(key=host_key, addrs=listen_addrs)
    routing = DummyRouting(datastore=datastore)
    return host, routing

