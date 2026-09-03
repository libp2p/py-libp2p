"""
tests/fake_ipfs.py
-------------------

An in-memory stand-in for a Kubo daemon, used throughout the test suite so
none of the tests require a real ``ipfs daemon`` to be running.

It satisfies :class:`p2p_checkpoint.ipfs_utils.SupportsIPFS` structurally
(same method names/signatures as :class:`IPFSClient`) without inheriting
from it, and content-addresses uploads the same way IPFS conceptually does
(hash of the bytes -> id), which is enough to exercise every code path in
``peer.py`` / ``sync.py`` that only cares about "upload gives me a stable
id, and that id gets me the same bytes back".
"""

from __future__ import annotations

import hashlib
from pathlib import Path


class FakeIPFS:
    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.upload_count = 0
        self.download_count = 0

    def upload_file(self, path: str | Path) -> str:
        path = Path(path)
        data = path.read_bytes()
        cid = "bafy" + hashlib.sha256(data).hexdigest()[:46]
        self.store[cid] = data
        self.upload_count += 1
        return cid

    def get_bytes(self, cid: str) -> bytes:
        if cid not in self.store:
            raise FileNotFoundError(f"No such CID in FakeIPFS: {cid}")
        self.download_count += 1
        return self.store[cid]

    def download_file(self, cid: str, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.get_bytes(cid))
        return destination
