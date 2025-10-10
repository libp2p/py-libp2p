"""
Sync Protocol for Browser-to-Backend P2P Communication

This module implements a custom protocol for real-time data synchronization
between browser clients and backend peers using libp2p.
"""

import json
import time
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Union
import logging

logger = logging.getLogger(__name__)


class OperationType(Enum):
    """Types of sync operations."""
    INSERT = "INSERT"
    DELETE = "DELETE"
    UPDATE = "UPDATE"
    MOVE = "MOVE"
    ACK = "ACK"
    HEARTBEAT = "HEARTBEAT"
    PEER_JOIN = "PEER_JOIN"
    PEER_LEAVE = "PEER_LEAVE"


@dataclass
class SyncOperation:
    """Represents a single sync operation."""
    type: str
    operation: OperationType
    id: str
    timestamp: float
    client_id: str
    data: Dict[str, Any]
    parent_id: Optional[str] = None
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "operation": self.operation.value,
            "id": self.id,
            "timestamp": self.timestamp,
            "client_id": self.client_id,
            "data": self.data,
            "parent_id": self.parent_id,
            "version": self.version
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SyncOperation":
        """Create from dictionary."""
        return cls(
            type=data["type"],
            operation=OperationType(data["operation"]),
            id=data["id"],
            timestamp=data["timestamp"],
            client_id=data["client_id"],
            data=data["data"],
            parent_id=data.get("parent_id"),
            version=data.get("version", 1)
        )


