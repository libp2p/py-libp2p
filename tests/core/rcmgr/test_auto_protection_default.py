"""
Tests for automatic resource protection defaults in new_host().
"""

import inspect

from libp2p import new_host


def test_new_host_enables_resource_manager_by_default():
    """new_host() should attach a ResourceManager when none is provided."""
    host = new_host()
    network = host.get_network()

    # Swarm exposes a private attribute _resource_manager; verify it's set.
    assert hasattr(network, "_resource_manager")
    assert getattr(network, "_resource_manager") is not None


def test_new_host_signature_kept_backward_compatible():
    """Signature should keep resource_manager optional for callers."""
    sig = inspect.signature(new_host)
    assert "resource_manager" in sig.parameters
    # Ensure it's still optional in signature
    assert sig.parameters["resource_manager"].default is None


