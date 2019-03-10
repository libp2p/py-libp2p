class MessageTalk():
    """
    Object to make parsing talk messages easier, where talk messages are
    defined as custom messages published to a set of topics
    """

    def __init__(self, from_id, origin_id, topics, data):
        self.msg_type = "talk"
        self.from_id = from_id
        self.origin_id = origin_id
        self.topics = topics
        self.data = data

    def to_str(self):
        """
        Convert to string
        :return: MessageTalk object in string representation
        """
        out = self.msg_type + '\n'
        out += self.from_id + '\n'
        out += self.origin_id + '\n'
        for i in range(len(self.topics)):
            out += self.topics[i]
            if i < len(self.topics) - 1:
                out += ','
        out += '\n' + self.data
        return out

class MessageSub():
    """
    Object to make parsing subscription messages easier, where subscription
    messages are defined as indicating the topics a node wishes to subscribe to
    or unsubscribe from
    """

    def __init__(self, from_id, origin_id, subs_map):
        self.msg_type = "subscription"
        self.from_id = from_id
        self.origin_id = origin_id
        self.subs_map = subs_map

    """
    Convert to string
    :return: MessageSub object in string representation
    """
    def to_str(self):
        out = self.msg_type + '\n'
        out += self.from_id + '\n'
        out += self.origin_id

        if self.subs_map:
            out += '\n'

        keys = list(self.subs_map)
        for i in range(len(keys)):
            topic = keys[i]
            sub = self.subs_map[keys[i]]
            if sub:
                out += "sub:"
            else:
                out += "unsub:"
            out += topic
            if i < len(keys) - 1:
                out += '\n'

        return out

def create_message_talk(msg_talk_as_str):
    """
    Create a MessageTalk object from a MessageTalk string representation
    :param msg_talk_as_str: a MessageTalk object in its string representation
    :return: MessageTalk object
    """
    msg_comps = msg_talk_as_str.split('\n')
    from_id = msg_comps[1]
    origin_id = msg_comps[2]
    topics = msg_comps[3].split(',')
    data = msg_comps[4]
    return MessageTalk(from_id, origin_id, topics, data)

def create_message_sub(msg_sub_as_str):
    """
    Create a MessageSub object from a MessageSub string representation
    :param msg_talk_as_str: a MessageSub object in its string representation
    :return: MessageSub object
    """
    msg_comps = msg_sub_as_str.split('\n')
    from_id = msg_comps[1]
    origin_id = msg_comps[2]
    subs_map = {}
    for i in range(3, len(msg_comps)):
        sub_comps = msg_comps[i].split(":")
        topic = sub_comps[1]
        if sub_comps[0] == "sub":
            subs_map[topic] = True
        else:
            subs_map[topic] = False
    return MessageSub(from_id, origin_id, subs_map)
