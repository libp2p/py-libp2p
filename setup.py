import setuptools

classifiers = [f"Programming Language :: Python :: {version}" for version in ["3.7"]]


extras_require = {
    "test": [
        "factory-boy>=2.12.0,<3.0.0",
        "pytest>=4.6.3,<5.0.0",
        "pytest-asyncio>=0.10.0,<1.0.0",
        "pytest-xdist>=1.30.0",
    ],
    "lint": [
        "mypy>=0.701,<1.0",
        "mypy-protobuf==1.15",
        "black==19.3b0",
        "isort==4.3.21",
        "flake8>=3.7.7,<4.0.0",
        "flake8-bugbear",
    ],
    "dev": [
        "bumpversion>=0.5.3,<1",
        "docformatter",
        "setuptools>=36.2.0",
        "tox>=3.13.2,<4.0.0",
        "twine",
        "wheel",
    ],
}

extras_require["dev"] = (
    extras_require["test"] + extras_require["lint"] + extras_require["dev"]
)


setuptools.setup(
    name="libp2p",
    description="libp2p implementation written in python",
    version="0.1.2",
    maintainer="The Ethereum Foundation",
    maintainer_email="snakecharmers@ethereum.org",
    url="https://github.com/ethereum/py-libp2p",
    license="MIT/APACHE2.0",
    platforms=["unix", "linux", "osx"],
    classifiers=classifiers,
    install_requires=[
        "pycryptodome>=3.8.2,<4.0.0",
        "base58>=1.0.3,<2.0.0",
        "pymultihash>=0.8.2",
        "multiaddr>=0.0.8,<0.1.0",
        "rpcudp>=3.0.0,<4.0.0",
        "lru-dict>=1.1.6",
        "protobuf==3.9.0",
        "coincurve>=10.0.0,<11.0.0",
        "fastecdsa==1.7.4",
        "pynacl==1.3.0",
    ],
    extras_require=extras_require,
    packages=setuptools.find_packages(exclude=["tests", "tests.*"]),
    zip_safe=False,
)
