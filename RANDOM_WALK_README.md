# Random Walk Module Implementation for py-libp2p

This document describes the implementation of the Random Walk module for py-libp2p, which provides automatic peer discovery and routing table maintenance for Kademlia DHT nodes.

## Overview

The Random Walk module implements a peer discovery mechanism similar to go-libp2p's implementation. It performs random walks through the DHT network to discover new peers and maintain routing table health through periodic refreshes.

## Architecture

### Components

1. **RandomWalk** (`libp2p/routing_table/random_walk.py`)
   - Generates random peer IDs for discovery queries
   - Performs FIND_NODE queries to discover peers
   - Validates discovered peers

2. **RTRefreshManager** (`libp2p/routing_table/rt_refresh_manager.py`)
   - Manages periodic routing table refreshes
   - Coordinates random walk operations
   - Handles peer liveness checks and eviction

3. **Configuration** (`libp2p/routing_table/config.py`)
   - Centralized configuration constants
   - Compatible with go-libp2p defaults

4. **Exceptions** (`libp2p/routing_table/exceptions.py`)
   - Custom exception types for error handling

### Integration Flow

```
Kademlia DHT → RT Refresh Manager → Random Walk → Peer Discovery → Routing Table Update
```

## Features

### Random Walk
- Generates cryptographically secure random 256-bit peer IDs
- Performs concurrent random walks for efficiency
- Validates discovered peers before adding to routing table
- Removes duplicate peers automatically

### RT Refresh Manager
- Automatic periodic routing table refreshes
- Manual refresh triggering capability
- Peer liveness checking and eviction
- Configurable refresh intervals and thresholds

### Go-libp2p Compatibility
- Uses same random peer ID generation (256-bit)
- Compatible refresh logic and timing
- Same DHT protocol messages
- Maintains protocol compatibility

## Configuration

### Default Settings (matching go-libp2p)

```python
# Timing constants
PEER_PING_TIMEOUT = 10.0  # seconds
REFRESH_QUERY_TIMEOUT = 60.0  # seconds  
REFRESH_INTERVAL = 300.0  # 5 minutes
SUCCESSFUL_OUTBOUND_QUERY_GRACE_PERIOD = 60.0  # 1 minute

# Routing table thresholds
MIN_RT_REFRESH_THRESHOLD = 4  # Minimum peers before triggering refresh
MAX_N_BOOTSTRAPPERS = 2  # Maximum bootstrap peers to try

# Random walk specific
RANDOM_WALK_CONCURRENCY = 3  # Number of concurrent random walks
RANDOM_WALK_ENABLED = True  # Enable automatic random walks
```

### Customization

All settings can be customized when creating the RTRefreshManager:

```python
rt_refresh_manager = RTRefreshManager(
    host=host,
    routing_table=routing_table,
    local_peer_id=local_peer_id,
    query_function=query_function,
    enable_auto_refresh=True,
    refresh_interval=300.0,  # Custom interval
    min_refresh_threshold=4,  # Custom threshold
)
```

## Usage

### Basic Integration with Kademlia DHT

The Random Walk module is automatically integrated with the Kademlia DHT. When you create a KadDHT instance, it will automatically:

1. Create and configure the RT Refresh Manager
2. Start automatic random walks (if enabled)
3. Maintain routing table health

```python
from libp2p.kad_dht.kad_dht import KadDHT, DHTMode

# Create DHT - Random Walk is automatically enabled
dht = KadDHT(host=host, mode=DHTMode.SERVER)

# Start DHT - this also starts the RT Refresh Manager
await dht.run()
```

### Manual Refresh Triggering

You can manually trigger routing table refreshes:

```python
# Trigger refresh respecting timing constraints
await dht.trigger_routing_table_refresh()

# Force refresh regardless of timing
await dht.trigger_routing_table_refresh(force=True)
```

### Standalone Usage

You can also use the Random Walk module independently:

```python
from libp2p.routing_table.random_walk import RandomWalk

# Create standalone Random Walk instance
random_walk = RandomWalk(
    host=host,
    local_peer_id=local_peer_id,
    query_function=query_function,
    validation_function=validation_function,
    ping_function=ping_function,
)

# Perform single random walk
peers = await random_walk.perform_random_walk()

# Perform concurrent random walks
peers = await random_walk.run_concurrent_random_walks(count=3)
```

## API Reference

### RandomWalk Class

