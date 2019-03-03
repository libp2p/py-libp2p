from libp2p.logger.logger import log_func


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


"""
Output:
'''
08:38:57:DEBUG2:A: __init__(<__main__.A object at 0x03E89490>, 12, kwarg=['at', 88]) called
08:38:57:DEBUG2:A: A initialized
08:38:57:DEBUG2:A: f(<__main__.A object at 0x03E89490>, 8, 89, hi, a=bye, b=485, c=True) called
08:38:57:DEBUG2:A: f(<__main__.A object at 0x03E89490>, 8, 89, hi, a=bye, b=485, c=True) returned 72
'''
"""
