#!/usr/bin/env python
import os

from setuptools import (
    find_packages,
    setup,
)

extras_require = {
    "dev": [
        "build>=0.9.0",
        "bump-my-version>=0.5.3",
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
        "towncrier>=21,<22",
    ],
    "test": [
        "pytest>=7.0.0",
        "pytest-xdist>=2.4.0",
        "pytest-trio>=0.5.2",
        "factory-boy>=2.12.0,<3.0.0",
    ],
}

extras_require["dev"] = (
    extras_require["dev"] + extras_require["docs"] + extras_require["test"]
)

fastecdsa = [
    # No official fastecdsa==1.7.4,1.7.5 wheels for Windows, using a pypi package that includes
    # the original library, but also windows-built wheels (32+64-bit) on those versions.
    # Fixme: Remove section when fastecdsa has released a windows-compatible wheel
    #  (specifically: both win32 and win_amd64 targets)
    #  See the following issues for more information;
    #  https://github.com/libp2p/py-libp2p/issues/363
    #  https://github.com/AntonKueltz/fastecdsa/issues/11
    "fastecdsa-any==1.7.5;sys_platform=='win32'",
    # Wheels are provided for these platforms, or compiling one is minimally frustrating in a
    # default python installation.
    "fastecdsa==1.7.5;sys_platform!='win32'",
]

with open("./README.md") as readme:
    long_description = readme.read()


install_requires = [
    "base58>=1.0.3",
    "coincurve>=10.0.0",
    "exceptiongroup>=1.2.0; python_version < '3.11'",
    "lru-dict>=1.1.6",
    "multiaddr>=0.0.9",
    "mypy-protobuf>=3.0.0",
    "noiseprotocol>=0.3.0",
    "protobuf>=5.27.0",
    "pycryptodome>=3.9.2",
    "pymultihash>=0.8.2",
    "pynacl>=1.3.0",
    "rpcudp>=3.0.0",
    "trio-typing>=0.0.4",
    "aioquic>=0.9.20",
    "trio>=0.26.0",
]


# NOTE: Some dependencies break RTD builds. We can not install system dependencies on the
# RTD system so we have to exclude these dependencies when we are in an RTD environment.
readthedocs_is_building = os.environ.get("READTHEDOCS", False)
if not readthedocs_is_building:
    install_requires.extend(fastecdsa)


setup(
    name="libp2p",
    # *IMPORTANT*: Don't manually change the version here. Use `make bump`, as described in readme
    version="0.2.0",
    description="""libp2p: The Python implementation of the libp2p networking stack""",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="The Ethereum Foundation",
    author_email="snakecharmers@ethereum.org",
    url="https://github.com/libp2p/py-libp2p",
    include_package_data=True,
    install_requires=install_requires,
    python_requires=">=3.8, <4",
    extras_require=extras_require,
    py_modules=["libp2p"],
    license="MIT/APACHE2.0",
    zip_safe=False,
    keywords="libp2p p2p",
    packages=find_packages(exclude=["scripts", "scripts.*", "tests", "tests.*"]),
    package_data={"libp2p": ["py.typed"]},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    platforms=["unix", "linux", "osx"],
)
