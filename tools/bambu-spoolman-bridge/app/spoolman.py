"""Spoolman REST client.

Uses the community-convention extra fields (concept §4.2) so the bridge,
OpenSpoolMan and BambuSpoolPal interoperate:
  spool.extra.tag          -> RFID tag_uid
  spool.extra.active_tray  -> current AMS slot
  filament.extra.filament_id / type / nozzle_temperature

NOTE: Spoolman stores extra-field *values* as JSON-encoded strings. We always
json.dumps on write and json.loads on read.
"""
from __future__ import annotations

import json
from typing import Any

import httpx


def _decode_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (extra or {}).items():
        try:
            out[k] = json.loads(v) if isinstance(v, str) else v
        except (ValueError, TypeError):
            out[k] = v
    return out


def _encode_extra(extra: dict[str, Any]) -> dict[str, str]:
    return {k: json.dumps(v) for k, v in extra.items()}


class SpoolmanClient:
    def __init__(self, base_url: str, tag_field: str = "tag", slot_field: str = "active_tray"):
        self.base = base_url.rstrip("/")
        self.tag_field = tag_field
        self.slot_field = slot_field
        self._http = httpx.Client(timeout=10.0)

    # ---- reads ------------------------------------------------------------
    def list_spools(self) -> list[dict]:
        r = self._http.get(f"{self.base}/api/v1/spool")
        r.raise_for_status()
        spools = r.json()
        for s in spools:
            s["_extra"] = _decode_extra(s.get("extra"))
        return spools

    def list_filaments(self) -> list[dict]:
        r = self._http.get(f"{self.base}/api/v1/filament")
        r.raise_for_status()
        return r.json()

    def find_spool_by_tag(self, tag_uid: str) -> dict | None:
        for s in self.list_spools():
            if str(s["_extra"].get(self.tag_field, "")) == tag_uid:
                return s
        return None

    def get_spool(self, spool_id: int) -> dict:
        r = self._http.get(f"{self.base}/api/v1/spool/{spool_id}")
        r.raise_for_status()
        s = r.json()
        s["_extra"] = _decode_extra(s.get("extra"))
        return s

    # ---- writes -----------------------------------------------------------
    def create_spool(self, filament_id: int, initial_weight: float, tag_uid: str = "") -> dict:
        body: dict[str, Any] = {"filament_id": filament_id, "initial_weight": initial_weight}
        if tag_uid:
            body["extra"] = _encode_extra({self.tag_field: tag_uid})
        r = self._http.post(f"{self.base}/api/v1/spool", json=body)
        r.raise_for_status()
        return r.json()

    def set_extra(self, spool_id: int, **values: Any) -> None:
        # merge with existing extra so we don't clobber other fields
        current = self.get_spool(spool_id)["_extra"]
        current.update(values)
        self._patch_spool(spool_id, {"extra": _encode_extra(current)})

    def set_tag(self, spool_id: int, tag_uid: str) -> None:
        self.set_extra(spool_id, **{self.tag_field: tag_uid})

    def set_active_tray(self, spool_id: int, slot: str | None) -> None:
        self.set_extra(spool_id, **{self.slot_field: slot or ""})

    def set_location(self, spool_id: int, location: str | None) -> None:
        """Spoolman's native (first-class) location field used for storage grouping."""
        self._patch_spool(spool_id, {"location": location or ""})

    def set_remaining(self, spool_id: int, grams: float) -> None:
        self._patch_spool(spool_id, {"remaining_weight": round(grams, 2)})

    def use_weight(self, spool_id: int, grams: float) -> None:
        r = self._http.put(
            f"{self.base}/api/v1/spool/{spool_id}/use", json={"use_weight": round(grams, 2)}
        )
        r.raise_for_status()

    def _patch_spool(self, spool_id: int, body: dict[str, Any]) -> None:
        r = self._http.put(f"{self.base}/api/v1/spool/{spool_id}", json=body)
        r.raise_for_status()
