"""
Shared transcript-binding setup for the two interop harnesses.

Both harnesses have to offer the *same* protocol list, because the check they
are exercising compares what one peer says it offered against what the other
concluded. If the dialer and the listener disagreed about the list, the check
would fire and look exactly like a detected downgrade, so the lists live here
once rather than in each script.

The other implementations' harnesses have to agree with these lists too. They
are written out here rather than derived, so a reader can compare them across
languages without running anything.
"""

from libp2p.security.noise.pq.transport_pq import (
    IDENTITY_BOUND_PROTOCOL_ID,
    PROTOCOL_ID,
)
from libp2p.security.noise.transcript_binding import (
    TranscriptBindingConfig,
    TranscriptBindingVariant,
)

CLASSICAL = "/noise"

#: A protocol neither side implements, used to force the check to fire. Both
#: peers claim to prefer it, so each concludes the other should have negotiated
#: it, which is the state a stripped proposal leaves behind. This is the
#: negative control: with it, a run that succeeds is a run where the check did
#: not work.
PHANTOM_PREFERRED = "/noise-interop-phantom/1.0.0"

MODES = ("off", "extension", "identity")


def protocol_id_for_mode(mode: str) -> str:
    """
    The protocol identifier a harness runs under in this mode.

    Args:
        mode: One of MODES.

    Returns:
        str: The identifier the handshake is running under.

    """
    if mode == "identity":
        return str(IDENTITY_BOUND_PROTOCOL_ID)
    return str(PROTOCOL_ID)


def binding_for_mode(
    mode: str, simulate_downgrade: bool = False
) -> TranscriptBindingConfig | None:
    """
    Build the configuration for a harness run, or None when the mode is off.

    Args:
        mode: One of MODES. "off" disables the mechanism entirely.
        simulate_downgrade: Prepend a protocol both peers claim to prefer but
            neither is running, so the check must refuse the session. Used as
            a negative control.

    Returns:
        TranscriptBindingConfig | None: The configuration to hand the pattern.

    Raises:
        ValueError: If mode is not one of MODES, or if a downgrade is
            simulated with the binding off, which would test nothing.

    """
    if mode not in MODES:
        raise ValueError(
            f"transcript binding mode must be one of {MODES}, got {mode!r}"
        )
    # The simulated downgrade is the negative control. With the binding off
    # nothing checks it, so the run would pass while exercising nothing.
    if mode == "off" and simulate_downgrade:
        raise ValueError(
            "--simulate-downgrade needs --transcript-binding extension or "
            "identity; with the binding off it tests nothing"
        )
    if mode == "off":
        return None

    actual = protocol_id_for_mode(mode)
    offered = [actual, CLASSICAL]
    if simulate_downgrade:
        offered.insert(0, PHANTOM_PREFERRED)

    variant: TranscriptBindingVariant = (
        "identity" if mode == "identity" else "extension"
    )
    return TranscriptBindingConfig(
        security_protocols=tuple(offered),
        actual_protocol=actual,
        mode="enforce",
        variant=variant,
    )
