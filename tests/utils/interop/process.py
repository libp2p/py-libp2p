from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Iterable,
)
import subprocess

import trio

TIMEOUT_DURATION = 30


class AbstractInterativeProcess(ABC):
    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


class BaseInteractiveProcess(AbstractInterativeProcess):
    proc: trio.Process | None = None
    cmd: str
    args: list[str]
    bytes_read: bytearray
    patterns: Iterable[bytes] | None = None
    event_ready: trio.Event

    async def wait_until_ready(self) -> None:
        if self.proc is None:
            raise Exception("process is not defined")
        if self.patterns is None:
            raise Exception("patterns is not defined")
        patterns_occurred = {pat: False for pat in self.patterns}
        buffers = {pat: bytearray() for pat in self.patterns}

        async def read_from_daemon_and_check() -> None:
            if self.proc is None:
                raise Exception("process is not defined")
            if self.proc.stdout is None:
                raise Exception("process stdout is None, cannot read output")

            async for data in self.proc.stdout:
                self.bytes_read.extend(data)
                for pat, occurred in patterns_occurred.items():
                    if occurred:
                        continue

                    # Check if pattern is in new data or spans across chunks
                    buf = buffers[pat]
                    buf.extend(data)
                    if pat in buf:
                        patterns_occurred[pat] = True
                    else:
                        keep = min(len(pat) - 1, len(buf))
                        buffers[pat] = buf[-keep:] if keep > 0 else bytearray()

                if all(patterns_occurred.values()):
                    return

        with trio.fail_after(TIMEOUT_DURATION):
            await read_from_daemon_and_check()
        self.event_ready.set()
        # Sleep a little bit to ensure the listener is up after logs are emitted.
        await trio.sleep(0.01)

    async def start(self) -> None:
        if self.proc is not None:
            return
        # mypy says that `open_process` is not an attribute of trio, suggests run_process instead.  # noqa: E501
        self.proc = await trio.open_process(  # type: ignore[attr-defined]
            [self.cmd] + self.args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Redirect stderr to stdout, which makes parsing easier  # noqa: E501
            bufsize=0,
        )
        await self.wait_until_ready()

    async def close(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        await self.proc.wait()
