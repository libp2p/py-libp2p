from libp2p.records.validator import Validator

class ServiceValidator(Validator):
    def validate(self, key: str, value: bytes) -> None:
        if not value:
            raise ValueError("Value cannot be empty")

    def select(self, key: str, values: list[bytes]) -> int:
        return 0
