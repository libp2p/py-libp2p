"""
Tests for transcript-bound security protocol negotiation.

Covers the canonical encoding, the two signature payloads, the downgrade check
itself, and the classical Noise XX handshake end to end with the binding on.
The XXhfs side of the same feature lives in
``tests/security/noise/pq/test_transcript_binding_pq.py``.
"""

from collections.abc import (
    Iterator,
)
import logging

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.security.noise.exceptions import (
    SecurityProtocolDowngrade,
)
from libp2p.security.noise.messages import (
    NoiseExtensions,
    build_handshake_payload,
    make_data_to_be_signed,
    verify_handshake_payload_sig,
)
from libp2p.security.noise.patterns import PatternXX
from libp2p.security.noise.transcript_binding import (
    MAX_PROTOCOLS,
    TRANSCRIPT_SIG_PREFIX,
    IdentityBinding,
    TranscriptBindingConfig,
    TranscriptBindingVariant,
    canonical_protocols,
    check_negotiation,
    expected_protocol,
    has_transcript_binding,
    transcript_signature_payload,
)
from libp2p.security.noise.transport import Transport
from tests.utils.factories import noise_static_key_factory, raw_conn_factory

HFS = "/noise-mlkem768-hfs/0.2.0"
NOISE = "/noise"

#: A stand-in for a real Noise transcript hash. The only property that matters
#: to the unit tests is that both sides use the same value.
FAKE_HASH = bytes(range(32))

VARIANTS: list[TranscriptBindingVariant] = ["extension", "identity"]


