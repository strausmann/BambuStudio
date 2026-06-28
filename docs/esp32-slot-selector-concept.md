# Konzept: ESP32-2432S028 Slot-Selector (Touch-Display neben dem Drucker)

> Ein **ESP32-2432S028** („Cheap Yellow Display", 2.8" Touch-TFT) im Gehäuse neben dem Drucker.
> Er hilft beim **Spulenwechsel**: Slot wählen → QR anzeigen → mit der Bridge-PWA scannen →
> Filament-Tag/QR scannen → die Bridge ordnet Filament ↔ Slot zu (Quelle: Spoolman) und pflegt
> Lagerort + Verbrauch. Unload und „gehört nach Lagerort X" laufen ebenfalls über das Display.

## 1. Rollen & Datenfluss

```
[ESP32-2432S028]  ──HTTP/REST──▶  [Bridge (Docker, LAN)]  ──MQTT──▶  Drucker/AMS
   Touch-UI                         - kennt Drucker/AMS/Slots         (1..n Drucker)
   QR anzeigen                      - Spoolman als Datenquelle
   Unload-Button                    - schreibt Lagerort/Verbrauch/k
        ▲                                   │ REST
        └────── Bridge-PWA (Handy) ─────────┘  scannt Slot-QR + Filament-Tag/QR
```
**Die Bridge ist die einzige Instanz, die mit den Druckern (MQTT) spricht.** ESP32 und PWA
sprechen nur **REST** mit der Bridge. Damit braucht der ESP32 keine Bambu-Credentials.

## 2. ESP32-Screens

1. **Drucker-Auswahl** (nur wenn >1 Drucker) — `GET /api/printers`.
2. **AMS-Auswahl** — `GET /api/printers/{serial}/ams` → Liste der AMS (mit sprechendem Namen,
   z. B. „AMS 2 Pro (1234)").
3. **Slot-Gitter** — pro AMS die Slots 1–4 mit Belegung (Material/Farbe/Restprozent, leer/voll).
4. **Slot-Detail** — zeigt **QR-Code** + Infozeilen *(Drucker, AMS, Slot)* + Buttons **Zurück** /
   **Home** + **Unload**.

## 3. QR-Payload (Slot)

Der ESP32 erzeugt den QR lokal. Inhalt = eine von der PWA verstandene URL:

```
https://<bridge-host>/slot?p=<serial>&a=<ams_id>&s=<tray_id>
```
- Scannt die PWA diesen QR, ruft sie **`POST /api/slot/stage {serial, ams_id, tray_id}`** auf
  (Slot „vormerken"). Kein sensibler Inhalt im QR (nur Indizes).

## 4. Bind-Flow (Slot ↔ Filament)

```
ESP32: Slot wählen → QR
PWA:   QR scannen           → POST /api/slot/stage         (Slot vorgemerkt)
PWA:   Filament scannen:
         - Bambu-RFID / Dritt-NFC (Custom-NDEF) / Spoolman-Spulen-QR
       → POST /api/slot/assign {tag_uid|spool_id}          (Zuweisung gemerkt)
Mensch: Filament physisch einlegen → AMS lädt
Bridge (MQTT-Load-Event für den Slot):
   - Spoolman-Spule = die zugewiesene → location/active_tray = Slot
   - hat RFID? → tag_uid ↔ Spule binden (zukünftig automatisch)
   - Dritthersteller ohne brauchbare Codierung + override aktiv → ams_filament_setting
     (Hersteller/Typ/Farbe/Temps auf den Slot schreiben)  ⚠ nur mit Developer Mode (§6)
```
Umgesetzt in der Bridge: `stage_slot()` / `assign_to_staged()` / `_apply_pending()`
(`/api/slot/stage`, `/api/slot/assign`).

## 5. Sonderfälle

- **Bambu-RFID erkannt:** Das AMS liest den Tag selbst; die Bridge erkennt ihn (MQTT `tag_uid`).
  Ist die Spule schon bekannt → **nur Lagerort** auf den Slot setzen (kein erneutes Anlegen).
- **Verbrauch:** läuft über den bestehenden Mechanismus (remain%-Reconcile + Pro-Job, `k`/`cali_idx`
  werden mitgeschrieben).
- **Unload über ESP32:** Button → `POST /api/ams/unload {serial, ams_id}` → MQTT
  `ams_change_filament` (slot/target=255). Danach: **Restmenge reconcilen** und der Spule ihren
  **Heim-Lagerort** zuweisen (vorher gemerkt, §5.3 der Bridge). Der ESP32 zeigt **„gehört nach:
  <Lagerort>"** an (aus dem Spoolman-`location`/`spool_home`).

## 6. Wichtige Einschränkungen (ehrlich)

- **Hersteller/Typ/Farbe auf dem Drucker-Slot setzen** (für Dritthersteller) = MQTT
  `ams_filament_setting` → braucht **LAN + Developer Mode** (deaktiviert die Cloud) → bei dir
  standardmäßig **aus**. Ohne Dev-Mode trackt die Bridge alles in **Spoolman** (Lagerort,
  Verbrauch, k), kann aber die Slot-Anzeige am Drucker nicht überschreiben → richtiges Filament
  am **Drucker-Display manuell** wählen (die per Preset-Generator erzeugten User-Presets stehen
  dann zur Auswahl, §filament-preset-db).
- **k schreiben** (`/api/cali/set`) und **Unload** (`/api/ams/unload`) sind aus Sicherheits-/
  FW-Gründen per Config-Flag **gated** (`ams.allow_k_write`, `ams.allow_unload`, Default `false`);
  beim Capture-Lauf bzgl. Dev-Mode/FW verifizieren.

## 7. Bridge-API für den ESP32 (vorhanden)

| Zweck | Endpoint |
|-------|----------|
| Drucker auflisten | `GET /api/printers` |
| AMS + Slots (Belegung) | `GET /api/printers/{serial}/ams` |
| Slot vormerken (QR-Scan) | `POST /api/slot/stage {serial,ams_id,tray_id}` |
| Filament zuweisen | `POST /api/slot/assign {tag_uid|spool_id}` |
| Unload | `POST /api/ams/unload {serial,ams_id}` *(gated)* |
| k setzen | `POST /api/cali/set {serial,ams_id,tray_id,k,n}` *(gated)* |
| k-Katalog | `GET /api/kcatalog` |

## 8. Status / nächste Schritte

- [x] Read-APIs (`/api/printers`, `/api/printers/{serial}/ams`) aus Live-MQTT.
- [x] Slot stage/assign + Apply-on-Load (RFID-Bind + Lagerort).
- [x] Unload- und k-Set-Kommandos (MQTT) — gated per Config.
- [ ] **ESP32-Firmware** (LVGL/Arduino) gegen diese REST-API (eigenes Repo/Unterordner).
- [ ] PWA: Slot-QR-Scan → stage → Filament-Scan → assign (UI-Flow).
- [ ] Optional: Slot-Override am Drucker (`ams_filament_setting`) — nur mit Dev-Mode.
