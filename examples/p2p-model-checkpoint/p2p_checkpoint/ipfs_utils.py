"""
ipfs_utils.py
-------------

A small, dependency-light wrapper around the Kubo (go-ipfs) HTTP RPC API.

Why not the ``ipfshttpclient`` package?
    It pins to a narrow range of daemon versions and regularly breaks on
    current Kubo releases (the upstream project itself points users away
    from it -- see README > Requirements). Kubo's HTTP RPC API is stable
    and trivial to drive with ``requests``, so we talk to it directly:
    everything is a ``POST`` to ``/api/v0/<command>`` with the payload
    either as a query string argument or a multipart file.

The rest of the codebase never imports ``requests`` or knows an HTTP API is
involved -- it only depends on the small interface below (``upload_file`` /
``download_file`` / ``get_bytes``), which keeps this module swappable, e.g.
for the in-memory fake used in the test suite.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol

import requests

DEFAULT_API_BASE = "http://127.0.0.1:5001/api/v0"
DEFAULT_GATEWAY_BASE = "http://127.0.0.1:8080/ipfs"


class IPFSError(RuntimeError):
    """Base class for all IPFS-related failures."""


class IPFSUnavailableError(IPFSError):
    """Raised when the local IPFS daemon can't be reached at all."""


class IPFSNotFoundError(IPFSError):
    """Raised when a CID can't be resolved/fetched."""


class SupportsIPFS(Protocol):
    """The interface the rest of the codebase actually depends on.

    Both :class:`IPFSClient` (real Kubo daemon over HTTP) and any test
    double satisfy this structurally -- no inheritance required.
    """

    def upload_file(self, path: str | Path) -> str: ...

    def download_file(self, cid: str, destination: str | Path) -> Path: ...

    def get_bytes(self, cid: str) -> bytes: ...


class IPFSClient:
    """Talks to a local Kubo daemon's HTTP RPC API.

    Parameters
    ----------
    api_base:
        Base URL of the daemon's RPC API. Defaults to the standard local
        Kubo address. Override via ``IPFS_API_URL`` or pass explicitly for
        a remote/gateway-style node.
    timeout:
        Per-request timeout in seconds. Uploads of large checkpoints may
        need a higher value than the default.
    """

    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        try:
            resp = self._session.post(f"{self.api_base}/id", timeout=5)
            return resp.ok
        except requests.RequestException:
            return False

    def version(self) -> str:
        resp = self._post("/version")
        return resp.json().get("Version", "unknown")

    # ------------------------------------------------------------------ #
    # Upload / download
    # ------------------------------------------------------------------ #
    def upload_file(self, path: str | Path) -> str:
        """Upload a single file, pin it, and return its CID.

        Kubo's ``/add`` endpoint streams back one JSON object per line for
        multi-file/directory adds; for a single file we just take the only
        line.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Cannot upload missing file: {path}")

        with open(path, "rb") as fh:
            files = {"file": (path.name, fh)}
            resp = self._post("/add", params={"pin": "true"}, files=files)

        line = resp.text.strip().splitlines()[-1]
        import json as _json

        data = _json.loads(line)
        cid = data.get("Hash")
        if not cid:
            raise IPFSError(f"Unexpected response from IPFS add: {resp.text!r}")
        return cid

    def get_bytes(self, cid: str) -> bytes:
        """Fetch the full content of ``cid`` into memory. Fine for
        checkpoint-sized archives (single-digit MB); use
        :meth:`download_file` for anything larger."""
        resp = self._post("/cat", params={"arg": cid}, stream=True)
        chunks = []
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if chunk:
                chunks.append(chunk)
        return b"".join(chunks)

    def download_file(self, cid: str, destination: str | Path) -> Path:
        """Stream ``cid`` straight to disk at ``destination``."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        resp = self._post("/cat", params={"arg": cid}, stream=True)
        with open(destination, "wb") as out:
            for chunk in resp.iter_content(chunk_size=1024 * 256):
                if chunk:
                    out.write(chunk)
        return destination

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    def _post(
        self,
        path: str,
        *,
        params: dict | None = None,
        files: dict[str, tuple[str, BinaryIO]] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        url = f"{self.api_base}{path}"
        try:
            resp = self._session.post(
                url,
                params=params,
                files=files,
                timeout=self.timeout,
                stream=stream,
            )
        except requests.exceptions.ConnectionError as exc:
            raise IPFSUnavailableError(
                f"Could not reach IPFS daemon at {self.api_base}. "
                "Is `ipfs daemon` running? "
                "(https://docs.ipfs.tech/install/command-line/)"
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise IPFSUnavailableError(
                f"IPFS daemon at {self.api_base} timed out after {self.timeout}s"
            ) from exc

        if resp.status_code == 404:
            raise IPFSNotFoundError(f"IPFS could not resolve/fetch: {params}")
        if not resp.ok:
            raise IPFSError(
                f"IPFS API error on {path} ({resp.status_code}): {resp.text[:300]}"
            )
        return resp
