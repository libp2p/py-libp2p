from importlib.metadata import (
    version,
)
import logging

logger = logging.getLogger("libp2p.utils.version")


def get_agent_version() -> str:
    """
    Return the version of libp2p.

    If the version cannot be determined due to an exception, return "py-libp2p/unknown".

    :return: The version of libp2p.
    :rtype: str
    """
    try:
        return f"py-libp2p/{version('libp2p')}"
    except Exception as e:
        logger.warning("Could not fetch libp2p version: %s", e)
        return "py-libp2p/unknown"
