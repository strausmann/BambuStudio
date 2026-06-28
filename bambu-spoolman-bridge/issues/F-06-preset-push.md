# F-06 — Preset-Push (Drittanbieter-Profile ins Bambu-Konto)

**Type:** feature · **Severity:** 🟡 normal · **Area:** import · **Status:** blocked · **Refs:** app/preset_gen.py, scripts/build_catalog.py, F-03

## Ziel
Generierte Filament-Presets (Drittanbieter) so ins Bambu-Konto schreiben, dass sie am
Druckerdisplay in den AMS-Slots auswählbar werden.

## Status: blocked
Hängt an F-03 (bestätigter Schreib-Endpoint / `put_setting`-Äquivalent) und an der Klärung,
ob das ohne offizielle API/Signatur überhaupt zulässig/möglich ist.

## Aufgaben
- [ ] Schreib-Endpoint aus Capture identifizieren (create/update setting)
- [ ] Lizenz-Klärung der Preset-Quellen (OrcaSlicer/BambuStudio = AGPL-3.0; SpoolmanDB = MIT)
- [ ] Mapping Preset → Cloud-Setting-Payload
- [ ] Trockenlauf + ein manueller End-to-End-Test

## Akzeptanzkriterien
- [ ] Mind. ein Dritthersteller-Preset erscheint am Display (manuell verifiziert)
- [ ] Lizenzhinweise dokumentiert
