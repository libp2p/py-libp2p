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
        from libp2p.bitswap import BitswapClient, MemoryBlockStore
        from libp2p.bitswap.dag import MerkleDag

        self.datastore = datastore
        self.blockstore = blockstore if blockstore is not None else MemoryBlockStore()
        self.host = host
        self.routing = routing
        self.config = config or Config()

        if host is not None:
            self._bitswap: Any = BitswapClient(host, self.blockstore)
        else:
            self._bitswap = None
            
        if self._bitswap is not None:
            self._dag: Any = MerkleDag(self._bitswap)
        else:
            self._dag = None

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
        peer = cls(
            datastore=datastore,
            blockstore=blockstore,
            host=host,
            routing=routing,
            config=config,
        )
        if peer._bitswap is not None:
            await peer._bitswap.start()
        return peer

    async def close(self) -> None:
        if self._bitswap is not None:
            await self._bitswap.stop()

    async def bootstrap(self, peers: list[Any]) -> None:
        if self.routing and hasattr(self.routing, "bootstrap"):
            await self.routing.bootstrap()

    def session(self, ctx: Any | None = None) -> Any:
        return self

    async def add(self, node: Any) -> Any:
        from libp2p.bitswap.cid import compute_cid_obj
        if isinstance(node, dict):
            import json
            data = json.dumps(node).encode()
        elif isinstance(node, str):
            data = node.encode()
        else:
            data = bytes(node)

        cid = compute_cid_obj(data)
        if self._bitswap is not None:
            await self._bitswap.add_block(cid, data)
        else:
            await self.blockstore.put_block(cid, data)
        return cid

    async def get(self, cid: Any) -> Any:
        if self._bitswap is not None:
            data = await self._bitswap.get_block(cid)
            return data
        else:
            return await self.blockstore.get_block(cid)

    async def remove(self, cid: Any) -> None:
        await self.blockstore.delete_block(cid)

    async def add_file(self, source: Any, params: AddParams | None = None) -> Any:
        if self._dag is None:
            raise RuntimeError("MerkleDag not initialized (requires host)")
        
        if hasattr(source, "read"):
            if hasattr(source, "mode") and "b" not in source.mode:
                # String IO
                data = source.read().encode()
                return await self._dag.add_bytes(data)
            return await self._dag.add_stream(source)
        elif isinstance(source, str):
            import os
            if os.path.exists(source):
                return await self._dag.add_file(source)
            else:
                return await self._dag.add_bytes(source.encode())
        elif isinstance(source, bytes):
            return await self._dag.add_bytes(source)
        else:
            raise TypeError("Unsupported source type for add_file")

    async def get_file(self, cid: Any) -> Any:
        import io
        if self._dag is None:
            raise RuntimeError("MerkleDag not initialized (requires host)")
        
        result = await self._dag.fetch_file(cid)
        if isinstance(result, tuple):
            data, filename = result
        else:
            data = result
        return io.BytesIO(data)

    def block_store(self) -> Any:
        return self.blockstore

    async def has_block(self, cid: Any) -> bool:
        return await self.blockstore.has_block(cid)

    def exchange(self) -> Any:
        return self._bitswap

    def block_service(self) -> Any:
        return self._bitswap

