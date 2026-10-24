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


class SecurityProtocolDowngrade(NoiseFailure):
    """
    Raised when the negotiated security protocol is not the one the two peers'
    signed protocol lists imply.

    multistream-select runs unauthenticated and in plaintext, so an on-path
    attacker can strip a proposal or forge an ``na`` to push both peers onto a
    weaker encrypter. Transcript binding has each peer sign its configured
    protocol list inside the encrypted handshake payload, bound to the Noise
    transcript hash, and both peers then recompute the outcome the negotiation
    should have produced. This error is distinguishable from an ordinary
    handshake failure so that callers can tell a downgrade from a peer that
    simply could not complete the handshake.
    """


class HandshakeMalformed(NoiseFailure):
    """
    Raised when a handshake message is truncated, oversized or otherwise
    malformed.

    Parsing is fail-closed: the message is rejected before any field is used,
    so no attacker-chosen slice reaches a cryptographic primitive. This also
    keeps backend exceptions (PyNaCl, ``cryptography``, ``struct``) from
    crossing the ``ISecureTransport`` boundary as themselves.
    """
