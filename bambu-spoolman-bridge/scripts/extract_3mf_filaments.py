#!/usr/bin/env python3
"""Extract filament profiles from a Bambu/Orca .3mf project file.

A .3mf is a ZIP. Bambu/Orca store the merged slicer settings in
`Metadata/project_settings.config` (JSON); filament parameters are arrays, one
entry per filament slot. This pulls them apart into per-filament dicts and emits:
  - a human summary (vendor / type / colour / temps)
  - filaments.json (Spoolman-friendly list)
  - the raw filament_* settings (to rebuild Orca/Bambu presets if wanted)

Usage:
    python3 extract_3mf_filaments.py model.3mf [--out outdir]

This does NOT upload anything to a Bambu account — for that, open the .3mf in
Bambu Studio and save the filaments as user presets (they sync to the cloud).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import zipfile

# project_settings.config keys we care about (all are per-slot arrays).
FIELDS = {
    "name": "filament_settings_id",
    "vendor": "filament_vendor",
    "type": "filament_type",
    "color_hex": "filament_colour",
    "density": "filament_density",
    "diameter": "filament_diameter",
    "nozzle_temp": "nozzle_temperature",
    "nozzle_temp_initial": "nozzle_temperature_initial_layer",
    "bed_temp": "hot_plate_temp",
    "max_vol_speed": "filament_max_volumetric_speed",
    "flow_ratio": "filament_flow_ratio",
}


def _load_settings(zf: zipfile.ZipFile) -> dict:
    names = zf.namelist()
    # primary location
    for cand in ("Metadata/project_settings.config", "Metadata/project_settings.json"):
        if cand in names:
            return json.loads(zf.read(cand))
    # fallback: any .config that parses as JSON containing filament_type
    for n in names:
        if n.lower().endswith((".config", ".json")) and "metadata/" in n.lower():
            try:
                d = json.loads(zf.read(n))
                if isinstance(d, dict) and "filament_type" in d:
                    return d
            except Exception:  # noqa: BLE001
                continue
    return {}


def _as_list(v):
    return v if isinstance(v, list) else [v]


def extract(path: str) -> list[dict]:
    with zipfile.ZipFile(path) as zf:
        cfg = _load_settings(zf)
    if not cfg:
        return []
    arrays = {key: _as_list(cfg.get(src, [])) for key, src in FIELDS.items()}
    count = max((len(v) for v in arrays.values() if v), default=0)
    out = []
    for i in range(count):
        rec = {}
        for key, vals in arrays.items():
            rec[key] = vals[i] if i < len(vals) else ""
        if rec.get("color_hex"):
            rec["color_hex"] = str(rec["color_hex"]).lstrip("#")
        out.append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("threemf")
    ap.add_argument("--out", default="filament_profiles")
    args = ap.parse_args()

    fils = extract(args.threemf)
    if not fils:
        print("No filament settings found (is this a Bambu/Orca project 3mf?).")
        return 1

    outdir = pathlib.Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "filaments.json").write_text(json.dumps(fils, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Found {len(fils)} filament profile(s) in {args.threemf}:\n")
    for f in fils:
        print(f"  • {f.get('name') or '?'}  [{f.get('vendor') or '?'} / {f.get('type') or '?'}]"
              f"  colour=#{f.get('color_hex') or '------'}"
              f"  nozzle={f.get('nozzle_temp') or '?'}°C  bed={f.get('bed_temp') or '?'}°C")
    print(f"\nWrote {outdir/'filaments.json'}")
    print("Import into the Bambu account: open the .3mf in Bambu Studio, save the")
    print("filaments as user presets -> they sync to your cloud account.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
