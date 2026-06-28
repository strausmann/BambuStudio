# Reichweite ohne Developer Mode / LAN-only

> Antwort auf: „Wie weit kommen wir ohne Developer Mode und LAN-only über unsere API/RE?"
> Grundlage: BambuStudio-Quellcode (MQTT-Felder/Kommandos), OpenSpool-Erkenntnisse
> (signierte MQTT-Kommandos), unsere Reviews. **Einige Schreibpfade sind unverifiziert** und beim
> echten Drucker zu bestätigen (markiert ⚠).

## Kernaussage

- **Lesen (Status/Telemetrie) über LAN-MQTT: funktioniert vollständig** — ohne Developer Mode.
- **Schreiben/Steuern am Drucker über MQTT** (Unload, k-set, Slot-Override): **wahrscheinlich
  blockiert** ohne Developer Mode (neuere Firmware signiert Steuer-Kommandos). ⚠ zu verifizieren.
- **Cloud-Account-API** (Filament-Bibliothek lesen, **User-Presets** anlegen → Drucker-Display):
  **funktioniert mit Token, unabhängig von Developer Mode** (ist Cloud, nicht Drucker-LAN).
- **Spoolman/Bridge-Logik** (Mapping, Lagerort, Verbrauch, k-Katalog): funktioniert immer
  (eigene Seite + Spoolman).

→ Praktisch: Die Bridge ist gegenüber dem **Drucker read+track**, gegenüber **Spoolman und
Bambu-Cloud-Account read+write**. Der „fehlende" Teil ist das aktive **Kommandieren des Druckers
über LAN-MQTT** — und der ist für unseren Kern-Use-Case **nicht nötig**.

## Matrix

| Funktion | Kanal | LAN-only, **kein** Dev-Mode | Lösung / Workaround |
|----------|-------|------------------------------|---------------------|
| AMS-Trays lesen (tag_uid, remain, k, n, cali_idx, Belegung) | LAN-MQTT `report`/`pushall` | ✅ funktioniert | — |
| AMS-Typ/Seriennummer (`get_version`) | LAN-MQTT `info` | ✅ | — |
| Druck-Status / gcode_state (Verbrauch pro Job) | LAN-MQTT | ✅ | remain%-Delta; `pushall` bei Jobende |
| RFID-Onboarding, Lagerort, Verbrauch → Spoolman | Bridge↔Spoolman REST | ✅ | unabhängig vom Drucker |
| k-Wert **lesen** | LAN-MQTT (Tray `k`/`n`) | ✅ | bereits umgesetzt |
| **Unload** auslösen (`ams_change_filament`) | LAN-MQTT (Schreib) | ⚠ vermutl. **blockiert** | manuell am Drucker; Unload nur „logisch" in Spoolman (Reconcile) |
| **k setzen** (`extrusion_cali_set`) | LAN-MQTT (Schreib) | ⚠ vermutl. **blockiert** | k am Drucker via Studio kalibrieren; Bridge trackt nur |
| **Slot-Profil/Override** (`ams_filament_setting`: Hersteller/Typ/Farbe) | LAN-MQTT (Schreib) | ⚠ vermutl. **blockiert** | **Cloud-User-Preset** anlegen → am Display **manuell** wählen |
| Filament-Bibliothek der Cloud **lesen** | Cloud REST + Token | ✅ (Endpoint per Capture bestätigen) | mitmproxy-Capture (Spec) |
| **User-Preset** anlegen → erscheint im Drucker-Display | Cloud REST (`put_setting`) + Token | ✅ ohne Dev-Mode | Endpoint per Capture bestätigen; sonst Studio-Sync |
| SpoolmanDB-Import (Filamente anlegen) | Bridge↔Spoolman | ✅ | — |

## Warum Schreiben am Drucker wahrscheinlich Dev-Mode braucht

OpenSpool/Community: neuere Firmware **verifiziert MQTT-Steuerkommandos kryptografisch**
(per-Installation-RSA). Reine **Status-Subscriptions** sind davon nicht betroffen → Lesen geht,
Steuern nicht. Developer Mode hebt die Prüfung auf — **deaktiviert aber die Cloud**, was hier
nicht gewünscht ist. Deshalb: **Drucker-Steuerung meiden**, stattdessen Cloud-Account-Presets +
manuelle Auswahl am Display.

## Konsequenz fürs Design

1. **Kern-Workflow kommt ohne Dev-Mode aus:** MQTT-Read (RFID/Verbrauch/Slot) + Spoolman-Tracking
   + Cloud-Preset für die Display-Auswahl.
2. Drucker-**Schreib**-Features (`/api/cali/set`, `/api/ams/unload`, Slot-Override) bleiben
   **per Config gated** und werden als „optional, Dev-Mode" geführt — nicht im Standardpfad.
3. **Verifikationsauftrag** (echter Drucker, ohne Dev-Mode): Funktionieren `extrusion_cali_set`
   und `ams_change_filament` (unload) trotzdem? Falls ja → super; falls nein → wie erwartet, kein
   Beinbruch (Workarounds s. o.).

## Was das RE noch braucht (alles ohne Dev-Mode)

- **Cloud-Filament-Endpoint** (`/v1/user-service/my/filament/v2`) + **`put_setting`-Pfad/Schema**
  per **mitmproxy-Capture** bestätigen (Spec/Runbook). Token genügt, kein Dev-Mode.
- Danach: Cloud-Bibliotheks-Import scharf schalten und Preset-Push automatisieren.
