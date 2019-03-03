import logging
from typing import Any, cast
from functools import wraps
from libp2p.logger.setup import DEBUG2_LEVEL_NUM, ExtendedDebugLogger, setup_extended_logging

setup_extended_logging()


def get_str_args(*args, **kwargs):
    string = ""
    for arg in args:
        string += (str(arg) + ", ")
    for key, value in kwargs.items():
        string += (str(key) + "=" + str(value) + ", ")
    return string[:-2]  # to remove trailing ", "


def log_func(name: str = 'debug2', log_call: bool = True, call_msg: str = "__DEFAULT__", log_return: bool = True,
             return_msg: str = "__DEFAULT__"):
    def _log_func(func):
        @wraps(func)
        def with_logging(*args, **kwargs):
            logging.basicConfig(level=DEBUG2_LEVEL_NUM,
                                format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
                                datefmt="%H:%M:%S")
            logger = cast(ExtendedDebugLogger, logging.getLogger(name))
            args_str = get_str_args(*args, **kwargs)
            if log_call:
                if call_msg == "__DEFAULT__":  # print default
                    logger.debug2(f"{func.__name__}({args_str}) called")
                else:
                    logger.debug2(call_msg)
            ans = func(*args, **kwargs)
            if log_return:
                if return_msg == "__DEFAULT__":  # print default
                    logger.debug2(f"{func.__name__}({args_str}) returned {ans}")
                else:
                    logger.debug2(return_msg)
            return ans

        return with_logging

    return _log_func
