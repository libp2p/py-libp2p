Hybrid Discovery System
========================

The Hybrid Discovery System demonstrates how to combine Ethereum smart contracts with py-libp2p's Kademlia DHT for efficient, cost-effective service discovery in Web3 applications.

Overview
--------

This example showcases a hybrid approach to service discovery that addresses the limitations of both purely on-chain and purely off-chain solutions:

- **On-chain**: Expensive but provides trust and verifiability
- **Off-chain**: Cheap but lacks trust and verifiability
- **Hybrid**: Combines the best of both worlds

Architecture
------------

The system consists of three main components:

1. **Smart Contract**: Stores lightweight service pointers (IDs, DHT keys, peer IDs)
2. **Kademlia DHT**: Stores detailed service metadata (endpoints, capabilities, real-time status)
3. **Hybrid Resolver**: Combines on-chain verification with off-chain data retrieval

Key Features
------------

- **Gas Cost Reduction**: 60-80% savings compared to traditional on-chain storage
- **Real-time Updates**: Off-chain metadata can be updated frequently
- **Trust & Verifiability**: On-chain verification of service ownership
- **Scalable Discovery**: DHT provides O(log n) lookup performance
- **Intelligent Caching**: Reduces redundant lookups

Use Cases
---------

- **DeFi Protocols**: DEX aggregators discovering liquidity sources
- **Data Networks**: IPFS nodes advertising storage capacity
- **Infrastructure Services**: RPC providers advertising endpoints

Getting Started
---------------

1. **Setup Environment**:

   .. code-block:: bash

      cd examples/hybrid_discovery
      ./setup.sh

2. **Deploy Smart Contract**:

   .. code-block:: bash

      cd contracts
      npx hardhat run deploy.js --network localhost

3. **Run Server Demo**:

   .. code-block:: bash

      python demo.py --mode server --contract-address <ADDRESS> --private-key <KEY>

4. **Run Client Demo**:

   .. code-block:: bash

      python demo.py --mode client --bootstrap <SERVER_ADDRESS> --contract-address <ADDRESS> --private-key <KEY>

API Usage
---------

Register a Service
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   service_pointer = await discovery_service.register_service(
       service_type="dex",
       service_name="UniswapV3",
       endpoints={"api": "https://api.uniswap.org/v3"},
       capabilities=["swap", "liquidity"],
       version="3.0.0"
   )

   tx_hash = ethereum_registry.register_service(
       service_pointer.service_id,
       "dex",
       "UniswapV3",
       service_pointer.dht_key,
       service_pointer.peer_id
   )

Discover Services
~~~~~~~~~~~~~~~~~

.. code-block:: python

   services = await resolver.resolve_services_by_type("dex")
   for service in services:
       print(f"Found DEX: {service.service_name}")
       print(f"Capabilities: {service.capabilities}")
       print(f"Endpoints: {service.endpoints}")

Components
----------

HybridDiscoveryService
~~~~~~~~~~~~~~~~~~~~~~

Manages service registration and metadata storage in the Kademlia DHT.

EthereumServiceRegistry
~~~~~~~~~~~~~~~~~~~~~~~

Handles smart contract integration for on-chain service pointer storage.

HybridServiceResolver
~~~~~~~~~~~~~~~~~~~~~

Combines on-chain and off-chain data sources for efficient service discovery.

Demo Features
-------------

Server Demo
~~~~~~~~~~~

- Registers 3 service types: DEX, Storage, Data Provider
- Shows gas cost estimates
- Demonstrates on-chain registration
- Real-time health monitoring

Client Demo
~~~~~~~~~~~

- Discovers services by type
- Shows service capabilities
- Demonstrates caching
- Real-time service resolution

Gas Cost Analysis
-----------------

+------------------+---------------------+---------------+----------+
| Operation        | Traditional On-Chain| Hybrid System | Savings  |
+==================+=====================+===============+==========+
| Register Service | ~500,000 gas        | ~200,000 gas  | 60%      |
+------------------+---------------------+---------------+----------+
| Update Metadata  | ~300,000 gas        | ~50,000 gas   | 83%      |
+------------------+---------------------+---------------+----------+
| Service Discovery| ~100,000 gas        | ~20,000 gas   | 80%      |
+------------------+---------------------+---------------+----------+

Security Features
-----------------

- **On-chain Verification**: Service ownership and registration verified on-chain
- **DHT Integrity**: Metadata signed and verified in DHT
- **TTL Management**: Automatic expiration of stale data
- **Access Control**: Only service owners can update/unregister

Performance Benefits
--------------------

- **Reduced Gas Costs**: 60-80% reduction in transaction costs
- **Real-time Updates**: Off-chain metadata can be updated frequently
- **Scalable Discovery**: DHT provides O(log n) lookup performance
- **Caching**: Intelligent caching reduces redundant lookups

Future Enhancements
-------------------

- Service reputation scoring
- Cross-chain support
- Load balancing
- Service mesh formation

For more details, see the complete implementation in ``examples/hybrid_discovery/``.
