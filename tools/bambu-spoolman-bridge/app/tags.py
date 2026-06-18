"""Tag lifecycle helpers (concept §5.4).

Compatibility guard: a Bambu read-only tag keeps its encoded material, so it
may only be reused on a same-material spool (no Developer Mode here -> no slot
override, see §5.5). Color is a warning, material is a hard rule.
"""
from __future__ import annotations

from .db import Database
from .models import material_family


def compatible(tag_material: str, spool_material: str) -> bool:
    return material_family(tag_material) == material_family(spool_material)


class TagService:
    def __init__(self, db: Database):
        self.db = db

    def register_seen(self, tag) -> None:
        """Record/refresh a Bambu tag's encoded metadata when seen in the AMS."""
        self.db.upsert_tag(
            tag.tag_uid,
            tag_class="bambu_readonly",
            meta_material=tag.material,
            meta_color=tag.color,
            meta_temp_min=tag.nozzle_temp_min or None,
            meta_temp_max=tag.nozzle_temp_max or None,
            meta_full_g=tag.tray_weight or None,
            origin=tag.setting_id or None,
        )

    def free_tag(self, tag_uid: str) -> None:
        self.db.upsert_tag(tag_uid, state="freed", current_spool=None)
        self.db.add_history(tag_uid, None, "free")

    def reassign(self, tag_uid: str, spoolman_id: int, spool_material: str) -> tuple[bool, str]:
        """Returns (ok, message). Enforces material compatibility."""
        tag = self.db.get_tag(tag_uid)
        tag_material = (tag or {}).get("meta_material", "")
        if tag and tag.get("tag_class") == "bambu_readonly" and tag_material:
            if not compatible(tag_material, spool_material):
                return False, (
                    f"Incompatible: tag is {tag_material!r}, spool is {spool_material!r}. "
                    "Without Developer Mode the printer would use the tag's material."
                )
        self.db.upsert_tag(tag_uid, state="reassigned", current_spool=spoolman_id)
        self.db.bind_tag(tag_uid, spoolman_id, hint="reassigned")
        self.db.add_history(tag_uid, spoolman_id, "reassign", note=f"-> {spool_material}")
        return True, "ok"
