# BR-02 — Ungelockter Cross-Thread-Zugriff auf geteilte Dicts

**Type:** bug · **Severity:** 🔴 critical · **Area:** concurrency · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-2

## Problem
`live_trays`, `_last_cali`, `_pending_assign`, `_staged_slot`, `ams_identity` werden vom MQTT-Thread und vom FastAPI-Threadpool genutzt; nur teils gelockt → `RuntimeError: dictionary changed size during iteration` möglich.

## Lösung
Ein `state_lock` um **alle** Zugriffe; über Kopien iterieren.

## Akzeptanzkriterien
- [ ] alle geteilten Strukturen nur unter Lock gelesen/geschrieben
- [ ] Lasttest ohne Race/Exception
