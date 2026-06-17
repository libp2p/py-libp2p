import json
import logging
from pathlib import Path

import trio

logger = logging.getLogger("py_ipfs_lite.api")

API_PORT = 5002


async def api_server_handler(server_stream, dag, host):
    """Handle an incoming API request."""
    try:
        # Use an unbounded capacity receive stream for simplicity, reading lines
        # In a real app we'd buffer and read until newline
        buffer = bytearray()
        while True:
            chunk = await server_stream.receive_some(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if b"\n" in buffer:
                break

        if not buffer:
            return

        line = buffer.split(b"\n")[0].decode("utf-8")
        req = json.loads(line)

        cmd = req.get("cmd")
        resp = {}

        if cmd == "add":
            filepath = req.get("file")
            file_path_obj = Path(filepath)
            if not file_path_obj.exists():
                resp = {"status": "error", "error": f"File not found: {filepath}"}
            else:
                cid = await dag.add_file(filepath, wrap_with_directory=False)
                from libp2p.bitswap.cid import format_cid_for_display

                addrs = [str(a) for a in host.get_addrs()]
                resp = {
                    "status": "ok",
                    "cid": format_cid_for_display(cid),
                    "peer_id": host.get_id().to_base58(),
                    "addrs": addrs,
                }
        elif cmd == "get":
            # For get, we can optionally connect to the provider and fetch
            cid_str = req.get("cid")
            provider_addr = req.get("provider")
            out_file = req.get("out")

            if provider_addr:
                from multiaddr import Multiaddr
                from libp2p.peer.peerinfo import info_from_p2p_addr

                maddr = Multiaddr(provider_addr)
                info = info_from_p2p_addr(maddr)
                await host.connect(info)

            from libp2p.bitswap.cid import parse_cid

            cid = parse_cid(cid_str)
            content, filename = await dag.fetch_file(cid)

            if out_file:
                with open(out_file, "wb") as f:
                    f.write(content)
                resp = {
                    "status": "ok",
                    "message": f"Saved {len(content)} bytes to {out_file}",
                }
            else:
                resp = {
                    "status": "ok",
                    "message": f"Fetched {len(content)} bytes",
                    "content": content.decode("utf-8", errors="replace"),
                }
        else:
            resp = {"status": "error", "error": f"Unknown command: {cmd}"}

        await server_stream.send_all((json.dumps(resp) + "\n").encode("utf-8"))
    except Exception as e:
        logger.error(f"API Error: {e}", exc_info=True)
        try:
            resp = {"status": "error", "error": str(e)}
            await server_stream.send_all((json.dumps(resp) + "\n").encode("utf-8"))
        except:
            pass


async def start_api_server(dag, host, task_status=trio.TASK_STATUS_IGNORED):
    """Start the TCP API server."""
    from functools import partial

    handler = partial(api_server_handler, dag=dag, host=host)
    await trio.serve_tcp(handler, API_PORT, host="127.0.0.1", task_status=task_status)


async def api_client_send(req: dict) -> dict:
    """Send a request to the local API server."""
    try:
        client_stream = await trio.open_tcp_stream("127.0.0.1", API_PORT)
        async with client_stream:
            await client_stream.send_all((json.dumps(req) + "\n").encode("utf-8"))
            buffer = bytearray()
            while True:
                chunk = await client_stream.receive_some(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
                if b"\n" in buffer:
                    break
            if not buffer:
                return {"status": "error", "error": "Empty response from daemon"}
            line = buffer.split(b"\n")[0].decode("utf-8")
            return json.loads(line)
    except OSError:
        return {
            "status": "error",
            "error": "Could not connect to daemon. Is it running? (run 'uv run python main.py daemon')",
        }
