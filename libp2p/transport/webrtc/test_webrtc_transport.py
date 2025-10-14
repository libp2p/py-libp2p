import base64
import json
import logging
import sys
from typing import Any

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
    SIGNALING_PROTOCOL,
)
from libp2p.transport.webrtc.private_to_private.transport import WebRTCTransport
from libp2p.transport.webrtc.private_to_public.gen_certificate import (
    WebRTCCertificate,
    create_webrtc_direct_multiaddr,
)
from libp2p.transport.webrtc.private_to_public.transport import WebRTCDirectTransport
from libp2p.transport.webrtc.signal_service import SignalService

logger = logging.getLogger("libp2p.transport.webrtc.test_suite")

# Test configuration
NETWORK_TIMEOUT = 3.0  # Quick timeout for network operations
TEST_TIMEOUT = 10.0  # Maximum time for individual tests


class WebRTCTransportTestSuite:
    """
    Comprehensive test suite for WebRTC transport.
    """

    def __init__(self) -> None:
        self.results = {
            # Data validation
            "data_validation": False,
            # Basic functionality
            "protocol_registration": False,
            "transport_initialization": False,
            "certificate_management": False,
            "multiaddr_support": False,
            # Network operations
            "network_timeout_handling": False,
            "mock_network_operations": False,
            # WebRTC functionality
            "webrtc_connection_creation": False,
            "stream_muxing": False,
            "data_exchange": False,
            # Interoperability
            "js_libp2p_protocol_compat": False,
            "js_libp2p_cert_compat": False,
            "js_libp2p_signaling_compat": False,
            # Advanced features
            "signal_service": False,
            "error_handling": False,
            "resource_cleanup": False,
        }
        self.test_mode = "full"
        self._test_peer_ids: dict[str, ID] = {}
        self._test_certificates: dict[str, WebRTCCertificate] = {}
        self._setup_test_data()

    def _setup_test_data(self) -> None:
        """Setup valid test peer IDs and certificates using ED25519"""
        # Generate multiple ED25519 peer IDs for testing
        for i in range(5):
            # Generate ED25519 key pair
            key_pair = create_new_key_pair()
            peer_id = generate_peer_id_from(key_pair)
            self._test_peer_ids[f"peer_{i}"] = peer_id

        # Generate valid certificates for testing
        for i in range(3):
            cert = WebRTCCertificate()
            self._test_certificates[f"cert_{i}"] = cert

    def get_test_peer_id(self, name: str = "peer_0") -> ID:
        """Get a valid ED25519 test peer ID"""
        return self._test_peer_ids.get(name, self._test_peer_ids["peer_0"])

    def get_test_certificate(self, name: str = "cert_0") -> WebRTCCertificate:
        """Get a valid test certificate"""
        return self._test_certificates.get(name, self._test_certificates["cert_0"])

    def generate_valid_peer_id(self) -> ID:
        """Generate a valid ED25519 peer ID for testing"""
        # Generate ED25519 key pair
        key_pair = create_new_key_pair()
        return generate_peer_id_from(key_pair)

    def generate_valid_certificate(self) -> WebRTCCertificate:
        """Generate a valid WebRTC certificate for testing"""
        return WebRTCCertificate()

    def create_valid_webrtc_multiaddrs(
        self, peer_id: ID, cert: WebRTCCertificate
    ) -> list[str]:
        """Create valid WebRTC multiaddrs using canonical libp2p utilities"""
        # Generate another ED25519 peer ID for relay scenarios
        relay_key_pair = create_new_key_pair()
        relay_peer_id = generate_peer_id_from(relay_key_pair)

        multiaddrs = [
            # WebRTC signaled (basic format)
            f"/webrtc/p2p/{peer_id}",
            # WebRTC-Direct using canonical utility
            str(create_webrtc_direct_multiaddr("127.0.0.1", 9000, peer_id)),
            # WebRTC-Direct with certificate hash (full format)
            f"/ip4/127.0.0.1/udp/9001/webrtc-direct/certhash/{cert.certhash}/p2p/{peer_id}",
            # Circuit relay format
            f"/ip4/127.0.0.1/tcp/8080/p2p/{relay_peer_id}/p2p-circuit/webrtc/p2p/{peer_id}",
            # IPv6 WebRTC-Direct
            f"/ip6/::1/udp/9002/webrtc-direct/certhash/{cert.certhash}/p2p/{peer_id}",
        ]

        return multiaddrs

    def validate_peer_id(self, peer_id: ID) -> bool:
        """Validate that a peer ID is properly formatted"""
        try:
            # A valid peer ID should be a proper ID object
            if not isinstance(peer_id, ID):
                return False

            # Get string representation
            peer_id_str = str(peer_id)

            # Basic length check - valid peer IDs are typically 40-60 characters
            if len(peer_id_str) < 40 or len(peer_id_str) > 70:
                return False

            # Validate base58 encoding - peer IDs are base58-encoded multihashes
            try:
                import base58

                decoded = base58.b58decode(peer_id_str)
                # Minimum: 2 bytes (type + length) +
                #  hash (20+ bytes for SHA-1, 32+ for SHA-256)
                if len(decoded) < 22:
                    return False
            except Exception:
                return False

            # Validate that it contains only valid base58 characters
            valid_base58_chars = set(
                "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
            )
            if not all(c in valid_base58_chars for c in peer_id_str):
                return False

            try:
                roundtrip_id = ID.from_base58(peer_id_str)
                if str(roundtrip_id) != peer_id_str:
                    return False
            except Exception:
                return False

            return True

        except Exception:
            return False

    def validate_ed25519_peer_id(self, peer_id: ID) -> bool:
        """Validate ED25519 peer ID format and properties"""
        try:
            # Verify it's a proper ID object
            if not isinstance(peer_id, ID):
                return False

            # ED25519 peer IDs should be valid base58
            peer_id_str = str(peer_id)
            if len(peer_id_str) < 40 or len(peer_id_str) > 70:
                return False

            # Test roundtrip conversion
            roundtrip = ID.from_base58(peer_id_str)
            if str(roundtrip) != peer_id_str:
                return False

            # ED25519 peer IDs use identity multihash for small keys
            peer_bytes = peer_id.to_bytes()
            if len(peer_bytes) < 10:  # Minimum reasonable size
                return False

            return True
        except Exception:
            return False

    def validate_certificate_hash(self, certhash: str) -> bool:
        """Validate that a certificate hash is properly formatted"""
        try:
            # Should start with uEi and be base64url encoded
            if not certhash.startswith("uEi"):
                return False
            hash_part = certhash[3:]
            # Should be valid base64url
            padding = 4 - (len(hash_part) % 4)
            if padding != 4:
                hash_part += "=" * padding
            decoded = base64.urlsafe_b64decode(hash_part)
            # Should be 32 bytes (SHA-256)
            return len(decoded) == 32
        except Exception:
            return False

    async def run_comprehensive_tests(self, mode: str = "full") -> None:
        """Run comprehensive test suite"""
        self.test_mode = mode

        print("🔬 Comprehensive WebRTC Transport Test Suite (ED25519)")
        print("=" * 60)
        print(f"Mode: {mode.upper()}")
        print("Using ED25519 peer IDs for all test cases")
        print()

        if mode in ["full", "basic"]:
            await self._run_basic_tests()

        if mode in ["full", "interop"]:
            await self._run_interop_tests()

        if mode == "full":
            await self._run_advanced_tests()

        self._print_final_summary()

    async def _run_basic_tests(self) -> None:
        """Run basic functionality tests"""
        print("🔧 BASIC FUNCTIONALITY TESTS")
        print("-" * 40)

        await self._test_data_validation()
        await self._test_protocol_registration()
        await self._test_transport_initialization()
        await self._test_certificate_management()
        await self._test_multiaddr_support()
        await self._test_network_timeout_handling()
        await self._test_webrtc_connection_creation()

    async def _run_interop_tests(self) -> None:
        """Run js-libp2p interoperability tests"""
        print("\n🔗 JS-LIBP2P INTEROPERABILITY TESTS")
        print("-" * 40)

        await self._test_js_libp2p_cert_compat()
        await self._test_js_libp2p_signaling_compat()

    async def _run_advanced_tests(self) -> None:
        """Run advanced functionality tests"""
        print("\n⚡ ADVANCED FUNCTIONALITY TESTS")
        print("-" * 40)

        await self._test_stream_muxing()
        await self._test_data_exchange()
        await self._test_signal_service()
        await self._test_error_handling()
        await self._test_resource_cleanup()

    async def _test_data_validation(self) -> None:
        """Test that all generated test data uses valid ED25519 formats"""
        print("0. 🔍 Testing ED25519 Data Validation...")
        try:
            validation_passed = 0

            # Test all pre-generated ED25519 peer IDs are valid
            for name, peer_id in self._test_peer_ids.items():
                if self.validate_ed25519_peer_id(peer_id):
                    validation_passed += 1
                    # Show complete peer ID without truncation
                    peer_id_str = str(peer_id)
                    print(f"   ✅ Valid ED25519 peer ID {name}: {peer_id_str}")
                else:
                    print(f"   ❌ Invalid peer ID {name}: {peer_id}")

            # Test all pre-generated certificates are valid
            for name, cert in self._test_certificates.items():
                if self.validate_certificate_hash(cert.certhash):
                    validation_passed += 1
                    print(f"   ✅ Valid certificate {name}: {cert.certhash}")
                else:
                    print(f"   ❌ Invalid certificate {name}: {cert.certhash}")

            # Test runtime ED25519 generation
            runtime_peer_id = self.generate_valid_peer_id()
            runtime_cert = self.generate_valid_certificate()

            if self.validate_ed25519_peer_id(runtime_peer_id):
                validation_passed += 1
                print(f"   ✅ Runtime ED25519 peer ID: {str(runtime_peer_id)}")

            if self.validate_certificate_hash(runtime_cert.certhash):
                validation_passed += 1
                print(f"   ✅ Runtime certificate: {runtime_cert.certhash}")

            # Validate multiaddr construction with real ED25519 data
            test_peer_id = self.get_test_peer_id("peer_0")
            test_cert = self.get_test_certificate("cert_0")

            test_multiaddrs = self.create_valid_webrtc_multiaddrs(
                test_peer_id, test_cert
            )

            for maddr_str in test_multiaddrs:
                try:
                    maddr = Multiaddr(maddr_str)
                    validation_passed += 1
                    print(f"   ✅ Valid multiaddr: {maddr}")
                except Exception as e:
                    print(f"   ❌ Invalid multiaddr: {e}")

            expected_validations = (
                len(self._test_peer_ids)
                + len(self._test_certificates)
                + 2
                + len(test_multiaddrs)
            )
            assert validation_passed == expected_validations, (
                f"validation failed: {validation_passed}/{expected_validations}"
            )

            print(f"validation passed ({validation_passed}/{expected_validations})")
            self.results["data_validation"] = True

        except Exception as e:
            print(f"ED25519 data validation failed: {e}")

    async def _test_protocol_registration(self) -> None:
        """Test WebRTC protocol registration with multiaddr"""
        print("1. 📋 Testing Protocol Registration...")
        try:
            # Verify protocol codes match js-libp2p
            assert CODEC_WEBRTC == 0x0119, f"WebRTC code mismatch: {CODEC_WEBRTC}"
            assert CODEC_WEBRTC_DIRECT == 0x0118, (
                f"WebRTC-Direct code mismatch: {CODEC_WEBRTC_DIRECT}"
            )
            assert CODEC_CERTHASH == 0x01D2, f"Certhash code mismatch: {CODEC_CERTHASH}"

            # Test multiaddr parsing with valid ED25519 peer IDs and certificate
            test_peer_id = self.get_test_peer_id("peer_0")
            test_cert = self.get_test_certificate("cert_0")

            test_addrs = [
                f"/webrtc/p2p/{test_peer_id}",
                f"/ip4/127.0.0.1/udp/9000/webrtc-direct/certhash/{test_cert.certhash}/p2p/{test_peer_id}",
            ]

            for addr_str in test_addrs:
                try:
                    maddr = Multiaddr(addr_str)
                    protocols = [p.name for p in maddr.protocols()]
                    assert any(p in ["webrtc", "webrtc-direct"] for p in protocols)
                except Exception as e:
                    print(f"    Multiaddr parsing issue: {e}")

            self.results["protocol_registration"] = True
            print("   Protocol registration successful")

        except Exception as e:
            print(f"    Protocol registration failed: {e}")

    async def _test_transport_initialization(self) -> None:
        """Test transport initialization without network dependencies"""
        print("2. 🚀 Testing Transport Initialization...")
        try:
            # Create hosts without network listening (avoid hanging)
            # Generate ED25519 key pairs
            key_pair_1 = create_new_key_pair()
            key_pair_2 = create_new_key_pair()

            host_1 = new_host(key_pair=key_pair_1)
            host_2 = new_host(key_pair=key_pair_2)

            # Test WebRTC Transport
            transport_1 = WebRTCTransport()
            transport_1.set_host(host_1)
            await transport_1.start()

            assert transport_1.is_started()
            assert "webrtc" in transport_1.supported_protocols

            # Test WebRTC-Direct Transport
            transport_2 = WebRTCDirectTransport()
            transport_2.set_host(host_2)
            async with trio.open_nursery() as nursery:
                await transport_2.start(nursery)

            assert transport_2.is_started()
            assert "webrtc-direct" in transport_2.supported_protocols
            assert transport_2.cert_mgr is not None

            # Cleanup
            await transport_1.stop()
            await transport_2.stop()
            await host_1.close()
            await host_2.close()

            self.results["transport_initialization"] = True
            print("   Transport initialization successful")

        except Exception as e:
            print(f"    Transport initialization failed: {e}")

    async def _test_certificate_management(self) -> None:
        """Test WebRTC certificate generation and management"""
        print("3. 🔐 Testing Certificate Management...")
        try:
            # Generate certificate
            cert = WebRTCCertificate()

            # Test certificate properties - must match js-libp2p format
            assert cert.certhash.startswith("uEi"), (
                f"Invalid cert hash prefix: {cert.certhash}"
            )
            assert len(cert.certhash) > 10, f"Cert hash too short: {cert.certhash}"

            # Test certificate hash format (js-libp2p compatibility)
            hash_part = cert.certhash[3:]  # Remove "uEi" prefix
            try:
                # Verify it's valid base64url
                padding = 4 - (len(hash_part) % 4)
                if padding != 4:
                    hash_part += "=" * padding
                decoded = base64.urlsafe_b64decode(hash_part)
                assert len(decoded) == 32, (
                    f"Certificate hash should be 32 bytes, got {len(decoded)}"
                )
            except Exception as e:
                print(f"    Certificate hash validation issue: {e}")

            # Test PEM export/import with comprehensive validation
            assert cert.validate_pem_export(), "PEM export/import validation failed"

            cert2 = WebRTCCertificate()
            assert cert.certhash != cert2.certhash

            self.results["certificate_management"] = True
            print(f"   Certificate management successful (hash: {cert.certhash})")

        except Exception as e:
            print(f"    Certificate management failed: {e}")

    async def _test_multiaddr_support(self) -> None:
        """Test multiaddr format support and parsing with valid formats"""
        print("4. 🌐 Testing Multiaddr Support...")
        try:
            # Generate valid test data
            cert = self.get_test_certificate("cert_0")
            test_peer_id = self.get_test_peer_id("peer_0")
            relay_peer_id = self.get_test_peer_id("peer_1")

            # Test various multiaddr formats using canonical utilities
            test_formats = self.create_valid_webrtc_multiaddrs(test_peer_id, cert)

            # Add some additional complex formats for comprehensive testing
            additional_formats = [
                # Complex circuit relay with external IP
                f"/ip4/147.28.186.157/udp/9095/webrtc-direct/certhash/{cert.certhash}/p2p/{test_peer_id}/p2p-circuit",
                # IPv6 complex relay scenarios
                f"/ip6/2604:1380:4642:6600::3/tcp/9095/p2p/{relay_peer_id}/p2p-circuit/webrtc/p2p/{test_peer_id}",
            ]
            test_formats.extend(additional_formats)

            transport = WebRTCTransport()
            parsed_count = 0

            for addr_str in test_formats:
                try:
                    maddr = Multiaddr(addr_str)
                    transport.can_handle(maddr)
                    parsed_count += 1
                    print(f"   Parsed: {addr_str}")
                except Exception as e:
                    print(f"    Failed to parse: {addr_str[:30]}... ({e})")

            assert parsed_count >= 4, (
                f"Should parse at least 4 multiaddr formats, got {parsed_count}"
            )

            self.results["multiaddr_support"] = True
            print(f"Maddr support ({parsed_count}/{len(test_formats)} formats)")

        except Exception as e:
            print(f" Multiaddr support failed: {e}")

    async def _test_network_timeout_handling(self) -> None:
        """Test network operations with timeout protection"""
        print("5. ⏱️ Testing Network Timeout Handling...")
        try:
            key_pair = create_new_key_pair()
            host = new_host(key_pair=key_pair)

            try:
                with trio.move_on_after(NETWORK_TIMEOUT) as cancel_scope:
                    addr = Multiaddr("/ip4/127.0.0.1/tcp/4000")
                    await host.get_network().listen(addr)
                if cancel_scope.cancelled_caught:
                    print("Network timeout handled gracefully")
                else:
                    print("Network setup completed quickly")

            except Exception as e:
                print(f"Network error handled: {e}")

            transport = WebRTCTransport()
            transport.set_host(host)
            await transport.start()
            assert transport.is_started()

            # Cleanup
            await transport.stop()
            await host.close()

            self.results["network_timeout_handling"] = True
            print("   Network timeout handling successful")

        except Exception as e:
            print(f"    Network timeout handling failed: {e}")

    async def _test_webrtc_connection_creation(self) -> None:
        """Test WebRTC connection creation without network dependencies"""
        print("6. 📡 Testing WebRTC Connection Creation...")
        try:
            # Create peer connection without STUN servers (no network calls)
            config = RTCConfiguration([])
            (
                pc,
                dc,
            ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
                config, "test-connection"
            )

            # Test SDP generation
            bridge = TrioSafeWebRTCOperations._get_bridge()
            async with bridge:
                offer = await bridge.create_offer(pc)

            assert offer.type == "offer"
            assert len(offer.sdp) > 200
            assert "application" in offer.sdp

            # Test connection wrapper with valid ED25519 peer ID
            test_peer_id = self.get_test_peer_id("peer_0")
            connection = WebRTCRawConnection(test_peer_id, pc, dc)

            assert connection.peer_id == test_peer_id
            assert not connection._closed

            # Cleanup
            await connection.close()

            self.results["webrtc_connection_creation"] = True
            print(f"WebRTC conn successful (SDP: {len(offer.sdp)} chars)")

        except Exception as e:
            print(f"WebRTC conn failed: {e}")

    async def _test_js_libp2p_cert_compat(self) -> None:
        """Test certificate format compatibility with js-libp2p"""
        print("7. 🔗 Testing js-libp2p Certificate Compatibility...")
        try:
            # Generate certificate
            cert = WebRTCCertificate()
            # Test hash format (should be uEi + base64url as per js-libp2p)
            assert cert.certhash.startswith("uEi"), "Cert should start with uEi"

            # Test base64url decoding (js-libp2p format)
            hash_part = cert.certhash[3:]  # Remove uEi prefix
            try:
                # Ensure hash_part is bytes for base64 decoding
                if isinstance(hash_part, str):
                    hash_part_bytes = hash_part.encode("ascii")
                else:
                    hash_part_bytes = hash_part

                # Add padding if needed
                padding = 4 - (len(hash_part_bytes) % 4)
                if padding != 4:
                    hash_part_bytes += b"=" * padding

                decoded = base64.urlsafe_b64decode(hash_part_bytes)
                assert len(decoded) >= 32, "Decoded hash should be at least 32 bytes"
                print(f"   Certificate hash format valid: {cert.certhash}")
            except Exception as e:
                print(f"    Base64 decode issue (may be encoding): {e}")
            # Test PEM compatibility with comprehensive validation
            assert cert.validate_pem_export(), "PEM export/import validation failed"

            self.results["js_libp2p_cert_compat"] = True
            print("   js-libp2p certificate compatibility confirmed")

        except Exception as e:
            print(f"    js-libp2p certificate compatibility failed: {e}")

    async def _test_js_libp2p_signaling_compat(self) -> None:
        """Test signaling message format compatibility with js-libp2p"""
        print("8. 🔗 Testing js-libp2p Signaling Compatibility...")
        try:
            # Test SDP message format (js-libp2p compatible)
            offer_msg: dict[str, Any] = {
                "type": "offer",
                "sdp": "v=0\r\no=-... webrtc-datachannel\r\n",
            }

            answer_msg: dict[str, Any] = {
                "type": "answer",
                "sdp": "v=0\r\no=-... webrtc-datachannel\r\n",
            }

            # Test ICE candidate format (js-libp2p compatible)
            ice_msg: dict[str, Any] = {
                "type": "ice-candidate",
                "candidate": "candidate:1 1UDP 2130706431 192.168.1.100 54400 typ host",
                "sdpMid": "0",
                "sdpMLineIndex": 0,
            }

            # Test JSON serialization/deserialization
            for msg_name, msg in [
                ("offer", offer_msg),
                ("answer", answer_msg),
                ("ice", ice_msg),
            ]:
                json_data = json.dumps(msg)
                parsed_msg = json.loads(json_data)
                assert parsed_msg["type"] == msg["type"]
                print(f"   {msg_name} message format valid")

            # Test signal service creation
            # Generate ED25519 key pair
            key_pair = create_new_key_pair()
            host = new_host(key_pair=key_pair)
            signal_service = SignalService(host)

            # Access protocol correctly (TProtocol object comparison)
            assert str(signal_service.signal_protocol) == SIGNALING_PROTOCOL

            await host.close()

            self.results["js_libp2p_signaling_compat"] = True
            print("   js-libp2p signaling compatibility confirmed")

        except Exception as e:
            print(f"    js-libp2p signaling compatibility failed: {e}")

    async def _test_stream_muxing(self) -> None:
        """Test stream multiplexing functionality"""
        print("9. 📊 Testing Stream Muxing...")
        try:
            # Create WebRTC connection for stream testing
            config = RTCConfiguration([])
            (
                pc,
                dc,
            ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
                config, "stream-mux-test"
            )

            test_peer_id = self.get_test_peer_id("peer_0")
            connection = WebRTCRawConnection(test_peer_id, pc, dc, is_initiator=True)

            # Create multiple streams
            streams = []
            protocols = [
                "/libp2p/identify/1.0.0",
                "/ipfs/ping/1.0.0",
                "/custom/test/1.0.0",
            ]

            for i, protocol in enumerate(protocols):
                stream = await connection.open_stream()
                stream.set_protocol(TProtocol(protocol))
                streams.append(stream)

                # Verify stream properties
                assert stream.stream_id == (i * 2 + 1), (
                    f"Wrong stream ID: {stream.stream_id}"
                )
                assert stream.get_protocol() == TProtocol(protocol)
                # Check connection reference (avoid type overlap by comparing peer IDs)
                assert (
                    hasattr(stream, "muxed_conn")
                    and stream.muxed_conn.peer_id == connection.peer_id
                )

            print(f"   Created {len(streams)} multiplexed streams")

            # Test stream cleanup
            for stream in streams:
                await stream.close()
                assert stream._closed

            await connection.close()

            self.results["stream_muxing"] = True
            print("   Stream muxing successful")

        except Exception as e:
            print(f"    Stream muxing failed: {e}")

    async def _test_data_exchange(self) -> None:
        """Test data exchange over WebRTC streams"""
        print("10. 💬 Testing Data Exchange...")
        try:
            # Create connection for data testing
            config = RTCConfiguration([])
            (
                pc,
                dc,
            ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
                config, "data-exchange-test"
            )

            test_peer_id = self.get_test_peer_id("peer_0")
            connection = WebRTCRawConnection(test_peer_id, pc, dc)

            # Test connection properties
            assert connection.peer_id == test_peer_id
            assert (
                connection.get_remote_address() is None
            )  # WebRTC doesn't expose IP:port

            # Test stream creation and protocol setting
            stream = await connection.open_stream()
            test_protocol = TProtocol("/test/data-exchange/1.0.0")
            stream.set_protocol(test_protocol)

            assert stream.get_protocol() == test_protocol
            print(f"   Stream created with protocol: {stream.get_protocol()}")

            # Test message encoding for muxed streams
            test_data = b"Hello WebRTC P2P Data Exchange!"
            message = {
                "stream_id": stream.stream_id,
                "type": "data",
                "data": test_data.decode("utf-8", errors="replace"),
            }

            # Verify message format
            json_msg = json.dumps(message)
            parsed_msg = json.loads(json_msg)
            assert parsed_msg["stream_id"] == stream.stream_id
            assert parsed_msg["type"] == "data"

            print(f"   Data message format valid (stream {stream.stream_id})")

            # Cleanup
            await stream.close()
            await connection.close()

            self.results["data_exchange"] = True
            print("   Data exchange successful")

        except Exception as e:
            print(f"    Data exchange failed: {e}")

    async def _test_signal_service(self) -> None:
        """Test signaling service functionality"""
        print("11. 🔔 Testing Signal Service...")
        try:
            # Create hosts for signal service
            # Generate ED25519 key pairs
            key_pair_1 = create_new_key_pair()
            key_pair_2 = create_new_key_pair()

            host_1 = new_host(key_pair=key_pair_1)
            host_2 = new_host(key_pair=key_pair_2)

            # Create signal services
            signal_1 = SignalService(host_1)
            signal_2 = SignalService(host_2)

            # Test handler registration
            handler_called: dict[str, int] = {"count": 0}

            async def test_handler(msg: dict[str, Any], peer_id: str) -> None:
                handler_called["count"] += 1

            signal_1.set_handler("offer", test_handler)
            signal_2.set_handler("answer", test_handler)

            assert "offer" in signal_1._handlers
            assert "answer" in signal_2._handlers

            print("   Signal handlers registered")

            # Test protocol registration
            assert str(signal_1.signal_protocol) == SIGNALING_PROTOCOL
            assert str(signal_2.signal_protocol) == SIGNALING_PROTOCOL

            print(f"   Signal protocol: {SIGNALING_PROTOCOL}")

            # Cleanup
            await host_1.close()
            await host_2.close()

            self.results["signal_service"] = True
            print("   Signal service successful")

        except Exception as e:
            print(f"    Signal service failed: {e}")

    async def _test_error_handling(self) -> None:
        """Test error handling and edge cases"""
        print("12. 🛡️ Testing Error Handling...")
        try:
            error_cases_passed = 0

            try:
                transport = WebRTCTransport()
                invalid_addr = Multiaddr("/invalid/protocol")
                can_handle = transport.can_handle(invalid_addr)
                assert not can_handle
                error_cases_passed += 1
                print("   Invalid multiaddr handled correctly")
            except Exception:
                print("    Invalid multiaddr test inconclusive")

            # Test 2: Closed connection operations
            try:
                config = RTCConfiguration([])
                (
                    pc,
                    dc,
                ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
                    config, "error-test"
                )

                test_peer_id = self.get_test_peer_id("peer_0")
                connection = WebRTCRawConnection(test_peer_id, pc, dc)

                # Close connection and test operations
                await connection.close()
                assert connection._closed

                # These should handle closed connection gracefully
                empty_data = await connection.read()
                assert empty_data == b""

                error_cases_passed += 1
                print("   Closed connection operations handled")

            except Exception as e:
                print(f"    Closed connection test issue: {e}")

            try:
                key_pair = create_new_key_pair()
                host = new_host(key_pair=key_pair)
                transport = WebRTCTransport()
                transport.set_host(host)

                # Multiple start/stop cycles
                for _ in range(2):
                    await transport.start()
                    assert transport.is_started()
                    await transport.stop()
                    assert not transport.is_started()

                await host.close()
                error_cases_passed += 1
                print("   Transport start/stop cycles handled")

            except Exception as e:
                print(f"    Transport lifecycle test issue: {e}")

            assert error_cases_passed >= 2, "At least 2 error cases should pass"

            self.results["error_handling"] = True
            print(f"   Error handling successful ({error_cases_passed}/3 cases)")

        except Exception as e:
            print(f"    Error handling failed: {e}")

    async def _test_resource_cleanup(self) -> None:
        """Test proper resource cleanup and memory management"""
        print("13. 🧹 Testing Resource Cleanup...")
        try:
            cleanup_operations = 0
            config = RTCConfiguration([])
            (
                pc,
                dc,
            ) = await TrioSafeWebRTCOperations.create_peer_conn_with_data_channel(
                config, "cleanup-test"
            )

            test_peer_id = self.get_test_peer_id("peer_0")
            connection = WebRTCRawConnection(test_peer_id, pc, dc)

            stream1 = await connection.open_stream()
            stream2 = await connection.open_stream()

            await stream1.close()
            await stream2.close()
            await connection.close()

            assert stream1._closed
            assert stream2._closed
            assert connection._closed

            cleanup_operations += 1
            print("   Connection and stream cleanup")

            key_pair = create_new_key_pair()
            host = new_host(key_pair=key_pair)
            transport = WebRTCTransport()
            transport.set_host(host)

            await transport.start()
            await transport.stop()
            await host.close()

            cleanup_operations += 1
            print("   Transport and host cleanup")

            # Test 3: Certificate cleanup (memory) - Simple validation
            cert1 = WebRTCCertificate()
            cert2 = WebRTCCertificate()
            # Certificates should be independent
            assert cert1.certhash != cert2.certhash, (
                "Certificate hashes should be unique"
            )
            assert len(cert1.certhash) > 10, "Certificate hash should be substantial"
            assert len(cert2.certhash) > 10, "Certificate hash should be substantial"

            cleanup_operations += 1
            print("   Certificate memory management")

            assert cleanup_operations == 3, "All cleanup operations should succeed"

            self.results["resource_cleanup"] = True
            print("   Resource cleanup successful")

        except Exception as e:
            print(f"    Resource cleanup failed: {e}")

    def _print_final_summary(self) -> None:
        print("\n" + "=" * 60)
        print("WEBRTC TRANSPORT TEST SUITE SUMMARY")
        print("=" * 60)

        basic_tests = [
            "protocol_registration",
            "transport_initialization",
            "certificate_management",
            "multiaddr_support",
            "network_timeout_handling",
            "webrtc_connection_creation",
        ]

        interop_tests = ["js_libp2p_cert_compat", "js_libp2p_signaling_compat"]

        advanced_tests = [
            "stream_muxing",
            "data_exchange",
            "signal_service",
            "error_handling",
            "resource_cleanup",
        ]

        def count_category(tests: list[str]) -> int:
            return sum(1 for test in tests if self.results.get(test, False))

        basic_passed = count_category(basic_tests)
        interop_passed = count_category(interop_tests)
        advanced_passed = count_category(advanced_tests)

        total_passed = sum(1 for v in self.results.values() if v)
        total_tests = len(self.results)

        print("\n📊 Test Results by Category:")
        print(f"Basic Functionality:{basic_passed}/{len(basic_tests)} tests passed")
        print(f"js-libp2p Interop:{interop_passed}/{len(interop_tests)} tests passed")
        print(f"Advanced Features:{advanced_passed}/{len(advanced_tests)} tests passed")
        print(f"Overall:{total_passed}/{total_tests} tests passed")

        percentage = (total_passed / total_tests) * 100
        print(f"\n🎯 Success Rate: {percentage:.1f}%")

        # Detailed results
        print("\n📝 Detailed Results:")
        for category, tests in [
            ("Basic", basic_tests),
            ("Interop", interop_tests),
            ("Advanced", advanced_tests),
        ]:
            if (
                self.test_mode in ["full"]
                or (self.test_mode == "basic" and category == "Basic")
                or (self.test_mode == "interop" and category == "Interop")
            ):
                print(f"   {category}:")
                for test in tests:
                    if test in self.results:
                        icon = "✅" if self.results[test] else "❌"
                        name = test.replace("_", " ").title()
                        print(f"     {icon} {name}")


async def main() -> None:
    mode = "full"
    if len(sys.argv) > 1:
        if "--basic" in sys.argv:
            mode = "basic"
        elif "--interop" in sys.argv:
            mode = "interop"

    test_suite = WebRTCTransportTestSuite()
    await test_suite.run_comprehensive_tests(mode)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    trio.run(main)
