DEFAULT_ECLIPSE_CONFIG = {
    "honest_nodes": 10,
    "malicious_nodes": 3,
    "attack_intensity": 0.5,
}

# Multiple attack configurations for testing different scenarios
ECLIPSE_ATTACK_CONFIGS = [
    {
        "name": "Low Intensity Attack",
        "honest_nodes": 10,
        "malicious_nodes": 2,
        "attack_intensity": 0.3,
    },
    {
        "name": "Medium Intensity Attack",
        "honest_nodes": 10,
        "malicious_nodes": 3,
        "attack_intensity": 0.5,
    },
    {
        "name": "High Intensity Attack",
        "honest_nodes": 10,
        "malicious_nodes": 5,
        "attack_intensity": 0.8,
    },
    {
        "name": "Overwhelming Attack",
        "honest_nodes": 10,
        "malicious_nodes": 8,
        "attack_intensity": 1.0,
    },
    {
        "name": "Large Network Low Attack",
        "honest_nodes": 50,
        "malicious_nodes": 5,
        "attack_intensity": 0.2,
    },
    {
        "name": "Large Network High Attack",
        "honest_nodes": 50,
        "malicious_nodes": 15,
        "attack_intensity": 0.7,
    },
    {
        "name": "Small Network Extreme Attack",
        "honest_nodes": 5,
        "malicious_nodes": 4,
        "attack_intensity": 0.9,
    },
    {
        "name": "Balanced Network Moderate Attack",
        "honest_nodes": 20,
        "malicious_nodes": 6,
        "attack_intensity": 0.4,
    },
    {
        "name": "Enterprise Scale Low Threat",
        "honest_nodes": 100,
        "malicious_nodes": 10,
        "attack_intensity": 0.15,
    },
    {
        "name": "Enterprise Scale High Threat",
        "honest_nodes": 100,
        "malicious_nodes": 25,
        "attack_intensity": 0.6,
    },
]

# Additional attack types for future expansion
ATTACK_TYPES = [
    "eclipse",
    "sybil",
    "flooding",
    "protocol_exploit",
    "bootnode_poisoning",
    "long_range_fork",
    "invalid_block",
    "finality_stall",
]

# Network topologies for different testing scenarios
NETWORK_TOPOLOGIES = ["random", "structured", "clustered", "mesh"]

# Extended Threat Model Configurations (Polkadot/Smoldot-inspired)

# Bootnode Poisoning Configurations
BOOTNODE_POISONING_CONFIGS = [
    {
        "name": "Light Bootnode Compromise",
        "honest_nodes": 10,
        "malicious_bootnodes": 1,
        "attack_intensity": 0.5,
        "fallback_peers": 2,
    },
    {
        "name": "Moderate Bootnode Compromise",
        "honest_nodes": 10,
        "malicious_bootnodes": 2,
        "attack_intensity": 0.7,
        "fallback_peers": 1,
    },
    {
        "name": "Complete Bootnode Compromise",
        "honest_nodes": 15,
        "malicious_bootnodes": 3,
        "attack_intensity": 0.9,
        "fallback_peers": 0,
    },
    {
        "name": "Large Network Bootnode Attack",
        "honest_nodes": 50,
        "malicious_bootnodes": 5,
        "attack_intensity": 0.8,
        "fallback_peers": 3,
    },
]

# Long-Range Fork Configurations
LONG_RANGE_FORK_CONFIGS = [
    {
        "name": "Short Offline Period",
        "online_peers": 10,
        "offline_peers": 3,
        "avg_offline_duration": 1800.0,  # 30 minutes
        "fork_attackers": 1,
        "attack_intensity": 0.5,
    },
    {
        "name": "Medium Offline Period",
        "online_peers": 10,
        "offline_peers": 5,
        "avg_offline_duration": 7200.0,  # 2 hours
        "fork_attackers": 2,
        "attack_intensity": 0.7,
    },
    {
        "name": "Extended Offline Period",
        "online_peers": 8,
        "offline_peers": 7,
        "avg_offline_duration": 86400.0,  # 1 day
        "fork_attackers": 3,
        "attack_intensity": 0.9,
    },
    {
        "name": "Critical Offline Period",
        "online_peers": 5,
        "offline_peers": 10,
        "avg_offline_duration": 604800.0,  # 7 days
        "fork_attackers": 4,
        "attack_intensity": 1.0,
    },
]

# Invalid Block Propagation Configurations
INVALID_BLOCK_CONFIGS = [
    {
        "name": "Light Client Vulnerability Test",
        "full_nodes": 5,
        "light_clients": 10,
        "malicious_validators": 1,
        "attack_intensity": 0.6,
        "finality_delay": 10.0,
    },
    {
        "name": "Balanced Network Test",
        "full_nodes": 10,
        "light_clients": 10,
        "malicious_validators": 2,
        "attack_intensity": 0.7,
        "finality_delay": 12.0,
    },
    {
        "name": "Light Client Dominated",
        "full_nodes": 5,
        "light_clients": 20,
        "malicious_validators": 3,
        "attack_intensity": 0.8,
        "finality_delay": 15.0,
    },
    {
        "name": "High Validator Corruption",
        "full_nodes": 10,
        "light_clients": 15,
        "malicious_validators": 5,
        "attack_intensity": 0.9,
        "finality_delay": 20.0,
    },
]

# Finality Stall Configurations
FINALITY_STALL_CONFIGS = [
    {
        "name": "Short Stall Low Block Rate",
        "light_clients": 10,
        "full_nodes": 5,
        "attackers": 1,
        "attack_intensity": 0.6,
        "stall_duration": 15.0,
        "block_production_rate": 1.0,
        "memory_limit_mb": 300.0,
        "pruning_enabled": True,
    },
    {
        "name": "Medium Stall Medium Block Rate",
        "light_clients": 10,
        "full_nodes": 5,
        "attackers": 2,
        "attack_intensity": 0.7,
        "stall_duration": 30.0,
        "block_production_rate": 2.0,
        "memory_limit_mb": 250.0,
        "pruning_enabled": True,
    },
    {
        "name": "Extended Stall High Block Rate",
        "light_clients": 15,
        "full_nodes": 5,
        "attackers": 2,
        "attack_intensity": 0.9,
        "stall_duration": 60.0,
        "block_production_rate": 3.0,
        "memory_limit_mb": 200.0,
        "pruning_enabled": True,
    },
    {
        "name": "Critical Stall Without Pruning",
        "light_clients": 10,
        "full_nodes": 3,
        "attackers": 3,
        "attack_intensity": 1.0,
        "stall_duration": 45.0,
        "block_production_rate": 3.0,
        "memory_limit_mb": 150.0,
        "pruning_enabled": False,
    },
]
