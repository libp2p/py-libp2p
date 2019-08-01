import time
from itertools import takewhile
import operator
from collections import OrderedDict
from abc import abstractmethod, ABC
from typing import TYPE_CHECKING, TypeVar, Iterator, Tuple

if TYPE_CHECKING:
    from typing import Any

TKey = TypeVar("TKey")
TValue = TypeVar("TValue")


class IStorage(ABC):
    """
    Local storage for this node.
    IStorage implementations of get must return the same type as put in by set
    """

    @abstractmethod
    def __setitem__(self, key: TKey, value: TValue) -> None:
        """
        Set a key to the given value.
        """

    @abstractmethod
    def __getitem__(self, key: TKey) -> TValue:
        """
        Get the given key.  If item doesn't exist, raises C{KeyError}
        """

    @abstractmethod
    def get(self, key: TKey, default: TValue = None) -> TValue:
        """
        Get given key.  If not found, return default.
        """

    @abstractmethod
    def iter_older_than(self, seconds_old: int) -> Iterator[Tuple[TKey, TValue]]:
        """
        Return the an iterator over (key, value) tuples for items older
        than the given seconds_old.
        """

    @abstractmethod
    def __iter__(self) -> Iterator[Tuple[TKey, TValue]]:
        """
        Get the iterator for this storage, should yield tuple of (key, value)
        """


class ForgetfulStorage(IStorage):
    data: "OrderedDict[Any, Any]"
    ttl: int

    def __init__(self, ttl: int = 604800) -> None:
        """
        By default, max age is a week.
        """
        self.data = OrderedDict()
        self.ttl = ttl

    def __setitem__(self, key: TKey, value: TValue) -> None:
        if key in self.data:
            del self.data[key]
        self.data[key] = (time.monotonic(), value)
        self.cull()

    def cull(self) -> None:
        for _, _ in self.iter_older_than(self.ttl):
            self.data.popitem(last=False)

    def get(self, key: TKey, default: TValue = None) -> TValue:
        self.cull()
        if key in self.data:
            return self[key]
        return default

    def __getitem__(self, key: TKey) -> TValue:
        self.cull()
        return self.data[key][1]

    def __repr__(self) -> str:
        self.cull()
        return repr(self.data)

    def iter_older_than(self, seconds_old: int) -> Iterator[Tuple[TKey, TValue]]:
        min_birthday = time.monotonic() - seconds_old
        zipped: Iterator[Tuple[TKey, int, TValue]] = self._triple_iter()
        matches = takewhile(lambda r: min_birthday >= r[1], zipped)
        for key, birthday, value in matches:
            yield key, value

    def _triple_iter(self) -> Iterator[Tuple[TKey, int, TValue]]:
        ikeys = self.data.keys()
        ibirthday = map(operator.itemgetter(0), self.data.values())
        ivalues = map(operator.itemgetter(1), self.data.values())
        return zip(ikeys, ibirthday, ivalues)

    def __iter__(self) -> Iterator[Tuple[TKey, TValue]]:
        self.cull()
        ikeys = self.data.keys()
        ivalues = map(operator.itemgetter(1), self.data.values())
        return zip(ikeys, ivalues)
