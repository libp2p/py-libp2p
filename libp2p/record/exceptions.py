
class ErrEmptyDomain(Exception):
    pass

class ErrEmptyPayloadType(Exception):
    pass

class ErrInvalidSignature(Exception):
    pass

class ErrInvalidRecordType(Exception):
    """Raised if a DHTRecord key's prefix is not found in the Validator map."""
    pass


class ErrBetterRecord(Exception):
    """Raised when a better record is found by a subsystem."""
    def __init__(self, key: str, value: bytes):
        self.key = key
        self.value = value
        super().__init__(f'found better value for "{key}"')
