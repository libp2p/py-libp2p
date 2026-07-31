import logging

logging.basicConfig(level=logging.INFO)
from libp2p.network.auto_connector import logger

print("IS INFO ENABLED?", logger.isEnabledFor(logging.INFO))
logger.info("TEST INFO")
logger.warning("TEST WARNING")
logger.error("TEST ERROR")
