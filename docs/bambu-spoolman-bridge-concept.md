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

> **Zwei Labels pro Karton (bestätigt aus Fotos):**
> - **Bambu-Originallabel** trägt nur den **SKU-Code** (Bambus maschinenlesbarer Produktcode,
>   identifiziert Sorte = Material+Farbe). Die SKU steckt **nicht** in der MQTT-Telemetrie →
>   maschineller Sorten-Anker der Bridge bleibt `tray_info_idx` + Farbe; die SKU kann optional
>   als zusätzlicher Match-Key / via App genutzt werden.
> - **Selbst gedrucktes Spoolman-Label** (Label-Printer-Hub) mit **QR → Spoolman-Spule**
>   (`/spool/{id}`) + #Zahl + Material/Temps. **Ein Karton = eine physische Rolle = eine
>   Spoolman-Spule.** Dieser QR ist der **schnelle Bind-Schlüssel** beim Einlegen (§5.1).

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
                 ├▶ Auto-Vorschlag: Match über tray_info_idx + Farbe (+ optional SKU)
                 └▶ SCHNELL-BIND: Spoolman-QR vom Karton scannen (PWA)
                       └▶ liefert /spool/{id} direkt → Mapping tag_uid → spool_id
```

> **Schnell-Bind per Karton-QR:** Da dein Spoolman-Label den QR **`/spool/{id}`** trägt
> (eine Rolle = eine Spule), entfällt die Auswahl aus einer Liste: in der PWA beim
> „Neue Spule"-Prompt einfach den **Karton-QR scannen** → die Bridge kennt die exakte
> Spoolman-Spule und verknüpft sie mit der gerade erkannten `tag_uid`. Das ist auch der
> sauberste Weg für **reassigned** Tags (§5.4): QR der Drittanbieter-Spule scannen → binden.

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

### 5.4 RFID-Tag-Lebenszyklus & Wiederverwendung

Realität deines Workflows: Spulen werden **nicht** vorsorglich ins AMS gelegt (Vakuumbeutel,
viele **Refills** ohne Reel). Leere Spulen werden behalten, und **Bambu-RFID-Tags werden
physisch weiterverwendet** — z. B. per gedrucktem Adapter auf **Sunlu-Gen3-Spulen**. Daraus
folgt ein eigenständiges **Tag-Inventar** entkoppelt vom Spulen-Inventar.

**Kernprinzip — `tag_uid` ist nur ein stabiler Identifier, kein Materialnachweis:**
Ein Bambu-Tag ist **read-only verschlüsselt**. Hängt er an einer Sunlu-Spule, meldet das AMS
weiterhin die **alte Bambu-Codierung** (`tray_type`, `tray_color`). → Die Bridge muss bei
**reassigned** Tags **ihre eigene Zuordnung bevorzugen** und die MQTT-Materialfelder ignorieren.

**Tag-Zustände** (`tag_registry`, §7):

| Zustand | Bedeutung |
|---------|-----------|
| `bambu_original` | Tag sitzt noch auf seiner originalen Bambu-Spule/Refill |
| `freed` | Bambu-Filament aufgebraucht, Tag abgenommen → **Pool wiederverwendbarer Tags** |
| `reassigned` | Tag auf Drittanbieter-Spule montiert, zeigt auf eine **andere** Spoolman-Spule |

**Abläufe:**
- **Tag freigeben:** Spule leer → in der PWA „Tag freigeben" → Zustand `freed`,
  Spoolman-Spule archivieren. Der `tag_uid` bleibt im Inventar.
- **Tag neu zuweisen:** PWA „Tag auf Spule montieren" → Drittanbieter-Spoolman-Spule wählen
  (oder neu anlegen) → Zustand `reassigned`, Mapping `tag_uid → neue spool_id`, **Verlauf**
  protokollieren (`tag_history`). **Restmenge auf voll** (= `initial_weight`) setzen.
- **Erkennung beim Einlegen:** kommt ein `tag_uid` per MQTT,
  - `bambu_original` → normaler Bambu-Pfad (§5.1).
  - `reassigned` → Mapping nutzen, **MQTT-Material ignorieren**, ggf. Slot korrigieren (§5.5).
  - `freed` (aber wieder eingelegt, noch nicht neu zugewiesen) → PWA-Prompt „Tag X ist frei —
    auf welche Spule montiert?".

> **Refill-Hinweis:** Refills haben einen **eigenen frischen RFID** → werden wie normale
> Bambu-Spulen behandelt; nur das `spool_weight` (Reel) unterscheidet sich, je nachdem auf
> welche behaltene Leerspule der Refill gesetzt wird.

### 5.5 AMS-Slot-Korrektur per MQTT (für reassigned Tags)

Damit der **Drucker** nicht „Bambu PLA Red" druckt, obwohl Sunlu PETG geladen ist, kann die
Bridge die Slot-Einstellung aktiv überschreiben — analog zu OpenSpool:

- MQTT-Kommando `print.command = "ams_filament_setting"` mit `ams_id`, `tray_id`,
  `tray_info_idx`/`setting_id`, `tray_color`, `tray_type`, `nozzle_temp_min/max`
  (vgl. `MachineObject::command_ams_filament_settings`, `DeviceManager.cpp:1667`).
- Quelle der korrekten Werte: die zugeordnete **Spoolman-Spule** (Material, Farbe, Temps).
- **Voraussetzung:** neuere Firmware braucht **LAN-Mode + Developer-Mode** (OpenSpool-Erkenntnis).
- Optional/aktivierbar (`config.yaml: ams.override_settings: true`).

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
CREATE TABLE tag_registry (             -- Tag-Inventar (entkoppelt vom Spulen-Inventar, §5.4)
    tag_uid        TEXT PRIMARY KEY,
    state          TEXT NOT NULL,       -- bambu_original | freed | reassigned
    current_spool  INTEGER,             -- aktuell zugeordnete Spoolman-Spool-ID (oder NULL)
    origin         TEXT,                -- z.B. ursprüngliche Bambu-Sorte/#Zahl
    freed_at       TEXT, updated_at TEXT
);
CREATE TABLE tag_history (              -- Verlauf der (Neu-)Zuweisungen
    id INTEGER PRIMARY KEY, tag_uid TEXT, spoolman_id INTEGER,
    action TEXT,                        -- assign | free | reassign
    note TEXT, at TEXT
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
- **Reassigned Tags melden falsches Material.** Bambu-Tags sind read-only → ein auf eine
  Sunlu-Spule montierter Tag meldet weiter die alte Bambu-Codierung. Die Bridge **muss** für
  `reassigned` Tags die eigene Zuordnung bevorzugen (§5.4) und kann den Slot per MQTT
  korrigieren (§5.5, nur mit LAN+Developer-Mode).
- **„Voll"-Reset bei Wiederverwendung:** Bambu setzt einen wiederverwendeten Tag i. d. R.
  auf voll und zählt Verbrauch neu; die Bridge spiegelt das, indem sie bei Reassignment die
  Spoolman-Restmenge auf `initial_weight` setzt (interne Buchung führt, nicht das `remain` des
  alten Tags vertrauen).
- **Tag-Identität ≠ Spulen-Identität:** ein leerer/„freed" Tag, der wieder im AMS auftaucht,
  darf **nicht** automatisch als alte Spule getrackt werden → erst Reassignment abfragen.

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

## 10. Etikettendruck-Integration (Label-Printer-Hub / Brother)

Onboarding-Hook: sobald eine Spool angelegt/zugeordnet ist, ruft die Bridge das
**Label-Printer-Hub** (`strausmann/Label-Printer-Hub`) im **Push-Mode (Webhook)** auf und
druckt auf dem **Brother**-Etikettendrucker (PT-/QL-Serie) ein Label.

- **Trigger:** nach `POST /spool` (neue Rolle) bzw. auf Knopfdruck in der PWA.
- **API:** `POST http://<label-hub>:8090/print` — Antwort `200` (synchron) oder `202` +
  `job_id` (asynchron, Status via `GET /jobs/{job_id}`).
