from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

NetworkAlias = Literal["mainnet", "calibnet"]


@dataclass(frozen=True, slots=True)
class FilecoinNetworkPreset:
    name: NetworkAlias
    genesis_network_name: str
    bootstrap_addresses: tuple[str, ...]


MAINNET_BOOTSTRAP: tuple[str, ...] = (
    "/dns/bootstrap.filecoin.chain.love/tcp/1235/p2p/12D3KooWBF8cpp65hp2u9LK5mh19x67ftAam84z9LsfaquTDSBpt",
    "/dns/bootstrap-venus.mainnet.filincubator.com/tcp/8888/p2p/QmQu8C6deXwKvJP2D8B6QGyhngc3ZiDnFzEHBDx8yeBXST",
    "/dns/bootstrap-mainnet-0.chainsafe-fil.io/tcp/34000/p2p/12D3KooWKKkCZbcigsWTEu1cgNetNbZJqeNtysRtFpq7DTqw3eqH",
    "/dns/bootstrap-mainnet-1.chainsafe-fil.io/tcp/34000/p2p/12D3KooWGnkd9GQKo3apkShQDaq1d6cKJJmsVe6KiQkacUk1T8oZ",
    "/dns/bootstrap-mainnet-2.chainsafe-fil.io/tcp/34000/p2p/12D3KooWHQRSDFv4FvAjtU32shQ7znz7oRbLBryXzZ9NMK2feyyH",
    "/dns/n1.mainnet.fil.devtty.eu/udp/443/quic-v1/p2p/12D3KooWAke3M2ji7tGNKx3BQkTHCyxVhtV1CN68z6Fkrpmfr37F",
    "/dns/n1.mainnet.fil.devtty.eu/tcp/443/p2p/12D3KooWAke3M2ji7tGNKx3BQkTHCyxVhtV1CN68z6Fkrpmfr37F",
    "/dns/n1.mainnet.fil.devtty.eu/udp/443/quic-v1/webtransport/certhash/uEiAWlgd8EqbNhYLv86OdRvXHMosaUWFFDbhgGZgCkcmKnQ/certhash/uEiAvtq6tvZOZf_sIuityDDTyAXDJPfXSRRDK2xy9UVPsqA/p2p/12D3KooWAke3M2ji7tGNKx3BQkTHCyxVhtV1CN68z6Fkrpmfr37F",
)

CALIBNET_BOOTSTRAP: tuple[str, ...] = (
    "/dns/bootstrap.calibration.filecoin.chain.love/tcp/1237/p2p/12D3KooWQPYouEAsUQKzvFUA9sQ8tz4rfpqtTzh2eL6USd9bwg7x",
    "/dns/bootstrap-calibnet-0.chainsafe-fil.io/tcp/34000/p2p/12D3KooWABQ5gTDHPWyvhJM7jPhtNwNJruzTEo32Lo4gcS5ABAMm",
    "/dns/bootstrap-calibnet-1.chainsafe-fil.io/tcp/34000/p2p/12D3KooWS3ZRhMYL67b4bD5XQ6fcpTyVQXnDe8H89LvwrDqaSbiT",
    "/dns/bootstrap-calibnet-2.chainsafe-fil.io/tcp/34000/p2p/12D3KooWEiBN8jBX8EBoM3M47pVRLRWV812gDRUJhMxgyVkUoR48",
    "/dns/bootstrap-archive-calibnet-0.chainsafe-fil.io/tcp/1347/p2p/12D3KooWLcRpEfmUq1fC8vfcLnKc1s161C92rUewEze3ALqCd9yJ",
)

NETWORK_PRESETS: dict[NetworkAlias, FilecoinNetworkPreset] = {
    "mainnet": FilecoinNetworkPreset(
        name="mainnet",
        genesis_network_name="testnetnet",
        bootstrap_addresses=MAINNET_BOOTSTRAP,
    ),
    "calibnet": FilecoinNetworkPreset(
        name="calibnet",
        genesis_network_name="calibrationnet",
        bootstrap_addresses=CALIBNET_BOOTSTRAP,
    ),
}


def get_network_preset(network: NetworkAlias | str) -> FilecoinNetworkPreset:
    network_key = network.lower()
    if network_key not in NETWORK_PRESETS:
        raise ValueError(
            f"unknown Filecoin network '{network}'. expected one of: "
            f"{', '.join(NETWORK_PRESETS.keys())}"
        )
    return NETWORK_PRESETS[network_key]  # type: ignore[index]
