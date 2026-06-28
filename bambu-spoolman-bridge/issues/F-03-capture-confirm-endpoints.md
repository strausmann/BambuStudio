# F-03 — Cloud-Endpoints per mitmproxy bestätigen

**Type:** feature · **Severity:** 🟠 high · **Area:** reverse-engineering · **Status:** open · **Refs:** docs/capture-runbook.md, src/slic3r/GUI/fila_manager/wgtFilaManagerCloudClient.cpp, analysis/ENDPOINTS.md

## Ziel
Die aus dem Studio-Quelltext abgeleiteten Filament-Cloud-Routen (list/create/update/
batch_delete/config über `/my/filament/v2`) gegen echten Traffic verifizieren und
Host + vollständige Pfade + Statusmodelle dokumentieren.

## Aufgaben
- [ ] Runbook auf der Ubuntu-VM durchführen (Cert-Bundle-Trick + mitmweb)
- [ ] GET (Liste), POST (create), PUT (update), DELETE (batch) auslösen
- [ ] `analysis/endpoints.schema.json` (redigiert) + `analysis/ENDPOINTS.md` füllen
- [ ] `cloud_library.endpoint` in der Config bestätigen/korrigieren

## Akzeptanzkriterien
- [ ] Host + Pfade jeder Operation dokumentiert (nur Schema, keine Credentials)
- [ ] Importer-Mapping gegen echte Antwort (file-Modus, dry_run) grün
