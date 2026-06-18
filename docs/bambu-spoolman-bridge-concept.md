# Konzept: Bambu-↔-Spoolman-Bridge (lokaler API-Wrapper im Docker-Container)

> **Zweck**
> Ein lokal (Docker) laufender Dienst, der die AMS-/RFID-/Verbrauchsdaten eines oder mehrerer
> Bambu-Lab-Drucker (hier: 2× **AMS 2 Pro**) abgreift und mit **Spoolman** synchronisiert.
> Ziel ist ein zuverlässiges **Verbrauchsmanagement pro physischer Spule**, identifiziert über
> die **RFID-Tag-UID** der Bambu-Spulen.
>
> **Schwester-Dokument:** `docs/filament-cloud-api-analysis-spec.md` (Analyse der Cloud-REST-API
> für die optionale Bibliotheks-Anreicherung, §6 hier).

---

## 0. Kernerkenntnis: RFID + Verbrauch kommen über **MQTT**, nicht über REST

Die Live-Daten „welche Spule (RFID) steckt in welchem AMS-Slot und wie viel ist noch drauf"
sind **MQTT-Telemetrie des Druckers** — kein Cloud-REST-Endpoint. Das ist der stabile,
lokale, dokumentierte Weg (kein Cert-Pinning, kein Token-Ablauf nötig).

Die im „Neues Filament"-Dialog der Bambu-App sichtbare **`SN`** (z. B. `5D585F4000000100`,
`D627C8DE00000100`) ist die **RFID-Tag-UID** — im BambuStudio-Code das Feld **`tag_uid`**.

---

## 1. Zielarchitektur

```
┌──────────────────────────── Docker-Host (Ubuntu, lokales Netz) ─────────────────────────────┐
│                                                                                              │
│   ┌───────────────┐   MQTT/TLS :8883     ┌────────────────────────┐                          │
│   │  Drucker +    │◀────────────────────▶│   bambu-spoolman-bridge │   REST    ┌───────────┐ │
│   │  2× AMS 2 Pro │  device/<SN>/report  │   (der Wrapper)         │──────────▶│  Spoolman │ │
│   └───────────────┘  device/<SN>/request │                        │           └───────────┘ │
│         ▲ LAN (primär)                    │  - MQTT-Ingest (LAN)    │                          │
│         │                                 │  - Cloud-MQTT-Fallback  │                          │
│   ┌───────────────┐  MQTT/TLS (Token)     │  - RFID↔Spool-Mapping   │   SQLite                 │
│   │  Bambu-Cloud  │◀────────────────────▶│  - Verbrauchs-Engine    │◀───────┐                 │
│   └───────────────┘  (Fallback)           │  - Onboarding-Web-UI    │        │ state.db        │
│                                            └────────────────────────┘────────┘                 │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Komponenten:**
1. **MQTT-Ingest** — abonniert den Drucker-Report, normalisiert AMS-Tray-Daten.
2. **Transport-Layer** — LAN primär, Cloud-MQTT als Fallback (siehe §3).
3. **RFID↔Spool-Mapping** — persistente Tabelle `tag_uid → spoolman_spool_id` (SQLite).
4. **Verbrauchs-Engine** — kombiniert „pro-Job-Abzug" (genau) + „remain%-Abgleich" (Reconcile).
5. **Onboarding-Web-UI** — fragt bei unbekannter RFID die Spoolman-Zuordnung ab.
6. **Spoolman-Client** — REST-Aufrufe (lesen/anlegen/Verbrauch buchen).

---

## 2. Datenquelle: MQTT-AMS-Telemetrie

### 2.1 Topics & Handshake

- **Subscribe:** `device/<SERIAL>/report`
- **Publish (einmalig für Vollzustand):** `device/<SERIAL>/request`
  mit `{"pushing":{"command":"pushall"}}`
- Danach kommen `print.command == "push_status"`-Deltas; Vollzustände periodisch.

### 2.2 Relevante Felder pro Tray (`print.ams.ams[].tray[]`)

Verifiziert aus `src/slic3r/GUI/DeviceManager.cpp` (AMS-Tray-Parsing ~Z. 4100–4217):

| MQTT-Feld        | Typ          | Bedeutung                              | Verwendung in der Bridge |
|------------------|--------------|----------------------------------------|--------------------------|
| `tag_uid`        | string       | **RFID-UID** (= „SN" in der App)       | **Primärschlüssel der Spule** |
| `tray_uuid`      | string       | Tray-UUID                              | sekundärer Schlüssel / Slot-Identität |
| `tray_info_idx`  | string       | Bambu Filament-Preset-ID (z. B. `GFL99`) | Material-/Filament-Zuordnung |
| `tray_type`      | string       | Materialtyp (PLA, PETG …)              | Spoolman-Material |
| `tray_sub_brands`| string       | Sub-Marke / Produktlinie               | Anzeigename |
| `tray_color`     | string (hex) | Primärfarbe                            | Farbabgleich |
| `cols`           | string[]     | Mehrfarb-Liste                         | Multicolor |
| `ctype`          | int          | Farbtyp (0/1/2)                        | Multicolor |
| `remain`         | int (0–100)  | **Restmenge in %** (nur bei RFID-Spule!) | Verbrauchs-Reconcile |
| `tray_weight`    | string (g)   | Sollgewicht der vollen Rolle           | g-Umrechnung von `remain` |
| `tray_diameter`  | string       | Durchmesser                            | Spoolman-Diameter |
| `nozzle_temp_min`/`max` | string| Temperaturfenster                      | optional |
| `tray_id_name`   | string       | Tray-Label                             | Anzeige |

> **Wichtig:** `remain` wird nur für **echte Bambu-RFID-Spulen** gepflegt. Fremdspulen ohne
> gültige RFID haben `tag_uid == "0"`/leer und kein verlässliches `remain` → in der Bridge
> ausfiltern (`is_valid_tag_uid`: nicht nur Nullen).

### 2.3 Mehrere AMS / mehrere Drucker

- AMS-Geräte liegen unter `print.ams.ams[]` mit eigener `id` (deine 2× AMS 2 Pro → zwei Einträge,
  je 4 Trays). Slot-Schlüssel = `(device_serial, ams_id, tray_id)`.
- Pro Drucker eine eigene MQTT-Verbindung (eigene `SERIAL` + Access Code).

---

## 3. Transport: LAN primär, Cloud-MQTT als Fallback

### 3.1 LAN-MQTT (primär)

- Endpoint: `mqtts://<drucker-ip>:8883` (TLS, Zertifikat des Druckers ist self-signed → CA-Check
  i. d. R. deaktivieren/Pinning auf Geräte-Cert).
