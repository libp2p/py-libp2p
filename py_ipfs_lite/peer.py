from __future__ import annotations

from typing import Any

from .config import AddParams, Config


class Peer:
    def __init__(
        self,
        *,
        datastore: Any,
        blockstore: Any | None,
        host: Any | None,
        routing: Any | None,
        config: Config | None = None,
    ) -> None:
        self.datastore = datastore
        self.blockstore = blockstore
        self.host = host
        self.routing = routing
        self.config = config or Config()

    @classmethod
    async def new(
        cls,
        *,
        datastore: Any,
        blockstore: Any | None,
        host: Any | None,
        routing: Any | None,
        config: Config | None = None,
    ) -> Peer:
        return cls(
            datastore=datastore,
            blockstore=blockstore,
            host=host,
            routing=routing,
            config=config,
        )

    async def close(self) -> None:
        return None

    async def bootstrap(self, peers: list[Any]) -> None:
        raise NotImplementedError("Planned for Phase 3 networking setup")

    def session(self, ctx: Any | None = None) -> Any:
        raise NotImplementedError("Planned for Phase 4 DAG operations")

    async def add(self, node: Any) -> Any:
        raise NotImplementedError("Planned for Phase 4 DAG operations")

    async def get(self, cid: Any) -> Any:
        raise NotImplementedError("Planned for Phase 4 DAG operations")

    async def remove(self, cid: Any) -> None:
        raise NotImplementedError("Planned for Phase 4 DAG operations")

    async def add_file(self, source: Any, params: AddParams | None = None) -> Any:
        raise NotImplementedError("Planned for Phase 4 file operations")

    async def get_file(self, cid: Any) -> Any:
        raise NotImplementedError("Planned for Phase 4 file operations")

    def block_store(self) -> Any:
        return self.blockstore

    async def has_block(self, cid: Any) -> bool:
        raise NotImplementedError("Planned for Phase 4 blockstore access")

    def exchange(self) -> Any:
        raise NotImplementedError("Planned for Phase 4 exchange access")

    def block_service(self) -> Any:
        raise NotImplementedError("Planned for Phase 4 block service access")

