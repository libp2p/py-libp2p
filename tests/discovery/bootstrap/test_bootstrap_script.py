#!/usr/bin/env python3
"""
Simple test script to verify bootstrap functionality
"""

import os
import sys

# Add the parent directory to sys.path so we can import libp2p
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from libp2p.discovery.bootstrap.utils import (
    parse_bootstrap_peer_info,
    validate_bootstrap_addresses,
)


def test_bootstrap_validation():
    """Test bootstrap address validation"""
    print("🧪 Testing Bootstrap Address Validation")

    # Test addresses
    test_addresses = [
        "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SznbYGzPwp8qDrq",
        "/ip4/127.0.0.1/tcp/8000/p2p/QmTest123",  # This might be invalid peer ID format
        "invalid-address",
        "/ip4/192.168.1.1/tcp/4001",  # Missing p2p component
        "/ip6/2604:a880:1:20::203:d001/tcp/4001/p2p/QmSoLPppuBtQSGwKDZT2M73ULpjvfd3aZ6ha4oFGL1KrGM",
    ]

    print(f"📋 Testing {len(test_addresses)} addresses:")
    for addr in test_addresses:
        print(f"   • {addr}")

    # Validate addresses
    valid_addresses = validate_bootstrap_addresses(test_addresses)

    print(f"\n✅ Valid addresses ({len(valid_addresses)}):")
    for addr in valid_addresses:
        print(f"   • {addr}")

        # Try to parse peer info
        peer_info = parse_bootstrap_peer_info(addr)
        if peer_info:
            print(f"     → Peer ID: {peer_info.peer_id}")
            print(f"     → Addresses: {[str(a) for a in peer_info.addrs]}")
        else:
            print("     → Failed to parse peer info")

    return len(valid_addresses) > 0


if __name__ == "__main__":
    print("=" * 60)
    print("Bootstrap Module Test")
    print("=" * 60)

    try:
        success = test_bootstrap_validation()
        if success:
            print("\n🎉 Bootstrap module test completed successfully!")
        else:
            print("\n❌ No valid bootstrap addresses found")
            sys.exit(1)
    except Exception as e:
        print(f"\n💥 Test failed with error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
