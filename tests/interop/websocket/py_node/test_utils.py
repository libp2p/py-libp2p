import json
import time
from typing import Any

import trio


class ResultCollector:
    def __init__(self) -> None:
        self.results: dict[str, dict[str, Any]] = {}
        self.errors: list[str] = []
        self.start_time = time.time()

    def add_result(self, test_name: str, success: bool, details: Any = None) -> None:
        self.results[test_name] = {
            "success": success,
            "details": details,
            "timestamp": time.time(),
            "duration": time.time() - self.start_time,
        }

    def add_error(self, error: str) -> None:
        self.errors.append(str(error))

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": self.results,
            "errors": self.errors,
            "total_tests": len(self.results),
            "passed": sum(1 for r in self.results.values() if r["success"]),
            "failed": sum(1 for r in self.results.values() if not r["success"]),
            "total_duration": time.time() - self.start_time,
        }


async def wait_for_server_ready(host: str, port: int, timeout: float = 10.0) -> bool:
    import socket

    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except Exception:
            pass
        await trio.sleep(0.5)
    return False


def save_results_to_file(
    results: dict[str, Any], filename: str = "test_results.json"
) -> None:
    try:
        with open(filename, "w") as f:
            json.dump(results, f, indent=2, default=str)
    except Exception:
        pass


def TestResults() -> ResultCollector:
    return ResultCollector()
