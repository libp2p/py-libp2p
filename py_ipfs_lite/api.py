import json
import logging
import os
import tempfile
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from py_ipfs_lite.config import Config
from py_ipfs_lite.exceptions import (
    BlockNotFoundError,
    IPFSLiteError,
    PeerNotStartedError,
    PinNotFoundError,
    RoutingError,
)
from py_ipfs_lite.peer import Peer

logger = logging.getLogger("py_ipfs_lite.api")
# The actual instantiation of the peer depends on how the daemon is run,
# but we can set up a default initialization inside the lifespan if none exists.


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, None]:
    # Check if a peer was already provided (e.g. injected during setup)
    peer = getattr(app.state, "peer", None)
    if not peer:
        # If not, initialize a default one for the daemon
        from libp2p.utils.address_validation import (
            find_free_port,
            get_available_interfaces,
        )

        config = Config()
        port = find_free_port()
        listen_addrs = get_available_interfaces(port)
        peer = Peer(config, listen_addrs=listen_addrs)
        app.state.peer = peer

    # Start the peer
    await peer.start()

    logger.info(f"Daemon P2P Peer ID: {peer.host.id()}")  # type: ignore[union-attr]
    for addr in peer.host.addrs():  # type: ignore[union-attr]
        logger.info(f"  P2P Listening on: {addr}")

    yield

    # Clean up on shutdown
    await peer.close()


app = FastAPI(title="py-ipfs-lite HTTP API", lifespan=lifespan)


@app.exception_handler(IPFSLiteError)
async def ipfs_lite_exception_handler(request: Request, exc: IPFSLiteError) -> Any:
    status_code = 500
    if isinstance(exc, (BlockNotFoundError, PinNotFoundError, RoutingError)):
        status_code = 404
    elif isinstance(exc, PeerNotStartedError):
        status_code = 503
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


@app.post("/api/v0/add")
async def add_file(request: Request, file: UploadFile = File(...)) -> Any:
    """Add a file to the local blockstore and announce it."""
    peer: Peer = request.app.state.peer

    # Save the uploaded file to a temporary file, then add it via peer
    fd, path = tempfile.mkstemp()
    try:
        with os.fdopen(fd, "wb") as f:
            content = await file.read()
            f.write(content)

        cid_str = await peer.add_file(path)
        return JSONResponse(
            content={"Name": file.filename, "Hash": cid_str, "Size": str(len(content))}
        )
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.remove(path)


@app.post("/api/v0/cat")
@app.get("/api/v0/cat")
async def cat_file(
    request: Request,
    arg: str = Query(..., description="The path to the IPFS object(s) to be outputted"),
) -> Any:
    """Fetch a file by its CID."""
    peer: Peer = request.app.state.peer
    try:
        content_iter = await peer.get_file(arg, stream=True)
        from fastapi.responses import StreamingResponse

        return StreamingResponse(content_iter, media_type="application/octet-stream")  # type: ignore[arg-type]
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/dag/put")
async def dag_put(
    request: Request, store_codec: str = Query("dag-json", alias="store-codec")
) -> Any:
    """Store a generic DAG node."""
    peer: Peer = request.app.state.peer
    body = await request.body()
    try:
        node_data = json.loads(body)
        cid_str = await peer.add_node(node_data, codec=store_codec)
        return JSONResponse(content={"Cid": {"/": cid_str}})
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/dag/get")
@app.get("/api/v0/dag/get")
async def dag_get(
    request: Request, arg: str = Query(..., description="The object to get")
) -> Any:
    """Retrieve a generic DAG node."""
    peer: Peer = request.app.state.peer
    try:
        node_data = await peer.get_node(arg)
        return JSONResponse(content=node_data)
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/block/stat")
async def block_stat(
    request: Request,
    arg: str = Query(
        ..., description="The base58 multihash of an existing block to stat"
    ),
) -> Any:
    """Check if a block exists locally and get its size."""
    peer: Peer = request.app.state.peer
    from libp2p.bitswap.cid import parse_cid

    try:
        cid = parse_cid(arg)
        data = await peer.blockstore.get(cid)  # type: ignore[union-attr]
        if data is None:
            raise HTTPException(status_code=404, detail="Block not found locally")

        return JSONResponse(content={"Key": arg, "Size": len(data)})  # type: ignore[arg-type]
    except HTTPException:
        raise
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/block/rm")
async def block_rm(
    request: Request,
    arg: str = Query(..., description="Bash58 multihash of block(s) to remove"),
) -> Any:
    """Remove a raw block from the local blockstore."""
    peer: Peer = request.app.state.peer
    try:
        await peer.remove_node(arg)
        return JSONResponse(content={"Hash": arg, "Error": ""})
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/pin/add")
async def pin_add(
    request: Request,
    arg: str = Query(..., description="Path to object(s) to be pinned"),
    recursive: bool = Query(True),
) -> Any:
    """Pin a CID."""
    peer: Peer = request.app.state.peer
    try:
        await peer.add_pin(arg, recursive=recursive)
        return JSONResponse(content={"Pins": [arg]})
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/pin/rm")
async def pin_rm(
    request: Request,
    arg: str = Query(..., description="Path to object(s) to be unpinned"),
) -> Any:
    """Unpin a CID."""
    peer: Peer = request.app.state.peer
    try:
        await peer.remove_pin(arg)
        return JSONResponse(content={"Pins": [arg]})
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/repo/gc")
async def repo_gc(request: Request) -> Any:
    """Run garbage collection."""
    peer: Peer = request.app.state.peer
    try:
        import dataclasses

        stats = await peer.gc()
        return JSONResponse(content=dataclasses.asdict(stats))
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/refs/local")
async def refs_local(request: Request) -> Any:
    """List all CIDs stored in the local blockstore."""
    peer: Peer = request.app.state.peer
    try:
        keys = peer.blockstore.all_keys()  # type: ignore[union-attr]
        results = []
        for k in keys:
            results.append({"Ref": k, "Err": ""})
        # Kubo streams this as NDJSON, but returning a JSON array of objects is easier for testing
        return JSONResponse(content={"Refs": results})
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/version")
@app.get("/api/v0/version")
async def api_version() -> Any:
    """Get the version of py-ipfs-lite."""
    return JSONResponse(
        content={"Version": "0.1.0", "Commit": "", "System": "py-ipfs-lite"}
    )


