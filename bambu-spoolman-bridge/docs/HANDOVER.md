# Übergabe-Briefing — Bambu ↔ Spoolman Bridge (+ Preset-DB, ESP32, Cloud-RE)

> **Zweck dieses Dokuments:** vollständige Übergabe, um das Projekt in ein **eigenständiges
> GitHub-Repo** zu überführen und mit einer **Claude-Code-Instanz auf der Ubuntu-VM**
> weiterzuentwickeln. Es ist self-contained — die neue Instanz braucht keinen Chat-Verlauf.
>
> **Herkunft:** entwickelt im Fork `strausmann/BambuStudio` (AGPL-3.0), Branch
> `claude/dazzling-sagan-vdro2v`, unter `` + `docs/` + `analysis/`.

---

## 1. TL;DR — was ist das?

Ein selbst-gehosteter, Docker-basierter Dienst, der **Bambu-Lab-Drucker mit Spoolman verbindet**:
- liest **AMS-/RFID-/Verbrauchs-Telemetrie** per **LAN-MQTT** und pflegt Spoolman (Spule, Lagerort,
  Verbrauch, k/cali),
- **onboardet** Spulen (RFID-Bind / QR / NFC), inkl. **Tag-Wiederverwendung**,
- **legt Filamente** in Spoolman an (Online-DB **SpoolmanDB**) und **erzeugt Bambu-Presets**
  (fürs Drucker-Display),
- bereitet einen **ESP32-2432S028** Slot-Selektor und das **RE der Bambu-Cloud-Filament-API** vor.

**Kernentscheidung:** LAN-MQTT ist der verlässliche Kern; Cloud-REST ist optionale Anreicherung.
**Ohne Developer Mode** (Cloud bleibt aktiv) funktioniert der Kern vollständig — Drucker-*Schreib*-
Kommandos sind optional/gated (siehe `no-devmode-capability-matrix.md`).

---

## 2. Lesereihenfolge (für die neue Claude-Instanz)

1. **`docs/HANDOVER.md`** (dieses Dokument) — Überblick + nächste Schritte.
2. **`docs/api-guideline.md`** — VERBINDLICH: Endpoints, Felder, Konventionen, Auth, Versionierung.
3. **`docs/database-guideline.md`** — VERBINDLICH: SQLite-Modell + Migrationen.
4. **`docs/bambu-spoolman-bridge-concept.md`** — das fachliche Gesamtkonzept.
5. **`docs/review-findings-backlog.md`** — priorisierte To-dos (BR-1…BR-20) mit Lösungen.
6. **`docs/no-devmode-capability-matrix.md`** — was ohne Dev-Mode geht/blockiert ist.
7. **`docs/capture-runbook.md`** — mitmproxy-Capture der Cloud-API (Schritt für Schritt).
8. Vertiefung nach Bedarf: `filament-cloud-api-analysis-spec.md`, `filament-preset-db-concept.md`,
   `esp32-slot-selector-concept.md`, `analysis/README.md`.

---

## 3. End-to-End-Workflow (Soll)

```
Spule ins AMS → AMS liest RFID → MQTT tag_uid/remain/k/cali → Bridge
   ├─ unbekannt? → Onboarding (PWA: QR-Quick-Bind / Auto-anlegen / SpoolmanDB)
   ├─ bekannt?   → Spoolman: Lagerort=Slot, Verbrauch fortschreiben, k/cali speichern
   ├─ Label-Hub: Etikett (#Zahl + QR auf /spool/{id})
   └─ Entladen   → Restmenge reconcilen, Lagerort zurück auf vorherigen Ort
ESP32 neben Drucker: Drucker→AMS→Slot wählen → Slot-QR → mit PWA scannen → Filament scannen → bind
Cloud (optional): Filament-Bibliothek/Presets via RE'd REST (nach Capture)
```

---

## 4. Architektur & aktueller Stand

**Transport:** LAN-MQTT (primär) + Cloud-MQTT-Fallback (Token). **Spoolman** = System of Record für
Spulen; **Bridge-DB (SQLite)** = Mappings + Workflow-State + Cache + k-Katalog.

