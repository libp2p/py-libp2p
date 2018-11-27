class MultiAddr:

    # Validates input string and constructs internal representation.
    def __init__(self, addr):
        self.protocol_map = dict()

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

        # Basic validation of protocols
        # TODO(rzajac): Add more validation as necessary.
        if 'ip4' in self.protocol_map and 'ip6' in self.protocol_map:
            raise MultiAddrValueError("Multiaddr should not specify two IP layers.")

        if 'tcp' in self.protocol_map and 'udp' in self.protocol_map:
            raise MultiAddrValueError("Multiaddr should not specify two transport layers.")

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

    def to_options(self):
        """
        Gives back a dictionary with access to transport information from this multiaddr.
        Example: MultiAddr('/ip4/127.0.0.1/tcp/4001').to_options()
        = { family: 'ipv4', host: '127.0.0.1', transport: 'tcp', port: '4001' }
        :return: {{family: String, host: String, transport: String, port: String}}
        with None if field does not exist
        """
        options = dict()

        if 'ip4' in self.protocol_map:
            options['family'] = 'ipv4'
            options['host'] = self.protocol_map['ip4']
        elif 'ip6' in self.protocol_map:
            options['family'] = 'ipv6'
            options['host'] = self.protocol_map['ip6']
        else:
            options['family'] = None
            options['host'] = None

        if 'tcp' in self.protocol_map:
            options['transport'] = 'tcp'
            options['port'] = self.protocol_map['tcp']
        elif 'udp' in self.protocol_map:
            options['transport'] = 'udp'
            options['port'] = self.protocol_map['udp']
        else:
            options['transport'] = None
            options['port'] = None

        return options


class MultiAddrValueError(ValueError):
    """Raised when the input string to the MultiAddr constructor was invalid."""
