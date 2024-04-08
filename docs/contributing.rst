Contributing
============

Development
-----------

py-libp2p requires Python 3.8+.

To get started, fork the repository to your own github account, then clone it to your
development machine:

```sh
git clone git@github.com:<your-github-username>/py-libp2p.git
```

then install the development dependencies. We recommend using a virtual environment,
such as [`virtualenv`](https://virtualenv.pypa.io/en/stable/)

```sh
cd py-libp2p
virtualenv -p python venv
. venv/bin/activate
python -m pip install -e ".[dev]"
pre-commit install
```

We use [pre-commit](https://pre-commit.com/) to maintain consistent code style. Once
installed, it will run automatically with every commit. You can also run it manually
with `make lint`. If you need to make a commit that skips the `pre-commit` checks, you
can do so with `git commit --no-verify`.

Testing
-------

You can run the tests with `make test` or `pytest tests`. This will run the unit tests




History
-------

Prior to 2023, this project is graciously sponsored by the Ethereum Foundation through
[Wave 5 of their Grants Program](https://blog.ethereum.org/2019/02/21/ethereum-foundation-grants-program-wave-5/).

The creators and original maintainers of this project are:
* [@zixuanzh](https://github.com/zixuanzh)
* [@alexh](https://github.com/alexh)
* [@stuckinaboot](https://github.com/stuckinaboot)
* [@robzajac](https://github.com/robzajac)
* [@carver](https://github.com/carver)