def make_config(
    actual_protocol: str = NOISE,
    protocols: tuple[str, ...] = (HFS, NOISE),
    mode: str = "enforce",
    variant: str = "extension",
) -> TranscriptBindingConfig:
    """Build a config without repeating the keyword names in every test."""
    return TranscriptBindingConfig(
        security_protocols=protocols,
        actual_protocol=actual_protocol,
        mode=mode,  # type: ignore[arg-type]
        variant=variant,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Canonical encoding
# ---------------------------------------------------------------------------


class TestCanonicalProtocols:
    def test_length_prefixes_are_big_endian_uint16(self) -> None:
        assert canonical_protocols(["ab", "c"]) == b"\x00\x02ab\x00\x01c"

    def test_different_split_points_encode_differently(self) -> None:
        """
        Plain concatenation would make these two lists identical, which would
        let an attacker swap one for the other under a single signature.
        """
        assert canonical_protocols(["ab", "c"]) != canonical_protocols(["a", "bc"])

    def test_order_is_significant(self) -> None:
        assert canonical_protocols([HFS, NOISE]) != canonical_protocols([NOISE, HFS])

    def test_empty_list_encodes_to_empty_bytes(self) -> None:
        assert canonical_protocols([]) == b""

    def test_non_ascii_identifiers_use_utf8(self) -> None:
        assert canonical_protocols(["é"]) == b"\x00\x02\xc3\xa9"

    def test_rejects_too_many_protocols(self) -> None:
        with pytest.raises(ValueError, match="too many security protocols"):
            canonical_protocols([f"/p/{i}" for i in range(MAX_PROTOCOLS + 1)])

    def test_rejects_an_overlong_identifier(self) -> None:
        with pytest.raises(ValueError, match="too long"):
            canonical_protocols(["x" * 0x10000])


# ---------------------------------------------------------------------------
# Signature payloads
# ---------------------------------------------------------------------------


class TestSignaturePayloads:
    def test_extension_variant_payload_layout(self) -> None:
        assert TRANSCRIPT_SIG_PREFIX == b"noise-libp2p-transcript:"
        assert transcript_signature_payload(FAKE_HASH, [HFS, NOISE]) == (
            b"noise-libp2p-transcript:" + FAKE_HASH + canonical_protocols([HFS, NOISE])
        )

    def test_identity_variant_payload_layout(self) -> None:
        static_pubkey = noise_static_key_factory().get_public_key()
        binding = IdentityBinding(FAKE_HASH, (HFS, NOISE))

        assert make_data_to_be_signed(static_pubkey, binding) == (
            b"noise-libp2p-static-key:"
            + static_pubkey.to_bytes()
            + FAKE_HASH
            + canonical_protocols([HFS, NOISE])
        )

    def test_unbound_payload_is_unchanged(self) -> None:
        static_pubkey = noise_static_key_factory().get_public_key()

        assert make_data_to_be_signed(static_pubkey) == (
            b"noise-libp2p-static-key:" + static_pubkey.to_bytes()
        )


# ---------------------------------------------------------------------------
# Configuration and the expected-outcome function
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_defaults_are_extension_and_enforce(self) -> None:
        config = TranscriptBindingConfig(
            security_protocols=(NOISE,), actual_protocol=NOISE
        )
        assert config.variant == "extension"
        assert config.mode == "enforce"
        assert config.enabled is True

    def test_off_is_not_enabled(self) -> None:
        assert make_config(mode="off").enabled is False

    def test_own_protocol_must_be_in_the_list(self) -> None:
        with pytest.raises(ValueError, match="must include this transport's own"):
            TranscriptBindingConfig(security_protocols=(HFS,), actual_protocol=NOISE)


class TestExpectedProtocol:
    def test_picks_the_dialers_first_common_entry(self) -> None:
        assert expected_protocol([HFS, NOISE], [NOISE, HFS]) == HFS

    def test_listener_order_does_not_matter(self) -> None:
        assert expected_protocol([NOISE, HFS], [HFS, NOISE]) == NOISE

    def test_returns_none_when_nothing_is_shared(self) -> None:
        assert expected_protocol([HFS], [NOISE]) is None


# ---------------------------------------------------------------------------
# The downgrade check
# ---------------------------------------------------------------------------


def remote_offer(*protocols: str) -> NoiseExtensions:
    """Extensions as they arrive from a peer that did send a binding."""
    return NoiseExtensions(
        security_protocols=list(protocols), transcript_sig=b"already-verified"
    )


class _LogCollector(logging.Handler):
    """Collects records straight off one logger."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def binding_log_records() -> Iterator[list[logging.LogRecord]]:
    """
    Capture records from the transcript-binding logger directly.

    pytest's ``caplog`` attaches at the root logger, and
    ``libp2p/utils/logging.py`` sets ``propagate = False`` on the ``libp2p``
    hierarchy at import time, so records never reach it. Attaching a handler
    to the target logger sidesteps that entirely.
    """
    target = logging.getLogger("libp2p.security.noise.transcript_binding")
    handler = _LogCollector()
    previous_level = target.level
    previous_disabled = target.disabled
    target.setLevel(logging.DEBUG)
    target.disabled = False
    target.addHandler(handler)
    try:
        yield handler.records
    finally:
        target.removeHandler(handler)
        target.setLevel(previous_level)
        target.disabled = previous_disabled


class TestCheckNegotiation:
    def test_honest_session_passes(self) -> None:
        check_negotiation(
            make_config(actual_protocol=HFS),
            is_initiator=True,
            remote_extensions=remote_offer(HFS, NOISE),
        )

    def test_downgrade_raises_under_enforce(self) -> None:
        with pytest.raises(SecurityProtocolDowngrade, match=HFS):
            check_negotiation(
                make_config(actual_protocol=NOISE),
                is_initiator=True,
                remote_extensions=remote_offer(HFS, NOISE),
            )

    def test_responder_detects_a_stripped_proposal(self) -> None:
        """The listener sees the dialer's real offer inside the payload."""
        with pytest.raises(SecurityProtocolDowngrade):
            check_negotiation(
                make_config(actual_protocol=NOISE),
                is_initiator=False,
                remote_extensions=remote_offer(HFS, NOISE),
            )

    def test_disjoint_offers_are_reported(self) -> None:
        with pytest.raises(SecurityProtocolDowngrade, match="no protocol in common"):
            check_negotiation(
                make_config(actual_protocol=NOISE, protocols=(NOISE,)),
                is_initiator=True,
                remote_extensions=remote_offer(HFS),
            )

    def test_warn_mode_logs_but_continues(
        self, binding_log_records: list[logging.LogRecord]
    ) -> None:
        check_negotiation(
            make_config(actual_protocol=NOISE, mode="warn"),
            is_initiator=True,
            remote_extensions=remote_offer(HFS, NOISE),
        )

        warnings = [r for r in binding_log_records if r.levelno >= logging.WARNING]
        assert warnings, "a mismatch in warn mode must not be a DEBUG-level event"
        assert "downgrade detected" in " ".join(r.getMessage() for r in warnings)

    def test_off_mode_checks_nothing(self) -> None:
        check_negotiation(
            make_config(actual_protocol=NOISE, mode="off"),
            is_initiator=True,
            remote_extensions=remote_offer(HFS, NOISE),
        )

    def test_unconfigured_peer_checks_nothing(self) -> None:
        check_negotiation(None, is_initiator=True, remote_extensions=remote_offer(HFS))

    @pytest.mark.parametrize("mode", ["warn", "enforce"])
    @pytest.mark.parametrize(
        "extensions",
        [None, NoiseExtensions(), NoiseExtensions(security_protocols=[HFS, NOISE])],
        ids=["no-extensions", "empty-extensions", "list-without-signature"],
    )
    def test_a_peer_without_a_binding_is_never_an_attack(
        self, mode: str, extensions: NoiseExtensions | None
    ) -> None:
        """
        Stripping the field is indistinguishable from talking to an older
        peer, so it is ignored in every mode.
        """
        check_negotiation(
            make_config(actual_protocol=NOISE, mode=mode),
            is_initiator=True,
            remote_extensions=extensions,
        )

    def test_extension_variant_needs_both_halves(self) -> None:
        listed = NoiseExtensions(security_protocols=[HFS])

        assert has_transcript_binding(None) is False
        assert has_transcript_binding(NoiseExtensions()) is False
        assert has_transcript_binding(listed) is False
        assert has_transcript_binding(remote_offer(HFS)) is True

    def test_identity_variant_needs_only_the_list(self) -> None:
        """
        The list is covered by identity_sig, which has already been verified
        over exactly these bytes by the time the check runs.
        """
        listed = NoiseExtensions(security_protocols=[HFS])

        assert has_transcript_binding(None, "identity") is False
        assert has_transcript_binding(NoiseExtensions(), "identity") is False
        assert has_transcript_binding(listed, "identity") is True

    def test_identity_variant_detects_a_downgrade(self) -> None:
        """
        Regression guard: the identity variant carries no transcript_sig, so a
        check keyed on that field alone would silently never fire.
        """
        with pytest.raises(SecurityProtocolDowngrade):
            check_negotiation(
                make_config(actual_protocol=NOISE, variant="identity"),
                is_initiator=True,
                remote_extensions=NoiseExtensions(
                    security_protocols=[HFS, NOISE], transcript_sig=b""
                ),
            )


# ---------------------------------------------------------------------------
# Payload signing and verification
# ---------------------------------------------------------------------------


class TestPayloadVerification:
    @pytest.mark.parametrize("variant", VARIANTS)
    def test_untampered_payload_verifies(self, variant: str) -> None:
        keypair = create_new_key_pair()
        static_key = noise_static_key_factory()
        config = make_config(actual_protocol=HFS, variant=variant)

        payload = build_handshake_payload(
            keypair.private_key,
            static_key.get_public_key(),
            config=config,
            payload_hash=FAKE_HASH,
        )

        assert payload.extensions is not None
        assert payload.extensions.security_protocols == [HFS, NOISE]
        assert verify_handshake_payload_sig(
            payload, static_key.get_public_key(), config=config, payload_hash=FAKE_HASH
        )

    @pytest.mark.parametrize("variant", VARIANTS)
    def test_tampered_protocol_list_fails_verification(self, variant: str) -> None:
        """An attacker rewriting the list would have to forge a signature."""
        keypair = create_new_key_pair()
        static_key = noise_static_key_factory()
        config = make_config(actual_protocol=NOISE, variant=variant)

        payload = build_handshake_payload(
            keypair.private_key,
            static_key.get_public_key(),
            config=config,
            payload_hash=FAKE_HASH,
        )
        assert payload.extensions is not None
        payload.extensions.security_protocols = [NOISE]

        assert not verify_handshake_payload_sig(
            payload, static_key.get_public_key(), config=config, payload_hash=FAKE_HASH
        )

    def test_a_replayed_binding_fails_under_another_transcript(self) -> None:
        keypair = create_new_key_pair()
        static_key = noise_static_key_factory()
        config = make_config(actual_protocol=HFS)

        payload = build_handshake_payload(
            keypair.private_key,
            static_key.get_public_key(),
            config=config,
            payload_hash=FAKE_HASH,
        )

        assert not verify_handshake_payload_sig(
            payload, static_key.get_public_key(), config=config, payload_hash=bytes(32)
        )

    def test_binding_is_absent_when_disabled(self) -> None:
        keypair = create_new_key_pair()
        static_key = noise_static_key_factory()

        payload = build_handshake_payload(
            keypair.private_key,
            static_key.get_public_key(),
            config=make_config(mode="off"),
            payload_hash=FAKE_HASH,
        )

        assert payload.extensions is None


# ---------------------------------------------------------------------------
# Noise XX handshake, end to end
# ---------------------------------------------------------------------------


def make_pattern(config: TranscriptBindingConfig | None) -> PatternXX:
    keypair = create_new_key_pair()
    return PatternXX(
        local_peer=ID.from_pubkey(keypair.public_key),
        libp2p_privkey=keypair.private_key,
        noise_static_key=noise_static_key_factory(),
        transcript_binding=config,
    )


async def run_handshake(
    nursery: trio.Nursery,
    initiator: PatternXX,
    responder: PatternXX,
    timeout: float = 30.0,
) -> list[BaseException]:
    """
    Run one XX handshake over a real connection pair.

    Each side's exception is collected rather than allowed to propagate, so a
    test can assert on both peers independently instead of unwrapping a
    nursery's exception group.

    Args:
        nursery: The nursery owning the TCP listener.
        initiator: The dialling pattern.
        responder: The listening pattern.

    When only one side rejects the handshake, the other blocks on a read that
    never arrives: this harness has no transport close to deliver an EOF. Pass
    a short ``timeout`` for those cases and assert on what was collected.

    Args (continued):
        timeout: Seconds to wait before giving up and returning what was
            raised so far.

    Returns:
        list: What each side raised, empty when the handshake succeeded.

    """
    errors: list[BaseException] = []

    async with raw_conn_factory(nursery) as conns:
        init_conn, resp_conn = conns

        async def dial() -> None:
            try:
                await initiator.handshake_outbound(init_conn, responder.local_peer)
            except Exception as exc:
                errors.append(exc)

        async def listen() -> None:
            try:
                await responder.handshake_inbound(resp_conn)
            except Exception as exc:
                errors.append(exc)

        with trio.move_on_after(timeout) as scope:
            async with trio.open_nursery() as handshake_nursery:
                handshake_nursery.start_soon(dial)
                handshake_nursery.start_soon(listen)

        if scope.cancelled_caught and not errors:
            raise AssertionError(
                f"handshake neither completed nor failed within {timeout}s"
            )

    return errors


@pytest.mark.trio
@pytest.mark.parametrize("variant", VARIANTS)
async def test_honest_session_completes(nursery: trio.Nursery, variant: str) -> None:
    """Both peers run /noise, both offer only /noise, so nothing is wrong."""
    config = make_config(protocols=(NOISE,), variant=variant)
    errors = await run_handshake(nursery, make_pattern(config), make_pattern(config))

    assert errors == []


@pytest.mark.trio
@pytest.mark.parametrize("variant", VARIANTS)
async def test_simulated_downgrade_is_refused(
    nursery: trio.Nursery, variant: str
) -> None:
    """
    Both peers offer the post-quantum suite first, yet this session is running
    plain /noise, which is what a stripped proposal looks like from the
    inside. Both ends must refuse.
    """
    config = make_config(actual_protocol=NOISE, variant=variant)
    errors = await run_handshake(nursery, make_pattern(config), make_pattern(config))

    assert len(errors) == 2
    assert all(isinstance(exc, SecurityProtocolDowngrade) for exc in errors)


@pytest.mark.trio
@pytest.mark.parametrize("initiator_binds", [True, False], ids=["dialer", "listener"])
async def test_a_peer_that_sends_no_binding_is_accepted(
    nursery: trio.Nursery, initiator_binds: bool
) -> None:
    """
    The extension variant is incrementally deployable: one peer running it
    against an unmodified peer still completes, in enforce mode, because a
    missing field is not evidence of an attack.
    """
    config = make_config(protocols=(HFS, NOISE))
    bound, unbound = make_pattern(config), make_pattern(None)
    initiator, responder = (bound, unbound) if initiator_binds else (unbound, bound)

    assert await run_handshake(nursery, initiator, responder) == []


@pytest.mark.trio
@pytest.mark.parametrize("initiator_binds", [True, False], ids=["dialer", "listener"])
async def test_the_identity_variant_cannot_talk_to_a_peer_without_it(
    nursery: trio.Nursery, initiator_binds: bool
) -> None:
    """
    The identity variant is a flag day, and mode does not soften it.

    The protocol list is inside identity_sig, so an unmodified peer signed a
    different message and verification fails before any mode is consulted.
    Falling back to the unbound form would let an attacker strip the binding,
    so the incompatibility is deliberate. Pinned here because the extension
    variant behaves the opposite way and the difference is easy to lose.
    """
    config = make_config(protocols=(HFS, NOISE), variant="identity")
    bound, unbound = make_pattern(config), make_pattern(None)
    initiator, responder = (bound, unbound) if initiator_binds else (unbound, bound)

    errors = await run_handshake(nursery, initiator, responder, timeout=5)

    assert errors, "an identity-variant peer must not complete against an older peer"


@pytest.mark.trio
async def test_the_identity_variant_fails_against_an_older_peer_even_in_warn_mode(
    nursery: trio.Nursery,
) -> None:
    config = make_config(protocols=(NOISE,), variant="identity", mode="warn")

    errors = await run_handshake(
        nursery, make_pattern(config), make_pattern(None), timeout=5
    )

    assert errors, "warn mode cannot soften a signature verification failure"


@pytest.mark.trio
async def test_peers_configured_with_different_variants_do_not_complete(
    nursery: trio.Nursery,
) -> None:
    extension = make_config(protocols=(NOISE,), variant="extension")
    identity = make_config(protocols=(NOISE,), variant="identity")

    errors = await run_handshake(
        nursery, make_pattern(extension), make_pattern(identity), timeout=5
    )

    assert errors, "a variant mismatch must not silently produce a session"


@pytest.mark.parametrize("variant", VARIANTS)
def test_a_remote_protocol_list_that_is_too_long_is_rejected_not_raised(
    variant: TranscriptBindingVariant,
) -> None:
    """
    The remote peer controls the list length, and the canonical encoding
    refuses more than MAX_PROTOCOLS entries by raising.

    Building the signed data therefore has to fail as a rejected signature.
    Letting the ValueError escape would turn a malformed peer into an
    unclassified exception out of a function documented to return bool, which
    a caller catching NoiseFailure would not handle. The extension variant
    already rejected this input; the identity variant raised instead.
    """
    keypair = create_new_key_pair()
    static_key = noise_static_key_factory()
    too_many = [f"/p/{index}" for index in range(MAX_PROTOCOLS + 1)]

    payload = build_handshake_payload(keypair.private_key, static_key.get_public_key())
    payload.extensions = NoiseExtensions(
        security_protocols=too_many, transcript_sig=b"not a signature"
    )
    config = make_config(protocols=(NOISE,), variant=variant)

    assert not verify_handshake_payload_sig(
        payload,
        static_key.get_public_key(),
        config=config,
        payload_hash=FAKE_HASH,
    )


class TestVariantDeployment:
    """
    The two variants are deployed in different places, because one of the four
    combinations cannot work.

    ``extension`` is wire compatible, so it rides on the existing /noise
    identifier. ``identity`` is not: it widens what identity_sig covers, and
    /noise is an identifier every libp2p implementation already answers to, so
    such a peer would negotiate /noise successfully and then fail signature
    verification against all of them. Refusing at construction turns a
    network-wide partition into a configuration error.
    """

    def _classical(self, **kwargs: object) -> Transport:
        return Transport(
            libp2p_keypair=create_new_key_pair(),
            noise_privkey=noise_static_key_factory(),
            **kwargs,  # type: ignore[arg-type]
        )

    def test_identity_variant_is_refused_on_noise(self) -> None:
        config = make_config(actual_protocol=NOISE, variant="identity")

        with pytest.raises(ValueError, match="not available on"):
            self._classical(transcript_binding=config)

    def test_warn_mode_does_not_soften_the_refusal(self) -> None:
        config = make_config(actual_protocol=NOISE, variant="identity", mode="warn")

        with pytest.raises(ValueError, match="not available on"):
            self._classical(transcript_binding=config)

    def test_extension_variant_is_allowed_on_noise(self) -> None:
        config = make_config(actual_protocol=NOISE, variant="extension")

        assert self._classical(transcript_binding=config).transcript_binding is config

    def test_off_mode_is_allowed_whatever_the_variant(self) -> None:
        config = make_config(actual_protocol=NOISE, variant="identity", mode="off")

        assert self._classical(transcript_binding=config).transcript_binding is config

    @pytest.mark.parametrize("mode", ["enforce", "warn"])
    def test_a_config_naming_another_protocol_is_refused(self, mode: str) -> None:
        # One config shared with the XXhfs transport names HFS as the actual
        # protocol. On /noise that would make a stripped HFS offer compare
        # equal to itself, so the downgrade this transport exists to catch
        # would pass silently.
        config = make_config(actual_protocol=HFS, mode=mode)

        with pytest.raises(ValueError, match="advertises '/noise'"):
            self._classical(transcript_binding=config)
