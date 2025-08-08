import logging
from typing import Any

from aiortc import RTCConfiguration
from multiaddr import Multiaddr
import trio

from libp2p import generate_peer_id_from, new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.transport.webrtc.async_bridge import TrioSafeWebRTCOperations
from libp2p.transport.webrtc.connection import WebRTCRawConnection
from libp2p.transport.webrtc.constants import (
    SIGNALING_PROTOCOL,
)
from libp2p.transport.webrtc.gen_certificate import (
    WebRTCCertificate,
    create_webrtc_direct_multiaddr,
)
from libp2p.transport.webrtc.private_to_private.transport import (
    WebRTCTransport,
)
from libp2p.transport.webrtc.private_to_public.transport import (
    WebRTCDirectTransport,
)
from libp2p.transport.webrtc.signal_service import (
    SignalService,
)

logger = logging.getLogger("webrtc.live_signaling_test")


class FixedLiveSignalingTest:
    """
    Live signaling tests for WebRTC transport.
    """

    def __init__(self) -> None:
        self.results: dict[str, bool] = {
            "peer_id_generation": False,
            "signaling_protocol": False,
            "transport_creation": False,
            "webrtc_connection_quick": False,
            "certificate_integration": False,
        }

    async def run_live_tests(self) -> None:
        """Run comprehensive live signaling tests"""
        print("🔴 Live Signaling Test Suite (ED25519)")
        print("=" * 50)
        print("Testing live WebRTC signaling with ED25519 peer IDs")
        print()

        await self.test_peer_id_generation()
        await self.test_signaling_protocol()
        await self.test_transport_creation()
        await self.test_webrtc_connection_quick()
        await self.test_certificate_integration()

        self.print_live_summary()

    async def test_peer_id_generation(self) -> None:
        """Test ED25519 peer ID generation for signaling"""
        print("1. 🔑 ED25519 Peer ID Generation...")
        try:
            dialer_key = create_new_key_pair()
            listener_key = create_new_key_pair()
            relay_key = create_new_key_pair()

            dialer_peer_id = generate_peer_id_from(dialer_key)
            listener_peer_id = generate_peer_id_from(listener_key)
            relay_peer_id = generate_peer_id_from(relay_key)

            print(f"   Dialer ED25519 Peer ID: {dialer_peer_id}")
            print(f"   Listener ED25519 Peer ID: {listener_peer_id}")
            print(f"   Relay ED25519 Peer ID: {relay_peer_id}")

            peer_ids = [dialer_peer_id, listener_peer_id, relay_peer_id]
            unique_ids = {str(pid) for pid in peer_ids}
            assert len(unique_ids) == 3, "All peer IDs should be unique"

            for peer_id in peer_ids:
                assert isinstance(peer_id, ID), "Should be proper ID object"
                peer_id_str = str(peer_id)
                assert len(peer_id_str) > 40, "Should be substantial length"

                roundtrip = ID.from_base58(peer_id_str)
                assert str(roundtrip) == peer_id_str, "Roundtrip should match"

            print("   ✅ ED25519 peer ID generation successful")
            print("   ✅ All peer IDs are unique and valid")

            self.results["peer_id_generation"] = True

        except Exception as e:
            print(f"   Peer ID generation failed: {e}")

    async def test_signaling_protocol(self) -> None:
        """Test signaling protocol setup with ED25519 peer IDs"""
        print("\n2. Signaling Protocol Test...")
        try:
            key_pair_1 = create_new_key_pair()
            key_pair_2 = create_new_key_pair()

            host_1 = new_host(key_pair=key_pair_1)
            host_2 = new_host(key_pair=key_pair_2)

            print(f"   Host 1 ED25519 Peer ID: {host_1.get_id()}")
            print(f"   Host 2 ED25519 Peer ID: {host_2.get_id()}")

            signal_1 = SignalService(host_1)
            signal_2 = SignalService(host_2)

            assert str(signal_1.signal_protocol) == SIGNALING_PROTOCOL
            assert str(signal_2.signal_protocol) == SIGNALING_PROTOCOL

            print(f"   Signaling protocol: {SIGNALING_PROTOCOL}")

            messages_received = {"count": 0}

            async def test_handler(msg: dict[str, Any], peer_id: str) -> None:
                messages_received["count"] += 1
                print(f"     Handler received message from {peer_id[:20]}...")

            signal_1.set_handler("offer", test_handler)
            signal_2.set_handler("answer", test_handler)

            print("   ✅ Signal handlers registered")
            print("   ✅ Protocol setup successful")

            # Cleanup
            await host_1.close()
            await host_2.close()

            self.results["signaling_protocol"] = True

        except Exception as e:
            print(f"    Signaling protocol test failed: {e}")

    async def test_transport_creation(self) -> None:
        """Test WebRTC transport creation with ED25519 peer IDs"""
        print("\n4. 🚀 Transport Creation Test...")
        try:
            key_pair = create_new_key_pair()
            host = new_host(key_pair=key_pair)

            print(f"   Host ED25519 Peer ID: {host.get_id()}")

            webrtc_transport = WebRTCTransport()
            webrtc_transport.set_host(host)

            await webrtc_transport.start()
            assert webrtc_transport.is_started()
            assert "webrtc" in webrtc_transport.supported_protocols

            print("   ✅ WebRTC transport started")

            direct_transport = WebRTCDirectTransport()
            direct_transport.set_host(host)

            await direct_transport.start()
            assert direct_transport.is_started()
            assert "webrtc-direct" in direct_transport.supported_protocols

            print("   ✅ WebRTC-Direct transport started")

            test_maddr = Multiaddr(f"/webrtc/p2p/{host.get_id()}")
            can_handle = webrtc_transport.can_handle(test_maddr)
            print(f"   Can handle multiaddr: {can_handle}")

            await webrtc_transport.stop()
            await direct_transport.stop()
            await host.close()

            self.results["transport_creation"] = True

        except Exception as e:
            print(f"    Transport creation test failed: {e}")

    async def test_webrtc_connection_quick(self) -> None:
        """Test quick WebRTC connection setup"""
        print("\n5.  Quick WebRTC Connection...")
        try:
            config = RTCConfiguration([])
            (
                pc,
                dc,
            ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
                config, "quick-test"
            )

            key_pair = create_new_key_pair()
            test_peer_id = generate_peer_id_from(key_pair)

            connection = WebRTCRawConnection(test_peer_id, pc, dc, is_initiator=True)

            print("   ✅ Created WebRTC connection")
            print(f"   ED25519 Peer ID: {test_peer_id}")

            stream = await connection.open_stream()
            stream.set_protocol(TProtocol("/libp2p/webrtc/signal/1.0.0"))
            print(f"Created {stream.stream_id} with protocol {stream.get_protocol()}")

            assert connection.peer_id == test_peer_id
            assert not connection._closed

            print("   ✅ Connection properties validated")

            await stream.close()
            await connection.close()

            self.results["webrtc_connection_quick"] = True
            print("   Quick WebRTC connection successful")

        except Exception as e:
            print(f"   WebRTC connection failed: {e}")

    async def test_certificate_integration(self) -> None:
        """Test certificate integration with ED25519 peer IDs"""
        print("\n6. 🔐 Certificate Integration Test...")
        try:
            cert = WebRTCCertificate.generate()
            key_pair = create_new_key_pair()
            peer_id = generate_peer_id_from(key_pair)

            print(f"   Certificate hash: {cert.certhash}")
            print(f"   ED25519 Peer ID: {peer_id}")

            multiaddrs = [
                f"/ip4/127.0.0.1/udp/9000/webrtc-direct/certhash/{cert.certhash}/p2p/{peer_id}",
                f"/ip6/::1/udp/9001/webrtc-direct/certhash/{cert.certhash}/p2p/{peer_id}",
                str(create_webrtc_direct_multiaddr("127.0.0.1", 9002, peer_id)),
            ]

            for addr_str in multiaddrs:
                try:
                    maddr = Multiaddr(addr_str)
                    protocols = [p.name for p in maddr.protocols()]
                    print(f"   ✅ Valid multiaddr: {addr_str}")
                    print(f"      Protocols: {protocols}")
                except Exception as e:
                    print(f"    Invalid multiaddr: {e}")

            assert cert.certhash.startswith("uEi"), "Should start with uEi"
            assert len(cert.certhash) > 20, "Should be substantial"

            # Test PEM export/import with comprehensive validation
            assert cert.validate_pem_export(), "PEM export/import validation failed"
            print("   ✅ Certificate PEM cryptographically validated")
            print("   ✅ Integration with ED25519 peer IDs working")

            self.results["certificate_integration"] = True

        except Exception as e:
            print(f"    Certificate integration test failed: {e}")

    def print_live_summary(self) -> None:
        """Print live test results summary"""
        print("\n" + "=" * 50)
        print("🔴 LIVE SIGNALING TEST SUMMARY (ED25519)")
        print("=" * 50)

        passed_tests = sum(1 for result in self.results.values() if result)
        total_tests = len(self.results)

        print(f"\n📊 Live Test Results: {passed_tests}/{total_tests} passed")

        for test_name, result in self.results.items():
            icon = "✅" if result else ""
            name = test_name.replace("_", " ").title()
            print(f"   {icon} {name}")

        percentage = (passed_tests / total_tests) * 100
        print(f"\n Success Rate: {percentage:.1f}%")

        if passed_tests == total_tests:
            print("\n All live signaling tests passed!")
        elif passed_tests >= total_tests * 0.8:
            print("Some minor signaling issues to address")
        else:
            print("\n Several live tests failed - needs investigation")


async def main() -> None:
    test = FixedLiveSignalingTest()
    await test.run_live_tests()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    trio.run(main)
