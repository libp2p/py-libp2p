import logging
import time
from typing import Dict, List, Optional, Any
import base58

# Try to import libp2p components, fall back to mock types if not available
try:
    from libp2p.abc import IHost
    from libp2p.kad_dht.kad_dht import KadDHT
    from libp2p.kad_dht.utils import create_key_from_binary
    from libp2p.peer.id import ID
    from libp2p.peer.peerinfo import PeerInfo
    from multiaddr import Multiaddr
    LIBP2P_AVAILABLE = True
except ImportError:
    LIBP2P_AVAILABLE = False
    # Mock types for standalone operation
    class IHost:
        def get_id(self): pass
        def get_addrs(self): pass
        def get_connected_peers(self): return []
    
    class KadDHT:
        def __init__(self, host, mode): pass
        async def put_value(self, key, value): pass
        async def get_value(self, key): pass
    
    def create_key_from_binary(data):
        import hashlib
        return hashlib.sha256(data).digest()
    
    class ID:
        def __init__(self, peer_id): self.peer_id = peer_id
        def to_string(self): return self.peer_id
        def pretty(self): return self.peer_id
    
    class PeerInfo:
        def __init__(self, peer_id, addrs): pass
    
    class Multiaddr:
        def __init__(self, addr): self.addr = addr
        def __str__(self): return self.addr

try:
    from .hybrid_discovery_service import HybridDiscoveryService, ServiceMetadata
    from .ethereum_contract import EthereumServiceRegistry, ServiceRegistration
except ImportError:
    from hybrid_discovery_service import HybridDiscoveryService, ServiceMetadata
    from ethereum_contract import EthereumServiceRegistry, ServiceRegistration

logger = logging.getLogger("hybrid_resolver")

