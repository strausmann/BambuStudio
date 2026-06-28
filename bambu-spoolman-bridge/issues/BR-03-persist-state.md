# BR-03 — In-Memory-State überlebt Neustart nicht

**Type:** bug · **Severity:** 🔴 critical · **Area:** persistence/db · **Status:** open · **Refs:** docs/database-guideline.md §3, docs/review-findings-backlog.md BR-3

## Problem
`_pending` (Onboarding), `_pending_assign` (Slot-Bind), `_staged_slot` nur im RAM → Neustart verliert laufende Workflows.

## Lösung
SQLite-Tabellen `onboarding_pending`, `slot_assign`, `kv` (DB-Guideline §3). `live_trays`/`_last_cali` bleiben flüchtig (Cache).

## Akzeptanzkriterien
- [ ] Onboarding/Slot-Bind überleben Container-Neustart
