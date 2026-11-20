QUIC: reject peer certificates whose libp2p TLS extension carries an invalid
proof-of-possession signature. ``PublicKey.verify()`` returns ``False`` rather than
raising, and the result was ignored, so a peer could claim any peer ID
(`GHSA-hrfr-7729-443m <https://github.com/libp2p/py-libp2p/security/advisories/GHSA-hrfr-7729-443m>`__).
