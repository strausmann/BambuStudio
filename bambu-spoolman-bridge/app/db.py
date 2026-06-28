"""SQLite persistence (see concept doc §7).

Single connection guarded by a lock — the bridge is low-throughput (a handful
of MQTT events per minute), so a global lock is plenty and keeps things simple.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS spool_map (
    tag_uid        TEXT PRIMARY KEY,
    spoolman_id    INTEGER NOT NULL,
    filament_hint  TEXT,
    created_at     TEXT,
    last_seen_at   TEXT
);
CREATE TABLE IF NOT EXISTS slot_state (
    device_serial  TEXT, ams_id INTEGER, tray_id INTEGER,
    tag_uid        TEXT, last_remain INTEGER, updated_at TEXT,
    PRIMARY KEY (device_serial, ams_id, tray_id)
);
CREATE TABLE IF NOT EXISTS job_log (
    job_id TEXT PRIMARY KEY, tag_uid TEXT, used_g REAL, booked_at TEXT
);
CREATE TABLE IF NOT EXISTS tag_registry (
    tag_uid        TEXT PRIMARY KEY,
    state          TEXT NOT NULL,          -- bambu_original | freed | reassigned
    current_spool  INTEGER,
    tag_class      TEXT,                   -- bambu_readonly | custom_ndef
    meta_material  TEXT,
    meta_color     TEXT,
    meta_temp_min  INTEGER, meta_temp_max INTEGER,
    meta_full_g    REAL,
    origin         TEXT,
    freed_at       TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tag_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_uid TEXT, spoolman_id INTEGER,
    action TEXT, note TEXT, at TEXT
);
CREATE TABLE IF NOT EXISTS spool_home (
    spool_id      INTEGER PRIMARY KEY,
    home_location TEXT,                  -- any prior Spoolman location string to restore on unload
    is_loaded     INTEGER DEFAULT 0,
    updated_at    TEXT
);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Database:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---- spool_map --------------------------------------------------------
    def get_spool_by_tag(self, tag_uid: str) -> int | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT spoolman_id FROM spool_map WHERE tag_uid=?", (tag_uid,)
            ).fetchone()
        return row["spoolman_id"] if row else None

    def bind_tag(self, tag_uid: str, spoolman_id: int, hint: str = "") -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO spool_map(tag_uid, spoolman_id, filament_hint, created_at, last_seen_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(tag_uid) DO UPDATE SET spoolman_id=excluded.spoolman_id,
                       filament_hint=excluded.filament_hint, last_seen_at=excluded.last_seen_at""",
                (tag_uid, spoolman_id, hint, _now(), _now()),
            )
            self._conn.commit()

    def touch_tag(self, tag_uid: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE spool_map SET last_seen_at=? WHERE tag_uid=?", (_now(), tag_uid)
            )
            self._conn.commit()

    # ---- slot_state -------------------------------------------------------
    def upsert_slot(self, serial: str, ams_id: int, tray_id: int, tag_uid: str, remain: int) -> str | None:
        """Returns the previously-seen tag_uid for this slot if it changed."""
        with self._lock:
            prev = self._conn.execute(
                "SELECT tag_uid FROM slot_state WHERE device_serial=? AND ams_id=? AND tray_id=?",
                (serial, ams_id, tray_id),
            ).fetchone()
            prev_tag = prev["tag_uid"] if prev else None
            self._conn.execute(
                """INSERT INTO slot_state(device_serial, ams_id, tray_id, tag_uid, last_remain, updated_at)
                   VALUES(?,?,?,?,?,?)
                   ON CONFLICT(device_serial, ams_id, tray_id) DO UPDATE SET
                       tag_uid=excluded.tag_uid, last_remain=excluded.last_remain, updated_at=excluded.updated_at""",
                (serial, ams_id, tray_id, tag_uid, remain, _now()),
            )
            self._conn.commit()
        return prev_tag if prev_tag and prev_tag != tag_uid else None

    # ---- tag_registry -----------------------------------------------------
    def upsert_tag(self, tag_uid: str, **fields: Any) -> None:
        cols = {k: v for k, v in fields.items() if v is not None}
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM tag_registry WHERE tag_uid=?", (tag_uid,)
            ).fetchone()
            if exists:
                if cols:
                    sets = ", ".join(f"{k}=?" for k in cols)
                    self._conn.execute(
                        f"UPDATE tag_registry SET {sets}, updated_at=? WHERE tag_uid=?",
                        (*cols.values(), _now(), tag_uid),
                    )
            else:
                cols.setdefault("state", "bambu_original")
                keys = ["tag_uid", *cols.keys(), "updated_at"]
                vals = [tag_uid, *cols.values(), _now()]
                ph = ",".join("?" * len(keys))
                self._conn.execute(
                    f"INSERT INTO tag_registry({','.join(keys)}) VALUES({ph})", vals
                )
            self._conn.commit()

    def get_tag(self, tag_uid: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tag_registry WHERE tag_uid=?", (tag_uid,)
            ).fetchone()
        return dict(row) if row else None

    def list_tags(self, state: str | None = None) -> list[dict]:
        q = "SELECT * FROM tag_registry"
        args: tuple = ()
        if state:
            q += " WHERE state=?"
            args = (state,)
        with self._lock:
            rows = self._conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def add_history(self, tag_uid: str, spoolman_id: int | None, action: str, note: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO tag_history(tag_uid, spoolman_id, action, note, at) VALUES(?,?,?,?,?)",
                (tag_uid, spoolman_id, action, note, _now()),
            )
            self._conn.commit()

    # ---- spool_home (previous/home location, concept §5.3) ----------------
    def mark_loaded(self, spool_id: int, home_location: str) -> None:
        """Record the spool's home location the first time it enters an AMS.
        No-op if already loaded (so we don't overwrite the home with the slot)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT is_loaded FROM spool_home WHERE spool_id=?", (spool_id,)
            ).fetchone()
            if row and row["is_loaded"]:
                return
            self._conn.execute(
                """INSERT INTO spool_home(spool_id, home_location, is_loaded, updated_at)
                   VALUES(?,?,1,?)
                   ON CONFLICT(spool_id) DO UPDATE SET home_location=excluded.home_location,
                       is_loaded=1, updated_at=excluded.updated_at""",
                (spool_id, home_location, _now()),
            )
            self._conn.commit()

    def mark_unloaded(self, spool_id: int) -> str | None:
        """Clear the loaded flag and return the stored home location."""
        with self._lock:
            row = self._conn.execute(
                "SELECT home_location FROM spool_home WHERE spool_id=?", (spool_id,)
            ).fetchone()
            home = row["home_location"] if row else None
            self._conn.execute(
                "UPDATE spool_home SET is_loaded=0, updated_at=? WHERE spool_id=?",
                (_now(), spool_id),
            )
            self._conn.commit()
        return home

    # ---- job_log ----------------------------------------------------------
    def job_booked(self, job_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM job_log WHERE job_id=?", (job_id,)
            ).fetchone()
        return row is not None

    def log_job(self, job_id: str, tag_uid: str, used_g: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO job_log(job_id, tag_uid, used_g, booked_at) VALUES(?,?,?,?)",
                (job_id, tag_uid, used_g, _now()),
            )
            self._conn.commit()
