# BR-14 — material_family zu naiv

**Type:** bug · **Severity:** 🟠 high · **Area:** safety · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-14

## Problem
`material_family` (split) ist load-bearing für den Kompatibilitätsschutz (kein PLA-Tag auf PETG). Edge-Cases (PA-CF vs PAHT-CF, 'Support for PLA') kollabieren falsch.

## Lösung
Härten: Bekannte-Typen-Tabelle + CF/HT-Varianten + Support-Erkennung.

## Akzeptanzkriterien
- [ ] Testfälle für gängige Materialien + Varianten grün
