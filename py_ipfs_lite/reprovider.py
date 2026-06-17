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
            
        cids = self.peer.blockstore.get_all_cids()
        if not cids:
            return
            
        logger.info(f"Reproviding {len(cids)} blocks to the DHT...")
        
        success_count = 0
        for cid_bytes in cids:
            try:
                cid_str = format_cid_for_display(cid_bytes)
                await self.peer.routing.provide(cid_str)
                success_count += 1
            except Exception as e:
                logger.debug(f"Failed to reprovide block {cid_str}: {e}")
                
        logger.info(f"Finished reproviding {success_count}/{len(cids)} blocks.")
