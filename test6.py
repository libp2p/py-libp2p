import logging

# Root logger is WARNING
root = logging.getLogger()
root.setLevel(logging.WARNING)
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG) # Handler accepts everything
root.addHandler(handler)

# Child logger is INFO
child = logging.getLogger("child")
child.setLevel(logging.INFO)

child.info("TEST INFO")
