"""Consumption engine (concept §5.2).

mode = combined: per-job subtraction is authoritative (TODO: needs reliable
job start/end + used-grams detection from MQTT), remain%% acts as a drift
reconcile. This scaffold implements the remain reconcile; per-job is stubbed.
"""
from __future__ import annotations

import logging

from .db import Database
from .models import Tray
from .spoolman import SpoolmanClient

log = logging.getLogger("bridge.consumption")


class ConsumptionEngine:
    def __init__(self, db: Database, spoolman: SpoolmanClient, mode: str = "combined",
                 reconcile_threshold_pct: float = 3.0):
        self.db = db
        self.spoolman = spoolman
        self.mode = mode
        self.threshold = reconcile_threshold_pct

    def reconcile_remaining(self, spool_id: int, tray: Tray, spool: dict | None = None) -> None:
        """Mirror Bambu's remain%% onto Spoolman when drift exceeds threshold.
        Pass an already-fetched `spool` to avoid a redundant GET."""
        if self.mode not in ("remain", "combined"):
            return
        target_g = tray.remaining_grams()
        if target_g is None:
            return
        if spool is None:
            try:
                spool = self.spoolman.get_spool(spool_id)
            except Exception:  # noqa: BLE001
                log.exception("reconcile: failed to read spool %s", spool_id)
                return
        current = spool.get("remaining_weight")
        full = spool.get("filament", {}).get("weight") or tray.tray_weight or 0
        if full <= 0:
            return
        drift_pct = abs((current or 0) - target_g) / full * 100.0
        if current is None or drift_pct >= self.threshold:
            log.info("reconcile spool %s: %.0fg -> %.0fg (drift %.1f%%)",
                     spool_id, current or -1, target_g, drift_pct)
            self.spoolman.set_remaining(spool_id, target_g)

    def book_job(self, spool_id: int, tag_uid: str, job_id: str, used_g: float) -> None:
        """Per-job subtraction with idempotency. TODO: wire to real job events."""
        if self.mode not in ("per_job", "combined"):
            return
        if self.db.job_booked(job_id):
            return
        try:
            self.spoolman.use_weight(spool_id, used_g)
            self.db.log_job(job_id, tag_uid, used_g)
            log.info("booked job %s: -%.0fg on spool %s", job_id, used_g, spool_id)
        except Exception:  # noqa: BLE001
            log.exception("book_job failed for %s", job_id)
