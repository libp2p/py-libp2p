import contextlib
import hashlib
import logging
from typing import Optional, Tuple

import trio
from multiaddr import Multiaddr

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.security.secio.transport import Transport as SecioTransport
from libp2p.bitswap import BitswapClient, MemoryBlockStore
from libp2p.bitswap.block_store import FilesystemBlockStore
from libp2p.bitswap.dag import MerkleDag, encode_node, decode_node, get_codec_from_cid, decode_dag_pb
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.bitswap.cid import (
    parse_cid, 
    format_cid_for_display, 
    compute_cid_v1,
    CODEC_DAG_PB,
    CODEC_RAW,
    CODEC_DAG_JSON,
    CODEC_DAG_CBOR,
    CODEC_IPLD,
    CODEC_DAG_JOSE,
    _normalise_codec,
    cid_to_bytes,
)
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery

from py_ipfs_lite.config import Config
from py_ipfs_lite.pin import PinStore
from py_ipfs_lite.reprovider import Reprovider
from py_ipfs_lite.interfaces import (
    Host, Routing, BlockStore, Exchange, DagService, Datastore,
    HostAdapter, RoutingAdapter, BlockStoreAdapter
)

logger = logging.getLogger("py_ipfs_lite.peer")


class Peer:
    def __init__(
        self,
        config: Config,
        *,
        host: Optional[Host] = None,
        routing: Optional[Routing] = None,
        datastore: Optional[Datastore] = None,
        blockstore: Optional[BlockStore] = None,
        exchange: Optional[Exchange] = None,
        dag_service: Optional[DagService] = None,
        host_key: Optional[KeyPair] = None,
        listen_addrs: Optional[list] = None,
    ):
        self.config = config
        self._host_key = host_key or create_new_key_pair()
        self._listen_addrs = listen_addrs or []
        
        self.host = host
        self.routing = routing
        self.datastore = datastore
        self.blockstore = blockstore
        self.exchange = exchange
        self.dag_service = dag_service
        
        pin_path = None
        if self.config.blockstore_type == "filesystem" and self.config.blockstore_path:
            import os
            pin_path = os.path.join(self.config.blockstore_path, "pins.json")
        self.pin_store = PinStore(pin_path)
        self.reprovider = Reprovider(self)
        
        self._started = False
        self._exit_stack = contextlib.AsyncExitStack()

    async def _create_host(self):
        maddrs = [Multiaddr(a) if isinstance(a, str) else a for a in self._listen_addrs]
        noise_key_pair = create_new_x25519_key_pair()
        sec_opt = {
            "/noise": NoiseTransport(
                self._host_key, noise_privkey=noise_key_pair.private_key
            ),
            "/secio/1.0.0": SecioTransport(self._host_key),
        }
        raw_host = new_host(key_pair=self._host_key, listen_addrs=maddrs, sec_opt=sec_opt)
        return HostAdapter(raw_host)

    async def _create_routing(self):
        raw_host = getattr(self.host, "_host", self.host)
        raw_routing = KadDHT(host=raw_host, mode=DHTMode.SERVER)
        return RoutingAdapter(raw_routing)

    def _create_blockstore(self):
        if self.config.blockstore_type == "filesystem":
            if not self.config.blockstore_path:
                raise ValueError("blockstore_path must be provided when blockstore_type is 'filesystem'")
            return BlockStoreAdapter(FilesystemBlockStore(self.config.blockstore_path))
        return BlockStoreAdapter(MemoryBlockStore())

    def _create_exchange(self):
        raw_host = getattr(self.host, "_host", self.host)
        raw_bs = getattr(self.blockstore, "_store", self.blockstore)
        return BitswapClient(raw_host, raw_bs)

    def _create_dag_service(self):
        return MerkleDag(self.exchange)

    async def start(self) -> None:
        if self._started:
            return

        if self.host is None:
            self.host = await self._create_host()
        if self.routing is None:
            self.routing = await self._create_routing()
        if self.blockstore is None:
            self.blockstore = self._create_blockstore()
        if self.exchange is None:
            self.exchange = self._create_exchange()
        if self.dag_service is None:
            self.dag_service = self._create_dag_service()

        maddrs = [Multiaddr(a) if isinstance(a, str) else a for a in self._listen_addrs]
        await self._exit_stack.enter_async_context(self.host.run(maddrs))
        
        nursery = await self._exit_stack.enter_async_context(trio.open_nursery())
        if hasattr(self.exchange, "set_nursery"):
            self.exchange.set_nursery(nursery)
        
        nursery.start_soon(self.reprovider.start)
        
        await self.exchange.start()
        
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
            
        await self.reprovider.stop()
        await self.exchange.stop()
        await self._exit_stack.aclose()
        self._started = False

    async def bootstrap(self, peers: list[str]) -> None:
        """Connect to bootstrap peers and join the DHT network."""
        self._ensure_started()
        discovery = BootstrapDiscovery(
            swarm=self.host.get_network(),
            bootstrap_addrs=peers
        )
        await discovery.start()

    async def add_file(self, path: str) -> str:
        self._ensure_started()
        cid = await self.dag_service.add_file(path, wrap_with_directory=False)
        cid_str = format_cid_for_display(cid)
        if self.routing:
            try:
                await self.routing.provide(cid_str)
            except Exception as e:
                logger.warning(f"Failed to provide {cid_str} to DHT: {e}")
        return cid_str

    async def get_file(self, cid_str: str, output_path: Optional[str] = None, provider_addr: Optional[str] = None) -> bytes:
        self._ensure_started()
        if provider_addr:
            maddr = Multiaddr(provider_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
        elif self.routing:
            try:
                providers = await self.routing.find_providers(cid_str)
                for provider in providers:
                    if provider.peer_id == self.host.id():
                        continue
                    try:
                        await self.host.connect(provider)
                    except Exception as e:
                        logger.debug(f"Failed to connect to provider {provider.peer_id}: {e}")
            except Exception as e:
                logger.warning(f"Failed to find providers for {cid_str} in DHT: {e}")
            
        cid = parse_cid(cid_str)
        content, _ = await self.dag_service.fetch_file(cid)
        
        if output_path:
            with open(output_path, "wb") as f:
                f.write(content)
                
        return content

    async def add_node(self, node, codec: str = "dag-json") -> str:
        self._ensure_started()
        data = encode_node(node, codec)
        cid = compute_cid_v1(data, codec=codec)
        await self.blockstore.put(cid, data)
        cid_str = format_cid_for_display(cid)
        if self.routing:
            try:
                await self.routing.provide(cid_str)
            except Exception as e:
                logger.warning(f"Failed to provide {cid_str} to DHT: {e}")
        return cid_str

    async def get_node(self, cid_str: str, provider_addr: Optional[str] = None):
        self._ensure_started()
        if provider_addr:
            maddr = Multiaddr(provider_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
        elif self.routing:
            try:
                providers = await self.routing.find_providers(cid_str)
                for provider in providers:
                    if provider.peer_id == self.host.id():
                        continue
                    try:
                        await self.host.connect(provider)
                    except Exception as e:
                        logger.debug(f"Failed to connect to provider {provider.peer_id}: {e}")
            except Exception as e:
                logger.warning(f"Failed to find providers for {cid_str} in DHT: {e}")
            
        cid = parse_cid(cid_str)
        data = await self.exchange.get_block(cid)
        if data is None:
            raise ValueError(f"Block not found for CID: {cid_str}")
        codec = get_codec_from_cid(cid)
        return decode_node(data, codec)

    async def remove_node(self, cid_str: str) -> None:
        self._ensure_started()
        cid = parse_cid(cid_str)
        await self.blockstore.delete(cid)

    async def add_pin(self, cid_str: str, recursive: bool = True) -> None:
        self._ensure_started()
        self.pin_store.add_pin(cid_str, recursive)

    async def remove_pin(self, cid_str: str) -> None:
        self._ensure_started()
        self.pin_store.remove_pin(cid_str)

    async def gc(self) -> dict:
        self._ensure_started()
        
        all_cids = set(self.blockstore.all_keys())
        reachable_cids = set()

        async def traverse(cid_bytes: bytes, recursive: bool):
            queue = [cid_bytes]
            while queue:
                curr_cid = queue.pop(0)
                if curr_cid in reachable_cids:
                    continue
                
                reachable_cids.add(curr_cid)

                if not recursive and curr_cid != cid_bytes:
                    continue
                
                data = await self.blockstore.get(curr_cid)
                if data is None:
                    continue
                
                codec = get_codec_from_cid(curr_cid)
                norm_codec = _normalise_codec(codec)

                if norm_codec == CODEC_DAG_PB:
                    try:
                        node_links, _ = decode_dag_pb(data)
                        for link in node_links:
                            if hasattr(link, "cid"):
                                queue.append(link.cid)
                    except Exception:
                        pass
                elif norm_codec in (CODEC_DAG_JSON, CODEC_DAG_CBOR, CODEC_IPLD, CODEC_DAG_JOSE):
                    try:
                        decoded = decode_node(data, codec)
                        def extract_links(obj):
                            if isinstance(obj, dict):
                                if "/" in obj and isinstance(obj["/"], str):
                                    try:
                                        link_cid = parse_cid(obj["/"])
                                        queue.append(cid_to_bytes(link_cid))
                                    except Exception:
                                        pass
                                for v in obj.values():
                                    extract_links(v)
                            elif isinstance(obj, list):
                                for item in obj:
                                    extract_links(item)
                        extract_links(decoded)
                    except Exception:
                        pass

        for cid_str, is_rec in self.pin_store.get_pins().items():
            try:
                c = parse_cid(cid_str)
                await traverse(cid_to_bytes(c), is_rec)
            except Exception as e:
                logger.warning(f"Failed to traverse pinned CID {cid_str}: {e}")

        to_delete = all_cids - reachable_cids
        deleted_count = 0
        for c_bytes in to_delete:
            await self.blockstore.delete_block(c_bytes)
            deleted_count += 1
            
        return {"reclaimed_blocks": deleted_count, "retained_blocks": len(reachable_cids)}

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("Peer not started. Call start() first.")
