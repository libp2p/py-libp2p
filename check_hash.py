from multiaddr import Multiaddr

m1 = Multiaddr("/ip4/127.0.0.1/tcp/8000")
m2 = Multiaddr("/ip4/127.0.0.1/tcp/8000")

print(f"m1 == m2: {m1 == m2}")
try:
    print(f"hash(m1): {hash(m1)}")
    s = {m1, m2}
    print(f"Set created: {s}")
except TypeError as e:
    print(f"Error: {e}")
