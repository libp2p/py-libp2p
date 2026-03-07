import argparse
import json
import logging
import os
import sys

from multiaddr import Multiaddr
import trio

from libp2p import new_host
from libp2p.custom_types import TProtocol
from libp2p.network.stream.net_stream import INetStream
from libp2p.peer.peerinfo import info_from_p2p_addr

PROTOCOL_ID = TProtocol("/file-share/1.0.0")
FRIENDS_FILE = "friends.json"
CHUNK_SIZE = 4096

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("FileShare")


# Persistence Layer
def load_friends() -> dict[str, str]:
    """Loads saved peer Multiaddrs from disk."""
    if not os.path.exists(FRIENDS_FILE):
        return {}
    try:
        with open(FRIENDS_FILE) as f:
            # Explicitly cast to dict to satisfy strict type checkers
            return dict(json.load(f))
    except Exception:
        return {}


def save_friend(name: str, multiaddr_str: str) -> None:
    """Saves a new peer to disk."""
    friends: dict[str, str] = load_friends()
    friends[name] = multiaddr_str
    with open(FRIENDS_FILE, "w") as f:
        json.dump(friends, f, indent=2)
    print(f"✅ Saved friend '{name}' to {FRIENDS_FILE}")


async def handle_incoming_file(stream: INetStream):
    """
    Receives a file over the stream and saves it to disk.
    """
    peer_id = stream.muxed_conn.peer_id
    print(f"\n📥 Incoming connection from {peer_id}...")

    try:
        # Step A: Read Filename Length & Filename
        len_bytes = await stream.read(4)
        if not len_bytes:
            return
        fname_len = int.from_bytes(len_bytes, "big")

        fname_bytes = await stream.read(fname_len)
        filename = fname_bytes.decode()

        # Step B: Read File Size
        size_bytes = await stream.read(8)
        file_size = int.from_bytes(size_bytes, "big")

        print(f"📄 Receiving '{filename}' ({file_size} bytes)")

        # Step C: Write to Disk (Prevent overwriting)
        save_name = f"received_{filename}"
        received_bytes = 0

        with open(save_name, "wb") as f:
            while received_bytes < file_size:
                remaining = file_size - received_bytes
                to_read = min(CHUNK_SIZE, remaining)

                chunk = await stream.read(to_read)
                if not chunk:
                    break

                f.write(chunk)
                received_bytes += len(chunk)

                percent = int((received_bytes / file_size) * 100)
                sys.stdout.write(f"\r⏳ Downloading: {percent}%")
                sys.stdout.flush()

        print(f"\n✅ File saved as '{save_name}'")
        await stream.close()

    except Exception as e:
        print(f"\n❌ Error receiving file: {e}")
        await stream.reset()


async def send_file(host, target_maddr_str, filepath):
    """
    Connects to a peer and streams a file.
    """
    if not os.path.exists(filepath):
        print("❌ File not found.")
        return

    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)

    try:
        # 1. Parse Address & Connect
        maddr = Multiaddr(target_maddr_str)
        info = info_from_p2p_addr(maddr)

        print(f"🔄 Connecting to {info.peer_id}...")
        await host.connect(info)

        # 2. Open Stream
        stream = await host.new_stream(info.peer_id, [PROTOCOL_ID])
        print("🌊 Stream opened. Sending header...")

        # 3. Send Header
        fname_bytes = filename.encode()
        await stream.write(len(fname_bytes).to_bytes(4, "big"))
        await stream.write(fname_bytes)
        await stream.write(filesize.to_bytes(8, "big"))

        # 4. Send Body
        sent_bytes = 0
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break

                await stream.write(chunk)
                sent_bytes += len(chunk)

                percent = int((sent_bytes / filesize) * 100)
                sys.stdout.write(f"\r🚀 Sending: {percent}%")
                sys.stdout.flush()

        print("\n✅ Transfer complete.")
        await stream.close()

    except Exception as e:
        print(f"\n❌ Connection failed: {e}")


async def user_interface_loop(host):
    """Handles user input in a non-blocking Trio-safe way."""
    while True:
        print("\n" + "=" * 40)
        print("     📂 P2P NAT FILE SHARING")
        print("=" * 40)

        print("📡 MY ADDRESSES:")
        public_found = False
        for addr in host.get_addrs():
            addr_str = str(addr)
            if (
                "/127.0.0.1/" in addr_str
                or "/192.168." in addr_str
                or "/10." in addr_str
            ):
                print(f"  🏠 Local:  {addr_str}")
            else:
                print(f"  🌍 Public: {addr_str} (NAT Traversal Success!)")
                public_found = True

        if not public_found:
            print("  ⚠️  No Public IP detected yet. (Wait for AutoNAT or use Relay)")

        print("\nOPTIONS:")
        print("1. 📤 Send File")
        print("2. 💾 Add Friend (Save Peer)")
        print("3. 📋 List Friends")
        print("4. 🔄 Refresh Info")
        print("Press Ctrl+C to exit")

        choice = await trio.to_thread.run_sync(input, "\n👉 Choose option: ")

        if choice == "1":
            friends = load_friends()
            if not friends:
                print("⚠️ No friends saved. Add one first or enter raw Multiaddr.")
                continue

            print("\n--- Friends ---")
            for name in friends:
                print(f"- {name}")
            print("---------------")

            target = await trio.to_thread.run_sync(
                input, "Enter Friend Name OR Multiaddr: "
            )

            # Resolve Friend Name to Address
            if target in friends:
                target = friends[target]

            fpath = await trio.to_thread.run_sync(input, "Enter file path to send: ")
            await send_file(host, target, fpath)

        elif choice == "2":
            name = await trio.to_thread.run_sync(input, "Enter a Name for this peer: ")
            addr = await trio.to_thread.run_sync(input, "Paste their Multiaddr: ")
            save_friend(name, addr.strip())

        elif choice == "3":
            friends = load_friends()
            print("\n🤝 Saved Friends (Persistent Peerstore):")
            for name, addr in friends.items():
                print(f" - {name}")

        elif choice == "4":
            continue


async def run(port):
    # Enable NAT Port Mapping (UPnP)
    host = new_host(enable_upnp=True)

    # Register the protocol handler
    host.set_stream_handler(PROTOCOL_ID, handle_incoming_file)

    async with host.run(listen_addrs=[Multiaddr(f"/ip4/0.0.0.0/tcp/{port}")]):
        print(f"\n🚀 Node Started on port {port}")
        print(f"🆔 Peer ID: {host.get_id()}")

        async with trio.open_nursery() as nursery:
            nursery.start_soon(user_interface_loop, host)


def main():
    parser = argparse.ArgumentParser(description="P2P File Transfer Across NATs")
    parser.add_argument(
        "-p", "--port", type=int, default=8000, help="Port to listen on"
    )
    args = parser.parse_args()

    try:
        trio.run(run, args.port)
    except KeyboardInterrupt:
        print("\n👋 Shutting down...")


if __name__ == "__main__":
    main()
