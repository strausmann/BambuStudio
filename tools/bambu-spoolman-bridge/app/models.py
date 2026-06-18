"""Shared data structures."""
from __future__ import annotations

from dataclasses import dataclass, field


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
