class MessageCache:

    class CacheEntry:

        def __init__(self, mid, topics):
            self.mid = mid
            self.topics = topics

    def __init(self, window_size, history_size):
        self.window_size = window_size
        self.history_size = history_size

        # (from_id, seqno) -> rpc message
        self.msgs = dict()

        # max length of history_size. each item is a list of CacheEntry.
        # messages lost upon shift().
        self.history = []

    def put(self, msg):
        mid = (msg.from_id, msg.seqno)
        self.msgs[mid] = msg

        if not self.history or not self.history[0]:
            self.history[0] = []

        self.history[0].append(self.CacheEntry(mid, msg.topicIDs))

    def get(self, mid):
        if mid in self.msgs:
            return self.msgs[mid]

        return None

    def window(self, topic):
        mids = []

        for entries_list in self.history[: self.window_size]:
            for entry in entries_list:
                for entry_topic in entry.topics:
                    if entry_topic == topic:
                        mids.append(entry.mid)

        return mids

    def shift(self):
        last_entries = self.history[len(self.history) - 1]

        for entry in last_entries:
            del self.msgs[entry.mid]

        i = len(self.history) - 2

        while i >= 0:
            self.history[i + 1] = self.history[i]

        self.history[0] = None
