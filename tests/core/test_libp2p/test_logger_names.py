import logging
from libp2p.network import swarm
from libp2p.pubsub import gossipsub


def test_logger_names():
    """Test that logger names use __name__ correctly."""
    assert swarm.logger.name == "libp2p.network.swarm"
    assert gossipsub.logger.name == "libp2p.pubsub.gossipsub"


def test_loggers_exist_and_callable():
    """Test that loggers exist and can be called without errors."""
    # Test that loggers are Logger instances
    assert isinstance(swarm.logger, logging.Logger)
    assert isinstance(gossipsub.logger, logging.Logger)
    
    assert hasattr(swarm.logger, 'debug')
    assert hasattr(swarm.logger, 'info')
    assert hasattr(swarm.logger, 'warning')
    assert hasattr(swarm.logger, 'error')
    
    assert callable(swarm.logger.debug)
    assert callable(swarm.logger.info)
    
  
    try:
        swarm.logger.info("Test info message")
        gossipsub.logger.info("Test gossipsub message")
        assert True
    except Exception as e:
        assert False, f"Logger calls failed with exception: {e}"


def manual_logger_verification():
    """Run this manually to verify loggers work with LIBP2P_DEBUG."""
    print("=== Manual Logger Verification ===")
    print(f"Swarm logger name: {swarm.logger.name}")
    print(f"GossipSub logger name: {gossipsub.logger.name}")
    
    print("\nTesting different log levels:")
    swarm.logger.debug("This is a debug message from swarm")
    swarm.logger.info("This is an info message from swarm")
    gossipsub.logger.debug("This is a debug message from gossipsub")
    gossipsub.logger.info("This is an info message from gossipsub")
    
    print("\nTo test LIBP2P_DEBUG functionality, run:")
    print("LIBP2P_DEBUG=network:DEBUG python -c 'from tests.core.test_libp2p.test_logger_names import manual_logger_verification; manual_logger_verification()'")


if __name__ == "__main__":
    manual_logger_verification()