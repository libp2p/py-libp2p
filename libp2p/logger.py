import logging
from typing import Any, cast
from functools import wraps

DEBUG2_LEVEL_NUM = 8


class ExtendedDebugLogger(logging.Logger):

    def debug2(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.log(DEBUG2_LEVEL_NUM, message, *args, **kwargs)


def setup_extended_logging() -> None:
    logging.setLoggerClass(ExtendedDebugLogger)
    logging.addLevelName(DEBUG2_LEVEL_NUM, 'DEBUG2')
    logging.basicConfig(level=DEBUG2_LEVEL_NUM,
                        format="%(asctime)s:%(levelname)s:%(name)s: %(message)s",
                        datefmt="%H:%M:%S")


setattr(logging, 'DEBUG2', DEBUG2_LEVEL_NUM)  # typing: ignore

setup_extended_logging()


def _get_str_args(*args, **kwargs):
    string = ""
    for arg in args:
        string += (str(arg) + ", ")
    for key, value in kwargs.items():
        string += (str(key) + "=" + str(value) + ", ")
    return string[:-2]  # to remove trailing ", "


def log_func(name: str = 'debug2', log_call: bool = True, call_msg: str = "__DEFAULT__", log_return: bool = True,
             return_msg: str = "__DEFAULT__", *log_args: Any, **log_kwargs: Any):
    def _log_func(func):
        @wraps(func)
        def with_logging(*args, **kwargs):
            logger = cast(ExtendedDebugLogger, logging.getLogger(name))
            args_str = _get_str_args(*args, **kwargs)
            if log_call:
                if call_msg == "__DEFAULT__":  # print default
                    logger.debug2(f"{func.__name__}({args_str}) called", *log_args, **log_kwargs)
                else:
                    logger.debug2(call_msg, *log_args, **log_kwargs)
            ans = func(*args, **kwargs)
            if log_return:
                if return_msg == "__DEFAULT__":  # print default
                    logger.debug2(f"{func.__name__}({args_str}) returned {ans}", *log_args, **log_kwargs)
                else:
                    logger.debug2(return_msg, *log_args, **log_kwargs)
            return ans

        return with_logging

    return _log_func


def getLogger(name):
    return cast(ExtendedDebugLogger, logging.getLogger(name))
