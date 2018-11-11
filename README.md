# py-libp2p

<img width="250" align="center" src="https://github.com/zixuanzh/py-libp2p/blob/master/assets/py-libp2p-logo.png?raw=true" alt="py-libp2p hex logo" />

## Development

py-libp2p requires Python 3.6 and the best way to guarantee a clean Python 3.6 environment is with [`virtualenv`](https://virtualenv.pypa.io/en/stable/)

```sh
virtualenv -p python3.6 venv
. venv/bin/activate
pip install -r requirements.txt
```

## Testing

After installing our requirements (see above), you can:
```sh
cd tests
pytest
```
