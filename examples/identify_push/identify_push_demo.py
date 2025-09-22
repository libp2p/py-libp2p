#!/usr/bin/env python3
"""
Example demonstrating the identify/push protocol.

This example shows how to:
1. Set up a host with the identify/push protocol handler
2. Connect to another peer
3. Push identify information to the peer
4. Receive and process identify/push messages
"""

import logging

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.abc import (
    INetStream,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.identity.identify_push import (
    ID_PUSH,
    push_identify_to_peer,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)
from libp2p.utils.address_validation import (
    get_available_interfaces,
)

# Configure logging
logger = logging.getLogger(__name__)


def create_custom_identify_handler(host, host_name: str):
    """Create a custom identify handler that displays received information."""

    async def handle_identify(stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id
        print(f"\n🔍 {host_name} received identify request from peer: {peer_id}")

        # Get the standard identify response using the existing function
        from libp2p.identity.identify.identify import (
            _mk_identify_protobuf,
            _remote_address_to_multiaddr,
        )

        # Get observed address
        observed_multiaddr = None
        try:
            remote_address = stream.get_remote_address()
            if remote_address:
                observed_multiaddr = _remote_address_to_multiaddr(remote_address)
        except Exception:
            pass

        # Build the identify protobuf
        identify_msg = _mk_identify_protobuf(host, observed_multiaddr)
        response_data = identify_msg.SerializeToString()

        print(f"   📋 {host_name} identify information:")
        if identify_msg.HasField("protocol_version"):
            print(f"      Protocol Version: {identify_msg.protocol_version}")
        if identify_msg.HasField("agent_version"):
            print(f"      Agent Version: {identify_msg.agent_version}")
        if identify_msg.HasField("public_key"):
            print(f"      Public Key: {identify_msg.public_key.hex()[:16]}...")
        if identify_msg.listen_addrs:
            print("      Listen Addresses:")
            for addr_bytes in identify_msg.listen_addrs:
                addr = multiaddr.Multiaddr(addr_bytes)
                print(f"        - {addr}")
        if identify_msg.protocols:
            print("      Supported Protocols:")
            for protocol in identify_msg.protocols:
                print(f"        - {protocol}")

        # Send the response
        await stream.write(response_data)
        await stream.close()

    return handle_identify


def create_custom_identify_push_handler(host, host_name: str):
    """Create a custom identify/push handler that displays received information."""

    async def handle_identify_push(stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id
        print(f"\n📤 {host_name} received identify/push from peer: {peer_id}")

        try:
            # Read the identify message using the utility function
            from libp2p.utils.varint import read_length_prefixed_protobuf

            data = await read_length_prefixed_protobuf(stream, use_varint_format=True)

            # Parse the identify message
            identify_msg = Identify()
            identify_msg.ParseFromString(data)

            print("   📋 Received identify information:")
            if identify_msg.HasField("protocol_version"):
                print(f"      Protocol Version: {identify_msg.protocol_version}")
            if identify_msg.HasField("agent_version"):
                print(f"      Agent Version: {identify_msg.agent_version}")
            if identify_msg.HasField("public_key"):
                print(f"      Public Key: {identify_msg.public_key.hex()[:16]}...")
            if identify_msg.HasField("observed_addr") and identify_msg.observed_addr:
                observed_addr = multiaddr.Multiaddr(identify_msg.observed_addr)
                print(f"      Observed Address: {observed_addr}")
            if identify_msg.listen_addrs:
                print("      Listen Addresses:")
                for addr_bytes in identify_msg.listen_addrs:
                    addr = multiaddr.Multiaddr(addr_bytes)
                    print(f"        - {addr}")
            if identify_msg.protocols:
                print("      Supported Protocols:")
                for protocol in identify_msg.protocols:
                    print(f"        - {protocol}")

            # Update the peerstore with the new information
            from libp2p.identity.identify_push.identify_push import (
                _update_peerstore_from_identify,
            )

            await _update_peerstore_from_identify(
                host.get_peerstore(), peer_id, identify_msg
            )

            print(f"   ✅ {host_name} updated peerstore with new information")

        except Exception as e:
            print(f"   ❌ Error processing identify/push: {e}")
        finally:
            await stream.close()

    return handle_identify_push


async def display_peerstore_info(host, host_name: str, peer_id, description: str):
    """Display peerstore information for a specific peer."""
    peerstore = host.get_peerstore()

    try:
        addrs = peerstore.addrs(peer_id)
    except Exception:
        addrs = []

    try:
        protocols = peerstore.get_protocols(peer_id)
    except Exception:
        protocols = []

    print(f"\n📚 {host_name} peerstore for {description}:")
    print(f"   Peer ID: {peer_id}")
    if addrs:
        print("   Addresses:")
        for addr in addrs:
            print(f"     - {addr}")
    else:
        print("   Addresses: None")

    if protocols:
        print("   Protocols:")
        for protocol in protocols:
            print(f"     - {protocol}")
    else:
        print("   Protocols: None")


async def main() -> None:
    print("\n==== Starting Enhanced Identify-Push Example ====\n")

    # Create key pairs for the two hosts
    key_pair_1 = create_new_key_pair()
    key_pair_2 = create_new_key_pair()

    # Create the first host
    host_1 = new_host(key_pair=key_pair_1)

    # Set up custom identify and identify/push handlers
    host_1.set_stream_handler(
        TProtocol("/ipfs/id/1.0.0"), create_custom_identify_handler(host_1, "Host 1")
    )
    host_1.set_stream_handler(
        ID_PUSH, create_custom_identify_push_handler(host_1, "Host 1")
    )

    # Create the second host
    host_2 = new_host(key_pair=key_pair_2)

    # Set up custom identify and identify/push handlers
    host_2.set_stream_handler(
        TProtocol("/ipfs/id/1.0.0"), create_custom_identify_handler(host_2, "Host 2")
    )
    host_2.set_stream_handler(
        ID_PUSH, create_custom_identify_push_handler(host_2, "Host 2")
    )

    # Start listening on available interfaces using random ports
    listen_addrs_1 = get_available_interfaces(0)  # 0 for random port
    listen_addrs_2 = get_available_interfaces(0)  # 0 for random port

    async with (
        host_1.run(listen_addrs_1),
        host_2.run(listen_addrs_2),
        trio.open_nursery() as nursery,
    ):
        # Start the peer-store cleanup task
        nursery.start_soon(host_1.get_peerstore().start_cleanup_task, 60)
        nursery.start_soon(host_2.get_peerstore().start_cleanup_task, 60)

        # Get the addresses of both hosts
        addr_1 = host_1.get_addrs()[0]
        addr_2 = host_2.get_addrs()[0]

        print("🏠 Host Configuration:")
        print(f"   Host 1: {addr_1}")
        print(f"   Host 1 Peer ID: {host_1.get_id().pretty()}")
        print(f"   Host 2: {addr_2}")
        print(f"   Host 2 Peer ID: {host_2.get_id().pretty()}")

        print("\n🔗 Connecting Host 2 to Host 1...")

        # Connect host_2 to host_1
        peer_info = info_from_p2p_addr(addr_1)
        await host_2.connect(peer_info)
        print("✅ Host 2 successfully connected to Host 1")

        # Run the identify protocol from host_2 to host_1
        print("\n🔄 Running identify protocol (Host 2 → Host 1)...")
        from libp2p.identity.identify.identify import ID as IDENTIFY_PROTOCOL_ID

        stream = await host_2.new_stream(host_1.get_id(), (IDENTIFY_PROTOCOL_ID,))
        response = await stream.read()
        await stream.close()

        # Run the identify protocol from host_1 to host_2
        print("\n🔄 Running identify protocol (Host 1 → Host 2)...")
        stream = await host_1.new_stream(host_2.get_id(), (IDENTIFY_PROTOCOL_ID,))
        response = await stream.read()
        await stream.close()

        # Update Host 1's peerstore with Host 2's addresses
        identify_msg = Identify()
        identify_msg.ParseFromString(response)
        peerstore_1 = host_1.get_peerstore()
        peer_id_2 = host_2.get_id()
        for addr_bytes in identify_msg.listen_addrs:
            maddr = multiaddr.Multiaddr(addr_bytes)
            peerstore_1.add_addr(peer_id_2, maddr, ttl=3600)

        # Display peerstore information before push
        await display_peerstore_info(
            host_1, "Host 1", peer_id_2, "Host 2 (before push)"
        )

        # Push identify information from host_1 to host_2
        print("\n📤 Host 1 pushing identify information to Host 2...")

        try:
            success = await push_identify_to_peer(host_1, host_2.get_id())

            if success:
                print("✅ Identify push completed successfully!")
            else:
                print("⚠️  Identify push didn't complete successfully")

        except Exception as e:
            print(f"❌ Error during identify push: {str(e)}")

        # Give a moment for the identify/push processing to complete
        await trio.sleep(0.5)

        # Display peerstore information after push
        await display_peerstore_info(host_1, "Host 1", peer_id_2, "Host 2 (after push)")
        await display_peerstore_info(
            host_2, "Host 2", host_1.get_id(), "Host 1 (after push)"
        )

        # Give more time for background tasks to finish and connections to stabilize
        print("\n⏳ Waiting for background tasks to complete...")
        await trio.sleep(1.0)

        # Gracefully close connections to prevent connection errors
        print("🔌 Closing connections...")
        await host_2.disconnect(host_1.get_id())
        await trio.sleep(0.2)

        print("\n🎉 Example completed successfully!")


if __name__ == "__main__":
    trio.run(main)


def run_main():
    """Non-async entry point for the console script."""
    trio.run(main)
