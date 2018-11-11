def encode_uvarint(number):
    """Pack `number` into varint bytes"""
    buf = b''
    while True:
        towrite = number & 0x7f
        number >>= 7
        if number:
            buf += bytes((towrite | 0x80, ))
        else:
            buf += bytes((towrite, ))
            break
    return buf

def decode_uvarint(buff, index):
    shift = 0
    result = 0
    while True:
        i = buff[index]
        result |= (i & 0x7f) << shift
        shift += 7
        if not i & 0x80:
            break
        index += 1

    return result, index
