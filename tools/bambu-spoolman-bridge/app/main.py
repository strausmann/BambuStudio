"""FastAPI app: wires MQTT ingest -> Spoolman, exposes the onboarding API/PWA.

Prototype scaffold — see docs/bambu-spoolman-bridge-concept.md.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DEFAULT_DB_PATH, load_config
from .consumption import ConsumptionEngine
from .db import Database
from .labels import LabelClient
from .models import Tray
from .mqtt_ingest import BambuPrinterMQTT
from .spoolman import SpoolmanClient
from .tags import TagService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bridge")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class Bridge:
    """Holds shared services and the live state."""

    def __init__(self) -> None:
        self.cfg = load_config()
        self.db = Database(DEFAULT_DB_PATH)
        sm = self.cfg.get("spoolman", {})
        self.spoolman = SpoolmanClient(
            sm.get("base_url", "http://spoolman:7912"),
            tag_field=sm.get("tag_field", "tag"),
            slot_field=sm.get("slot_field", "active_tray"),
        )
        lp = self.cfg.get("label_printer", {})
        self.labels = LabelClient(
            lp.get("base_url", "http://label-hub:8090"),
            lp.get("template_id", "spool-qr-12mm"),
            enabled=bool(lp.get("enabled", False)),
        )
        cons = self.cfg.get("consumption", {})
        self.consumption = ConsumptionEngine(
            self.db, self.spoolman,
            mode=cons.get("mode", "combined"),
            reconcile_threshold_pct=float(cons.get("reconcile_threshold_pct", 3)),
        )
        self.tags = TagService(self.db)
        self.public_url = self.cfg.get("spoolman_public_url", sm.get("base_url", "")).rstrip("/")
        self.label_on_onboard = bool(lp.get("print_on_onboard", False))

        ams_cfg = self.cfg.get("ams", {})
        # alias map keyed by AMS serial number, e.g. {"AMSSN1234": "Werkstatt-links"}
        self.ams_aliases: dict[str, str] = ams_cfg.get("aliases", {}) or {}
        # where a spool's location is set when it leaves the AMS
        self.storage_location = ams_cfg.get("storage_location", "Lager")

        # in-memory onboarding queue: tag_uid -> tray snapshot
        self._pending: dict[str, dict[str, Any]] = {}
        # AMS identity learned from get_version: (serial, ams_id) -> {type, sn}
        self.ams_identity: dict[tuple[str, int], dict[str, str]] = {}
        self._lock = threading.Lock()
        self._printers: list[BambuPrinterMQTT] = []

    # ---- MQTT handler -----------------------------------------------------
    def on_tray(self, tray: Tray) -> None:
        try:
            self._handle_tray(tray)
        except Exception:  # noqa: BLE001
            log.exception("on_tray failed (%s ams%s tray%s)", tray.printer_serial, tray.ams_id, tray.tray_id)

    def on_version(self, serial: str, modules: list[dict]) -> None:
        with self._lock:
            for m in modules:
                ams_id = m.get("ams_id")
                if isinstance(ams_id, int):
                    self.ams_identity[(serial, ams_id)] = {"type": m.get("type", "AMS"), "sn": m.get("sn", "")}
        if modules:
            log.info("[%s] AMS modules: %s", serial, modules)

    def _ams_name(self, tray: Tray) -> str:
        """Human-friendly AMS name: config alias > 'Type (SNxxxx)' > 'AMS<id>'."""
        ident = self.ams_identity.get((tray.printer_serial, tray.ams_id))
        if ident:
            sn = ident.get("sn", "")
            if sn and sn in self.ams_aliases:
                return self.ams_aliases[sn]
            if sn:
                return f"{ident['type']} ({sn[-4:]})"
            return ident["type"]
        return f"AMS{tray.ams_id}"

    def _slot_str(self, tray: Tray) -> str:
        # 1-based slot number for humans (Bambu UI shows slots 1..4).
        return f"{self._ams_name(tray)}/Slot{tray.tray_id + 1}"

    def _handle_tray(self, tray: Tray) -> None:
        if tray.is_empty:
            return
        if not tray.has_rfid:
            return  # non-RFID / third-party without tag -> manual assign in UI (TODO)

        self.tags.register_seen(tray)
        prev_tag = self.db.upsert_slot(
            tray.printer_serial, tray.ams_id, tray.tray_id, tray.tag_uid, tray.remain
        )
        if prev_tag:
            self._clear_slot_for_tag(prev_tag)

        spool_id = self.db.get_spool_by_tag(tray.tag_uid)
        if spool_id is None:
            with self._lock:
                self._pending[tray.tag_uid] = self._tray_snapshot(tray)
            log.info("unknown tag %s -> onboarding pending", tray.tag_uid)
            return

        self.db.touch_tag(tray.tag_uid)
        slot = self._slot_str(tray)
        spool = None
        try:
            spool = self.spoolman.get_spool(spool_id)
            # Remember where the spool lived before entering the AMS, so we can
            # restore that exact location on unload (concept §5.3).
            self.db.mark_loaded(spool_id, spool.get("location") or "")
            self.spoolman.set_active_tray(spool_id, slot)          # OpenSpoolMan-compat extra
            self.spoolman.set_location(spool_id, slot)             # Spoolman native location (Lagerort)
        except Exception:  # noqa: BLE001
            log.exception("set location failed for spool %s", spool_id)
        self.consumption.reconcile_remaining(spool_id, tray, spool=spool)

    def _clear_slot_for_tag(self, tag_uid: str) -> None:
        spool_id = self.db.get_spool_by_tag(tag_uid)
        if spool_id is not None:
            try:
                home = self.db.mark_unloaded(spool_id)
                self.spoolman.set_active_tray(spool_id, None)
                # Restore the previous location (Hangar code), fall back to storage default.
                self.spoolman.set_location(spool_id, home or self.storage_location)
            except Exception:  # noqa: BLE001
                log.exception("clear slot/location failed for spool %s", spool_id)

    def _tray_snapshot(self, tray: Tray) -> dict[str, Any]:
        return {
            "tag_uid": tray.tag_uid,
            "slot": self._slot_str(tray),
            "material": tray.material,
            "color": tray.color,
            "setting_id": tray.setting_id,
            "sub_brands": tray.sub_brands,
            "remain": tray.remain,
            "tray_weight": tray.tray_weight,
        }

    # ---- actions used by the API -----------------------------------------
    def bind(self, tag_uid: str, spool_id: int) -> None:
        self.db.bind_tag(tag_uid, spool_id, hint="bind")
        self.db.upsert_tag(tag_uid, state="bambu_original", current_spool=spool_id)
        self.db.add_history(tag_uid, spool_id, "assign")
        with self._lock:
            self._pending.pop(tag_uid, None)
        if self.label_on_onboard:
            self._maybe_print_label(spool_id)

    def _maybe_print_label(self, spool_id: int) -> None:
        try:
            spool = self.spoolman.get_spool(spool_id)
            fil = spool.get("filament", {})
            name = fil.get("name") or fil.get("material") or f"Spool {spool_id}"
            self.labels.print_spool_label(
                title=name,
                primary_id=str(spool.get("_extra", {}).get(self.spoolman.tag_field, "")),
                qr_payload=f"{self.public_url}/spool/{spool_id}",
                secondary=[fil.get("material", ""), f"{fil.get('weight', '')} g"],
            )
        except Exception:  # noqa: BLE001
            log.exception("label print failed for spool %s", spool_id)

    def start(self) -> None:
        for p in self.cfg.get("printers", []):
            lan = p.get("lan", {})
            if not lan.get("host"):
                log.warning("printer %s has no lan.host; cloud transport is TODO", p.get("name"))
                continue
            client = BambuPrinterMQTT(
                serial=p["serial"], host=lan["host"], access_code=lan.get("access_code", ""),
                on_tray=self.on_tray, on_version=self.on_version,
            )
            client.start()
            self._printers.append(client)
            log.info("started MQTT for %s (%s)", p.get("name"), p["serial"])

    @property
    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._pending.values())


bridge = Bridge()
app = FastAPI(title="Bambu↔Spoolman Bridge")


@app.on_event("startup")
def _startup() -> None:
    bridge.start()


# ---- API models ----------------------------------------------------------
class BindReq(BaseModel):
    tag_uid: str
    spool_id: int


class ReassignReq(BaseModel):
    tag_uid: str
    spool_id: int
    spool_material: str


class TagReq(BaseModel):
    tag_uid: str


# ---- routes --------------------------------------------------------------
@app.get("/api/state")
def api_state() -> dict[str, Any]:
    with bridge._lock:
        ams = [{"printer": k[0], "ams_id": k[1], **v} for k, v in bridge.ams_identity.items()]
    return {
        "pending": bridge.pending,
        "free_tags": bridge.db.list_tags("freed"),
        "all_tags": bridge.db.list_tags(),
        "ams": ams,
    }


@app.get("/api/spools")
def api_spools() -> list[dict]:
    return bridge.spoolman.list_spools()


@app.get("/api/filaments")
def api_filaments() -> list[dict]:
    return bridge.spoolman.list_filaments()


@app.post("/api/bind")
def api_bind(req: BindReq) -> dict[str, str]:
    bridge.bind(req.tag_uid, req.spool_id)
    return {"status": "ok"}


@app.post("/api/free")
def api_free(req: TagReq) -> dict[str, str]:
    bridge.tags.free_tag(req.tag_uid)
    return {"status": "ok"}


@app.post("/api/reassign")
def api_reassign(req: ReassignReq) -> dict[str, str]:
    ok, msg = bridge.tags.reassign(req.tag_uid, req.spool_id, req.spool_material)
    if not ok:
        raise HTTPException(status_code=409, detail=msg)
    with bridge._lock:
        bridge._pending.pop(req.tag_uid, None)
    return {"status": "ok"}


@app.post("/api/label/{spool_id}")
def api_label(spool_id: int) -> dict[str, str]:
    bridge._maybe_print_label(spool_id)
    return {"status": "ok"}


# ---- static PWA ----------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
