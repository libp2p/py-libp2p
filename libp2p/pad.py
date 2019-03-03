from libp2p.logger import log_func, getLogger


class A:
    @log_func("A", return_msg="A initialized")
    def __init__(self, arg, kwarg=88):
        self.arg = arg
        self.kwarg = kwarg

    # def __str__(self):
    #     return "A"

    @log_func(name="A")
    def f(self, x, *args, **kwargs):
        """does some math"""

        return x * x + x


a = A(12, kwarg=["at", 88])
a.f(8, 89, "hi", a="bye", b=485, c=True)

p = 88
q = p * 2

logger = getLogger('hi')
logger.info(f"Value of p={p}")
logger.debug2(f"Value of p={p}")

"""
OUTPUT
'''
10:46:39:DEBUG2:A: __init__(<__main__.A object at 0x03CFB110>, 12, kwarg=['at', 88]) called
10:46:39:DEBUG2:A: A initialized
10:46:39:DEBUG2:A: f(<__main__.A object at 0x03CFB110>, 8, 89, hi, a=bye, b=485, c=True) called
10:46:39:DEBUG2:A: f(<__main__.A object at 0x03CFB110>, 8, 89, hi, a=bye, b=485, c=True) returned 72
10:46:39:INFO:hi: Value of p=88
10:46:39:DEBUG2:hi: Value of p=88
'''
"""