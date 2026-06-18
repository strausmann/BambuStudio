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

    def list_vendors(self) -> list[dict]:
        r = self._http.get(f"{self.base}/api/v1/vendor")
        r.raise_for_status()
        return r.json()

    def find_spool_by_tag(self, tag_uid: str) -> dict | None:
        return self.find_spool_by_extra(self.tag_field, tag_uid)

    def find_spool_by_extra(self, key: str, value: str) -> dict | None:
        if not value:
            return None
        for s in self.list_spools():
            if str(s["_extra"].get(key, "")) == str(value):
                return s
        return None

    def get_spool(self, spool_id: int) -> dict:
        r = self._http.get(f"{self.base}/api/v1/spool/{spool_id}")
        r.raise_for_status()
        s = r.json()
        s["_extra"] = _decode_extra(s.get("extra"))
        return s

    # ---- find-or-create (auto onboarding, concept §4.1.1) -----------------
    def find_or_create_vendor(self, name: str) -> int | None:
        if not name:
            return None
        for v in self.list_vendors():
            if v.get("name", "").lower() == name.lower():
                return v["id"]
        r = self._http.post(f"{self.base}/api/v1/vendor", json={"name": name})
        r.raise_for_status()
        return r.json()["id"]

    def find_filament(self, material: str, color_hex: str, vendor_id: int | None) -> dict | None:
        ch = (color_hex or "").lstrip("#").lower()
        for f in self.list_filaments():
            if (f.get("material", "").upper() == material.upper()
                    and (f.get("color_hex", "") or "").lstrip("#").lower() == ch
                    and (vendor_id is None or (f.get("vendor") or {}).get("id") == vendor_id)):
                return f
        return None

    def create_filament(self, name: str, material: str, color_hex: str, weight: float,
                        diameter: float, density: float, vendor_id: int | None,
                        extra: dict[str, Any] | None = None) -> dict:
        body: dict[str, Any] = {
            "name": name, "material": material, "density": density, "diameter": diameter,
            "weight": weight, "color_hex": (color_hex or "").lstrip("#"),
        }
        if vendor_id is not None:
            body["vendor_id"] = vendor_id
        if extra:
            body["extra"] = _encode_extra(extra)
        r = self._http.post(f"{self.base}/api/v1/filament", json=body)
        r.raise_for_status()
        return r.json()

    # ---- writes -----------------------------------------------------------
    def create_spool(self, filament_id: int, initial_weight: float, tag_uid: str = "",
                    extra: dict[str, Any] | None = None, remaining: float | None = None) -> dict:
        body: dict[str, Any] = {"filament_id": filament_id, "initial_weight": initial_weight}
        merged = dict(extra or {})
        if tag_uid:
            merged[self.tag_field] = tag_uid
        if merged:
            body["extra"] = _encode_extra(merged)
        r = self._http.post(f"{self.base}/api/v1/spool", json=body)
        r.raise_for_status()
        spool = r.json()
        if remaining is not None and remaining > 0 and abs(remaining - initial_weight) > 0.5:
            self.set_remaining(spool["id"], remaining)
        return spool

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