class SyncProtocol:
    """
    Protocol for handling real-time data synchronization.
    
    This protocol manages:
    - Operation ordering and conflict resolution
    - Peer discovery and connection management
    - Message acknowledgment and reliability
    - Heartbeat and connection health
    """

    PROTOCOL_ID = "/sync/1.0.0"
    
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.operations: Dict[str, SyncOperation] = {}
        self.pending_acks: Dict[str, float] = {}
        self.connected_peers: Dict[str, float] = {}
        self.last_heartbeat = time.time()
        self.operation_counter = 0

    def create_operation(
        self,
        operation_type: OperationType,
        data: Dict[str, Any],
        parent_id: Optional[str] = None
    ) -> SyncOperation:
        """Create a new sync operation."""
        operation_id = f"{self.client_id}_{self.operation_counter}_{uuid.uuid4().hex[:8]}"
        self.operation_counter += 1
        
        operation = SyncOperation(
            type="operation",
            operation=operation_type,
            id=operation_id,
            timestamp=time.time(),
            client_id=self.client_id,
            data=data,
            parent_id=parent_id
        )
        
        self.operations[operation_id] = operation
        return operation

    def create_ack(self, operation_id: str) -> SyncOperation:
        """Create an acknowledgment for an operation."""
        return SyncOperation(
            type="ack",
            operation=OperationType.ACK,
            id=f"ack_{operation_id}_{self.client_id}",
            timestamp=time.time(),
            client_id=self.client_id,
            data={"ack_for": operation_id}
        )

    def create_heartbeat(self) -> SyncOperation:
        """Create a heartbeat message."""
        return SyncOperation(
            type="heartbeat",
            operation=OperationType.HEARTBEAT,
            id=f"heartbeat_{self.client_id}_{int(time.time())}",
            timestamp=time.time(),
            client_id=self.client_id,
            data={"status": "alive"}
        )

    def create_peer_join(self, peer_info: Dict[str, Any]) -> SyncOperation:
        """Create a peer join notification."""
        return SyncOperation(
            type="peer_event",
            operation=OperationType.PEER_JOIN,
            id=f"join_{self.client_id}_{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            client_id=self.client_id,
            data=peer_info
        )

    def create_peer_leave(self, peer_id: str) -> SyncOperation:
        """Create a peer leave notification."""
        return SyncOperation(
            type="peer_event",
            operation=OperationType.PEER_LEAVE,
            id=f"leave_{self.client_id}_{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            client_id=self.client_id,
            data={"peer_id": peer_id}
        )

    def serialize_operation(self, operation: SyncOperation) -> bytes:
        """Serialize operation to bytes for transmission."""
        return json.dumps(operation.to_dict()).encode('utf-8')

    def deserialize_operation(self, data: bytes) -> SyncOperation:
        """Deserialize operation from bytes."""
        try:
            json_data = json.loads(data.decode('utf-8'))
            return SyncOperation.from_dict(json_data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to deserialize operation: {e}")
            raise

    def should_apply_operation(self, operation: SyncOperation) -> bool:
        """
        Determine if an operation should be applied based on conflict resolution rules.
        
        Current strategy: Last-write-wins with timestamp ordering.
        """
        operation_id = operation.id
        
        # Always apply new operations
        if operation_id not in self.operations:
            return True
            
        existing = self.operations[operation_id]
        
        # Apply if timestamp is newer
        if operation.timestamp > existing.timestamp:
            return True
            
        # Apply if same timestamp but different client (tie-breaker)
        if (operation.timestamp == existing.timestamp and 
            operation.client_id != existing.client_id):
            return operation.client_id > existing.client_id
            
        return False

    def apply_operation(self, operation: SyncOperation) -> bool:
        """
        Apply an operation to the local state.
        Returns True if operation was applied, False if rejected.
        """
        if not self.should_apply_operation(operation):
            logger.debug(f"Rejecting operation {operation.id} due to conflict resolution")
            return False
            
        self.operations[operation.id] = operation
        
        # Handle different operation types
        if operation.operation == OperationType.ACK:
            # Remove from pending acks
            ack_for = operation.data.get("ack_for")
            if ack_for in self.pending_acks:
                del self.pending_acks[ack_for]
                
        elif operation.operation == OperationType.HEARTBEAT:
            # Update peer heartbeat
            self.connected_peers[operation.client_id] = operation.timestamp
            
        elif operation.operation == OperationType.PEER_JOIN:
            # Handle peer join
            peer_id = operation.data.get("peer_id", operation.client_id)
            self.connected_peers[peer_id] = operation.timestamp
            
        elif operation.operation == OperationType.PEER_LEAVE:
            # Handle peer leave
            peer_id = operation.data.get("peer_id")
            if peer_id in self.connected_peers:
                del self.connected_peers[peer_id]
        
        return True

    def get_pending_operations(self, since_timestamp: float = 0) -> List[SyncOperation]:
        """Get operations that occurred after the given timestamp."""
        return [
            op for op in self.operations.values()
            if op.timestamp > since_timestamp and op.client_id != self.client_id
        ]

    def get_operations_for_peer(self, peer_id: str, since_timestamp: float = 0) -> List[SyncOperation]:
        """Get operations from a specific peer since the given timestamp."""
        return [
            op for op in self.operations.values()
            if (op.client_id == peer_id and 
                op.timestamp > since_timestamp and
                op.operation != OperationType.ACK)
        ]

    def cleanup_old_operations(self, max_age_seconds: float = 3600):
        """Remove old operations to prevent memory bloat."""
        current_time = time.time()
        cutoff_time = current_time - max_age_seconds
        
        to_remove = [
            op_id for op_id, op in self.operations.items()
            if op.timestamp < cutoff_time
        ]
        
        for op_id in to_remove:
            del self.operations[op_id]
            
        # Also cleanup old pending acks
        to_remove_acks = [
            ack_id for ack_id, timestamp in self.pending_acks.items()
            if timestamp < cutoff_time
        ]
        
        for ack_id in to_remove_acks:
            del self.pending_acks[ack_id]

    def get_connected_peers(self) -> List[str]:
        """Get list of currently connected peers."""
        current_time = time.time()
        # Remove peers that haven't sent heartbeat in 30 seconds
        active_peers = [
            peer_id for peer_id, last_seen in self.connected_peers.items()
            if current_time - last_seen < 30
        ]
        
        # Update connected_peers to only include active peers
        self.connected_peers = {
            peer_id: self.connected_peers[peer_id] 
            for peer_id in active_peers
        }
        
        return active_peers

    def mark_operation_pending_ack(self, operation_id: str):
        """Mark an operation as pending acknowledgment."""
        self.pending_acks[operation_id] = time.time()

    def get_pending_acks(self) -> List[str]:
        """Get list of operations pending acknowledgment."""
        current_time = time.time()
        # Remove acks older than 10 seconds
        active_acks = [
            ack_id for ack_id, timestamp in self.pending_acks.items()
            if current_time - timestamp < 10
        ]
        
        self.pending_acks = {
            ack_id: self.pending_acks[ack_id] 
            for ack_id in active_acks
        }
        
        return active_acks

    def get_stats(self) -> Dict[str, Any]:
        """Get protocol statistics."""
        return {
            "total_operations": len(self.operations),
            "pending_acks": len(self.pending_acks),
            "connected_peers": len(self.connected_peers),
            "client_id": self.client_id,
            "last_heartbeat": self.last_heartbeat,
            "operation_counter": self.operation_counter
        }
