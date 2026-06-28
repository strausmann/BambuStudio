# BR-10 — Job-Ende liest evtl. veraltetes remain

**Type:** bug · **Severity:** 🟠 high · **Area:** consumption · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-10

## Problem
`_end` liest `remaining_grams()` aus `live_trays`; bei FINISH evtl. noch kein frisches `remain` → Unterzählung. 'genau' ist faktisch remain-Delta-genau (~10 g/1 kg).

## Lösung
Bei Jobende `pushall` triggern bzw. auf nächsten Tray-Push nach Ende buchen; Doku 'remain-Delta-genau'.

## Akzeptanzkriterien
- [ ] Verbrauch wird nach Jobende mit aktuellem remain gebucht
