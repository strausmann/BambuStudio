# API Guideline — Bambu ↔ Spoolman Bridge (Single Source of Truth)

> **Zweck:** Verbindlicher Standard für die HTTP-API, die Feldnamen, die Spoolman-Extra-Fields,
> die Config-Keys und die Konventionen der Bridge (`tools/bambu-spoolman-bridge`) **und** der
> Clients (PWA, ESP32). Jede Teilentwicklung MUSS sich hieran halten — keine ad-hoc-Namen,
> -Endpoints oder -Annahmen mehr. Änderungen an dieser Datei laufen über Review (siehe Issue).
>
> **Status:** v1-Definition. Der aktuelle Prototyp weicht teils ab (`/api/...` ohne Version) →
> Abweichungen + Migration in §12 / im Tracking-Issue.

## 1. Grundprinzipien

- **JSON only.** Request- und Response-Bodies sind `application/json` (UTF-8).
- **snake_case** für alle JSON-Feldnamen und Query-Parameter.
- **Versioniert:** alle Endpoints unter **`/api/v1`**. Breaking Changes → `/api/v2`.
- **Ressourcen-orientiert:** Pfade sind Substantive im **Plural**; Hierarchie spiegelt Besitz.
- **Einheiten fix** (§6). **Keine Synonyme** für kanonische Felder (§5).
- **Sicher per Default:** HTTPS-only (Proxy, §9), API-Key auf allen mutierenden Routen (§8).
- **Idempotent, wo möglich** (§7).

## 2. URL-Struktur & Ressourcen

```
/api/v1/state                                  Gesamt-Schnellzustand (UI-Polling)
/api/v1/printers                               Drucker des Setups
/api/v1/printers/{serial}/ams                  AMS-Geräte + Slots (Belegung, Badges)
/api/v1/printers/{serial}/ams/{ams_id}/unload  Aktion: Slot entladen           [gated]
/api/v1/printers/{serial}/ams/{ams_id}/slots/{tray_id}/calibration  k setzen   [gated]
/api/v1/spools                                 Spoolman-Spulen (Proxy/Index)
/api/v1/spools/bind                            tag_uid ↔ Spoolman-Spule binden
/api/v1/tags                                   Tag-Inventar (frei/zugewiesen)
/api/v1/tags/{tag_uid}/free | /reassign        Tag-Lifecycle
/api/v1/onboarding/pending                     offene RFID-Onboardings
/api/v1/onboarding/auto                        Auto-Anlage aus Tray-Metadaten
/api/v1/slots/stage | /slots/assign            ESP32-Bind-Flow
/api/v1/filaments/db/summary | /db/import      SpoolmanDB (vendor/type → Spoolman)
/api/v1/presets/generate                       Bambu-Preset-JSON erzeugen
/api/v1/cloud/import                           Bambu-Filament-Bibliothek → Spoolman [blockiert*]
/api/v1/calibration/kcatalog                   beobachtete k-Werte (Katalog)
/api/v1/labels/{spool_id}/print                Etikett drucken (Label-Hub)
```
`{serial}` = Drucker-Seriennummer, `{ams_id}` = AMS-Index (int), `{tray_id}` = Slot 0-basiert.
`*blockiert` = abhängig vom per Capture zu bestätigenden Cloud-Endpoint (Spec §1.2.1).

## 3. HTTP-Methoden & Statuscodes

| Methode | Verwendung |
|---------|-----------|
| `GET` | Lesen, keine Seiteneffekte |
| `POST` | Anlegen / Aktion auslösen (auch Aktionen wie `unload`, `import`, `stage`) |
| `PUT` | Vollständig ersetzen |
| `PATCH` | Teil-Update |
| `DELETE` | Löschen |

| Code | Bedeutung |
|------|-----------|
| 200 | OK (Ergebnis im Body) · 201 angelegt · 202 angenommen/async · 204 leer |
| 400 | Validierungs-/Eingabefehler · 401 fehlende/falsche Auth · 403 deaktiviert/gated |
| 404 | nicht gefunden · 409 Konflikt (z. B. Inkompatibilität) · 422 Schema-Fehler (FastAPI) |
| 502 | Upstream-Fehler (Spoolman/Bambu-Cloud) · 503 Drucker/MQTT nicht verbunden |

