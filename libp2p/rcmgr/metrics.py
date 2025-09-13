class Metrics:
    def __init__(self):
        self.data = {}

    def record(self, key: str, value: float):
        self.data[key] = value

    def get(self, key: str) -> float:
        return self.data.get(key, 0.0)
