from libp2p.security.exceptions import (
    HandshakeFailure,
)


class NoiseFailure(HandshakeFailure):
    pass


class HandshakeHasNotFinished(NoiseFailure):
    pass


class InvalidSignature(NoiseFailure):
    pass


class NoiseStateError(NoiseFailure):
    """
    Raised when anything goes wrong in the noise state in `noiseprotocol`
    package.
    """


class PeerIDMismatchesPubkey(NoiseFailure):
    pass


class HandshakeMalformed(NoiseFailure):
    """
    Raised when a handshake message is truncated, oversized or otherwise
    malformed.

    Parsing is fail-closed: the message is rejected before any field is used,
    so no attacker-chosen slice reaches a cryptographic primitive. This also
    keeps backend exceptions (PyNaCl, ``cryptography``, ``struct``) from
    crossing the ``ISecureTransport`` boundary as themselves.
    """
