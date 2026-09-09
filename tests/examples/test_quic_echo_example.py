def test_echo_quic_example():
    """Test that the QUIC echo example can be imported and has required functions."""
    from examples.echo import echo_quic

    assert hasattr(echo_quic, "main")
    assert hasattr(echo_quic, "run")
