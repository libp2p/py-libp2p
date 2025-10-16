class InvalidRecordType(Exception):
    pass


def split_key(key: str) -> tuple[str, str]:
    """
    Split a record key into its type and the rest. The key must start with
    '/' and contain another '/' to separate the type. Raises `InvalidRecordType`
    if the key is invalid.

    Args:
        key (str): The record key to split.

    Returns:
        tuple[str, str]: The key type and the rest.

    """
    if not key or key[0] != "/":
        raise InvalidRecordType("Invalid record keytype")

    key = key[1:]

    i = key.find("/")
    if i <= 0:
        raise InvalidRecordType("Invalid record keytype")

    return key[:i], key[i + 1 :]
