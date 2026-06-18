"""Shared data structures."""
from __future__ import annotations

from dataclasses import dataclass, field


# Bambu Filament Manager caps the filament name at 30 chars (observed in UI).
# Spoolman has no such limit, but names meant to round-trip into Bambu / the
# cloud library (concept §4.1.2, §6) must be truncated. The trailing "#<num>"
# is preserved because it is our human cross-reference.
BAMBU_FILAMENT_NAME_MAXLEN = 30


def fit_bambu_name(name: str, max_len: int = BAMBU_FILAMENT_NAME_MAXLEN) -> str:
    """Truncate to max_len while keeping a trailing ' #<num>' tag intact."""
    if len(name) <= max_len:
        return name
    import re

    m = re.search(r"\s*#\d+\s*$", name)
    if not m:
        return name[:max_len].rstrip()
    tag = m.group().strip()
    base = name[: m.start()].rstrip()
    keep = max_len - len(tag) - 1  # space before the tag
    if keep <= 0:
        return tag[:max_len]
    return f"{base[:keep].rstrip()} {tag}"


def is_valid_tag_uid(tag_uid: str | None) -> bool:
    """Mirror BambuStudio's FilamentSpool::is_valid_tag_uid: non-empty and not
    all zeros. Non-RFID / empty trays report "0" or a zero string."""
    if not tag_uid:
        return False
    return any(c != "0" for c in tag_uid)


@dataclass
class Tray:
    """One AMS tray slot as parsed from MQTT push_status."""

    printer_serial: str
    ams_id: int
    tray_id: int

    tag_uid: str = ""
    tray_uuid: str = ""
    setting_id: str = ""       # tray_info_idx, e.g. "GFL99"
    material: str = ""         # tray_type, e.g. "PLA"
    sub_brands: str = ""       # tray_sub_brands
    color: str = ""            # tray_color (hex)
    colors: list[str] = field(default_factory=list)
    remain: int = -1           # remaining percent (0-100), -1 = unknown
    tray_weight: float = 0.0   # nominal full weight (g)
    nozzle_temp_min: int = 0
    nozzle_temp_max: int = 0

    @property
    def has_rfid(self) -> bool:
        return is_valid_tag_uid(self.tag_uid)

    @property
    def is_empty(self) -> bool:
        return not self.setting_id and not self.has_rfid

    def remaining_grams(self) -> float | None:
        if self.remain < 0 or self.tray_weight <= 0:
            return None
        return self.tray_weight * (self.remain / 100.0)
