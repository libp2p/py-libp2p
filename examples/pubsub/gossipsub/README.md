# Gossipsub Examples

This directory contains comprehensive examples showcasing the differences between Gossipsub protocol versions and demonstrating advanced features of Gossipsub 2.0.

## Overview

With the recent implementation of Gossipsub 2.0 support in py-libp2p, we now have full protocol version support spanning:

- **Gossipsub 1.0** (`/meshsub/1.0.0`) - Basic mesh-based pubsub
- **Gossipsub 1.1** (`/meshsub/1.1.0`) - Added peer scoring and behavioral penalties
- **Gossipsub 1.2** (`/meshsub/1.2.0`) - Added IDONTWANT message filtering
- **Gossipsub 2.0** (`/meshsub/2.0.0`) - Enhanced security, adaptive gossip, and advanced peer scoring

## Examples

### 1. Version Comparison Demo (`version_comparison.py`)

Side-by-side demonstration of how different Gossipsub versions handle the same network scenarios.

**Features:**
- **Network Simulation**: Creates identical network topologies running different protocol versions
- **Scenario Testing**: Tests various network conditions (high churn, malicious peers, network partitions)
- **Performance Metrics**: Compares message delivery rates, latency, and network overhead
- **Visual Output**: Real-time comparison charts and statistics

**Usage:**
```bash
# Normal operation scenario
python version_comparison.py --scenario normal --duration 60

# High peer churn scenario
python version_comparison.py --scenario high_churn --duration 60

# Spam attack scenario
python version_comparison.py --scenario spam_attack --duration 60

# Network partition scenario
python version_comparison.py --scenario network_partition --duration 60

# Save results to JSON
python version_comparison.py --scenario normal --output results.json
```

**Scenarios:**
- **Normal Operation**: Honest peers publishing regularly
- **High Churn**: Peers joining/leaving frequently
- **Spam Attack**: Some peers sending excessive messages
- **Network Partition**: Network splits and recovers

### 2. Gossipsub 2.0 Feature Showcase (`v2_showcase.py`)

Interactive demonstration of Gossipsub 2.0's advanced features.

**Features:**

#### Peer Scoring Visualization
- **Real-time Score Display**: Shows peer scores (P1-P7 parameters) updating in real-time
- **Score Component Breakdown**: Visualizes individual scoring components
- **Behavioral Penalties**: Demonstrates how misbehavior affects peer scores
- **IP Colocation Penalties**: Shows P7 penalties for peers from same IP ranges
- **Application Scoring**: Demonstrates P6 custom application-defined scoring

#### Adaptive Gossip Demonstration
- **Network Health Monitoring**: Displays network health score calculation
- **Dynamic Parameter Adjustment**: Shows how gossip parameters adapt to network conditions
- **Mesh Quality Maintenance**: Visualizes mesh degree adjustments
- **Opportunistic Grafting**: Demonstrates score-based peer selection

#### Security Features
- **Spam Protection**: Shows rate limiting in action
- **Eclipse Attack Protection**: Demonstrates IP diversity enforcement
- **Equivocation Detection**: Shows detection and penalties for duplicate messages
- **Message Validation**: Demonstrates validation hooks and caching

**Usage:**
```bash
# Interactive mode - explore all features
python v2_showcase.py --mode interactive

# Demo specific features
python v2_showcase.py --mode demo --feature scoring --duration 60
python v2_showcase.py --mode demo --feature adaptive --duration 60
python v2_showcase.py --mode demo --feature security --duration 60

# Save monitoring data
python v2_showcase.py --mode demo --feature scoring --output monitoring.json
```

## Protocol Version Differences

### Gossipsub 1.0 (`/meshsub/1.0.0`)
- Basic mesh-based pubsub protocol
- Simple flooding for message dissemination
- No peer scoring or advanced security features
- Suitable for trusted networks with low adversarial activity

### Gossipsub 1.1 (`/meshsub/1.1.0`)
- **Added Peer Scoring**: P1-P4 topic-scoped parameters
  - P1: Time in mesh
  - P2: First message deliveries
  - P3: Mesh message deliveries
  - P4: Invalid messages penalty
- **Behavioral Penalties**: P5 global behavior penalty
- **Signed Peer Records**: Enhanced peer exchange with signed records
- Better resilience against basic attacks

### Gossipsub 1.2 (`/meshsub/1.2.0`)
- **IDONTWANT Messages**: Peers can signal they don't want specific messages
- **Message Filtering**: Reduces redundant message transmission
- **Improved Efficiency**: Lower bandwidth usage in dense networks
- All v1.1 features included

### Gossipsub 2.0 (`/meshsub/2.0.0`)
- **Enhanced Peer Scoring**: P6 (application-specific) and P7 (IP colocation) parameters
- **Adaptive Gossip**: Dynamic parameter adjustment based on network health
- **Advanced Security Features**:
  - Spam protection with rate limiting
  - Eclipse attack protection via IP diversity
  - Equivocation detection
  - Enhanced message validation
