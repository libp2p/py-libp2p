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
from libp2p.bitswap.dag import MerkleDag, encode_node, decode_node, get_codec_from_cid
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.bitswap.cid import parse_cid, format_cid_for_display, compute_cid_v1

from py_ipfs_lite.config import Config

logger = logging.getLogger("py_ipfs_lite.peer")


class Peer:
    def __init__(
        self,
        config: Config,
        *,
        host=None,
        routing=None,
        datastore=None,
        blockstore=None,
        exchange=None,
        dag_service=None,
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
        return new_host(key_pair=self._host_key, listen_addrs=maddrs, sec_opt=sec_opt)

    async def _create_routing(self):
        return KadDHT(host=self.host, mode=DHTMode.SERVER)

    def _create_blockstore(self):
        if self.config.blockstore_type == "filesystem":
            if not self.config.blockstore_path:
                raise ValueError("blockstore_path must be provided when blockstore_type is 'filesystem'")
            return FilesystemBlockStore(self.config.blockstore_path)
        return MemoryBlockStore()

    def _create_exchange(self):
        return BitswapClient(self.host, self.blockstore)

    def _create_dag_service(self):
        return MerkleDag(self.exchange)

    async def bootstrap(self) -> None:
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
        
        await self.exchange.start()
        
        self._started = True

    async def close(self) -> None:
        if not self._started:
            return
            
        await self.exchange.stop()
        await self._exit_stack.aclose()
        self._started = False

    async def add_file(self, path: str) -> str:
        self._ensure_started()
        cid = await self.dag_service.add_file(path, wrap_with_directory=False)
        return format_cid_for_display(cid)

    async def get_file(self, cid_str: str, output_path: Optional[str] = None, provider_addr: Optional[str] = None) -> bytes:
        self._ensure_started()
        if provider_addr:
            maddr = Multiaddr(provider_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
            
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
        await self.blockstore.put_block(cid, data)
        return format_cid_for_display(cid)

    async def get_node(self, cid_str: str, provider_addr: Optional[str] = None):
        self._ensure_started()
        if provider_addr:
            maddr = Multiaddr(provider_addr)
            info = info_from_p2p_addr(maddr)
            await self.host.connect(info)
            
        cid = parse_cid(cid_str)
        data = await self.exchange.get_block(cid)
        if data is None:
            raise ValueError(f"Block not found for CID: {cid_str}")
        codec = get_codec_from_cid(cid)
        return decode_node(data, codec)

    async def remove_node(self, cid_str: str) -> None:
        self._ensure_started()
        cid = parse_cid(cid_str)
        await self.blockstore.delete_block(cid)

    def _ensure_started(self) -> None:
        if not self._started:
            raise RuntimeError("Peer not started. Call bootstrap() first.")
