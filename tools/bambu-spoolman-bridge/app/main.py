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

from .cloud_library import (
    CloudLibraryImporter,
    api_host_for,
    fetch_cloud_filaments,
    load_from_file,
    DEFAULT_ENDPOINT,
)
from .config import DEFAULT_DB_PATH, load_config
from .consumption import ConsumptionEngine
from .db import Database
from .jobs import JobTracker
from .labels import LabelClient
from .models import Tray, density_for, material_family
from .mqtt_ingest import BambuPrinterMQTT, tcp_reachable
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
        self.jobs = JobTracker(self)
        self.cloud_importer = CloudLibraryImporter(self.spoolman, self.db)
        self.cloud_cfg = self.cfg.get("cloud_library", {})
        self.public_url = self.cfg.get("spoolman_public_url", sm.get("base_url", "")).rstrip("/")
        self.label_on_onboard = bool(lp.get("print_on_onboard", False))

        onb = self.cfg.get("onboard", {})
        self.auto_create = bool(onb.get("auto_create", False))   # auto-create sort+spool on unknown tag
        self.default_vendor = onb.get("default_vendor", "Bambu Lab")

        # live view of trays seen via MQTT, used by the job tracker
        self.live_trays: dict[tuple[str, int, int], Tray] = {}

        ams_cfg = self.cfg.get("ams", {})
        # alias map keyed by AMS serial number, e.g. {"AMSSN1234": "Werkstatt-links"}
        self.ams_aliases: dict[str, str] = ams_cfg.get("aliases", {}) or {}
        # where a spool's location is set when it leaves the AMS
        self.storage_location = ams_cfg.get("storage_location", "Lager")

        # in-memory onboarding queue: tag_uid -> tray snapshot
        self._pending: dict[str, dict[str, Any]] = {}
        # last cali_idx written per tag, so we only push on change
        self._last_cali: dict[str, int] = {}
        # AMS identity learned from get_version: (serial, ams_id) -> {type, sn}
        self.ams_identity: dict[tuple[str, int], dict[str, str]] = {}
        self._lock = threading.Lock()
        self._printers: list[BambuPrinterMQTT] = []

    # ---- MQTT handler -----------------------------------------------------
    def on_status(self, serial: str, print_obj: dict) -> None:
        try:
            self.jobs.on_status(serial, print_obj)
        except Exception:  # noqa: BLE001
            log.exception("on_status failed (%s)", serial)

    def on_tray(self, tray: Tray) -> None:
        try:
            if tray.has_rfid:
                self.live_trays[(tray.printer_serial, tray.ams_id, tray.tray_id)] = tray
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
            if self.auto_create:
                try:
                    self.auto_create_from_tray(tray)
                    return
                except Exception:  # noqa: BLE001
                    log.exception("auto-create failed for %s", tray.tag_uid)
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
        # Track the printer's PA/k calibration: cali_idx links to the printer's PA
        # table; the actual k/n come straight from the tray push_status (concept §8.1).
        k = round(tray.k, 4) if tray.k > 0 else None
        sig = (tray.cali_idx, k)
        if sig != self._last_cali.get(tray.tag_uid):
            self._last_cali[tray.tag_uid] = sig
            extra: dict[str, Any] = {"cali_idx": tray.cali_idx,
                                     "calibrated": (tray.cali_idx >= 0 or (k or 0) > 0)}
            if k:
                extra["k_value"] = k
            if tray.n > 0:
                extra["n_coef"] = round(tray.n, 4)
            try:
                self.spoolman.set_extra(spool_id, **extra)
            except Exception:  # noqa: BLE001
                log.exception("set k/cali failed for spool %s", spool_id)

        self.consumption.reconcile_remaining(spool_id, tray, spool=spool)

    def _clear_slot_for_tag(self, tag_uid: str) -> None:
        spool_id = self.db.get_spool_by_tag(tag_uid)
        if spool_id is not None:
            try:
                home = self.db.mark_unloaded(spool_id)
                self.spoolman.set_active_tray(spool_id, None)
                # Restore whatever location the spool had before (any Spoolman location
                # string, e.g. a Hangar code if Hangar is used), fall back to storage default.
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

    # ---- auto-create (concept §4.1.1) ------------------------------------
    def auto_create_by_tag(self, tag_uid: str) -> int:
        """API entry: locate the (live or pending) tray for a tag and auto-create."""
        tray = None
        for (_s, _a, _t), t in self.live_trays.items():
            if t.tag_uid == tag_uid:
                tray = t
                break
        if tray is None:
            with self._lock:
                snap = self._pending.get(tag_uid)
            if not snap:
                raise KeyError(tag_uid)
            tray = Tray(
                printer_serial="", ams_id=-1, tray_id=-1, tag_uid=tag_uid,
                setting_id=snap.get("setting_id", ""), material=snap.get("material", ""),
                color=snap.get("color", ""), tray_weight=float(snap.get("tray_weight", 0) or 0),
            )
        return self.auto_create_from_tray(tray)

    def auto_create_from_tray(self, tray: Tray) -> int:
        """Find-or-create the Spoolman filament (sort) from tray metadata, then
        create a spool for this physical roll and bind the tag. Returns spool_id."""
        material = material_family(tray.material) or tray.material or "PLA"
        vendor_id = self.spoolman.find_or_create_vendor(self.default_vendor)
        fil = self.spoolman.find_filament(material, tray.color, vendor_id)
        if fil is None:
            variant = tray.material if tray.material and tray.material != material else ""
            name = " ".join(p for p in [self.default_vendor, variant or material] if p).strip()
            fil = self.spoolman.create_filament(
                name=name, material=material, color_hex=tray.color,
                weight=tray.tray_weight or 1000.0, diameter=tray.diameter or 1.75,
                density=density_for(tray.material), vendor_id=vendor_id,
                extra={"filament_id": tray.setting_id, "type": tray.material} if tray.setting_id else None,
            )
            log.info("auto-created filament '%s' (%s)", name, fil.get("id"))
        spool = self.spoolman.create_spool(
            filament_id=fil["id"],
            initial_weight=tray.tray_weight or 1000.0,
            tag_uid=tray.tag_uid,
        )
        spool_id = spool["id"]
        self.db.bind_tag(tray.tag_uid, spool_id, hint="auto")
        self.db.upsert_tag(tray.tag_uid, state="bambu_original", current_spool=spool_id)
        self.db.add_history(tray.tag_uid, spool_id, "assign", note="auto-create")
        with self._lock:
            self._pending.pop(tray.tag_uid, None)
        if self.label_on_onboard:
            self._maybe_print_label(spool_id)
        log.info("auto-created spool #%s for tag %s", spool_id, tray.tag_uid)
        return spool_id

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
        acct = self.cfg.get("bambu_account", {})
        region = acct.get("region", "eu")
        token = acct.get("token", "")
        cloud_user = acct.get("username", "")
        for p in self.cfg.get("printers", []):
            client = self._make_client(p, region, token, cloud_user)
            if client is None:
                continue
            client.start()
            self._printers.append(client)
            log.info("started %s MQTT for %s (%s)", client.label, p.get("name"), p["serial"])

    def _make_client(self, p: dict, region: str, token: str, cloud_user: str):
        serial = p["serial"]
        lan = p.get("lan", {})
        transport = p.get("transport", "auto")
        cb = dict(on_tray=self.on_tray, on_version=self.on_version, on_status=self.on_status)

        want_lan = bool(lan.get("host")) and transport in ("auto", "lan")
        # In auto, prefer LAN only if it's actually reachable; otherwise fall back to cloud.
        if want_lan and transport == "auto" and not tcp_reachable(lan["host"], 8883):
            log.warning("[%s] LAN %s unreachable; trying cloud fallback", serial, lan["host"])
            want_lan = False

        if want_lan:
            return BambuPrinterMQTT.for_lan(serial, lan["host"], lan.get("access_code", ""), **cb)
        if token and transport in ("auto", "cloud"):
            return BambuPrinterMQTT.for_cloud(serial, region, token, username=cloud_user, **cb)
        if transport == "lan" and lan.get("host"):
            return BambuPrinterMQTT.for_lan(serial, lan["host"], lan.get("access_code", ""), **cb)
        log.warning("printer %s: no usable transport (need lan.host or bambu_account.token)", p.get("name"))
        return None

    def run_cloud_import(self, source: str = "live", path: str = "", dry_run: bool = True) -> dict[str, Any]:
        """Import the cloud filament library into Spoolman (concept §6).
        source='file' reads a saved capture (path); source='live' calls the cloud REST."""
        if source == "file":
            if not path:
                raise ValueError("source=file requires a path")
            records = load_from_file(path)
        else:
            acct = self.cfg.get("bambu_account", {})
            token = acct.get("token", "")
            if not token:
                raise ValueError("live import needs bambu_account.token")
            host = api_host_for(acct.get("region", "eu"), self.cloud_cfg.get("api_host", ""))
            endpoint = self.cloud_cfg.get("endpoint", DEFAULT_ENDPOINT)
            records = fetch_cloud_filaments(host, endpoint, token, int(self.cloud_cfg.get("limit", 200)))
        log.info("cloud import: %d records (source=%s, dry_run=%s)", len(records), source, dry_run)
        return self.cloud_importer.import_records(records, dry_run=dry_run)

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


class CloudImportReq(BaseModel):
    source: str = "live"      # live | file
    path: str = ""
    dry_run: bool = True


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


@app.post("/api/cloud/import")
def api_cloud_import(req: CloudImportReq) -> dict[str, Any]:
    try:
        return bridge.run_cloud_import(req.source, req.path, req.dry_run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"cloud import failed: {e}")


@app.post("/api/onboard_auto")
def api_onboard_auto(req: TagReq) -> dict[str, Any]:
    try:
        spool_id = bridge.auto_create_by_tag(req.tag_uid)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown tag (no live/pending tray)")
    return {"status": "ok", "spool_id": spool_id}


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
