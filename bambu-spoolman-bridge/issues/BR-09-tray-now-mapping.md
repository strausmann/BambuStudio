# BR-09 — tray_now-Mapping verfehlt Virtual/0x80

**Type:** bug · **Severity:** 🟠 high · **Area:** mqtt/consumption · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-9 · verify@hardware

## Problem
`map_tray_now`/Write-Pfad nutzen `ams_id*4+slot`, ignorieren Virtual-Tray (255) und 0x80-Bereich (Extern/2.-Extruder) → falsche Zuordnung.

## Lösung
Firmware-Ranges spiegeln (`DevExtruderSystem.cpp`); Virtual-Tray-Sonderfall in `set_k`/`unload`.

## Akzeptanzkriterien
- [ ] korrekte Zuordnung für AMS-Slots, Externspule, 2.-Extruder (am 2×-AMS verifiziert)