**Code-Map (`app/`, ~2140 LOC):**
| Datei | Inhalt | Status |
|-------|--------|--------|
| `main.py` | FastAPI-App, Verdrahtung, alle Endpoints, Bridge-State | ✅ läuft (Findings: Auth/Locks/Lazy-Init offen) |
| `mqtt_ingest.py` | LAN/Cloud-MQTT, AMS-Tray-Parser, get_version, publish | ✅ |
| `spoolman.py` | Spoolman-REST-Client (Community-Extra-Fields) | ✅ (chatty → BR-7) |
| `db.py` | SQLite (spool_map, slot_state, tag_registry, …) | ✅ (neue Tabellen → DB-Guideline §3) |
| `consumption.py` | remain%-Reconcile + Pro-Job (kombiniert) | ✅ |
| `jobs.py` | Druckjob-Erkennung (gcode_state, tray_now) | ✅ (Annahmen → BR-9/10) |
| `tags.py` | Tag-Lifecycle + Material-Kompatibilität | ✅ |
| `kcatalog.py` | k-Katalog (JSON; → DB migrieren) | ✅ |
| `cloud_library.py` | Cloud-Bibliotheks-Import (live/file) | ⚠ Endpoint Hypothese (Capture) |
| `preset_gen.py` | Bambu-Preset-JSON erzeugen | ✅ |
| `spoolmandb.py` | SpoolmanDB → Spoolman bulk-create | ✅ (httpx zur Laufzeit) |
| `labels.py` | Label-Printer-Hub Client | ✅ |
| `models.py`/`config.py` | Datentypen, Config-Load | ✅ |
| `scripts/` | build_catalog, extract_3mf_filaments, extract_endpoints, mitm_bambu_addon, redact_flows | ✅ Hilfsskripte |
| `web/` | Tailwind-PWA (Tabs: Onboarding/SpoolmanDB/Preset/Cloud/NFC) | ✅ (CDN → BR-18) |

**Geprüft:** Syntax (py_compile/node), Logik-Unit-Tests (Preset, SpoolmanDB, kcatalog, Mapping).
**Nicht** end-to-end gegen echten Drucker/Capture gelaufen (keine Hardware/Deps in der Build-Umgebung).

---

## 5. Verbindliche Konventionen (nicht abweichen!)

- **API:** `docs/api-guideline.md` — `/api/v1`, snake_case, Feld-Glossar, Error-Envelope
  `{detail,error_code}`, `X-API-Key`-Auth, HTTPS-Pflicht via Proxy.
- **DB:** `docs/database-guideline.md` — WAL, `user_version`-Migrationen, definierte Tabellen.
- **Spoolman-Extra-Fields:** `tag`, `active_tray`, `cali_idx`, `calibrated`, `k_value`, `n_coef`,
  `cloud_id`, `filament_id`, `type`, `nozzle_temperature`.
- **Auth-Profile:** HomeLab = hinter Proxy (Key optional); Werkstatt = API-Key und/oder Pangolin-SSO.
- **Kein Dev-Mode** als Default → Drucker-Schreibpfade bleiben gated.

---

## 6. Roadmap / nächste Schritte (priorisiert, ohne Drucker/Capture machbar zuerst)

