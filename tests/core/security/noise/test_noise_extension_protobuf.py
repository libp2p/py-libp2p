from libp2p.security.noise.pb import noise_pb2 as noise_pb


def test_noise_extensions_serialization():
    # Test NoiseExtensions
    ext = noise_pb.NoiseExtensions()
    ext.stream_muxers.append("/mplex/6.7.0")
    ext.stream_muxers.append("/yamux/1.0.0")

    # Serialize and deserialize
    data = ext.SerializeToString()
    ext2 = noise_pb.NoiseExtensions.FromString(data)
    assert list(ext2.stream_muxers) == ["/mplex/6.7.0", "/yamux/1.0.0"]
