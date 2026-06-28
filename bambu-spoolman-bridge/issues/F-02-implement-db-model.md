# F-02 — SQLite-Datenmodell + Migrationen implementieren

**Type:** feature · **Severity:** 🟠 high · **Area:** persistence · **Status:** open · **Refs:** docs/database-guideline.md, app/db.py

## Ziel
Das in der Database-Guideline definierte Modell sauber umsetzen (Tabellen, Indizes,
Migrationen, WAL), damit Bridge-State Neustarts übersteht (vgl. BR-03).

## Aufgaben
- [ ] Schema-Version-Tabelle + idempotente Migrationen (`schema_version`)
- [ ] Tabellen: `spool_map`, `slot_state`, `tag_registry`, `tag_history`, `spool_home`, `job_log`
- [ ] Indizes je Guideline; `PRAGMA journal_mode=WAL`, `foreign_keys=ON`
- [ ] Repository-Layer (CRUD) statt Streufunktionen
- [ ] State beim Start aus DB rehydrieren

## Akzeptanzkriterien
- [ ] Frischer Start legt DB an; zweiter Start migriert nicht erneut
- [ ] Slot-/Spool-Zustand überlebt Neustart
- [ ] Unit-Tests für Migrationen + Repository
