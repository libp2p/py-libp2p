import ipaddress
import logging

import miniupnpc  # type: ignore[import-error]
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
                if str(e) == "Success":
                    num_devices = 1
                else:
                    logger.exception("UPnP discovery exception")
                    return False

            if num_devices > 0:
                await trio.to_thread.run_sync(self._gateway.selectigd)
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
