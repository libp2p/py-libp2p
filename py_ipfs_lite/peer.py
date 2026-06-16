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
        if self.routing and hasattr(self.routing, "bootstrap"):
            await self.routing.bootstrap()

    def session(self, ctx: Any | None = None) -> Any:
        return self

    async def add(self, node: Any) -> Any:
        if self.blockstore is not None:
            self.blockstore[f"mock_cid_{id(node)}"] = node
        return f"mock_cid_{id(node)}"

    async def get(self, cid: Any) -> Any:
        if self.blockstore is not None:
            return self.blockstore.get(cid)
        return None

    async def remove(self, cid: Any) -> None:
        if self.blockstore is not None and cid in self.blockstore:
            del self.blockstore[cid]

    async def add_file(self, source: Any, params: AddParams | None = None) -> Any:
        # Mock add_file: read all and save as a single block
        data = source.read() if hasattr(source, "read") else source
        if self.blockstore is not None:
            self.blockstore[f"mock_file_cid_{hash(data)}"] = data
        return f"mock_file_cid_{hash(data)}"

    async def get_file(self, cid: Any) -> Any:
        import io
        if self.blockstore is not None:
            data = self.blockstore.get(cid)
            if data is not None:
                if isinstance(data, bytes):
                    return io.BytesIO(data)
                return io.StringIO(str(data))
        return None

    def block_store(self) -> Any:
        return self.blockstore

    async def has_block(self, cid: Any) -> bool:
        return self.blockstore is not None and cid in self.blockstore

    def exchange(self) -> Any:
        return "mock_exchange"

    def block_service(self) -> Any:
        return "mock_block_service"

