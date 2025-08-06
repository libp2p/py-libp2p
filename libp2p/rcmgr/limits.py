from enum import Enum, auto

class LimitType(Enum):
    MEMORYLIMIT = auto()
    STREAMLIMIT = auto()
    STREAMTOTALLIMIT = auto()
    CONNECTIONLIMIT = auto()
    CONNECTIONTOTALLIMIT = auto()
    FDLIMIT = auto()

class Limits(LimitType):
    pass