- **Network Health Monitoring**: Continuous assessment of network conditions
- **Opportunistic Grafting**: Score-based peer selection for mesh optimization

## Peer Scoring Parameters (P1-P7)

### Topic-Scoped Parameters (P1-P4)
- **P1 (Time in Mesh)**: Rewards peers for staying in the mesh longer
- **P2 (First Message Deliveries)**: Rewards peers for delivering messages first
- **P3 (Mesh Message Deliveries)**: Rewards peers for consistent message delivery
- **P4 (Invalid Messages)**: Penalizes peers for sending invalid messages

### Global Parameters (P5-P7)
- **P5 (Behavior Penalty)**: General behavioral penalty for misbehavior
- **P6 (Application Score)**: Custom application-defined scoring
- **P7 (IP Colocation)**: Penalizes multiple peers from same IP address

## Security Features in Gossipsub 2.0

### Spam Protection
- Rate limiting per peer per topic
- Configurable message rate thresholds
- Automatic penalty application for rate limit violations

### Eclipse Attack Protection
- Minimum IP diversity requirements in mesh
- Penalties for excessive peers from same IP range
- Mesh diversity monitoring and enforcement

### Equivocation Detection
- Detection of duplicate messages with same sequence number
- Penalties for peers sending conflicting messages
- Message deduplication and validation

### Message Validation
- Configurable validation hooks
- Validation result caching
- Integration with peer scoring system

## Running the Examples

### Basic Usage
```bash
# Navigate to the examples directory
cd examples/pubsub/gossipsub

# Run version comparison
python version_comparison.py --scenario normal

# Run interactive showcase
python v2_showcase.py --mode interactive
```

### Advanced Usage
```bash
# Compare all versions with custom parameters
python version_comparison.py \
    --scenario spam_attack \
    --duration 120 \
    --nodes 8 \
    --output spam_comparison.json \
    --verbose

# Showcase specific features with monitoring
python v2_showcase.py \
    --mode demo \
    --feature security \
    --duration 180 \
    --nodes 10 \
    --output security_monitoring.json \
    --verbose
```

## Understanding the Output

### Version Comparison Results
The comparison demo outputs a detailed table showing:
- **Messages Sent/Received**: Total message counts per version
- **Delivery Rate**: Percentage of messages successfully delivered
- **Average Latency**: Mean message propagation time
- **Spam Blocked**: Number of spam messages filtered (v2.0 only)
- **Churn Events**: Number of peer join/leave events handled

### Feature Showcase Output
The v2.0 showcase provides real-time displays of:
- **Peer Score Breakdown**: Individual P1-P7 component scores
- **Network Health Metrics**: Connectivity and health scores
- **Security Events**: Real-time security event notifications
- **Adaptive Parameters**: Dynamic parameter adjustments

## Network Topologies

Both examples create realistic network topologies:
- **Mesh Connectivity**: Each node connects to 3-4 peers
- **Realistic Latency**: Simulated network delays
- **Diverse Roles**: Honest peers, spammers, validators, attackers
- **Dynamic Behavior**: Peer churn, network partitions, attacks

## Customization

### Adding Custom Scenarios
To add new test scenarios to the version comparison:

```python
async def _run_custom_scenario(self, duration: int):
    """Your custom scenario implementation"""
    # Implement custom network behavior
    pass

# Register in run_scenario method
elif scenario == "custom":
    await self._run_custom_scenario(duration)
```

### Custom Scoring Functions
To implement custom application scoring:

```python
def custom_app_score(peer_id: ID) -> float:
    """Custom application-specific scoring logic"""
    # Implement your scoring logic
    return score

# Use in ScoreParams
score_params = ScoreParams(
    app_specific_score_fn=custom_app_score,
    p6_appl_slack_weight=0.5
)
```

### Custom Validation
To add custom message validation:

```python
def custom_validator(message) -> bool:
    """Custom message validation logic"""
    # Implement validation rules
    return is_valid

# Use in node setup
node._validate_message = custom_validator
```

## Troubleshooting

### Common Issues

1. **Port Conflicts**: If you get port binding errors, the examples will automatically find free ports
2. **Connection Failures**: Ensure firewall allows local connections on the used ports
3. **High CPU Usage**: Reduce the number of nodes or increase sleep intervals for testing
4. **Memory Usage**: Large networks may consume significant memory; monitor usage

### Debug Mode
Enable verbose logging for detailed information:
```bash
python version_comparison.py --scenario normal --verbose
python v2_showcase.py --mode interactive --verbose
```

### Performance Tuning
For better performance in large networks:
- Reduce heartbeat frequency
- Increase message intervals
- Limit concurrent connections
- Use smaller mesh degrees

## References

- [Gossipsub v1.1 Specification](https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v1.1.md)
- [Gossipsub v1.2 Specification](https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v1.2.md)
- [Gossipsub v2.0 Specification](https://github.com/libp2p/specs/blob/master/pubsub/gossipsub/gossipsub-v2.0.md)