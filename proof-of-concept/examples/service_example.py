"""
Example of a class-based service using the anyio-based implementation.
"""

import anyio

from ..base import (
    Service,
)
from ..manager import (
    run_service,
)


class ExampleService(Service):
    async def run(self) -> None:
        self.manager.run_daemon_task(self.background_task, "Task 1")
        self.manager.run_daemon_task(self.background_task, "Task 2")

        # Run for a while
        for i in range(10):
            if self.manager.is_cancelled:
                break
            await anyio.sleep(1)
            print(f"Main service running: {i}")

    async def background_task(self, name: str) -> None:
        while True:
            await anyio.sleep(0.5)
            print(f"Background task {name} running")


async def main():
    print("Running class-based service:")
    async with run_service(ExampleService()) as manager:
        await anyio.sleep(3)
        print(f"Service stats: {manager.stats}")
    print("Class-based service finished")


if __name__ == "__main__":
    anyio.run(main)
