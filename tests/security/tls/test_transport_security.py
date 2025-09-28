from pathlib import Path

import pytest

from libp2p import generate_new_rsa_identity
from libp2p.security.tls.transport import TLSTransport
from tests.utils.factories import tls_conn_factory


def test_temp_files_cleanup():
    """Test that temporary files are properly cleaned up."""
    keypair = generate_new_rsa_identity()
    transport = TLSTransport(keypair)

    # Create SSL context which will create temp files
    ctx = transport.create_ssl_context()

    # Get the directory listing before cleanup
    tmp_dir = Path("/tmp")
    tmp_files_before = {f for f in tmp_dir.iterdir() if f.is_file()}

    # Create another context to generate more temp files
    ctx2 = transport.create_ssl_context(server_side=True)

    # Get files created during the test
    tmp_files_after = {f for f in tmp_dir.iterdir() if f.is_file()}
    new_files = tmp_files_after - tmp_files_before

    # Verify no temporary files were left behind
    assert not any(f.name.startswith("tmp") for f in new_files), "Temporary files were not cleaned up"

@pytest.mark.trio
async def test_sensitive_data_handling():
    """Test that sensitive data is properly handled and cleaned up."""
    keypair_a = generate_new_rsa_identity()
    keypair_b = generate_new_rsa_identity()

    transport_a = TLSTransport(keypair_a)
    transport_b = TLSTransport(keypair_b)

    # Get initial state of temp directory
    tmp_dir = Path("/tmp")
    initial_files = {f for f in tmp_dir.iterdir() if f.is_file()}

    async with tls_conn_factory(nursery, client_transport=transport_a, server_transport=transport_b) as (client_conn, server_conn):
        # Perform some data transfer
        test_data = b"sensitive_test_data"
        await client_conn.write(test_data)
        received = await server_conn.read(len(test_data))
        assert received == test_data

    # Check temp files after connection is closed
    final_files = {f for f in tmp_dir.iterdir() if f.is_file()}
    new_files = final_files - initial_files

    # Verify cleanup
    assert not any(f.name.startswith("tmp") for f in new_files), "Temporary files remained after connection closed"
    for f in new_files:
        if f.exists():  # Check if file still exists
            content = f.read_bytes()
            assert test_data not in content, "Sensitive data found in temporary files"

@pytest.mark.trio
async def test_cert_loading_security():
    """Test secure handling of certificates during loading."""
    keypair = generate_new_rsa_identity()
    transport = TLSTransport(keypair)

    # Test with malicious paths
    with pytest.raises(Exception):
        transport._trusted_peer_certs_pem.append("../../../etc/passwd")
        ctx = transport.create_ssl_context(server_side=True)

@pytest.mark.trio
async def test_connection_cleanup():
    """Test proper cleanup of connections and associated resources."""
    keypair_a = generate_new_rsa_identity()
    keypair_b = generate_new_rsa_identity()

    transport_a = TLSTransport(keypair_a)
    transport_b = TLSTransport(keypair_b)

    async with tls_conn_factory(nursery, client_transport=transport_a, server_transport=transport_b) as (client_conn, server_conn):
        # Force close the connection
        await client_conn.close()

        # Verify resources are cleaned up
        # Try to write to closed connection
        with pytest.raises(Exception):
            await client_conn.write(b"test")

        # Try to read from closed connection
        data = await server_conn.read(1024)
        assert data == b"", "Connection not properly closed"
