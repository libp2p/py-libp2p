import logging
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

try:
    from .ethereum_contract import ServiceRegistration
except ImportError:
    from ethereum_contract import ServiceRegistration

logger = logging.getLogger("mock_ethereum")

class MockEthereumServiceRegistry:
    """
    Mock Ethereum service registry for demonstration purposes.
    This simulates the behavior of a real Ethereum contract without requiring
    web3 dependencies or actual blockchain interaction.
    """
    
    def __init__(self):
        self.services: Dict[str, ServiceRegistration] = {}
        self.registered_services_count = 0
    
    def register_service(
        self,
        service_id: str,
        service_type: str,
        service_name: str,
        dht_key: str,
        peer_id: str
    ) -> str:
        """Mock service registration - returns a fake transaction hash."""
        self.services[service_id] = ServiceRegistration(
            service_id=service_id,
            service_type=service_type,
            service_name=service_name,
            dht_key=dht_key,
            peer_id=peer_id,
            owner="0x1234567890123456789012345678901234567890",
            timestamp=int(time.time()),
            active=True
        )
        self.registered_services_count += 1
        
        fake_tx_hash = f"0x{'mock_tx_' + service_id[:8]:0<64}"
        logger.info(f"Mock: Registered service {service_name} with fake tx: {fake_tx_hash}")
        return fake_tx_hash
    
    def unregister_service(self, service_id: str) -> str:
        """Mock service unregistration."""
        if service_id in self.services:
            self.services[service_id].active = False
            fake_tx_hash = f"0x{'mock_unreg_' + service_id[:8]:0<64}"
            logger.info(f"Mock: Unregistered service {service_id} with fake tx: {fake_tx_hash}")
            return fake_tx_hash
        return None
    
    def get_service(self, service_id: str) -> Optional[ServiceRegistration]:
        """Get a service by ID."""
        service = self.services.get(service_id)
        return service if service and service.active else None
    
    def get_services_by_type(self, service_type: str) -> List[ServiceRegistration]:
        """Get all active services of a specific type."""
        return [
            service for service in self.services.values()
            if service.service_type == service_type and service.active
        ]
    
    def get_all_services(self) -> List[ServiceRegistration]:
        """Get all active services."""
        return [
            service for service in self.services.values()
            if service.active
        ]
    
    def get_gas_estimate_register(
        self,
        service_id: str,
        service_type: str,
        service_name: str,
        dht_key: str,
        peer_id: str
    ) -> int:
        """Mock gas estimation - returns a realistic estimate."""
        return 200000
    
    def get_gas_estimate_unregister(self, service_id: str) -> int:
        """Mock gas estimation for unregistration."""
        return 100000
    
    def get_stats(self) -> Dict[str, int]:
        """Get registry statistics."""
        return {
            "total_services": len(self.services),
            "active_services": len([s for s in self.services.values() if s.active]),
            "registered_count": self.registered_services_count
        }
