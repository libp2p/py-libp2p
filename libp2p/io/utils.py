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

    # If we get 0 bytes on first read and requested > 0, it's likely a closed stream
    if len(data) == 0 and n > 0:
        raise IncompleteReadError(
            {"requested_count": n, "received_count": 0, "received_data": data}
        )

    for _ in range(retry_count):
        if len(data) < n:
            remaining = n - len(data)
            chunk = await reader.read(remaining)
            # If we get no more data, the stream is closed
            if len(chunk) == 0:
                raise IncompleteReadError(
                    {
                        "requested_count": n,
                        "received_count": len(data),
                        "received_data": data,
                    }
                )
            data += chunk
        else:
            return data
    raise IncompleteReadError(
        {"requested_count": n, "received_count": len(data), "received_data": data}
    )
