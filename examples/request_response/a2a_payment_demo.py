from __future__ import annotations

import argparse
import json
import logging
import random
import secrets

import multiaddr
import trio

from libp2p import new_host
from libp2p.crypto.secp256k1 import create_new_key_pair
from libp2p.filecoin.address import DEMO_F410_PAYER
from libp2p.peer.peerinfo import info_from_p2p_addr
from libp2p.request_response import JSONCodec, RequestContext, RequestResponse
from libp2p.utils.address_validation import (
    find_free_port,
    get_available_interfaces,
    get_optimal_binding_address,
)

from .a2a_payment_protocol import (
    DEFAULT_COPIES,
    DEFAULT_LOCKUP_EPOCHS,
    DEFAULT_PAYMENT_RATE_USDFC_PER_EPOCH,
    PROTOCOL_ID,
    A2APaymentDemoServer,
    build_authorization_followup_request,
    build_get_agent_card_request,
    build_get_task_request,
    build_send_message_request,
)

logging.basicConfig(level=logging.WARNING)
logging.getLogger("multiaddr").setLevel(logging.WARNING)
logging.getLogger("libp2p").setLevel(logging.WARNING)


def _print_agent_card(card: dict[str, object]) -> None:
    print("Agent Card:")
    print(json.dumps(card, indent=2, sort_keys=True))


def _extract_task(response: dict[str, object]) -> dict[str, object]:
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("JSON-RPC response is missing result")
    task = result.get("task")
    if not isinstance(task, dict):
        raise ValueError("JSON-RPC result is missing task")
    return task


def _print_task(task: dict[str, object], *, title: str) -> None:
    print(f"\n{title}:")
    print(json.dumps(task, indent=2, sort_keys=True))


def _extract_quote(task: dict[str, object]) -> dict[str, object]:
    metadata = task.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("task is missing metadata")
    quote = metadata.get("quote")
    if not isinstance(quote, dict):
        raise ValueError("task metadata is missing quote")
    return quote


def _extract_context_id(task: dict[str, object]) -> str:
    context_id = task.get("contextId")
    if not isinstance(context_id, str):
        raise ValueError("task is missing contextId")
    return context_id


def _extract_task_id(task: dict[str, object]) -> str:
    task_id = task.get("id")
    if not isinstance(task_id, str):
        raise ValueError("task is missing id")
    return task_id


def _extract_state(task: dict[str, object]) -> str:
    status = task.get("status")
    if not isinstance(status, dict):
        raise ValueError("task is missing status")
    state = status.get("state")
    if not isinstance(state, str):
        raise ValueError("task status is missing state")
    return state


async def _handler(
    server: A2APaymentDemoServer,
    request: dict[str, object],
    context: RequestContext,
) -> dict[str, object]:
    del context
    return server.process_request(request)


