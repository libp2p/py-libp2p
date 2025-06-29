import random
import string


def stringGen(len: int = 63) -> str:
    """Generate a random string of lowercase letters and digits."""
    charset = string.ascii_lowercase + string.digits
    result = []
    for _ in range(len):
        result.append(random.choice(charset))
    return "".join(result)
