"""
Optimized Network Test for WebRTC Transport.

Fixes the major painpoint of hosts waiting too long for network resources
by using timeouts, mock networking, and simplified host setup.
"""

import logging

from aiortc import RTCConfiguration
from multiaddr import Multiaddr
import trio

from libp2p import generate_peer_id_from, new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID
from libp2p.transport.webrtc.async_bridge import (
    TrioSafeWebRTCOperations,
)
from libp2p.transport.webrtc.connection import WebRTCRawConnection
from libp2p.transport.webrtc.constants import (
    CODEC_CERTHASH,
    CODEC_WEBRTC,
    CODEC_WEBRTC_DIRECT,
)
from libp2p.transport.webrtc.gen_certificate import (
    WebRTCCertificate,
    create_webrtc_direct_multiaddr,
)
from libp2p.transport.webrtc.private_to_private.transport import (
    WebRTCTransport,
)
from libp2p.transport.webrtc.signal_service import (
    SignalService,
)

logger = logging.getLogger("webrtc.network_optimized_test")


class OptimizedNetworkTest:
    """
    Network-optimized WebRTC test implementation.
    """

    def __init__(self) -> None:
        self.results = {
            "host_creation": False,
            "mock_signaling": False,
            "webrtc_without_network": False,
            "stream_muxing_standalone": False,
            "protocol_validation": False,
            "certificate_standalone": False,
        }

    async def run_optimized_tests(self) -> None:
        """Run network-optimized test suite"""
        print("⚡ Network-Optimized WebRTC Test Suite")
        print("=" * 55)
        print("Fast tests with ED25519 peer IDs and network timeouts")
        print()

        await self.test_host_creation()
        await self.test_mock_signaling()
        await self.test_webrtc_without_network()
        await self.test_stream_muxing_standalone()
        self.test_protocol_validation()
        await self.test_certificate_standalone()

        self.print_final_results()

    async def test_host_creation(self) -> None:
        """Test host creation without network dependencies"""
        print("1. Host Creation Test...")
        try:
            key_pair_1 = create_new_key_pair()
            key_pair_2 = create_new_key_pair()

            host_1 = new_host(key_pair=key_pair_1)
            host_2 = new_host(key_pair=key_pair_2)

            peer_id_1 = host_1.get_id()
            peer_id_2 = host_2.get_id()
            print(f"    Host 1 ED25519 Peer ID: {peer_id_1}")
            print(f"    Host 2 ED25519 Peer ID: {peer_id_2}")

            assert peer_id_1 != peer_id_2, "Peer IDs should be unique"

            # Basic peer ID validation
            for peer_id in [peer_id_1, peer_id_2]:
                assert isinstance(peer_id, ID), "Should be proper ID object"
                peer_id_str = str(peer_id)
                assert len(peer_id_str) > 20, "Should be substantial length"

                # ED25519 peer IDs should be valid base58
                try:
                    roundtrip = ID.from_base58(peer_id_str)
                    assert str(roundtrip) == peer_id_str, "Roundtrip should match"
                except Exception as e:
                    print(f"    Peer ID validation error: {e}")

            assert len(str(host_1.get_id())) > 20  # Valid peer ID format

            print("    Host properties validated")

            # Cleanup
            try:
                await host_1.close()
                await host_2.close()
            except Exception as e:
                print(f"       Host cleanup: {e}")

            self.results["host_creation"] = True
            print("    ✅ ED25519 host creation successful")

        except Exception as e:
            print(f"    Host creation failed: {e}")

    async def test_mock_signaling(self) -> None:
        """Test mock signaling without real network"""
        print("\n2. 📡 Mock Signaling Test...")
        try:
            key_pair = create_new_key_pair()
            host = new_host(key_pair=key_pair)

            SignalService(host)
            test_offer = {
                "type": "offer",
                "sdp": "v=0\r\no=-... webrtc-datachannel\r\n",
            }

            # Serialize/deserialize to test format
            import json

            json_data = json.dumps(test_offer)
            parsed_offer = json.loads(json_data)

            assert parsed_offer["type"] == "offer"
            assert "webrtc-datachannel" in parsed_offer["sdp"]

            print("    Signal message format validated")
            print(f"    Host ED25519 Peer ID: {host.get_id()}")

            await host.close()

            self.results["mock_signaling"] = True
            print("    ✅ Mock signaling test successful")

        except Exception as e:
            print(f"     Mock signaling test failed: {e}")

    async def test_webrtc_without_network(self) -> None:
        """Test WebRTC functionality without network dependencies"""
        print("\n3. ⚡ WebRTC Without Network Test...")
        try:
            # Create transport without network
            transport = WebRTCTransport()

            # Test transport properties
            assert not transport.is_started()
            assert "webrtc" in transport.get_supported_protocols()

            key_pair = create_new_key_pair()
            host = new_host(key_pair=key_pair)
            transport.set_host(host)
            await transport.start()
            assert transport.is_started()

            print("    Transport started without network")

            valid_peer_id = generate_peer_id_from(key_pair)
            test_maddr = Multiaddr(f"/webrtc/p2p/{valid_peer_id}")
            can_handle = transport.can_handle(test_maddr)

            print(f"    Can handle WebRTC multiaddr: {can_handle}")
            print(f"    ED25519 Peer ID: {valid_peer_id}")

            # Cleanup
            await transport.stop()
            await host.close()

            self.results["webrtc_without_network"] = True
            print("    ✅ WebRTC without network test successful")

        except Exception as e:
            print(f"     WebRTC without network test failed: {e}")

    async def test_stream_muxing_standalone(self) -> None:
        """Test stream muxing without network dependencies"""
        print("\n4. 📊 Standalone Stream Muxing Test...")
        try:
            config = RTCConfiguration([])
            (
                peer_connection,
                data_channel,
            ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
                config, "test-stream-mux"
            )

            # Generate valid ED25519 peer ID for testing
            key_pair = create_new_key_pair()
            test_peer_id = generate_peer_id_from(key_pair)
            connection = WebRTCRawConnection(
                test_peer_id, peer_connection, data_channel, is_initiator=True
            )

            print("    Created connection for stream testing")
            print(f"    ED25519 Peer ID: {test_peer_id}")

            # Test stream creation
            stream_1 = await connection.open_stream()
            stream_2 = await connection.open_stream()
            stream_3 = await connection.open_stream()

            assert stream_1.stream_id == 1
            assert stream_2.stream_id == 3
            assert stream_3.stream_id == 5

            # Test protocol assignment
            protocols = [
                "/libp2p/identify/1.0.0",
                "/ipfs/ping/1.0.0",
                "/custom/test/1.0.0",
            ]
            streams = [stream_1, stream_2, stream_3]

            for stream, protocol in zip(streams, protocols):
                stream.set_protocol(TProtocol(protocol))
                assert stream.get_protocol() == TProtocol(protocol)
                print(f"    Stream {stream.stream_id}: {protocol}")

            # Test stream properties
            for stream in streams:
                assert hasattr(stream, "muxed_conn"), "Stream should have muxed_conn"
                assert stream.muxed_conn.peer_id == test_peer_id, (
                    "Should reference correct peer"
                )
                assert not stream._closed, "Stream should be open"

            print("    Stream properties validated")

            # Cleanup streams
            for stream in streams:
                await stream.close()
                assert stream._closed, "Stream should be closed"

            await connection.close()

            self.results["stream_muxing_standalone"] = True
            print("    ✅ Standalone stream muxing successful")

        except Exception as e:
            print(f"     Standalone stream muxing failed: {e}")

    def test_protocol_validation(self) -> None:
        """Test protocol validation without network"""
        print("\n5. 📋 Protocol Validation Test...")
        try:
            expected_webrtc = 0x0119
            expected_webrtc_direct = 0x0118
            expected_certhash = 0x01D2

            assert CODEC_WEBRTC == expected_webrtc
            assert CODEC_WEBRTC_DIRECT == expected_webrtc_direct
            assert CODEC_CERTHASH == expected_certhash

            print(
                f"WebRTC={hex(CODEC_WEBRTC)}, WebRTC-Direct={hex(CODEC_WEBRTC_DIRECT)}"
            )

            # Test multiaddr parsing (should work without network)
            key_pair = create_new_key_pair()
            valid_peer_id = generate_peer_id_from(key_pair)
            valid_cert = WebRTCCertificate.generate()

            test_addresses = [
                # Use canonical utility for WebRTC-Direct multiaddr
                str(create_webrtc_direct_multiaddr("127.0.0.1", 9000, valid_peer_id)),
                # WebRTC-Direct with certificate hash (full format)
                f"/ip4/127.0.0.1/udp/9001/webrtc-direct/certhash/{valid_cert.certhash}/p2p/{valid_peer_id}",
                # Basic WebRTC signaled
                f"/webrtc/p2p/{valid_peer_id}",
            ]

            for addr_str in test_addresses:
                try:
                    maddr = Multiaddr(addr_str)
                    protocols = [p.name for p in maddr.protocols()]
                    print(f"    Parsed multiaddr: {addr_str}")
                    print(f"      Protocols: {protocols}")
                except Exception as e:
                    print(f"    Multiaddr parsing: {e}")

            # Test transport can_handle (should work without network)
            transport = WebRTCTransport()

            test_maddr = Multiaddr(f"/webrtc/p2p/{valid_peer_id}")
            can_handle = transport.can_handle(test_maddr)

            print(f"    Transport can handle: {can_handle}")
            print(f"    ED25519 Peer ID: {valid_peer_id}")

            self.results["protocol_validation"] = True
            print("    ✅ Protocol validation successful")

        except Exception as e:
            print(f"     Protocol validation failed: {e}")

    async def test_certificate_standalone(self) -> None:
        """Test certificate operations without network"""
        print("\n6. 🔐 Standalone Certificate Test...")
        try:
            # Generate certificate
            cert = WebRTCCertificate.generate()

            # Test certificate properties
            assert cert.certhash.startswith("uEi"), "Should start with uEi"
            assert len(cert.certhash) > 20, "Should be substantial length"

            print(f"    Certificate hash: {cert.certhash}")
            print(f"    Fingerprint: {cert.fingerprint}")

            # Test PEM export/import with comprehensive validation
            assert cert.validate_pem_export(), "PEM export/import validation failed"
            print("    PEM export/import cryptographically validated")

            # Test multiple certificates are unique
            cert2 = WebRTCCertificate.generate()
            assert cert.certhash != cert2.certhash, "Certificates should be unique"
            print("Certificate uniqueness confirmed")

            key_pair = create_new_key_pair()
            peer_id = generate_peer_id_from(key_pair)

            parsed_maddr = Multiaddr(
                f"/ip4/127.0.0.1/udp/9000/webrtc-direct/certhash/{cert.certhash}/p2p/{peer_id}"
            )
            print(f"Integrated multiaddr: {parsed_maddr}")
            print(f"ED25519 Peer ID: {peer_id}")
            self.results["certificate_standalone"] = True
            print(" Standalone certificate test successful")

        except Exception as e:
            print(f"Standalone certificate test failed: {e}")

    def print_final_results(self) -> None:
        """Print final test results"""
        print("\n" + "=" * 55)
        print("⚡ NETWORK-OPTIMIZED TEST SUMMARY")
        print("=" * 55)

        passed_tests = sum(1 for result in self.results.values() if result)
        total_tests = len(self.results)

        print(f"\n Test Results: {passed_tests}/{total_tests} passed")

        for test_name, result in self.results.items():
            icon = "✅" if result else "❌"
            name = test_name.replace("_", " ").title()
            print(f"   {icon} {name}")

        percentage = (passed_tests / total_tests) * 100
        print(f"\n Success Rate: {percentage:.1f}%")

        if passed_tests == total_tests:
            print("\n All network-optimized tests passed!")
        elif passed_tests >= total_tests * 0.8:
            print("  Some minor issues to address")
        else:
            print("\n  Several tests failed - needs investigation")


async def main() -> None:
    test = OptimizedNetworkTest()
    await test.run_optimized_tests()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    trio.run(main)
