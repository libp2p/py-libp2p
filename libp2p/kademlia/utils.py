"""
General catchall for functions that don't make sense as methods.
"""
import asyncio
import hashlib
import operator
from typing import Awaitable, Dict, List, Sequence, TypeVar, Union

ItemT = TypeVar("ItemT")

KT = TypeVar("KT")
VT = TypeVar("VT")


async def gather_dict(dic: Dict[KT, Awaitable[VT]]) -> Dict[KT, VT]:
    cors = list(dic.values())
    results = await asyncio.gather(*cors)
    return dict(zip(dic.keys(), results))


def digest(string: Union[str, bytes, int]) -> bytes:
    if not isinstance(string, bytes):
        string = str(string).encode("utf8")
    return hashlib.sha1(string).digest()


class OrderedSet(List[ItemT]):
    """
    Acts like a list in all ways, except in the behavior of the
    :meth:`push` method.
    """

    def push(self, thing: ItemT) -> None:
        """
        1. If the item exists in the list, it's removed
        2. The item is pushed to the end of the list
        """
        if thing in self:
            self.remove(thing)
        self.append(thing)


def shared_prefix(args: Sequence[str]) -> str:
    """
    Find the shared prefix between the strings.

    For instance:

        sharedPrefix(['blahblah', 'blahwhat'])

    returns 'blah'.
    """
    i = 0
    while i < min(map(len, args)):
        if len(set(map(operator.itemgetter(i), args))) != 1:
            break
        i += 1
    return args[0][:i]


def bytes_to_bit_string(bites: bytes) -> str:
    bits = [bin(bite)[2:].rjust(8, "0") for bite in bites]
    return "".join(bits)