- **Beispiel-Payload (direkte Daten):**
  ```json
  {
    "template_id": "spool-qr-12mm",
    "data": {
      "title": "PLA Basic Grau #60",
      "primary_id": "5D585F4000000100",
      "qr_payload": "http://<spoolman>:7912/spool/123",
      "secondary": ["PLA Basic · Grau", "1000 g", "AMS1/Slot2"]
    },
    "options": { "copies": 1, "auto_cut": true }
  }
  ```
- **Feld-Mapping Bridge → Hub:**
  - `title` ← Filamentname inkl. **#Zahl**
  - `primary_id` ← **RFID `tag_uid`** (oder Spoolman-Spool-ID)
  - `qr_payload` ← **Spoolman-Spool-URL** (`/spool/{id}`) zum schnellen Wiederfinden/Scannen
  - `secondary[]` ← Material+Farbe, Sollgewicht, aktueller AMS-Slot
- **Konfiguration** (`config.yaml`):
  ```yaml
  label_printer:
    enabled: true
    base_url: "http://label-hub:8090"
    template_id: "spool-qr-12mm"
    print_on_onboard: true
  ```
- **Hinweis:** Beide Dienste laufen als **Docker-Container im selben Netz** → Aufruf direkt
  über Service-Name. Async-Jobs (`202`) optional via `GET /jobs/{job_id}` quittieren.

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
- **Etikettendruck:** `strausmann/Label-Printer-Hub` (`POST /print` :8090, Brother PT/QL, Docker).
- Community-Referenzen für Bambu-MQTT-Parsing: `pybambu`, `bambulabs-api`,
  Home-Assistant-Bambu-Integration.
- Web NFC (PWA): NDEF-only, kein Mifare Classic → Bambu-Tags nicht per Browser lesbar.
