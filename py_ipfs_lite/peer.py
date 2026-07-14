import contextlib
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from typing import (
    Any,
    BinaryIO,
)

import trio
from libp2p import new_host
from multiaddr import Multiaddr

from py_ipfs_lite.config import AddParams, Config
from py_ipfs_lite.exceptions import BlockNotFoundError, PeerNotStartedError
from py_ipfs_lite.metrics import (
    IPFS_BITSWAP_BYTES_RECEIVED_TOTAL,
    IPFS_GC_RECLAIMED_BLOCKS_TOTAL,
    IPFS_GC_RUNS_TOTAL,
    MetricsBlockStore,
)


@dataclass
class GCResult:
    reclaimed_blocks: int
    retained_blocks: int


import json

import cbor2
from libp2p.bitswap import BitswapClient, MemoryBlockStore
from libp2p.bitswap.block_store import FilesystemBlockStore
from libp2p.bitswap.cid import (
    cid_to_bytes,
    compute_cid_v1,
    format_cid_for_display,
    parse_cid,
    parse_cid_codec,
)
from libp2p.bitswap.dag import MerkleDag, decode_dag_pb
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.network.auto_connector import AutoConnector
from libp2p.network.connection_pruner import ConnectionPruner
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.security.noise.transport import Transport as NoiseTransport


def encode_node(node: Any, codec: str) -> bytes:
    if codec == "dag-json":
        return json.dumps(node, separators=(",", ":")).encode("utf-8")
    elif codec in ("dag-cbor", "cbor"):
        return cbor2.dumps(node)
    elif codec == "raw":
        return node if isinstance(node, bytes) else node.encode("utf-8")
    else:
        raise ValueError(f"Unsupported codec for encode_node: {codec}")


def decode_node(data: bytes, codec: str) -> Any:
    if codec == "dag-json":
        return json.loads(data.decode("utf-8"))
    elif codec in ("dag-cbor", "cbor"):
        return cbor2.loads(data)
    elif codec == "raw":
        return data
    elif codec == "dag-pb":
        links, unixfs = decode_dag_pb(data)
        return {"Links": links, "Data": unixfs}
    else:
        raise ValueError(f"Unsupported codec for decode_node: {codec}")


from py_ipfs_lite.interfaces import (
    BlockStore,
    BlockStoreAdapter,
    DagService,
    Datastore,
    Exchange,
    Host,
    HostAdapter,
    Routing,
    RoutingAdapter,
)
from py_ipfs_lite.pin import PinStore
from py_ipfs_lite.reprovider import Reprovider

logger = logging.getLogger("py_ipfs_lite.peer")


def default_bootstrap_peers() -> list[str]:
    from py_ipfs_lite.cli import DEFAULT_BOOTSTRAP_PEERS

    return DEFAULT_BOOTSTRAP_PEERS.copy()


async def setup_libp2p(
    host_key: Any,
    listen_addrs: list[Any],
    datastore: Any = None,
    offline: bool = False,
) -> Any:
    maddrs = [Multiaddr(a) if isinstance(a, str) else a for a in listen_addrs]
    noise_key_pair = create_new_x25519_key_pair()
    sec_opt = {
        "/noise": NoiseTransport(host_key, noise_privkey=noise_key_pair.private_key),
    }
    raw_host = new_host(key_pair=host_key, listen_addrs=maddrs, sec_opt=sec_opt)  # type: ignore[arg-type]

    if not offline:
        raw_routing = KadDHT(host=raw_host, mode=DHTMode.SERVER)
        return HostAdapter(raw_host), RoutingAdapter(raw_routing)
    return HostAdapter(raw_host), None


def new_in_memory_datastore() -> Any:
    return BlockStoreAdapter(MemoryBlockStore())


