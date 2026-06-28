# BR-11 — MQTT-Schreibpfad/Robustheit

**Type:** bug · **Severity:** 🟠 high · **Area:** mqtt · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-11

## Problem
`publish_command` prüft Verbindung nicht (set_k/unload geben trotzdem 200); schwere Arbeit läuft im MQTT-Callback (Keepalive-Risiko); kein Reconnect-Watchdog; Token-Ablauf (~3 Mon.) ohne Refresh.

## Lösung
`is_connected()`-Check → 503; Heavy-Work in Worker-Queue; Reconnect-Watchdog; Token-Ablauf im UI/Log anzeigen.

## Akzeptanzkriterien
- [ ] Schreibkommando bei getrennter Verbindung → 503
- [ ] MQTT-Loop blockiert nicht durch Spoolman-Calls
