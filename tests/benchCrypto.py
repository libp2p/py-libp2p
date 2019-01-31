#!/usr/bin/env python3.6
# pylint: skip-file

from Crypto.PublicKey import RSA
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.hashes import SHA256, Hash
from time import time
import multihash

SAMPLES = 10

def formatDuration(t):
    return str(round(t, 2)) + "s"

def makeItTime(func, count):
    i = 0
    time1 = time()
    while i < count:
        func()
        i += 1
    return (time() - time1) / count

def makeItTimeFormated(func, count):
    return formatDuration(makeItTime(func, count))

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

print("Running some test with " + str(SAMPLES) + " samples per algo.")
print("I will print result in a markdown compatible table.")

print("test 0/4")
CM = makeItTimeFormated(genPyCrypto__hashMultihash, SAMPLES)
print("test 1/4")
CgM = makeItTimeFormated(genPython_Cryptography__hashMultihash, SAMPLES)
print("test 2/4")
CCg = makeItTimeFormated(genPyCrypto__hashPython_Cryptography, SAMPLES)
print("test 3/4")
CgCg = makeItTimeFormated(genPython_Cryptography__hashPython_Cryptography, SAMPLES)
print("test 4/4\n")
print(
    "|                     | Crypto | Python Cryptography |\n" +
    "| :-----------------: | ------ | ------------------- |\n" +
    "| MultiHash           | " + CM + " " * (7 - len(CM)) + "| " + CgM + " " * (20 - len(CgM)) + "|\n" +
    "| Python Cryptography | " + CCg + " " * (7 - len(CCg)) + "| " + CgCg + " " * (20 - len(CgCg)) +"|"
)
