from unittest.mock import MagicMock, patch

import pytest

from libp2p.discovery.upnp import UpnpManager

pytestmark = pytest.mark.trio


@pytest.fixture
def mock_upnp_gateway():
    """A pytest fixture to mock the miniupnpc.UPnP object."""
    with patch("libp2p.discovery.upnp.miniupnpc.UPnP") as mock_upnp_class:
        mock_gateway = MagicMock()
        mock_upnp_class.return_value = mock_gateway
        yield mock_gateway


async def test_upnp_discover_success(mock_upnp_gateway):
    """
    Test successful discovery of a UPnP gateway.
    """
    mock_upnp_gateway.discover.return_value = 1
    mock_upnp_gateway.selectigd.return_value = None
    mock_upnp_gateway.lanaddr = "192.168.1.100"
    mock_upnp_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    result = await manager.discover()

    assert result is True
    assert manager.get_external_ip() == "123.45.67.89"
    assert manager._lan_addr == "192.168.1.100"
    mock_upnp_gateway.discover.assert_called_once()
    mock_upnp_gateway.selectigd.assert_called_once()
    mock_upnp_gateway.externalipaddress.assert_called_once()


async def test_upnp_discover_with_success_exception(mock_upnp_gateway):
    """
    Test the workaround for the miniupnpc bug where it raises Exception("Success").
    """
    mock_upnp_gateway.discover.side_effect = Exception("Success")
    mock_upnp_gateway.selectigd.return_value = None
    mock_upnp_gateway.lanaddr = "192.168.1.100"
    mock_upnp_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    result = await manager.discover()

    assert result is True
    assert manager.get_external_ip() == "123.45.67.89"


async def test_upnp_discover_no_devices_found(mock_upnp_gateway):
    """
    Test UPnP discovery when no devices are found.
    """
    mock_upnp_gateway.discover.return_value = 0
    manager = UpnpManager()
    result = await manager.discover()

    assert result is False
    assert manager.get_external_ip() is None


@patch("libp2p.discovery.upnp.logger")
async def test_upnp_discover_double_nat(mock_logger, mock_upnp_gateway):
    """
    Test UPnP discovery when the external IP is private (double NAT).
    """
    mock_upnp_gateway.discover.return_value = 1
    mock_upnp_gateway.selectigd.return_value = None
    mock_upnp_gateway.lanaddr = "192.168.1.100"
    mock_upnp_gateway.externalipaddress.return_value = "10.0.0.1"

    manager = UpnpManager()
    result = await manager.discover()

    assert result is False
    assert manager.get_external_ip() == "10.0.0.1"
    mock_logger.warning.assert_called_once_with(
        "UPnP gateway has a private IP; you may be behind a double NAT."
    )


async def test_add_port_mapping_success(mock_upnp_gateway):
    """
    Test successfully adding a port mapping after discovery.
    """
    mock_upnp_gateway.discover.return_value = 1
    mock_upnp_gateway.selectigd.return_value = None
    mock_upnp_gateway.lanaddr = "192.168.1.100"
    mock_upnp_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    await manager.discover()

    mock_upnp_gateway.addportmapping.return_value = None
    result = await manager.add_port_mapping(port=8080, protocol="TCP")

    assert result is True
    mock_upnp_gateway.addportmapping.assert_called_once_with(
        8080, "TCP", "192.168.1.100", 8080, "py-libp2p", ""
    )


@patch("libp2p.discovery.upnp.logger")
async def test_add_port_mapping_failure_no_discover(mock_logger, mock_upnp_gateway):
    """
    Test that adding a port mapping fails if discover() hasn't been run.
    """
    manager = UpnpManager()
    result = await manager.add_port_mapping(port=8080, protocol="TCP")

    assert result is False
    mock_upnp_gateway.addportmapping.assert_not_called()
    mock_logger.error.assert_called_once_with(
        "Cannot add port mapping: discovery has not been run successfully."
    )


@patch("libp2p.discovery.upnp.logger")
async def test_add_port_mapping_exception(mock_logger, mock_upnp_gateway):
    """
    Test adding a port mapping when the gateway raises an exception.
    """
    mock_upnp_gateway.discover.return_value = 1
    mock_upnp_gateway.lanaddr = "192.168.1.100"
    mock_upnp_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    await manager.discover()

    mock_upnp_gateway.addportmapping.side_effect = Exception("Gateway rejected mapping")
    result = await manager.add_port_mapping(port=8080, protocol="TCP")

    assert result is False
    mock_logger.exception.assert_called_once_with("Failed to map port 8080")


async def test_remove_port_mapping_success(mock_upnp_gateway):
    """
    Test successfully removing a port mapping.
    """
    manager = UpnpManager()
    manager._lan_addr = "192.168.1.100"
    manager._external_ip = "123.45.67.89"

    mock_upnp_gateway.deleteportmapping.return_value = None
    result = await manager.remove_port_mapping(port=8080, protocol="TCP")

    assert result is True
    mock_upnp_gateway.deleteportmapping.assert_called_once_with(8080, "TCP")
