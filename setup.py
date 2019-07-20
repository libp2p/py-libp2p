import setuptools


classifiers = [
    f"Programming Language :: Python :: {version}"
    for version in ["3.7"]
]


setuptools.setup(
    name="libp2p",
    description="libp2p implementation written in python",
    version="0.0.1",
    license="MIT/APACHE2.0",
    platforms=["unix", "linux", "osx"],
    classifiers=classifiers,
    install_requires=[
        "pycryptodome>=3.8.2,<4.0.0",
        "click>=7.0,<8.0",
        "base58>=1.0.3,<2.0.0",
        "pymultihash>=0.8.2",
        "multiaddr>=0.0.8,<0.1.0",
        "rpcudp>=3.0.0,<4.0.0",
        "grpcio>=1.21.1,<2.0.0",
        "grpcio-tools>=1.21.1,<2.0.0",
        "lru-dict>=1.1.6",
        "aio_timers>=0.0.1,<0.1.0",
    ],
    packages=setuptools.find_packages(exclude=["tests", "tests.*"]),
    zip_safe=False,
)
