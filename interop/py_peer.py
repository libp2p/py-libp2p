#!/usr/bin/env python3
"""
Interop peer: Python IPFS-Lite peer for cross-language testing.

Commands:
  add      --listen ADDR --file PATH           Add file and serve
  get      --listen ADDR --connect ADDR --cid CID [--out PATH]  Fetch file
  add-node --listen ADDR --data JSON           Add a generic JSON node
  get-node --listen ADDR --connect ADDR --cid CID  Fetch node
  has      --listen ADDR --cid CID             Check if block exists
  remove   --listen ADDR --cid CID             Remove a block
  pin-gc   --listen ADDR                       Pin/GC round-trip test
"""
import argparse
import json
import os
import sys
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    stream=sys.stderr,
    force=True,
)
logging.getLogger("multiaddr").setLevel(logging.WARNING)

import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config
from libp2p.bitswap.cid import parse_cid


def parse_args():
    parser = argparse.ArgumentParser(description="Python IPFS-Lite interop peer")
    sub = parser.add_subparsers(dest="mode", required=True)

    # --- add file ---
    add_p = sub.add_parser("add", help="Add file and serve it")
    add_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")
    add_p.add_argument("--file", required=True, help="File to add")

    # --- get file ---
    get_p = sub.add_parser("get", help="Fetch a CID from a peer")
    get_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")
    get_p.add_argument("--connect", required=False, help="Peer multiaddr to connect to")
    get_p.add_argument("--bootstrap", required=False, help="Bootstrap peer multiaddr")
    get_p.add_argument("--cid", required=True, help="CID to fetch")
    get_p.add_argument("--out", required=False, help="Output file path")

    # --- add node ---
    add_node_p = sub.add_parser("add-node", help="Add a generic JSON node")
    add_node_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")
    add_node_p.add_argument("--data", required=True, help="JSON string data")

    # --- get node ---
    get_node_p = sub.add_parser("get-node", help="Fetch a generic JSON node")
    get_node_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")
    get_node_p.add_argument("--bootstrap", required=False, help="Bootstrap peer")
    get_node_p.add_argument("--connect", required=False, help="Direct connect peer")
    get_node_p.add_argument("--cid", required=True, help="CID to fetch")

    # --- has block ---
    has_p = sub.add_parser("has", help="Check if a block exists locally")
    has_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")
    has_p.add_argument("--cid", required=True, help="CID to check")

    # --- remove block ---
    rm_p = sub.add_parser("remove", help="Remove a block locally")
    rm_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")
    rm_p.add_argument("--cid", required=True, help="CID to remove")

    # --- pin-gc test ---
    pingc_p = sub.add_parser("pin-gc", help="Pin/GC round-trip test")
    pingc_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")

    # --- add-get-remove compound test ---
    agr_p = sub.add_parser("add-get-remove", help="Compound add/has/remove test")
    agr_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/0", help="Listen multiaddr")
    agr_p.add_argument("--data", required=True, help="Text data to add")

    return parser.parse_args()


# ──────────────────────────────────────────────────────────────
# Command implementations
# ──────────────────────────────────────────────────────────────

async def run_add(listen_addr: str, filepath: str):
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()
        root_cid = await peer.add_file(filepath)

        peer_id = peer.host.id()
        addr = str(peer.host.addrs()[0])

        print(f"PEER_ID={peer_id}", flush=True)
        print(f"ADDR={addr}", flush=True)
        print(f"CID={root_cid}", flush=True)
        print("READY", flush=True)

        await trio.sleep_forever()
    finally:
        await peer.close()


async def run_get(listen_addr: str, connect_addr: str, bootstrap_addr: str, cid_str: str, out_path: str):
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()
        if bootstrap_addr:
            await peer.bootstrap([bootstrap_addr])

        with trio.fail_after(180):
            await peer.get_file(cid_str, output_path=out_path, provider_addr=connect_addr)
    except Exception as e:
        print(f"Failed to get file: {e}", file=sys.stderr)
        return
    finally:
        await peer.close()

    print("CONTENT_SAVED", flush=True)


async def run_add_node(listen_addr: str, data: str):
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()
        node_data = json.loads(data)
        root_cid = await peer.add_node(node_data, codec="dag-json")

        peer_id = peer.host.id()
        addr = str(peer.host.addrs()[0])

        print(f"PEER_ID={peer_id}", flush=True)
        print(f"ADDR={addr}", flush=True)
        print(f"CID={root_cid}", flush=True)
        print("READY", flush=True)

        await trio.sleep_forever()
    finally:
        await peer.close()


