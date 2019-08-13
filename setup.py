import setuptools

classifiers = [f"Programming Language :: Python :: {version}" for version in ["3.7"]]


extras_require = {
    "test": [
        "codecov>=2.0.15,<3.0.0",
        "factory-boy>=2.12.0,<3.0.0",
        "pytest>=4.6.3,<5.0.0",
        "pytest-cov>=2.7.1,<3.0.0",
        "pytest-asyncio>=0.10.0,<1.0.0",
    ],
    "lint": [
        "mypy>=0.701,<1.0",
        "black==19.3b0",
        "isort==4.3.21",
        "flake8>=3.7.7,<4.0.0",
    ],
    "dev": ["tox>=3.13.2,<4.0.0"],
}

extras_require["dev"] = (
    extras_require["test"] + extras_require["lint"] + extras_require["dev"]
)


setuptools.setup(
    name="libp2p",
    description="libp2p implementation written in python",
    version="0.0.1",
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
    ],
    extras_require=extras_require,
    packages=setuptools.find_packages(exclude=["tests", "tests.*"]),
    zip_safe=False,
)
