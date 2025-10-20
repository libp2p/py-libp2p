from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.trio


@pytest.fixture
def mock_upnp_gateway():
    """A pytest fixture to mock the miniupnpc.UPnP object."""
    # Mock the entire miniupnpc module since it might be None
    mock_miniupnpc = MagicMock()
    mock_gateway = MagicMock()
    mock_miniupnpc.UPnP.return_value = mock_gateway

    with patch("libp2p.discovery.upnp.upnp.miniupnpc", mock_miniupnpc):
        # Import UpnpManager after mocking miniupnpc
        from libp2p.discovery.upnp.upnp import UpnpManager

        yield mock_gateway, UpnpManager


async def test_upnp_discover_success(mock_upnp_gateway):
    """
    Test successful discovery of a UPnP gateway.
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.return_value = 1
    mock_gateway.selectigd.return_value = None
    mock_gateway.lanaddr = "192.168.1.100"
    mock_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    result = await manager.discover()

    assert result is True
    assert manager.get_external_ip() == "123.45.67.89"
    assert manager._lan_addr == "192.168.1.100"
    mock_gateway.discover.assert_called_once()
    mock_gateway.selectigd.assert_called_once()
    # externalipaddress is called twice: once in _validate_igd and once in discover
    assert mock_gateway.externalipaddress.call_count == 2


async def test_upnp_discover_with_success_exception(mock_upnp_gateway):
    """
    Test the workaround for the miniupnpc bug where it raises Exception("Success").
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.side_effect = Exception("Success")
    mock_gateway.selectigd.return_value = None
    mock_gateway.lanaddr = "192.168.1.100"
    mock_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    result = await manager.discover()

    assert result is True
    assert manager.get_external_ip() == "123.45.67.89"


async def test_upnp_discover_no_devices_found(mock_upnp_gateway):
    """
    Test UPnP discovery when no devices are found.
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.return_value = 0
    manager = UpnpManager()
    result = await manager.discover()

    assert result is False
    assert manager.get_external_ip() is None


@patch("libp2p.discovery.upnp.upnp.logger")
async def test_upnp_discover_double_nat(mock_logger, mock_upnp_gateway):
    """
    Test UPnP discovery when the external IP is private (double NAT).
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.return_value = 1
    mock_gateway.selectigd.return_value = None
    mock_gateway.lanaddr = "192.168.1.100"
    mock_gateway.externalipaddress.return_value = "10.0.0.1"

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
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.return_value = 1
    mock_gateway.selectigd.return_value = None
    mock_gateway.lanaddr = "192.168.1.100"
    mock_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    await manager.discover()

    mock_gateway.addportmapping.return_value = None
    result = await manager.add_port_mapping(port=8080, protocol="TCP")

    assert result is True
    mock_gateway.addportmapping.assert_called_once_with(
        8080, "TCP", "192.168.1.100", 8080, "py-libp2p", ""
    )


@patch("libp2p.discovery.upnp.upnp.logger")
async def test_add_port_mapping_failure_no_discover(mock_logger, mock_upnp_gateway):
    """
    Test that adding a port mapping fails if discover() hasn't been run.
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    manager = UpnpManager()
    result = await manager.add_port_mapping(port=8080, protocol="TCP")

    assert result is False
    mock_gateway.addportmapping.assert_not_called()
    mock_logger.error.assert_called_once_with(
        "Cannot add port mapping: discovery has not been run successfully."
    )


@patch("libp2p.discovery.upnp.upnp.logger")
async def test_add_port_mapping_exception(mock_logger, mock_upnp_gateway):
    """
    Test adding a port mapping when the gateway raises an exception.
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.return_value = 1
    mock_gateway.lanaddr = "192.168.1.100"
    mock_gateway.externalipaddress.return_value = "123.45.67.89"

    manager = UpnpManager()
    await manager.discover()

    mock_gateway.addportmapping.side_effect = Exception("Gateway rejected mapping")
    result = await manager.add_port_mapping(port=8080, protocol="TCP")

    assert result is False
    mock_logger.exception.assert_called_once_with("Failed to map port 8080")


async def test_remove_port_mapping_success(mock_upnp_gateway):
    """
    Test successfully removing a port mapping.
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    manager = UpnpManager()
    manager._lan_addr = "192.168.1.100"
    manager._external_ip = "123.45.67.89"

    mock_gateway.deleteportmapping.return_value = None
    result = await manager.remove_port_mapping(port=8080, protocol="TCP")

    assert result is True
    mock_gateway.deleteportmapping.assert_called_once_with(8080, "TCP")


@patch("libp2p.discovery.upnp.upnp.logger")
async def test_upnp_discover_invalid_igd(mock_logger, mock_upnp_gateway):
    """
    Test UPnP discovery when a non-IGD device is selected.
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.return_value = 1
    mock_gateway.selectigd.return_value = None
    mock_gateway.lanaddr = None  # Simulate invalid IGD
    mock_gateway.externalipaddress.return_value = None

    manager = UpnpManager()
    result = await manager.discover()

    assert result is False
    mock_logger.error.assert_called_with(
        "Selected UPnP device is not a valid Internet Gateway Device. "
        "The device may be a smart home device or other UPnP device "
        "that doesn't support port mapping."
    )


@patch("libp2p.discovery.upnp.upnp.logger")
async def test_upnp_discover_selectigd_failure(mock_logger, mock_upnp_gateway):
    """
    Test UPnP discovery when selectigd fails with a descriptive error.
    """
    mock_gateway, UpnpManager = mock_upnp_gateway
    mock_gateway.discover.return_value = 1
    mock_gateway.selectigd.side_effect = Exception("No UPnP device discovered")

    manager = UpnpManager()
    result = await manager.discover()

    assert result is False
    mock_logger.error.assert_any_call("Failed to select IGD: No UPnP device discovered")
    mock_logger.error.assert_any_call(
        "UPnP devices were found, but none are valid Internet Gateway Devices. "
        "Check your router's UPnP/IGD settings."
    )
