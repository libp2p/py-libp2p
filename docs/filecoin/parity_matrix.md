# Filecoin libp2p Parity Matrix (Lotus v1.35.0 / Forest 0.32.2)

| Concern                                    | Lotus reference                              | Forest reference                                          | py-libp2p mapping                                  | Status      | Notes                                                                 |
| ------------------------------------------ | -------------------------------------------- | --------------------------------------------------------- | -------------------------------------------------- | ----------- | --------------------------------------------------------------------- |
| Hello protocol ID                          | `node/hello/hello.go:31`                     | `src/libp2p/hello/mod.rs:12`                              | `libp2p/filecoin/constants.py:8`                   | implemented | Exact `/fil/hello/1.0.0`.                                             |
| Hello protocol usage surface               | `node/hello/hello.go:134`                    | `src/libp2p/service.rs:636`                               | `examples/filecoin/filecoin_ping_identify_demo.py` | implemented | Examples validate peer protocol support for diagnostics.              |
| Chain exchange protocol ID                 | `chain/exchange/protocol.go:18`              | `src/libp2p/chain_exchange/mod.rs:12`                     | `libp2p/filecoin/constants.py:9`                   | implemented | Exact `/fil/chain/xchg/0.0.1`.                                        |
| Chain exchange protocol usage surface      | `chain/exchange/protocol.go:18`              | `src/libp2p/service.rs:775`                               | `examples/filecoin/filecoin_ping_identify_demo.py` | implemented | Example reports chain-exchange support from identify protocols list.  |
| Blocks topic format                        | `build/params_shared_funcs.go:16`            | `src/libp2p/service.rs:75`                                | `libp2p/filecoin/constants.py:22`                  | implemented | `/fil/blocks/<network>`.                                              |
| Messages topic format                      | `build/params_shared_funcs.go:17`            | `src/libp2p/service.rs:77`                                | `libp2p/filecoin/constants.py:26`                  | implemented | `/fil/msgs/<network>`.                                                |
| DHT protocol name format                   | `build/params_shared_funcs.go:18`            | N/A (not contradicted in provided snapshot)               | `libp2p/filecoin/constants.py:30`                  | implemented | Default follows pinned Lotus helper form.                             |
| Mainnet alias/genesis name                 | `node/modules/chain.go:128`                  | `src/networks/mainnet/mod.rs:26`                          | `libp2p/filecoin/networks.py:36`                   | implemented | `mainnet -> testnetnet`.                                              |
| Calibnet alias/genesis name                | `build/buildconstants/params_calibnet.go:27` | `src/networks/calibnet/mod.rs:24`                         | `libp2p/filecoin/networks.py:41`                   | implemented | `calibnet -> calibrationnet`.                                         |
| Canonical mainnet bootstrap list           | `build/bootstrap/mainnet:1`                  | `src/networks/mainnet/mod.rs:37`                          | `libp2p/filecoin/networks.py:16`                   | implemented | 8 entries pinned.                                                     |
| Canonical calibnet bootstrap list          | `build/bootstrap/calibnet:1`                 | `src/networks/calibnet/mod.rs:33`                         | `libp2p/filecoin/networks.py:27`                   | implemented | 5 entries pinned.                                                     |
| Runtime bootstrap filter and conversion    | `node/config/types.go:Libp2p.BootstrapPeers` | `src/libp2p/service.rs:dial_to_bootstrap_peers_if_needed` | `libp2p/filecoin/bootstrap.py:48`, `:79`, `:122`   | implemented | Transport filter + DNS-to-ip4/tcp conversion in DX layer.             |
| Score thresholds                           | `node/modules/lp2p/pubsub.go:31`             | `src/libp2p/gossip_params.rs:125`                         | `libp2p/filecoin/constants.py:15`                  | implemented | `-500/-1000/-2500/1000/3.5` captured.                                 |
| Mesh defaults (`D`, `Dlo`, `Dhi`, history) | `node/modules/lp2p/pubsub.go:24`             | N/A (Forest does not mirror all knobs identically)        | `libp2p/filecoin/pubsub.py:91`, `:105`, `:108`     | implemented | `8/6/12`, history `10`, initial direct-connect delay `30`.            |
| Topic score references                     | `node/modules/lp2p/pubsub.go:92`             | `src/libp2p/gossip_params.rs:17`                          | `libp2p/filecoin/pubsub.py:34`                     | implemented | Stored as reference constants for future full scorer parity.          |
| Runtime score mode                         | `node/modules/lp2p/pubsub.go:92`             | `src/libp2p/gossip_params.rs:17`                          | `libp2p/filecoin/pubsub.py:64`                     | partial     | Runtime mode is intentionally `thresholds_only`.                      |
| Message ID function                        | `node/modules/lp2p/pubsub.go:429`            | `src/libp2p/behaviour.rs:79`                              | `libp2p/filecoin/constants.py:34`                  | implemented | Blake2b-256 over message payload.                                     |
| CLI topics/bootstrap/preset                | `build/params_shared_funcs.go:16-18`         | `src/libp2p/service.rs:75`                                | `libp2p/filecoin/cli.py`                           | implemented | CLI outputs are derived from mapped constants/helpers.                |
| Dependency-tree artifacts                  | `node/modules/lp2p/pubsub.go:24`             | `src/libp2p/gossip_params.rs:125`                         | `docs/filecoin/*`, `artifacts/filecoin/*`          | implemented | Manual V1 traceability corpus anchored to pinned upstream references. |
| Architecture positioning docs              | `node/modules/chain.go:128`                  | `src/networks/mainnet/mod.rs:26`                          | `docs/filecoin_architecture_positioning.rst`       | implemented | Captures where py-libp2p fits and where full nodes remain required.   |

## Divergence register

1. **DHT textual spec vs pinned implementation helper**

   - Text spec often cited as `fil/<network-name>/kad/1.0.0`.
   - Pinned Lotus helper in provided corpus uses `/fil/kad/<network-name>`.
   - Implementation decision: keep pinned implementation parity unless maintainer overrides.

1. **Score model depth**

   - Upstream clients have richer per-topic scoring machinery.
   - Implementation decision: keep runtime threshold gating and preserve richer values as
     references in `FILECOIN_TOPIC_SCORE_REFERENCE`.
