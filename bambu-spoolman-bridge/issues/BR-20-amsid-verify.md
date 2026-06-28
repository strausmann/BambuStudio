# BR-20 — get_version ams_id ↔ print.ams id verifizieren

**Type:** task · **Severity:** 🟡 low · **Area:** mqtt · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-20 · verify@hardware

## Problem
Annahme: `ams_id` aus `get_version`-Modulname (`n3f/0`) == `print.ams.ams[].id`. Bei Abweichung falsche AMS-Namen.

## Lösung
Am echten 2×-AMS verifizieren; ggf. Mapping korrigieren.
