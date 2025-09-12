import asyncio
import logging
import time
from typing import List

from multiaddr import Multiaddr
from libp2p.network.stream.net_stream_interface import INetStream
from libp2p.protocols.dcutr.pb import holepunch_pb2

DCUTR_PROTOCOL_ID = "/libp2p/dcutr/1.0.0"
logger = logging.getLogger(__name__)

class DCUtRProtocol:
    def __init__(self, host):
        self.host = host
    
    async def handle_inbound_stream(self, stream: INetStream) -> None:
        """Handle incoming DCUtR stream"""
        logger.info("Handling DCUtR stream")
        
        try:
            # Read CONNECT message
            msg = await self._read_message(stream)
            if msg.type == holepunch_pb2.HolePunch.CONNECT:
                await self._handle_connect(stream, msg)
        except Exception as e:
            logger.error(f"DCUtR error: {e}")
        finally:
            await stream.close()
    
    async def upgrade_connection(self, peer_id) -> bool:
        """Start hole punching with peer"""
        logger.info(f"Starting hole punch to {peer_id}")
        
        try:
            # Open DCUtR stream
            stream = await self.host.new_stream(peer_id, [DCUTR_PROTOCOL_ID])
            
            # Send CONNECT message
            connect_msg = holepunch_pb2.HolePunch()
            connect_msg.type = holepunch_pb2.HolePunch.CONNECT
            # Add our addresses (simplified)
            connect_msg.ObsAddrs.append(b"/ip4/127.0.0.1/tcp/0")
            
            await self._write_message(stream, connect_msg)
            
            # Read response
            response = await self._read_message(stream)
            
            # Send SYNC and attempt connections
            sync_msg = holepunch_pb2.HolePunch()
            sync_msg.type = holepunch_pb2.HolePunch.SYNC
            await self._write_message(stream, sync_msg)
            
            logger.info("Hole punch attempt completed")
            return True
            
        except Exception as e:
            logger.error(f"Hole punch failed: {e}")
            return False
    
    async def _handle_connect(self, stream, msg):
        """Handle CONNECT message"""
        # Send our CONNECT response
        response = holepunch_pb2.HolePunch()
        response.type = holepunch_pb2.HolePunch.CONNECT
        response.ObsAddrs.append(b"/ip4/127.0.0.1/tcp/0")
        
        await self._write_message(stream, response)
        
        # Wait for SYNC
        sync_msg = await self._read_message(stream)
        logger.info("Received SYNC, starting hole punch")
    
    async def _read_message(self, stream):
        """Read protobuf message from stream"""
        # Simple message reading (length-prefixed)
        length_bytes = await stream.read(1)
        if not length_bytes:
            raise ValueError("Stream closed")
        
        length = length_bytes
        data = await stream.read(length)
        
        msg = holepunch_pb2.HolePunch()
        msg.ParseFromString(data)
        return msg
    
    async def _write_message(self, stream, msg):
        """Write protobuf message to stream"""
        data = msg.SerializeToString()
        await stream.write(bytes([len(data)]) + data)
