import json
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import hashlib
import base58

# Try to import libp2p components, fall back to mock types if not available
try:
    from libp2p.abc import IHost
    from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
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
    
    class KadDHT:
        def __init__(self, host, mode): pass
        async def put_value(self, key, value): pass
        async def get_value(self, key): pass
    
    class DHTMode:
        CLIENT = "CLIENT"
        SERVER = "SERVER"
    
    def create_key_from_binary(data):
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

logger = logging.getLogger("hybrid_discovery")

@dataclass
class ServiceMetadata:
    service_type: str
    service_name: str
    peer_id: str
    addresses: List[str]
    endpoints: Dict[str, str]
    capabilities: List[str]
    version: str
    timestamp: int
    ttl: int = 3600

@dataclass
class ServicePointer:
    service_id: str
    dht_key: str
    peer_id: str
    cid: Optional[str] = None

class HybridDiscoveryService:
    def __init__(self, host: IHost, dht: KadDHT):
        self.host = host
        self.dht = dht
        self.local_peer_id = host.get_id()
        self.registered_services: Dict[str, ServiceMetadata] = {}
        self.service_pointers: Dict[str, ServicePointer] = {}
        
    def _generate_service_id(self, service_type: str, service_name: str) -> str:
        content = f"{service_type}:{service_name}:{self.local_peer_id.to_string()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _generate_dht_key(self, service_id: str) -> bytes:
        if LIBP2P_AVAILABLE:
            return create_key_from_binary(f"service:{service_id}".encode())
        else:
            return hashlib.sha256(f"service:{service_id}".encode()).digest()
    
    def _serialize_metadata(self, metadata: ServiceMetadata) -> bytes:
        return json.dumps(asdict(metadata)).encode()
    
    def _deserialize_metadata(self, data: bytes) -> ServiceMetadata:
        metadata_dict = json.loads(data.decode())
        return ServiceMetadata(**metadata_dict)
    
    async def register_service(
        self,
        service_type: str,
        service_name: str,
        endpoints: Dict[str, str],
        capabilities: List[str],
        version: str = "1.0.0",
        ttl: int = 3600
    ) -> ServicePointer:
        service_id = self._generate_service_id(service_type, service_name)
        dht_key = self._generate_dht_key(service_id)
        
        addresses = [str(addr) for addr in self.host.get_addrs()]
        
        metadata = ServiceMetadata(
            service_type=service_type,
            service_name=service_name,
            peer_id=self.local_peer_id.to_string(),
            addresses=addresses,
            endpoints=endpoints,
            capabilities=capabilities,
            version=version,
            timestamp=int(time.time()),
            ttl=ttl
        )
        
        serialized_metadata = self._serialize_metadata(metadata)
        
        try:
            await self.dht.put_value(dht_key, serialized_metadata)
            logger.info(f"Registered service {service_name} in DHT with key: {base58.b58encode(dht_key).decode()}")
            
            service_pointer = ServicePointer(
                service_id=service_id,
                dht_key=base58.b58encode(dht_key).decode(),
                peer_id=self.local_peer_id.to_string()
            )
            
            self.registered_services[service_id] = metadata
            self.service_pointers[service_id] = service_pointer
            
            return service_pointer
            
        except Exception as e:
            logger.error(f"Failed to register service {service_name}: {e}")
            raise
    
    async def discover_service(self, service_type: str, service_name: str, peer_id: str) -> Optional[ServiceMetadata]:
        service_id = self._generate_service_id(service_type, service_name)
        dht_key = self._generate_dht_key(service_id)
        
        try:
            metadata_bytes = await self.dht.get_value(dht_key)
            if metadata_bytes:
                metadata = self._deserialize_metadata(metadata_bytes)
                
                if time.time() - metadata.timestamp > metadata.ttl:
                    logger.warning(f"Service metadata expired for {service_name}")
                    return None
                
                logger.info(f"Discovered service {service_name} from DHT")
                return metadata
            else:
                logger.warning(f"Service {service_name} not found in DHT")
                return None
                
        except Exception as e:
            logger.error(f"Failed to discover service {service_name}: {e}")
            return None
    
    async def discover_services_by_type(self, service_type: str) -> List[ServiceMetadata]:
        discovered_services = []
        
        for service_id, metadata in self.registered_services.items():
            if metadata.service_type == service_type:
                dht_key = self._generate_dht_key(service_id)
                try:
                    metadata_bytes = await self.dht.get_value(dht_key)
                    if metadata_bytes:
                        fresh_metadata = self._deserialize_metadata(metadata_bytes)
                        if time.time() - fresh_metadata.timestamp <= fresh_metadata.ttl:
                            discovered_services.append(fresh_metadata)
                except Exception as e:
                    logger.error(f"Failed to refresh metadata for service {service_id}: {e}")
        
        return discovered_services
    
    async def update_service_metadata(
        self,
        service_id: str,
        endpoints: Optional[Dict[str, str]] = None,
        capabilities: Optional[List[str]] = None,
        ttl: Optional[int] = None
    ) -> bool:
        if service_id not in self.registered_services:
            logger.error(f"Service {service_id} not registered")
            return False
        
        metadata = self.registered_services[service_id]
        
        if endpoints is not None:
            metadata.endpoints.update(endpoints)
        if capabilities is not None:
            metadata.capabilities = capabilities
        if ttl is not None:
            metadata.ttl = ttl
        
        metadata.timestamp = int(time.time())
        
        dht_key = self._generate_dht_key(service_id)
        serialized_metadata = self._serialize_metadata(metadata)
        
        try:
            await self.dht.put_value(dht_key, serialized_metadata)
            logger.info(f"Updated service metadata for {service_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update service metadata for {service_id}: {e}")
            return False
    
    async def unregister_service(self, service_id: str) -> bool:
        if service_id not in self.registered_services:
            logger.error(f"Service {service_id} not registered")
            return False
        
        dht_key = self._generate_dht_key(service_id)
        
        try:
            await self.dht.put_value(dht_key, b"")
            del self.registered_services[service_id]
            if service_id in self.service_pointers:
                del self.service_pointers[service_id]
            logger.info(f"Unregistered service {service_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to unregister service {service_id}: {e}")
            return False
    
    def get_service_pointer(self, service_id: str) -> Optional[ServicePointer]:
        return self.service_pointers.get(service_id)
    
    def get_registered_services(self) -> Dict[str, ServiceMetadata]:
        return self.registered_services.copy()
    
    async def refresh_all_services(self) -> int:
        refreshed_count = 0
        
        for service_id, metadata in self.registered_services.items():
            try:
                success = await self.update_service_metadata(service_id)
                if success:
                    refreshed_count += 1
            except Exception as e:
                logger.error(f"Failed to refresh service {service_id}: {e}")
        
        logger.info(f"Refreshed {refreshed_count} services")
        return refreshed_count
