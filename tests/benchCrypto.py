from Crypto.PublicKey import RSA
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.hashes import SHA256, Hash
from time import time
import multihash

def makeItTime(func, count):
    i = 0
    time1 = time()
    while i < count:
        func()
        i += 1
    return (time() - time1) / count

def genPyCrypto__hashMultihash():
    k = RSA.generate(2048, e=65537)
    algo = multihash.Func.sha2_256
    mh_digest = multihash.digest(k.publickey().exportKey("DER"), algo)

def genPython_Cryptography__hashMultihash():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    algo = multihash.Func.sha2_256
    mh_digest = multihash.digest(priv.public_key().public_bytes(Encoding.DER, PublicFormat.PKCS1), algo)

def genPyCrypto__hashPython_Cryptography():
    k = RSA.generate(2048, e=65537)
    algo = multihash.Func.sha2_256
    mh_digest = multihash.digest(k.publickey().exportKey("DER"), algo)

def genPython_Cryptography__hashPython_Cryptography():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
    h = Hash(SHA256(), default_backend())
    h.update(priv.public_key().public_bytes(Encoding.DER, PublicFormat.PKCS1))
    h.finalize()

print("Py-Crypto - MultiHash :")
print(str(round(makeItTime(genPyCrypto__hashMultihash, 10), 2)) + "s")
print("Python Cryptography - MultiHash :")
print(str(round(makeItTime(genPython_Cryptography__hashMultihash, 10), 2)) + "s")
print("Py-Crypto - Python Cryptography :")
print(str(round(makeItTime(genPyCrypto__hashPython_Cryptography, 10), 2)) + "s")
print("Python Cryptography - Python Cryptography :")
print(str(round(makeItTime(genPython_Cryptography__hashPython_Cryptography, 10), 2)) + "s")
