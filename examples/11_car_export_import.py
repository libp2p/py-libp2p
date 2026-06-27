import os
import tempfile

import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer


async def main():
    print("=== Example 11: CAR File Export/Import ===")

    # Create temp file
    car_path = os.path.join(tempfile.gettempdir(), "book.car")

    print("\n--- Phase 1: Writer Peer ---")
    writer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
    )
    await writer.start()

    # Build a DAG
    leaf_a = await writer.add_node({"content": "chapter one"}, codec="dag-cbor")
    leaf_b = await writer.add_node({"content": "chapter two"}, codec="dag-cbor")
    root = await writer.add_node(
        {"title": "My Book", "chapters": [{"/": leaf_a}, {"/": leaf_b}]},
        codec="dag-cbor",
    )
    print(f"Created Book DAG with Root CID: {root}")

    # Export to CAR
    print(f"Exporting DAG to {car_path}...")
    await writer.export_car(root, car_path)
    file_size = os.path.getsize(car_path)
    print(f"Exported {file_size} bytes to book.car")
    await writer.close()

    print("\n--- Phase 2: Offline Reader Peer ---")
    # Import on a fresh peer — fully offline, no network needed
    reader = Peer(
        Config(offline=True, reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
    )
    await reader.start()

    print(f"Importing DAG from {car_path}...")
    imported_roots = await reader.import_car(car_path)
    print(f"Imported roots: {imported_roots}")

    imported_root = imported_roots[0]
    assert imported_root == root, f"Mismatch: {imported_root} != {root}"

    print("Fetching Book content from Reader Peer...")
    book = await reader.get_node(root)
    print(f"Imported offline: '{book['title']}' with {len(book['chapters'])} chapters")

    print("\n✓ Offline import and traversal successful!")
    await reader.close()

    # Cleanup
    if os.path.exists(car_path):
        os.unlink(car_path)


if __name__ == "__main__":
    trio.run(main)
