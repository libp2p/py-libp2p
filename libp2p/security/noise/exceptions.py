from libp2p.security.exceptions import HandshakeFailure


class NoiseFailure(HandshakeFailure):
    pass


class HandshakeHasNotFinished(NoiseFailure):
    pass
