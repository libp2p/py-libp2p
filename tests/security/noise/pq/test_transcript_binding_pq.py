"""
Transcript-bound negotiation over the XXhfs (post-quantum) handshake.

The mechanism itself is covered in
``tests/core/security/noise/test_transcript_binding.py``. What is specific
here is that ``PatternXXhfs`` reads ``h`` off its own SymmetricState at the
right instant, so these tests exercise the full three-message handshake rather
than the encoding and the check in isolation.
"""

import contextlib

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.exceptions import SecurityProtocolDowngrade
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs
from libp2p.security.noise.pq.transport_pq import (
    IDENTITY_BOUND_PROTOCOL_ID,
    PROTOCOL_ID,
    TransportPQ,
    protocol_id_for,
)
from libp2p.security.noise.transcript_binding import (
    TranscriptBindingConfig,
    TranscriptBindingVariant,
)
from tests.security.noise.pq.helpers import make_conn_pair

HFS = "/noise-mlkem768-hfs/0.2.0"
NOISE = "/noise"

VARIANTS: list[TranscriptBindingVariant] = ["extension", "identity"]


def make_config(
    actual_protocol: str = HFS,
    protocols: tuple[str, ...] = (HFS, NOISE),
    mode: str = "enforce",
    variant: str = "extension",
) -> TranscriptBindingConfig:
    return TranscriptBindingConfig(
        security_protocols=protocols,
        actual_protocol=actual_protocol,
        mode=mode,  # type: ignore[arg-type]
        variant=variant,  # type: ignore[arg-type]
    )


def make_pattern(
    config: TranscriptBindingConfig | None,
) -> tuple[PatternXXhfs, ID]:
    keypair = create_new_key_pair()
    peer = ID.from_pubkey(keypair.public_key)
    pattern = PatternXXhfs(
        local_peer=peer,
        libp2p_privkey=keypair.private_key,
        noise_static_key=X25519PrivateKey.new(),
        transcript_binding=config,
    )
    return pattern, peer


async def run_handshake(
    initiator: PatternXXhfs,
    responder: PatternXXhfs,
    responder_peer: ID,
    timeout: float | None = None,
) -> list[BaseException]:
    """
    Run one XXhfs handshake over an in-memory connection pair.

    Each side's exception is collected rather than allowed to propagate, so a
    test can assert on both peers independently.

    Args:
        initiator: The dialling pattern.
        responder: The listening pattern.
        responder_peer: The peer ID the initiator expects.
        timeout: Seconds to wait when only one side is expected to refuse;
            None means both sides must finish, within 60 seconds.

    Returns:
        list: What each side raised, empty when the handshake succeeded.

    """
    init_conn, resp_conn = make_conn_pair()
    errors: list[BaseException] = []

    async def dial() -> None:
        try:
            await initiator.handshake_outbound(init_conn, responder_peer)
        except Exception as exc:
            errors.append(exc)

    async def listen() -> None:
        try:
            await responder.handshake_inbound(resp_conn)
        except Exception as exc:
            errors.append(exc)

    if timeout is None:
        with trio.fail_after(60):
            async with trio.open_nursery() as nursery:
                nursery.start_soon(dial)
                nursery.start_soon(listen)
        return errors

    # When only one side refuses, the other blocks on a message that never
    # arrives: the in-memory pair delivers no EOF. Collect what was raised.
    with trio.move_on_after(timeout) as scope:
        async with trio.open_nursery() as nursery:
            nursery.start_soon(dial)
            nursery.start_soon(listen)
    if scope.cancelled_caught and not errors:
        raise AssertionError(f"handshake neither completed nor failed in {timeout}s")
    return errors


class _CountingConn:
    """Delegates to a connection and counts the messages written to it."""

    def __init__(self, inner: object) -> None:
        self._inner = inner
        self.writes = 0

    async def write(self, data: bytes) -> None:
        self.writes += 1
        await self._inner.write(data)  # type: ignore[attr-defined]

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


@pytest.mark.trio
@pytest.mark.parametrize("variant", VARIANTS)
async def test_honest_session_completes(variant: str) -> None:
    """The post-quantum suite is what both peers prefer, and what they got."""
    config = make_config(variant=variant)
    initiator, _ = make_pattern(config)
    responder, responder_peer = make_pattern(config)

    assert await run_handshake(initiator, responder, responder_peer) == []


@pytest.mark.trio
@pytest.mark.parametrize("variant", VARIANTS)
async def test_simulated_downgrade_is_refused(variant: str) -> None:
    """
    Running XXhfs while both peers' offers imply plain /noise is as much a
    mismatch as the other way round, and is refused just the same.
    """
    config = make_config(actual_protocol=HFS, protocols=(NOISE, HFS), variant=variant)
    initiator, _ = make_pattern(config)
    responder, responder_peer = make_pattern(config)

    errors = await run_handshake(initiator, responder, responder_peer, timeout=5)

    # The dialer refuses after msg B, before sending msg C, so the listener
    # never gets far enough to run its own check.
    assert len(errors) == 1
    assert isinstance(errors[0], SecurityProtocolDowngrade)


