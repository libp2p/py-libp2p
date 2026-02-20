import logging

from libp2p.records.utils import InvalidRecordType, split_key

logger = logging.getLogger(__name__)


class ErrBetterRecord(Exception):
    def __init__(self, key: str, value: bytes):
        self.key = key
        self.value = value
        super().__init__(f'Found better value for "{key}')


class ValidationError(Exception):
    """Raised when record validation fails."""

    pass


class Validator:
    """Base class for all validators"""

    def validate(self, key: str, value: bytes) -> None:
        raise NotImplementedError

    def select(self, key: str, values: list[bytes]) -> int:
        raise NotImplementedError


class BlankValidator(Validator):
    """
    A permissive validator that accepts all records.

    This is used as a default/fallback validator when no specific
    validator is registered for a namespace and strict validation
    is not enabled.
    """

    def validate(self, key: str, value: bytes) -> None:
        """Accept all records without validation."""
        pass

    def select(self, key: str, values: list[bytes]) -> int:
        """Select the first value (all values are treated equally)."""
        return 0


class NamespacedValidator:
    """
    Manages a collection of validators, each associated with a specific namespace.

    Following the go-libp2p pattern, this validator can operate in two modes:

    - strict_validation=False (default): Non-namespaced keys are accepted without
      validation using a fallback BlankValidator
    - strict_validation=True: All keys must match a registered namespace validator,
      otherwise validation fails with InvalidRecordType

    This aligns with go-libp2p/rust-libp2p behavior where:

    - Records are always validated through the validator system
    - Networks can enforce strict namespace requirements for security
    """

    def __init__(
        self,
        validators: dict[str, Validator],
        strict_validation: bool = False,
        fallback_validator: Validator | None = None,
    ):
        """
        Initialize a NamespacedValidator.

        Args:
            validators: A dictionary mapping namespace strings to Validator instances.
            strict_validation: If True, reject keys without registered namespace
                validators. If False, use the fallback_validator for non-namespaced
                keys. Default is False for backward compatibility.
            fallback_validator: Validator to use for non-namespaced keys when
                strict_validation is False. Defaults to BlankValidator.

        """
        self._validators = validators
        self._strict_validation = strict_validation
        self._fallback_validator = fallback_validator or BlankValidator()

    @property
    def strict_validation(self) -> bool:
        """Return whether strict validation mode is enabled."""
        return self._strict_validation

    @strict_validation.setter
    def strict_validation(self, value: bool) -> None:
        """Set strict validation mode."""
        self._strict_validation = value

    def validator_by_key(self, key: str) -> Validator | None:
        """
        Retrieve the validator responsible for the given key's namespace.

        Args:
            key (str): A namespaced key in the form "/namespace/value".

        Returns:
            Validator: The matching validator, the fallback validator if
                strict_validation is False and key is non-namespaced, or None
                if strict_validation is True and no validator matches.

        """
        try:
            ns, _ = split_key(key)
            return self._validators.get(ns)
        except InvalidRecordType:
            # Key is not namespaced (doesn't start with / or has no second /)
            if self._strict_validation:
                return None
            return self._fallback_validator

    def validate(self, key: str, value: bytes) -> None:
        """
        Validate a key-value pair using the appropriate namespaced validator.

        This method follows the go-libp2p pattern where keys with registered
        namespace validators are validated by that validator. Non-namespaced
        keys are handled based on strict_validation setting: if True, raises
        InvalidRecordType (go-libp2p behavior); if False, uses fallback
        validator (permissive mode).

        Args:
            key (str): The key (e.g., "/pk/Qm..." or "my-plain-key").
            value (bytes): The value to be validated.

        Raises:
            InvalidRecordType: If strict_validation is True and no validator found.
            ValidationError: If the validator rejects the record.

        """
        validator = self.validator_by_key(key)
        if validator is None:
            if self._strict_validation:
                raise InvalidRecordType(
                    f"No validator registered for key '{key}' and strict validation "
                    "is enabled. Keys must use registered namespaces (e.g., /pk/, "
                    "/ipns/) or strict_validation must be disabled."
                )
            # This should not happen as validator_by_key returns fallback
            # when strict_validation is False, but guard anyway
            logger.warning(
                f"No validator found for key '{key}', using implicit acceptance"
            )
            return
        return validator.validate(key, value)

    def select(self, key: str, values: list[bytes]) -> int:
        """
        Choose the best value from a list using the namespaced validator.

        Args:
            key (str): The key used to find the validator.
            values (List[bytes]): List of candidate values to choose from.

        Returns:
            int: Index of the selected best value in the input list.

        Raises:
            ValueError: If the values list is empty.
            InvalidRecordType: If strict_validation is True and no validator found.

        """
        if not values:
            raise ValueError("Can't select from empty value list")
        validator = self.validator_by_key(key)
        if validator is None:
            if self._strict_validation:
                raise InvalidRecordType(
                    f"No validator registered for key '{key}' and strict validation "
                    "is enabled."
                )
            return 0
        return validator.select(key, values)

    def add_validator(self, namespace: str, validator: Validator) -> None:
        """
        Add or update a validator for a specific namespace.

        Args:
            namespace (str): The namespace string (e.g., "pk", "myapp").
            validator (Validator): A Validator instance to handle validation
            for this namespace.

        """
        self._validators[namespace] = validator
