# BR-12 — Importe ohne Idempotenz-Lock

**Type:** bug · **Severity:** 🟠 high · **Area:** import · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-12

## Problem
Paralleler `cloud/import`/`spoolmandb/import` → check-then-act-Race → Duplikate.

## Lösung
Importe global serialisieren (Lock); Dedup über RFID/`cloud_id`/vendor+material+color beibehalten.

## Akzeptanzkriterien
- [ ] zwei parallele Importe erzeugen keine Duplikate