async def run_get_node(listen_addr: str, connect_addr: str, bootstrap_addr: str, cid_str: str):
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()
        if bootstrap_addr:
            await peer.bootstrap([bootstrap_addr])

        with trio.fail_after(180):
            node_data = await peer.get_node(cid_str, provider_addr=connect_addr)
            print(f"DONE_FETCH_NODE: {json.dumps(node_data)}", flush=True)
    except Exception as e:
        print(f"Failed to get node: {e}", file=sys.stderr)
        return
    finally:
        await peer.close()


async def run_has(listen_addr: str, cid_str: str):
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()
        cid = parse_cid(cid_str)
        has = await peer.blockstore.has(cid)
        print(f"HAS_BLOCK={has}", flush=True)
    finally:
        await peer.close()


async def run_remove(listen_addr: str, cid_str: str):
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()
        await peer.remove_node(cid_str)
        print("REMOVE=ok", flush=True)
    except Exception as e:
        print(f"REMOVE=error:{e}", flush=True)
    finally:
        await peer.close()


async def run_pin_gc(listen_addr: str):
    """Pin/GC round-trip: add 3 nodes, pin 1, GC, verify results."""
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()

        # Add 3 nodes
        cid1 = await peer.add_node({"name": "pinned_node", "value": 1})
        cid2 = await peer.add_node({"name": "unpinned_node_a", "value": 2})
        cid3 = await peer.add_node({"name": "unpinned_node_b", "value": 3})
        print(f"ADDED_3_NODES={cid1},{cid2},{cid3}", flush=True)

        # Pin only cid1
        await peer.add_pin(cid1, recursive=False)
        print(f"PINNED={cid1}", flush=True)

        # GC
        stats = await peer.gc()
        print(f"GC_RECLAIMED={stats['reclaimed_blocks']}", flush=True)
        print(f"GC_RETAINED={stats['retained_blocks']}", flush=True)

        # Verify: cid1 should exist, cid2 and cid3 should be gone
        has1 = await peer.blockstore.has(parse_cid(cid1))
        has2 = await peer.blockstore.has(parse_cid(cid2))
        has3 = await peer.blockstore.has(parse_cid(cid3))
        print(f"HAS_PINNED={has1}", flush=True)
        print(f"HAS_UNPINNED_A={has2}", flush=True)
        print(f"HAS_UNPINNED_B={has3}", flush=True)

        if has1 and not has2 and not has3:
            print("PIN_GC_RESULT=PASS", flush=True)
        else:
            print("PIN_GC_RESULT=FAIL", flush=True)
    finally:
        await peer.close()


async def run_add_get_remove(listen_addr: str, data: str):
    """Compound test: add a node, verify has, remove, verify gone."""
    config = Config(reprovide_interval_seconds=-1)
    peer = Peer(config, listen_addrs=[listen_addr])
    try:
        await peer.start()

        # Add
        cid_str = await peer.add_node({"content": data})
        print(f"ADDED_CID={cid_str}", flush=True)

        # HasBlock after add
        cid = parse_cid(cid_str)
        has = await peer.blockstore.has(cid)
        print(f"HAS_AFTER_ADD={has}", flush=True)

        # Remove
        await peer.remove_node(cid_str)
        print("REMOVE=ok", flush=True)

        # HasBlock after remove
        has_after = await peer.blockstore.has(cid)
        print(f"HAS_AFTER_REMOVE={has_after}", flush=True)

        if has and not has_after:
            print("ADD_GET_REMOVE_RESULT=PASS", flush=True)
        else:
            print("ADD_GET_REMOVE_RESULT=FAIL", flush=True)
    finally:
        await peer.close()


# ──────────────────────────────────────────────────────────────

def main():
    args = parse_args()
    if args.mode == "add":
        trio.run(run_add, args.listen, args.file)
    elif args.mode == "get":
        trio.run(run_get, args.listen, args.connect, getattr(args, 'bootstrap', None), args.cid, args.out)
    elif args.mode == "add-node":
        trio.run(run_add_node, args.listen, args.data)
    elif args.mode == "get-node":
        trio.run(run_get_node, args.listen, getattr(args, 'connect', None), getattr(args, 'bootstrap', None), args.cid)
    elif args.mode == "has":
        trio.run(run_has, args.listen, args.cid)
    elif args.mode == "remove":
        trio.run(run_remove, args.listen, args.cid)
    elif args.mode == "pin-gc":
        trio.run(run_pin_gc, args.listen)
    elif args.mode == "add-get-remove":
        trio.run(run_add_get_remove, args.listen, args.data)


if __name__ == "__main__":
    main()
