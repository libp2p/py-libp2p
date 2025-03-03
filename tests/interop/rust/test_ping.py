#!/usr/bin/env python3

import argparse
import asyncio
import os
import subprocess
import sys
from typing import (
    Optional,
)

import multiaddr
import trio

from libp2p import (
    new_host,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.network.stream.net_stream import (
    INetStream,
)
from libp2p.peer.peerinfo import (
    info_from_p2p_addr,
)

# Constants matching both implementations
PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")
PING_LENGTH = 32
RESP_TIMEOUT = 60

# Test config
PYTHON_PORT = 10333
RUST_PORT = 10334
SUCCESS_COUNT = 3  # Number of successful pings needed to pass the test
TIMEOUT = 60  # Overall test timeout in seconds


class TestResult:
    def __init__(self):
        self.pings_sent = 0
        self.pongs_received = 0
        self.success = False


async def handle_ping(stream: INetStream) -> None:
    """Handle incoming ping requests by responding with pong."""
    while True:
        try:
            payload = await stream.read(PING_LENGTH)
            peer_id = stream.muxed_conn.peer_id
            if payload is not None:
                print(f"[Python] Received ping from {peer_id}")
                await stream.write(payload)
                print(f"[Python] Responded with pong to {peer_id}")
        except Exception as e:
            print(f"[Python] Error in handle_ping: {e}")
            await stream.reset()
            break


async def send_ping(stream: INetStream, result: TestResult) -> None:
    """Send ping to a peer and handle the response."""
    try:
        payload = b"\x01" * PING_LENGTH
        print(f"[Python] Sending ping to {stream.muxed_conn.peer_id}")
        result.pings_sent += 1
        await stream.write(payload)

        with trio.fail_after(RESP_TIMEOUT):
            response = await stream.read(PING_LENGTH)

        if response == payload:
            print(f"[Python] Received pong from {stream.muxed_conn.peer_id}")
            result.pongs_received += 1
            if result.pongs_received >= SUCCESS_COUNT:
                result.success = True
                print(
                    f"[Python] Successfully received"
                    f"{SUCCESS_COUNT} pings, test passed!"
                )
    except Exception as e:
        print(f"[Python] Error in send_ping: {e}")


async def run_python_node(
    test_mode: str, rust_addr: Optional[str], result: TestResult
) -> None:
    """Run a Python libp2p node in either client or server mode."""
    listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{PYTHON_PORT}")
    host = new_host()

    # Fix: properly use the nursery (line too long fixed)
    addr_str = f"/ip4/127.0.0.1/tcp/{PYTHON_PORT}/p2p/{host.get_id().pretty()}"
    async with host.run(listen_addrs=[listen_addr]):
        if test_mode == "server" or test_mode == "both":
            # Act as a server that responds to pings
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)
            print(f"[Python] Server listening on {addr_str}")

        if (test_mode == "client" or test_mode == "both") and rust_addr:
            # Act as a client that sends pings
            maddr = multiaddr.Multiaddr(rust_addr)
            info = info_from_p2p_addr(maddr)
            print(f"[Python] Connecting to Rust node at {rust_addr}")
            await host.connect(info)
            stream = await host.new_stream(info.peer_id, [PING_PROTOCOL_ID])

            for _ in range(SUCCESS_COUNT):
                if not result.success:
                    await send_ping(stream, result)
                    await trio.sleep(1)

        # Keep running for the server mode
        if test_mode == "server" or (test_mode == "both" and not result.success):
            deadline = trio.current_time() + TIMEOUT
            while trio.current_time() < deadline and not result.success:
                await trio.sleep(1)


def run_rust_node(
    test_mode: str, python_addr: Optional[str] = None
) -> subprocess.Popen:
    """Start the Rust libp2p ping example with appropriate parameters."""
    cmd = ["cargo", "run", "--example", "ping", "--", f"/ip4/0.0.0.0/tcp/{RUST_PORT}"]

    if test_mode == "client" or test_mode == "both":
        if python_addr:
            cmd.append(python_addr)

    print(f"[Test] Starting Rust libp2p node: {' '.join(cmd)}")
    env = os.environ.copy()
    env["RUST_LOG"] = "info"

    # Start the process without capturing output
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    # Give the process time to start up
    import time

    time.sleep(2)

    return process


