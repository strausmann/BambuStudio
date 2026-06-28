# Bambu ↔ Spoolman Bridge (Prototype)

Local Docker service that ingests AMS/RFID/consumption telemetry from Bambu Lab
printers via **LAN MQTT** and syncs it to **Spoolman**, with an onboarding PWA
(QR quick-bind + Web NFC for third-party tags) and an optional **Label-Printer-Hub**
hook.

> **Dependencies: only the printer (MQTT) + Spoolman.** The bridge is fully
> self-contained and works **without Hangar** and **without the Label-Hub** — both
> are optional. It only reads/writes Spoolman's native `location` field as plain
> text, so any external viewer (e.g. Hangar) is purely additive.

> Design rationale and decisions: [`docs/bambu-spoolman-bridge-concept.md`](../../docs/bambu-spoolman-bridge-concept.md)
> Cloud-API analysis (optional enrichment): [`docs/filament-cloud-api-analysis-spec.md`](../../docs/filament-cloud-api-analysis-spec.md)

## Status

Scaffold / work in progress. **Implemented:** LAN MQTT ingest + AMS tray parsing,
AMS identity via `get_version` (type + serial → friendly location names), SQLite
state (spool map, slot state, tag registry, job log, spool home), Spoolman client
with community extra fields (`tag` / `active_tray` / `filament_id`), AMS slot →
Spoolman native `location` with previous-location restore on unload, remain%
reconcile, **auto-create** of Spoolman vendor/filament/spool from tray metadata,
**per-job consumption tracking** (remain%-delta; history-only in `combined`,
subtractive in `per_job`), onboarding API + PWA (QR quick-bind, auto-create,
Web NFC read/write), Label-Hub call, tag lifecycle (free / reassign with material
compatibility guard), **cloud-MQTT fallback** (token auth, `transport: auto`
prefers LAN via TCP reachability check), **cloud-library import** (Filament
Manager → Spoolman, live REST or saved JSON capture, idempotent via RFID +
cloud_id). **TODO:** persist pending queue, verify gcode_state/tray_now/
cloud-username **and the cloud filament endpoint path** against a real
printer/account.

## Finding the real cloud endpoint (packed DLL)

`bambu_networking.dll` is packed, so static `strings` shows no URLs. The decrypted
strings live in a **memory dump of the running Bambu Studio process** (1–1.5 GB —
don't upload it, scan it locally):

```bash
python3 scripts/extract_endpoints.py StudioDump.dmp        # Python (any OS)
# or on Windows with Sysinternals:  strings64.exe -n 6 StudioDump.dmp | findstr /i bambulab filament mqtt
```

Share only the matching `bambulab` / `/v1/...` / `filament` / `mqtt` lines — **redact any
token/cookie/personal id**. Put the confirmed filament path into
`config.cloud_library.endpoint`, then run the importer.

## Cloud library import

Imports your Bambu Filament Manager library into Spoolman.

```bash
# Dry run first (the live endpoint path is a HYPOTHESIS — verify via capture):
curl -X POST localhost:8099/api/cloud/import -H 'Content-Type: application/json' \
  -d '{"source":"live","dry_run":true}'
# Or test the mapping against a saved mitmproxy capture, no live call needed:
curl -X POST localhost:8099/api/cloud/import -H 'Content-Type: application/json' \
  -d '{"source":"file","path":"/data/capture.json","dry_run":false}'
```

## Quick start

```bash
cd tools/bambu-spoolman-bridge
mkdir -p data
cp config.example.yaml data/config.yaml   # then edit: printer serial, LAN host, access code, spoolman url
docker compose up --build
# UI on http://<host>:8099  (put HTTPS in front for Web NFC — see concept §12)
```

Local dev without Docker:

```bash
pip install -r requirements.txt
BRIDGE_CONFIG=data/config.yaml BRIDGE_DB=data/state.db uvicorn app.main:app --reload --port 8099
```

## Spoolman setup

Add these **extra fields** in Spoolman (Settings → Extra fields), matching the
OpenSpoolMan / BambuSpoolPal convention so tools interoperate:

- Spool: `tag` (text), `active_tray` (text)
- Filament: `filament_id` (text), `type` (text), `nozzle_temperature` (text)

## How it works

1. MQTT `device/<serial>/report` → AMS trays parsed (`tag_uid`, `tray_info_idx`,
   `tray_type`, `tray_color`, `remain`, `tray_weight`).
2. Known `tag_uid` → update Spoolman `active_tray` + reconcile remaining weight.
3. Unknown `tag_uid` → appears under "Neue Spulen" in the PWA → **scan the carton
   QR** (`/spool/{id}`) or enter the spool id to bind. Optional label print.
4. Tag lifecycle: free a tag when a spool is used up; reassign to a *same-material*
   third-party spool (no Developer Mode → no slot override, concept §5.4/§5.5).

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/state` | pending onboarding + free/all tags |
| GET | `/api/spools` · `/api/filaments` | Spoolman proxy |
| POST | `/api/bind` `{tag_uid, spool_id}` | link tag → spool |
| POST | `/api/free` `{tag_uid}` | mark tag reusable |
| POST | `/api/reassign` `{tag_uid, spool_id, spool_material}` | reuse on third-party (compat-checked) |
| POST | `/api/label/{spool_id}` | print a label |
| GET | `/api/spoolmandb/summary` | vendors/types from SpoolmanDB (online, MIT) |
| POST | `/api/spoolmandb/import` `{vendors,types,dry_run}` | bulk-create selected filaments in Spoolman |
| POST | `/api/preset/generate` `{vendor,material,…}` | build a Bambu filament preset JSON (Studio import) |

## UI

Tailwind (Play CDN) PWA with tabs: **Onboarding** (pending RFID, free tags, AMS),
**SpoolmanDB** (pick vendor+type → dry-run/import), **Preset-Generator** (form → download
Bambu preset JSON), **Cloud-Import**, **NFC** (read/write OpenSpool tags). HTTPS required for
Web NFC/camera — front it with a reverse proxy (concept §12).

## License

MIT (intended), to ease upstreaming into `drndos/openspoolman` (MIT). See concept §11.
