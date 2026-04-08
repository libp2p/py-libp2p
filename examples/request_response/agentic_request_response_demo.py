from __future__ import annotations

import argparse
import hashlib
import json
import logging
import random
import secrets
import time

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.request_response import JSONCodec, RequestContext, RequestResponse
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

from .agentic_protocol import (
    PROTOCOL_ID,
    REQUIRED_SESSION_PERMISSIONS,
    build_capability_query,
    build_store_intent,
    process_request,
)

logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)


def _build_authorization(mode: str, expired_session: bool) -> dict[str, object]:
    if mode == "root":
        return {"mode": "root"}

    expires_at = int(time.time()) - 60 if expired_session else int(time.time()) + 3600
    return {
        "mode": "session_key",
        "expires_at": expires_at,
        "permissions": list(REQUIRED_SESSION_PERMISSIONS),
    }


async def _handler(
    request: dict[str, object], context: RequestContext
) -> dict[str, object]:
    del context
    return process_request(request)


def _make_task_id(name: str, size: int, copies: int, auth_mode: str) -> str:
    digest = hashlib.sha256(f"{name}:{size}:{copies}:{auth_mode}".encode()).hexdigest()
    return f"task-{digest[:8]}"


def _print_capabilities(response: dict[str, object]) -> None:
    print("Capability response:")
    print(json.dumps(response, indent=2, sort_keys=True))


def _print_store_result(response: dict[str, object]) -> None:
    print("\nStore result summary:")
    print(f"  status: {response.get('status')}")
    print(f"  complete: {response.get('complete')}")
    print(f"  task_id: {response.get('task_id')}")
    print(f"  piece_cid: {response.get('piece_cid')}")

    copies = response.get("copies", [])
    if isinstance(copies, list) and copies:
        print("  successful copies:")
        for copy in copies:
            if not isinstance(copy, dict):
                continue
            print(
                "    "
                f"provider={copy.get('provider_id')} "
                f"role={copy.get('role')} "
                f"data_set_id={copy.get('data_set_id')} "
                f"piece_id={copy.get('piece_id')}"
            )

    failed_attempts = response.get("failed_attempts", [])
    if isinstance(failed_attempts, list) and failed_attempts:
        print("  failed attempts:")
        for attempt in failed_attempts:
            if not isinstance(attempt, dict):
                continue
            print(
                "    "
                f"provider={attempt.get('provider_id')} "
                f"role={attempt.get('role')} "
                f"error={attempt.get('error')}"
            )

    errors = response.get("errors", [])
    if isinstance(errors, list) and errors:
        print("  errors:")
        for error in errors:
            print(f"    {error}")

    notes = response.get("notes", [])
    if isinstance(notes, list) and notes:
        print("  notes:")
        for note in notes:
            print(f"    {note}")


async def run(
    port: int,
    destination: str | None,
    name: str,
    size: int,
    copies: int,
    with_cdn: bool,
    auth_mode: str,
    expired_session: bool,
    seed: int | None = None,
) -> None:
    if port <= 0:
        port = find_free_port()
    listen_addr = get_available_interfaces(port)

    if seed is not None:
        random.seed(seed)
        secret_number = random.getrandbits(32 * 8)
        secret = secret_number.to_bytes(length=32, byteorder="big")
    else:
        secret = secrets.token_bytes(32)

    host = new_host(key_pair=create_new_key_pair(secret))
    rr = RequestResponse(host)
    codec = JSONCodec()

    async with host.run(listen_addrs=listen_addr), trio.open_nursery() as nursery:
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
        print(f"I am {host.get_id().to_string()}")

        if not destination:
            rr.set_handler(PROTOCOL_ID, handler=_handler, codec=codec)
            peer_id = host.get_id().to_string()
            print("Listener ready, listening on:\n")
            for addr in listen_addr:
                print(f"{addr}/p2p/{peer_id}")

            optimal_addr = get_optimal_binding_address(port)
            optimal_addr_with_peer = f"{optimal_addr}/p2p/{peer_id}"
            print(
                "\nRun this from the same folder in another console:\n\n"
                "agentic-request-response-demo "
                f"-d {optimal_addr_with_peer} --name hello.txt --size 256\n\n"
                "For a partial-success run that requests too many healthy copies:\n\n"
                "agentic-request-response-demo "
                f"-d {optimal_addr_with_peer} --name hello.txt --size 256 --copies 3\n"
            )
            print("Waiting for incoming requests...")
            await trio.sleep_forever()

        destination_str = destination
        if destination_str is None:
            raise ValueError("destination is required in dialer mode")

        rr.set_handler(PROTOCOL_ID, handler=_handler, codec=codec)
        maddr = multiaddr.Multiaddr(destination_str)
        info = info_from_p2p_addr(maddr)
        await host.connect(info)

        capabilities = await rr.send_request(
            peer_id=info.peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=build_capability_query(),
            codec=codec,
        )
        _print_capabilities(capabilities)

        task_id = _make_task_id(name, size, copies, auth_mode)
        store_result = await rr.send_request(
            peer_id=info.peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=build_store_intent(
                task_id=task_id,
                content_label=name,
                declared_size_bytes=size,
                copies=copies,
                with_cdn=with_cdn,
                dataset_metadata={"source": "agent-demo"},
                piece_metadata={"filename": name},
                authorization=_build_authorization(auth_mode, expired_session),
            ),
            codec=codec,
        )
        _print_store_result(store_result)
        nursery.cancel_scope.cancel()


def main() -> None:
    description = """
    Demonstrates a Filecoin-aligned, locally simulated agent workflow on top of
    the high-level libp2p request/response helper. Run once without -d to start
    a listener, then run again with -d to perform capability discovery and
    submit a storage-style task request.
    """
    example_maddr = (
        "/ip4/[HOST_IP]/tcp/8000/p2p/QmQn4SwGkDZKkUEpBRBvTmheQycxAHJUNmVEnjA2v1qe8Q"
    )
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("-p", "--port", default=0, type=int, help="source port")
    parser.add_argument(
        "-d",
        "--destination",
        type=str,
        help=f"destination multiaddr string, e.g. {example_maddr}",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="hello.txt",
        help="content label to include in the simulated storage request",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=256,
        help="declared size in bytes for the simulated storage request",
    )
    parser.add_argument(
        "--copies",
        type=int,
        default=2,
        help="requested number of simulated storage copies",
    )
    parser.add_argument(
        "--with-cdn",
        action="store_true",
        help="set the simulated CDN flag on the storage request",
    )
    parser.add_argument(
        "--auth-mode",
        choices=("root", "session"),
        default="root",
        help="authorization mode to send with the simulated task",
    )
    parser.add_argument(
        "--expired-session",
        action="store_true",
        help="send an expired simulated session-key authorization",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="seed the RNG to make peer IDs reproducible",
    )
    args = parser.parse_args()

    auth_mode = "session_key" if args.auth_mode == "session" else "root"
    try:
        trio.run(
            run,
            args.port,
            args.destination,
            args.name,
            args.size,
            args.copies,
            args.with_cdn,
            auth_mode,
            args.expired_session,
            args.seed,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
