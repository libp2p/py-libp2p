#!/usr/bin/env python

import argparse
import asyncio
import logging
import os
import random
import secrets
import sys
import time
from typing import Dict, List, Optional

import base58
from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.abc import IHost
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.tools.async_service import background_trio_service
from libp2p.tools.utils import info_from_p2p_addr
from libp2p.utils.address_validation import get_available_interfaces, get_optimal_binding_address

from .hybrid_discovery_service import HybridDiscoveryService
from .hybrid_resolver import HybridServiceResolver

# Try to import web3, fall back to mock if not available
try:
    from web3 import Web3
    from .ethereum_contract import EthereumServiceRegistry
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False
    from .mock_ethereum import MockEthereumServiceRegistry as EthereumServiceRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("hybrid_discovery_demo")

class HybridDiscoveryDemo:
    def __init__(self, mode: str, port: int, bootstrap_addrs: List[str], 
                 ethereum_rpc: str, contract_address: str, private_key: str):
        self.mode = mode
        self.port = port
        self.bootstrap_addrs = bootstrap_addrs
        self.ethereum_rpc = ethereum_rpc
        self.contract_address = contract_address
        self.private_key = private_key
        
        self.host: Optional[IHost] = None
        self.dht: Optional[KadDHT] = None
        self.discovery_service: Optional[HybridDiscoveryService] = None
        self.ethereum_registry: Optional[EthereumServiceRegistry] = None
        self.resolver: Optional[HybridServiceResolver] = None
        
    async def setup_ethereum(self):
        try:
            if WEB3_AVAILABLE:
                web3 = Web3(Web3.HTTPProvider(self.ethereum_rpc))
                if not web3.is_connected():
                    logger.warning("Failed to connect to Ethereum RPC, using mock registry")
                    self.ethereum_registry = EthereumServiceRegistry()
                else:
                    self.ethereum_registry = EthereumServiceRegistry(
                        web3, self.contract_address, self.private_key
                    )
                    logger.info(f"Connected to Ethereum at {self.ethereum_rpc}")
            else:
                logger.info("Web3 not available, using mock Ethereum registry")
                self.ethereum_registry = EthereumServiceRegistry()
            
            return True
        except Exception as e:
            logger.warning(f"Failed to setup Ethereum, using mock: {e}")
            self.ethereum_registry = EthereumServiceRegistry()
            return True
    
    async def setup_libp2p(self):
        try:
            if self.port <= 0:
                self.port = random.randint(10000, 60000)
            
            dht_mode = DHTMode.SERVER if self.mode == "server" else DHTMode.CLIENT
            
            key_pair = create_new_key_pair(secrets.token_bytes(32))
            self.host = new_host(key_pair=key_pair)
            
            listen_addrs = get_available_interfaces(self.port)
            
            async with self.host.run(listen_addrs=listen_addrs):
                await self.host.get_peerstore().start_cleanup_task(60)
                
                peer_id = self.host.get_id().pretty()
                all_addrs = self.host.get_addrs()
                
                logger.info("LibP2P host ready, listening on:")
                for addr in all_addrs:
                    logger.info(f"  {addr}")
                
                optimal_addr = get_optimal_binding_address(self.port)
                optimal_addr_with_peer = f"{optimal_addr}/p2p/{self.host.get_id().to_string()}"
                logger.info(f"Connect to this node: {optimal_addr_with_peer}")
                
                await self.connect_to_bootstrap_nodes()
                
                self.dht = KadDHT(self.host, dht_mode)
                
                for peer_id in self.host.get_peerstore().peer_ids():
                    await self.dht.routing_table.add_peer(peer_id)
                
                async with background_trio_service(self.dht):
                    logger.info(f"DHT service started in {dht_mode.value} mode")
                    
                    self.discovery_service = HybridDiscoveryService(self.host, self.dht)
                    self.resolver = HybridServiceResolver(
                        self.host, self.dht, self.discovery_service, self.ethereum_registry
                    )
                    
                    if self.mode == "server":
                        await self.run_server_demo()
                    else:
                        await self.run_client_demo()
                        
        except Exception as e:
            logger.error(f"LibP2P setup failed: {e}")
            raise
    
    async def connect_to_bootstrap_nodes(self):
        for addr in self.bootstrap_addrs:
            try:
                peer_info = info_from_p2p_addr(Multiaddr(addr))
                self.host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 3600)
                await self.host.connect(peer_info)
                logger.info(f"Connected to bootstrap node: {addr}")
            except Exception as e:
                logger.error(f"Failed to connect to bootstrap node {addr}: {e}")
    
    async def run_server_demo(self):
        logger.info("=== Running Server Demo ===")
        
        services = [
            {
                "type": "dex",
                "name": "UniswapV3",
                "endpoints": {
                    "api": "https://api.uniswap.org/v3",
                    "graph": "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"
                },
                "capabilities": ["swap", "liquidity", "price_feed"],
                "version": "3.0.0"
            },
            {
                "type": "storage",
                "name": "IPFS_Storage",
                "endpoints": {
                    "gateway": "https://ipfs.io/ipfs/",
                    "api": "https://api.ipfs.io/api/v0"
                },
                "capabilities": ["store", "retrieve", "pin"],
                "version": "0.12.0"
            },
            {
                "type": "data_provider",
                "name": "Chainlink_Oracles",
                "endpoints": {
                    "api": "https://api.chain.link/v1",
                    "feeds": "https://feeds.chain.link"
                },
                "capabilities": ["price_feeds", "randomness", "automation"],
                "version": "2.0.0"
            }
        ]
        
        registered_services = []
        
        for service_config in services:
            try:
                logger.info(f"Registering service: {service_config['name']}")
                
                service_pointer = await self.discovery_service.register_service(
                    service_type=service_config["type"],
                    service_name=service_config["name"],
                    endpoints=service_config["endpoints"],
                    capabilities=service_config["capabilities"],
                    version=service_config["version"]
                )
                
                gas_estimate = self.ethereum_registry.get_gas_estimate_register(
                    service_pointer.service_id,
                    service_config["type"],
                    service_config["name"],
                    service_pointer.dht_key,
                    service_pointer.peer_id
                )
                
                logger.info(f"Gas estimate for on-chain registration: {gas_estimate}")
                
                tx_hash = self.ethereum_registry.register_service(
                    service_pointer.service_id,
                    service_config["type"],
                    service_config["name"],
                    service_pointer.dht_key,
                    service_pointer.peer_id
                )
                
                if tx_hash:
                    logger.info(f"Service {service_config['name']} registered on-chain: {tx_hash}")
                    registered_services.append(service_config)
                else:
                    logger.error(f"Failed to register {service_config['name']} on-chain")
                    
            except Exception as e:
                logger.error(f"Failed to register service {service_config['name']}: {e}")
        
        logger.info(f"Successfully registered {len(registered_services)} services")
        
        while True:
            try:
                health = await self.resolver.health_check()
                logger.info(f"Health check: {health}")
                
                connected_peers = len(self.host.get_connected_peers())
                registered_count = len(self.discovery_service.get_registered_services())
                
                logger.info(
                    f"Status - Connected peers: {connected_peers}, "
                    f"Registered services: {registered_count}, "
                    f"Cache size: {len(self.resolver.cache)}"
                )
                
                await trio.sleep(30)
                
            except KeyboardInterrupt:
                logger.info("Shutting down server...")
                break
            except Exception as e:
                logger.error(f"Server error: {e}")
                await trio.sleep(5)
    
    async def run_client_demo(self):
        logger.info("=== Running Client Demo ===")
        
        service_types = ["dex", "storage", "data_provider"]
        
        while True:
            try:
                logger.info("Discovering services...")
                
                for service_type in service_types:
                    logger.info(f"Looking for {service_type} services...")
                    
                    services = await self.resolver.resolve_services_by_type(service_type)
                    
                    if services:
                        logger.info(f"Found {len(services)} {service_type} services:")
                        for service in services:
                            logger.info(f"  - {service.service_name} v{service.version}")
                            logger.info(f"    Peer: {service.peer_id}")
                            logger.info(f"    Endpoints: {list(service.endpoints.keys())}")
                            logger.info(f"    Capabilities: {service.capabilities}")
                            
                            if service_type == "dex" and "swap" in service.capabilities:
                                logger.info(f"    🚀 DEX service available for trading!")
                            elif service_type == "storage" and "store" in service.capabilities:
                                logger.info(f"    💾 Storage service available for file storage!")
                            elif service_type == "data_provider" and "price_feeds" in service.capabilities:
                                logger.info(f"    📊 Price feed service available for data!")
                    else:
                        logger.info(f"No {service_type} services found")
                
                cache_stats = self.resolver.get_cache_stats()
                logger.info(f"Cache stats: {cache_stats}")
                
                await trio.sleep(60)
                
            except KeyboardInterrupt:
                logger.info("Shutting down client...")
                break
            except Exception as e:
                logger.error(f"Client error: {e}")
                await trio.sleep(5)
    
    async def run(self):
        logger.info(f"Starting Hybrid Discovery Demo in {self.mode} mode")
        
        if not await self.setup_ethereum():
            logger.error("Failed to setup Ethereum connection")
            return
        
        await self.setup_libp2p()

