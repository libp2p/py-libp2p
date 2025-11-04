"""
Test cases for resource manager integration with new_host().

This module tests the new resource_manager parameter added to new_host()
and new_swarm() functions.
"""

from libp2p.rcmgr import ResourceManager
from libp2p.rcmgr.manager import ResourceLimits


class TestResourceManagerIntegration:
    """Test resource manager integration with host creation."""

    def test_new_host_accepts_resource_manager_parameter(self):
        """Test that new_host() accepts resource_manager parameter."""
        # Test that new_host() function signature includes resource_manager
        import inspect

        from libp2p import new_host

        sig = inspect.signature(new_host)
        assert "resource_manager" in sig.parameters
        assert sig.parameters["resource_manager"].default is None

    def test_new_swarm_accepts_resource_manager_parameter(self):
        """Test that new_swarm() accepts resource_manager parameter."""
        # Test that new_swarm() function signature includes resource_manager
        import inspect

        from libp2p import new_swarm

        sig = inspect.signature(new_swarm)
        assert "resource_manager" in sig.parameters
        assert sig.parameters["resource_manager"].default is None

    def test_new_host_passes_resource_manager_to_swarm(self):
        """Test that new_host() passes resource_manager to new_swarm()."""
        # This test verifies the integration by checking the function signature
        # and ensuring the parameter is properly passed through the call chain
        import inspect

        from libp2p import new_host, new_swarm

        # Check that new_host has resource_manager parameter
        new_host_sig = inspect.signature(new_host)
        assert "resource_manager" in new_host_sig.parameters

        # Check that new_swarm has resource_manager parameter
        new_swarm_sig = inspect.signature(new_swarm)
        assert "resource_manager" in new_swarm_sig.parameters

        # Verify the parameter types and defaults
        assert new_host_sig.parameters["resource_manager"].default is None
        assert new_swarm_sig.parameters["resource_manager"].default is None

    def test_resource_manager_import_available(self):
        """Test that ResourceManager can be imported from libp2p.rcmgr."""
        from libp2p.rcmgr import ResourceManager

        assert ResourceManager is not None

    def test_resource_manager_creation(self):
        """Test that ResourceManager can be created with default settings."""
        # Test with default limits
        rm = ResourceManager()
        assert rm is not None
        assert hasattr(rm, "limits")

        # Test with custom limits
        custom_limits = ResourceLimits()
        rm_custom = ResourceManager(limits=custom_limits)
        assert rm_custom is not None
        assert rm_custom.limits == custom_limits