def get_rust_node_addr(process: subprocess.Popen) -> Optional[str]:
    """Parse the Rust node's listening address from its output."""
    # Wait for the "Listening on" line in the output
    addr = None
    for _ in range(10):  # Try for a few seconds
        line = process.stdout.readline()
        if not line:
            break
        print(f"[Rust] {line.strip()}")
        if "Listening on" in line:
            # Extract the multiaddress from the output
            # Format: Listening on "/ip4/127.0.0.1/tcp/10334/p2p/..."
            addr_str = line.split('"')[1]
            addr = addr_str
            break

    return addr


async def run_test(test_mode: str) -> bool:
    """Run the interoperability test between Python and Rust libp2p implementations."""
    result = TestResult()

    # Determine which nodes to start based on test mode
    if test_mode == "python-client":
        # Start Rust server first
        rust_process = run_rust_node("server")
        rust_addr = get_rust_node_addr(rust_process)
        if not rust_addr:
            print("[Test] Failed to get Rust node address!")
            rust_process.terminate()
            return False

        # Then start Python client
        print(f"[Test] Starting Python client connecting to {rust_addr}")
        try:
            await trio.to_thread.run_sync(
                lambda: trio.run(run_python_node, "client", rust_addr, result)
            )
        finally:
            rust_process.terminate()

    elif test_mode == "rust-client":
        # Start Python node in a separate thread since we need to extract the address
        python_addr_event = asyncio.Event()
        python_addr = None

        def start_python_server():
            nonlocal python_addr
            host = new_host()
            listen_addr = multiaddr.Multiaddr(f"/ip4/0.0.0.0/tcp/{PYTHON_PORT}")

            # Fix: properly use host.run without assigning to nursery
            host.run(listen_addrs=[listen_addr]).__enter__()
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)
            python_addr = (
                f"/ip4/127.0.0.1/tcp/{PYTHON_PORT}/p2p/{host.get_id().pretty()}"
            )
            print(f"[Python] Server listening on {python_addr}")
            python_addr_event.set()

            # Keep the server running
            trio.sleep(TIMEOUT)

        # Start the Python server in a separate thread
        import threading

        python_thread = threading.Thread(target=lambda: trio.run(start_python_server))
        python_thread.daemon = True
        python_thread.start()

        # Wait for the Python address to be available
        await python_addr_event.wait()

        # Start the Rust client
        rust_process = run_rust_node("client", python_addr)

        # Monitor the Rust process output for ping success
        success = False
        # Fix: Initialize success_count
        success_count = 0
        try:
            for _ in range(10):
                line = rust_process.stdout.readline()
                if not line:
                    break
                print(f"[Rust] {line.strip()}")
                if "Ping success" in line:
                    success_count += 1
                    if success_count >= SUCCESS_COUNT:
                        success = True
                        break
                await asyncio.sleep(1)
        finally:
            rust_process.terminate()

        return success

    elif test_mode == "both":
        # Start both nodes and let them connect to each other
        rust_process = run_rust_node("server")
        rust_addr = get_rust_node_addr(rust_process)
        if not rust_addr:
            print("[Test] Failed to get Rust node address!")
            rust_process.terminate()
            return False

        try:
            await trio.to_thread.run_sync(
                lambda: trio.run(run_python_node, "both", rust_addr, result)
            )
        finally:
            rust_process.terminate()

    return result.success


def main():
    parser = argparse.ArgumentParser(
        description="Interoperability test between"
        "py-libp2p and rust-libp2p ping implementations"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["python-client", "rust-client", "both"],
        default="both",
        help="Test mode: python-client (Python connects to Rust), "
        "rust-client (Rust connects to Python), or both",
    )
    args = parser.parse_args()

    # Run the test with asyncio since we need to use both asyncio and trio
    success = asyncio.run(run_test(args.mode))

    if success:
        print("[Test] Interoperability test PASSED! 🎉")
        return 0
    else:
        print("[Test] Interoperability test FAILED! ❌")
        return 1


if __name__ == "__main__":
    sys.exit(main())
