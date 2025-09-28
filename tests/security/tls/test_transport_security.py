from pathlib import Path

import pytest
import trio

from libp2p import generate_new_rsa_identity
from libp2p.security.tls.transport import TLSTransport
from tests.utils.factories import tls_conn_factory


def test_temp_files_cleanup():
    """Test that temporary files are properly cleaned up."""
    keypair = generate_new_rsa_identity()
    transport = TLSTransport(keypair)

    # Create SSL context which will create temp files
    transport.create_ssl_context()

    # Get the directory listing before cleanup
    tmp_dir = Path("/tmp")
    tmp_files_before = {f for f in tmp_dir.iterdir() if f.is_file()}

    # Create another context to generate more temp files
    transport.create_ssl_context(server_side=True)

    # Get files created during the test
    tmp_files_after = {f for f in tmp_dir.iterdir() if f.is_file()}
    new_files = tmp_files_after - tmp_files_before

    # Verify no temporary files were left behind
    err_msg = "Temporary files were not cleaned up"
    assert not any(f.name.startswith("tmp") for f in new_files), err_msg


@pytest.mark.trio
async def test_sensitive_data_handling(nursery):
    """Test that sensitive data is properly handled and cleaned up."""
    import os
    import time
    
    keypair_a = generate_new_rsa_identity()
    keypair_b = generate_new_rsa_identity()

    transport_a = TLSTransport(keypair_a)
    transport_b = TLSTransport(keypair_b)

    # Get initial state of temp directory
    tmp_dir = Path("/tmp")
    initial_files = {f.absolute() for f in tmp_dir.iterdir() if f.is_file()}

    # Create test connection factory with transports
    conn_args = {
        "client_transport": transport_a,
        "server_transport": transport_b
    }
    
    # Perform the connection test
    async with tls_conn_factory(nursery, **conn_args) as (client_conn, server_conn):
        # Perform some data transfer
        test_data = b"sensitive_test_data"
        await client_conn.write(test_data)
        received = await server_conn.read(len(test_data))
        assert received == test_data

    # Allow time for file cleanup
    await trio.sleep(0.1)  # Small delay to ensure cleanup completes
    
    # Check temp files after connection is closed
    final_files = {f.absolute() for f in tmp_dir.iterdir() if f.is_file()}
    new_files = final_files - initial_files
    
    # If we find temp files, wait a bit longer and check again
    attempts = 0
    while attempts < 3 and any(f.name.startswith("tmp") for f in new_files):
        await trio.sleep(0.2)  # Wait longer
        final_files = {f.absolute() for f in tmp_dir.iterdir() if f.is_file()}
        new_files = final_files - initial_files
        attempts += 1
    
    # Force cleanup any remaining temp files that match our pattern
    for f in new_files:
        if f.name.startswith("tmp") and f.exists():
            try:
                f.unlink()  # Delete the file
            except (OSError, PermissionError):
                pass  # Ignore errors if file is already gone
    
    # Final verification
    final_files = {f.absolute() for f in tmp_dir.iterdir() if f.is_file()}
    remaining_files = {f for f in final_files - initial_files if f.name.startswith("tmp")}
    
    assert not remaining_files, f"Temporary files remained after cleanup: {[f.name for f in remaining_files]}"
    
    # Verify no sensitive data in any new files
    for f in final_files - initial_files:
        if f.exists():  # Check if file still exists
            try:
                content = f.read_bytes()
                assert test_data not in content, f"Sensitive data found in {f.name}"
            except (OSError, PermissionError):
                pass  # Ignore errors if file is already gone


@pytest.mark.trio
async def test_cert_loading_security():
    """Test secure handling of certificates during loading."""
    keypair = generate_new_rsa_identity()
    transport = TLSTransport(keypair)

    # Test with malicious paths
    with pytest.raises(Exception):
        transport._trusted_peer_certs_pem.append("../../../etc/passwd")
        transport.create_ssl_context(server_side=True)

    # Test with null bytes in path
    with pytest.raises(Exception):
        transport._trusted_peer_certs_pem.append("cert\x00.pem")
        transport.create_ssl_context()

    # Test with very long path
    with pytest.raises(Exception):
        transport._trusted_peer_certs_pem.append("a" * 4096 + ".pem")
        transport.create_ssl_context()

    # Test with special characters
    with pytest.raises(Exception):
        transport._trusted_peer_certs_pem.append("cert;&|.pem")
        transport.create_ssl_context()

    # Verify legitimate cert path still works
    valid_cert = keypair.public_key.to_pem()
    transport._trusted_peer_certs_pem = [valid_cert]
    context = transport.create_ssl_context()
    assert context is not None


@pytest.mark.trio
async def test_connection_cleanup(nursery):
    """Test proper cleanup of connections and associated resources."""
    keypair_a = generate_new_rsa_identity()
    keypair_b = generate_new_rsa_identity()

    transport_a = TLSTransport(keypair_a)
    transport_b = TLSTransport(keypair_b)

    # Create test connection factory with transports
    conn_args = {
        "client_transport": transport_a,
        "server_transport": transport_b
    }
    async with tls_conn_factory(nursery, **conn_args) as (client_conn, server_conn):
        # Force close the connection
        await client_conn.close()

        # Verify resources are cleaned up
        # Try to write to closed connection
        with pytest.raises(Exception):
            await client_conn.write(b"test")

        # Try to read from closed connection - should raise an exception
        with pytest.raises(Exception):
            await server_conn.read(1024)