@app.post("/api/v0/id")
@app.get("/api/v0/id")
async def api_id(request: Request) -> Any:
    """Show IPFS node id info."""
    peer: Peer = request.app.state.peer
    return JSONResponse(
        content={
            "ID": peer.host.id().to_base58(),  # type: ignore[union-attr]
            "Addresses": [str(addr) for addr in peer.host.addrs()],  # type: ignore[union-attr]
        }
    )


@app.post("/api/v0/repo/stat")
@app.get("/api/v0/repo/stat")
async def repo_stat(request: Request) -> Any:
    """Get stats for the currently used repo."""
    peer: Peer = request.app.state.peer
    try:
        from libp2p.bitswap.cid import cid_to_bytes, parse_cid

        keys = peer.blockstore.all_keys()  # type: ignore[union-attr]
        num_objects = len(keys)
        repo_size = 0
        for k in keys:
            cid_bytes = cid_to_bytes(parse_cid(k))
            repo_size += await peer.blockstore.get_size(cid_bytes)  # type: ignore[union-attr, misc]

        path = peer.config.blockstore_path
        if peer.config.blockstore_type == "memory":
            path = ""

        return JSONResponse(
            content={
                "NumObjects": num_objects,
                "RepoSize": repo_size,
                "RepoPath": path,
                "Version": "1",
            }
        )
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/swarm/peers")
@app.get("/api/v0/swarm/peers")
async def swarm_peers(request: Request) -> Any:
    """List peers with open connections."""
    peer: Peer = request.app.state.peer
    network = peer.host.get_network()  # type: ignore[union-attr]
    peers_data = []

    try:
        if hasattr(network, "connections"):
            conns_dict = network.connections
            for peer_id_obj, conns in conns_dict.items():
                if not isinstance(conns, list):
                    conns = [conns]

                for c in conns:
                    addr_str = ""
                    try:
                        if hasattr(c, "remote_addr"):
                            addr_str = str(c.remote_addr)
                        elif hasattr(c, "get_remote_multiaddr"):
                            addr_str = str(c.get_remote_multiaddr())
                    except Exception:
                        pass

                    peers_data.append(
                        {
                            "Peer": peer_id_obj.to_base58(),
                            "Addr": addr_str,
                            "Direction": 0,
                        }
                    )
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))

    return JSONResponse(content={"Peers": peers_data})


@app.get("/debug/metrics/prometheus")
async def metrics() -> Any:
    """Expose Prometheus metrics."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v0/repo/version")
@app.get("/api/v0/repo/version")
async def repo_version(request: Request) -> Any:
    """Return the datastore/repo version."""
    peer: Peer = request.app.state.peer

    if peer.config.blockstore_type == "filesystem" and peer.config.blockstore_path:
        from py_ipfs_lite.versioning import get_repo_version

        v = get_repo_version(peer.config.blockstore_path)
    else:
        v = "memory"

    return JSONResponse(content={"Version": v})


@app.post("/api/v0/name/publish")
async def name_publish(
    request: Request,
    arg: str = Query(..., description="IPFS path of the object to be published"),
) -> Any:
    """Publish an IPNS record."""
    peer: Peer = request.app.state.peer
    try:
        # Default lifetime is 24 hours.
        name = await peer.publish_name(arg, lifetime_hours=24)
        return JSONResponse(content={"Name": name, "Value": arg})
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v0/name/resolve")
@app.get("/api/v0/name/resolve")
async def name_resolve(
    request: Request, arg: str = Query(..., description="The IPNS name to resolve")
) -> Any:
    """Resolve an IPNS record."""
    peer: Peer = request.app.state.peer
    try:
        value = await peer.resolve_name(arg)
        return JSONResponse(content={"Path": value})
    except Exception as e:
        if isinstance(e, IPFSLiteError):
            raise
        raise HTTPException(status_code=500, detail=str(e))
