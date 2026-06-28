"""Generate a Bambu/Orca filament preset JSON from catalog/SpoolmanDB data.

Output is importable in Bambu Studio (save as user preset -> auto cloud sync ->
appears in the printer's AMS filament picker). Pushing via put_setting is a TODO
(needs the RE'd endpoint).

Preset values are stored as string arrays, mirroring the slicer profile format
(see resources/profiles/.../filament/*.json).
"""
from __future__ import annotations

from typing import Any

from .models import material_family

# Map material family -> Bambu abstract base preset (inherits target).
BASE_BY_FAMILY = {
    "PLA": "fdm_filament_pla",
    "PETG": "fdm_filament_pet",
    "PET": "fdm_filament_pet",
    "ABS": "fdm_filament_abs",
    "ASA": "fdm_filament_asa",
    "TPU": "fdm_filament_tpu",
    "PC": "fdm_filament_pc",
    "PA": "fdm_filament_pa",
    "PVA": "fdm_filament_pva",
    "HIPS": "fdm_filament_hips",
}


def base_for(material: str) -> str:
    return BASE_BY_FAMILY.get(material_family(material), "fdm_filament_pla")


def _arr(v) -> list[str]:
    return [str(v)]


def generate(vendor: str, material: str, name: str = "", color_hex: str = "",
             nozzle_temp=None, bed_temp=None, flow_ratio=None, density=None,
             diameter: float = 1.75, max_vol_speed=None, filament_id: str = "",
             compatible_printer: str = "Bambu Lab X1 Carbon 0.4 nozzle") -> dict[str, Any]:
    """Return a Bambu filament preset dict. Unspecified values inherit from base."""
    disp = name or f"{vendor} {material}".strip()
    j: dict[str, Any] = {
        "type": "filament",
        "name": disp,
        "inherits": base_for(material),
        "from": "User",
        "filament_vendor": _arr(vendor or "Generic"),
        "filament_type": _arr(material or "PLA"),
        "filament_diameter": _arr(diameter or 1.75),
        "compatible_printers": [compatible_printer] if compatible_printer else [],
    }
    if filament_id:
        j["filament_id"] = _arr(filament_id)
    if color_hex:
        j["default_filament_colour"] = _arr("#" + str(color_hex).lstrip("#")[:6])
    if nozzle_temp is not None:
        j["nozzle_temperature"] = _arr(nozzle_temp)
        j["nozzle_temperature_initial_layer"] = _arr(nozzle_temp)
    if bed_temp is not None:
        j["hot_plate_temp"] = _arr(bed_temp)
    if flow_ratio is not None:
        j["filament_flow_ratio"] = _arr(flow_ratio)
    if density is not None:
        j["filament_density"] = _arr(density)
    if max_vol_speed is not None:
        j["filament_max_volumetric_speed"] = _arr(max_vol_speed)
    return j


def from_catalog_entry(e: dict) -> dict[str, Any]:
    """Build a preset from a build_catalog.py / catalog.json entry."""
    return generate(
        vendor=e.get("vendor", ""), material=e.get("type", "PLA"),
        name=e.get("name", ""), color_hex=e.get("color_hex", ""),
        nozzle_temp=e.get("nozzle_temp") or None, bed_temp=e.get("bed_temp") or None,
        flow_ratio=e.get("flow_ratio") or None, density=e.get("density") or None,
        diameter=float(e.get("diameter") or 1.75),
        max_vol_speed=e.get("max_vol_speed") or None, filament_id=e.get("filament_id", ""),
    )
