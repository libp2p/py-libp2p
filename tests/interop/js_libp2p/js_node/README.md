# @libp2p/example-chat <!-- omit in toc -->

[![libp2p.io](https://img.shields.io/badge/project-libp2p-yellow.svg?style=flat-square)](http://libp2p.io/)
[![Discuss](https://img.shields.io/discourse/https/discuss.libp2p.io/posts.svg?style=flat-square)](https://discuss.libp2p.io)
[![codecov](https://img.shields.io/codecov/c/github/libp2p/js-libp2p-examples.svg?style=flat-square)](https://codecov.io/gh/libp2p/js-libp2p-examples)
[![CI](https://img.shields.io/github/actions/workflow/status/libp2p/js-libp2p-examples/ci.yml?branch=main&style=flat-square)](https://github.com/libp2p/js-libp2p-examples/actions/workflows/ci.yml?query=branch%3Amain)

> An example chat app using libp2p

## Table of contents <!-- omit in toc -->

- [Setup](#setup)
- [Running](#running)
- [Need help?](#need-help)
- [License](#license)
- [Contribution](#contribution)

## Setup

1. Install example dependencies
   ```console
   $ npm install
   ```
1. Open 2 terminal windows in the `./src` directory.

## Running

1. Run the listener in window 1, `node listener.js`
1. Run the dialer in window 2, `node dialer.js`
1. Wait until the two peers discover each other
1. Type a message in either window and hit *enter*
1. Tell yourself secrets to your hearts content!

## Need help?

- Read the [js-libp2p documentation](https://github.com/libp2p/js-libp2p/tree/main/doc)
- Check out the [js-libp2p API docs](https://libp2p.github.io/js-libp2p/)
- Check out the [general libp2p documentation](https://docs.libp2p.io) for tips, how-tos and more
- Read the [libp2p specs](https://github.com/libp2p/specs)
- Ask a question on the [js-libp2p discussion board](https://github.com/libp2p/js-libp2p/discussions)

## License

Licensed under either of

- Apache 2.0, ([LICENSE-APACHE](LICENSE-APACHE) / <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT ([LICENSE-MIT](LICENSE-MIT) / <http://opensource.org/licenses/MIT>)

## Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted
for inclusion in the work by you, as defined in the Apache-2.0 license, shall be
dual licensed as above, without any additional terms or conditions.
