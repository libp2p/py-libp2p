from collections.abc import AsyncIterator
from typing import Any, Protocol


class Datastore(Protocol):
    async def get(self, key: bytes) -> bytes: ...
    async def put(self, key: bytes, value: bytes) -> None: ...
    async def delete(self, key: bytes) -> None: ...
    async def query(self, prefix: str) -> AsyncIterator[tuple[str, bytes]]: ...
    async def close(self) -> None: ...


class BlockStore(Protocol):
    async def put(self, cid: bytes, data: bytes) -> None: ...
    async def get(self, cid: bytes) -> bytes | None: ...
    async def has(self, cid: bytes) -> bool: ...
    async def delete(self, cid: bytes) -> None: ...
    async def get_size(self, cid: bytes) -> int: ...
    def all_keys(self) -> list[str]: ...


class Exchange(Protocol):
    async def get_block(
        self,
        cid: bytes,
        peer_id: Any = None,
        timeout: float = 90,
    ) -> bytes | None: ...
    async def get_blocks(
        self, cids: list[bytes]
    ) -> AsyncIterator[tuple[bytes, bytes]]: ...
    def notify_new_blocks(self, blocks: Any) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class DagService(Protocol):
    async def add(self, node: Any) -> Any: ...
    async def get(self, cid: Any) -> Any: ...
    async def remove(self, cid: Any) -> None: ...
    async def get_many(self, cids: list[Any]) -> Any: ...


class Routing(Protocol):
    async def bootstrap(self) -> None: ...
    async def find_providers(self, key: str, count: int = 20) -> list[Any]: ...
    async def provide(self, key: str) -> bool: ...
    async def get_value(self, key: str) -> bytes | None: ...
    async def put_value(self, key: str, value: bytes) -> None: ...


class Host(Protocol):
    def id(self) -> Any: ...
    def addrs(self) -> list[Any]: ...
    async def connect(self, peer_info: Any) -> None: ...
    async def disconnect(self, peer_id: Any) -> None: ...
    async def open_stream(self, peer_id: Any, protocol_ids: list[str]) -> Any: ...
    def set_stream_handler(self, protocol_id: str, stream_handler: Any) -> None: ...
    async def close(self) -> None: ...


# Adapters for py-libp2p concrete types


class HostAdapter:
    def __init__(self, host: Any) -> None:
        self._host = host

    def id(self) -> Any:
        return self._host.get_id()

    def addrs(self) -> Any:
        return self._host.get_addrs()

    async def connect(self, peer_info: Any) -> Any:
        return await self._host.connect(peer_info)

    async def disconnect(self, peer_id: Any) -> Any:
        return await self._host.disconnect(peer_id)

    async def open_stream(self, peer_id: Any, protocol_ids: Any) -> Any:
        return await self._host.new_stream(peer_id, protocol_ids)

    def set_stream_handler(self, protocol_id: Any, stream_handler: Any) -> Any:
        return self._host.set_stream_handler(protocol_id, stream_handler)

    async def close(self) -> Any:
        return await self._host.close()

    # Pass-through for existing usage
    def get_network(self) -> Any:
        return self._host.get_network()

    def run(self, *args: Any, **kwargs: Any) -> Any:
        return self._host.run(*args, **kwargs)


class BlockStoreAdapter:
    def __init__(self, blockstore: Any) -> None:
        self._store = blockstore

    async def put(self, cid: bytes, data: bytes) -> None:
        return await self._store.put_block(cid, data)

    async def get(self, cid: bytes) -> bytes | None:
        return await self._store.get_block(cid)

    async def has(self, cid: bytes) -> bool:
        return await self._store.has_block(cid)

    async def delete(self, cid: bytes) -> None:
        return await self._store.delete_block(cid)

    async def get_size(self, cid: bytes) -> int:
        if hasattr(self._store, "get_size"):
            import inspect

            if inspect.iscoroutinefunction(self._store.get_size):
                return await self._store.get_size(cid)
            return self._store.get_size(cid)
        data = await self.get(cid)
        return len(data) if data else 0

    def all_keys(self) -> list[str]:
        from libp2p.bitswap.cid import format_cid_for_display, parse_cid

        return [
            format_cid_for_display(parse_cid(c)) for c in self._store.get_all_cids()
        ]


from py_ipfs_lite.metrics import IPFS_DHT_QUERY_LATENCY_SECONDS


class RoutingAdapter:
    def __init__(self, routing: Any) -> None:
        self._routing = routing

    async def bootstrap(self) -> None:
        with IPFS_DHT_QUERY_LATENCY_SECONDS.time():
            if hasattr(self._routing, "bootstrap"):
                return await self._routing.bootstrap()
            elif hasattr(self._routing, "refresh_routing_table"):
                return await self._routing.refresh_routing_table()

    async def refresh_routing_table(self) -> None:
        with IPFS_DHT_QUERY_LATENCY_SECONDS.time():
            if hasattr(self._routing, "refresh_routing_table"):
                return await self._routing.refresh_routing_table()

    async def find_providers(self, key: str, count: int = 20) -> list[Any]:
        with IPFS_DHT_QUERY_LATENCY_SECONDS.time():
            return await self._routing.find_providers(key, count)

    async def provide(self, key: str) -> bool:
        with IPFS_DHT_QUERY_LATENCY_SECONDS.time():
            return await self._routing.provide(key)

    async def get_value(self, key: str | bytes) -> bytes | None:
        return await self._routing.get_value(key)

    async def put_value(self, key: str | bytes, value: bytes) -> None:
        return await self._routing.put_value(key, value)
