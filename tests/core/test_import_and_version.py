def test_import_and_version():
    import libp2p

    assert isinstance(libp2p.__version__, str)
