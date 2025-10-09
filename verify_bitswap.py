#!/usr/bin/env python3
"""
Quick verification script for Bitswap implementation.
This script verifies that the implementation is correctly structured.
"""

from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")

    try:
        # Test main module
        from libp2p.bitswap import (  # noqa: F401
            BitswapClient,
            BitswapError,
            BlockNotFoundError,
            BlockStore,
            BlockTooLargeError,
            InvalidBlockError,
            InvalidCIDError,
            MemoryBlockStore,
            MessageTooLargeError,
            TimeoutError,
            config,
        )
        print("✓ Main module imports successful")

        # Test submodules
        from libp2p.bitswap.block_store import BlockStore as BS  # noqa: F401
        from libp2p.bitswap.client import BitswapClient as BC  # noqa: F401
        from libp2p.bitswap.messages import create_message  # noqa: F401
        from libp2p.bitswap.pb.bitswap_pb2 import Message  # noqa: F401
        print("✓ Submodule imports successful")

        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False


def test_config():
    """Test configuration constants."""
    print("\nTesting configuration...")

    try:
        from libp2p.bitswap import config

        assert hasattr(config, 'BITSWAP_PROTOCOL_V100')
        assert config.BITSWAP_PROTOCOL_V100 == "/ipfs/bitswap/1.0.0"
        assert hasattr(config, 'MAX_MESSAGE_SIZE')
        assert config.MAX_MESSAGE_SIZE == 4 * 1024 * 1024
        assert hasattr(config, 'MAX_BLOCK_SIZE')
        assert config.MAX_BLOCK_SIZE == 2 * 1024 * 1024

        print("✓ Configuration constants verified")
        return True
    except (ImportError, AssertionError) as e:
        print(f"✗ Configuration test failed: {e}")
        return False


def test_block_store():
    """Test block store functionality."""
    print("\nTesting block store...")

    try:
        import trio

        from libp2p.bitswap import MemoryBlockStore

        async def test():
            store = MemoryBlockStore()

            # Test put and get
            cid = b"test_cid_123"
            data = b"test data"
            await store.put_block(cid, data)

            retrieved = await store.get_block(cid)
            assert retrieved == data, "Retrieved data doesn't match"

            # Test has_block
            has_it = await store.has_block(cid)
            assert has_it is True, "Block should exist"

            # Test delete
            await store.delete_block(cid)
            has_it = await store.has_block(cid)
            assert has_it is False, "Block should be deleted"

            return True

        # Use trio to run the test
        result = trio.run(test)

        if result:
            print("✓ Block store functionality verified")
            return True
    except Exception as e:
        print(f"✗ Block store test failed: {e}")
        return False


def test_message_creation():
    """Test message creation helpers."""
    print("\nTesting message creation...")

    try:
        from libp2p.bitswap.messages import (
            create_message,
            create_wantlist_entry,
            create_wantlist_message,
        )

        # Create wantlist entry
        entry = create_wantlist_entry(b"cid123", priority=5)
        assert entry.block == b"cid123"
        assert entry.priority == 5
        assert entry.cancel is False

        # Create wantlist message
        msg = create_wantlist_message([entry], full=True)
        assert len(msg.wantlist.entries) == 1
        assert msg.wantlist.full is True

        # Create combined message with blocks
        msg = create_message(wantlist_entries=[entry], blocks_v100=[b"data"])
        assert len(msg.wantlist.entries) == 1
        assert len(msg.blocks) == 1

        print("✓ Message creation verified")
        return True
    except Exception as e:
        print(f"✗ Message creation test failed: {e}")
        return False


def test_protobuf():
    """Test protobuf message serialization."""
    print("\nTesting protobuf...")

    try:
        from libp2p.bitswap.pb.bitswap_pb2 import Message

        # Create message
        msg = Message()
        entry = msg.wantlist.entries.add()
        entry.block = b"test_cid"
        entry.priority = 1
        msg.blocks.append(b"block_data")

        # Serialize and deserialize
        serialized = msg.SerializeToString()
        assert len(serialized) > 0

        msg2 = Message()
        msg2.ParseFromString(serialized)

        assert len(msg2.wantlist.entries) == 1
        assert msg2.wantlist.entries[0].block == b"test_cid"
        assert len(msg2.blocks) == 1

        print("✓ Protobuf serialization verified")
        return True
    except Exception as e:
        print(f"✗ Protobuf test failed: {e}")
        return False


def test_file_structure():
    """Test that all expected files exist."""
    print("\nTesting file structure...")

    base = Path(__file__).parent
    expected_files = [
        # Core implementation
        "libp2p/bitswap/__init__.py",
        "libp2p/bitswap/block_store.py",
        "libp2p/bitswap/cid.py",
        "libp2p/bitswap/client.py",
        "libp2p/bitswap/config.py",
        "libp2p/bitswap/errors.py",
        "libp2p/bitswap/messages.py",
        # Protocol buffers
        "libp2p/bitswap/pb/__init__.py",
        "libp2p/bitswap/pb/bitswap.proto",
        "libp2p/bitswap/pb/bitswap_pb2.py",
        "libp2p/bitswap/pb/bitswap_pb2.pyi",
        # Examples
        "examples/bitswap/__init__.py",
        "examples/bitswap/bitswap.py",
        "examples/bitswap/comprehensive_demo.py",
        "examples/bitswap/COMPREHENSIVE_DEMO.md",
        "examples/bitswap/README.md",
        # Documentation
        "BITSWAP.md",
        "docs/libp2p.bitswap.rst",
        "docs/examples.bitswap.rst",
    ]

    all_exist = True
    for file_path in expected_files:
        full_path = base / file_path
        if full_path.exists():
            print(f"  ✓ {file_path}")
        else:
            print(f"  ✗ {file_path} - NOT FOUND")
            all_exist = False

    if all_exist:
        print("✓ All expected files exist")
        return True
    else:
        print("✗ Some files are missing")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Bitswap Implementation Verification")
    print("=" * 60)

    tests = [
        ("File Structure", test_file_structure),
        ("Imports", test_imports),
        ("Configuration", test_config),
        ("Block Store", test_block_store),
        ("Message Creation", test_message_creation),
        ("Protobuf", test_protobuf),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{name:20s}: {status}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed! Bitswap implementation is ready.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
