#!/usr/bin/env python

import asyncio
import logging
import secrets
import time
from unittest.mock import Mock, AsyncMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p import new_host
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode

from hybrid_discovery_service import HybridDiscoveryService, ServiceMetadata
from mock_ethereum import MockEthereumServiceRegistry, ServiceRegistration
from hybrid_resolver import HybridServiceResolver

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_hybrid_discovery")

# Use the actual MockEthereumServiceRegistry from mock_ethereum.py

async def test_hybrid_discovery():
    logger.info("🧪 Testing Hybrid Discovery System")
    
    # Create mock host and DHT
    key_pair = create_new_key_pair(secrets.token_bytes(32))
    host = new_host(key_pair=key_pair)
    
    # Mock DHT
    mock_dht = Mock()
    mock_dht.put_value = AsyncMock()
    mock_dht.get_value = AsyncMock()
    
    # Create services
    discovery_service = HybridDiscoveryService(host, mock_dht)
    ethereum_registry = MockEthereumServiceRegistry()
    resolver = HybridServiceResolver(host, mock_dht, discovery_service, ethereum_registry)
    
    # Test 1: Register a service
    logger.info("Test 1: Registering a service...")
    
    service_pointer = await discovery_service.register_service(
        service_type="dex",
        service_name="TestDEX",
        endpoints={"api": "https://api.testdex.com"},
        capabilities=["swap", "liquidity"],
        version="1.0.0"
    )
    
    assert service_pointer is not None
    assert service_pointer.service_type == "dex"
    assert service_pointer.service_name == "TestDEX"
    logger.info("✅ Service registration successful")
    
    # Test 2: Register on-chain
    logger.info("Test 2: Registering service on-chain...")
    
    tx_hash = ethereum_registry.register_service(
        service_pointer.service_id,
        "dex",
        "TestDEX",
        service_pointer.dht_key,
        service_pointer.peer_id
    )
    
    assert tx_hash is not None
    logger.info("✅ On-chain registration successful")
    
    # Test 3: Mock DHT response for discovery
    logger.info("Test 3: Testing service discovery...")
    
    # Create mock metadata
    mock_metadata = ServiceMetadata(
        service_type="dex",
        service_name="TestDEX",
        peer_id=host.get_id().to_string(),
        addresses=[str(addr) for addr in host.get_addrs()],
        endpoints={"api": "https://api.testdex.com"},
        capabilities=["swap", "liquidity"],
        version="1.0.0",
        timestamp=int(time.time()),
        ttl=3600
    )
    
    # Mock DHT get_value response
    mock_dht.get_value.return_value = discovery_service._serialize_metadata(mock_metadata)
    
    # Test service resolution
    resolved_service = await resolver.resolve_service("dex", "TestDEX", host.get_id().to_string())
    
    assert resolved_service is not None
    assert resolved_service.service_name == "TestDEX"
    assert "swap" in resolved_service.capabilities
    logger.info("✅ Service discovery successful")
    
    # Test 4: Test service discovery by type
    logger.info("Test 4: Testing discovery by service type...")
    
    services = await resolver.resolve_services_by_type("dex")
    assert len(services) == 1
    assert services[0].service_name == "TestDEX"
    logger.info("✅ Service discovery by type successful")
    
    # Test 5: Test caching
    logger.info("Test 5: Testing caching...")
    
    cache_stats = resolver.get_cache_stats()
    assert cache_stats["cache_size"] > 0
    logger.info("✅ Caching working correctly")
    
    # Test 6: Test health check
    logger.info("Test 6: Testing health check...")
    
    health = await resolver.health_check()
    assert "on_chain_services_count" in health
    assert "dht_accessible" in health
    logger.info("✅ Health check successful")
    
    logger.info("🎉 All tests passed!")

async def test_gas_optimization():
    logger.info("💰 Testing Gas Optimization")
    
    # Mock registry for gas estimation
    mock_registry = MockEthereumServiceRegistry()
    
    # Test gas estimates
    gas_estimate = mock_registry.get_gas_estimate_register(
        "test_service_id",
        "dex",
        "TestDEX",
        "test_dht_key",
        "test_peer_id"
    )
    
    assert gas_estimate == 200000
    logger.info(f"✅ Gas estimate: {gas_estimate} gas units")
    
    # Compare with traditional on-chain storage
    traditional_gas = 500000  # Estimated for full metadata storage
    savings = ((traditional_gas - gas_estimate) / traditional_gas) * 100
    
    logger.info(f"💰 Gas savings: {savings:.1f}%")
    assert savings > 50  # Should save at least 50%
    logger.info("✅ Gas optimization verified")

async def main():
    try:
        await test_hybrid_discovery()
        await test_gas_optimization()
        logger.info("🚀 All tests completed successfully!")
    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
