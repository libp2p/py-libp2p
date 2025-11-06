# py-libp2p

<h1 align="center">
  <a href="https://libp2p.io/"><img width="250" src="https://github.com/libp2p/py-libp2p/blob/main/assets/py-libp2p-logo.png?raw=true" alt="py-libp2p hex logo" /></a>
</h1>

<h3 align="center">The Python implementation of the libp2p networking stack.</h3>

<p align="center">
  <a href="https://filecoin.drips.network/app/projects/github/libp2p/py-libp2p" target="_blank">
    <img src="https://filecoin.drips.network/api/embed/project/https%3A%2F%2Fgithub.com%2Flibp2p%2Fpy-libp2p/support.png?background=light&style=drips&text=Support&stat=support"
         alt="Support py-libp2p on drips.network" height="36">
  </a>
</p>

[![Discord](https://img.shields.io/discord/1204447718093750272?color=blueviolet&label=discord)](https://discord.gg/hQJnbd85N6)
[![PyPI version](https://badge.fury.io/py/libp2p.svg)](https://badge.fury.io/py/libp2p)
[![Python versions](https://img.shields.io/pypi/pyversions/libp2p.svg)](https://pypi.python.org/pypi/libp2p)
[![Build Status](https://img.shields.io/github/actions/workflow/status/libp2p/py-libp2p/tox.yml?branch=main&label=build%20status)](https://github.com/libp2p/py-libp2p/actions/workflows/tox.yml)
[![Docs build](https://readthedocs.org/projects/py-libp2p/badge/?version=latest)](https://py-libp2p.readthedocs.io/en/latest/?badge=latest)

> py-libp2p has moved beyond its experimental roots and is progressing toward production readiness. Core modules are stable, with active work on performance, protocol coverage, and interop with other libp2p implementations. We welcome contributions and real-world usage feedback.

## Impact

py-libp2p connects the Web3 networking stack to the Python ecosystem—widely used in scientific computing, distributed systems research, machine learning workflows, and backend services.

These libraries are already powering work in:

- Federated learning frameworks
- Decentralized research data sharing systems
- IPFS and Filecoin developer toolchains
- Contribution verification and reproducibility protocols

By bringing libp2p to Python, we open decentralized networking to millions of researchers, engineers, and data practitioners who previously lacked access to modern peer-to-peer infrastructure.

## Community Adoption and Collaboration

The project participates in Filecoin & IPFS working groups and has been highlighted at PL EngRes, The Gathering, Code for GovTech 2024–25, and Zanzalu. Development is community-driven across the Filecoin, IPFS, Ethereum, and decentralized computing ecosystems.

This strengthens the Filecoin network by enabling applied science and research computing workloads to run over decentralized infrastructure.

## Why This Matters to Filecoin

A production-ready Python libp2p stack allows Filecoin storage, retrieval, compute, and collaborative data workflows to integrate directly into Python-based systems—from ML pipelines to distributed scientific research.

We aim for py-libp2p to become the default networking substrate for distributed Python applications.

Read more in the documentation: https://py-libp2p.readthedocs.io  
Release Notes: https://py-libp2p.readthedocs.io/en/latest/release_notes.html

## Maintainers

Maintained by [@pacrob](https://github.com/pacrob), [@seetadev](https://github.com/seetadev), and [@dhuseby](https://github.com/dhuseby).

Questions or ideas?  
Start a discussion: https://github.com/libp2p/py-libp2p/discussions  
Join the Discord: https://discord.gg/d92MEugb (#py-libp2p)

## Feature Breakdown

py-libp2p aligns with the standard libp2p modules architecture:

✅ Stable · 🛠️ In Progress · 🌱 Prototype · ❌ Not Yet Implemented

---

### Transports

| Transport                            | Status | Source |
|-------------------------------------|:------:|:------:|
| `libp2p-tcp`                        | ✅ | https://github.com/libp2p/py-libp2p/blob/main/libp2p/transport/tcp/tcp.py |
| `libp2p-quic`                       | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/transport/quic |
| `libp2p-websocket`                  | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/transport/websocket |
| `libp2p-webrtc-browser-to-server`   | 🌱 | — |
| `libp2p-webrtc-private-to-private`  | 🌱 | — |

---

### NAT Traversal

| NAT Traversal             | Status | Source |
|--------------------------|:------:|:------:|
| `libp2p-circuit-relay-v2`| ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/relay/circuit_v2 |
| `libp2p-autonat`         | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/host/autonat |
| `libp2p-hole-punching`   | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/relay/circuit_v2 |

---

### Secure Communication

| Secure Channel   | Status | Source |
|------------------|:------:|:------:|
| `libp2p-noise`   | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/security/noise |
| `libp2p-tls`     | ✅ | — |

---

### Discovery

| Discovery        | Status | Source |
|------------------|:------:|:------:|
| `bootstrap`      | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/bootstrap |
| `random-walk`    | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/random_walk |
| `mdns-discovery` | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/mdns |
| `rendezvous`     | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/discovery/rendezvous |

---

### Peer Routing

| Peer Routing     | Status | Source |
|------------------|:------:|:------:|
| `libp2p-kad-dht` | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/kad_dht |

---

### Publish/Subscribe

| PubSub            | Status | Source |
|-------------------|:------:|:------:|
| `libp2p-floodsub` | ✅ | https://github.com/libp2p/py-libp2p/blob/main/libp2p/pubsub/floodsub.py |
| `libp2p-gossipsub`| ✅ | https://github.com/libp2p/py-libp2p/blob/main/libp2p/pubsub/gossipsub.py |

---

### Stream Muxers

| Muxer            | Status | Source |
|------------------|:------:|:------:|
| `libp2p-yamux`   | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/stream_muxer/yamux |
| `libp2p-mplex`   | ✅ | https://github.com/libp2p/py-libp2p/tree/main/libp2p/stream_muxer/mplex |

---

## Support

If py-libp2p has been useful to your project or organization, please consider supporting ongoing development:

<a href="https://filecoin.drips.network/app/projects/github/libp2p/py-libp2p" target="_blank">
  <img src="https://filecoin.drips.network/api/embed/project/https%3A%2F%2Fgithub.com%2Flibp2p%2Fpy-libp2p/support.png?background=light&style=drips&text=project&stat=support" height="32" alt="Support py-libp2p on drips.network">
</a>
