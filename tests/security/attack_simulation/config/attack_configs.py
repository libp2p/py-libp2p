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
ATTACK_TYPES = ["eclipse", "sybil", "flooding", "protocol_exploit"]

# Network topologies for different testing scenarios
NETWORK_TOPOLOGIES = ["random", "structured", "clustered", "mesh"]
