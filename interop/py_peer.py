#!/usr/bin/env python3
"""
Interop peer: Python IPFS-Lite peer for cross-language testing (10MB file transfer).

Usage:
  uv run python py_peer.py add --listen /ip4/127.0.0.1/tcp/4011 --file /path/to/file
  uv run python py_peer.py get --connect /ip4/.../p2p/<id> --cid <cid> --out /path/to/out
"""
import argparse
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

def parse_args():
    parser = argparse.ArgumentParser(description="Python IPFS-Lite interop peer")
    sub = parser.add_subparsers(dest="mode", required=True)

    add_p = sub.add_parser("add", help="Add file and serve it")
    add_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/4011", help="Listen multiaddr")
    add_p.add_argument("--file", required=True, help="File to add")

    get_p = sub.add_parser("get", help="Fetch a CID from a peer")
    get_p.add_argument("--listen", default="/ip4/127.0.0.1/tcp/4012", help="Listen multiaddr")
    get_p.add_argument("--connect", required=True, help="Peer multiaddr to connect to")
    get_p.add_argument("--cid", required=True, help="CID to fetch")
    get_p.add_argument("--out", required=True, help="Output file path")

    return parser.parse_args()


async def run_add(listen_addr: str, filepath: str):
    config = Config()
    peer = Peer(config, listen_addrs=[listen_addr])

    try:
        await peer.bootstrap()
        root_cid = await peer.add_file(filepath)

        peer_id = peer.host.get_id()
        addr = str(peer.host.get_addrs()[0])

        print(f"PEER_ID={peer_id}", flush=True)
        print(f"ADDR={addr}", flush=True)
        print(f"CID={root_cid}", flush=True)
        print("READY", flush=True)

        await trio.sleep_forever()
    finally:
        await peer.close()


async def run_get(listen_addr: str, connect_addr: str, cid_str: str, out_path: str):
    config = Config()
    peer = Peer(config, listen_addrs=[listen_addr])

    try:
        await peer.bootstrap()
        with trio.fail_after(180):
            await peer.get_file(cid_str, output_path=out_path, provider_addr=connect_addr)
    except Exception as e:
        print(f"Failed to get file: {e}", file=sys.stderr)
        return
    finally:
        await peer.close()

    print(f"CONTENT_SAVED", flush=True)


def main():
    args = parse_args()
    if args.mode == "add":
        trio.run(run_add, args.listen, args.file)
    else:
        trio.run(run_get, args.listen, args.connect, args.cid, args.out)

if __name__ == "__main__":
    main()
