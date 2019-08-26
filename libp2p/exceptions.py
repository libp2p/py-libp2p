class BaseLibp2pError(Exception):
    pass


class ValidationError(BaseLibp2pError):
    """
    Raised when something does not pass a validation check.
    """


class ParseError(BaseLibp2pError):
    pass
