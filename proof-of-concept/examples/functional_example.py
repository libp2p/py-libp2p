"""
Example of a function-based service using the anyio-based implementation.
"""
import anyio

from ..base import as_service
from ..manager import AnyIOManager, background_service
from ..abc import InternalManagerAPI

@as_service
async def example_functional_service(manager: InternalManagerAPI, param: str) -> None:
    manager.run_daemon_task(background_worker, param)
    
    for i in range(5):
        if manager.is_cancelled:
            break
        await anyio.sleep(1)
        print(f"Functional service running: {i}, param: {param}")

async def background_worker(param: str) -> None:
    while True:
        await anyio.sleep(0.5)
        print(f"Worker processing {param}")

async def main():
    print("Running functional service:")
    service_fn = example_functional_service("test-param")
    await AnyIOManager.run_service(service_fn)
    print("Functional service finished")

if __name__ == "__main__":
    anyio.run(main)