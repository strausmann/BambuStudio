# BR-04 — _staged_slot ist global (ein Slot)

**Type:** bug · **Severity:** 🔴 critical · **Area:** esp32/flow · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-4

## Problem
`stage_slot()` speichert genau einen globalen Slot → Mehrnutzer/Retry überschreiben sich, falsche Bindung möglich.

## Lösung
Staging session-/clientbezogen in `kv` (`staged_slot:<session>`); RMW unter Lock.

## Akzeptanzkriterien
- [ ] zwei parallele Stage/Assign-Flows kollidieren nicht
