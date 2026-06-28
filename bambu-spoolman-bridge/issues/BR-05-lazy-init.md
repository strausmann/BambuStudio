# BR-05 — Bridge() beim Import + veraltetes on_event

**Type:** bug · **Severity:** 🔴 critical · **Area:** app/lifecycle · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-5

## Problem
`bridge = Bridge()` auf Modulebene braucht `config.yaml`, sonst bricht `uvicorn`/Test-Import. `@app.on_event("startup")` ist deprecated.

## Lösung
Lazy-Init im FastAPI-`lifespan`-Contextmanager.

## Akzeptanzkriterien
- [ ] Modul importierbar ohne config; Start nur im lifespan; keine Deprecation-Warnung
