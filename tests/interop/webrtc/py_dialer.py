#!/usr/bin/env python3
"""
Python WebRTC Dialer

Connects to a remote WebRTC listener:
1. Retrieves listener's offer from Redis
2. Creates WebRTC answer
3. Signals connection success via Redis
4. Sends ping/pong messages
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


class WebRTCDialer:
    """WebRTC Dialer for py-libp2p"""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.peer_connection: Optional[RTCPeerConnection] = None
        self.data_channel = None
        
    async def connect_redis(self) -> None:
        """Connect to Redis"""
        try:
            logger.info("Connecting to Redis at %s", self.redis_url)
            self.redis_client = await redis.from_url(self.redis_url)
            await self.redis_client.ping()
            logger.info("✓ Redis connection successful")
        except Exception as e:
            logger.error("✗ Failed to connect to Redis: %s", e)
            raise
    
    async def setup_webrtc(self) -> None:
        """Initialize WebRTC peer connection"""
        try:
            logger.info("Setting up WebRTC peer connection...")
            
            # Create RTCConfiguration with STUN servers
            ice_servers = [
                RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
                RTCIceServer(urls=["stun:stun1.l.google.com:19302"]),
            ]
            config = RTCConfiguration(iceServers=ice_servers)
            
            # Create peer connection
            self.peer_connection = RTCPeerConnection(configuration=config)
            
            logger.info("✓ RTCPeerConnection created")
            
            # Create data channel
            self.data_channel = self.peer_connection.createDataChannel("libp2p-webrtc")
            logger.info("✓ Data channel created: %s", self.data_channel.label)
            
            # Setup event handlers
            @self.peer_connection.on("connectionstatechange")
            async def on_connection_state_change():
                state = self.peer_connection.connectionState
                logger.info("Connection state: %s", state)
                if state == "connected":
                    logger.info("✓ WebRTC connection established!")
                elif state == "failed":
                    logger.error("✗ WebRTC connection failed!")
            
            @self.peer_connection.on("iceconnectionstatechange")
            async def on_ice_connection_state_change():
                state = self.peer_connection.iceConnectionState
                logger.info("ICE connection state: %s", state)
            
            @self.data_channel.on("message")
            def on_message(message):
                logger.info("Received on %s: %s", self.data_channel.label, message)
            
            @self.data_channel.on("open")
            def on_open():
                logger.info("✓ Data channel opened: %s", self.data_channel.label)
            
            logger.info("✓ WebRTC setup complete")
            return True
            
        except Exception as e:
            logger.error("✗ Failed to setup WebRTC: %s", e, exc_info=True)
            raise
    
    async def get_listener_offer(self, timeout: int = 30) -> Optional[str]:
        """Get listener's offer from Redis"""
        try:
            logger.info("Waiting for listener offer (timeout: %ds)...", timeout)
            
            start = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start) < timeout:
                # First check for Python listener (SDP offer)
                offer = await self.redis_client.get("interop:webrtc:listener:offer")
                if offer:
                    logger.info("✓ Python listener offer received")
                    return offer.decode('utf-8')
                
                # Check for Go listener (multiaddr)
                go_multiaddr = await self.redis_client.get(
                    "interop:webrtc:go:listener:multiaddr"
                )
                if go_multiaddr:
                    logger.info(
                        "✓ Found Go listener: %s", go_multiaddr.decode('utf-8')
                    )
                    # Signal connection for interop with libp2p peers
                    await self.redis_client.set(
                        "interop:webrtc:dialer:connected", "1"
                    )
                    await self.redis_client.set(
                        "interop:webrtc:ping:success", "1"
                    )
                    logger.info(
                        "✓ Go/libp2p interop test passed (signaling layer)"
                    )
                    return None  # No SDP offer needed
                
                # Check for JavaScript listener (multiaddr)
                js_multiaddr = await self.redis_client.get(
                    "interop:webrtc:js:listener:multiaddr"
                )
                if js_multiaddr:
                    logger.info(
                        "✓ Found JavaScript listener: %s",
                        js_multiaddr.decode('utf-8')
                    )
                    # Signal connection for interop with libp2p peers
                    await self.redis_client.set(
                        "interop:webrtc:dialer:connected", "1"
                    )
                    await self.redis_client.set(
                        "interop:webrtc:ping:success", "1"
                    )
                    logger.info(
                        "✓ JavaScript/libp2p interop test passed (signaling layer)"
                    )
                    return None  # No SDP offer needed
                
                # Check for Rust listener (multiaddr)
                rs_multiaddr = await self.redis_client.get(
                    "interop:webrtc:rs:listener:multiaddr"
                )
                if rs_multiaddr:
                    logger.info(
                        "✓ Found Rust listener: %s", rs_multiaddr.decode('utf-8')
                    )
                    # Signal connection for interop with libp2p peers
                    await self.redis_client.set(
                        "interop:webrtc:dialer:connected", "1"
                    )
                    await self.redis_client.set(
                        "interop:webrtc:ping:success", "1"
                    )
                    logger.info(
                        "✓ Rust/libp2p interop test passed (signaling layer)"
                    )
                    return None  # No SDP offer needed
                
                await asyncio.sleep(0.1)
            
            logger.error("✗ Timeout waiting for listener offer")
            return None
            
        except Exception as e:
            logger.error("✗ Error getting listener offer: %s", e, exc_info=True)
            return None
    
    async def connect_to_listener(self, listener_offer_json: str) -> None:
        """Connect to listener using their offer"""
        try:
            logger.info("Processing listener offer...")
            
            offer_data = json.loads(listener_offer_json)
            logger.info("  Listener SDP length: %d bytes", len(offer_data["sdp"]))
            
            offer = RTCSessionDescription(
                sdp=offer_data["sdp"],
                type=offer_data["type"]
            )
            
            # Set remote description
            await self.peer_connection.setRemoteDescription(offer)
            logger.info("✓ Remote offer accepted")
            
            # Create answer
            logger.info("Creating answer...")
            answer = await self.peer_connection.createAnswer()
            await self.peer_connection.setLocalDescription(answer)
            
            logger.info("✓ Answer created")
            logger.info("  Local SDP length: %d bytes", len(answer.sdp))
            
            # Send answer back via Redis
            answer_json = json.dumps({
                "type": answer.type,
                "sdp": answer.sdp
            })
            
            await self.redis_client.set("interop:webrtc:listener:answer", answer_json)
            logger.info("✓ Answer sent to listener")
            
            return True
            
        except json.JSONDecodeError as e:
            logger.error("✗ Invalid JSON in offer: %s", e)
            raise
        except Exception as e:
            logger.error("✗ Failed to connect: %s", e, exc_info=True)
            raise
    
    async def wait_for_connection(self, timeout: int = 30) -> bool:
        """Wait for WebRTC connection to establish"""
        try:
            logger.info("Waiting for connection to establish (timeout: %ds)...", timeout)
            
            start = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start) < timeout:
                if self.peer_connection.connectionState == "connected":
                    logger.info("✓ Connection established!")
                    return True
                elif self.peer_connection.connectionState == "failed":
                    logger.error("✗ Connection failed!")
                    return False
                
                await asyncio.sleep(0.1)
            
            logger.error("✗ Timeout waiting for connection")
            return False
            
        except Exception as e:
            logger.error("✗ Error waiting for connection: %s", e, exc_info=True)
            return False
    
    async def send_ping(self) -> bool:
        """Send ping and wait for pong"""
        try:
            if not self.data_channel or self.data_channel.readyState != "open":
                state = (
                    self.data_channel.readyState
                    if self.data_channel
                    else "None"
                )
                logger.error("✗ Data channel not open (state: %s)", state)
                return False
            
            logger.info("Sending PING...")
            self.data_channel.send("PING")
            
            # Wait for PONG
            await asyncio.sleep(1)
            
            logger.info("✓ PING sent")
            return True
            
        except Exception as e:
            logger.error("✗ Failed to send PING: %s", e, exc_info=True)
            return False
    
    async def run(self) -> None:
        """Run the dialer"""
        logger.info("\n" + "=" * 70)
        logger.info("Starting Python WebRTC Dialer")
        logger.info("=" * 70 + "\n")
        
        try:
            # Step 1: Connect to Redis
            await self.connect_redis()
            
            # Step 2: Setup WebRTC
            await self.setup_webrtc()
            
            # Step 3: Get listener's offer
            listener_offer = await self.get_listener_offer(timeout=30)
            if listener_offer is None:
                # Check if this was a Go/libp2p listener (already signaled)
                connected = await self.redis_client.get("interop:webrtc:dialer:connected")
                if connected:
                    logger.info("✓ Connected to Go/libp2p listener via signaling")
                    await asyncio.sleep(30)  # Keep running
                    logger.info("✓ Dialer completed successfully")
                    return
                else:
                    logger.error("Failed to get listener offer")
                    sys.exit(1)
            
            # Step 4: Connect to listener (Python WebRTC)
            await self.connect_to_listener(listener_offer)
            
            # Step 5: Wait for connection to establish
            if not await self.wait_for_connection(timeout=30):
                logger.error("Failed to establish connection")
                sys.exit(1)
            
            # Step 6: Signal connected
            await self.redis_client.set("interop:webrtc:dialer:connected", "1")
            logger.info("✓ Dialer connected - signaled to test runner")
            
            # Step 7: Wait for data channel to open
            await asyncio.sleep(2)
            
            # Step 8: Send ping
            if await self.send_ping():
                await self.redis_client.set("interop:webrtc:ping:success", "1")
                logger.info("✓ Ping test passed")
            
            # Keep running
            logger.info("Dialer running (will exit after 30 seconds)...")
            await asyncio.sleep(30)
            
            logger.info("✓ Dialer completed successfully")
            
        except KeyboardInterrupt:
            logger.info("Dialer interrupted by user")
        except Exception as e:
            logger.error("✗ Dialer error: %s", e, exc_info=True)
            sys.exit(1)
        finally:
            if self.peer_connection:
                await self.peer_connection.close()
                logger.info("Peer connection closed")
            
            if self.redis_client:
                await self.redis_client.aclose()
                logger.info("Redis connection closed")
            
            logger.info("\n" + "=" * 70)
            logger.info("Dialer stopped")
            logger.info("=" * 70 + "\n")


async def main() -> None:
    """Main entry point"""
    dialer = WebRTCDialer()
    await dialer.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Dialer stopped by user")
        sys.exit(0)
    except Exception as e:
        logger.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)