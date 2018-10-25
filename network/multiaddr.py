class MultiAddr:

    # Validates input string and constructs internal representation.
    def __init__(self, addr):
        # Empty multiaddrs are valid.
        if not addr:
            self.protocol_map = dict()
            return

        if not addr[0] == "/":
            raise MultiAddrValueError("Invalid input multiaddr.")

        addr = addr[1:]
        protocol_map = dict()
        split_addr = addr.split("/")

        if not split_addr or len(split_addr) % 2 != 0:
            raise MultiAddrValueError("Invalid input multiaddr.")

        is_protocol = True
        curr_protocol = ""

        for addr_part in split_addr:
            if is_protocol:
                curr_protocol = addr_part
            else:
                protocol_map[curr_protocol] = addr_part
            is_protocol = not is_protocol

        self.protocol_map = protocol_map

    def get_protocols(self):
        """
        :return: List of protocols contained in this multiaddr.
        """
        return list(self.protocol_map.keys())

    def get_protocol_value(self, protocol):
        """
        Getter for protocol values in this multiaddr.
        :param protocol: the protocol whose value to retrieve
        :return: value of input protocol
        """
        if protocol not in self.protocol_map:
            return None

        return self.protocol_map[protocol]

    def add_protocol(self, protocol, value):
        """
        Setter for protocol values in this multiaddr.
        :param protocol: the protocol whose value to set or add
        :param value: the value for the input protocol
        :return: True if successful
        """
        self.protocol_map[protocol] = value
        return True

    def remove_protocol(self, protocol):
        """
        Remove protocol and its value from this multiaddr.
        :param protocol: the protocol to remove
        :return: True if remove succeeded, False if protocol was not contained in this multiaddr
        """
        del self.protocol_map[protocol]

    def get_multiaddr_string(self):
        """
        :return: the string representation of this multiaddr.
        """
        addr = ""

        for protocol in self.protocol_map:
            addr += "/" + protocol + "/" + self.get_protocol_value(protocol)

        return addr


class MultiAddrValueError(ValueError):
    """Raised when the input string to the Multiaddr constructor was invalid."""
    pass
