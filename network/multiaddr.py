class Multiaddr:

    def __init__(self, addr):
        if not addr[0] == "/":
            raise MultiaddrValueError("Invalid input multiaddr.")

        addr = addr[1:]
        protocol_map = dict()
        split_addr = addr.split("/")

        if not split_addr or len(split_addr) % 2 != 0:
            raise MultiaddrValueError("Invalid input multiaddr.")

        is_protocol = True
        curr_protocol = ""

        for addr_part in split_addr:
            if is_protocol:
                curr_protocol = addr_part
            else:
                protocol_map[curr_protocol] = addr_part
            is_protocol = not is_protocol

        self.protocol_map = protocol_map
        self.addr = addr

    def get_protocols(self):
        return list(self.protocol_map.keys())

    def get_protocol_value(self, protocol):
        if protocol not in self.protocol_map:
            return None

        return self.protocol_map[protocol]


class MultiaddrValueError(ValueError):
    """Raised when the input string to the Multiaddr constructor was invalid."""
    pass
