#!/usr/bin/env python3
"""
Python WebRTC Listener

Creates a WebRTC listener that:
1. Initializes aiortc RTCPeerConnection
2. Creates WebRTC offer
3. Signals readiness via Redis
4. Accepts incoming answer
5. Handles data channel for communication
"""

import asyncio
import json
import logging
import sys
from typing import Optional

import redis.asyncio as redis
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class WebRTCListener:
    """WebRTC Listener for py-libp2p"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.peer_connection: Optional[RTCPeerConnection] = None
        self.data_channel = None
        self.listen_addr = "/ip4/127.0.0.1/udp/8000/webrtc"
        self.peer_id = "QmListener12D3Koo5678901234567890123456"
        
    async def connect_redis(self):
        """Connect to Redis for signaling"""
        try:
            logger.info("Connecting to Redis at %s", self.redis_url)
            self.redis_client = await redis.from_url(self.redis_url)
            await self.redis_client.ping()
            logger.info("✓ Redis connection successful")
        except Exception as e:
            logger.error("✗ Failed to connect to Redis: %s", e)
            raise
    
    async def setup_webrtc(self):
        """Initialize WebRTC peer connection"""
        try:
            logger.info("Setting up WebRTC peer connection...")
            
            # Create RTCConfiguration with STUN servers for NAT traversal
            ice_servers = [
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
                RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
            ]
            config = RTCConfiguration(iceServers=ice_servers)
            
            # Create peer connection
            self.peer_connection = RTCPeerConnection(configuration=config)
            
            logger.info("✓ RTCPeerConnection created")
            
            # Setup event handlers
            @self.peer_connection.on("connectionstatechange")
            async def on_connection_state_change():
                state = self.peer_connection.connectionState
                logger.info("Connection state changed: %s", state)
                if state == "connected":
                    logger.info("✓ WebRTC connection established!")
                elif state == "failed":
                    logger.error("✗ WebRTC connection failed!")
            
            @self.peer_connection.on("iceconnectionstatechange")
            async def on_ice_connection_state_change():
                state = self.peer_connection.iceConnectionState
                logger.info("ICE connection state: %s", state)
            
            @self.peer_connection.on("icegatheringstatechange")
            async def on_ice_gathering_state_change():
                state = self.peer_connection.iceGatheringState
                logger.info("ICE gathering state: %s", state)
            
            @self.peer_connection.on("datachannel")
            async def on_datachannel(channel):
                logger.info("Data channel received: %s", channel.label)
                self.data_channel = channel
                
                @channel.on("message")
                def on_message(message):
                    logger.info("Received message: %s", message)
                    try:
                        channel.send(f"Echo: {message}")
                        logger.info("✓ Echo sent back")
                    except Exception as e:
                        logger.error("✗ Failed to send echo: %s", e)
            
            logger.info("✓ WebRTC setup complete")
            return True
            
        except Exception as e:
            logger.error("✗ Failed to setup WebRTC: %s", e, exc_info=True)
            raise
    
    async def create_offer(self) -> str:
        """Create WebRTC offer and return as JSON string"""
        try:
            logger.info("Creating WebRTC offer...")
            
            # Create offer
            offer = await self.peer_connection.createOffer()
            await self.peer_connection.setLocalDescription(offer)
            
            logger.info("✓ WebRTC offer created")
            logger.info("  SDP length: %d bytes", len(offer.sdp))
            
            # Convert to JSON string
            offer_json = json.dumps({
                "type": offer.type,
                "sdp": offer.sdp
            })
            
            return offer_json
            
        except Exception as e:
            logger.error("✗ Failed to create offer: %s", e, exc_info=True)
            raise
    
    async def handle_answer(self, answer_json: str):
        """Handle WebRTC answer from remote peer"""
        try:
            logger.info("Processing remote answer...")
            
            answer_data = json.loads(answer_json)
            logger.info("  Answer SDP length: %d bytes", len(answer_data["sdp"]))
            
            answer = RTCSessionDescription(
                sdp=answer_data["sdp"],
                type=answer_data["type"]
            )
            
            await self.peer_connection.setRemoteDescription(answer)
            logger.info("✓ Remote answer accepted")
            
        except json.JSONDecodeError as e:
            logger.error("✗ Invalid JSON in answer: %s", e)
            raise
        except Exception as e:
            logger.error("✗ Failed to handle answer: %s", e, exc_info=True)
            raise
    
    async def signal_readiness(self):
        """Signal that listener is ready via Redis"""
        try:
            logger.info("Signaling listener readiness to Redis...")
            
            # Create multiaddr
            multiaddr = f"{self.listen_addr}/p2p/{self.peer_id}"
            
            # Set Redis keys for Python listener
            await self.redis_client.set("interop:webrtc:listener:ready", "1")
            await self.redis_client.set("interop:webrtc:listener:multiaddr", multiaddr)
            
            # Also set the SDP offer for WebRTC peers
            offer_json = await self.redis_client.get("interop:webrtc:listener:offer")
            if offer_json:
                await self.redis_client.set("interop:webrtc:py:listener:offer", offer_json)
            
            logger.info("✓ Listener ready!")
            logger.info("  Multiaddr: %s", multiaddr)
            
        except Exception as e:
            logger.error("✗ Failed to signal readiness: %s", e, exc_info=True)
            raise
    
    async def wait_for_answer(self, timeout: int = 30) -> Optional[str]:
        """Wait for remote answer from Redis"""
        try:
            logger.info("Waiting for remote answer (timeout: %ds)...", timeout)
            
            start = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start) < timeout:
                answer = await self.redis_client.get("interop:webrtc:listener:answer")
                if answer:
                    logger.info("✓ Remote answer received")
                    return answer.decode('utf-8')
                
                await asyncio.sleep(0.1)
            
            logger.error("✗ Timeout waiting for remote answer")
            return None
            
        except Exception as e:
            logger.error("✗ Error waiting for answer: %s", e, exc_info=True)
            return None
    
    async def run(self):
        """Run the listener"""
        logger.info("\n" + "=" * 70)
        logger.info("Starting Python WebRTC Listener")
        logger.info("=" * 70 + "\n")
        
        try:
            # Step 1: Connect to Redis
            await self.connect_redis()
            
            # Step 2: Setup WebRTC
            await self.setup_webrtc()
            
            # Step 3: Create offer
            offer_json = await self.create_offer()
            await self.redis_client.set("interop:webrtc:listener:offer", offer_json)
            
            # Step 4: Signal readiness
            await self.signal_readiness()
            
            # Step 5: Wait for answer
            answer_json = await self.wait_for_answer(timeout=30)
            if answer_json:
                await self.handle_answer(answer_json)
            else:
                logger.warning("No answer received, continuing anyway...")
            
            # Step 6: Keep running
            logger.info("Listener running (will exit after 60 seconds)...")
            await asyncio.sleep(60)
            
            logger.info("✓ Listener completed successfully")
            
        except KeyboardInterrupt:
            logger.info("Listener interrupted by user")
        except Exception as e:
            logger.error("✗ Listener error: %s", e, exc_info=True)
            sys.exit(1)
        finally:
            if self.peer_connection:
                await self.peer_connection.close()
                logger.info("Peer connection closed")
            
            if self.redis_client:
                await self.redis_client.aclose()
                logger.info("Redis connection closed")
            
            logger.info("\n" + "=" * 70)
            logger.info("Listener stopped")
            logger.info("=" * 70 + "\n")


async def main():
    """Main entry point"""
    listener = WebRTCListener()
    await listener.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Listener stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)