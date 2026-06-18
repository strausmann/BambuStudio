"""Per-job consumption tracking (concept §5.2).

Detects print start/end from MQTT gcode_state and computes how many grams the
active tray consumed during the job via the remain%% delta (more robust than a
slicer estimate, and uses data we already receive). In `combined` mode this is
recorded for history only — the absolute remain%% reconcile owns the spool's
remaining weight (so we never double-count). In `per_job` mode book_job()
subtracts it via Spoolman /use.

Assumptions to verify against a real printer:
- gcode_state values: PREPARE/RUNNING/PAUSE/FINISH/FAILED/IDLE
- active tray index: print.ams.tray_now, global index = ams_id*4 + slot
  (255/254 = external/none). See get_tray_id_by_ams_id_and_slot_id in
  src/slic3r/GUI/DeviceManager.cpp.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("bridge.jobs")

_END_STATES = {"FINISH", "FAILED", "IDLE"}


def _job_id(print_obj: dict) -> str:
    for k in ("subtask_id", "task_id", "job_id"):
        v = print_obj.get(k)
        if v:
            return str(v)
    return f"{print_obj.get('gcode_file', 'job')}@{int(time.time())}"


def map_tray_now(tray_now) -> tuple[int, int] | None:
    try:
        idx = int(tray_now)
    except (TypeError, ValueError):
        return None
    if idx < 0 or idx >= 128:  # 254/255 = external / none
        return None
    return idx // 4, idx % 4


class JobTracker:
    def __init__(self, bridge):
        self.bridge = bridge
        self._state: dict[str, dict] = {}  # serial -> {gcode_state, job_id, start_g:{tag:grams}}

    def on_status(self, serial: str, print_obj: dict) -> None:
        gs = print_obj.get("gcode_state")
        if gs is None:
            return
        st = self._state.setdefault(serial, {"gcode_state": None, "job_id": None, "start_g": {}})
        prev = st["gcode_state"]
        st["gcode_state"] = gs
        if gs == "RUNNING" and prev != "RUNNING":
            self._start(serial, print_obj, st)
        elif prev == "RUNNING" and gs in _END_STATES:
            self._end(serial, st)

    def _active_tray(self, serial: str, print_obj: dict):
        mapped = map_tray_now((print_obj.get("ams") or {}).get("tray_now"))
        if not mapped:
            return None
        ams_id, tray_id = mapped
        return self.bridge.live_trays.get((serial, ams_id, tray_id))

    def _start(self, serial: str, print_obj: dict, st: dict) -> None:
        st["job_id"] = _job_id(print_obj)
        st["start_g"] = {}
        tray = self._active_tray(serial, print_obj)
        if tray and tray.has_rfid:
            g = tray.remaining_grams()
            if g is not None:
                st["start_g"][tray.tag_uid] = g
        log.info("[%s] job %s started (active=%s)", serial, st["job_id"],
                 getattr(tray, "tag_uid", None))

    def _end(self, serial: str, st: dict) -> None:
        job_id = st.get("job_id")
        if not job_id:
            return
        for tag_uid, start_g in st.get("start_g", {}).items():
            tray = self._find_tray_by_tag(serial, tag_uid)
            end_g = tray.remaining_grams() if tray else None
            if end_g is None:
                continue
            used = start_g - end_g
            if used <= 0:
                continue
            spool_id = self.bridge.db.get_spool_by_tag(tag_uid)
            if spool_id is not None:
                self.bridge.consumption.book_job(spool_id, tag_uid, f"{job_id}:{tag_uid}", used)
        st["job_id"] = None
        st["start_g"] = {}

    def _find_tray_by_tag(self, serial: str, tag_uid: str):
        for (s, _a, _t), tray in self.bridge.live_trays.items():
            if s == serial and tray.tag_uid == tag_uid:
                return tray
        return None
