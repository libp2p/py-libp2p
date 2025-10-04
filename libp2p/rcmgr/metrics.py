class Metrics:
    def __init__(self) -> None:
        self.data: dict[str, float] = {}

    def record(self, key: str, value: float) -> None:
        self.data[key] = value

    def get(self, key: str) -> float:
        return self.data.get(key, 0.0)
