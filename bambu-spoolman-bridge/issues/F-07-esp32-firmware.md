# F-07 — ESP32-2432S028 Slot-Selektor (Firmware)

**Type:** feature · **Severity:** 🟡 normal · **Area:** hardware/esp32 · **Status:** open · **Refs:** docs/esp32-slot-selector-concept.md

## Ziel
Firmware für das ESP32-2432S028 (Touch-Display) neben dem Drucker: AMS-Slots anzeigen,
Filament auswählen, QR-Bind-Flow, NFC-Scan, Unload, Restock-Location.

## Aufgaben
- [ ] Touch-UI: AMS/Slots mit Belegung + Info-Zeichen für „kein Profil zugeordnet"
- [ ] REST-Client gegen Bridge (`/api/v1/...`) inkl. API-Key
- [ ] QR-Bind-Flow (Spule ↔ Slot) + NFC-Scan-Trigger
- [ ] Unload-Aktion + Restock-Location-Auswahl
- [ ] WLAN-Setup/Config-Portal

## Akzeptanzkriterien
- [ ] Slot-Belegung live aus Bridge sichtbar
- [ ] Bind + Unload lösen korrekte Bridge-Calls aus
