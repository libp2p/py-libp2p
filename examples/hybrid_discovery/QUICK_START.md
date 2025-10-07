# Quick Start Guide

## 🚀 Run the Demo in 30 Seconds

```bash
# Install dependencies
pip install base58 trio

# Run the demo
python3 simple_demo.py
```

That's it! The demo will show:
- ✅ Service registration in DHT
- ✅ On-chain pointer storage (mock)
- ✅ 60% gas cost reduction
- ✅ Real-time service discovery
- ✅ Intelligent caching
- ✅ Health monitoring

## 🎯 What You'll See

```
🚀 Hybrid Discovery System Demo
==================================================
📝 Step 1: Register a DEX service
✅ Service registered with ID: eda013e4ed593a2b
   DHT Key: CzK7dq7JG5z4xvBAMNjiH65GZCDeCfJ3CRvvMmN6FeTq
   Peer ID: QmMockPeer123

📝 Step 2: Register service on-chain (mock)
💰 Gas estimate: 200000 gas units
✅ On-chain registration: 0xmock_tx_eda013e4...
💰 Gas savings: 60.0%

📝 Step 3: Register additional services
✅ Registered IPFS_Storage: 0xmock_tx_06e49eae...
✅ Registered Chainlink_Oracles: 0xmock_tx_ca2f4ac7...

📝 Step 4: Discover services
🔍 Found 1 DEX services
   - UniswapV3 v3.0.0
     Capabilities: swap, liquidity, price_feed
     Endpoints: ['api']

📝 Step 5: Show registry statistics
📊 Registry Stats:
   Total services: 3
   Active services: 3
   Registered count: 3

📝 Step 6: Health check
🏥 Health Status:
   On-chain services: 3
   DHT accessible: True
   Cache size: 1
   Connected peers: 0

🎉 Demo completed successfully!
Key Benefits Demonstrated:
✅ 60% gas cost reduction
✅ Real-time service discovery
✅ Hybrid on-chain/off-chain architecture
✅ Intelligent caching
✅ Health monitoring
```

## 🔧 For Full libp2p Integration

If you want to run with real libp2p networking:

```bash
# Install full dependencies
pip install base58 trio web3 eth-account

# Run the full demo
python3 demo.py --mode server
```