class HybridServiceResolver:
    def __init__(
        self,
        host: IHost,
        dht: KadDHT,
        discovery_service: HybridDiscoveryService,
        ethereum_registry: EthereumServiceRegistry
    ):
        self.host = host
        self.dht = dht
        self.discovery_service = discovery_service
        self.ethereum_registry = ethereum_registry
        self.cache: Dict[str, ServiceMetadata] = {}
        self.cache_ttl = 300  # 5 minutes
        
    async def resolve_service(
        self,
        service_type: str,
        service_name: str,
        peer_id: str,
        use_cache: bool = True
    ) -> Optional[ServiceMetadata]:
        cache_key = f"{service_type}:{service_name}:{peer_id}"
        
        if use_cache and cache_key in self.cache:
            cached_metadata = self.cache[cache_key]
            if time.time() - cached_metadata.timestamp < self.cache_ttl:
                logger.info(f"Returning cached service metadata for {service_name}")
                return cached_metadata
        
        try:
            service_id = self.discovery_service._generate_service_id(service_type, service_name)
            
            on_chain_service = self.ethereum_registry.get_service(service_id)
            if not on_chain_service:
                logger.warning(f"Service {service_name} not found on-chain")
                return None
            
            if not on_chain_service.active:
                logger.warning(f"Service {service_name} is inactive on-chain")
                return None
            
            dht_key_bytes = base58.b58decode(on_chain_service.dht_key)
            metadata_bytes = await self.dht.get_value(dht_key_bytes)
            
            if not metadata_bytes:
                logger.warning(f"Service metadata not found in DHT for {service_name}")
                return None
            
            metadata = self.discovery_service._deserialize_metadata(metadata_bytes)
            
            if time.time() - metadata.timestamp > metadata.ttl:
                logger.warning(f"Service metadata expired for {service_name}")
                return None
            
            self.cache[cache_key] = metadata
            logger.info(f"Successfully resolved service {service_name} via hybrid discovery")
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to resolve service {service_name}: {e}")
            return None
    
    async def resolve_services_by_type(self, service_type: str, use_cache: bool = True) -> List[ServiceMetadata]:
        try:
            on_chain_services = self.ethereum_registry.get_services_by_type(service_type)
            resolved_services = []
            
            for on_chain_service in on_chain_services:
                if not on_chain_service.active:
                    continue
                
                try:
                    dht_key_bytes = base58.b58decode(on_chain_service.dht_key)
                    metadata_bytes = await self.dht.get_value(dht_key_bytes)
                    
                    if metadata_bytes:
                        metadata = self.discovery_service._deserialize_metadata(metadata_bytes)
                        
                        if time.time() - metadata.timestamp <= metadata.ttl:
                            resolved_services.append(metadata)
                            
                            if use_cache:
                                cache_key = f"{metadata.service_type}:{metadata.service_name}:{metadata.peer_id}"
                                self.cache[cache_key] = metadata
                        else:
                            logger.warning(f"Service metadata expired for {on_chain_service.service_name}")
                    else:
                        logger.warning(f"Service metadata not found in DHT for {on_chain_service.service_name}")
                        
                except Exception as e:
                    logger.error(f"Failed to resolve service {on_chain_service.service_name}: {e}")
                    continue
            
            logger.info(f"Resolved {len(resolved_services)} services of type {service_type}")
            return resolved_services
            
        except Exception as e:
            logger.error(f"Failed to resolve services by type {service_type}: {e}")
            return []
    
    async def resolve_all_services(self, use_cache: bool = True) -> Dict[str, List[ServiceMetadata]]:
        try:
            on_chain_services = self.ethereum_registry.get_all_services()
            services_by_type: Dict[str, List[ServiceMetadata]] = {}
            
            for on_chain_service in on_chain_services:
                if not on_chain_service.active:
                    continue
                
                try:
                    dht_key_bytes = base58.b58decode(on_chain_service.dht_key)
                    metadata_bytes = await self.dht.get_value(dht_key_bytes)
                    
                    if metadata_bytes:
                        metadata = self.discovery_service._deserialize_metadata(metadata_bytes)
                        
                        if time.time() - metadata.timestamp <= metadata.ttl:
                            if metadata.service_type not in services_by_type:
                                services_by_type[metadata.service_type] = []
                            services_by_type[metadata.service_type].append(metadata)
                            
                            if use_cache:
                                cache_key = f"{metadata.service_type}:{metadata.service_name}:{metadata.peer_id}"
                                self.cache[cache_key] = metadata
                        else:
                            logger.warning(f"Service metadata expired for {on_chain_service.service_name}")
                    else:
                        logger.warning(f"Service metadata not found in DHT for {on_chain_service.service_name}")
                        
                except Exception as e:
                    logger.error(f"Failed to resolve service {on_chain_service.service_name}: {e}")
                    continue
            
            logger.info(f"Resolved services across {len(services_by_type)} service types")
            return services_by_type
            
        except Exception as e:
            logger.error(f"Failed to resolve all services: {e}")
            return {}
    
    async def connect_to_service(self, metadata: ServiceMetadata) -> bool:
        try:
            peer_id = ID.from_string(metadata.peer_id)
            addrs = [Multiaddr(addr) for addr in metadata.addresses]
            
            peer_info = PeerInfo(peer_id, addrs)
            self.host.get_peerstore().add_addrs(peer_id, addrs, 3600)
            
            await self.host.connect(peer_info)
            logger.info(f"Connected to service {metadata.service_name} at peer {peer_id.pretty()}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to service {metadata.service_name}: {e}")
            return False
    
    async def discover_and_connect(
        self,
        service_type: str,
        service_name: str,
        peer_id: str
    ) -> Optional[ServiceMetadata]:
        metadata = await self.resolve_service(service_type, service_name, peer_id)
        
        if metadata:
            success = await self.connect_to_service(metadata)
            if success:
                return metadata
            else:
                logger.error(f"Failed to connect to resolved service {service_name}")
                return None
        else:
            logger.warning(f"Could not resolve service {service_name}")
            return None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        return {
            "cache_size": len(self.cache),
            "cache_ttl": self.cache_ttl,
            "cached_services": list(self.cache.keys())
        }
    
    def clear_cache(self) -> None:
        self.cache.clear()
        logger.info("Service resolution cache cleared")
    
    def set_cache_ttl(self, ttl: int) -> None:
        self.cache_ttl = ttl
        logger.info(f"Cache TTL set to {ttl} seconds")
    
    async def health_check(self) -> Dict[str, Any]:
        try:
            on_chain_services = self.ethereum_registry.get_all_services()
            dht_accessible = True
            
            if LIBP2P_AVAILABLE:
                test_key = create_key_from_binary(b"health_check")
            else:
                import hashlib
                test_key = hashlib.sha256(b"health_check").digest()
            try:
                await self.dht.get_value(test_key)
            except Exception:
                dht_accessible = False
            
            return {
                "on_chain_services_count": len(on_chain_services),
                "dht_accessible": dht_accessible,
                "cache_size": len(self.cache),
                "host_connected_peers": len(self.host.get_connected_peers()),
                "timestamp": int(time.time())
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "error": str(e),
                "timestamp": int(time.time())
            }
