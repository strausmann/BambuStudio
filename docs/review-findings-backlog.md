# Review-Findings → Lösungen (Backlog / Issue-Ersatz)

> Aus dem Code- + Architektur-Review (zwei Entwickler-Agenten, Branch `claude/dazzling-sagan-vdro2v`).
> GitHub-Issues sind im Repo deaktiviert → dieser Backlog vertritt sie 1:1. Jede Zeile = ein
> „Issue" mit konkreter Lösung. Bezug: `docs/api-guideline.md`, `docs/database-guideline.md`,
> `docs/no-devmode-capability-matrix.md`.

Legende: 🔴 must-fix · 🟠 should-fix · 🟡 nice-to-have · Status: [ ] offen / [~] geplant / [x] erledigt

## 🔴 Kritisch

- **BR-1 [ ] Keine Auth auf druckersteuernder API.** Lösung: `X-API-Key`-Dependency (Guideline §8),
  Key aus `security.api_key`/`BRIDGE_API_KEY`, auf allen mutierenden Routen; Deployment-Profile
  HomeLab vs. Werkstatt. Default: ohne Key = Warnung + nur hinter Proxy.
- **BR-2 [ ] Ungelockter Cross-Thread-Zugriff** auf `live_trays`, `_last_cali`, `_pending_assign`,
  `_staged_slot`, `ams_identity` (MQTT-Thread vs. FastAPI-Threadpool → „dict changed size").
  Lösung: ein `state_lock` um **alle** Zugriffe; Iterationen über Kopien.
- **BR-3 [ ] In-Memory-State geht bei Neustart verloren** (`_pending`, `_pending_assign`,
  `_staged_slot`). Lösung: in SQLite persistieren — `onboarding_pending`, `slot_assign`, `kv`
  (DB-Guideline §3). `live_trays`/`_last_cali` bleiben flüchtig (Cache).
- **BR-4 [ ] `_staged_slot` global (ein Slot)** → Mehrnutzer/Retry überschreibt. Lösung:
  session-/clientbezogen in `kv` (`staged_slot:<session>`); RMW unter Lock.
- **BR-5 [ ] `bridge = Bridge()` beim Import** (braucht config.yaml, bricht uvicorn/Tests) +
  veraltetes `@app.on_event`. Lösung: Lazy-Init im **FastAPI `lifespan`**.
- **BR-6 [ ] Doku überzeichnet „implementiert"** für Cloud-Push/k-Set (hängt an unbestätigtem
  Endpoint / evtl. Dev-Mode). Lösung: in den Docs als „blockiert/gated, ungetestet" labeln
  (Capability-Matrix referenzieren).

## 🟠 Wichtig

- **BR-7 [ ] Spoolman zu „chatty"** (`find_spool_by_extra` = Full-Scan N+1; mehrere G/PUTs pro
  Tray-Push auch ohne Änderung). Lösung: Spoolman-Filter-Query bzw. einmal-Index; `active_tray`/
  `location` nur bei Änderung schreiben (wie `_last_cali`-Muster).
- **BR-8 [ ] `set_extra` GET-modify-PUT racy** (last-writer-wins auf gesamtes `extra`). Lösung:
  pro-Spool serialisieren; nur geänderte Keys schreiben.
- **BR-9 [ ] `tray_now`-Mapping** verfehlt Virtual-Tray (255) + 0x80-Bereich (Extern/2.-Extruder)
  → falsche Zuordnung. Lösung: Firmware-Ranges spiegeln (`DevExtruderSystem.cpp`); im Write-Pfad
  (`set_k`/`unload`) Virtual-Tray-Sonderfall beachten (`get_tray_id_by_ams_id_and_slot_id`).
- **BR-10 [ ] Job-Ende liest evtl. veraltetes `remain`** → Unterzählung. Lösung: bei Jobende
  `pushall` triggern bzw. auf den nächsten Tray-Push nach Ende buchen. „genau" → „remain-Delta-genau".
- **BR-11 [ ] MQTT-Schreibpfad ohne Verbindungsprüfung** (`publish_command` gibt trotzdem 200) +
  schwere Arbeit im MQTT-Callback (Keepalive-Risiko) + kein Watchdog/Token-Refresh. Lösung:
  `is_connected()`-Check → 503; Heavy-Work in Worker-Queue; Reconnect-Watchdog; Token-Ablauf
  (~3 Mon.) im UI/Log anzeigen.
- **BR-12 [ ] Importe ohne Idempotenz-Lock** (paralleler `cloud/import` → Duplikate). Lösung:
  Importe global serialisieren (Lock); Dedup über RFID/`cloud_id` beibehalten.
- **BR-13 [ ] `fetch_cloud_filaments` paginiert nicht** (nur erste Seite). Lösung: Offset-Schleife
  bis < `limit`.
- **BR-14 [ ] `material_family` naiv** (load-bearing für Kompatibilitätsschutz). Lösung: härten
  (Bekannte-Typen-Tabelle, CF/HT-Varianten, „Support for …" abfangen).

## 🟡 Nice-to-have

- **BR-15 [ ] `_last_cali`-Typannotation** falsch (`dict[str,int]` statt Tupel). Lösung: korrigieren.
- **BR-16 [ ] Leer-String-Extra `'""'`** statt Key löschen. Lösung: leere Extras entfernen.
- **BR-17 [ ] README ↔ Routen-Drift** (fehlende Routen, paho v1/v2-Latenz). Lösung: Routen-Tabelle
  aus echter Routenliste generieren; paho-Pin kommentieren.
- **BR-18 [ ] Tailwind Play-CDN** (offline unbrauchbar, Drittskript). Lösung: für Produktion
  Tailwind kompiliert ausliefern (Build-Stage).
- **BR-19 [ ] CORS** nicht gesetzt. Lösung: bei Cross-Origin explizit `allow_origins` (kein `*`).
- **BR-20 [ ] `get_version`-`ams_id` ↔ `print.ams.ams[].id`** Annahme. Lösung: am echten 2×-AMS
  verifizieren.

## Umsetzungs-Reihenfolge (ohne Drucker/Capture machbar zuerst)

1. **BR-5** (Lazy-Init/lifespan) — entsperrt sauberen Start/Tests.
2. **BR-1** (Auth) + **BR-2** (Locks) — Sicherheit/Stabilität.
3. **BR-3/BR-4** (State → SQLite, DB-Guideline) — Robustheit.
4. **BR-7/BR-8** (Spoolman-Schreiblast/Race).
5. **BR-6** (Doku-Ehrlichkeit) — laufend.
6. Drucker-/Capture-abhängig: **BR-9/BR-10/BR-11** (am echten 2×-AMS), Cloud-Endpoint/`put_setting`.
