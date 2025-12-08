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
    Read exactly n bytes from the reader.

    This function attempts to read exactly n bytes from the reader, retrying
    up to retry_count times if partial data is received. If the connection
    closes before n bytes are received, raises IncompleteReadError with
    enhanced error messages that include transport context (if available).

    The error message includes:

    - The expected and actual number of bytes received
    - Transport type and connection duration (if reader provides conn_state())
    - Context about possible causes (peer closure, network issues,
      transport-specific problems)

    Args:
        reader: The reader to read from
        n: Number of bytes to read
        retry_count: Maximum number of retries if partial data is received

    Returns:
        bytes: Exactly n bytes of data

    Raises:
        IncompleteReadError: If the connection closes before n bytes are received.
            The error message includes transport context if available via
            reader.conn_state().

    .. note::
        Relies on exceptions to break out on erroneous conditions, like EOF.

    """
    buffer = bytearray()
    buffer.extend(await reader.read(n))

    for _ in range(retry_count):
        if len(buffer) < n:
            remaining = n - len(buffer)
            buffer.extend(await reader.read(remaining))

        else:
            return bytes(buffer)

    # Get transport context if available
    context_info = ""
    try:
        if hasattr(reader, "conn_state"):
            conn_state_method = getattr(reader, "conn_state")
            if callable(conn_state_method):
                state = conn_state_method()
                if isinstance(state, dict):
                    transport = state.get("transport", "unknown")
                    duration = state.get("connection_duration", 0)
                    context_info = (
                        f" (transport: {transport}, duration: {duration:.2f}s)"
                    )
    except Exception:
        # Gracefully handle if conn_state() is not available or fails
        pass

    raise IncompleteReadError(
        f"Connection closed during read operation: expected {n} bytes but "
        f"received {len(buffer)} bytes{context_info}"
    )
