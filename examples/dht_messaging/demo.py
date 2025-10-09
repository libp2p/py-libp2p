#!/usr/bin/env python

"""
DHT Messaging Demo - ETH Delhi Hackathon

This demo script shows how to run multiple DHT messaging nodes that can
discover each other without bootstrap servers and communicate directly.

Usage:
    python demo.py --mode pubsub    # Run pubsub messaging demo
    python demo.py --mode direct    # Run direct messaging demo
    python demo.py --mode both      # Run both demos
"""

import argparse
import asyncio
import logging
import subprocess
import sys
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("dht-messaging-demo")


class DHTMessagingDemo:
    """Demo runner for DHT messaging examples."""

    def __init__(self, mode: str):
        self.mode = mode
        self.processes = []
        self.script_dir = Path(__file__).parent

    def run_pubsub_demo(self):
        """Run the pubsub messaging demo with multiple nodes."""
        logger.info("🚀 Starting DHT PubSub Messaging Demo")
        logger.info("=" * 60)
        
        # Start 3 nodes for the demo
        nodes = [
            {"username": "Alice", "port": 8001},
            {"username": "Bob", "port": 8002},
            {"username": "Charlie", "port": 8003},
        ]
        
        for node in nodes:
            cmd = [
                sys.executable,
                str(self.script_dir / "dht_messaging.py"),
                "-p", str(node["port"]),
                "-u", node["username"],
                "-v"
            ]
            
            logger.info(f"Starting {node['username']} on port {node['port']}")
            process = subprocess.Popen(cmd)
            self.processes.append(process)
            time.sleep(2)  # Give each node time to start
        
        logger.info("\n🎉 Demo nodes started!")
        logger.info("💡 Each node will discover others via DHT and start messaging")
        logger.info("💡 Type messages in any terminal to see them broadcast")
        logger.info("💡 Type 'quit' in any terminal to stop that node")
        logger.info("\nPress Ctrl+C to stop all nodes")

    def run_direct_demo(self):
        """Run the direct messaging demo with multiple nodes."""
        logger.info("🚀 Starting DHT Direct Messaging Demo")
        logger.info("=" * 60)
        
        # Start 3 nodes for the demo
        nodes = [
            {"username": "Alice", "port": 9001},
            {"username": "Bob", "port": 9002},
            {"username": "Charlie", "port": 9003},
        ]
        
        for node in nodes:
            cmd = [
                sys.executable,
                str(self.script_dir / "dht_direct_messaging.py"),
                "-p", str(node["port"]),
                "-u", node["username"],
                "-v"
            ]
            
            logger.info(f"Starting {node['username']} on port {node['port']}")
            process = subprocess.Popen(cmd)
            self.processes.append(process)
            time.sleep(2)  # Give each node time to start
        
        logger.info("\n🎉 Demo nodes started!")
        logger.info("💡 Each node will discover others via DHT")
        logger.info("💡 Use 'msg <peer_id> <message>' to send direct messages")
        logger.info("💡 Use 'peers' to see connected peers")
        logger.info("💡 Type 'quit' in any terminal to stop that node")
        logger.info("\nPress Ctrl+C to stop all nodes")

    def run_both_demos(self):
        """Run both pubsub and direct messaging demos."""
        logger.info("🚀 Starting Both DHT Messaging Demos")
        logger.info("=" * 60)
        
        # Start pubsub demo
        self.run_pubsub_demo()
        time.sleep(5)
        
        # Start direct messaging demo
        self.run_direct_demo()

    def run(self):
        """Run the demo based on the selected mode."""
        try:
            if self.mode == "pubsub":
                self.run_pubsub_demo()
            elif self.mode == "direct":
                self.run_direct_demo()
            elif self.mode == "both":
                self.run_both_demos()
            else:
                logger.error(f"❌ Unknown mode: {self.mode}")
                return
            
            # Wait for user to stop
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("\n🛑 Stopping demo...")
            self.stop_all_processes()
        except Exception as e:
            logger.error(f"❌ Demo error: {e}")
            self.stop_all_processes()

    def stop_all_processes(self):
        """Stop all running processes."""
        for process in self.processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            except Exception as e:
                logger.error(f"❌ Error stopping process: {e}")
        
        logger.info("✅ All demo processes stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="DHT Messaging Demo - ETH Delhi Hackathon"
    )
    parser.add_argument(
        "--mode",
        choices=["pubsub", "direct", "both"],
        default="pubsub",
        help="Demo mode to run"
    )
    
    args = parser.parse_args()
    
    logger.info("🎯 ETH Delhi Hackathon - DHT Messaging Demo")
    logger.info("📋 Demonstrating serverless peer discovery and messaging")
    
    demo = DHTMessagingDemo(args.mode)
    demo.run()


if __name__ == "__main__":
    main()
