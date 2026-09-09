import trio


async def simulate_peer_behavior(
    peer_id: str, messages: int, delay: float = 0.01
) -> list[str]:
    events = []
    for i in range(messages):
        events.append(f"{peer_id}_msg_{i}")
        await trio.sleep(delay)
    return events