Aus `docs/review-findings-backlog.md`:
1. **BR-5** Lazy-Init via FastAPI-`lifespan` (kein Config-Zwang beim Import).
2. **BR-1** `X-API-Key`-Auth + **BR-2** State-Locks.
3. **BR-3/BR-4** In-Memory-State → SQLite (`onboarding_pending`, `slot_assign`, `kv`).
4. **BR-7/BR-8** Spoolman-Schreiblast/Race reduzieren.
5. **BR-6** Doku-Ehrlichkeit (Cloud-Push/k-Set als „gated/ungetestet").
6. **Hardware/Capture (auf der VM):**
   - `docs/capture-runbook.md` ausführen → Cloud-Filament-Endpoint + `put_setting` bestätigen.
   - Am echten 2×-AMS verifizieren: `gcode_state`, `tray_now`-Indexierung, `ams_id`-Zuordnung,
     und ob `extrusion_cali_set`/`ams_change_filament` **ohne** Dev-Mode funktionieren.
7. **ESP32-Firmware** (CYD/LVGL) gegen die REST-API; **PWA-Slot-Bind-Flow**.

---

## 7. Migration in ein eigenständiges Repo

**Bereits konsolidiert:** Das gesamte Projekt liegt jetzt in **einem** Ordner
**`bambu-spoolman-bridge/`** (App im Root + `docs/` + `analysis/`). Dieser Ordner **ist** der
künftige Standalone-Repo-Root.

**Transfer = diesen einen Ordner kopieren:**
```bash
# im eigenständigen Repo:
cp -r bambu-spoolman-bridge/* bambu-spoolman-bridge/.gitignore <neues-repo>/
# (alternativ: git filter-repo / git subtree split auf den Ordner, um Historie zu behalten)
```
Inhalt: `app/ web/ scripts/ docs/ analysis/ Dockerfile docker-compose.yml requirements.txt
config.example.yaml README.md .gitignore`.

**NICHT übernehmen:** `data/` (Config/DB/Secrets), Captures/Dumps, die Bambu-DLL, Tokens.
(`.gitignore` blockt das bereits.) Optional entfernbar: `web/style.css` (von der Tailwind-UI
nicht mehr genutzt).

**Lizenz-Entscheidung (wichtig):**
- Der **App-Code ist Eigenentwicklung** → kann **MIT** sein. Empfehlung: neues Repo **MIT**,
  `LICENSE` hinzufügen.
- **Nicht** mitliefern: aus AGPL-Profilen **generierte** Daten (`catalog.json`) oder verbatim
  BambuStudio/OrcaSlicer-Profile — diese sind **AGPL**. Stattdessen `build_catalog.py` beim Nutzer
  **lokal** gegen dessen Studio/Orca-Installation laufen lassen (keine Weiterverteilung).
- **SpoolmanDB** ist MIT → frei nutzbar.
- Die Konzept-Docs sind unsere Texte (referenzieren AGPL-Quelle per Datei:Zeile = normale Doku).
- Falls stattdessen ein **Fork von `drndos/openspoolman`** (MIT) gewünscht ist: unsere MIT-fähigen
  Teile (MQTT-Ingest, Spoolman-Sync, Tag-Lifecycle, SpoolmanDB) passen dort hinein; AGPL-abgeleitete
  Preset-Daten getrennt halten.

**Empfohlene Repo-Struktur:**
```
bambu-spoolman-bridge/
├── app/  web/  scripts/  docs/  analysis/
├── Dockerfile  docker-compose.yml  requirements.txt  config.example.yaml
├── LICENSE (MIT)  README.md (aus README.md + HANDOVER-Auszug)
```

---

## 8. Setup auf der Ubuntu-VM

```bash
git clone <neues-repo> ~/bridge && cd ~/bridge
mkdir -p data && cp config.example.yaml data/config.yaml   # Drucker(LAN+Code)/Spoolman/security.api_key eintragen
docker compose up --build                                   # UI: http://<host>:8099 (HTTPS-Proxy davor!)
# lokal ohne Docker:
pip install -r requirements.txt
BRIDGE_CONFIG=data/config.yaml BRIDGE_DB=data/state.db uvicorn app.main:app --port 8099
```
**Spoolman-Extra-Fields** anlegen (Settings → Extra fields): Spool `tag`,`active_tray`;
Filament `filament_id`,`type`,`nozzle_temperature`.
**HTTPS** über Pangolin/Traefik/Caddy/NPM davor (Pflicht für Web NFC).
**Capture** der Cloud-API: `docs/capture-runbook.md` (mitmproxy + Cert-Bundle-Trick + Addon).

---

## 9. Erst-Prompt für die neue Claude-Code-Instanz

> Du übernimmst das Projekt „Bambu ↔ Spoolman Bridge". Lies in dieser Reihenfolge:
> `docs/HANDOVER.md`, `docs/api-guideline.md`, `docs/database-guideline.md`,
> `docs/review-findings-backlog.md`, `docs/no-devmode-capability-matrix.md`.
> Halte dich strikt an die API- und DB-Guideline (keine neuen Namen/Endpoints/Felder).
> Beginne mit dem Backlog in dieser Reihenfolge: BR-5 (Lazy-Init/lifespan) → BR-1 (X-API-Key) →
> BR-2 (State-Locks) → BR-3/BR-4 (State→SQLite). Validiere jeweils mit py_compile und kurzen
> Logik-Tests; committe in kleinen Schritten. Hardware-abhängige Punkte (Capture, Dev-Mode,
> tray_now) erst, wenn Drucker/mitmproxy bereit sind — dann `docs/capture-runbook.md` befolgen.

---

## 10. Offene Punkte / am echten Setup zu verifizieren

- Cloud-Filament-Endpoint (`/v1/user-service/my/filament/v2`) + `put_setting`-Schema (Capture).
- `gcode_state`-Werte, `tray_now`-Indexierung (2× AMS 2 Pro), `ams_id`↔get_version-Zuordnung.
- Ob `extrusion_cali_set` / `ams_change_filament` (unload) **ohne** Dev-Mode funktionieren.
- Bambu-Eigenverhalten: legt der Filament Manager bei neuer RFID einen separaten Record an? (§6.1)

---

## 11. Datei-Inventar (Stand Übergabe)

- **Tool:** `` — 17 `app/*.py`, 5 `scripts/*.py`, 4 `web/*`, Docker,
  compose, requirements, config.example, README, .gitignore.
- **Docs:** `docs/` — HANDOVER, api-guideline, database-guideline, bambu-spoolman-bridge-concept,
  filament-cloud-api-analysis-spec, filament-preset-db-concept, esp32-slot-selector-concept,
  capture-runbook, no-devmode-capability-matrix, review-findings-backlog, TODO-api-guideline-adoption.
- **Austausch:** `analysis/` — README, ENDPOINTS, .gitignore (schema-only Hand-off-Zone).

> Stand: Branch `claude/dazzling-sagan-vdro2v` im AGPL-Repo `strausmann/BambuStudio`.
> GitHub-Issues dort **deaktiviert** → Backlog liegt in `docs/review-findings-backlog.md`.
