import ipaddress
import logging

import miniupnpc  # type: ignore[import-untyped]
import trio

logger = logging.getLogger("libp2p.discovery.upnp")


class UpnpManager:
    """
    A simple, self-contained manager for UPnP port mapping that can be used
    alongside a libp2p Host.
    """

    def __init__(self) -> None:
        self._gateway = miniupnpc.UPnP()
        self._lan_addr: str | None = None
        self._external_ip: str | None = None

    def _validate_igd(self) -> bool:
        """
        Validate that the selected device is actually an Internet Gateway Device.

        :return: True if the device is a valid IGD, False otherwise.
        """
        try:
            # Check if we can get basic IGD information
            if not self._gateway.lanaddr:
                logger.debug("IGD validation failed: No LAN address available")
                return False

            # Try to get the external IP - this is a good test of IGD validity
            external_ip = self._gateway.externalipaddress()
            if not external_ip:
                logger.debug("IGD validation failed: No external IP address available")
                return False

            # Additional validation: check if we can get the connection type
            # This is a more advanced IGD feature that non-IGD devices typically
            # don't support
            try:
                connection_type = self._gateway.connectiontype()
                if connection_type:
                    logger.debug(f"IGD connection type: {connection_type}")
            except Exception:
                # Connection type is optional, so we don't fail if it's not available
                logger.debug("IGD connection type not available (this is optional)")

            return True
        except Exception as e:
            logger.debug(f"IGD validation failed: {e}")
            return False

    async def discover(self) -> bool:
        """
        Discover the UPnP IGD on the network.

        :return: True if a gateway is found, False otherwise.
        """
        logger.debug("Discovering UPnP gateway...")
        try:
            try:
                num_devices = await trio.to_thread.run_sync(self._gateway.discover)
            except Exception as e:
                # The miniupnpc library has a documented quirk where `discover()` can
                # raise an exception with the message "Success" on some platforms
                # (particularly Windows) due to inconsistent error handling in the C
                # library. This is a known issue in miniupnpc where successful
                # discovery sometimes raises an exception instead of returning a count.
                # See: https://github.com/miniupnp/miniupnp/issues/
                if str(e) == "Success":  # type: ignore
                    num_devices = 1
                else:
                    logger.exception("UPnP discovery exception")
                    return False

            if num_devices > 0:
                logger.debug(f"Found {num_devices} UPnP device(s), selecting IGD...")
                try:
                    await trio.to_thread.run_sync(self._gateway.selectigd)
                except Exception as e:
                    logger.error(f"Failed to select IGD: {e}")
                    logger.error(
                        "UPnP devices were found, but none are valid Internet "
                        "Gateway Devices. Check your router's UPnP/IGD settings."
                    )
                    return False

                # Validate that the selected device is actually an IGD
                if not await trio.to_thread.run_sync(self._validate_igd):
                    logger.error(
                        "Selected UPnP device is not a valid Internet Gateway Device. "
                        "The device may be a smart home device or other UPnP device "
                        "that doesn't support port mapping."
                    )
                    return False

                self._lan_addr = self._gateway.lanaddr
                self._external_ip = await trio.to_thread.run_sync(
                    self._gateway.externalipaddress
                )
                logger.debug(f"UPnP gateway found: {self._external_ip}")

                if self._external_ip is None:
                    logger.error("Gateway did not return an external IP address")
                    return False

                ip_obj = ipaddress.ip_address(self._external_ip)
                if ip_obj.is_private:
                    logger.warning(
                        "UPnP gateway has a private IP; you may be behind a double NAT."
                    )
                    return False
                return True
            else:
                logger.debug("No UPnP devices found")
                return False
        except Exception:
            logger.exception("UPnP discovery failed")
            return False

    async def add_port_mapping(self, port: int, protocol: str = "TCP") -> bool:
        """
        Request a new port mapping from the gateway.

        :param port: the internal port to map
        :param protocol: the protocol to map (TCP or UDP)
        :return: True on success, False otherwise
        """
        try:
            port = int(port)
            if not 0 < port < 65536:
                logger.error(f"Invalid port number for mapping: {port}")
                return False
        except (ValueError, TypeError):
            logger.error(f"Invalid port value: {port}")
            return False
        if port < 1024:
            logger.warning(
                f"Mapping a well-known (privileged) port ({port}) may fail or "
                "require root."
            )

        if not self._lan_addr:
            logger.error(
                "Cannot add port mapping: discovery has not been run successfully."
            )
            return False

        logger.debug(f"Requesting UPnP mapping for {protocol} port {port}...")
        try:
            await trio.to_thread.run_sync(
                lambda: self._gateway.addportmapping(
                    port, protocol, self._lan_addr, port, "py-libp2p", ""
                )
            )
            logger.info(
                f"Successfully mapped external port {self._external_ip}:{port} "
                f"to internal port {self._lan_addr}:{port}"
            )
            return True
        except Exception:
            logger.exception(f"Failed to map port {port}")
        return False

    async def remove_port_mapping(self, port: int, protocol: str = "TCP") -> bool:
        """
        Remove an existing port mapping.

        :param port: the external port to unmap
        :param protocol: the protocol (TCP or UDP)
        :return: True on success, False otherwise
        """
        try:
            port = int(port)
            if not 0 < port < 65536:
                logger.error(f"Invalid port number for removal: {port}")
                return False
        except (ValueError, TypeError):
            logger.error(f"Invalid port value: {port}")
            return False

        logger.debug(f"Removing UPnP mapping for {protocol} port {port}...")
        try:
            await trio.to_thread.run_sync(
                lambda: self._gateway.deleteportmapping(port, protocol)
            )
            logger.info(f"Successfully removed mapping for port {port}")
            return True
        except Exception:
            logger.exception(f"Failed to remove mapping for port {port}")
        return False

    def get_external_ip(self) -> str | None:
        return self._external_ip
