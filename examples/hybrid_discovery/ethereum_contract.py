import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

try:
    from web3 import Web3
    from web3.contract import Contract
    from eth_account import Account
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    Web3 = None
    Contract = None
    Account = None

logger = logging.getLogger("ethereum_contract")

@dataclass
class ServiceRegistration:
    service_id: str
    service_type: str
    service_name: str
    dht_key: str
    peer_id: str
    owner: str
    timestamp: int
    active: bool

class EthereumServiceRegistry:
    def __init__(self, web3: Web3, contract_address: str, private_key: str):
        if not WEB3_AVAILABLE:
            raise ImportError("web3 and eth-account are required for Ethereum integration. Install with: pip install web3 eth-account")
        
        self.web3 = web3
        self.contract_address = contract_address
        self.account = Account.from_key(private_key)
        self.contract = self._load_contract()
        
    def _load_contract(self) -> Contract:
        contract_abi = [
            {
                "inputs": [
                    {"name": "serviceId", "type": "string"},
                    {"name": "serviceType", "type": "string"},
                    {"name": "serviceName", "type": "string"},
                    {"name": "dhtKey", "type": "string"},
                    {"name": "peerId", "type": "string"}
                ],
                "name": "registerService",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [{"name": "serviceId", "type": "string"}],
                "name": "unregisterService",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [{"name": "serviceId", "type": "string"}],
                "name": "getService",
                "outputs": [
                    {"name": "serviceType", "type": "string"},
                    {"name": "serviceName", "type": "string"},
                    {"name": "dhtKey", "type": "string"},
                    {"name": "peerId", "type": "string"},
                    {"name": "owner", "type": "address"},
                    {"name": "timestamp", "type": "uint256"},
                    {"name": "active", "type": "bool"}
                ],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [{"name": "serviceType", "type": "string"}],
                "name": "getServicesByType",
                "outputs": [
                    {
                        "components": [
                            {"name": "serviceId", "type": "string"},
                            {"name": "serviceType", "type": "string"},
                            {"name": "serviceName", "type": "string"},
                            {"name": "dhtKey", "type": "string"},
                            {"name": "peerId", "type": "string"},
                            {"name": "owner", "type": "address"},
                            {"name": "timestamp", "type": "uint256"},
                            {"name": "active", "type": "bool"}
                        ],
                        "name": "services",
                        "type": "tuple[]"
                    }
                ],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [],
                "name": "getAllServices",
                "outputs": [
                    {
                        "components": [
                            {"name": "serviceId", "type": "string"},
                            {"name": "serviceType", "type": "string"},
                            {"name": "serviceName", "type": "string"},
                            {"name": "dhtKey", "type": "string"},
                            {"name": "peerId", "type": "string"},
                            {"name": "owner", "type": "address"},
                            {"name": "timestamp", "type": "uint256"},
                            {"name": "active", "type": "bool"}
                        ],
                        "name": "services",
                        "type": "tuple[]"
                    }
                ],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "serviceId", "type": "string"},
                    {"indexed": True, "name": "serviceType", "type": "string"},
                    {"indexed": False, "name": "serviceName", "type": "string"},
                    {"indexed": False, "name": "dhtKey", "type": "string"},
                    {"indexed": False, "name": "peerId", "type": "string"},
                    {"indexed": False, "name": "owner", "type": "address"}
                ],
                "name": "ServiceRegistered",
                "type": "event"
            },
            {
                "anonymous": False,
                "inputs": [
                    {"indexed": True, "name": "serviceId", "type": "string"},
                    {"indexed": False, "name": "owner", "type": "address"}
                ],
                "name": "ServiceUnregistered",
                "type": "event"
            }
        ]
        
        return self.web3.eth.contract(
            address=self.contract_address,
            abi=contract_abi
        )
    
    def register_service(
        self,
        service_id: str,
        service_type: str,
        service_name: str,
        dht_key: str,
        peer_id: str
    ) -> str:
        try:
            tx = self.contract.functions.registerService(
                service_id,
                service_type,
                service_name,
                dht_key,
                peer_id
            ).build_transaction({
                'from': self.account.address,
                'gas': 200000,
                'gasPrice': self.web3.eth.gas_price,
                'nonce': self.web3.eth.get_transaction_count(self.account.address)
            })
            
            signed_tx = self.web3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt.status == 1:
                logger.info(f"Service {service_name} registered on-chain with tx: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Transaction failed for service {service_name}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to register service {service_name} on-chain: {e}")
            return None
    
    def unregister_service(self, service_id: str) -> str:
        try:
            tx = self.contract.functions.unregisterService(service_id).build_transaction({
                'from': self.account.address,
                'gas': 100000,
                'gasPrice': self.web3.eth.gas_price,
                'nonce': self.web3.eth.get_transaction_count(self.account.address)
            })
            
            signed_tx = self.web3.eth.account.sign_transaction(tx, self.account.key)
            tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt.status == 1:
                logger.info(f"Service {service_id} unregistered on-chain with tx: {tx_hash.hex()}")
                return tx_hash.hex()
            else:
                logger.error(f"Transaction failed for unregistering service {service_id}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to unregister service {service_id} on-chain: {e}")
            return None
    
    def get_service(self, service_id: str) -> Optional[ServiceRegistration]:
        try:
            result = self.contract.functions.getService(service_id).call()
            
            if result[6]:  # active field
                return ServiceRegistration(
                    service_id=service_id,
                    service_type=result[0],
                    service_name=result[1],
                    dht_key=result[2],
                    peer_id=result[3],
                    owner=result[4],
                    timestamp=result[5],
                    active=result[6]
                )
            else:
                return None
                
        except Exception as e:
            logger.error(f"Failed to get service {service_id} from contract: {e}")
            return None
    
    def get_services_by_type(self, service_type: str) -> List[ServiceRegistration]:
        try:
            results = self.contract.functions.getServicesByType(service_type).call()
            
            services = []
            for result in results:
                if result[7]:  # active field
                    services.append(ServiceRegistration(
                        service_id=result[0],
                        service_type=result[1],
                        service_name=result[2],
                        dht_key=result[3],
                        peer_id=result[4],
                        owner=result[5],
                        timestamp=result[6],
                        active=result[7]
                    ))
            
            return services
            
        except Exception as e:
            logger.error(f"Failed to get services by type {service_type}: {e}")
            return []
    
    def get_all_services(self) -> List[ServiceRegistration]:
        try:
            results = self.contract.functions.getAllServices().call()
            
            services = []
            for result in results:
                if result[7]:  # active field
                    services.append(ServiceRegistration(
                        service_id=result[0],
                        service_type=result[1],
                        service_name=result[2],
                        dht_key=result[3],
                        peer_id=result[4],
                        owner=result[5],
                        timestamp=result[6],
                        active=result[7]
                    ))
            
            return services
            
        except Exception as e:
            logger.error(f"Failed to get all services: {e}")
            return []
    
    def get_gas_estimate_register(self, service_id: str, service_type: str, service_name: str, dht_key: str, peer_id: str) -> int:
        try:
            gas_estimate = self.contract.functions.registerService(
                service_id, service_type, service_name, dht_key, peer_id
            ).estimate_gas({'from': self.account.address})
            return gas_estimate
        except Exception as e:
            logger.error(f"Failed to estimate gas for registration: {e}")
            return 0
    
    def get_gas_estimate_unregister(self, service_id: str) -> int:
        try:
            gas_estimate = self.contract.functions.unregisterService(service_id).estimate_gas({'from': self.account.address})
            return gas_estimate
        except Exception as e:
            logger.error(f"Failed to estimate gas for unregistration: {e}")
            return 0