- **User:** `bblp`  **Passwort:** **Access Code** (Druckerdisplay → Einstellungen → WLAN/LAN).
- Voraussetzung: Drucker im LAN erreichbar; „LAN Mode" bzw. lokaler Zugriff aktiv.
- Vorteil: kein Token-Ablauf, keine Cloud-Abhängigkeit, niedrige Latenz.

### 3.2 Cloud-MQTT (Fallback)

- Broker: `us.mqtt.bambulab.com:8883` (Global/EU) bzw. `cn.mqtt.bambulab.com:8883` (China).
- Auth über Account-Token (siehe `filament-cloud-api-analysis-spec.md` §1.5: `get_my_token`).
- **EU-Konto:** gehört zur „Global"-Region → **`api.bambulab.com` / `us.mqtt.bambulab.com`**
  (es gibt kein eigenes `.eu`). Region ggf. aus dem JWT-Payload bestätigen.
- Nutzung nur, wenn LAN nicht verfügbar (Reconnect-Strategie: LAN bevorzugen, bei n
  fehlgeschlagenen LAN-Verbindungen auf Cloud schwenken, regelmäßig LAN erneut probieren).

### 3.3 Konfiguration (Beispiel `config.yaml`)

```yaml
printers:
  - name: x1c-werkstatt
    serial: "00M00A2B0123456"
    transport: auto            # auto | lan | cloud
    lan:
      host: 192.168.1.50
      access_code: "12345678"
    # cloud-Auth global über bambu_account unten
bambu_account:
  region: eu                   # → global-Infra
  token: "<jwt-or-empty>"
spoolman:
  base_url: "http://spoolman:7912"
  rfid_field: "bambu_rfid"     # Spoolman Extra-Field (siehe §4.2)
consumption:
  mode: combined               # per_job | remain | combined
  reconcile_on_unload: true
```

---

## 4. Spoolman-Datenmodell & Mapping

### 4.1 Modell-Abbildung

Spoolman: **Vendor → Filament → Spool**. Das passt 1:1:

