import json
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("py_ipfs_lite.pin")

class PinStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._pins: Dict[str, str] = {}  # cid_str -> "direct" | "recursive"
        self._load()

    def _load(self):
        if not self.path:
            return
        pin_file = Path(self.path)
        if pin_file.exists():
            try:
                with open(pin_file, "r") as f:
                    data = json.load(f)
                    # Migrate old bool format to new string format if needed
                    raw_pins = data.get("pins", {})
                    self._pins = {}
                    for k, v in raw_pins.items():
                        if isinstance(v, bool):
                            self._pins[k] = "recursive" if v else "direct"
                        else:
                            self._pins[k] = v
            except Exception as e:
                logger.error(f"Failed to load pins from {self.path}: {e}")

    def _save(self):
        if not self.path:
            return
        import os
        pin_file = Path(self.path)
        pin_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = pin_file.with_suffix('.tmp')
        try:
            with open(tmp_file, "w") as f:
                json.dump({"pins": self._pins}, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_file, pin_file)
        except Exception as e:
            logger.error(f"Failed to save pins to {self.path}: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    def add_pin(self, cid_str: str, pin_type: str = "recursive"):
        if pin_type not in ("direct", "recursive"):
            raise ValueError(f"Invalid pin type: {pin_type}")
        self._pins[cid_str] = pin_type
        self._save()

    def remove_pin(self, cid_str: str):
        if cid_str not in self._pins:
            from py_ipfs_lite.exceptions import PinNotFoundError
            raise PinNotFoundError(f"not pinned or pinned indirectly: {cid_str}")
        del self._pins[cid_str]
        self._save()

    def is_pinned(self, cid_str: str) -> bool:
        return cid_str in self._pins

    def get_pin_type(self, cid_str: str) -> Optional[str]:
        return self._pins.get(cid_str)

    def get_pins(self, type_filter: str = "all") -> Dict[str, str]:
        if type_filter == "all":
            return self._pins.copy()
        if type_filter in ("direct", "recursive"):
            return {k: v for k, v in self._pins.items() if v == type_filter}
        return {}
