import logging

from libp2p.records.utils import InvalidRecordType, split_key

logger = logging.getLogger("records-validator")


class ErrBetterRecord(Exception):
    def __init__(self, key: str, value: bytes):
        self.key = key
        self.value = value
        super().__init__(f'Found better value for "{key}')


class Validator:
    """Base class for all validators"""

    def validate(self, key: str, value: bytes) -> None:
        raise NotImplementedError

    def select(self, key: str, values: list[bytes]) -> int:
        raise NotImplementedError


class NamespacedValidator:
    """
    Manages a collection of validators, each associated with a specific namespace.
    """

    def __init__(self, validators: dict[str, Validator]):
        self._validators = validators

    def validator_by_key(self, key: str) -> Validator | None:
        """
        Retrieve the validator responsible for the given key's namespace.

        Args:
            key (str): A namespaced key in the form "namespace/value".

        Returns:
            Optional[Validator]: The matching validator, or None if not found.

        """
        try:
            ns, _ = split_key(key)
        except InvalidRecordType:
            return None
        return self._validators.get(ns)

    def validate(self, key: str, value: bytes) -> None:
        """
        Validate a key-value pair using the appropriate namespaced validator.

        Args:
            key (str): The namespaced key (e.g., "pk/Qm...").
            value (bytes): The value to be validated.

        Raises:
            InvalidRecordType: If no matching validator is found.
            Exception: Propagates any exception raised by the sub-validator.

        """
        validator = self.validator_by_key(key)
        if validator is None:
            raise InvalidRecordType("Invalid record keytype")
        return validator.validate(key, value)

    def select(self, key: str, values: list[bytes]) -> int:
        """
        Choose the best value from a list using the namespaced validator.

        Args:
            key (str): The namespaced key used to find the validator.
            values (List[bytes]): List of candidate values to choose from.

        Returns:
            int: Index of the selected best value in the input list.

        Raises:
            ValueError: If the values list is empty.
            InvalidRecordType: If no matching validator is found.

        """
        if not values:
            raise ValueError("Can't select from empty value list")
        validator = self.validator_by_key(key)
        if validator is None:
            raise InvalidRecordType("Invalid record keytype")
        return validator.select(key, values)