- Ein **Filament** = eine Sorte/Farbe, in deiner App z. B. „PLA Basic Grau **#60**".
  Diese hast du bereits mit der **#Zahl** in Spoolman angelegt.
- Eine **Spool** = eine **physische Rolle** = **eine RFID** (`tag_uid`).
  (In der App sichtbar als „12 Rollen (9808 g)" unter einem Filament.)

→ Die Bridge verwaltet **RFID → Spoolman-Spool-ID**. Die #Zahl ist der **menschliche** Anker
beim Onboarding, die RFID der **maschinelle** Anker im Betrieb.

### 4.1.1 Zwei Ebenen: Filament (Sorte) *und* Spool (Rolle) anlegen

Onboarding hat **zwei** Stufen — und die Bridge kann beide beschleunigen:

1. **Filament-Sorte fehlt in Spoolman?** → automatisch anlegen aus den Tray-Metadaten
   (`filamentVendor`=„Bambu Lab", `tray_type`, `tray_color`, Name aus `tray_sub_brands` +
   Farbname). So entsteht „PLA Basic Grau" in Spoolman, ohne dass du es manuell anlegst.
2. **Physische Rolle (RFID) fehlt?** → Spool unter dieser Sorte anlegen (§4.1).

> **SKU-/Karton-Scan (App):** Das Scannen des Bambu-Kartons (SKU/QR) ist eine **reine
> Android-App-Funktion** — die SKU taucht **nicht** in der MQTT-Telemetrie oder im offenen
> Code auf. Der **maschinelle Sorten-Anker der Bridge** ist daher `tray_info_idx`
> (Preset-ID, z. B. `GFL99`) + Farbe, nicht die SKU. Der App-Scan bleibt aber nützlich: er
> befüllt schnell **Bambus eigene** Bibliothek, die du dann per Cloud-REST-Import (§6) in
> einem Rutsch nach Spoolman übernehmen kannst. Optional kann die Bridge eine eigene
> **SKU→Attribute-Tabelle** pflegen, falls du SKUs manuell erfassen willst.

### 4.1.2 #Zahl-Konvention

Du legst die Spoolman-ID aktuell **manuell als #Zahl in den Titel**. Die Bridge respektiert
das und kann es automatisieren: beim Auto-Anlegen einer Sorte/Spule wird die Spoolman-ID
(bzw. eine fortlaufende #Zahl) in `name`/`extra` gespiegelt, damit deine bestehende
Benennungslogik erhalten bleibt. Maschinell ist die #Zahl dank RFID-Mapping aber **nicht mehr
zwingend** — sie dient nur noch der menschlichen Lesbarkeit.

### 4.2 RFID-Speicherung in Spoolman

- Empfehlung: in Spoolman ein **Extra-Field** `bambu_rfid` (Typ Text) definieren
  (Settings → Extra fields → Spool) und die `tag_uid` dort ablegen.
- Alternativ das eingebaute `lot_nr`-Feld verwenden (einfacher, aber zweckentfremdet).
- Lookup einer Spule: `GET /api/v1/spool?...` und clientseitig nach `extra.bambu_rfid`
  filtern, plus lokaler SQLite-Cache als schneller Index.

### 4.3 Genutzte Spoolman-Endpoints

| Zweck | Methode/Pfad |
|-------|--------------|
| Filamente listen (#Zahl → filament_id) | `GET /api/v1/filament` |
| **Sorte anlegen** (falls fehlt, §4.1.1 Stufe 1) | `POST /api/v1/filament` `{vendor_id/name, material, color_hex, name, weight}` |
| Spule(n) suchen | `GET /api/v1/spool` (+ clientseitiger Filter auf `extra.bambu_rfid`) |
| Spule anlegen | `POST /api/v1/spool` `{filament_id, initial_weight, extra:{bambu_rfid:"<UID>"}}` |
| Restgewicht setzen (Reconcile) | `PUT /api/v1/spool/{id}` `{remaining_weight: <g>}` |
| Verbrauch buchen (pro Job) | `PUT /api/v1/spool/{id}/use` `{use_weight: <g>}` |
| **AMS-Slot pflegen** (§5.3) | `PUT /api/v1/spool/{id}` `{location: "<printer>/AMS<id>/Slot<n>"}` |

---

## 5. Abläufe

### 5.1 RFID-Onboarding (unbekannte Spule)

```
Spule eingelegt
   └▶ MQTT-Tray mit gültiger tag_uid
        └▶ Bridge: tag_uid in Mapping?  ── ja ──▶ Spoolman-Spool bekannt → §5.2
                                         └─ nein ─▶ Onboarding:
              Web-UI/Notification:
              "Neue Spule <tag_uid> erkannt.
               Material=<tray_type>, Farbe=<tray_color>, Preset=<tray_info_idx>.
               Welche Spoolman-Sorte/#Zahl ist das?"
                 ├▶ Sorte existiert → Nutzer wählt Filament (#Zahl)
                 │     └▶ POST /spool  (neue physische Rolle unter dem Filament)
                 │           └▶ Mapping speichern: tag_uid → spool_id
                 ├▶ Sorte fehlt → "Neue Sorte aus Tray-Daten anlegen?" (§4.1.1 Stufe 1)
                 │     └▶ POST /filament  → danach POST /spool
                 └▶ (optional) Auto-Vorschlag: Match über tray_info_idx + Farbe
```

- **Komfort:** Die Bridge kann anhand `tray_type` + `tray_color` + `tray_info_idx` einen
  **Vorschlag** machen, welche #Zahl passt; der Nutzer bestätigt nur noch. Fehlt die Sorte
  ganz, wird sie auf Wunsch direkt aus den Tray-Metadaten angelegt (§4.1.1).
- Initialgewicht der neuen Spool: aus `tray_weight` (Soll) bzw. `remain% × tray_weight`.

### 5.3 AMS-Slot-Pflege in Spoolman

Spoolman hat pro Spool ein **`location`-Feld** — ideal, um den aktuellen AMS-Slot abzubilden:

```
Tray-Update (tag_uid bekannt)
   └▶ location der Spool setzen: "<printer>/AMS<ams_id>/Slot<tray_id>"
      └▶ alte Belegung desselben Slots (anderer tag_uid) → location dort leeren
Entladen (Slot wird leer / tag_uid wechselt)
   └▶ location der vorigen Spool leeren (oder auf "Lager" setzen) + Reconcile (§5.2)
```

- Quelle der Slot-Belegung = `slot_state`-Tabelle (§7): Schlüssel `(device_serial, ams_id, tray_id)`.
- So siehst du in Spoolman direkt, **welche Rolle gerade in welchem AMS-Slot** steckt — über
  beide AMS 2 Pro hinweg.
- Optional zusätzlich Spoolman-Felder `first_used` (bei erstem Slot-Einsatz) / `last_used`
  (bei jedem Verbrauchs-Event) pflegen.

### 5.2 Verbrauchsmanagement (Modus `combined`)

Kombiniert beide Strategien (du hast „beides" gewählt):

1. **Pro-Job-Abzug (primär, genau):**
   - Druckstart erkennen (Statuswechsel auf RUNNING; aktiver Tray bekannt).
   - Bei Job-Ende den real verbrauchten Gramm-Wert ermitteln
     (aus Job-/Slicer-Schätzung bzw. Gewichtsdifferenz) und
     `PUT /spool/{id}/use {use_weight}` buchen.
2. **remain%-Reconcile (Abgleich, robust):**
   - Bei jedem stabilen `remain`-Update bzw. beim Entladen:
     `remaining_weight = remain% × tray_weight` mit Spoolman abgleichen.
   - Dient als Drift-Korrektur, falls ein Job-Event verpasst wurde.
- **Konfliktregel:** Pro-Job ist führend; Reconcile korrigiert nur, wenn die Abweichung
  eine Schwelle überschreitet (z. B. >3 %), um „Zappeln" zu vermeiden.

---

## 6. Optionale Anreicherung über die Cloud-Filament-Bibliothek (REST)

Nicht zwingend für den Use-Case, aber komfortabel für den **Erstimport** deiner bereits
gepflegten Bibliothek (Namen, #Zahlen, Sollgewichte, RFIDs) nach Spoolman, statt alles manuell.

- Endpoint-Hypothese (siehe Spec-Dokument §1.2.1):
  `GET https://api.bambulab.com/v1/user-service/my/filament/v2`
- Liefert die Spool-Liste inkl. `RFID`, `filamentVendor`, `filamentType`, `color`,
  `totalNetWeight`, `netWeight` → kann initial nach Spoolman gemappt werden
  (Feld-Tabelle: Spec §1.3).
- Pfad ist noch per Capture/Static-Analysis zu bestätigen (Spec §3/§3b).

---

## 7. Persistenz (SQLite-Schema, Entwurf)

```sql
CREATE TABLE spool_map (
    tag_uid        TEXT PRIMARY KEY,   -- RFID-UID
    spoolman_id    INTEGER NOT NULL,
    filament_hint  TEXT,               -- #Zahl / Preset-id zum Zeitpunkt des Onboardings
    created_at     TEXT,
    last_seen_at   TEXT
);
CREATE TABLE slot_state (               -- letzte bekannte Belegung je Slot
    device_serial  TEXT, ams_id INTEGER, tray_id INTEGER,
    tag_uid        TEXT, last_remain INTEGER, updated_at TEXT,
    PRIMARY KEY (device_serial, ams_id, tray_id)
);
CREATE TABLE job_log (                  -- Verbrauchsbuchungen (Idempotenz)
    job_id TEXT PRIMARY KEY, tag_uid TEXT, used_g REAL, booked_at TEXT
);
```

---

## 8. Stolpersteine / offene Punkte

- **`remain` nur bei RFID-Spulen.** Fremdspulen ohne Tag → kein zuverlässiges Tracking
  (Konzept deckt bewusst „zumindest Bambu-Lab-Spulen" ab).
- **LAN-Mode-Voraussetzung.** Neuere Firmware kann lokalen Zugriff einschränken / Bambu
  Connect verlangen. Lesen des Report-Topics funktioniert i. d. R. weiter; Cloud-MQTT ist
  der Fallback.
- **Job-Verbrauch exakt ermitteln** ist die anspruchsvollste Stelle (Quelle: Slicer-Schätzung
  vs. reale Differenz). Im Modus `combined` durch remain%-Reconcile abgefedert.
- **Idempotenz:** Verbrauch nur einmal pro `job_id` buchen (siehe `job_log`).
- **Spool-Wechsel im selben Slot:** Slot-State-Tabelle erkennt `tag_uid`-Wechsel → sauberer
  Übergang (alte Spule final reconcilen, neue ggf. onboarden).
- **MQTT-Reconnect & Vollzustand:** nach jedem Reconnect erneut `pushall` senden.

---

## 9. NFC-Strategie: Bambu- vs. Dritthersteller-Spulen (inkl. PWA-Grenzen)

Entscheidende technische Klärung, weil sie den Onboarding-Weg bestimmt:

- **Bambus RFID = verschlüsselte Mifare Classic.**
- **Web NFC (PWA, Chrome/Edge/Opera/Samsung Internet auf Android) ist NDEF-only** — kann
  Low-Level-Protokolle (ISO-DEP/NFC-A) und damit **Mifare Classic NICHT** lesen/schreiben.
  → **Eine PWA kann Bambus eigene RFID-Tags NICHT auslesen.** Web NFC kann aber **NDEF-Tags
  (OpenSpool/OpenTag) lesen und schreiben.**

Daraus folgt die Aufteilung:

| Fall | Identifikation | Tooling |
|------|----------------|---------|
| **Bambu-Spule im AMS** | `tag_uid` kommt **per MQTT** vom AMS | **kein Handy/NFC nötig** — Kernweg der Bridge |
| **Bambu-Spule vor dem AMS** (Karton-/Erst-Onboarding) | verschlüsselte Mifare → **native App** | **BambuSpoolPal** (Android) oder USB-Reader — **PWA geht hier nicht** |
| **Dritthersteller-Spule** | eigener **NDEF**-Tag | **PWA (Web NFC) kann OpenSpool-Tags schreiben** ✅ — oder manuelle Zuordnung im UI |

### 9.1 Was BambuSpoolPal genau macht

Native Android-App: scannt offizielle **Bambu-RFID-Tags** per NFC und extrahiert
**Identifier, Dichte, Anfangsgewicht, Länge, Farbe** → matcht gegen die Spoolman-Filament-DB
und legt/aktualisiert **Spool-Datensätze in Spoolman** an. Voraussetzungen: NFC-Android-Gerät,
Spoolman-Instanz, HTTPS. Hinweis: mind. ~2 s pro Scan, sonst Lesefehler. Optional KI-basierte
Gewichtserkennung per Kamera. → Ideal für **dein Karton-/Erst-Onboarding** per Handy.

### 9.2 Rolle der PWA in unserem Projekt

- **Onboarding-/Bedien-UI** der Bridge als **PWA** (mobil bedienbar, „neue Spule zuordnen").
- **Web NFC nur für Dritthersteller**: in der PWA „Tag schreiben" → OpenSpool-NDEF-JSON
  (`protocol`, `version`, `type`, `color_hex`, `brand`, `min_temp`, `max_temp`) auf NTAG-215/216
  schreiben, Spoolman-ID/#Zahl mit einbetten.
- **Bambu-Tag-Lesen** bleibt **MQTT (im AMS)** bzw. **native App (vor dem AMS)** — nicht PWA.

---

## 10. Etikettendruck-Integration (Printer Hub / Brother)

Onboarding-Hook: sobald eine Spool angelegt/zugeordnet ist, ruft die Bridge dein
**Printer-Hub-Projekt** auf, um auf dem **Brother-Etikettendrucker** ein Label zu drucken.

- **Trigger:** nach `POST /spool` (neue Rolle) bzw. auf Knopfdruck in der PWA.
- **Label-Inhalt (Vorschlag):** **#Zahl**, Material + Farbe, ggf. RFID-`tag_uid`, und ein
  **QR-Code** auf die Spoolman-Spool-URL (`/spool/{id}`) für schnelles Wiederfinden/Scannen.
- **Anbindung:** generischer **Webhook/REST-Call** an die Printer-Hub-API (konfigurierbar in
  `config.yaml`, z. B. `label_printer.webhook_url` + Template-Feldmapping).
- **Offen:** API/Endpoint deines Printer-Hub-Projekts — Repo/Schnittstelle bitte nennen, dann
  wird der konkrete Call hier spezifiziert.

---

## 11. Build-vs-Adopt & Upstream-Strategie

`drndos/openspoolman` deckt den Kern bereits ab → **nicht bei null starten, sondern forken/erweitern.**

| Schwäche von OpenSpoolMan | Unser Beitrag |
|---|---|
| „Untested with multiple AMS units" | **Multi-AMS** (2× AMS 2 Pro) über Slot-Schlüssel `(device_serial, ams_id, tray_id)` |
| Voller Gewichtsabzug bei Druckstart (auch bei Fehldruck) | **`combined`-Verbrauch** mit `remain%`-Reconcile (§5.2) |
| LAN-only | **Cloud-MQTT-Fallback** (§3.2) |
| Match nur über `tray_type` | **Zwei-Ebenen-Onboarding** + Filament-Auto-Create (§4.1.1) |
| — | **Etikettendruck-Hook** (§10), **PWA-Dritthersteller-Tags** (§9.2) |

**Vorgehen (Upstream-first):**
1. **Lizenz prüfen** von `drndos/openspoolman` (bestimmt, ob/wie wir forken & beitragen dürfen).
2. Auf eigenem **Fork** entwickeln, Features klein & abgegrenzt halten.
3. Pro Feature **Upstream-PR** anbieten (Multi-AMS, Reconcile, Cloud-Fallback).
4. Wird es angenommen → Upstream nutzen; sonst **Fork pflegen** (Rebase-fähig halten).

---

## 12. Referenzen

- Schwester-Spec (Cloud-REST/Endpoints): `docs/filament-cloud-api-analysis-spec.md`
- AMS-Tray-Felder im Quellcode: `src/slic3r/GUI/DeviceManager.cpp` (Tray-Parsing ~Z. 4100–4217),
  `command_ams_filament_settings` (`DeviceManager.cpp:1667`), `pushall` (`:1314`).
- Lokales Spool-Schema (Mapping-Vorlage): `src/slic3r/GUI/fila_manager/wgtFilaManagerStore.h`.
- Spoolman REST-API: offizielle Spoolman-Doku (`/api/v1/...`).
- **Basis-Projekt (Fork-Kandidat):** `drndos/openspoolman` (Python/Docker, MQTT-LAN→Spoolman).
- **Bambu-RFID per Handy:** `MrBambuSpoolPal` (Android, Bambu-Tags → Spoolman).
- **Offener NFC-Tag-Standard (Dritthersteller):** `spuder/OpenSpool` (NDEF, ESP32+PN532).
- Community-Referenzen für Bambu-MQTT-Parsing: `pybambu`, `bambulabs-api`,
  Home-Assistant-Bambu-Integration.
- Web NFC (PWA): NDEF-only, kein Mifare Classic → Bambu-Tags nicht per Browser lesbar.
