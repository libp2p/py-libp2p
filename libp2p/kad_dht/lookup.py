"""
Iterative Kademlia lookup, independent of the RPC each step sends.

``PeerRouting.find_closest_peers_network`` drives it with FIND_NODE. The
engine owns the candidate set, the per-round random draw (#1544), the ``ALPHA``
query window, the ``BETA`` termination gate, ``MAX_PEER_LOOKUP_ROUNDS`` and the
lookup deadline, so other lookups can reuse them (#1384).
"""

from collections.abc import Awaitable, Callable
import logging
import random

import trio

from libp2p.peer.id import ID

from .common import ALPHA, BETA, BUCKET_SIZE
from .utils import sort_peer_ids_by_distance

logger = logging.getLogger(__name__)

MAX_PEER_LOOKUP_ROUNDS = 20  # Maximum number of rounds in peer lookup
LOOKUP_DEADLINE = 30.0  # Seconds; the spec's recommended upper bound

# Each round's batch is drawn at random so a Sybil at the closest XOR position
# is not guaranteed a first-round slot. SystemRandom: not predictable by peers.
_rng = random.SystemRandom()

QueryFn = Callable[[ID], Awaitable[list[ID]]]


class Lookup:
    """
    One iterative lookup for ``target_key``, starting from ``closest_peers``.

    ``query(peer)`` returns the peers that ``peer`` reports as closer to the
    target. A query that raises is logged and counts as an empty answer.
    """

    def __init__(
        self,
        target_key: bytes,
        closest_peers: list[ID],
        query: QueryFn,
        *,
        local_id: ID,
        count: int = 20,
        rng: random.Random | None = None,
    ) -> None:
        self.target_key = target_key
        self.closest_peers = closest_peers
        self.query = query
        self.local_id = local_id
        self.count = count
        self.rng = rng or _rng
        self.queried_peers: set[ID] = set()
        self.rounds = 0
        self.query_count = 0

    async def _collect(self, peer: ID, new_peers: list[ID]) -> None:
        """Query one peer and add its unseen answers to ``new_peers``."""
        try:
            result = await self.query(peer)
            # Add deduplication to prevent duplicate peers
            for peer_id in result:
                if peer_id not in new_peers:
                    new_peers.append(peer_id)
            logger.debug(
                "Queried peer %s for closest peers, got %d results (%d unique)",
                peer,
                len(result),
                len([p for p in result if p not in new_peers[: -len(result)]]),
            )
        except Exception as e:
            logger.debug(f"Query to peer {peer} failed: {e}")

    async def run(self) -> list[ID]:
        """Run the lookup and return the closest peers found, closest first."""
        closest_peers = self.closest_peers
        queried_peers = self.queried_peers
        local_id = self.local_id
        start_time = trio.current_time()

        # Return early if we have no peers to start with
        if not closest_peers:
            logger.debug("No local peers available for network lookup")
            return []

        # Iterative lookup using a semaphore-based sliding window.
        # Instead of lock-step batches (start ALPHA, wait for ALL, repeat),
        # we keep up to ALPHA queries in flight at all times. When one finishes,
        # the next candidate starts immediately — no idle slots.
        #
        # Each round still picks a bounded set of candidates (up to `count`)
        # so that Kademlia's iterative refinement is preserved: after each
        # round we re-sort and may discover closer peers for the next round.
        sem = trio.Semaphore(ALPHA)
        new_peers: list[ID] = []

        async def _guarded_query(peer: ID) -> None:
            """Run a single peer query while holding one semaphore slot."""
            try:
                await self._collect(peer, new_peers)
            finally:
                sem.release()

        while self.rounds < MAX_PEER_LOOKUP_ROUNDS:
            # Check total timeout (30 seconds max per spec recommendation)
            elapsed = trio.current_time() - start_time
            if elapsed > LOOKUP_DEADLINE:
                logger.debug(
                    f"Lookup timed out after {elapsed:.1f}s, "
                    f"completed {self.rounds} rounds"
                )
                break

            self.rounds += 1
            logger.debug(f"Lookup round {self.rounds}/{MAX_PEER_LOOKUP_ROUNDS}")

            # Admit at most ALPHA peers per round to preserve classic Kademlia
            # iterative refinement: after each small batch we re-sort with any
            # newly discovered peers before admitting the next batch.
            # Exclude self - we can't query ourselves (Kubo does the same)
            candidates = [
                p for p in closest_peers if p not in queried_peers and p != local_id
            ]
            # Draw the batch at random from the candidate window instead of always
            # taking the strictly closest ALPHA. Every candidate is already within
            # the `count` closest peers we know of, so convergence is preserved,
            # but a Sybil peer sitting at the closest XOR position is no longer
            # guaranteed a slot in the *first* round and so cannot shape the
            # lookup path from hop one. It may still be queried later: the BETA
            # gate below deliberately contacts the closest peers before the
            # lookup returns. See issue #1384.
            peers_to_query = self.rng.sample(candidates, min(ALPHA, len(candidates)))
            if not peers_to_query:
                logger.debug("No more unqueried peers available, ending lookup")
                break

            new_peers.clear()

            async with trio.open_nursery() as nursery:
                for peer in peers_to_query:
                    await sem.acquire()
                    queried_peers.add(peer)
                    self.query_count += 1
                    nursery.start_soon(_guarded_query, peer)

            # If we got no new peers, check if there are still unqueried
            # closest peers before terminating
            if not new_peers:
                unqueried_in_topk = [
                    p
                    for p in closest_peers[:BUCKET_SIZE]
                    if p not in queried_peers and p != local_id
                ]
                if unqueried_in_topk:
                    logger.debug(
                        f"No new peers discovered but {len(unqueried_in_topk)} "
                        "unqueried closest peers remain, continuing"
                    )
                    continue
                logger.debug("No new peers discovered and all closest queried")
                break

            # Update our list of closest peers
            all_candidates = list(dict.fromkeys(closest_peers + new_peers))
            old_closest_peers = closest_peers[:]
            closest_peers = sort_peer_ids_by_distance(self.target_key, all_candidates)[
                : self.count
            ]
            self.closest_peers = closest_peers
            logger.debug(f"Updated closest peers count: {len(closest_peers)}")

            # Check if we made any progress (found closer peers)
            if closest_peers == old_closest_peers:
                # Kademlia terminates once the closest known peers have been
                # contacted. Because admission is randomised, a round can fail
                # to improve while the closest peers are still unqueried, so
                # keep going until the BETA closest have been queried. Bounded
                # by MAX_PEER_LOOKUP_ROUNDS and the deadline above.
                unqueried_beta = [
                    p
                    for p in closest_peers[:BETA]
                    if p not in queried_peers and p != local_id
                ]
                if unqueried_beta:
                    logger.debug(
                        f"No improvement but {len(unqueried_beta)} of the BETA "
                        "closest peers are unqueried, continuing"
                    )
                    continue
                logger.debug("No improvement in closest peers, ending lookup")
                break

            # Beta resiliency: ensure at least BETA of the closest peers
            # have been queried before terminating
            queried_in_closest = sum(
                1 for p in closest_peers[:BUCKET_SIZE] if p in queried_peers
            )
            if queried_in_closest < BETA and len(closest_peers) >= BETA:
                # Not enough closest peers queried, continue if we have candidates
                unqueried_closest = [
                    p
                    for p in closest_peers[:BUCKET_SIZE]
                    if p not in queried_peers and p != local_id
                ]
                if unqueried_closest:
                    logger.debug(
                        f"Only {queried_in_closest}/{BETA} closest peers queried, "
                        "continuing lookup"
                    )
                    continue

        logger.info(
            f"Network lookup completed after {self.rounds} rounds "
            f"({self.query_count} queries), found {len(closest_peers)} peers"
        )
        return closest_peers