#### Constructor
```python
RandomWalk(
    host: IHost,
    local_peer_id: ID,
    query_function: Callable[[str], AsyncContextManager[List[PeerInfo]]],
    validation_function: Optional[Callable[[PeerInfo], AsyncContextManager[bool]]] = None,
    ping_function: Optional[Callable[[ID], AsyncContextManager[bool]]] = None,
)
```

#### Methods

- `generate_random_peer_id() -> str`: Generate random 256-bit peer ID
- `validate_peer(peer_info: PeerInfo) -> bool`: Validate discovered peer
- `perform_random_walk() -> List[PeerInfo]`: Perform single random walk
- `run_concurrent_random_walks(count: int = 3) -> List[PeerInfo]`: Run concurrent walks

### RTRefreshManager Class

#### Constructor
```python
RTRefreshManager(
    host: IHost,
    routing_table: RoutingTableProtocol,
    local_peer_id: ID,
    query_function: Callable[[str], AsyncContextManager[List[PeerInfo]]],
    ping_function: Optional[Callable[[ID], AsyncContextManager[bool]]] = None,
    validation_function: Optional[Callable[[PeerInfo], AsyncContextManager[bool]]] = None,
    enable_auto_refresh: bool = True,
    refresh_interval: float = 300.0,
    min_refresh_threshold: int = 4,
)
```

#### Methods

- `start() -> None`: Start the refresh manager
- `stop() -> None`: Stop the refresh manager  
- `trigger_refresh(force: bool = False) -> None`: Trigger manual refresh
- `add_refresh_done_callback(callback: Callable[[], None]) -> None`: Add completion callback
- `remove_refresh_done_callback(callback: Callable[[], None]) -> None`: Remove callback

## Error Handling

The module provides custom exception types:

- `RoutingTableRefreshError`: Base exception for refresh operations
- `RandomWalkError`: Specific to random walk failures
- `PeerValidationError`: Peer validation failures

All operations include proper error handling and logging:

```python
try:
    peers = await random_walk.perform_random_walk()
except RandomWalkError as e:
    logger.error(f"Random walk failed: {e}")
    # Handle gracefully
```

## Logging

The module uses structured logging with appropriate log levels:

- `INFO`: Important operations and results
- `DEBUG`: Detailed operation progress
- `WARNING`: Recoverable issues
- `ERROR`: Operation failures

Log names:
- `libp2p.routing_table.random_walk`
- `libp2p.routing_table.rt_refresh_manager`

## Performance Considerations

### Concurrency
- Uses trio nurseries for concurrent operations
- Default 3 concurrent random walks
- Configurable concurrency levels

### Rate Limiting
- Respects configured timeouts
- Implements backoff for failed operations
- Prevents resource exhaustion

### Memory Management
- Removes duplicate peers automatically
- Evicts unresponsive peers
- Bounded routing table size

## Testing

### Unit Tests
Run the basic test suite:

```bash
python3 tests/routing_table/test_random_walk.py
```

### Demo
Run the comprehensive demonstration:

```bash
python3 examples/random_walk_demo.py
```

The demo shows:
- Random peer ID generation
- Single and concurrent random walks
- RT Refresh Manager operation
- Peer discovery and validation

## Dependencies

The implementation uses only standard dependencies:
- Standard Python libraries (secrets, time, logging)
- Existing py-libp2p modules
- trio for async operations
- typing for type hints

No additional external dependencies are required.

## Compatibility

### Protocol Compatibility
- Compatible with go-libp2p DHT nodes
- Uses standard Kademlia DHT messages
- Same peer ID format (256-bit)
- Compatible refresh behavior

### Version Compatibility
- Python 3.8+
- py-libp2p 0.1.0+
- trio 0.20.0+

## Future Enhancements

Potential improvements for future versions:

1. **Metrics and Monitoring**
   - Add Prometheus metrics
   - Performance statistics
   - Health monitoring

2. **Advanced Configuration**
   - Per-network configuration profiles
   - Dynamic parameter adjustment
   - A/B testing capabilities

3. **Optimization**
   - Smart peer selection algorithms
   - Adaptive refresh intervals
   - Network condition awareness

4. **Additional Features**
   - Peer reputation tracking
   - Geographic diversity
   - Network topology awareness

## Contributing

When contributing to the Random Walk module:

1. Follow existing code style and patterns
2. Add comprehensive tests for new features
3. Update documentation for API changes
4. Ensure go-libp2p compatibility
5. Include performance considerations

## License

This implementation follows the same license as py-libp2p (MIT/Apache 2.0).
