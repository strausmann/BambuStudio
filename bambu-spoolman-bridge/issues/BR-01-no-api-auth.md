# BR-01 — Keine Authentifizierung auf der API

**Type:** bug · **Severity:** 🔴 critical · **Area:** security/api · **Status:** open · **Refs:** docs/api-guideline.md §8, docs/review-findings-backlog.md BR-1

## Problem
Alle Endpoints (inkl. druckersteuernde: `/api/cali/set`, `/api/ams/unload`, `/api/bind`, `/api/cloud/import`) sind ohne Auth erreichbar. `allow_*`-Flags sind kein Auth-Ersatz.

## Lösung
`X-API-Key`-Dependency (Guideline §8); Key aus `security.api_key`/`BRIDGE_API_KEY`; auf allen mutierenden Routen erzwingen; ohne Key → Warnung + nur hinter Proxy (HomeLab-Profil).

## Akzeptanzkriterien
- [ ] mutierende Routen ohne gültigen Key → 401 `{detail,error_code:"unauthorized"}`
- [ ] Key konfigurierbar (Config + Env); HomeLab-Modus dokumentiert
