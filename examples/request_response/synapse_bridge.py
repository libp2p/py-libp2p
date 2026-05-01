from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import subprocess
from typing import Final

DEFAULT_NETWORK: Final = "calibration"
DEFAULT_SOURCE: Final = "py-libp2p-a2a-demo"


class SynapseBridgeError(RuntimeError):
    pass


class SynapseNodeBridgeBackend:
    """Storage backend that delegates real execution to a Node Synapse sidecar."""

    name = "synapse"

    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        cwd: Path | None = None,
        network: str = DEFAULT_NETWORK,
        source: str = DEFAULT_SOURCE,
        execute_transactions: bool = False,
        verify_download: bool = True,
    ) -> None:
        sidecar_dir = cwd or Path(__file__).with_name("synapse_sidecar")
        self._cwd = sidecar_dir
        self._command = list(command or ("node", "synapse_bridge.mjs"))
        self._network = network
        self._source = source
        self._execute_transactions = execute_transactions
        self._verify_download = verify_download

    @classmethod
    def from_env(cls) -> "SynapseNodeBridgeBackend":
        command_env = os.getenv("A2A_SYNAPSE_BRIDGE_COMMAND")
        command = tuple(command_env.split()) if command_env else None
        execute_transactions = os.getenv("A2A_SYNAPSE_EXECUTE_TRANSACTIONS") == "1"
        verify_download = os.getenv("A2A_SYNAPSE_VERIFY_DOWNLOAD", "1") != "0"
        network = os.getenv("A2A_SYNAPSE_NETWORK", DEFAULT_NETWORK)
        source = os.getenv("A2A_SYNAPSE_SOURCE", DEFAULT_SOURCE)
        return cls(
            command=command,
            network=network,
            source=source,
            execute_transactions=execute_transactions,
            verify_download=verify_download,
        )

    def prepare_quote(
        self,
        *,
        task_id: str,
        request_payload: Mapping[str, object],
        base_quote: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        result = self._invoke(
            "prepare_quote",
            {
                "taskId": task_id,
                "requestPayload": dict(request_payload),
                "baseQuote": dict(base_quote),
            },
        )
        return result.get("prepareQuote")

    def execute_storage(
        self,
        *,
        request_payload: Mapping[str, object],
        quote: Mapping[str, object],
        payment_authorization: Mapping[str, object],
    ) -> dict[str, object]:
        result = self._invoke(
            "store",
            {
                "requestPayload": dict(request_payload),
                "quote": dict(quote),
                "paymentAuthorization": dict(payment_authorization),
            },
        )
        storage_result = result.get("storageResult")
        if not isinstance(storage_result, dict):
            raise SynapseBridgeError("sidecar response is missing storageResult")
        return storage_result

    def _invoke(self, action: str, payload: Mapping[str, object]) -> dict[str, object]:
        body = {
            "action": action,
            "network": self._network,
            "source": self._source,
            "executeTransactions": self._execute_transactions,
            "verifyDownload": self._verify_download,
            "payload": dict(payload),
        }
        env = os.environ.copy()
        env.setdefault("A2A_SYNAPSE_NETWORK", self._network)
        env.setdefault("A2A_SYNAPSE_SOURCE", self._source)

        completed = subprocess.run(
            self._command,
            cwd=self._cwd,
            env=env,
            input=json.dumps(body),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            stdout = completed.stdout.strip()
            raise SynapseBridgeError(
                "Synapse sidecar failed"
                + (f": {stderr}" if stderr else "")
                + (f" | stdout={stdout}" if stdout else "")
            )
        try:
            parsed = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise SynapseBridgeError(
                f"Synapse sidecar returned invalid JSON: {completed.stdout!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise SynapseBridgeError("Synapse sidecar returned a non-object response")
        error = parsed.get("error")
        if isinstance(error, str) and error:
            raise SynapseBridgeError(error)
        return parsed
