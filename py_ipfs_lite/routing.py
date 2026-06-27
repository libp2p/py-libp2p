import base64
import json
import logging
from typing import Any, List, Optional

import httpx
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from multiaddr import Multiaddr

logger = logging.getLogger("py_ipfs_lite.routing")


class DelegatedHTTPRouting:
    def __init__(self, endpoint: str = "https://cid.contact", host=None):
        self.endpoint = endpoint.rstrip("/")
        self.client = httpx.AsyncClient(base_url=self.endpoint, timeout=10.0)
        self.host = host

    async def bootstrap(self) -> None:
        pass

    async def find_providers(self, key: str, count: int = 20) -> List[PeerInfo]:
        providers = []
        try:
            # IPIP-337 Delegated Routing API
            response = await self.client.get(
                f"/routing/v1/providers/{key}",
                headers={"Accept": "application/x-ndjson"},
            )
            if response.status_code == 200:
                for line in response.text.strip().split("\n"):
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        peer_id_str = data.get("ID")
                        if not peer_id_str:
                            continue

                        addrs = data.get("Addrs", [])
                        maddrs = []
                        for a in addrs:
                            try:
                                maddrs.append(Multiaddr(a))
                            except Exception:
                                pass

                        try:
                            peer_id = ID.from_base58(peer_id_str)
                            providers.append(PeerInfo(peer_id, maddrs))
                        except Exception:
                            pass

                        if len(providers) >= count:
                            return providers
                    except Exception:
                        pass
                return providers

            # Fallback to IPNI native API
            response = await self.client.get(f"/cid/{key}")
            if response.status_code != 200:
                return providers

            data = response.json()
            results = data.get("MultihashResults", [])
            for res in results:
                for prov in res.get("ProviderResults", []):
                    provider_info = prov.get("Provider", {})
                    peer_id_str = provider_info.get("ID")
                    if not peer_id_str:
                        continue

                    addrs = provider_info.get("Addrs", [])
                    maddrs = []
                    for a in addrs:
                        try:
                            decoded = base64.b64decode(a)
                            maddrs.append(Multiaddr(decoded))
                        except Exception:
                            try:
                                maddrs.append(Multiaddr(a))
                            except Exception:
                                pass

                    try:
                        peer_id = ID.from_base58(peer_id_str)
                        providers.append(PeerInfo(peer_id, maddrs))
                    except Exception:
                        pass

                    if len(providers) >= count:
                        return providers
        except Exception as e:
            logger.warning(f"Failed to query HTTP Delegated Routing for {key}: {e}")

        return providers

    async def provide(self, key: str) -> bool:
        if not self.host:
            return False

        try:
            peer_id = self.host.get_id().to_base58()
            addrs = [str(a) for a in self.host.get_addrs()]

            payload = {"Schema": "peer", "ID": peer_id, "Addrs": addrs}

            resp = await self.client.put(f"/routing/v1/providers/{key}", json=payload)

            if resp.status_code in (200, 202, 204):
                return True
            else:
                logger.debug(f"IPNI provide failed: {resp.status_code} {resp.text}")
                return False

        except Exception as e:
            logger.debug(
                f"Failed to query HTTP Delegated Routing provide for {key}: {e}"
            )
            return False

    async def get_value(self, key: str) -> Optional[bytes]:
        return None

    async def put_value(self, key: str, value: bytes) -> None:
        pass

    async def close(self) -> None:
        await self.client.aclose()


class TieredRouting:
    def __init__(self, routers: List[Any]):
        self.routers = routers

    async def bootstrap(self) -> None:
        for r in self.routers:
            if hasattr(r, "bootstrap"):
                await r.bootstrap()
            elif hasattr(r, "refresh_routing_table"):
                await r.refresh_routing_table()

    async def find_providers(self, key: str, count: int = 20) -> List[PeerInfo]:
        all_providers = []
        seen_ids = set()
        for r in self.routers:
            try:
                providers = await r.find_providers(key, count)
                if not providers:
                    continue
                for p in providers:
                    if p.peer_id not in seen_ids:
                        seen_ids.add(p.peer_id)
                        all_providers.append(p)
                if len(all_providers) >= count:
                    break
            except Exception as e:
                logger.debug(f"Router {r} find_providers failed: {e}")
        return all_providers[:count]

    async def provide(self, key: str) -> bool:
        success = False
        for r in self.routers:
            try:
                if await r.provide(key):
                    success = True
            except Exception:
                pass
        return success

    async def get_value(self, key: str) -> Optional[bytes]:
        for r in self.routers:
            try:
                val = await r.get_value(key)
                if val is not None:
                    return val
            except Exception:
                pass
        return None

    async def put_value(self, key: str, value: bytes) -> None:
        for r in self.routers:
            try:
                await r.put_value(key, value)
            except Exception as e:
                logger.debug(f"TieredRouting put_value failed on {r}: {type(e)} {e}")

    async def close(self) -> None:
        for r in self.routers:
            if hasattr(r, "close"):
                await r.close()
