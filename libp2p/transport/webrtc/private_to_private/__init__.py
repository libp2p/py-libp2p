"""
Private-to-private WebRTC transport implementation.

Uses circuit relays for signaling and establishes direct WebRTC connections.
"""

from .transport import WebRTCTransport

__all__ = ["WebRTCTransport"]
