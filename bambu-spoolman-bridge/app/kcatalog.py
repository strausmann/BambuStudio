"""Persistent k-value catalog (concept §8, item c).

Stores observed/calibrated pressure-advance k per (vendor, material-family,
nozzle) so your calibrations survive and can seed future presets/printers.
Keyed coarse on purpose: k depends on filament + nozzle, not on the spool.
"""
from __future__ import annotations

import json
import os
import threading
import time

from .models import material_family


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class KCatalog:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if os.path.exists(path):
            try:
                self._data = json.load(open(path, encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self._data = {}

    @staticmethod
    def _key(vendor: str, material: str, nozzle: str) -> str:
        return f"{(vendor or '').strip()}|{material_family(material)}|{nozzle}"

    def upsert(self, vendor: str, material: str, nozzle: str, k: float, n: float | None = None) -> bool:
        """Returns True if k changed/added."""
        key = self._key(vendor, material, nozzle)
        with self._lock:
            e = self._data.get(key, {"samples": 0})
            changed = e.get("k") != k
            e.update({"vendor": vendor, "material": material_family(material),
                      "nozzle": nozzle, "k": k})
            if n is not None:
                e["n"] = n
            e["samples"] = e.get("samples", 0) + 1
            e["updated_at"] = _now()
            self._data[key] = e
            if changed:
                self._save()
        return changed

    def get(self, vendor: str, material: str, nozzle: str) -> dict | None:
        return self._data.get(self._key(vendor, material, nozzle))

    def all(self) -> list[dict]:
        return list(self._data.values())

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
