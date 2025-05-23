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

import trio

from libp2p import (
    new_host,
)
from libp2p.crypto.secp256k1 import (
    create_new_key_pair,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.identity.identify import (
    identify_handler_for,
)
from libp2p.identity.identify_push import (
    ID_PUSH,
    identify_push_handler_for,
    push_identify_to_peer,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

# Configure logging
logger = logging.getLogger(__name__)


async def main() -> None:
    print("\n==== Starting Identify-Push Example ====\n")

    # Create key pairs for the two hosts
    key_pair_1 = create_new_key_pair()
    key_pair_2 = create_new_key_pair()

    # Create the first host
    host_1 = new_host(key_pair=key_pair_1)

    # Set up the identify and identify/push handlers
    host_1.set_stream_handler(TProtocol("/ipfs/id/1.0.0"), identify_handler_for(host_1))
    host_1.set_stream_handler(ID_PUSH, identify_push_handler_for(host_1))

    # Create the second host
    host_2 = new_host(key_pair=key_pair_2)

    # Set up the identify and identify/push handlers
    host_2.set_stream_handler(TProtocol("/ipfs/id/1.0.0"), identify_handler_for(host_2))
    host_2.set_stream_handler(ID_PUSH, identify_push_handler_for(host_2))

    # Start listening on random ports using the run context manager
    import multiaddr

    listen_addr_1 = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
    listen_addr_2 = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")

    async with host_1.run([listen_addr_1]), host_2.run([listen_addr_2]):
        # Get the addresses of both hosts
        addr_1 = host_1.get_addrs()[0]
        logger.info(f"Host 1 listening on {addr_1}")
        print(f"Host 1 listening on {addr_1}")
        print(f"Peer ID: {host_1.get_id().pretty()}")

        addr_2 = host_2.get_addrs()[0]
        logger.info(f"Host 2 listening on {addr_2}")
        print(f"Host 2 listening on {addr_2}")
        print(f"Peer ID: {host_2.get_id().pretty()}")

        print("\nConnecting Host 2 to Host 1...")

        # Connect host_2 to host_1
        peer_info = info_from_p2p_addr(addr_1)
        await host_2.connect(peer_info)
        logger.info("Host 2 connected to Host 1")
        print("Host 2 successfully connected to Host 1")

        # Run the identify protocol from host_2 to host_1
        # (so Host 1 learns Host 2's address)
        from libp2p.identity.identify.identify import ID as IDENTIFY_PROTOCOL_ID

        stream = await host_2.new_stream(host_1.get_id(), (IDENTIFY_PROTOCOL_ID,))
        response = await stream.read()
        await stream.close()

        # Run the identify protocol from host_1 to host_2
        # (so Host 2 learns Host 1's address)
        stream = await host_1.new_stream(host_2.get_id(), (IDENTIFY_PROTOCOL_ID,))
        response = await stream.read()
        await stream.close()

        # --- NEW CODE: Update Host 1's peerstore with Host 2's addresses ---
        from libp2p.identity.identify.pb.identify_pb2 import (
            Identify,
        )

        identify_msg = Identify()
        identify_msg.ParseFromString(response)
        peerstore_1 = host_1.get_peerstore()
        peer_id_2 = host_2.get_id()
        for addr_bytes in identify_msg.listen_addrs:
            maddr = multiaddr.Multiaddr(addr_bytes)
            # TTL can be any positive int
            peerstore_1.add_addr(
                peer_id_2,
                maddr,
                ttl=3600,
            )
        # --- END NEW CODE ---

        # Now Host 1's peerstore should have Host 2's address
        peerstore_1 = host_1.get_peerstore()
        peer_id_2 = host_2.get_id()
        addrs_1_for_2 = peerstore_1.addrs(peer_id_2)
        logger.info(
            f"[DEBUG] Host 1 peerstore addresses for Host 2 before push: "
            f"{addrs_1_for_2}"
        )
        print(
            f"[DEBUG] Host 1 peerstore addresses for Host 2 before push: "
            f"{addrs_1_for_2}"
        )

        # Push identify information from host_1 to host_2
        logger.info("Host 1 pushing identify information to Host 2")
        print("\nHost 1 pushing identify information to Host 2...")

        try:
            # Call push_identify_to_peer which now returns a boolean
            success = await push_identify_to_peer(host_1, host_2.get_id())

            if success:
                logger.info("Identify push completed successfully")
                print("Identify push completed successfully!")
            else:
                logger.warning("Identify push didn't complete successfully")
                print("\nWarning: Identify push didn't complete successfully")

        except Exception as e:
            logger.error(f"Error during identify push: {str(e)}")
            print(f"\nError during identify push: {str(e)}")

        # Add this at the end of your async with block:
        await trio.sleep(0.5)  # Give background tasks time to finish


if __name__ == "__main__":
    trio.run(main)


def run_main():
    """Non-async entry point for the console script."""
    trio.run(main)