## 4. Envelopes

- **Einzelressource (GET):** das Objekt selbst (kein Wrapper).
- **Liste (paginierbar):** `{"items": [...], "total": <int>, "limit": <int>, "offset": <int>}`.
  Kurze, feste Listen (z. B. `printers`) dürfen ein bloßes Array sein.
- **Aktion:** `{"status": "ok", ...ergebnisfelder}`.
- **Fehler (immer):**
  ```json
  { "detail": "human readable message", "error_code": "machine_code" }
  ```
  `detail` bleibt FastAPI-kompatibel; `error_code` ist optional, aber empfohlen
  (z. B. `printer_offline`, `k_write_disabled`, `incompatible_material`, `unknown_tag`).

## 5. Kanonisches Feld-Glossar (KEINE Synonyme!)

| Feld | Typ | Bedeutung |
|------|-----|-----------|
| `serial` | string | Drucker-Seriennummer |
| `ams_id` | int | AMS-Index (entspricht `print.ams.ams[].id`) |
| `tray_id` | int | Slot-Index **0-basiert**; UI zeigt 1-basiert an |
| `tag_uid` | string | RFID/NFC-UID (Bambu „SN") — der maschinelle Spulen-Schlüssel |
| `spool_id` | int | Spoolman-Spool-ID (= die „#Zahl") |
| `filament_id` | string | Bambu Preset-/Setting-ID (z. B. `GFL99`); Synonym im Bambu-Tray: `tray_info_idx` (nur intern beim Parsen) |
| `setting_id` | string | = `filament_id` im Kontext einer Spule (nicht doppelt einführen) |
| `material` | string | Materialtyp (PLA, PETG, …); Bambu-Tray-Feld `tray_type` |
| `material_family` | string | grobe Familie (PLA/PETG/…) für Kompatibilität |
| `color_hex` | string | Farbe **ohne** `#`, 6 Hex-Zeichen |
| `vendor` | string | Hersteller |
| `remain` | int | Restmenge **in %** (0–100) wie vom AMS gemeldet |
| `remaining_weight` | float | Restmenge **in Gramm** (Spoolman) |
| `k_value` | float | Pressure-Advance k |
| `n_coef` | float | PA n-Koeffizient (Bambu fix 1.4 beim Setzen) |
| `cali_idx` | int | Index in der Drucker-PA-Tabelle (-1 = keiner) |
| `nozzle` | string | Düsendurchmesser als String, z. B. `"0.4"` |
| `dry_run` | bool | Vorschau ohne Schreiben |

Bambu-Protokoll-Feldnamen (`tray_info_idx`, `tray_type`, `tray_color`, `cols`, `ctype`) werden
**nur beim MQTT-Parsing** verwendet und sofort auf die kanonischen Namen gemappt.

## 6. Einheiten & Formate

- Gewichte: **Gramm** (float). Temperaturen: **°C** (int). Durchmesser: **mm** (float).
- Farbe: 6-stelliges Hex **ohne** `#` (Alpha nur wenn nötig, dann 8-stellig).
- Zeitstempel: **ISO-8601 UTC** (`2026-06-28T10:00:00Z`).
- IDs: `spool_id`/`ams_id`/`tray_id`/`cali_idx` = int; `tag_uid`/`serial`/`filament_id` = string.

## 7. Idempotenz

- **Bind/Assign/Onboard** sind über `tag_uid` idempotent (erneutes Binden überschreibt sauber).
- **Importe** (`cloud/import`, `filaments/db/import`) erkennen Bestehendes (RFID/`cloud_id`/
  vendor+material+color) und **überspringen** statt zu duplizieren; bieten `dry_run`.
- Lang laufende Importe serialisieren (kein paralleles Doppel-Anlegen).

## 8. Authentifizierung

- **Alle mutierenden** Endpoints (POST/PUT/PATCH/DELETE) erfordern den Header
  **`X-API-Key: <key>`**. Lese-Endpoints SOLLTEN ihn ebenfalls verlangen (konfigurierbar).
- Key kommt aus `config.yaml` (`security.api_key`) oder Env `BRIDGE_API_KEY`.
- Fehlt/falsch → **401** `{"detail":"unauthorized","error_code":"unauthorized"}`.
- Der API-Key ist **kein** Ersatz für den HTTPS-Proxy (§9), sondern Ergänzung.

## 9. Transport / HTTPS (Pflicht)

- Die Bridge bindet intern an HTTP (z. B. `:8099`); **TLS terminiert ein Reverse-Proxy davor**:
  **Pangolin** (mit SSO), **Traefik**, **Caddy** (Auto-HTTPS) oder **Nginx Proxy Manager**.
- **HTTPS ist Pflicht** für die PWA (Web NFC + Kamera brauchen Secure Context). Reine LAN-IP
  über `http://` ist für die App nicht nutzbar (Konzept §12).

## 10. Spoolman-Extra-Fields (kanonisch, Interop mit OpenSpoolMan/BambuSpoolPal)

| Ebene | Extra-Field | Inhalt |
|-------|-------------|--------|
| Spool | `tag` | `tag_uid` (RFID) |
| Spool | `active_tray` | aktueller AMS-Slot (`"<AMS-Name>/Slot<n>"`) |
| Spool | `cali_idx` | int · `calibrated` bool · `k_value` float · `n_coef` float |
| Spool | `cloud_id` | Bambu-Cloud-Record-ID (Import-Idempotenz) |
| Filament | `filament_id` · `type` · `nozzle_temperature` | Bambu-Preset-Bezug |

Spoolmans **natives** `location`-Feld = menschlicher Lagerort (AMS-Slot bei „geladen", sonst
vorheriger Lagerort/`storage_location`).

## 11. Config-Schema (`config.yaml`) — kanonische Keys

```
printers[]: { name, serial, transport(auto|lan|cloud), lan{host,access_code} }
bambu_account: { region, token, username }
spoolman: { base_url, tag_field, slot_field }
spoolmandb: { url }
cloud_library: { enabled, api_host, endpoint, limit }
consumption: { mode(per_job|remain|combined), reconcile_threshold_pct }
ams: { override_settings, nozzle, allow_k_write, allow_unload, aliases{}, storage_location }
label_printer: { enabled, base_url, template_id, print_on_onboard }
onboard: { auto_create, default_vendor }
security: { api_key }            # NEU (§8)
spoolman_public_url
```
Neue Keys nur ergänzen, nicht umbenennen. Defaults dokumentieren in `config.example.yaml`.

## 12. Audit: aktueller Prototyp → Ziel-API (Migration)

| Aktuell | Ziel (v1) |
|---------|-----------|
| `/api/state` | `/api/v1/state` |
| `/api/printers` · `/api/printers/{serial}/ams` | `/api/v1/printers` · `…/ams` |
| `/api/cali/set` (Body ams_id/tray_id) | `POST /api/v1/printers/{serial}/ams/{ams_id}/slots/{tray_id}/calibration` |
| `/api/ams/unload` (Body ams_id) | `POST /api/v1/printers/{serial}/ams/{ams_id}/unload` |
| `/api/bind` | `POST /api/v1/spools/bind` |
| `/api/free` · `/api/reassign` | `POST /api/v1/tags/{tag_uid}/free` · `…/reassign` |
| `/api/onboard_auto` | `POST /api/v1/onboarding/auto` |
| `/api/slot/stage` · `/api/slot/assign` | `/api/v1/slots/stage` · `/api/v1/slots/assign` |
| `/api/spoolmandb/summary` · `/import` | `/api/v1/filaments/db/summary` · `/db/import` |
| `/api/preset/generate` | `/api/v1/presets/generate` |
| `/api/cloud/import` | `/api/v1/cloud/import` |
| `/api/kcatalog` | `/api/v1/calibration/kcatalog` |
| `/api/label/{id}` | `/api/v1/labels/{id}/print` |

Migration ist ein eigener Schritt (Tracking-Issue) — Clients (PWA/ESP32) ziehen mit.

## 13. Pflege

- Diese Datei ist die **Quelle der Wahrheit**. PRs, die Endpoints/Felder/Configs ändern, MÜSSEN
  sie aktualisieren (und `README.md`/`config.example.yaml` synchron halten).
- Endpoint-Tabelle der README wird aus der tatsächlichen Routenliste gepflegt (kein Drift).
- Versionspolitik: additive Änderungen ok; Breaking → neue Version + Deprecation-Hinweis.
