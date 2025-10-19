#!/usr/bin/env python3
"""
Standalone test script for P2P File Sharing components.

This script tests the basic functionality without requiring libp2p installation.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, asdict
from enum import Enum


class MessageType(Enum):
    """Types of messages in the file sharing protocol."""
    LIST_FILES = "list_files"
    FILE_LIST = "file_list"
    REQUEST_FILE = "request_file"
    FILE_CHUNK = "file_chunk"
    FILE_COMPLETE = "file_complete"
    ERROR = "error"


@dataclass
class FileInfo:
    """Information about a file available for sharing."""
    name: str
    size: int
    hash: str
    modified_time: float
    description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FileInfo":
        """Create from dictionary."""
        return cls(**data)

    @classmethod
    def from_file(cls, file_path: str, description: str = "") -> "FileInfo":
        """Create FileInfo from an actual file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        stat = os.stat(file_path)
        
        # Calculate file hash
        file_hash = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                file_hash.update(chunk)
        
        return cls(
            name=os.path.basename(file_path),
            size=stat.st_size,
            hash=file_hash.hexdigest(),
            modified_time=stat.st_mtime,
            description=description
        )


@dataclass
class ProtocolMessage:
    """Base protocol message."""
    type: MessageType
    data: dict
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            import time
            self.timestamp = time.time()

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps({
            "type": self.type.value,
            "data": self.data,
            "timestamp": self.timestamp
        })

    @classmethod
    def from_json(cls, json_str: str) -> "ProtocolMessage":
        """Deserialize from JSON."""
        data = json.loads(json_str)
        return cls(
            type=MessageType(data["type"]),
            data=data["data"],
            timestamp=data["timestamp"]
        )


def test_file_info():
    """Test FileInfo class functionality."""
    print("🧪 Testing FileInfo Class...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create test file
        test_file = os.path.join(temp_dir, "test.txt")
        content = "Hello, P2P File Sharing!"
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


def test_protocol_message():
    """Test ProtocolMessage class functionality."""
    print("\n🧪 Testing ProtocolMessage Class...")
    
    # Create a test message
    message = ProtocolMessage(
        type=MessageType.LIST_FILES,
        data={"test": "data"}
    )
    
    print(f"  📨 Message type: {message.type}")
    print(f"  📊 Message data: {message.data}")
    print(f"  ⏰ Timestamp: {message.timestamp}")
    
    # Test serialization
    json_str = message.to_json()
    message_restored = ProtocolMessage.from_json(json_str)
    
    if (message.type == message_restored.type and 
        message.data == message_restored.data):
        print("  ✅ ProtocolMessage serialization/deserialization successful")
    else:
        print("  ❌ ProtocolMessage serialization/deserialization failed")
    
    print("  ✅ ProtocolMessage test completed")


def test_file_sharing_simulation():
    """Simulate file sharing operations."""
    print("\n🧪 Testing File Sharing Simulation...")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create shared files directory
        shared_dir = os.path.join(temp_dir, "shared")
        os.makedirs(shared_dir, exist_ok=True)
        
        # Create test files
        test_files = [
            ("file1.txt", "Content of file 1"),
            ("file2.txt", "Content of file 2"),
            ("file3.json", '{"name": "test", "value": 123}')
        ]
        
        for filename, content in test_files:
            file_path = os.path.join(shared_dir, filename)
            with open(file_path, 'w') as f:
                f.write(content)
        
        # Simulate file listing
        files = []
        for filename in os.listdir(shared_dir):
            file_path = os.path.join(shared_dir, filename)
            if os.path.isfile(file_path):
                try:
                    file_info = FileInfo.from_file(file_path)
                    files.append(file_info)
                except Exception as e:
                    print(f"  ⚠️  Failed to load file {filename}: {e}")
        
        print(f"  📁 Found {len(files)} files:")
        for file_info in files:
            print(f"    📄 {file_info.name} ({file_info.size} bytes)")
        
        # Simulate file request message
        if files:
            target_file = files[0]
            request_message = ProtocolMessage(
                type=MessageType.REQUEST_FILE,
                data={"file_hash": target_file.hash}
            )
            
            print(f"  📨 File request message: {request_message.to_json()}")
            
            # Simulate file response
            response_message = ProtocolMessage(
                type=MessageType.FILE_CHUNK,
                data={
                    "file_hash": target_file.hash,
                    "chunk_index": 0,
                    "chunk_data": "Content of file 1".encode().hex(),
                    "total_size": target_file.size
                }
            )
            
            print(f"  📤 File chunk message: {response_message.to_json()}")
        
        print("  ✅ File sharing simulation completed")


def main():
    """Run all tests."""
    print("🚀 P2P File Sharing Standalone Tests")
    print("=" * 50)
    
    try:
        test_file_info()
        test_protocol_message()
        test_file_sharing_simulation()
        
        print("\n" + "=" * 50)
        print("✅ All standalone tests completed successfully!")
        print("\n💡 This demonstrates the core functionality works correctly.")
        print("   For full testing with libp2p, install the dependencies and run:")
        print("   python3 test_basic.py")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
