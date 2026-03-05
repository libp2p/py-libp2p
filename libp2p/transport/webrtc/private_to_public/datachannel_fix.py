"""
Fix for handshake data channel 'open' event timeout.

Problem: aiortc emits 'open' event via asyncio callbacks. When we wait in trio
with trio.Event(), the asyncio loop isn't processing events, so 'open' never fires.

Solution: Create an asyncio.Future on the trio_asyncio loop and wait for it with
aio_as_trio(), which keeps the asyncio loop processing events.
"""

import asyncio
import logging
from typing import Any

import trio
from trio_asyncio import aio_as_trio
from trio_asyncio._loop import current_loop

logger = logging.getLogger("libp2p.transport.webrtc.datachannel_fix")


async def wait_for_datachannel_open(
    channel: Any, role: str, timeout: float = 30.0
) -> bool:
    """
    Wait for RTCDataChannel to open, processing asyncio events.

    Unlike trio.Event(), this keeps asyncio loop active so aiortc can
    fire the 'open' event callback.

    Returns:
        True if channel opened, False on timeout

    """
    # Check if already open
    if channel.readyState == "open":
        logger.debug(f"{role} Channel already open")
        return True

    logger.debug(
        f"{role} Waiting for channel to open "
        f"(current state: {channel.readyState}, timeout: {timeout}s)"
    )

    loop = current_loop.get()
    if loop is None:
        logger.error(f"{role} No asyncio loop in context (must run inside bridge)")
        return False
    open_future = loop.create_future()

    def on_open() -> None:
        """Called by aiortc when channel opens."""
        logger.debug(f"{role} Channel open event fired")
        if not open_future.done():
            open_future.set_result(True)

    def on_error(error: Any) -> None:
        """Called by aiortc on channel error."""
        logger.error(f"{role} Channel error: {error}")
        if not open_future.done():
            open_future.set_exception(Exception(f"Channel error: {error}"))

    def on_close() -> None:
        """Called by aiortc when channel closes."""
        logger.warning(f"{role} Channel closed before opening")
        if not open_future.done():
            open_future.set_exception(Exception("Channel closed before opening"))

    # Register handlers
    channel.on("open", on_open)
    channel.on("error", on_error)
    channel.on("close", on_close)

    try:
        # Check again in case it opened while registering handlers
        if channel.readyState == "open":
            logger.debug(f"{role} Channel opened during handler registration")
            return True

        # Wait with timeout using aio_as_trio so asyncio events are processed
        with trio.move_on_after(timeout) as cancel_scope:
            await aio_as_trio(asyncio.wait_for(open_future, timeout=timeout))

        if cancel_scope.cancelled_caught:
            logger.error(
                f"{role} Channel open timeout after {timeout}s "
                f"(state: {channel.readyState})"
            )
            return False

        # Success
        logger.info(f"{role} Channel opened successfully")
        return True

    except asyncio.TimeoutError:
        logger.error(
            f"{role} asyncio timeout waiting for channel (state: {channel.readyState})"
        )
        return False
    except Exception as e:
        logger.error(f"{role} Error waiting for channel: {e}", exc_info=True)
        return False
