"""Import the Bambu Filament Manager / cloud library into Spoolman (concept §6).

Reads the cloud filament list (REST) — or a saved JSON capture — and maps each
record (cloud "FilamentV2" camelCase schema, see filament-cloud-api-analysis-spec.md
§1.3) to Spoolman vendor/filament/spool, storing the RFID as extra.tag and the
cloud id as extra.cloud_id for idempotency.

IMPORTANT: the live endpoint path is still a HYPOTHESIS (spec §1.2.1) and must be
confirmed via capture/RE. Use `load_from_file()` against a mitmproxy capture to
test the mapping before the path is verified.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .db import Database
from .models import density_for, is_valid_tag_uid
from .spoolman import SpoolmanClient

log = logging.getLogger("bridge.cloud_library")

CLOUD_ID_FIELD = "cloud_id"
DEFAULT_ENDPOINT = "/v1/user-service/my/filament/v2"  # hypothesis — verify (spec §1.2.1)


def api_host_for(region: str, override: str = "") -> str:
    if override:
        return override.rstrip("/")
    return "https://api.bambulab.cn" if (region or "").lower() == "cn" else "https://api.bambulab.com"


def extract_records(payload: Any) -> list[dict]:
    """Pull the filament array out of various plausible response shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("filaments", "list", "data", "result"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict) and isinstance(v.get("filaments"), list):
                return v["filaments"]
    return []


def map_record(rec: dict) -> dict:
    """Normalize one cloud record to the fields we need. Tolerates local-key aliases."""
    def s(*keys: str) -> str:
        for k in keys:
            if rec.get(k) not in (None, ""):
                return str(rec[k])
        return ""

    def num(*keys: str) -> float:
        for k in keys:
            v = rec.get(k)
            if isinstance(v, (int, float)):
                return float(v)
        return 0.0

    rfid = s("RFID", "rfid", "tag_uid")
    return {
        "cloud_id": s("id", "spool_id"),
        "rfid": rfid if is_valid_tag_uid(rfid) else "",
        "vendor": s("filamentVendor", "brand") or "Bambu Lab",
        "material": s("filamentType", "material_type") or "PLA",
        "name": s("filamentName", "series"),
        "color_hex": s("color", "color_code").lstrip("#"),
        "setting_id": s("filamentId", "setting_id"),
        "total_net": num("totalNetWeight", "initial_weight"),
        "net": num("netWeight", "net_weight"),
    }


def fetch_cloud_filaments(api_host: str, endpoint: str, token: str, limit: int = 200) -> list[dict]:
    import httpx

    url = api_host.rstrip("/") + endpoint
    r = httpx.get(url, headers={"Authorization": f"Bearer {token}"},
                  params={"limit": limit, "offset": 0}, timeout=20.0)
    r.raise_for_status()
    return extract_records(r.json())


def load_from_file(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        return extract_records(json.load(fh))


class CloudLibraryImporter:
    def __init__(self, spoolman: SpoolmanClient, db: Database):
        self.spoolman = spoolman
        self.db = db

    def import_records(self, records: list[dict], dry_run: bool = False) -> dict[str, Any]:
        summary = {"total": len(records), "created": 0, "updated": 0, "skipped": 0,
                   "errors": 0, "details": []}
        for raw in records:
            m = map_record(raw)
            try:
                self._import_one(m, summary, dry_run)
            except Exception as e:  # noqa: BLE001
                summary["errors"] += 1
                summary["details"].append({"action": "error", "cloud_id": m.get("cloud_id"), "error": str(e)})
                log.exception("import failed for cloud_id=%s", m.get("cloud_id"))
        return summary

    def _existing_spool_id(self, m: dict) -> int | None:
        if m["rfid"]:
            sid = self.db.get_spool_by_tag(m["rfid"])
            if sid is not None:
                return sid
            sp = self.spoolman.find_spool_by_tag(m["rfid"])
            if sp:
                return sp["id"]
        if m["cloud_id"]:
            sp = self.spoolman.find_spool_by_extra(CLOUD_ID_FIELD, m["cloud_id"])
            if sp:
                return sp["id"]
        return None

    def _import_one(self, m: dict, summary: dict, dry_run: bool) -> None:
        existing = self._existing_spool_id(m)
        if existing is not None:
            summary["skipped"] += 1
            summary["details"].append({"action": "skip", "cloud_id": m["cloud_id"], "spool_id": existing})
            if m["rfid"] and not dry_run:
                self.db.bind_tag(m["rfid"], existing, hint="cloud")
            return

        if dry_run:
            summary["created"] += 1
            summary["details"].append({"action": "would-create", "cloud_id": m["cloud_id"],
                                       "name": m["name"] or m["material"], "rfid": m["rfid"]})
            return

        vendor_id = self.spoolman.find_or_create_vendor(m["vendor"])
        fil = self.spoolman.find_filament(m["material"], m["color_hex"], vendor_id)
        if fil is None:
            name = m["name"] or f'{m["vendor"]} {m["material"]}'.strip()
            extra = {"filament_id": m["setting_id"], "type": m["material"]} if m["setting_id"] else None
            fil = self.spoolman.create_filament(
                name=name, material=m["material"], color_hex=m["color_hex"],
                weight=m["total_net"] or 1000.0, diameter=1.75,
                density=density_for(m["material"]), vendor_id=vendor_id, extra=extra,
            )
        spool = self.spoolman.create_spool(
            filament_id=fil["id"],
            initial_weight=m["total_net"] or 1000.0,
            tag_uid=m["rfid"],
            extra={CLOUD_ID_FIELD: m["cloud_id"]} if m["cloud_id"] else None,
            remaining=m["net"] if m["net"] > 0 else None,
        )
        sid = spool["id"]
        if m["rfid"]:
            self.db.bind_tag(m["rfid"], sid, hint="cloud")
            self.db.upsert_tag(m["rfid"], state="bambu_original", current_spool=sid)
        summary["created"] += 1
        summary["details"].append({"action": "created", "cloud_id": m["cloud_id"], "spool_id": sid})
