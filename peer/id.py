import base58

class ID:

    def __init__(self, id_str):
        self._id_str = id_str

    def pretty(self):
        return base58.b58encode(self._id_str).decode()

    def __str__(self):
        pid = self.pretty()
        if len(pid) <= 10:
            return "<peer.ID %s>" % pid
        return "<peer.ID %s*%s>" % (pid[:2], pid[len(pid)-6:])

    __repr__ = __str__