"""
File sharing protocol implementation for P2P file sharing.

This module defines the protocol messages and handlers for file sharing operations
including file listing, file requests, and file transfers.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream

logger = logging.getLogger("libp2p.file_sharing.protocol")

# Protocol ID for file sharing
FILE_SHARING_PROTOCOL = TProtocol("/p2p/file-sharing/1.0.0")

# Maximum chunk size for file transfers (1MB)
MAX_CHUNK_SIZE = 1024 * 1024

# Maximum file size (100MB)
MAX_FILE_SIZE = 100 * 1024 * 1024


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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileInfo":
        """Create from dictionary."""
        return cls(**data)

    @classmethod
    def from_file(cls, file_path: str, description: str = "") -> "FileInfo":
        """Create FileInfo from an actual file."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        stat = os.stat(file_path)
        if stat.st_size > MAX_FILE_SIZE:
            raise ValueError(f"File too large: {stat.st_size} bytes (max: {MAX_FILE_SIZE})")
        
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
    data: Dict[str, Any]
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
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


class FileSharingProtocol:
    """Protocol handler for file sharing operations."""

    def __init__(self, shared_files_dir: str = "./shared_files"):
        """
        Initialize the file sharing protocol.

        Args:
            shared_files_dir: Directory containing files to share
        """
        self.shared_files_dir = shared_files_dir
        self.shared_files: Dict[str, FileInfo] = {}
        self.active_transfers: Dict[str, Dict[str, Any]] = {}
        
        # Ensure shared files directory exists
        os.makedirs(shared_files_dir, exist_ok=True)
        
        # Load existing files
        self._refresh_file_list()

    def _refresh_file_list(self) -> None:
        """Refresh the list of available files."""
        self.shared_files.clear()
        
        if not os.path.exists(self.shared_files_dir):
            return
        
        for filename in os.listdir(self.shared_files_dir):
            file_path = os.path.join(self.shared_files_dir, filename)
            if os.path.isfile(file_path):
                try:
                    file_info = FileInfo.from_file(file_path)
                    self.shared_files[file_info.hash] = file_info
                except Exception as e:
                    logger.warning(f"Failed to load file {filename}: {e}")

    def get_file_list(self) -> List[FileInfo]:
        """Get list of available files."""
        self._refresh_file_list()
        return list(self.shared_files.values())

    def get_file_by_hash(self, file_hash: str) -> Optional[FileInfo]:
        """Get file info by hash."""
        return self.shared_files.get(file_hash)

    def get_file_path(self, file_hash: str) -> Optional[str]:
        """Get file path by hash."""
        file_info = self.shared_files.get(file_hash)
        if file_info:
            return os.path.join(self.shared_files_dir, file_info.name)
        return None

    async def handle_stream(self, stream: INetStream) -> None:
        """
        Handle incoming file sharing protocol stream.

        Args:
            stream: The network stream to handle
        """
        try:
            peer_id = stream.muxed_conn.peer_id
            logger.info(f"Handling file sharing stream from peer: {peer_id}")
            
            # Read the initial message
            message_data = await stream.read()
            if not message_data:
                logger.warning("Empty message received")
                return
            
            message = ProtocolMessage.from_json(message_data.decode('utf-8'))
            logger.debug(f"Received message type: {message.type}")
            
            # Handle different message types
            if message.type == MessageType.LIST_FILES:
                await self._handle_list_files(stream)
            elif message.type == MessageType.REQUEST_FILE:
                await self._handle_request_file(stream, message.data)
            else:
                await self._send_error(stream, f"Unknown message type: {message.type}")
                
        except Exception as e:
            logger.error(f"Error handling file sharing stream: {e}")
            try:
                await self._send_error(stream, str(e))
            except:
                pass
        finally:
            await stream.close()

    async def _handle_list_files(self, stream: INetStream) -> None:
        """Handle file list request."""
        files = self.get_file_list()
        file_data = [file_info.to_dict() for file_info in files]
        
        response = ProtocolMessage(
            type=MessageType.FILE_LIST,
            data={"files": file_data}
        )
        
        await stream.write(response.to_json().encode('utf-8'))
        logger.info(f"Sent file list with {len(files)} files")

    async def _handle_request_file(self, stream: INetStream, data: Dict[str, Any]) -> None:
        """Handle file request."""
        file_hash = data.get("file_hash")
        if not file_hash:
            await self._send_error(stream, "Missing file_hash in request")
            return
        
        file_path = self.get_file_path(file_hash)
        if not file_path or not os.path.exists(file_path):
            await self._send_error(stream, f"File not found: {file_hash}")
            return
        
        file_info = self.get_file_by_hash(file_hash)
        if not file_info:
            await self._send_error(stream, f"File info not found: {file_hash}")
            return
        
        logger.info(f"Sending file: {file_info.name} ({file_info.size} bytes)")
        
        # Send file in chunks
        with open(file_path, 'rb') as f:
            chunk_index = 0
            while True:
                chunk = f.read(MAX_CHUNK_SIZE)
                if not chunk:
                    break
                
                chunk_message = ProtocolMessage(
                    type=MessageType.FILE_CHUNK,
                    data={
                        "file_hash": file_hash,
                        "chunk_index": chunk_index,
                        "chunk_data": chunk.hex(),
                        "total_size": file_info.size
                    }
                )
                
                await stream.write(chunk_message.to_json().encode('utf-8'))
                chunk_index += 1
                
                # Small delay to prevent overwhelming the network
                import trio
                await trio.sleep(0.001)
        
        # Send completion message
        complete_message = ProtocolMessage(
            type=MessageType.FILE_COMPLETE,
            data={
                "file_hash": file_hash,
                "total_chunks": chunk_index
            }
        )
        
        await stream.write(complete_message.to_json().encode('utf-8'))
        logger.info(f"File transfer completed: {file_info.name}")

    async def _send_error(self, stream: INetStream, error_message: str) -> None:
        """Send error message."""
        error_msg = ProtocolMessage(
            type=MessageType.ERROR,
            data={"error": error_message}
        )
        
        await stream.write(error_msg.to_json().encode('utf-8'))
        logger.error(f"Sent error: {error_message}")

    async def request_file_list(self, stream: INetStream) -> List[FileInfo]:
        """Request file list from remote peer."""
        request = ProtocolMessage(
            type=MessageType.LIST_FILES,
            data={}
        )
        
        await stream.write(request.to_json().encode('utf-8'))
        
        # Read response
        response_data = await stream.read()
        response = ProtocolMessage.from_json(response_data.decode('utf-8'))
        
        if response.type == MessageType.FILE_LIST:
            files_data = response.data.get("files", [])
            return [FileInfo.from_dict(file_data) for file_data in files_data]
        elif response.type == MessageType.ERROR:
            raise Exception(f"Remote error: {response.data.get('error', 'Unknown error')}")
        else:
            raise Exception(f"Unexpected response type: {response.type}")

    async def download_file(self, stream: INetStream, file_hash: str, save_path: str) -> None:
        """Download a file from remote peer."""
        request = ProtocolMessage(
            type=MessageType.REQUEST_FILE,
            data={"file_hash": file_hash}
        )
        
        await stream.write(request.to_json().encode('utf-8'))
        
        # Create download directory if needed
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        with open(save_path, 'wb') as f:
            while True:
                response_data = await stream.read()
                if not response_data:
                    break
                
                response = ProtocolMessage.from_json(response_data.decode('utf-8'))
                
                if response.type == MessageType.FILE_CHUNK:
                    chunk_data = bytes.fromhex(response.data["chunk_data"])
                    f.write(chunk_data)
                    
                elif response.type == MessageType.FILE_COMPLETE:
                    logger.info(f"File download completed: {save_path}")
                    break
                    
                elif response.type == MessageType.ERROR:
                    raise Exception(f"Remote error: {response.data.get('error', 'Unknown error')}")
        
        # Verify file hash
        file_info = FileInfo.from_file(save_path)
        if file_info.hash != file_hash:
            os.remove(save_path)
            raise Exception("File hash verification failed")
