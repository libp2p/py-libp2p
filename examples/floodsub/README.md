# FloodSub Examples

This directory contains examples demonstrating FloodSub functionality in py-libp2p.

## What is FloodSub?

FloodSub is the simplest pubsub routing algorithm in libp2p. It works by flooding messages to all connected peers that are subscribed to a topic. While not as efficient as more advanced algorithms like GossipSub, FloodSub is:

- Simple to understand and implement
- Reliable for small networks
- Useful for testing and development
- A good foundation for learning pubsub concepts

## Examples

### 1. Simple PubSub (`simple_pubsub.py`)

A basic example showing:
- Creating two libp2p hosts with FloodSub
- Connecting them together
- Publishing and subscribing to messages
- Basic message flow

**Run it:**
```bash
python examples/floodsub/simple_pubsub.py
```

**What it does:**
1. Creates two libp2p nodes with FloodSub
2. Connects them
3. One node subscribes to a topic
4. The other node publishes messages
5. Shows received messages

### 2. Multi-Node PubSub (`multi_node_pubsub.py`)

A more advanced example showing:
- Multiple nodes (3) in a network
- Different nodes subscribing to different topics
- Publishing from multiple nodes
- Message flooding across the network

**Run it:**
```bash
python examples/floodsub/multi_node_pubsub.py
```

**What it does:**
1. Creates 3 libp2p nodes with FloodSub
2. Connects them in a chain: A -> B -> C
3. Each node subscribes to different topics
4. Each node publishes messages to different topics
5. Shows how messages flood through the network

## Key Concepts

### Publishing Messages

```python
# Publish a message to a topic
await pubsub.publish("my-topic", b"Hello, FloodSub!")
```

### Subscribing to Topics

```python
# Subscribe to a topic
subscription = await pubsub.subscribe("my-topic")

# Receive messages
message = await subscription.get()
print(f"Received: {message.data.decode()}")
```

### Creating FloodSub

```python
from libp2p.pubsub.floodsub import FloodSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.tools.constants import FLOODSUB_PROTOCOL_ID

# Create FloodSub router
floodsub = FloodSub(protocols=[FLOODSUB_PROTOCOL_ID])

# Create Pubsub with FloodSub
pubsub = Pubsub(
    host=host,
    router=floodsub,
    strict_signing=False,  # Disable for simplicity
)
```

## Interoperability

FloodSub in py-libp2p is designed to be compatible with other libp2p implementations:

- **go-libp2p**: Uses the same FloodSub protocol
- **js-libp2p**: Compatible with js-libp2p FloodSub
- **rust-libp2p**: Should work with rust-libp2p FloodSub

See the interoperability tests in `tests/interop/` for examples of cross-language communication.

## Protocol Details

FloodSub uses the `/floodsub/1.0.0` protocol and follows the libp2p pubsub specification:

1. **Message Format**: Uses protobuf messages as defined in the libp2p pubsub spec
2. **Flooding Algorithm**: Forwards messages to all connected peers subscribed to the topic
3. **Deduplication**: Uses message IDs to prevent duplicate message processing
4. **Subscription Management**: Handles topic subscriptions and unsubscriptions

## Performance Characteristics

- **Latency**: Low (direct flooding)
- **Bandwidth**: High (floods to all peers)
- **Scalability**: Poor (doesn't scale well with network size)
- **Reliability**: High (simple, no complex routing)

## Use Cases

FloodSub is suitable for:
- Small networks (< 100 peers)
- Testing and development
- Learning pubsub concepts
- Networks where simplicity is more important than efficiency
- Bootstrapping more complex pubsub algorithms

## Limitations

- Doesn't scale well with network size
- High bandwidth usage
- No intelligent routing or optimization
- All peers receive all messages for subscribed topics

## Next Steps

After understanding FloodSub, consider exploring:
- **GossipSub**: More efficient pubsub algorithm
- **Custom Validators**: Message validation and filtering
- **Message Signing**: Cryptographic message authentication
- **Topic Discovery**: Finding peers interested in topics
