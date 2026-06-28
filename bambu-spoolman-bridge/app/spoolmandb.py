"""SpoolmanDB integration (concept §2/§7).

Fetches the community filament database (https://donkie.github.io/SpoolmanDB/,
MIT) and creates the selected vendors/filaments in Spoolman — pick by
manufacturer + material type. Tolerant of both the compiled (flattened) and
source-ish shapes.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import material_family
from .spoolman import SpoolmanClient

log = logging.getLogger("bridge.spoolmandb")

DEFAULT_URL = "https://donkie.github.io/SpoolmanDB/filaments.json"


def fetch(url: str = DEFAULT_URL) -> list[dict]:
    r = httpx.get(url, timeout=30.0)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("filaments", [])


def vendor_of(e: dict) -> str:
    return str(e.get("manufacturer") or e.get("vendor") or e.get("brand") or "").strip()


def _weight(e: dict) -> tuple[float | None, float | None]:
    w = e.get("weights")
    if isinstance(w, list) and w:
        return w[0].get("weight"), w[0].get("spool_weight")
    return e.get("weight"), e.get("spool_weight")


def _diameter(e: dict) -> float:
    d = e.get("diameters")
    if isinstance(d, list) and d:
        try:
            return float(d[0])
        except (TypeError, ValueError):
            return 1.75
    try:
        return float(e.get("diameter", 1.75))
    except (TypeError, ValueError):
        return 1.75


def colors_of(e: dict) -> list[dict]:
    cs = e.get("colors")
    if isinstance(cs, list) and cs:
        return cs
    hexv = e.get("color_hex") or e.get("hex")
    if hexv:
        return [{"name": e.get("color_name", ""), "hex": hexv}]
    return [{}]


def summary(entries: list[dict]) -> dict[str, Any]:
    vendors: dict[str, int] = {}
    types: dict[str, int] = {}
    for e in entries:
        vendors[vendor_of(e)] = vendors.get(vendor_of(e), 0) + 1
        t = material_family(str(e.get("material", "")))
        types[t] = types.get(t, 0) + 1
    return {
        "count": len(entries),
        "vendors": sorted(k for k in vendors if k),
        "types": sorted(k for k in types if k),
    }


def import_selected(spoolman: SpoolmanClient, entries: list[dict],
                    vendors: list[str] | None, types: list[str] | None,
                    dry_run: bool = True) -> dict[str, Any]:
    vset = {v.lower() for v in (vendors or [])}
    tset = {material_family(t) for t in (types or [])}
    res = {"created": 0, "skipped": 0, "errors": 0, "details": []}

    for e in entries:
        ven = vendor_of(e)
        material = str(e.get("material", ""))
        if vset and ven.lower() not in vset:
            continue
        if tset and material_family(material) not in tset:
            continue
        weight, spool_weight = _weight(e)
        diameter = _diameter(e)
        density = e.get("density")
        etemp = e.get("extruder_temp")
        btemp = e.get("bed_temp")
        for c in colors_of(e):
            chex = str(c.get("hex") or "").lstrip("#")[:6]
            cname = c.get("name") or ""
            name = f"{ven} {e.get('name', material)}".strip()
            if cname and cname.lower() not in name.lower():
                name = f"{name} {cname}".strip()
            try:
                vendor_id = None if dry_run else spoolman.find_or_create_vendor(ven)
                existing = spoolman.find_filament(material, chex, vendor_id) if not dry_run else None
                if existing:
                    res["skipped"] += 1
                    continue
                if dry_run:
                    res["created"] += 1
                    res["details"].append({"action": "would-create", "name": name, "material": material})
                    continue
                spoolman.create_filament(
                    name=name, material=material, color_hex=chex,
                    weight=float(weight or 1000.0), diameter=diameter,
                    density=float(density or 1.24), vendor_id=vendor_id,
                    spool_weight=float(spool_weight) if spool_weight else None,
                    extruder_temp=etemp, bed_temp=btemp,
                )
                res["created"] += 1
                res["details"].append({"action": "created", "name": name})
            except Exception as ex:  # noqa: BLE001
                res["errors"] += 1
                res["details"].append({"action": "error", "name": name, "error": str(ex)})
                log.exception("spoolmandb import failed for %s", name)
    return res
