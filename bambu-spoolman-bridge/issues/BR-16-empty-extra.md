# BR-16 — Leer-String-Extra ('""') statt Key löschen

**Type:** chore · **Severity:** 🟡 low · **Area:** spoolman · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-16

## Problem
`set_active_tray(id, None)` schreibt `active_tray = '\"\"'` statt den Key zu entfernen → inkonsistente 'gesetzt?'-Checks.

## Lösung
Leere Extras entfernen statt leeren String schreiben.
