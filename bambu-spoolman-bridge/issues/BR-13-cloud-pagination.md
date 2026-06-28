# BR-13 — Cloud-Fetch paginiert nicht

**Type:** bug · **Severity:** 🟠 high · **Area:** cloud · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-13

## Problem
`fetch_cloud_filaments` lädt nur die erste Seite (limit 200); größere Bibliotheken werden still abgeschnitten.

## Lösung
Offset-Schleife bis Rückgabe < limit.

## Akzeptanzkriterien
- [ ] vollständiger Import unabhängig von der Bibliotheksgröße
