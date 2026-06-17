import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("py_ipfs_lite.pin")

class PinStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._pins: Dict[str, bool] = {}  # cid_str -> is_recursive
        self._load()

    def _load(self):
        if not self.path:
            return
        pin_file = Path(self.path)
        if pin_file.exists():
            try:
                with open(pin_file, "r") as f:
                    data = json.load(f)
                    self._pins = data.get("pins", {})
            except Exception as e:
                logger.error(f"Failed to load pins from {self.path}: {e}")

    def _save(self):
        if not self.path:
            return
        pin_file = Path(self.path)
        pin_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(pin_file, "w") as f:
                json.dump({"pins": self._pins}, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save pins to {self.path}: {e}")

    def add_pin(self, cid_str: str, recursive: bool = True):
        self._pins[cid_str] = recursive
        self._save()

    def remove_pin(self, cid_str: str):
        if cid_str in self._pins:
            del self._pins[cid_str]
            self._save()

    def is_pinned(self, cid_str: str) -> bool:
        return cid_str in self._pins

    def is_recursive(self, cid_str: str) -> bool:
        return self._pins.get(cid_str, False)

    def get_pins(self) -> Dict[str, bool]:
        return self._pins.copy()
