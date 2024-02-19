from libp2p.io.abc import (
    Reader,
)
from libp2p.io.exceptions import (
    IncompleteReadError,
)

DEFAULT_RETRY_READ_COUNT = 100


async def read_exactly(
    reader: Reader, n: int, retry_count: int = DEFAULT_RETRY_READ_COUNT
) -> bytes:
    """
    NOTE: relying on exceptions to break out on erroneous conditions, like EOF
    """
    data = await reader.read(n)

    for _ in range(retry_count):
        if len(data) < n:
            remaining = n - len(data)
            data += await reader.read(remaining)
        else:
            return data
    raise IncompleteReadError({"requested_count": n, "received_count": len(data)})
