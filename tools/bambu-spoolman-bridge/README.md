# Bambu ↔ Spoolman Bridge (Prototype)

Local Docker service that ingests AMS/RFID/consumption telemetry from Bambu Lab
printers via **LAN MQTT** and syncs it to **Spoolman**, with an onboarding PWA
(QR quick-bind + Web NFC for third-party tags) and an optional **Label-Printer-Hub**
hook.

> Design rationale and decisions: [`docs/bambu-spoolman-bridge-concept.md`](../../docs/bambu-spoolman-bridge-concept.md)
> Cloud-API analysis (optional enrichment): [`docs/filament-cloud-api-analysis-spec.md`](../../docs/filament-cloud-api-analysis-spec.md)

## Status

Scaffold / work in progress. **Implemented:** LAN MQTT ingest + AMS tray parsing,
SQLite state (spool map, slot state, tag registry, job log), Spoolman client with
community extra fields (`tag` / `active_tray` / `filament_id`), remain% reconcile,
onboarding API + PWA, Label-Hub call, tag lifecycle (free / reassign with material
compatibility guard). **TODO:** cloud-MQTT fallback, per-job used-grams detection,
auto-create Spoolman filament from tray metadata, persisting the pending queue,
cloud-library import.

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

## License

MIT (intended), to ease upstreaming into `drndos/openspoolman` (MIT). See concept §11.
