#!/usr/bin/env python3
"""
Demonstration script to test address validation utilities
"""

from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
)


def main():
    print("=== Address Validation Utilities Demo ===\n")

    port = 8000

    # Test available interfaces
    print(f"Available interfaces for port {port}:")
    interfaces = get_available_interfaces(port)
    for i, addr in enumerate(interfaces, 1):
        print(f"  {i}. {addr}")

    print()

    # Test optimal binding address
    print(f"Optimal binding address for port {port}:")
    optimal = get_optimal_binding_address(port)
    print(f"  -> {optimal}")

    print()

    # Check for wildcard addresses
    wildcard_found = any("0.0.0.0" in str(addr) for addr in interfaces)
    print(f"Wildcard addresses found: {wildcard_found}")

    # Check for loopback addresses
    loopback_found = any("127.0.0.1" in str(addr) for addr in interfaces)
    print(f"Loopback addresses found: {loopback_found}")

    # Check if optimal is wildcard
    optimal_is_wildcard = "0.0.0.0" in str(optimal)
    print(f"Optimal address is wildcard: {optimal_is_wildcard}")

    print()

    if not wildcard_found and loopback_found and not optimal_is_wildcard:
        print("✅ All checks passed! Address validation is working correctly.")
        print("   - No wildcard addresses")
        print("   - Loopback always available")
        print("   - Optimal address is secure")
    else:
        print("❌ Some checks failed. Address validation needs attention.")

    print()

    # Test different protocols
    print("Testing different protocols:")
    for protocol in ["tcp", "udp"]:
        addr = get_optimal_binding_address(port, protocol=protocol)
        print(f"  {protocol.upper()}: {addr}")
        if "0.0.0.0" in str(addr):
            print(f"    ⚠️  Warning: {protocol} returned wildcard address")


if __name__ == "__main__":
    main()
