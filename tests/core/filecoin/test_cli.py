import json
import runpy
import sys

import pytest

from libp2p.filecoin.cli import main


def test_cli_topics_json_output(capsys) -> None:
    rc = main(["topics", "--network", "mainnet", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["network_alias"] == "mainnet"
    assert payload["network_name"] == "testnetnet"
    assert payload["blocks_topic"] == "/fil/blocks/testnetnet"
    assert payload["messages_topic"] == "/fil/msgs/testnetnet"
    assert payload["dht_protocol"] == "/fil/kad/testnetnet"


def test_cli_bootstrap_canonical_json_output(capsys) -> None:
    rc = main(["bootstrap", "--network", "calibnet", "--canonical", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["network_alias"] == "calibnet"
    assert payload["mode"] == "canonical"
    assert payload["count"] == 5
    assert payload["addresses"][0].startswith("/dns/")


def test_cli_bootstrap_runtime_json_output_without_dns_resolution(capsys) -> None:
    rc = main(
        [
            "bootstrap",
            "--network",
            "mainnet",
            "--runtime",
            "--no-resolve-dns",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["network_alias"] == "mainnet"
    assert payload["mode"] == "runtime"
    assert payload["count"] > 0
    assert all("/tcp/" in addr for addr in payload["addresses"])


def test_cli_preset_json_output(capsys) -> None:
    rc = main(["preset", "--network", "calibnet", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["network"]["alias"] == "calibnet"
    assert payload["network"]["genesis_network_name"] == "calibrationnet"
    assert payload["topics"]["blocks"] == "/fil/blocks/calibrationnet"
    assert payload["score"]["gossip_threshold"] == -500.0
    assert payload["score"]["publish_threshold"] == -1000.0
    assert payload["score"]["graylist_threshold"] == -2500.0
    assert payload["score"]["accept_px_threshold"] == 1000.0


def test_python_module_invocation_smoke(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "libp2p.filecoin",
            "topics",
            "--network",
            "calibnet",
            "--json",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("libp2p.filecoin", run_name="__main__")
    assert exc.value.code == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["network_alias"] == "calibnet"
    assert payload["network_name"] == "calibrationnet"