@pytest.mark.trio
@pytest.mark.parametrize("variant", VARIANTS)
async def test_the_listener_refuses_a_downgrade_the_dialer_only_logs(
    variant: str,
) -> None:
    """A warn-mode dialer sends msg C anyway; the listener's check refuses."""
    protocols = (NOISE, HFS)
    dialer = make_config(protocols=protocols, variant=variant, mode="warn")
    listener = make_config(protocols=protocols, variant=variant)
    initiator, _ = make_pattern(dialer)
    responder, responder_peer = make_pattern(listener)

    errors = await run_handshake(initiator, responder, responder_peer, timeout=5)

    assert len(errors) == 1
    assert isinstance(errors[0], SecurityProtocolDowngrade)


@pytest.mark.trio
async def test_the_dialer_refuses_before_sending_msg_c() -> None:
    """Msg C carries the dialer's payload; it must not leave on a downgrade."""
    config = make_config(protocols=(NOISE, HFS))
    initiator, _ = make_pattern(config)
    responder, responder_peer = make_pattern(config)
    init_conn, resp_conn = make_conn_pair()
    counting = _CountingConn(init_conn)
    raised: list[BaseException] = []

    async def dial() -> None:
        try:
            await initiator.handshake_outbound(
                counting,  # type: ignore[arg-type]
                responder_peer,
            )
        except Exception as exc:
            raised.append(exc)

    async def listen() -> None:
        # Blocks on msg C, which should never arrive.
        with contextlib.suppress(Exception):
            await responder.handshake_inbound(resp_conn)

    with trio.move_on_after(10):
        async with trio.open_nursery() as nursery:
            nursery.start_soon(dial)
            nursery.start_soon(listen)
            while not raised:
                await trio.sleep(0.01)
            nursery.cancel_scope.cancel()

    assert len(raised) == 1 and isinstance(raised[0], SecurityProtocolDowngrade)
    assert counting.writes == 1, "only msg A may leave the dialer"


@pytest.mark.trio
@pytest.mark.parametrize("initiator_binds", [True, False], ids=["dialer", "listener"])
async def test_a_peer_that_sends_no_binding_is_accepted(initiator_binds: bool) -> None:
    """A peer without the extension is an older peer, not an attacker."""
    config = make_config()
    bound, bound_peer = make_pattern(config)
    unbound, unbound_peer = make_pattern(None)

    if initiator_binds:
        errors = await run_handshake(bound, unbound, unbound_peer)
    else:
        errors = await run_handshake(unbound, bound, bound_peer)

    assert errors == []


@pytest.mark.trio
async def test_warn_mode_completes_the_handshake() -> None:
    """Warn mode reports a mismatch without refusing the connection."""
    config = make_config(protocols=(NOISE, HFS), mode="warn")
    initiator, _ = make_pattern(config)
    responder, responder_peer = make_pattern(config)

    assert await run_handshake(initiator, responder, responder_peer) == []


class TestIdentifierMovesWithTheVariant:
    """
    The identity variant carries its own protocol identifier.

    A peer binding that way verifies a different message, so it must not answer
    to the identifier used by peers that do not. Letting multistream-select
    separate them is the difference between "no protocol in common" and a
    handshake that negotiates and then fails on a signature.
    """

    def _transport(self, config: TranscriptBindingConfig | None) -> TransportPQ:
        return TransportPQ(
            libp2p_keypair=create_new_key_pair(),
            noise_privkey=X25519PrivateKey.new(),
            transcript_binding=config,
        )

    def test_identity_variant_advertises_the_bound_identifier(self) -> None:
        config = make_config(
            actual_protocol=IDENTITY_BOUND_PROTOCOL_ID,
            protocols=(IDENTITY_BOUND_PROTOCOL_ID, NOISE),
            variant="identity",
        )

        assert self._transport(config).protocol_id == IDENTITY_BOUND_PROTOCOL_ID

    def test_extension_variant_keeps_the_ordinary_identifier(self) -> None:
        config = make_config(actual_protocol=HFS, variant="extension")

        assert self._transport(config).protocol_id == PROTOCOL_ID

    def test_off_and_unconfigured_keep_the_ordinary_identifier(self) -> None:
        off = make_config(actual_protocol=HFS, variant="identity", mode="off")

        assert self._transport(off).protocol_id == PROTOCOL_ID
        assert self._transport(None).protocol_id == PROTOCOL_ID

    def test_protocol_id_for_matches_the_transport(self) -> None:
        for config in (
            None,
            make_config(actual_protocol=HFS, variant="extension"),
            make_config(
                actual_protocol=IDENTITY_BOUND_PROTOCOL_ID,
                protocols=(IDENTITY_BOUND_PROTOCOL_ID, NOISE),
                variant="identity",
            ),
        ):
            assert protocol_id_for(config) == self._transport(config).protocol_id

    def test_a_config_naming_the_wrong_identifier_is_refused(self) -> None:
        """
        The downgrade check compares against ``actual_protocol``, so a config
        naming an identifier this transport does not advertise would compare
        against the wrong thing and either miss a downgrade or invent one.
        """
        config = make_config(actual_protocol=HFS, variant="identity")

        with pytest.raises(ValueError, match="advertises"):
            self._transport(config)
