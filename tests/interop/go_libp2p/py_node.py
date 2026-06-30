#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import time
from typing import List

import trio
from multiaddr import Multiaddr

# libp2p imports
from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import Pubsub
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.tools.async_service.trio_service import background_trio_service

# FIXED: Correct imports for security and muxers
from libp2p.security.noise.transport import Transport as NoiseTransport
from libp2p.stream_muxer.yamux import Yamux
from libp2p.stream_muxer.mplex import mplex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import socket

# FIXED: Define the noise protocol ID directly (since import was failing)
NOISE_PROTOCOL_ID = TProtocol("/noise")

def find_free_port() -> int:
    """Return a free ephemeral port from the OS."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    addr, port = s.getsockname()
    s.close()
    return port

def get_available_interfaces(listen_port: int) -> List[Multiaddr]:
    """Return a list of listen multiaddrs."""
    port = listen_port if (listen_port and listen_port > 0) else find_free_port()
    return [Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]

class PyLibp2pNode:
    def __init__(self, listen_port: int = 0):
        self.listen_port = listen_port if listen_port > 0 else 0
        self.host = None
        self.pubsub = None
        self.gossipsub = None
        self.subscribed_topics = {}
        self.received_messages = []

    async def start(self):
        try:
            listen_addrs = get_available_interfaces(self.listen_port)
            key_pair = create_new_key_pair()

            # FIXED: Proper security and muxer configuration
            # Create noise transport with proper key handling
            noise_transport = NoiseTransport(
                libp2p_keypair=key_pair,
                noise_privkey=key_pair.private_key  # Use the same private key
            )
            
            # Configure multiplexers (both for compatibility)
            muxer_opts = {
                TProtocol("/yamux/1.0.0"): Yamux,
                TProtocol("/mplex/6.7.0"): mplex,
            }
            
            # FIXED: Use the protocol ID directly (not imported constant)
            sec_opts = {
                NOISE_PROTOCOL_ID: noise_transport,
            }

            # Create host with explicit configuration
            self.host = new_host(
                key_pair=key_pair,
                listen_addrs=listen_addrs,
                sec_opt=sec_opts,
                muxer_opt=muxer_opts,
            )
            
            if self.host is None:
                raise RuntimeError("Failed to create libp2p host")

            # Create gossipsub router with compatible settings
            self.gossipsub = GossipSub(
                protocols=[
                    TProtocol("/meshsub/1.1.0"), 
                    TProtocol("/meshsub/1.0.0"),
                    TProtocol("/floodsub/1.0.0")  # Fallback compatibility
                ],
                degree=6,
                degree_low=4,
                degree_high=12,
                time_to_live=30,
                gossip_window=3,
                gossip_history=5,
                heartbeat_interval=1,
                do_px=True,
            )

            # Create pubsub with host and router
            self.pubsub = Pubsub(
                host=self.host,
                router=self.gossipsub,
                cache_size=128,
            )

            logger.info("Py-libp2p node started successfully")
            logger.info(f"Peer ID: {self.host.get_id()}")
            logger.info(f"Security protocols: {list(sec_opts.keys())}")
            logger.info(f"Muxer protocols: {list(muxer_opts.keys())}")
            
            # Log listening addresses with peer ID
            addrs = self.host.get_addrs()
            for addr in addrs:
                full_addr = f"{addr}/p2p/{self.host.get_id()}"
                logger.info(f"Listening on: {full_addr}")
                
        except Exception as e:
            logger.error(f"Failed to start node: {e}")
            import traceback
            traceback.print_exc()
            raise

    async def get_addresses(self) -> List[str]:
        if self.host is None:
            return []
        return [f"{addr}/p2p/{self.host.get_id()}" for addr in self.host.get_addrs()]

    def get_peer_id(self) -> str:
        if self.host is None:
            return "unknown"
        return str(self.host.get_id())

    async def connect_to_peer(self, peer_addr: str):
        if self.host is None:
            raise RuntimeError("Node not started")
            
        try:
            logger.info(f"Attempting to connect to: {peer_addr}")
            maddr = Multiaddr(peer_addr)
            peer_info = info_from_p2p_addr(maddr)
            
            logger.info(f"Connecting to peer ID: {peer_info.peer_id}")
            logger.info(f"Peer addresses: {peer_info.addrs}")
            
            await self.host.connect(peer_info)
            logger.info(f"Successfully connected to peer: {peer_info.peer_id}")
            
            # Allow connection to stabilize
            await trio.sleep(2)
            
        except Exception as e:
            logger.error(f"Failed to connect to peer {peer_addr}: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            raise

    async def subscribe(self, topic_name: str):
        if self.pubsub is None:
            raise RuntimeError("Pubsub not initialized")
            
        if topic_name in self.subscribed_topics:
            logger.warning(f"Already subscribed to topic: {topic_name}")
            return

        try:
            # Subscribe and get the subscription queue
            subscription = await self.pubsub.subscribe(topic_name)
            self.subscribed_topics[topic_name] = subscription

            logger.info(f"Successfully subscribed to topic: {topic_name}")
            return subscription
            
        except Exception as e:
            logger.error(f"Failed to subscribe to topic {topic_name}: {e}")
            raise

    async def publish(self, topic_name: str, message: str):
        if self.pubsub is None:
            raise RuntimeError("Pubsub not initialized")
            
        if topic_name not in self.subscribed_topics:
            raise ValueError(f"Not subscribed to topic: {topic_name}")

        try:
            message_bytes = message.encode("utf-8")
            await self.pubsub.publish(topic_name, message_bytes)
            logger.info(f"Published to '{topic_name}': {message}")
        except Exception as e:
            logger.error(f"Failed to publish message: {e}")
            raise

    def get_connected_peers(self) -> List[str]:
        if self.host is None:
            return []
        try:
            network = self.host.get_network()
            if network and hasattr(network, "connections"):
                return [str(peer_id) for peer_id in network.connections.keys()]
        except Exception as e:
            logger.debug(f"Error getting connected peers: {e}")
        return []

    def get_mesh_peers(self, topic_name: str) -> List[str]:
        if self.gossipsub is None:
            return []
        try:
            if hasattr(self.gossipsub, "mesh") and topic_name in self.gossipsub.mesh:
                return [str(peer_id) for peer_id in self.gossipsub.mesh[topic_name]]
        except Exception as e:
            logger.debug(f"Error getting mesh peers: {e}")
        return []

    def get_subscribed_topics(self) -> List[str]:
        return list(self.subscribed_topics.keys())

    def get_received_messages(self) -> List[dict]:
        return self.received_messages.copy()

    async def close(self):
        if self.host:
            try:
                await self.host.close()
                logger.info("Node closed successfully")
            except Exception as e:
                logger.error(f"Error closing node: {e}")

# Message handling for subscriptions
async def handle_subscription_messages(subscription, topic_name: str, received_messages: List[dict]):
    """Handle incoming messages from a subscription"""
    while True:
        try:
            message = await subscription.get()
            message_content = message.data.decode("utf-8") if message.data else ""
            sender = message.from_id.hex() if message.from_id else "unknown"
            
            logger.info(f"Received on '{topic_name}' from {sender}: {message_content}")
            received_messages.append({
                'topic': topic_name,
                'data': message_content,
                'from': sender,
                'timestamp': time.time()
            })
        except Exception as e:
            logger.error(f"Error handling message on {topic_name}: {e}")
            break

# Mode implementations
async def run_interactive_mode(node: PyLibp2pNode, topic: str):
    logger.info("Interactive mode. Type messages to publish, 'quit' to exit:")
    
    # Start pubsub and gossipsub services
    async with node.host.run(listen_addrs=get_available_interfaces(node.listen_port)):
        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await node.pubsub.wait_until_ready()
                
                # Subscribe to topic
                subscription = await node.subscribe(topic)
                
                async with trio.open_nursery() as nursery:
                    # Start message handler
                    nursery.start_soon(handle_subscription_messages, subscription, topic, node.received_messages)
                    
                    # Interactive loop
                    while True:
                        try:
                            message = await trio.to_thread.run_sync(input, "> ")
                            if message.strip().lower() == "quit":
                                break
                            if message.strip():
                                await node.publish(topic, message.strip())
                        except (EOFError, KeyboardInterrupt):
                            break
                        except Exception as e:
                            logger.error(f"Error in interactive mode: {e}")

async def run_publisher_mode(node: PyLibp2pNode, topic: str, message: str, count: int):
    logger.info(f"Publisher mode: sending {count} messages to topic '{topic}'")
    
    # Start pubsub and gossipsub services  
    async with node.host.run(listen_addrs=get_available_interfaces(node.listen_port)):
        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await node.pubsub.wait_until_ready()
                
                # Subscribe to topic
                subscription = await node.subscribe(topic)
                
                async with trio.open_nursery() as nursery:
                    # Start message handler
                    nursery.start_soon(handle_subscription_messages, subscription, topic, node.received_messages)
                    
                    # Wait for mesh formation
                    logger.info("Waiting for mesh formation...")
                    await trio.sleep(3)
                    
                    # Publishing loop
                    for i in range(1, count + 1):
                        msg = f"{message} #{i}"
                        try:
                            await node.publish(topic, msg)
                            await trio.sleep(1)
                        except Exception as e:
                            logger.error(f"Failed to publish message {i}: {e}")

                    logger.info("Publishing complete, waiting for any final messages...")
                    await trio.sleep(5)

async def run_subscriber_mode(node: PyLibp2pNode, topic: str):
    logger.info("Subscriber mode: waiting for messages...")
    logger.info("Press Ctrl+C to stop")
    
    # Start pubsub and gossipsub services
    async with node.host.run(listen_addrs=get_available_interfaces(node.listen_port)):
        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await node.pubsub.wait_until_ready()
                
                # Subscribe to topic
                subscription = await node.subscribe(topic)
                
                async with trio.open_nursery() as nursery:
                    # Start message handler
                    nursery.start_soon(handle_subscription_messages, subscription, topic, node.received_messages)
                    
                    # Status monitoring loop
                    try:
                        while True:
                            await trio.sleep(5)
                            connected = len(node.get_connected_peers())
                            topics = node.get_subscribed_topics()
                            received = len(node.get_received_messages())
                            logger.info(f"Status: {connected} peers connected, {len(topics)} topics subscribed, {received} messages received")
                            
                    except KeyboardInterrupt:
                        logger.info("Received interrupt signal, shutting down...")

async def run_test_mode(node: PyLibp2pNode, topic: str, message: str, count: int):
    logger.info(f"Test mode starting for topic '{topic}'")
    
    # Start pubsub and gossipsub services
    async with node.host.run(listen_addrs=get_available_interfaces(node.listen_port)):
        async with background_trio_service(node.pubsub):
            async with background_trio_service(node.gossipsub):
                await node.pubsub.wait_until_ready()
                
                # Subscribe to topic
                subscription = await node.subscribe(topic)
                
                async def publisher():
                    logger.info("Publisher: Waiting for mesh formation...")
                    await trio.sleep(3)
                    
                    logger.info(f"Publisher: Starting to send {count} messages")
                    for i in range(1, count + 1):
                        msg = f"{message}-test-{os.getpid()}-{i}"
                        try:
                            await node.publish(topic, msg)
                            await trio.sleep(0.8)
                        except Exception as e:
                            logger.error(f"Failed to publish test message {i}: {e}")
                    logger.info("Publisher: Finished sending messages")

                async def status_monitor():
                    for iteration in range(10):  # Monitor for ~20 seconds
                        await trio.sleep(2)
                        connected_peers = node.get_connected_peers()
                        mesh_peers = node.get_mesh_peers(topic)
                        received_msgs = node.get_received_messages()
                        
                        logger.info(f"Status [{iteration+1}/10]: Connected={len(connected_peers)}, Mesh={len(mesh_peers)}, Received={len(received_msgs)}")

                    logger.info("Test complete")
                    logger.info(f"Final - Connected peers: {node.get_connected_peers()}")
                    logger.info(f"Final - Mesh peers for '{topic}': {node.get_mesh_peers(topic)}")
                    logger.info(f"Final - Total received messages: {len(node.get_received_messages())}")

                async with trio.open_nursery() as nursery:
                    # Start message handler
                    nursery.start_soon(handle_subscription_messages, subscription, topic, node.received_messages)
                    nursery.start_soon(status_monitor)
                    nursery.start_soon(publisher)

async def main():
    parser = argparse.ArgumentParser(description="Py-libp2p Gossipsub Interop Node (WORKING VERSION)")
    parser.add_argument("--listen", default="0", help="Listen port (0 for random)")
    parser.add_argument("--connect", default="", help="Peer address to connect to")
    parser.add_argument("--topic", default="interop-test", help="Topic name")
    parser.add_argument(
        "--mode",
        default="interactive",
        choices=["interactive", "publisher", "subscriber", "test"],
        help="Operating mode",
    )
    parser.add_argument("--message", default="Hello from Python!", help="Message to publish")
    parser.add_argument("--count", type=int, default=5, help="Number of messages to send")

    args = parser.parse_args()

    # Validate connection address format if provided
    if args.connect and not (args.connect.startswith("/ip4/") and "/p2p/" in args.connect):
        logger.error("Connection address must be in format: /ip4/IP/tcp/PORT/p2p/PEER_ID")
        logger.error(f"Received: {args.connect}")
        return

    listen_port = int(args.listen) if args.listen.isdigit() else 0
    node = PyLibp2pNode(listen_port)

    try:
        logger.info(f"Starting py-libp2p node in {args.mode} mode (FIXED VERSION)...")
        await node.start()

        # Connect to peer if specified
        if args.connect:
            logger.info(f"Connecting to peer: {args.connect}")
            await node.connect_to_peer(args.connect)

        # Run the specified mode
        if args.mode == "interactive":
            await run_interactive_mode(node, args.topic)
        elif args.mode == "publisher":
            await run_publisher_mode(node, args.topic, args.message, args.count)
        elif args.mode == "subscriber":
            await run_subscriber_mode(node, args.topic)
        elif args.mode == "test":
            await run_test_mode(node, args.topic, args.message, args.count)

    except KeyboardInterrupt:
        logger.info("Received interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error in main: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        logger.info("Closing node...")
        await node.close()

if __name__ == "__main__":
    trio.run(main)