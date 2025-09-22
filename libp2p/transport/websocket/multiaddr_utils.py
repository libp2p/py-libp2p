"""
WebSocket multiaddr parsing utilities.
"""

from typing import NamedTuple

from multiaddr import Multiaddr
from multiaddr.protocols import Protocol


class ParsedWebSocketMultiaddr(NamedTuple):
    """Parsed WebSocket multiaddr information."""

    is_wss: bool
    sni: str | None
    rest_multiaddr: Multiaddr


def parse_websocket_multiaddr(maddr: Multiaddr) -> ParsedWebSocketMultiaddr:
    """
    Parse a WebSocket multiaddr and extract security information.

    :param maddr: The multiaddr to parse
    :return: Parsed WebSocket multiaddr information
    :raises ValueError: If the multiaddr is not a valid WebSocket multiaddr
    """
    # First validate that this is a valid WebSocket multiaddr
    if not is_valid_websocket_multiaddr(maddr):
        raise ValueError(f"Not a valid WebSocket multiaddr: {maddr}")

    protocols = list(maddr.protocols())

    # Find the WebSocket protocol and check for security
    is_wss = False
    sni = None
    ws_index = -1
    tls_index = -1
    sni_index = -1

    # Find protocol indices
    for i, protocol in enumerate(protocols):
        if protocol.name == "ws":
            ws_index = i
        elif protocol.name == "wss":
            ws_index = i
            is_wss = True
        elif protocol.name == "tls":
            tls_index = i
        elif protocol.name == "sni":
            sni_index = i
            sni = protocol.value

    if ws_index == -1:
        raise ValueError("Not a WebSocket multiaddr")

    # Handle /wss protocol (convert to /tls/ws internally)
    if is_wss and tls_index == -1:
        # Convert /wss to /tls/ws format
        # Remove /wss to get the base multiaddr
        without_wss = maddr.decapsulate(Multiaddr("/wss"))
        return ParsedWebSocketMultiaddr(
            is_wss=True, sni=None, rest_multiaddr=without_wss
        )

    # Handle /tls/ws and /tls/sni/.../ws formats
    if tls_index != -1:
        is_wss = True
        # Extract the base multiaddr (everything before /tls)
        # For /ip4/127.0.0.1/tcp/8080/tls/ws, we want /ip4/127.0.0.1/tcp/8080
        # Use multiaddr methods to properly extract the base
        rest_multiaddr = maddr
        # Remove /tls/ws or /tls/sni/.../ws from the end
        if sni_index != -1:
            # /tls/sni/example.com/ws format
            rest_multiaddr = rest_multiaddr.decapsulate(Multiaddr("/ws"))
            rest_multiaddr = rest_multiaddr.decapsulate(Multiaddr(f"/sni/{sni}"))
            rest_multiaddr = rest_multiaddr.decapsulate(Multiaddr("/tls"))
        else:
            # /tls/ws format
            rest_multiaddr = rest_multiaddr.decapsulate(Multiaddr("/ws"))
            rest_multiaddr = rest_multiaddr.decapsulate(Multiaddr("/tls"))
        return ParsedWebSocketMultiaddr(
            is_wss=is_wss, sni=sni, rest_multiaddr=rest_multiaddr
        )

    # Regular /ws multiaddr - remove /ws and any additional protocols
    rest_multiaddr = maddr.decapsulate(Multiaddr("/ws"))
    return ParsedWebSocketMultiaddr(
        is_wss=False, sni=None, rest_multiaddr=rest_multiaddr
    )


def is_valid_websocket_multiaddr(maddr: Multiaddr) -> bool:
    """
    Validate that a multiaddr has a valid WebSocket structure.

    :param maddr: The multiaddr to validate
    :return: True if valid WebSocket structure, False otherwise
    """
    try:
        # WebSocket multiaddr should have structure like:
        # /ip4/127.0.0.1/tcp/8080/ws (insecure)
        # /ip4/127.0.0.1/tcp/8080/wss (secure)
        # /ip4/127.0.0.1/tcp/8080/tls/ws (secure with TLS)
        # /ip4/127.0.0.1/tcp/8080/tls/sni/example.com/ws (secure with SNI)
        protocols: list[Protocol] = list(maddr.protocols())

        # Must have at least 3 protocols: network (ip4/ip6/dns4/dns6) + tcp + ws/wss
        if len(protocols) < 3:
            return False

        # First protocol should be a network protocol (ip4, ip6, dns, dns4, dns6)
        if protocols[0].name not in ["ip4", "ip6", "dns", "dns4", "dns6"]:
            return False

        # Second protocol should be tcp
        if protocols[1].name != "tcp":
            return False

        # Check for valid WebSocket protocols
        ws_protocols = ["ws", "wss"]
        tls_protocols = ["tls"]
        sni_protocols = ["sni"]

        # Find the WebSocket protocol
        ws_protocol_found = False
        tls_found = False
        # sni_found = False  # Not used currently

        for i, protocol in enumerate(protocols[2:], start=2):
            if protocol.name in ws_protocols:
                ws_protocol_found = True
                break
            elif protocol.name in tls_protocols:
                tls_found = True
            elif protocol.name in sni_protocols:
                pass  # sni_found = True  # Not used in current implementation

        if not ws_protocol_found:
            return False

        # Validate protocol sequence
        # For /ws: network + tcp + ws
        # For /wss: network + tcp + wss
        # For /tls/ws: network + tcp + tls + ws
        # For /tls/sni/example.com/ws: network + tcp + tls + sni + ws

        # Check if it's a simple /ws or /wss
        if len(protocols) == 3:
            return protocols[2].name in ["ws", "wss"]

        # Check for /tls/ws or /tls/sni/.../ws patterns
        if tls_found:
            # Must end with /ws (not /wss when using /tls)
            if protocols[-1].name != "ws":
                return False

            # Check for valid TLS sequence
            tls_index = None
            for i, protocol in enumerate(protocols[2:], start=2):
                if protocol.name == "tls":
                    tls_index = i
                    break

            if tls_index is None:
                return False

            # After tls, we can have sni, then ws
            remaining_protocols = protocols[tls_index + 1 :]
            if len(remaining_protocols) == 1:
                # /tls/ws
                return remaining_protocols[0].name == "ws"
            elif len(remaining_protocols) == 2:
                # /tls/sni/example.com/ws
                return (
                    remaining_protocols[0].name == "sni"
                    and remaining_protocols[1].name == "ws"
                )
            else:
                return False

        # If we have more than 3 protocols but no TLS, check for valid continuations
        # Allow additional protocols after the WebSocket protocol (like /p2p)
        valid_continuations = ["p2p"]

        # Find the WebSocket protocol index
        ws_index = None
        for i, protocol in enumerate(protocols):
            if protocol.name in ["ws", "wss"]:
                ws_index = i
                break

        if ws_index is not None:
            # Check protocols after the WebSocket protocol
            for i in range(ws_index + 1, len(protocols)):
                if protocols[i].name not in valid_continuations:
                    return False

        return True

    except Exception:
        return False
