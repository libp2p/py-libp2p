from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from libp2p.record.record import Record

from .exceptions import (
    ErrInvalidRecordType,
)
from .utils import split_key


class Validator(ABC):
    """Interface that should be implemented by record validators."""

    @abstractmethod
    def validate(self, rec: Record) -> None:
        """
        Validate the given record, raising an exception if it's invalid
        (e.g., expired, signed by the wrong key, etc.).
        """
        pass

    @abstractmethod
    def select(self, key: str, values: List[Record]) -> Record | None:
        """
        Select the best record from the set of records (e.g., the newest).
        Returns (index, error).
        """
        pass

class NamespacedValidator(Validator):
    """
    A validator that delegates to sub-validators by namespace.
    Essentially a mapping from namespace -> Validator.
    """

    def __init__(self, validators: Dict[str, Validator]):
        self.validators = validators

    def validator_by_key(self, key: str) -> Optional[Validator]:
        try:
            ns, _ = split_key(key)
        except Exception:
            return None
        return self.validators.get(ns)

    def validate(self, rec: Record) -> None:
        vi = self.validator_by_key(rec.key_str)
        if vi is None:
            raise ErrInvalidRecordType()
        return vi.validate(rec)

    def select(self, key: str, values: List[Record]) -> Record | None:
        if not values:
            raise ValueError("can't select from no values")
        vi = self.validator_by_key(key)
        if vi is None:
            raise ErrInvalidRecordType()
        return vi.select(key, values)

