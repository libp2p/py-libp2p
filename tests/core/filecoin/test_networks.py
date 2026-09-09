import pytest

from libp2p.filecoin.networks import (
    CALIBNET_BOOTSTRAP,
    MAINNET_BOOTSTRAP,
    get_network_preset,
)


def test_network_alias_maps_to_expected_genesis_names() -> None:
    assert get_network_preset("mainnet").genesis_network_name == "testnetnet"
    assert get_network_preset("calibnet").genesis_network_name == "calibrationnet"


def test_mainnet_bootstrap_list_integrity() -> None:
    preset = get_network_preset("mainnet")
    assert preset.bootstrap_addresses == MAINNET_BOOTSTRAP
    assert len(preset.bootstrap_addresses) == 8
    assert len(set(preset.bootstrap_addresses)) == len(preset.bootstrap_addresses)
    assert all("/p2p/" in addr for addr in preset.bootstrap_addresses)
    assert any("/quic-v1/" in addr for addr in preset.bootstrap_addresses)


def test_calibnet_bootstrap_list_integrity() -> None:
    preset = get_network_preset("calibnet")
    assert preset.bootstrap_addresses == CALIBNET_BOOTSTRAP
    assert len(preset.bootstrap_addresses) == 5
    assert len(set(preset.bootstrap_addresses)) == len(preset.bootstrap_addresses)
    assert all("/p2p/" in addr for addr in preset.bootstrap_addresses)
    assert all("/tcp/" in addr for addr in preset.bootstrap_addresses)


def test_unknown_network_alias_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_network_preset("devnet")