def parse_args():
    parser = argparse.ArgumentParser(
        description="Hybrid Discovery Demo - On-Chain + Off-Chain Service Discovery"
    )
    parser.add_argument(
        "--mode",
        choices=["server", "client"],
        default="server",
        help="Run as server (register services) or client (discover services)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port to listen on (0 for random)"
    )
    parser.add_argument(
        "--bootstrap",
        type=str,
        nargs="*",
        help="Multiaddrs of bootstrap nodes"
    )
    parser.add_argument(
        "--ethereum-rpc",
        type=str,
        default="http://localhost:8545",
        help="Ethereum RPC endpoint (optional, uses mock if not provided)"
    )
    parser.add_argument(
        "--contract-address",
        type=str,
        help="Service registry contract address (optional, uses mock if not provided)"
    )
    parser.add_argument(
        "--private-key",
        type=str,
        help="Private key for Ethereum transactions (optional, uses mock if not provided)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    return args

def main():
    try:
        args = parse_args()
        
        demo = HybridDiscoveryDemo(
            mode=args.mode,
            port=args.port,
            bootstrap_addrs=args.bootstrap or [],
            ethereum_rpc=args.ethereum_rpc,
            contract_address=args.contract_address,
            private_key=args.private_key
        )
        
        trio.run(demo.run)
        
    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    except Exception as e:
        logger.critical(f"Demo failed: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
