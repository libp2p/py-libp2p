#!/usr/bin/env python3
"""
Network Testing Script for P2P File Sharing.

This script tests the P2P file sharing application across different network
scenarios including local networks, NAT traversal, and relay connections.
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import trio

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from examples.p2p_file_sharing.file_sharing_app import P2PFileSharingApp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("network_test")


class NetworkTester:
    """Network testing utility for P2P file sharing."""
    
    def __init__(self):
        self.test_results = {}
        self.apps = []
    
    async def create_test_app(self, port: int, seed: int = None) -> P2PFileSharingApp:
        """Create a test application instance."""
        app = P2PFileSharingApp(
            port=port,
            shared_files_dir=f"./test_shared_{port}",
            download_dir=f"./test_downloads_{port}",
            peer_db_path=f"./test_peers_{port}.json",
            seed=seed
        )
        
        # Create test files
        await self._create_test_files(app.shared_files_dir, port)
        
        return app
    
    async def _create_test_files(self, shared_dir: str, port: int):
        """Create test files for the application."""
        os.makedirs(shared_dir, exist_ok=True)
        
        # Create a test file
        test_file = Path(shared_dir) / f"test_file_peer_{port}.txt"
        with open(test_file, 'w') as f:
            f.write(f"Test file from peer on port {port}\n" * 100)
    
    async def test_local_connection(self):
        """Test connection between two peers on the same machine."""
        print("\n🧪 Testing Local Connection...")
        
        app1 = await self.create_test_app(8001, seed=12345)
        app2 = await self.create_test_app(8002, seed=54321)
        
        try:
            # Start both apps
            async with app1.host.run(listen_addrs=app1.host.get_addrs()):
                await app1.initialize()
                
                async with app2.host.run(listen_addrs=app2.host.get_addrs()):
                    await app2.initialize()
                    
                    # Get peer addresses
                    peer1_addrs = app1.host.get_addrs()
                    peer2_addrs = app2.host.get_addrs()
                    
                    print(f"  Peer 1 addresses: {peer1_addrs}")
                    print(f"  Peer 2 addresses: {peer2_addrs}")
                    
                    # Test connection
                    peer1_info = app1.host.get_peerstore().peer_info(app1.host.get_id())
                    peer2_info = app2.host.get_peerstore().peer_info(app2.host.get_id())
                    
                    # Add peer info to each other's peerstore
                    app1.host.get_peerstore().add_addrs(peer2_info.peer_id, peer2_info.addrs, 3600)
                    app2.host.get_peerstore().add_addrs(peer1_info.peer_id, peer1_info.addrs, 3600)
                    
                    # Attempt connection
                    try:
                        await app2.host.connect(peer1_info)
                        print("  ✅ Local connection successful")
                        self.test_results["local_connection"] = True
                    except Exception as e:
                        print(f"  ❌ Local connection failed: {e}")
                        self.test_results["local_connection"] = False
                    
                    # Test file sharing
                    try:
                        # Create stream for file sharing
                        stream = await app2.host.new_stream(peer1_info.peer_id, [app1.file_protocol.FILE_SHARING_PROTOCOL])
                        
                        # Request file list
                        files = await app1.file_protocol.request_file_list(stream)
                        await stream.close()
                        
                        if files:
                            print(f"  ✅ File sharing successful - found {len(files)} files")
                            self.test_results["file_sharing"] = True
                        else:
                            print("  ⚠️  File sharing successful but no files found")
                            self.test_results["file_sharing"] = False
                            
                    except Exception as e:
                        print(f"  ❌ File sharing failed: {e}")
                        self.test_results["file_sharing"] = False
                    
        except Exception as e:
            print(f"  ❌ Local connection test failed: {e}")
            self.test_results["local_connection"] = False
        
        finally:
            await app1.shutdown()
            await app2.shutdown()
    
    async def test_nat_traversal(self):
        """Test NAT traversal capabilities."""
        print("\n🌐 Testing NAT Traversal...")
        
        app1 = await self.create_test_app(8003, seed=11111)
        app2 = await self.create_test_app(8004, seed=22222)
        
        try:
            # Start both apps
            async with app1.host.run(listen_addrs=app1.host.get_addrs()):
                await app1.initialize()
                
                async with app2.host.run(listen_addrs=app2.host.get_addrs()):
                    await app2.initialize()
                    
                    # Test NAT status determination
                    nat_status1 = await app1.nat_traversal.determine_nat_status()
                    nat_status2 = await app2.nat_traversal.determine_nat_status()
                    
                    print(f"  Peer 1 NAT status: {nat_status1}")
                    print(f"  Peer 2 NAT status: {nat_status2}")
                    
                    # Test relay discovery
                    relays1 = await app1.nat_traversal.discover_relays()
                    relays2 = await app2.nat_traversal.discover_relays()
                    
                    print(f"  Peer 1 discovered relays: {len(relays1)}")
                    print(f"  Peer 2 discovered relays: {len(relays2)}")
                    
                    # Test connection with NAT traversal
                    peer1_info = app1.host.get_peerstore().peer_info(app1.host.get_id())
                    peer2_info = app2.host.get_peerstore().peer_info(app2.host.get_id())
                    
                    app1.host.get_peerstore().add_addrs(peer2_info.peer_id, peer2_info.addrs, 3600)
                    app2.host.get_peerstore().add_addrs(peer1_info.peer_id, peer1_info.addrs, 3600)
                    
                    # Attempt NAT traversal connection
                    success = await app2.nat_traversal.connect_with_nat_traversal(peer1_info)
                    
                    if success:
                        print("  ✅ NAT traversal connection successful")
                        self.test_results["nat_traversal"] = True
                    else:
                        print("  ⚠️  NAT traversal connection failed (expected in test environment)")
                        self.test_results["nat_traversal"] = False
                    
        except Exception as e:
            print(f"  ❌ NAT traversal test failed: {e}")
            self.test_results["nat_traversal"] = False
        
        finally:
            await app1.shutdown()
            await app2.shutdown()
    
    async def test_peer_discovery(self):
        """Test peer discovery mechanisms."""
        print("\n🔍 Testing Peer Discovery...")
        
        app1 = await self.create_test_app(8005, seed=33333)
        app2 = await self.create_test_app(8006, seed=44444)
        
        try:
            # Start both apps
            async with app1.host.run(listen_addrs=app1.host.get_addrs()):
                await app1.initialize()
                
                async with app2.host.run(listen_addrs=app2.host.get_addrs()):
                    await app2.initialize()
                    
                    # Test peer manager functionality
                    peer_stats1 = app1.peer_manager.get_peer_stats()
                    peer_stats2 = app2.peer_manager.get_peer_stats()
                    
                    print(f"  Peer 1 stats: {peer_stats1}")
                    print(f"  Peer 2 stats: {peer_stats2}")
                    
                    # Test adding peers
                    peer1_info = app1.host.get_peerstore().peer_info(app1.host.get_id())
                    peer2_info = app2.host.get_peerstore().peer_info(app2.host.get_id())
                    
                    app1.peer_manager.add_peer(peer2_info)
                    app2.peer_manager.add_peer(peer1_info)
                    
                    # Check if peers were added
                    known_peers1 = app1.peer_manager.get_known_peers()
                    known_peers2 = app2.peer_manager.get_known_peers()
                    
                    print(f"  Peer 1 known peers: {len(known_peers1)}")
                    print(f"  Peer 2 known peers: {len(known_peers2)}")
                    
                    if len(known_peers1) > 0 and len(known_peers2) > 0:
                        print("  ✅ Peer discovery successful")
                        self.test_results["peer_discovery"] = True
                    else:
                        print("  ❌ Peer discovery failed")
                        self.test_results["peer_discovery"] = False
                    
        except Exception as e:
            print(f"  ❌ Peer discovery test failed: {e}")
            self.test_results["peer_discovery"] = False
        
        finally:
            await app1.shutdown()
            await app2.shutdown()
    
    async def test_file_transfer(self):
        """Test file transfer functionality."""
        print("\n📁 Testing File Transfer...")
        
        app1 = await self.create_test_app(8007, seed=55555)
        app2 = await self.create_test_app(8008, seed=66666)
        
        try:
            # Start both apps
            async with app1.host.run(listen_addrs=app1.host.get_addrs()):
                await app1.initialize()
                
                async with app2.host.run(listen_addrs=app2.host.get_addrs()):
                    await app2.initialize()
                    
                    # Connect the peers
                    peer1_info = app1.host.get_peerstore().peer_info(app1.host.get_id())
                    peer2_info = app2.host.get_peerstore().peer_info(app2.host.get_id())
                    
                    app1.host.get_peerstore().add_addrs(peer2_info.peer_id, peer2_info.addrs, 3600)
                    app2.host.get_peerstore().add_addrs(peer1_info.peer_id, peer1_info.addrs, 3600)
                    
                    await app2.host.connect(peer1_info)
                    
                    # Test file listing
                    stream = await app2.host.new_stream(peer1_info.peer_id, [app1.file_protocol.FILE_SHARING_PROTOCOL])
                    files = await app1.file_protocol.request_file_list(stream)
                    await stream.close()
                    
                    if files:
                        print(f"  Found {len(files)} files for transfer")
                        
                        # Test file download
                        file_to_download = files[0]
                        download_path = os.path.join(app2.download_dir, f"downloaded_{file_to_download.name}")
                        
                        stream = await app2.host.new_stream(peer1_info.peer_id, [app1.file_protocol.FILE_SHARING_PROTOCOL])
                        await app2.file_protocol.download_file(stream, file_to_download.hash, download_path)
                        await stream.close()
                        
                        # Verify download
                        if os.path.exists(download_path):
                            print("  ✅ File transfer successful")
                            self.test_results["file_transfer"] = True
                        else:
                            print("  ❌ File transfer failed - file not found")
                            self.test_results["file_transfer"] = False
                    else:
                        print("  ❌ No files available for transfer")
                        self.test_results["file_transfer"] = False
                    
        except Exception as e:
            print(f"  ❌ File transfer test failed: {e}")
            self.test_results["file_transfer"] = False
        
        finally:
            await app1.shutdown()
            await app2.shutdown()
    
    def print_results(self):
        """Print test results summary."""
        print("\n" + "=" * 50)
        print("📊 Test Results Summary")
        print("=" * 50)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result)
        
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"  {test_name.replace('_', ' ').title()}: {status}")
        
        print(f"\nOverall: {passed_tests}/{total_tests} tests passed")
        
        if passed_tests == total_tests:
            print("🎉 All tests passed!")
        else:
            print("⚠️  Some tests failed. Check the logs above for details.")
    
    async def cleanup(self):
        """Clean up test files and directories."""
        print("\n🧹 Cleaning up test files...")
        
        # Remove test directories
        test_dirs = [
            "./test_shared_8001", "./test_shared_8002", "./test_shared_8003", "./test_shared_8004",
            "./test_shared_8005", "./test_shared_8006", "./test_shared_8007", "./test_shared_8008",
            "./test_downloads_8001", "./test_downloads_8002", "./test_downloads_8003", "./test_downloads_8004",
            "./test_downloads_8005", "./test_downloads_8006", "./test_downloads_8007", "./test_downloads_8008",
        ]
        
        for test_dir in test_dirs:
            if os.path.exists(test_dir):
                shutil.rmtree(test_dir)
        
        # Remove test database files
        test_dbs = [
            "./test_peers_8001.json", "./test_peers_8002.json", "./test_peers_8003.json", "./test_peers_8004.json",
            "./test_peers_8005.json", "./test_peers_8006.json", "./test_peers_8007.json", "./test_peers_8008.json",
        ]
        
        for test_db in test_dbs:
            if os.path.exists(test_db):
                os.remove(test_db)
        
        print("  ✅ Cleanup completed")


async def main():
    """Main test function."""
    print("🧪 P2P File Sharing Network Tests")
    print("=" * 50)
    
    tester = NetworkTester()
    
    try:
        # Run all tests
        await tester.test_local_connection()
        await tester.test_nat_traversal()
        await tester.test_peer_discovery()
        await tester.test_file_transfer()
        
        # Print results
        tester.print_results()
        
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
    finally:
        await tester.cleanup()


if __name__ == "__main__":
    trio.run(main)
