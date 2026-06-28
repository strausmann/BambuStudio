# F-01 — API-Guideline übernehmen (Prefix, Auth, Envelope)

**Type:** feature · **Severity:** 🔴 critical · **Area:** api · **Status:** open · **Refs:** docs/api-guideline.md, docs/TODO-api-guideline-adoption.md

## Ziel
Den real existierenden Code an die verbindliche API-Guideline angleichen, damit Teil-
entwicklungen nicht erneut abweichen (Pfade, Fehler-Envelope, Auth, Versionierung).

## Aufgaben
- [ ] Einheitliches Prefix `/api/v1/…` für alle Routen (Alias auf Altpfade übergangsweise)
- [ ] Fehler-Envelope `{detail, error_code}` überall (Guideline §5)
- [ ] `X-API-Key`-Dependency auf mutierenden Routen (siehe BR-01)
- [ ] Health/Ready-Endpoints (`/api/v1/health`, `/api/v1/ready`)
- [ ] OpenAPI-Tags/Beschreibungen je Ressource

## Akzeptanzkriterien
- [ ] `docs/TODO-api-guideline-adoption.md` vollständig abgehakt
- [ ] Alle Routen unter `/api/v1`, Altpfade liefern 308/Alias
- [ ] Smoke-Test deckt Health + ein Beispiel je Ressource ab
