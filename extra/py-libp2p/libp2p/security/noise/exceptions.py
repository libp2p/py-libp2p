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
