import binascii

import multiaddr.codec
import multiaddr.protocols
from multiaddr.protocols import Protocol, add_protocol, code_to_varint

# Monkeypatch to support missing protocols in the environment's multiaddr library

# 1. Register TLS protocol if missing
try:
    multiaddr.protocols.protocol_with_name("tls")
except ValueError:
    # Register TLS protocol
    # We'll use a temporary code for testing.
    P_TLS = 777

    # MUST add to _CODES first because Protocol.__init__ validates against it
    if P_TLS not in multiaddr.protocols._CODES:
        multiaddr.protocols._CODES.append(P_TLS)

    vcode = code_to_varint(P_TLS)
    # Protocol(code, size, name, vcode)
    tls_proto = Protocol(P_TLS, 0, "tls", vcode)

    # Use the library's function to register it properly
    add_protocol(tls_proto)

# 2. Monkeypatch address_string_to_bytes to support dns family and tls
original_address_string_to_bytes = multiaddr.codec.address_string_to_bytes

def patched_address_string_to_bytes(proto, addr_string):
    if proto.name in ("dns", "dns4", "dns6", "dnsaddr"):
        # Size is -1 (variable), so we must prefix with length
        data = addr_string.encode("utf-8")
        # code_to_varint returns HEX string of varint
        length_prefix = code_to_varint(len(data))
        # We need to hexlify the data too, as the result must be a hex string
        data_hex = binascii.hexlify(data)
        return length_prefix + data_hex
    if proto.name == "tls":
        # Size is 0, return empty bytes (which is valid empty hex string)
        return b""
    return original_address_string_to_bytes(proto, addr_string)

multiaddr.codec.address_string_to_bytes = patched_address_string_to_bytes

# 3. Monkeypatch address_bytes_to_string to support dns family
original_address_bytes_to_string = multiaddr.codec.address_bytes_to_string

def patched_address_bytes_to_string(proto, buf):
    if proto.name in ("dns", "dns4", "dns6", "dnsaddr"):
        # buf is hex encoded bytes of the value
        try:
            return binascii.unhexlify(buf).decode("utf-8")
        except Exception:
            # Fallback to original if decoding fails (though it likely won't work for dns)
            pass
    return original_address_bytes_to_string(proto, buf)

multiaddr.codec.address_bytes_to_string = patched_address_bytes_to_string
