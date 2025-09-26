from datetime import date


class Libp2pRecord:
    def __init__(self, key: bytes, value: bytes, time_received: date) -> None:
        self.key = key 
        self.value = value 
        self.time_received = date
    
    def serialize(self) -> bytes:
        return self.key 
        