async def run(
    port: int,
    destination: str | None,
    name: str,
    size: int,
    copies: int,
    with_cdn: bool,
    payer: str,
    max_lockup_usdfc: int | None,
    payment_rate_usdfc_per_epoch: int,
    lockup_epochs: int,
    seed: int | None,
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
    server = A2APaymentDemoServer()

    async with host.run(listen_addrs=listen_addr), trio.open_nursery() as nursery:
        nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)
        rr.set_handler(
            PROTOCOL_ID,
            handler=lambda request, context: _handler(server, request, context),
            codec=codec,
        )
        print(f"I am {host.get_id().to_string()}")

        if not destination:
            peer_id = host.get_id().to_string()
            print("Listener ready, listening on:\n")
            for addr in listen_addr:
                print(f"{addr}/p2p/{peer_id}")

            optimal_addr = get_optimal_binding_address(port)
            optimal_addr_with_peer = f"{optimal_addr}/p2p/{peer_id}"
            print(
                "\nRun this from the same folder in another console:\n\n"
                "a2a-payment-demo "
                f"-d {optimal_addr_with_peer} --name hello.txt --size 256\n\n"
                "To simulate partial provider fulfilment with three "
                "requested copies:\n\n"
                "a2a-payment-demo "
                f"-d {optimal_addr_with_peer} --name hello.txt --size 256 --copies 3\n"
            )
            print("Waiting for incoming requests...")
            await trio.sleep_forever()

        destination_str = destination
        if destination_str is None:
            raise ValueError("destination is required in dialer mode")

        maddr = multiaddr.Multiaddr(destination_str)
        info = info_from_p2p_addr(maddr)
        await host.connect(info)

        card_response = await rr.send_request(
            peer_id=info.peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=build_get_agent_card_request(),
            codec=codec,
        )
        card_result = card_response.get("result")
        if not isinstance(card_result, dict):
            raise ValueError("agent card response is missing result")
        _print_agent_card(card_result)

        initial_task_response = await rr.send_request(
            peer_id=info.peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=build_send_message_request(
                request_id="send-message",
                message_id="msg-store-request",
                content_label=name,
                declared_size_bytes=size,
                copies=copies,
                with_cdn=with_cdn,
                payment_rate_usdfc_per_epoch=payment_rate_usdfc_per_epoch,
                lockup_epochs=lockup_epochs,
            ),
            codec=codec,
        )
        initial_task = _extract_task(initial_task_response)
        _print_task(initial_task, title="Task after initial SendMessage")

        quote = _extract_quote(initial_task)
        task_id = _extract_task_id(initial_task)
        context_id = _extract_context_id(initial_task)
        quoted_lockup = quote.get("depositNeededUsdfc")
        if not isinstance(quoted_lockup, int):
            raise ValueError("quote is missing depositNeededUsdfc")
        approved_lockup = (
            max_lockup_usdfc if max_lockup_usdfc is not None else quoted_lockup
        )

        followup_response = await rr.send_request(
            peer_id=info.peer_id,
            protocol_ids=[PROTOCOL_ID],
            request=build_authorization_followup_request(
                request_id="authorize-payment",
                message_id="msg-authorize-payment",
                task_id=task_id,
                context_id=context_id,
                max_lockup_usdfc=approved_lockup,
                payer=payer,
            ),
            codec=codec,
        )
        auth_task = _extract_task(followup_response)
        _print_task(auth_task, title="Task after payment authorization")

        task_state = _extract_state(auth_task)
        print(f"\nWatching task progress ({task_state}):")
        _STREAMING_INTERVAL = 0.5
        _MAX_POLLS = 10

        for poll_index in range(1, _MAX_POLLS + 1):
            if task_state in (
                "TASK_STATE_COMPLETED",
                "TASK_STATE_FAILED",
                "TASK_STATE_CANCELED",
            ):
                print("  (Task reached terminal state)")
                break

            await trio.sleep(_STREAMING_INTERVAL)
            polled_response = await rr.send_request(
                peer_id=info.peer_id,
                protocol_ids=[PROTOCOL_ID],
                request=build_get_task_request(
                    request_id=f"poll-{poll_index}", task_id=task_id
                ),
                codec=codec,
            )
            polled_task = _extract_task(polled_response)
            new_state = _extract_state(polled_task)
            if new_state != task_state:
                print(f"  State changed: {task_state} -> {new_state}")
                task_state = new_state

        if task_state != _extract_state(auth_task):
            fetched_task_response = await rr.send_request(
                peer_id=info.peer_id,
                protocol_ids=[PROTOCOL_ID],
                request=build_get_task_request(request_id="get-final", task_id=task_id),
                codec=codec,
            )
            fetched_task = _extract_task(fetched_task_response)
            _print_task(fetched_task, title="Final task state (streaming complete)")
        nursery.cancel_scope.cancel()


def main() -> None:
    description = """
    Demonstrates an A2A-shaped Filecoin payment and storage workflow built on top
    of the high-level libp2p request/response helper. Run once without -d to
    start a listener, then run again with -d to perform Agent Card discovery,
    task creation, payment authorization, and final task retrieval.
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
        help="content label to include in the storage request",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=256,
        help="declared size in bytes for the storage request",
    )
    parser.add_argument(
        "--copies",
        type=int,
        default=DEFAULT_COPIES,
        help="requested number of storage copies",
    )
    parser.add_argument(
        "--with-cdn",
        action="store_true",
        help="set the simulated CDN flag on the storage request",
    )
    parser.add_argument(
        "--payer",
        type=str,
        default=DEMO_F410_PAYER,
        help="payer identifier as a Filecoin address (f410 for delegated/EAM, "
        "f0 for ID, f1 for SECP256K1)",
    )
    parser.add_argument(
        "--max-lockup-usdfc",
        type=int,
        help="override the authorized lockup amount; defaults to the quoted deposit",
    )
    parser.add_argument(
        "--payment-rate-usdfc-per-epoch",
        type=int,
        default=DEFAULT_PAYMENT_RATE_USDFC_PER_EPOCH,
        help="simulated Filecoin Pay rate per epoch",
    )
    parser.add_argument(
        "--lockup-epochs",
        type=int,
        default=DEFAULT_LOCKUP_EPOCHS,
        help="simulated Filecoin Pay lockup period in epochs",
    )
    parser.add_argument(
        "-s",
        "--seed",
        type=int,
        help="seed the RNG to make peer IDs reproducible",
    )
    args = parser.parse_args()

    try:
        trio.run(
            run,
            args.port,
            args.destination,
            args.name,
            args.size,
            args.copies,
            args.with_cdn,
            args.payer,
            args.max_lockup_usdfc,
            args.payment_rate_usdfc_per_epoch,
            args.lockup_epochs,
            args.seed,
        )
    except BaseException as exc:
        if _is_keyboard_interrupt_exit(exc):
            return
        raise


def _is_keyboard_interrupt_exit(exc: BaseException) -> bool:
    if isinstance(exc, KeyboardInterrupt):
        return True

    nested = getattr(exc, "exceptions", None)
    if not isinstance(nested, tuple) or not nested:
        return False

    return all(_is_keyboard_interrupt_exit(child) for child in nested)


if __name__ == "__main__":
    main()
