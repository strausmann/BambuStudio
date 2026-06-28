# Datenbank-Guideline & Modell — Bridge (SQLite)

> Verbindliches Datenmodell + Konventionen für die SQLite-DB der Bridge. Quelle der Wahrheit für
> Tabellen, Keys, Typen, Migrationen. Ergänzt die API-Guideline (`docs/api-guideline.md`).
> Ziel u. a.: die im Review bemängelte **flüchtige In-Memory-State** (Onboarding-Queue,
> Slot-Staging, AMS-Identität) **persistent** machen.

## 1. Prinzipien

- **Eine Datei:** `<data_dir>/state.db` (Env `BRIDGE_DB`, Default `data/state.db`).
- **WAL-Modus** (`PRAGMA journal_mode=WAL`) + `PRAGMA foreign_keys=ON` beim Connect.
- **Nebenläufigkeit:** ein Prozess, MQTT-Thread + FastAPI-Threadpool. Zugriff **serialisiert**
  (eine Connection `check_same_thread=False` + globaler Lock **oder** Connection-per-Thread).
  Kurze Transaktionen; keine langen Reads unter Lock.
- **Schema-Versionierung:** `PRAGMA user_version`; Migrationen in `app/db.py` als nummerierte
  Schritte (idempotent, additiv; `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ADD COLUMN`).
- **Konventionen:** `snake_case`; Zeitstempel **ISO-8601 UTC** (TEXT); Geld/Gewicht REAL (Gramm);
  IDs gemäß API-Glossar (`spool_id` INTEGER, `tag_uid`/`serial`/`filament_id` TEXT).
- **Idempotenz:** Upserts via `INSERT … ON CONFLICT … DO UPDATE`; Logs via `INSERT OR IGNORE`.
- **Keine Geheimnisse** in der DB (keine Tokens/Cookies). Tokens nur aus Config/Env.

## 2. Tabellen — Bestand (bereits in `app/db.py`)

```sql
spool_map(   tag_uid TEXT PK, spoolman_id INTEGER NOT NULL, filament_hint TEXT,
             created_at TEXT, last_seen_at TEXT )
tag_registry(tag_uid TEXT PK, state TEXT, current_spool INTEGER, tag_class TEXT,
             meta_material TEXT, meta_color TEXT, meta_temp_min INT, meta_temp_max INT,
             meta_full_g REAL, origin TEXT, freed_at TEXT, updated_at TEXT )
tag_history( id INTEGER PK, tag_uid TEXT, spoolman_id INTEGER, action TEXT, note TEXT, at TEXT )
slot_state(  device_serial TEXT, ams_id INT, tray_id INT, tag_uid TEXT, last_remain INT,
             updated_at TEXT, PRIMARY KEY(device_serial, ams_id, tray_id) )
spool_home(  spool_id INTEGER PK, home_location TEXT, is_loaded INT, updated_at TEXT )
job_log(     job_id TEXT PK, tag_uid TEXT, used_g REAL, booked_at TEXT )
```

## 3. Tabellen — NEU (Persistenz des bisherigen In-Memory-State)

```sql
-- offene RFID-Onboardings (ersetzt Bridge._pending)
onboarding_pending(
    tag_uid TEXT PRIMARY KEY, serial TEXT, ams_id INT, tray_id INT,
    material TEXT, color TEXT, setting_id TEXT, remain INT, tray_weight REAL, seen_at TEXT )

-- ESP32 Bind-Flow: vorgemerkte Zuweisung Slot -> Spule (ersetzt Bridge._pending_assign)
slot_assign(
    serial TEXT, ams_id INT, tray_id INT, spool_id INTEGER, staged_by TEXT, created_at TEXT,
    PRIMARY KEY(serial, ams_id, tray_id) )

-- AMS-Identität aus get_version (ersetzt Bridge.ams_identity-Cache)
ams_identity(
    serial TEXT, ams_id INT, type TEXT, sn TEXT, updated_at TEXT,
    PRIMARY KEY(serial, ams_id) )

-- k-Katalog (Migration der bisherigen data/k_catalog.json)
kcatalog(
    vendor TEXT, material TEXT, nozzle TEXT, k REAL, n REAL, samples INT, updated_at TEXT,
    PRIMARY KEY(vendor, material, nozzle) )

-- Schlüssel/Wert für Sonstiges (z. B. zuletzt geladene SpoolmanDB-Etag, gestagter Slot je Session)
kv( key TEXT PRIMARY KEY, value TEXT, updated_at TEXT )
```
- **`_staged_slot`** (aktuell ein globaler Wert) wird **session-/clientbezogen** in `kv`
  (`staged_slot:<session>`) abgelegt — behebt das „global überschreibt sich"-Problem aus dem Review.
- **`live_trays`/`_last_cali`** bleiben bewusst **flüchtig** (reiner Laufzeit-Cache; nach Reconnect
  via `pushall` neu befüllt) — müssen **nicht** persistiert werden.

## 4. Beziehungen (logisch)

```
tag_registry.tag_uid ─1:1─ spool_map.tag_uid ─→ spoolman_id (extern in Spoolman)
spool_map.spoolman_id ─1:1─ spool_home.spool_id
slot_state(serial,ams,tray) ─→ tag_uid ─→ spool_map
onboarding_pending.tag_uid / slot_assign(serial,ams,tray): transiente Workflows
ams_identity(serial,ams) ─→ benennt Slots (active_tray)
kcatalog(vendor,material,nozzle): unabhängig (Kalibrier-Wissen)
```
Spoolman bleibt das **System of Record** für die eigentlichen Spulen-/Filamentdaten; die Bridge-DB
hält **Mappings + Workflow-State + Cache + Kalibrier-Katalog**.

## 5. Migrationen

- `PRAGMA user_version` als Versionszähler. Beim Start: `_migrate()` führt fehlende Schritte aus.
- Schritte additiv & idempotent. Beispiel-Reihenfolge:
  1. (v1) Bestands-Tabellen (§2)
  2. (v2) `onboarding_pending`, `slot_assign`, `ams_identity`, `kv`
  3. (v3) `kcatalog` + Einmal-Import aus `data/k_catalog.json` (falls vorhanden)
- Kein destruktives `DROP` ohne explizite Migration + Backup-Hinweis.

## 6. Offen / nächste Schritte (siehe Tracking)

- [ ] `app/db.py` um §3-Tabellen + `_migrate()`/`user_version` erweitern.
- [ ] `Bridge._pending` → `onboarding_pending`; `_pending_assign` → `slot_assign`;
      `ams_identity` → Tabelle; `_staged_slot` → `kv` (session-keyed).
- [ ] `kcatalog.py` von JSON auf die Tabelle umstellen (mit Einmal-Migration).
- [ ] WAL aktivieren; Lock-Strategie gemäß §1 durchziehen (Review-Finding: ungelockte Dicts).