class RWLock:
    """A trio-compatible read-write lock to allow concurrent reads but exclusive writes."""

    def __init__(self) -> None:
        self._write_lock = trio.Lock()
        self._read_count = 0
        self._read_count_lock = trio.Lock()
        self._read_cond = trio.Condition(self._read_count_lock)

    @contextlib.asynccontextmanager
    async def read_lock(self) -> AsyncGenerator[Any, None]:
        async with self._write_lock:
            async with self._read_count_lock:
                self._read_count += 1
        try:
            yield
        finally:
            async with self._read_count_lock:
                self._read_count -= 1
                if self._read_count == 0:
                    self._read_cond.notify_all()

    @contextlib.asynccontextmanager
    async def write_lock(self) -> AsyncGenerator[Any, None]:
        async with self._write_lock:
            async with self._read_count_lock:
                while self._read_count > 0:
                    await self._read_cond.wait()
            try:
                yield
            finally:
                pass


class Peer:
    def __init__(
        self,
        config: Config,
        *,
        host: Host | None = None,
        routing: Routing | None = None,
        datastore: Datastore | None = None,
        blockstore: BlockStore | None = None,
        exchange: Exchange | None = None,
        dag_service: DagService | None = None,
        host_key: KeyPair | None = None,
        listen_addrs: list[Any] | None = None,
    ) -> None:
        self.config = config
        self._host_key = host_key or create_new_key_pair()
        self._listen_addrs = listen_addrs or []

        self.host = host
        self.routing = routing
        self.datastore = datastore
        self.blockstore = blockstore
        self._exchange = exchange
        self.dag_service = dag_service

        pin_path = None
        if self.config.blockstore_type == "filesystem" and self.config.blockstore_path:
            import os

            pin_path = os.path.join(self.config.blockstore_path, "pins.json")
        self.pin_store = PinStore(pin_path)
        self.reprovider = Reprovider(self)

        self._gc_lock = RWLock()
        self._started = False
        self._exit_stack = contextlib.AsyncExitStack()
        self._auto_connector = None
        self._connection_pruner = None

    @classmethod
    async def new(
        cls, datastore: Any, blockstore: Any, host: Any, routing: Any, config: Any
    ) -> Any:
        peer = cls(
            config=config,
            datastore=datastore,
            blockstore=blockstore,
            host=host,
            routing=routing,
        )
        await peer.start()
        return peer

    async def _create_host(self) -> Any:
        maddrs = [Multiaddr(a) if isinstance(a, str) else a for a in self._listen_addrs]
        noise_key_pair = create_new_x25519_key_pair()
        sec_opt = {
            "/noise": NoiseTransport(
                self._host_key, noise_privkey=noise_key_pair.private_key
            ),
        }
        raw_host = new_host(
            key_pair=self._host_key,
            listen_addrs=maddrs,
            sec_opt=sec_opt,  # type: ignore[arg-type]
        )
        return HostAdapter(raw_host)

    async def _create_routing(self) -> Any:
        if self.config.offline:
            return None

        raw_host = getattr(self.host, "_host", self.host)
        raw_routing = KadDHT(host=raw_host, mode=DHTMode.SERVER)  # type: ignore[arg-type]
        dht_adapter = RoutingAdapter(raw_routing)

        if getattr(self.config, "use_ipni", False):
            from py_ipfs_lite.routing import DelegatedHTTPRouting, TieredRouting

            ipni = DelegatedHTTPRouting(
                endpoint=getattr(self.config, "ipni_endpoint", "https://cid.contact"),
                host=raw_host,
            )
            return TieredRouting([ipni, dht_adapter])

        return dht_adapter

    def _create_blockstore(self) -> Any:
        if self.config.blockstore_type == "filesystem":
            if not self.config.blockstore_path:
                raise ValueError(
                    "blockstore_path must be provided when blockstore_type is 'filesystem'"
                )

            from py_ipfs_lite.versioning import init_repo_version

            init_repo_version(self.config.blockstore_path)

            raw_bs = FilesystemBlockStore(self.config.blockstore_path)
        else:
            raw_bs = MemoryBlockStore()  # type: ignore[assignment]
        return BlockStoreAdapter(MetricsBlockStore(raw_bs))

    def _create_exchange(self) -> Any:
        raw_host = getattr(self.host, "_host", self.host)
        raw_bs = getattr(self.blockstore, "_store", self.blockstore)
        bitswap = BitswapClient(raw_host, raw_bs)  # type: ignore[arg-type]

        class ExchangeAdapter:
            def __init__(self, exchange: Any) -> None:
                self._exchange = exchange

            async def get_block(
                self, cid: Any, peer_id: Any = None, timeout: float = 90
            ) -> Any:
                data = await self._exchange.get_block(
                    cid, peer_id=peer_id, timeout=timeout
                )
                if data:
                    IPFS_BITSWAP_BYTES_RECEIVED_TOTAL.inc(len(data))
                return data

            def __getattr__(self, name: Any) -> Any:
                return getattr(self._exchange, name)

        return ExchangeAdapter(bitswap)

    def _create_dag_service(self) -> Any:
        return MerkleDag(self._exchange)  # type: ignore[arg-type]

    async def start(self) -> None:
        if self._started:
            return

        if self.host is None:
            self.host = await self._create_host()
        if self.routing is None:
            self.routing = await self._create_routing()
        if self.blockstore is None:
            self.blockstore = self._create_blockstore()
        if self._exchange is None:
            self._exchange = self._create_exchange()
        if self.dag_service is None:
            self.dag_service = self._create_dag_service()

        maddrs = [Multiaddr(a) if isinstance(a, str) else a for a in self._listen_addrs]
        await self._exit_stack.enter_async_context(self.host.run(maddrs))  # type: ignore[union-attr]

        self._nursery = await self._exit_stack.enter_async_context(trio.open_nursery())
        if hasattr(self._exchange, "set_nursery"):
            self._exchange.set_nursery(self._nursery)

        self._nursery.start_soon(self.reprovider.start)

        # Initialize and start connection managers
        raw_swarm = self.host._host.get_network()  # type: ignore[union-attr]
        if hasattr(raw_swarm, "connection_config") and raw_swarm.connection_config:
            raw_swarm.connection_config.high_watermark = self.config.conn_mgr_high_water
            raw_swarm.connection_config.low_watermark = self.config.conn_mgr_low_water
            raw_swarm.connection_config.max_connections = (
                self.config.conn_mgr_high_water
            )

            self._auto_connector = AutoConnector(raw_swarm)  # type: ignore[assignment]
            self._connection_pruner = ConnectionPruner(raw_swarm)  # type: ignore[assignment]

            await self._auto_connector.start()  # type: ignore[attr-defined]
            await self._connection_pruner.start()  # type: ignore[attr-defined]

            await self._auto_connector.run_background_task(self._nursery)  # type: ignore[attr-defined]
            self._nursery.start_soon(self._periodic_pruner_task)

        await self._exchange.start()

        self._started = True

    async def _periodic_pruner_task(self) -> None:
        """Periodically trigger connection pruning."""
        while self._started:
            if self._connection_pruner:
                try:
                    await self._connection_pruner.maybe_prune_connections()
                except Exception as e:
                    logger.debug(f"Error in connection pruner: {e}")
            await trio.sleep(15.0)

    async def __aenter__(self) -> "Peer":
        if not self._started:
            await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if not self._started:
            return

        if hasattr(self, "_nursery") and self._nursery:
            self._nursery.cancel_scope.cancel()

        await self.reprovider.stop()
        await self._exchange.stop()  # type: ignore[union-attr]
        if self._auto_connector:
            await self._auto_connector.stop()
        if self._connection_pruner:
            await self._connection_pruner.stop()

        if self.routing and hasattr(self.routing, "close"):
            await self.routing.close()

        await self._exit_stack.aclose()
        self._started = False

    async def bootstrap(self, peers: list[str]) -> None:
        """Connect to bootstrap peers and join the DHT network."""
        self._ensure_started()
        discovery = BootstrapDiscovery(
            swarm=self.host.get_network(),  # type: ignore
            bootstrap_addrs=peers,  # type: ignore[union-attr]
        )
        await discovery.start()

    async def add_file(
        self,
        path_or_stream: str | bytes | BinaryIO,
        params: AddParams | None = None,
        timeout: float | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> str:
        self._ensure_started()
        t_val = timeout if timeout is not None else self.config.default_timeout
        chunk_size: int | None = None
        if params is not None and params.chunker and params.chunker.startswith("size-"):
            try:
                chunk_size = int(params.chunker.split("-")[1])
            except ValueError:
                pass

        wrapped_callback = None
        if progress_callback is not None:

            def _wrapped_callback(
                bytes_written: int, total_bytes: int, phase: str
            ) -> None:
                progress_callback(bytes_written, total_bytes)

            wrapped_callback = _wrapped_callback

        async with self._gc_lock.read_lock():
            if isinstance(path_or_stream, str):
                cid = await self.dag_service.add_file(  # type: ignore[union-attr]
                    path_or_stream,
                    chunk_size=chunk_size,
                    progress_callback=wrapped_callback,
                    wrap_with_directory=False,
                )
            elif isinstance(path_or_stream, bytes):
                cid = await self.dag_service.add_bytes(  # type: ignore[union-attr]
                    path_or_stream,
                    chunk_size=chunk_size,
                    progress_callback=wrapped_callback,
                )
            else:
                cid = await self.dag_service.add_stream(  # type: ignore[union-attr]
                    path_or_stream,
                    chunk_size=chunk_size,
                    progress_callback=wrapped_callback,
                )
        cid_str = format_cid_for_display(cid)
        if self.routing:
            try:
                with trio.fail_after(t_val):
                    await self.routing.provide(cid_str)
            except Exception as e:
                logger.warning(f"Failed to provide {cid_str} to DHT: {e}")
        return cid_str

    async def get_file(
        self,
        cid_str: str,
        provider_addr: str | None = None,
        output_path: str | None = None,
        timeout: float | None = None,
        stream: bool = False,
    ) -> bytes | AsyncIterator[bytes] | None:
        self._ensure_started()
        t_val = timeout if timeout is not None else self.config.default_timeout
        cid = parse_cid(cid_str)
        has_root = await self.blockstore.has(cid_to_bytes(cid))  # type: ignore[union-attr]

        if not has_root:
            if provider_addr:
                maddr = Multiaddr(provider_addr)
                info = info_from_p2p_addr(maddr)
                await self.host.connect(info)  # type: ignore[union-attr]
            elif self.routing:
                try:
                    with trio.fail_after(t_val):
                        providers = await self.routing.find_providers(cid_str)
                    for provider in providers:
                        if provider.peer_id == self.host.id():  # type: ignore[union-attr]
                            continue
                        try:
                            with trio.fail_after(t_val):
                                await self.host.connect(provider)  # type: ignore[union-attr]
                        except Exception as e:
                            logger.debug(
                                f"Failed to connect to provider {provider.peer_id}: {e}"
                            )
                except Exception as e:
                    logger.warning(
                        f"Failed to find providers for {cid_str} in DHT: {e}"
                    )

        from libp2p.bitswap.dag import is_directory_node

        # Helper to isolate trio.fail_after from the async generator
        async def fetch_block_with_timeout(current_cid: Any) -> Any:
            with trio.fail_after(t_val):
                return await self._exchange.get_block(current_cid)  # type: ignore[union-attr]

        async def fetch_stream(current_cid: Any) -> AsyncGenerator[Any, None]:
            data = await fetch_block_with_timeout(current_cid)
            if data is None:
                raise BlockNotFoundError(
                    f"Block not found for CID: {format_cid_for_display(current_cid)}"
                )

            codec = parse_cid_codec(cid_to_bytes(current_cid))
            if codec == "raw":
                yield data
                return

            if codec == "dag-pb":
                if is_directory_node(data):
                    links, _ = decode_dag_pb(data)
                    if links:
                        async for chunk in fetch_stream(links[0].cid):
                            yield chunk
                    return

                links, unixfs = decode_dag_pb(data)
                if not links:
                    if unixfs and unixfs.data:
                        yield unixfs.data
                    return

                for link in links:
                    async for chunk in fetch_stream(link.cid):
                        yield chunk

        if output_path:
            with open(output_path, "wb") as f:
                async for chunk in fetch_stream(cid):
                    f.write(chunk)
            return None

        if stream:
            return fetch_stream(cid)

        # Default behavior: buffer and return bytes
        chunks = []
        async for chunk in fetch_stream(cid):
            chunks.append(chunk)
        return b"".join(chunks)

    async def add_node(
        self,
        node: dict[Any, Any] | list[Any] | str | int | bytes,
        codec: str = "dag-json",
        timeout: float | None = None,
    ) -> str:
        self._ensure_started()
        t_val = timeout if timeout is not None else self.config.default_timeout
        data = encode_node(node, codec)
        cid = compute_cid_v1(data, codec=codec)
        async with self._gc_lock.read_lock():
            await self.blockstore.put(cid, data)  # type: ignore[union-attr]
        cid_str = format_cid_for_display(cid)
        if self.routing:
            try:
                with trio.fail_after(t_val):
                    await self.routing.provide(cid_str)
            except Exception as e:
                logger.warning(f"Failed to provide {cid_str} to DHT: {e}")
        return cid_str

    async def get_node(
        self,
        cid_str: str,
        provider_addr: str | None = None,
        timeout: float | None = None,
    ) -> dict[Any, Any] | list[Any] | str | int | bytes:
        self._ensure_started()
        t_val = timeout if timeout is not None else self.config.default_timeout
        cid = parse_cid(cid_str)

        # Check local blockstore first
        data = await self.blockstore.get(cid_to_bytes(cid))  # type: ignore[union-attr]

        if data is None:
            if provider_addr:
                maddr = Multiaddr(provider_addr)
                info = info_from_p2p_addr(maddr)
                await self.host.connect(info)  # type: ignore[union-attr]
            elif self.routing:
                try:
                    with trio.fail_after(t_val):
                        providers = await self.routing.find_providers(cid_str)
                    for provider in providers:
                        if provider.peer_id == self.host.id():  # type: ignore[union-attr]
                            continue
                        try:
                            with trio.fail_after(t_val):
                                await self.host.connect(provider)  # type: ignore[union-attr]
                        except Exception as e:
                            logger.debug(
                                f"Failed to connect to provider {provider.peer_id}: {e}"
                            )
                except Exception as e:
                    logger.warning(
                        f"Failed to find providers for {cid_str} in DHT: {e}"
                    )

            with trio.fail_after(t_val):
                data = await self._exchange.get_block(cid)  # type: ignore[union-attr]

        if data is None:
            raise BlockNotFoundError(f"Block not found for CID: {cid_str}")
        codec = parse_cid_codec(cid_to_bytes(cid))
        return decode_node(data, codec)

    async def remove_node(self, cid_str: str) -> None:
        self._ensure_started()
        cid = parse_cid(cid_str)
        await self.blockstore.delete(cid)  # type: ignore[union-attr]

    async def add_pin(self, cid_str: str, recursive: bool = True) -> None:
        self._ensure_started()
        pin_type = "recursive" if recursive else "direct"
        self.pin_store.add_pin(cid_str, pin_type)

    async def remove_pin(self, cid_str: str) -> None:
        self._ensure_started()
        self.pin_store.remove_pin(cid_str)

    async def list_pins(self, type_filter: str = "all") -> dict[str, str]:
        """List pins by type. type_filter can be 'direct', 'recursive', 'indirect', or 'all'."""
        self._ensure_started()

        if type_filter not in ("all", "direct", "recursive", "indirect"):
            raise ValueError(
                "Invalid type_filter. Must be 'all', 'direct', 'recursive', or 'indirect'"
            )

        stored_pins = self.pin_store.get_pins()

        if type_filter in ("direct", "recursive"):
            return {k: v for k, v in stored_pins.items() if v == type_filter}

        result = stored_pins.copy()

        from libp2p.bitswap.cid import cid_to_bytes, format_cid_for_display, parse_cid

        from py_ipfs_lite.dag_utils import walk_dag

        indirect_pins = {}
        for cid_str, pin_type in stored_pins.items():
            if pin_type == "recursive":
                try:
                    c_bytes = cid_to_bytes(parse_cid(cid_str))
                    async for reachable_cid_bytes in walk_dag(
                        c_bytes,
                        self.blockstore.get,  # type: ignore[union-attr]
                        recursive=True,  # type: ignore[union-attr]
                    ):
                        if reachable_cid_bytes != c_bytes:
                            r_str = format_cid_for_display(
                                parse_cid(reachable_cid_bytes)
                            )
                            if r_str not in result:
                                indirect_pins[r_str] = "indirect"
                except Exception as e:
                    logger.warning(f"Failed to traverse pinned CID {cid_str}: {e}")

        if type_filter == "indirect":
            return indirect_pins

        result.update(indirect_pins)
        return result

    async def gc(self) -> GCResult:
        self._ensure_started()
        from libp2p.bitswap.cid import format_cid_for_display

        from py_ipfs_lite.dag_utils import walk_dag

        async with self._gc_lock.write_lock():
            IPFS_GC_RUNS_TOTAL.inc()
            all_cids = set(self.blockstore.all_keys())  # type: ignore[union-attr]
            reachable_cids = set()

            for cid_str, pin_type in self.pin_store.get_pins().items():
                try:
                    c_bytes = cid_to_bytes(parse_cid(cid_str))
                    is_rec = pin_type == "recursive"
                    async for reachable_cid_bytes in walk_dag(
                        c_bytes,
                        self.blockstore.get,  # type: ignore[union-attr]
                        recursive=is_rec,  # type: ignore[union-attr]
                    ):
                        reachable_cids.add(
                            format_cid_for_display(parse_cid(reachable_cid_bytes))
                        )
                except Exception as e:
                    logger.warning(f"Failed to traverse pinned CID {cid_str}: {e}")

            to_delete = all_cids - reachable_cids
            deleted_count = 0
            for c_str in to_delete:
                await self.blockstore.delete(cid_to_bytes(parse_cid(c_str)))  # type: ignore[union-attr]
                deleted_count += 1

            IPFS_GC_RECLAIMED_BLOCKS_TOTAL.inc(deleted_count)
            return GCResult(
                reclaimed_blocks=deleted_count, retained_blocks=len(reachable_cids)
            )

    async def resolve_name(self, peer_id_str: str, timeout: float | None = None) -> str:
        """Resolve an IPNS name (PeerID) to its value."""
        self._ensure_started()
        t_val = timeout if timeout is not None else self.config.default_timeout
        from libp2p.peer.id import ID

        from py_ipfs_lite.ipns import resolve_name as ipns_resolve

        # We need to look up the routing
        peer_id = ID.from_base58(peer_id_str)
        with trio.fail_after(t_val):
            return await ipns_resolve(self.routing, peer_id)

    async def publish_name(
        self, value: str, lifetime_hours: int = 24, timeout: float | None = None
    ) -> str:
        """Publish an IPNS record pointing to `value` using this node's private key."""
        self._ensure_started()
        t_val = timeout if timeout is not None else self.config.default_timeout
        # Sequence number could be maintained in datastore or retrieved from DHT first.
        # For a basic implementation, we just use a timestamp for sequence to ensure it's monotonically increasing
        import time

        from py_ipfs_lite.ipns import publish_name as ipns_publish

        sequence = int(time.time())

        with trio.fail_after(t_val):
            await ipns_publish(
                self.routing,
                self._host_key.private_key,
                self.host.id(),  # type: ignore[union-attr]
                value,
                sequence,
                lifetime_hours,
            )
        return self.host.id().to_base58()  # type: ignore[union-attr]

    async def export_car(self, cid_str: str, output_path: str) -> None:
        self._ensure_started()
        from py_ipfs_lite.car import export_car as _export_car

        await _export_car(self, cid_str, output_path)

    async def import_car(self, input_path: str) -> list[str]:
        self._ensure_started()
        from py_ipfs_lite.car import import_car as _import_car

        return await _import_car(self, input_path)

    def session(self) -> Any:
        return self

    async def has_block(self, cid_str: str) -> bool:
        self._ensure_started()
        cid = parse_cid(cid_str)
        return await self.blockstore.has(cid)  # type: ignore[union-attr]

    def block_store(self) -> Any:
        return self.blockstore

    def exchange(self) -> Any:
        return self._exchange

    def block_service(self) -> Any:
        return self.dag_service

    def _ensure_started(self) -> None:
        if not self._started:
            raise PeerNotStartedError("Peer not started. Call start() first.")
