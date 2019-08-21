from libp2p.exceptions import BaseLibp2pError


class MultiselectError(BaseLibp2pError):
    """Raised when an error occurs in multiselect process"""


class MultiselectClientError(BaseLibp2pError):
    """Raised when an error occurs in protocol selection process"""
