# F-04 — Druckerverhalten ohne Developer-Mode (2×AMS) verifizieren

**Type:** feature · **Severity:** 🟠 high · **Area:** hardware/mqtt · **Status:** open · **Refs:** docs/no-devmode-capability-matrix.md, app/mqtt_ingest.py

## Ziel
Empirisch klären, welche MQTT-Reads/Writes ohne Developer-Mode (Cloud bleibt aktiv,
LAN-only nicht zwingend) am echten Drucker mit zwei AMS funktionieren.

## Aufgaben
- [ ] `pushall`/`get_version` + Tray-Report lesen (tag_uid, tray_info_idx, remain, k/n, cali_idx)
- [ ] AMS-Identität (echte Namen statt AMS1/2) verifizieren
- [ ] Steuerbefehle testen: `extrusion_cali_set`, `ams_change_filament` (unload) — erlaubt/blockiert?
- [ ] Capability-Matrix (`no-devmode-capability-matrix.md`) mit Ist-Ergebnissen füllen

## Akzeptanzkriterien
- [ ] Matrix unterscheidet belegt „funktioniert / blockiert / unklar" je Befehl
- [ ] Lesepfad (k-Wert, remain) am realen Gerät bestätigt
