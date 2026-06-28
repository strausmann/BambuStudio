# BR-06 — Doku überzeichnet 'implementiert'

**Type:** doc · **Severity:** 🔴 critical · **Area:** docs · **Status:** open · **Refs:** docs/no-devmode-capability-matrix.md, docs/review-findings-backlog.md BR-6

## Problem
Cloud-Push (`put_setting`) und k-Set sind als 'implementiert/[x]' markiert, hängen aber am unbestätigten Endpoint bzw. evtl. an Developer Mode.

## Lösung
In allen Docs als 'gated/ungetestet/blockiert bis Capture' kennzeichnen; Capability-Matrix verlinken.

## Akzeptanzkriterien
- [ ] keine 'implementiert'-Aussage für ungetestete Schreib-/Cloud-Pfade
