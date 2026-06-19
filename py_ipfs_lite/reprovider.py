import logging
import trio
from libp2p.bitswap.cid import format_cid_for_display

logger = logging.getLogger("py_ipfs_lite.reprovider")

class Reprovider:
    def __init__(self, peer):
        self.peer = peer
        self.interval = peer.config.reprovide_interval_seconds
        self._cancel_scope = None

    async def start(self):
        if self.interval < 0:
            logger.info("Reprovider disabled (interval < 0)")
            return
            
        self._cancel_scope = trio.CancelScope()
        with self._cancel_scope:
            while True:
                await self.reprovide()
                await trio.sleep(self.interval)

    async def stop(self):
        if self._cancel_scope:
            self._cancel_scope.cancel()

    async def reprovide(self):
        if not self.peer.routing:
            return
            
        strategy = self.peer.config.reprovider_strategy
        
        if strategy == "all":
            cids = self.peer.blockstore.all_keys()
        elif strategy in ("pinned", "roots"):
            # Since pin_store currently only stores root pins (direct/recursive),
            # both "pinned" and "roots" iterate the pin_store directly.
            # If indirect pin tracking is added later, "pinned" would include them.
            cids = list(self.peer.pin_store.get_pins("all").keys())
        else:
            logger.warning(f"Unknown reprovider strategy: {strategy}")
            return
            
        if not cids:
            return
            
        logger.info(f"Reproviding {len(cids)} blocks to the DHT using strategy '{strategy}'...")
        
        success_count = 0
        for cid_str in cids:
            try:
                # Add a timeout just to be safe
                with trio.fail_after(self.peer.config.default_timeout):
                    await self.peer.routing.provide(cid_str)
                success_count += 1
            except Exception as e:
                logger.debug(f"Failed to reprovide block {cid_str}: {e}")
        
        logger.info(f"Successfully reprovided {success_count}/{len(cids)} blocks.")
