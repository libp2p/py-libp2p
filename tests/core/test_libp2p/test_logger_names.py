import logging
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_logger_names():
    """Ensure modules use logging.getLogger(__name__) for logger."""
    files = [
        "libp2p/network/swarm.py",
        "libp2p/host/basic_host.py",
        "libp2p/transport/tcp/tcp.py",
        "libp2p/pubsub/floodsub.py",
        "libp2p/pubsub/gossipsub.py",
        "libp2p/pubsub/pubsub.py",
        "libp2p/pubsub/validators.py",
    ]
    for f in files:
        src = _read(f)
        assert "logger = logging.getLogger(__name__)" in src, f"{f} missing __name__ logger"
        assert "logging.getLogger(\"libp2p" not in src, f"{f} contains hardcoded logger name"


def test_loggers_exist_and_callable():
    """Create loggers by name and ensure methods are callable (sanity)."""
    names = [
        "libp2p.network.swarm",
        "libp2p.host.basic_host",
        "libp2p.transport.tcp.tcp",
        "libp2p.pubsub.floodsub",
        "libp2p.pubsub.gossipsub",
        "libp2p.pubsub.pubsub",
        "libp2p.pubsub.validators",
    ]
    for name in names:
        lg = logging.getLogger(name)
        assert isinstance(lg, logging.Logger)
        assert callable(lg.debug)
        assert callable(lg.info)