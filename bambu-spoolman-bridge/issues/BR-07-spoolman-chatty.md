# BR-07 — Spoolman-Aufrufe zu chatty (N+1)

**Type:** perf · **Severity:** 🟠 high · **Area:** spoolman · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-7

## Problem
`find_spool_by_extra` scannt alle Spulen; pro Tray-Push mehrere GET/PUT auch ohne Änderung.

## Lösung
Spoolman-Filter-Query bzw. Einmal-Index; `active_tray`/`location` nur bei Änderung schreiben (wie `_last_cali`).

## Akzeptanzkriterien
- [ ] kein Full-Scan pro Lookup; keine PUTs ohne Wertänderung
