#!/usr/bin/env python
import sys

from setuptools import (
    find_packages,
    setup,
)

description = "libp2p: The Python implementation of the libp2p networking stack"

# Platform-specific dependencies
if sys.platform == "win32":
    crypto_requires = []  # We'll use coincurve instead of fastecdsa on Windows
else:
    crypto_requires = ["fastecdsa==1.7.5"]

extras_require = {
    "dev": [
        "build>=0.9.0",
        "bump_my_version>=0.19.0",
        "ipython",
        "mypy==1.10.0",
        "pre-commit>=3.4.0",
        "tox>=4.0.0",
        "twine",
        "wheel",
    ],
    "docs": [
        "sphinx>=6.0.0",
        "sphinx_rtd_theme>=1.0.0",
        "towncrier>=24,<25",
    ],
    "test": [
        "p2pclient==0.2.0",
        "pytest>=7.0.0",
        "pytest-xdist>=2.4.0",
        "pytest-trio>=0.5.2",
        "factory-boy>=2.12.0,<3.0.0",
    ],
}

extras_require["dev"] = (
    extras_require["dev"] + extras_require["docs"] + extras_require["test"]
)

try:
    with open("./README.md", encoding="utf-8") as readme:
        long_description = readme.read()
except FileNotFoundError:
    long_description = description

install_requires = [
    "base58>=1.0.3",
    "coincurve>=10.0.0",
    "exceptiongroup>=1.2.0; python_version < '3.11'",
    "grpcio>=1.41.0",
    "lru-dict>=1.1.6",
    "multiaddr>=0.0.9",
    "mypy-protobuf>=3.0.0",
    "noiseprotocol>=0.3.0",
    "protobuf>=6.30.1",
    "pycryptodome>=3.9.2",
    "pymultihash>=0.8.2",
    "pynacl>=1.3.0",
    "rpcudp>=3.0.0",
    "trio-typing>=0.0.4",
    "trio>=0.26.0",
]

# Add platform-specific dependencies
install_requires.extend(crypto_requires)

setup(
    name="libp2p",
    # *IMPORTANT*: Don't manually change the version here. See Contributing docs for the release process.
    version="0.2.7",
    description=description,
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="The Ethereum Foundation",
    author_email="snakecharmers@ethereum.org",
    url="https://github.com/libp2p/py-libp2p",
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.9, <4",
    extras_require=extras_require,
    py_modules=["libp2p"],
    license="MIT AND Apache-2.0",
    license_files=("LICENSE-MIT", "LICENSE-APACHE"),
    zip_safe=False,
    keywords="libp2p p2p",
    packages=find_packages(exclude=["scripts", "scripts.*", "tests", "tests.*"]),
    package_data={"libp2p": ["py.typed"]},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
    platforms=["unix", "linux", "osx", "win32"],
    entry_points={
        "console_scripts": [
            "chat-demo=examples.chat.chat:main",
            "echo-demo=examples.echo.echo:main",
            "ping-demo=examples.ping.ping:main",
            "identify-demo=examples.identify.identify:main",
            "identify-push-demo=examples.identify_push.identify_push_demo:run_main",
            "identify-push-listener-dialer-demo=examples.identify_push.identify_push_listener_dialer:main",
            "pubsub-demo=examples.pubsub.pubsub:main",
        ],
    },
)
