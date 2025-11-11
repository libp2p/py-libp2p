# py-libp2p Dependency Graph

**Project**: libp2p v0.4.0
**Python Version**: >=3.10, \<4.0

## Runtime Dependencies

Total: 20 dependencies

- **aioquic** (>=1.2.0)
- **base58** (>=1.0.3)
- **coincurve** (==21.0.0)
- **exceptiongroup** (>=1.2.0) [python_version < '3.11']
- **fastecdsa** (==2.3.2) [sys_platform != 'win32']
- **grpcio** (>=1.41.0)
- **lru-dict** (>=1.1.6)
- **miniupnpc** (>=2.3)
- **multiaddr** (>=0.0.11)
- **mypy-protobuf** (>=3.0.0)
- **noiseprotocol** (>=0.3.0)
- **protobuf** (>=4.25.0,\<7.0.0)
- **pycryptodome** (>=3.9.2)
- **pymultihash** (>=0.8.2)
- **pynacl** (>=1.3.0)
- **rpcudp** (>=3.0.0)
- **trio** (>=0.26.0)
- **trio-typing** (>=0.0.4)
- **trio-websocket** (>=0.11.0)
- **zeroconf** (>=0.147.0,\<0.148.0)

## Optional Dependencies

### Dev (21 dependencies)

- **build** (>=0.9.0)
- **bump_my_version** (>=0.19.0)
- **factory-boy** (>=2.12.0,\<3.0.0)
- **ipython**
- **mypy** (>=1.15.0)
- **p2pclient** (==0.2.0)
- **pre-commit** (>=3.4.0)
- **pyrefly** (>=0.17.1,\<0.18.0)
- **pytest** (>=7.0.0)
- **pytest-rerunfailures** (>=12.0)
- **pytest-timeout** (>=2.4.0)
- **pytest-trio** (>=0.5.2)
- **pytest-xdist** (>=2.4.0)
- **ruff** (>=0.11.10)
- **setuptools** (>=42)
- **sphinx** (>=6.0.0)
- **sphinx_rtd_theme** (>=1.0.0)
- **towncrier** (>=24,\<25)
- **tox** (>=4.0.0)
- **twine**
- **wheel**

### Docs (4 dependencies)

- **sphinx** (>=6.0.0)
- **sphinx_rtd_theme** (>=1.0.0)
- **tomli** [python_version < '3.11']
- **towncrier** (>=24,\<25)

### Test (7 dependencies)

- **factory-boy** (>=2.12.0,\<3.0.0)
- **p2pclient** (==0.2.0)
- **pytest** (>=7.0.0)
- **pytest-asyncio** (>=0.21.0)
- **pytest-timeout** (>=2.4.0)
- **pytest-trio** (>=0.5.2)
- **pytest-xdist** (>=2.4.0)
