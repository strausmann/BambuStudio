# BR-08 — set_extra GET-modify-PUT ist racy

**Type:** bug · **Severity:** 🟠 high · **Area:** spoolman · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-8

## Problem
`set_extra` liest+schreibt das gesamte `extra`-Objekt → last-writer-wins, paralleler Verlust möglich.

## Lösung
Pro-Spool serialisieren; nur geänderte Keys schreiben (falls Spoolman partial unterstützt).

## Akzeptanzkriterien
- [ ] gleichzeitige Updates verschiedener extra-Keys gehen nicht verloren
