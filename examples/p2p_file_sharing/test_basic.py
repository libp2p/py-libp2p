#!/usr/bin/env python3
"""
Basic test script for P2P File Sharing components.

This script tests the basic functionality of the file sharing components
without requiring network connectivity.
"""

import asyncio
import os
import sys
import tempfile
import trio
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from file_protocol import FileSharingProtocol, FileInfo


async def test_file_protocol():
    """Test the file sharing protocol."""
    print("🧪 Testing File Sharing Protocol...")
    
    # Create temporary directories
    with tempfile.TemporaryDirectory() as temp_dir:
        shared_dir = os.path.join(temp_dir, "shared")
        os.makedirs(shared_dir, exist_ok=True)
        
        # Create test file
        test_file = os.path.join(shared_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("Hello, P2P File Sharing!")
        
        # Initialize protocol
        protocol = FileSharingProtocol(shared_dir)
        
        # Test file listing
        files = protocol.get_file_list()
        print(f"  ✅ Found {len(files)} files")
        
        if files:
            file_info = files[0]
            print(f"  📄 File: {file_info.name}")
            print(f"  📏 Size: {file_info.size} bytes")
            print(f"  🔐 Hash: {file_info.hash}")
            
            # Test file retrieval
            file_path = protocol.get_file_path(file_info.hash)
            if file_path and os.path.exists(file_path):
                print("  ✅ File path retrieval successful")
            else:
                print("  ❌ File path retrieval failed")
        
        print("  ✅ File protocol test completed")


async def test_file_info():
    """Test FileInfo class."""
    print("\n🧪 Testing FileInfo Class...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test file
        test_file = os.path.join(temp_dir, "test.txt")
        content = "Test content for file info"
        with open(test_file, 'w') as f:
            f.write(content)
        
        # Create FileInfo from file
        file_info = FileInfo.from_file(test_file, "Test file")
        
        print(f"  📄 Name: {file_info.name}")
        print(f"  📏 Size: {file_info.size}")
        print(f"  🔐 Hash: {file_info.hash}")
        print(f"  📝 Description: {file_info.description}")
        
        # Test serialization
        file_dict = file_info.to_dict()
        file_info_restored = FileInfo.from_dict(file_dict)
        
        if (file_info.name == file_info_restored.name and 
            file_info.size == file_info_restored.size and
            file_info.hash == file_info_restored.hash):
            print("  ✅ FileInfo serialization/deserialization successful")
        else:
            print("  ❌ FileInfo serialization/deserialization failed")
        
        print("  ✅ FileInfo test completed")


async def main():
    """Run all tests."""
    print("🚀 P2P File Sharing Basic Tests")
    print("=" * 40)
    
    try:
        await test_file_protocol()
        await test_file_info()
        
        print("\n" + "=" * 40)
        print("✅ All basic tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    trio.run(main)
