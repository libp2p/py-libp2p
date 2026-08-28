#!/usr/bin/env python3
"""
run_peer.py
-----------

Command-line entrypoint for the whole demo (README > Example CLI).

    # Terminal 1 -- start peer-a and keep it listening / serving requests
    python run_peer.py --name peer-a --port 8000 listen

    # Terminal 2 -- train peer-b's local shard, publish to IPFS, and
    # announce the result to peer-a
    python run_peer.py --name peer-b --port 8001 train \\
        --connect /ip4/127.0.0.1/tcp/8000/p2p/<peer-a-id>

    # Ask a connected peer for its latest checkpoint and adopt it if newer
    python run_peer.py --name peer-a --port 8000 sync \\
        --connect /ip4/127.0.0.1/tcp/8001/p2p/<peer-b-id>

    # Local (and optionally remote) status
    python run_peer.py --name peer-a --data-dir ./data/peer-a status \\
        --connect /ip4/127.0.0.1/tcp/8001/p2p/<peer-b-id>

Every subcommand starts a fresh libp2p host. For reproducible peer IDs
across runs (handy for demos, since the "peer-a" multiaddr won't change
every time you restart it), pass ``--seed``.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import trio
from multiaddr import Multiaddr

from examples.iris_data import load_partition
from libp2p.peer.peerinfo import info_from_p2p_addr
from p2p_checkpoint.ipfs_utils import IPFSClient, IPFSUnavailableError
from p2p_checkpoint.peer import Peer
from p2p_checkpoint.sync import describe, sync_with_peer

logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)


def _default_data_dir(name: str) -> Path:
    return Path("data") / name


def _seed_bytes(seed: int | None) -> bytes | None:
    if seed is None:
        return None
    return seed.to_bytes(32, byteorder="big", signed=False)


def _build_peer(args: argparse.Namespace) -> Peer:
    data_dir = Path(args.data_dir) if args.data_dir else _default_data_dir(args.name)
    ipfs = IPFSClient(api_base=args.ipfs_api)
    peer = Peer(
        name=args.name,
        data_dir=data_dir,
        ipfs=ipfs,
        seed=_seed_bytes(args.seed),
    )
    return peer


def _check_ipfs_or_warn(peer: Peer) -> None:
    if isinstance(peer.ipfs, IPFSClient) and not peer.ipfs.is_available():
        print(
            f"[warning] No IPFS daemon reachable at {peer.ipfs.api_base}. "
            "Checkpoint upload/download will fail until `ipfs daemon` is running.",
            file=sys.stderr,
        )


async def cmd_listen(args: argparse.Namespace) -> None:
    from libp2p.utils.address_validation import get_available_interfaces

    peer = _build_peer(args)
    _check_ipfs_or_warn(peer)
    listen_addrs = get_available_interfaces(args.port)

    async with peer.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        nursery.start_soon(peer.host.get_peerstore().start_cleanup_task, 60)
        print(f"Peer: {peer.name}")
        print(f"Peer ID: {peer.peer_id}")
        print("Listening on:")
        for addr in peer.listen_addrs_with_peer_id():
            print(f"  {addr}")
        print("\nWaiting for incoming sync / checkpoint requests... (Ctrl+C to stop)")
        await trio.sleep_forever()


async def cmd_train(args: argparse.Namespace) -> None:
    from libp2p.utils.address_validation import get_available_interfaces

    peer = _build_peer(args)
    _check_ipfs_or_warn(peer)
    listen_addrs = get_available_interfaces(args.port)

    async with peer.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        nursery.start_soon(peer.host.get_peerstore().start_cleanup_task, 60)
        print(f"Peer: {peer.name} ({peer.peer_id})")

        X_train, y_train, X_test, y_test, feature_names, class_names = load_partition(
            peer.name
        )
        print(f"Training on {len(X_train)} local samples...")
        cid, round_ = peer.train_and_publish(
            X_train,
            y_train,
            feature_names=feature_names,
            class_names=class_names,
            eval_data=(X_test, y_test),
        )
        record = peer.db.by_round(round_)
        print(f"Checkpoint saved (round {round_}).")
        print(f"Uploaded to IPFS -> CID: {cid}")
        if record and record.model_hash:
            print(f"Model hash: {record.model_hash}")

        if args.connect:
            info = info_from_p2p_addr(Multiaddr(args.connect))
            print(f"Connecting to {info.peer_id.to_string()} to announce...")
            await peer.host.connect(info)
            ack = await peer.announce_latest(info.peer_id)
            print(f"Announcement acknowledged: {ack}")

        if args.serve_after:
            print("\nStaying up to serve this checkpoint to other peers "
                  "(Ctrl+C to stop)...")
            await trio.sleep_forever()

        peer.close()


async def cmd_sync(args: argparse.Namespace) -> None:
    from libp2p.utils.address_validation import get_available_interfaces

    if not args.connect:
        print("`sync` requires --connect <multiaddr>", file=sys.stderr)
        raise SystemExit(2)

    peer = _build_peer(args)
    _check_ipfs_or_warn(peer)
    listen_addrs = get_available_interfaces(args.port)

    async with peer.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        nursery.start_soon(peer.host.get_peerstore().start_cleanup_task, 60)
        info = info_from_p2p_addr(Multiaddr(args.connect))
        print(f"Peer: {peer.name} ({peer.peer_id})")
        print(f"Connecting to {info.peer_id.to_string()}...")
        await peer.host.connect(info)

        print("Syncing...")
        try:
            outcome = await sync_with_peer(peer, info.peer_id)
        except IPFSUnavailableError as exc:
            print(f"Sync failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

        if outcome.action == "remote_empty":
            print("Remote peer has no checkpoint yet.")
        elif outcome.action == "up_to_date":
            print(f"Already up to date (round {outcome.local_round_before}).")
        elif outcome.action == "remote_behind":
            print(
                f"Remote is behind us (remote round {outcome.remote_round} "
                f"< local round {outcome.local_round_before}); nothing to do."
            )
        elif outcome.action == "updated":
            print("✓ Downloaded checkpoint from IPFS")
            print("✓ Integrity verified")
            print("✓ Model loaded")
            print(
                f"\nLocal model updated: round {outcome.local_round_before} "
                f"-> {outcome.local_round_after} (cid={outcome.cid})"
            )
        peer.close()


async def cmd_status(args: argparse.Namespace) -> None:
    from libp2p.utils.address_validation import get_available_interfaces

    peer = _build_peer(args)
    print(f"Peer: {peer.name}")
    print(f"Peer ID: {peer.peer_id}")
    record = peer.db.latest()
    print(f"Local checkpoint: {describe(record)}")

    if not args.connect:
        peer.close()
        return

    listen_addrs = get_available_interfaces(args.port)
    async with peer.host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
        nursery.start_soon(peer.host.get_peerstore().start_cleanup_task, 60)
        info = info_from_p2p_addr(Multiaddr(args.connect))
        await peer.host.connect(info)
        response = await peer.request_sync(info.peer_id)
        local_round = peer.db.latest_round()
        print(f"Connected peers: 1 ({info.peer_id.to_string()})")
        if not response.has_checkpoint:
            print("Remote checkpoint: none")
        else:
            print(
                f"Remote checkpoint: round {response.latest_round} "
                f"(cid={response.cid})"
            )
        if not response.has_checkpoint or response.latest_round <= local_round:
            print("Sync status: UP TO DATE")
        else:
            behind = response.latest_round - local_round
            print(f"Sync status: OUT OF DATE ({behind} round(s) behind)")
        peer.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="P2P model checkpoint sharing over IPFS + libp2p"
    )
    parser.add_argument(
        "--name", required=True, help="Peer identity, e.g. peer-a / peer-b"
    )
    parser.add_argument("--port", type=int, default=0, help="libp2p listen port")
    parser.add_argument(
        "--data-dir", default=None, help="Storage dir (default: ./data/<name>)"
    )
    parser.add_argument(
        "--ipfs-api",
        default="http://127.0.0.1:5001/api/v0",
        help="Kubo HTTP API base URL",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional integer seed for a reproducible peer ID",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_listen = sub.add_parser("listen", help="Start a peer and idle, serving requests")
    p_listen.set_defaults(func=cmd_listen)

    p_train = sub.add_parser("train", help="Train a round, checkpoint, upload to IPFS")
    p_train.add_argument("--connect", default=None, help="Multiaddr to announce to")
    p_train.add_argument(
        "--serve-after",
        action="store_true",
        help="Keep the peer alive after training to serve this checkpoint",
    )
    p_train.set_defaults(func=cmd_train)

    p_sync = sub.add_parser("sync", help="Pull the latest checkpoint from a peer")
    p_sync.add_argument("--connect", required=True, help="Multiaddr of the peer to sync from")
    p_sync.set_defaults(func=cmd_sync)

    p_status = sub.add_parser("status", help="Show local (and optionally remote) status")
    p_status.add_argument("--connect", default=None, help="Multiaddr to compare against")
    p_status.set_defaults(func=cmd_status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        trio.run(args.func, args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
