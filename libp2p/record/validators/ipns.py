from typing import List, Tuple, Optional
from libp2p.record.validator import Validator
from libp2p.record.record import Record
from libp2p.record.exceptions import ErrInvalidRecordType

class IPNSValidator(Validator):
    """
    Validates IPNS records (signature, sequence number, TTL)
    """

    def validate(self, rec: Record) -> None:
        raise NotImplementedError

    def select(self, key: str, values: List[Record]) -> int:
        raise NotImplementedError
