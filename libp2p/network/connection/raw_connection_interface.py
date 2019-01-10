from abc import ABC

# pylint: disable=too-few-public-methods


class IRawConnection(ABC):
    """
    A Raw Connection provides a Reader and a Writer
    """
