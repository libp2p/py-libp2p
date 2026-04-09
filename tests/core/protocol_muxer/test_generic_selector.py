from unittest.mock import (
    AsyncMock,
    MagicMock,
)

import pytest

from libp2p.custom_types import (
    TProtocol,
)
from libp2p.protocol_muxer.exceptions import (
    MultiselectError,
)
from libp2p.protocol_muxer.generic_selector import (
    GenericMultistreamSelector,
)


def test_add_handler_stores_protocol():
    """Test that add_handler stores the protocol and handler correctly."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")
    assert TProtocol("/proto/1.0.0") in selector.handlers
    assert selector.handlers[TProtocol("/proto/1.0.0")] == "handler_a"


def test_add_handler_updates_precedence():
    """Test that re-adding a protocol moves it to the end (updates precedence)."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")
    selector.add_handler(TProtocol("/proto/2.0.0"), "handler_b")
    assert list(selector.handlers.keys()) == [
        TProtocol("/proto/1.0.0"),
        TProtocol("/proto/2.0.0"),
    ]
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a_updated")
    assert list(selector.handlers.keys()) == [
        TProtocol("/proto/2.0.0"),
        TProtocol("/proto/1.0.0"),
    ]
    assert selector.handlers[TProtocol("/proto/1.0.0")] == "handler_a_updated"


def test_get_protocols_returns_ordered_list():
    """Test that get_protocols returns protocols in insertion order."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")
    selector.add_handler(TProtocol("/proto/2.0.0"), "handler_b")
    selector.add_handler(TProtocol("/proto/3.0.0"), "handler_c")
    assert selector.get_protocols() == [
        TProtocol("/proto/1.0.0"),
        TProtocol("/proto/2.0.0"),
        TProtocol("/proto/3.0.0"),
    ]


@pytest.mark.trio
async def test_select_initiator_uses_multiselect_client():
    """Test that select() uses multiselect_client when is_initiator=True."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")

    mock_conn = MagicMock()
    selector.multiselect_client.select_one_of = AsyncMock(
        return_value=TProtocol("/proto/1.0.0")
    )

    protocol, handler = await selector.select(mock_conn, is_initiator=True)

    selector.multiselect_client.select_one_of.assert_called_once()
    assert protocol == TProtocol("/proto/1.0.0")
    assert handler == "handler_a"


@pytest.mark.trio
async def test_select_listener_uses_multiselect_negotiate():
    """Test that select() uses multiselect.negotiate when is_initiator=False."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")

    mock_conn = MagicMock()
    selector.multiselect.negotiate = AsyncMock(
        return_value=(TProtocol("/proto/1.0.0"), None)
    )

    protocol, handler = await selector.select(mock_conn, is_initiator=False)

    selector.multiselect.negotiate.assert_called_once()
    assert protocol == TProtocol("/proto/1.0.0")
    assert handler == "handler_a"


@pytest.mark.trio
async def test_select_raises_on_no_protocol():
    """Test that select() raises MultiselectError when no protocol is selected."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")

    mock_conn = MagicMock()
    selector.multiselect.negotiate = AsyncMock(return_value=(None, None))

    with pytest.raises(MultiselectError):
        await selector.select(mock_conn, is_initiator=False)


@pytest.mark.trio
async def test_select_respects_timeout_initiator():
    """Test that the negotiate_timeout is passed to multiselect_client."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")

    mock_conn = MagicMock()
    selector.multiselect_client.select_one_of = AsyncMock(
        return_value=TProtocol("/proto/1.0.0")
    )

    await selector.select(mock_conn, is_initiator=True, negotiate_timeout=42)

    args, _ = selector.multiselect_client.select_one_of.call_args
    assert args[2] == 42


@pytest.mark.trio
async def test_select_respects_timeout_listener():
    """Test that the negotiate_timeout is passed to multiselect.negotiate."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    selector.add_handler(TProtocol("/proto/1.0.0"), "handler_a")

    mock_conn = MagicMock()
    selector.multiselect.negotiate = AsyncMock(
        return_value=(TProtocol("/proto/1.0.0"), None)
    )

    await selector.select(mock_conn, is_initiator=False, negotiate_timeout=99)

    args, _ = selector.multiselect.negotiate.call_args
    assert args[1] == 99


def test_selector_exposes_multiselect_and_client():
    """Test that multiselect and multiselect_client are accessible on the selector."""
    selector: GenericMultistreamSelector[str] = GenericMultistreamSelector()
    assert selector.multiselect is not None
    assert selector.multiselect_client is not None
