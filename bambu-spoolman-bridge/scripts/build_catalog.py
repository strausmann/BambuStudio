#!/usr/bin/env python3
"""Seed a normalized filament catalog from the bundled slicer profiles.

BambuStudio (and OrcaSlicer) ship an open database of filament presets as JSON
trees under resources/profiles/<Vendor>/filament/*.json, linked via `inherits`.
This resolves the inherit chains and emits one flat catalog.json — the seed of
our own filament DB (vendor/type/temps/flow/density/…), no API needed.

Usage:
    python3 build_catalog.py /path/to/resources/profiles -o catalog.json

NOTE: the Bambu *K value* (pressure advance) is NOT in these presets — it is
per-printer calibration (cali_idx). The catalog carries filament_flow_ratio and
a placeholder `k_value` you fill from your own calibration (see README).
"""
from __future__ import annotations

import argparse
import glob
import json
import os

PICK = {
    "vendor": "filament_vendor",
    "type": "filament_type",
    "filament_id": "filament_id",
    "flow_ratio": "filament_flow_ratio",
    "density": "filament_density",
    "diameter": "filament_diameter",
    "nozzle_temp": "nozzle_temperature",
    "bed_temp": "hot_plate_temp",
    "max_vol_speed": "filament_max_volumetric_speed",
    "color_hex": "default_filament_colour",
}


def _first(v):
    if isinstance(v, list):
        return v[0] if v else ""
    return v


def build_index(root: str) -> dict[str, str]:
    idx = {}
    for path in glob.glob(os.path.join(root, "*", "filament", "*.json")):
        try:
            d = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        name = d.get("name")
        if name:
            idx[name] = path
    return idx


def resolve(name: str, idx: dict[str, str], cache: dict[str, dict], seen=None) -> dict:
    if name in cache:
        return cache[name]
    seen = seen or set()
    if name in seen or name not in idx:
        return {}
    seen.add(name)
    d = json.load(open(idx[name], encoding="utf-8"))
    parent = resolve(d["inherits"], idx, cache, seen) if d.get("inherits") in idx else {}
    merged = {**parent, **d}
    cache[name] = merged
    return merged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profiles_root", help="resources/profiles")
    ap.add_argument("-o", "--out", default="catalog.json")
    args = ap.parse_args()

    idx = build_index(args.profiles_root)
    cache: dict[str, dict] = {}
    catalog = []
    for name in idx:
        if name.startswith("fdm_") or "@base" in name:
            continue  # skip abstract base classes
        m = resolve(name, idx, cache)
        if not m.get("filament_type") or not m.get("filament_vendor"):
            continue
        rec = {k: _first(m.get(src, "")) for k, src in PICK.items()}
        rec["name"] = name
        rec["k_value"] = None  # fill from your own calibration (per nozzle)
        catalog.append(rec)

    catalog.sort(key=lambda r: (r["vendor"], r["type"], r["name"]))
    json.dump({"filaments": catalog}, open(args.out, "w", encoding="utf-8"),
              indent=2, ensure_ascii=False)

    vendors = sorted({r["vendor"] for r in catalog})
    print(f"Catalog: {len(catalog)} presets from {len(vendors)} vendors -> {args.out}")
    print("Vendors:", ", ".join(vendors))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
