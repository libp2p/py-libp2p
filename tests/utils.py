import asyncio

from contextlib import suppress


async def cleanup():
    pending = asyncio.all_tasks()
    for task in pending:
        task.cancel()

        # Now we should await task to execute it's cancellation.
        # Cancelled task raises asyncio.CancelledError that we can suppress:
        with suppress(asyncio.CancelledError):
            await task
