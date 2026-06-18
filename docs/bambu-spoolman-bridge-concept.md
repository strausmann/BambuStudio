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

> **Harte Abhängigkeiten: NUR Drucker (MQTT) + Spoolman.** Alles andere — Label-Printer-Hub,
> Hangar, Cloud — ist **optional** und per Config abschaltbar. Die Bridge läuft eigenständig.

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

### 2.3 Mehrere AMS / mehrere Drucker + AMS-Identität

- AMS-Geräte liegen unter `print.ams.ams[]` mit eigener `id` (deine 2× AMS 2 Pro → zwei Einträge,
  je 4 Trays). Slot-Schlüssel = `(device_serial, ams_id, tray_id)`.
- Pro Drucker eine eigene MQTT-Verbindung (eigene `SERIAL` + Access Code).

**Mehr als nur „AMS1/AMS2" — via `get_version` (LAN-MQTT, keine Cloud nötig):**
Der Drucker liefert auf `{"info":{"command":"get_version"}}` eine Modulliste mit Einträgen wie
`n3f/0`, `n3f/1` (= **AMS 2 Pro**), `ams/0` (klassisches AMS), `n3s/128` (Single/HT) — jeweils
mit **`sn` (Seriennummer)** und Firmware. Daraus baut die Bridge einen **sprechenden Namen**:
- `config.ams.aliases` (Seriennummer → Wunschname, z. B. „Werkstatt-links"), sonst
- Fallback `"AMS 2 Pro (1234)"` (Typ + SN-Endung), sonst `"AMS0"`.

Typ-Mapping (aus `DevAmsType`, `DevFilaSystem.h`): `ams`→AMS, `n3f`→AMS 2 Pro, `n3s`→AMS HT,
`ams_lite`/`f1`→AMS Lite. **Bonus** (N3F/N3S): Luftfeuchte %, Trocknungs-Restzeit, Temperatur —
optional später als Spool-/Lager-Hinweis nutzbar.

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
  tag_field: "tag"             # Community-Konvention (§4.2), NICHT bambu_rfid
  slot_field: "active_tray"
consumption:
  mode: combined               # per_job | remain | combined
  reconcile_on_unload: true
ams:
  override_settings: false     # kein Developer Mode → MQTT-Slot-Override aus (§5.5)
  aliases:                     # AMS-Seriennummer → Lagerort-Name (§2.3); leer = Auto-Name
    # "AMSSN0001": "Werkstatt-links"
  storage_location: "Lager"    # Lagerort, wenn die Rolle das AMS verlässt (§5.3)
```

---

## 4. Spoolman-Datenmodell & Mapping

### 4.1 Modell-Abbildung

Spoolman: **Vendor → Filament → Spool**. Das passt 1:1:

- Ein **Filament** = eine Sorte/Farbe (z. B. „PLA Basic Rot", „PLA Matte Blau").
- Eine **Spool** = eine **physische Rolle** = **eine RFID** (`tag_uid`) = **eine eigene #Zahl**.

→ **Die #Zahl ist pro physischer Spule, nicht pro Sorte** (bestätigt aus dem Filament Manager:
unter „PLA Matte Blau" liegen einzeln **#65, #66, #67, #68, #69, #70**; unter „PLA Basic Rot"
**#** und **#38**). Jede Rolle ist bereits einzeln in Spoolman angelegt — mit **eigener
Spoolman-Spool-ID (#Zahl), eigenem Label und eigenem QR** — und ebenso einzeln im Bambu
Filament Manager eingetragen. Die Gruppierung „N Rollen" in der App ist reine Sortier-Anzeige
nach Sorte.

→ Die Bridge verwaltet **RFID → Spoolman-Spool-ID**. Die #Zahl ist der **menschliche** Anker
pro Rolle, die RFID der **maschinelle** Anker im Betrieb.

> **RFID-Badge-Beobachtung:** Im Filament Manager tragen nur bereits **im AMS gelesene**
> Spulen das „RFID"-Badge (z. B. #77, #60). Manuell angelegte, aber noch nicht eingelegte
> Spulen (z. B. #38, #65–#70) haben **noch keine RFID** → genau diese Verknüpfung
> (`tag_uid` ↔ #Zahl/Spule) ist die Aufgabe des Bridge-Onboardings (§5.1).

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

Du legst aktuell **pro Spule manuell die #Zahl in den Titel** (= Spoolman-Spool-ID). Die
Bridge respektiert das und kann es automatisieren: beim Auto-Anlegen einer **Spule** wird die
Spoolman-Spool-ID (bzw. die nächste fortlaufende #Zahl) in `name`/`extra` gespiegelt, damit
deine bestehende Benennungs- und Label-Logik erhalten bleibt. Maschinell ist die #Zahl dank
RFID-Mapping aber **nicht mehr zwingend** — sie dient der menschlichen Lesbarkeit und als
Aufdruck auf dem QR-Label.

> **Längenlimit Bambu Filament Manager: max. 30 Zeichen** für das Feld „Filamentname"
> (cloud `filamentName`, beobachtet im UI — erklärt Kürzungen wie „PLA Basic **Sunflow** Yellow").
> Spoolman selbst hat dieses Limit **nicht**. Wenn wir Namen **inkl. #Zahl** erzeugen, die auch
> in Bambus Filament Manager passen sollen (oder beim Cloud-Import, §6), muss die Bridge auf
> **≤ 30 Zeichen kürzen** (z. B. Sorte abkürzen, #Zahl immer erhalten: `…Yellow #32`).

### 4.2 RFID-Speicherung in Spoolman — Community-Konvention (Interop!)

Damit **BambuSpoolPal** (Android) und **OpenSpoolMan** parallel/austauschbar nutzbar sind,
verwenden wir **die gleichen Spoolman-Extra-Fields** wie OpenSpoolMan (de-facto-Standard):

| Ebene | Extra-Field | Inhalt |
|-------|-------------|--------|
| Spool | **`tag`** | RFID/NFC-Tag-UID (`tag_uid`) |
| Spool | **`active_tray`** | aktueller AMS-Slot |
| Filament | **`filament_id`** | Bambu Filament-Preset-ID (z. B. `GFL99`) |
| Filament | **`type`** | Material-Variante (Basic/Matte/CF/…) |
| Filament | **`nozzle_temperature`** | Temperaturbereich °C |

- **Wichtig:** Nicht das frühere `bambu_rfid`/`location` verwenden, sondern **`tag`** und
  **`active_tray`** — sonst sind App und Bridge nicht kompatibel.
- Lookup einer Spule: `GET /api/v1/spool` + clientseitiger Filter auf `extra.tag`,
  plus lokaler SQLite-Cache als schneller Index.

### 4.3 Genutzte Spoolman-Endpoints

| Zweck | Methode/Pfad |
|-------|--------------|
| Filamente listen (Sorte → filament_id) | `GET /api/v1/filament` |
| **Sorte anlegen** (falls fehlt, §4.1.1 Stufe 1) | `POST /api/v1/filament` `{vendor_id/name, material, color_hex, name, weight, extra:{type, nozzle_temperature, filament_id}}` |
| Spule(n) suchen | `GET /api/v1/spool` (+ clientseitiger Filter auf `extra.tag`) |
| Spule anlegen | `POST /api/v1/spool` `{filament_id, initial_weight, extra:{tag:"<UID>"}}` |
| Restgewicht setzen (Reconcile) | `PUT /api/v1/spool/{id}` `{remaining_weight: <g>}` |
| Verbrauch buchen (pro Job) | `PUT /api/v1/spool/{id}/use` `{use_weight: <g>}` |
| **AMS-Slot pflegen** (§5.3) | `PUT /api/v1/spool/{id}` `{extra:{active_tray:"<printer>/AMS<id>/Slot<n>"}}` |

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

### 5.3 AMS-Slot als Spoolman-Lagerort

Der AMS-Slot wird mit dem **sprechenden Namen** aus §2.3 (`<AMS-Name>/Slot<n>`, 1-basiert)
in **zwei** Feldern gepflegt:
- **`location`** (Spoolmans **natives** Lagerort-Feld) → so erscheint die Rolle in Spoolmans
  Standortverwaltung direkt am AMS-Slot („AMS und Slots als Lagerort").
- **`active_tray`** (Extra-Field, Community-Konvention §4.2) → Kompatibilität mit OpenSpoolMan.

```
Einlegen (tag_uid bekannt, Slot vorher anders belegt)
   └▶ HOME merken: aktuellen Spoolman-`location` speichern (spool_home, §7)  ← z.B. Hangar-Code "SMA-022-001"
   └▶ location + active_tray setzen: "Werkstatt-links/Slot2"  (Alias o. "AMS 2 Pro (1234)/Slot2")
Entladen (Slot leer / tag_uid wechselt)
   └▶ vorige Spool: location → **gemerkter HOME-Lagerort** (Fallback config.ams.storage_location),
      active_tray leeren + Reconcile (§5.2)
```

- **Vorheriger Lagerort wird wiederhergestellt:** Beim Einlegen merkt sich die Bridge den
  bisherigen `location` der Spule (`spool_home`-Tabelle, gesetzt nur beim Übergang ins AMS, nicht
  bei jedem MQTT-Tick). Beim Entladen wird **genau dieser** Lagerort-String zurückgeschrieben —
  egal **was** dort stand (ein beliebiger Spoolman-`location`-Text, ein Code wie „SMA-022-001",
  oder leer). Nur wenn kein Home bekannt ist, greift `storage_location` als Default.
- Quelle der Slot-Belegung = `slot_state`-Tabelle (§7): Schlüssel `(device_serial, ams_id, tray_id)`.
- So siehst du in Spoolman direkt, **welche Rolle in welchem (benannten) AMS-Slot** steckt — über
  beide AMS 2 Pro hinweg, mit echten Namen statt „AMS1/AMS2".
- Optional zusätzlich Spoolman-Felder `first_used` / `last_used` pflegen.

> **Harte Abhängigkeiten: nur Drucker (MQTT) + Spoolman.** Die Bridge **funktioniert vollständig
> ohne Hangar** (und ohne Label-Hub). Sie liest/schreibt ausschließlich Spoolmans natives
> `location`-Feld als reinen Text — die Restore-Logik ist inhaltsagnostisch.
>
> **Optional, falls vorhanden — Hangar (`hangar.strausmann.cloud`):** Dein Resolver für
> Snipe-IT/Spoolman/Grocy kann Spoolman als Lagerort-Autorität nutzen (Codes wie `SMA-022-001`,
> „verschieben", Etiketten-Nachdruck). Da die Bridge Spoolmans `location`-Feld pflegt, bleibt eine
> evtl. vorhandene Hangar-Sicht konsistent (im Druck = AMS-Slot, nach Entladen = vorheriger Ort).
> Wer Hangar hat, **kann** den Etikettendruck dorthin auslegen (Dublette vermeiden) — wer nicht,
> nutzt den eingebauten Label-Hook (§10) oder gar keinen. Kein Teil davon ist Pflicht.

### 5.2 Verbrauchsmanagement (Modus `combined`)

**Wichtige Designentscheidung gegen Doppelzählung:** In `combined` ist der **absolute
remain%-Reconcile die Quelle der Wahrheit** für das Spoolman-Restgewicht (Bambus `remain` ist
für RFID-Spulen verlässlich und selbstkorrigierend — auch bei Fehldrucken). Der **Pro-Job-Teil
zählt NICHT zusätzlich ab**, sondern dient der **Historie/Audit**.

1. **remain%-Reconcile (Restgewicht-Autorität):**
   - Bei jedem stabilen `remain`-Update / beim Entladen:
     `remaining_weight = remain% × tray_weight` → Spoolman (`PUT /spool/{id}`).
   - Nur schreiben, wenn die Abweichung `reconcile_threshold_pct` (z. B. 3 %) überschreitet
     (verhindert „Zappeln").
2. **Pro-Job-Tracking (Historie, via `remain`-Differenz):**
   - Druckstart (`gcode_state` → `RUNNING`) erkennen, aktiven Tray (`ams.tray_now`) + dessen
     Rest-Gramm merken; bei Job-Ende (`FINISH`/`FAILED`/`IDLE`) `verbraucht = vorher − nachher`.
   - In `combined`/`remain`: nur in `job_log` schreiben (kein `/use`).
   - In **`per_job`** (ohne Reconcile): `PUT /spool/{id}/use {use_weight}` bucht den Verbrauch.
   - Idempotent über `job_id` (`subtask_id`/`task_id`).
- **Annahmen** (gegen echten Drucker zu verifizieren): `gcode_state`-Werte, `ams.tray_now`
  als globaler Index `ams_id*4 + slot` (255/254 = extern/keiner).

### 5.4 RFID-Tag-Lebenszyklus & Wiederverwendung

Realität deines Workflows: Spulen werden **nicht** vorsorglich ins AMS gelegt (Vakuumbeutel,
viele **Refills** ohne Reel). Leere Spulen werden behalten, und **Bambu-RFID-Tags werden
physisch weiterverwendet** — z. B. per gedrucktem Adapter auf **Sunlu-Gen3-Spulen**. Daraus
folgt ein eigenständiges **Tag-Inventar** entkoppelt vom Spulen-Inventar.

**Kernprinzip — `tag_uid` ist ein stabiler Identifier, die Bambu-Codierung bleibt aber aktiv:**
Ein Bambu-Tag ist **read-only verschlüsselt**. Hängt er an einer Sunlu-Spule, meldet das AMS
weiterhin die **alte Bambu-Codierung** (`tray_type`, `tray_color`) — und **der Drucker druckt
mit diesem Profil**.

> **Primärregel (wegen fehlendem Developer Mode!): Tag nur auf material-/farbgleiche Spule
> wiederverwenden.** Beispiel: ein „PLA Basic White"-Tag → nur wieder auf eine weiße
> PLA-Basic-Spule (Bambu **oder** Sunlu — Sunlu gilt als baugleich/kompatibel). Dann stimmt
> die Bambu-Codierung weiter mit der Realität überein, der Drucker druckt korrekt, und es
> braucht **keine** Slot-Korrektur. **Niemals** einen PLA-Tag auf eine PETG-CF-Spule (falsche
> Temperaturen!). Die Bridge erzwingt das über eine **Kompatibilitätsprüfung** (s. u.).

**Tag-Zustände** (`tag_registry`, §7) — inkl. **gespeicherter Tag-Metadaten** für die Übersicht:

| Zustand | Bedeutung |
|---------|-----------|
| `bambu_original` | Tag sitzt noch auf seiner originalen Bambu-Spule/Refill |
| `freed` | Bambu-Filament aufgebraucht, Tag abgenommen → **Pool wiederverwendbarer Tags** |
| `reassigned` | Tag auf material-/farbgleicher Spule (Bambu/Sunlu) montiert |

Pro Tag werden **Material, Farbe, Temps, Sollgewicht** (aus der ursprünglichen Bambu-Codierung)
gespeichert → die **„Freie Tags"-Übersicht** zeigt z. B. „Tag A1B2 = PLA Basic White, 220 °C"
und lässt eine Neuzuweisung **nur auf kompatible Spulen** zu (Material muss matchen; Farbe als
Warnung). So wird verhindert, dass ein PLA-Tag auf PETG-CF landet — oder umgekehrt.

**Abläufe:**
- **Tag freigeben:** Spule leer → in der PWA „Tag freigeben" → Zustand `freed`,
  Spoolman-Spule archivieren. Tag-Metadaten bleiben erhalten.
- **Tag neu zuweisen:** PWA „Tag auf Spule montieren" → es werden **nur kompatible** Spoolman-
  Spulen angeboten (gleiches Material) → Zustand `reassigned`, Mapping `tag_uid → neue spool_id`,
  **Verlauf** (`tag_history`), **Restmenge auf voll** (= `initial_weight`).
- **Erkennung beim Einlegen:** kommt ein `tag_uid` per MQTT,
  - `bambu_original` / `reassigned` → über Mapping zur Spoolman-Spule (Material stimmt ohnehin).
  - `freed` (wieder eingelegt, noch nicht zugewiesen) → PWA-Prompt „Tag X (PLA White) ist frei —
    auf welche **kompatible** Spule montiert?".

> **Refill-Hinweis:** Refills haben einen **eigenen frischen RFID** → werden wie normale
> Bambu-Spulen behandelt; nur das `spool_weight` (Reel) unterscheidet sich, je nachdem auf
> welche behaltene Leerspule der Refill gesetzt wird.

### 5.5 AMS-Slot-Korrektur per MQTT — NICHT im Standardpfad (kein Developer Mode)

> **Für dieses Setup deaktiviert.** Das aktive Überschreiben der Slot-Einstellung per MQTT
> (`ams_filament_setting`) bräuchte **LAN-Mode + Developer-Mode** — und Developer-Mode
> **deaktiviert die Bambu-Cloud**, was du nicht willst. Deshalb ist die **Parameter-Gleichheit
> bei der Tag-Wiederverwendung (§5.4 Primärregel) der eigentliche Lösungsweg**: Tag nur auf
> material-/farbgleiche Spule → Drucker druckt automatisch korrekt, kein Override nötig.

- **Default:** `ams.override_settings: false` (passt zu deinem Setup).
- Nur als **optionale Funktion** dokumentiert, falls jemand Developer-Mode fährt: MQTT-Kommando
  `print.command = "ams_filament_setting"` (`ams_id`, `tray_id`, `tray_info_idx`/`setting_id`,
  `tray_color`, `tray_type`, `nozzle_temp_min/max`; vgl.
  `MachineObject::command_ams_filament_settings`, `DeviceManager.cpp:1667`).
- **Mismatch-Fallback ohne Override:** weicht ein Tag doch ab, **warnt** die Bridge nur
  (Spoolman-Tracking bleibt korrekt über das Mapping) — die richtige Filament-Auswahl trifft
  man dann **manuell im Slicer** für den Druck.

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

### 6.1 Offene Fragen zur Bambu-Eigenlogik (→ hier wird das Cloud-API-RE relevant)

Zwei Verhaltensfragen lassen sich **nicht** sicher aus dem offenen Code beantworten — sie sind
genau der Grund, warum das **RE der Filament-Cloud-API** (Spec-Dokument) wertvoll bleibt:

1. **Verknüpft Bambu eine neu erkannte RFID mit einer zuvor per Scan/Manuell angelegten Spule —
   oder fragt es danach?**
   - **Status: UNGETESTET.** (Korrektur einer früheren Fehlannahme.) Die Datensätze mit
     RFID-Badge wurden **bereits vor** dem Setzen der #Zahl ins AMS eingelegt; die #Zahl hat der
     Nutzer **nachträglich** durch Ablesen des physischen Spoolman-Labels ergänzt. Die rein
     **manuell** per App angelegten #Zahl-Spulen (z. B. #38) wurden seitdem **noch nicht** ins
     AMS eingelegt → das Zusammenführungs-/Abfrageverhalten ist **noch nicht beobachtet**.
   - „PLA Basic Rot #" (RFID) **und** „#38" (manuell) sind **zwei verschiedene physische Rollen**
     (2 Rollen = 2000 g), **keine** Dublette → daraus lässt sich **nichts** über Bambus
     Merge-Logik ableiten.
   - **Sauberer Test (auszuführen):** eine Spule, die **nur** als manueller #Zahl-Eintrag
     existiert (RFID noch unbekannt), ins AMS einlegen und beobachten, ob Bambu (a) zum Verknüpfen
     **auffordert**, (b) per Heuristik **automatisch zuordnet**, oder (c) einen **separaten**
     `ams`-Record anlegt (Dublette).
   - **Für unsere Bridge ist das Ergebnis unkritisch:** sie verknüpft `tag_uid` ohnehin selbst mit
     der Spoolman-Spule (per QR-Schnellbind, §5.1) — unabhängig davon, was Bambu intern tut.

2. **Wie „vergisst" der Filament Manager die #Zahl↔RFID-Zuweisung, wenn ein Tag (leer) neu
   verwendet wird?**
   - Ebenfalls **ungetestet**; vermutlich über `update`/`delete` auf dem Cloud-Record (vgl.
     Spec §1.2: `PUT`/`DELETE` `/my/filament/v2`). Bestätigung erfordert Capture/RE.
   - **Unsere Unabhängigkeit:** Die Bridge führt ihr **eigenes** `tag_registry`/Mapping (§7) —
     sie ist damit **nicht** davon abhängig, wie Bambu intern auf-/abräumt. Optional kann sie
     über die RE'd Endpoints Bambus Bibliothek **mitpflegen** (Record löschen/aktualisieren),
     ist aber nicht darauf angewiesen.

> **Verifikationsaufträge** (Capture-/RE-Session, Spec-Dokument):
> (a) Nur-manuelle #Zahl-Spule ins AMS einlegen → Abfrage/Merge/Dublette beobachten und den
> begleitenden Cloud-Request mitschneiden. (b) Verhalten bei Tag-Reuse (leerer/neu belegter Tag).

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
    tag_class      TEXT,                -- bambu_readonly | custom_ndef  (§9.3)
    -- Tag-Metadaten (aus Bambu-Codierung) für Übersicht + Kompatibilitätsprüfung:
    meta_material  TEXT,                -- z.B. "PLA Basic"  -> Match-Pflicht bei Reassign
    meta_color     TEXT,                -- z.B. "White"      -> Warnung bei Abweichung
    meta_temp_min  INTEGER, meta_temp_max INTEGER,
    meta_full_g    REAL,                -- Sollgewicht voll
    origin         TEXT,                -- ursprüngliche Bambu-Sorte/#Zahl
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
- **Custom-NDEF-Tags (Dritthersteller): die PWA liest UND schreibt sie** — im **gleichen
  Format wie das ESP32** (OpenSpool-NDEF-JSON: `protocol`, `version`, `type`, `color_hex`,
  `brand`, `min_temp`, `max_temp`; + eingebettete Spoolman-ID/#Zahl). PWA und ESP32 sind damit
  austauschbare Lese-/Schreibstationen für dieselben Tags.
- **Bambu-Tag-Lesen** bleibt **MQTT (im AMS)** bzw. **native App (vor dem AMS)** — nicht PWA
  (Mifare Classic, §9).
- **Voraussetzung Web NFC = HTTPS (Secure Context).** Über eine reine LAN-IP (`http://…`)
  funktioniert Web NFC **nicht**. → Die PWA muss per **HTTPS** erreichbar sein; genau das löst
  die Pangolin-Anbindung (§12) elegant mit.

### 9.3 Zwei Tag-Klassen + ESP32-/OpenSpool-Kompatibilität

Die Bridge unterscheidet zwei Tag-Klassen (`tag_class` in `tag_registry`, §7):

| Klasse | Beispiel | Lesbar/Schreibbar | Wiederverwendung |
|--------|----------|-------------------|------------------|
| `bambu_readonly` | Original-Bambu-Tag | nur **lesen** (AMS→MQTT; native App) | nur auf **material-/farbgleiche** Spule (§5.4) |
| `custom_ndef` | OpenSpool-/OpenTag (NTAG215/216) | **lesen + schreiben** (PWA Web NFC, ESP32) | frei **überschreibbar** — z. B. „Overture PLA Gelb" → „Sunlu PETG White" |

**Eindeutige ID vs. nur Metadaten (wichtig!):**
- Der **OpenSpool-NDEF-Standard enthält nur Metadaten** (`type, color_hex, brand, min_temp,
  max_temp`) — **keine eindeutige Spool-ID**. Er identifiziert also die *Sorte*, nicht die
  *einzelne Rolle*.
- NTAG-Chips haben zwar eine **Hardware-UID**, aber **Web NFC (PWA) liefert sie nicht** (nur
  NDEF) — **nur das ESP32 (PN532)** kann die UID lesen. Sie taugt daher nicht als gemeinsamer
  Schlüssel für PWA **und** ESP32.
- **Lösung:** Wir betten eine **eigene `spoolman_id`** (und optional eine `uid`) **in den
  NDEF-Inhalt** ein. Diese lesen PWA **und** ESP32 gleichermaßen → eindeutige Pro-Rollen-Bindung
  unabhängig von der Hardware-UID. (In der PWA bereits im Schreib-Payload enthalten.)

**ESP32 (OpenSpool-Gerät) als Lese-/Schreibstation:**
- Gedacht zum **Scannen/Beschreiben von Dritthersteller- & Custom-Tags** neben dem Drucker.
- **Interop über das gemeinsame Datenformat:** wir verwenden das **OpenSpool-NDEF-JSON** als
  Tag-Inhalt **und** die Spoolman-Extra-Fields aus §4.2. Dadurch können ESP32, unsere PWA und
  die Bridge **dieselben** Custom-Tags lesen/schreiben.
- **Custom-Tags in Rahmen/Adapter** (gedruckt) wie Bambu-Tags montierbar und **wiederbeschreibbar**;
  bei Umwidmung wird der NDEF-Inhalt neu geschrieben **und** das Spoolman-Mapping aktualisiert.
- **Unsere App liest beide Klassen**: `custom_ndef` direkt (NDEF), `bambu_readonly` über MQTT
  bzw. native App.
- **Lizenz beachten:** das OpenSpool-**Format/Protokoll** ist offen nutzbar; vor Übernahme von
  OpenSpool-**Firmware-Code** dessen Custom-Lizenz (`LICENSE-Software.txt`) prüfen (§11).

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

### 11.1 Lizenzprüfung (Stand der Recherche)

| Projekt | Lizenz | Konsequenz für uns |
|---------|--------|--------------------|
| **`drndos/openspoolman`** | **MIT** ✅ | **Idealer Fork-Basis-Kandidat** — frei forkbar, einfacher Upstream-PR, kombinierbar mit MIT-Code. |
| **`strausmann/Label-Printer-Hub`** | **MIT** ✅ (deins) | frei integrierbar. |
| **`MrBambuSpoolPal`** | **GPL-3.0** ⚠️ | Code-Übernahme erzwingt GPL-3.0. → **Nur Interop** (gleiche Spoolman-Felder §4.2), **keinen Code linken**; App bleibt eigenständig. |
| **`spuder/OpenSpool`** | **Custom/Mehrfach** (HW: OSHWA; SW: `LICENSE-Software.txt`) ⚠️ | **Format/Protokoll** offen nutzbar; vor Übernahme von **Firmware-Code** die Custom-SW-Lizenz genau lesen. |
| **Bambu `libbambu_networking`** | AGPLv3-Streit (closed) ⛔ | nicht einbinden; nur RE-Erkenntnisse aus dem Spec-Dokument nutzen. |

→ **Empfehlung:** Fork von **openspoolman (MIT)** als Basis; BambuSpoolPal & OpenSpool nur über
**offene Datenformate** anbinden (kein Code-Linking). Eigene Beiträge MIT halten.

**Vorgehen (Upstream-first):**
1. **Lizenzen geprüft** (s. o.) → openspoolman MIT ist tragfähig.
2. Auf eigenem **Fork** entwickeln, Features klein & abgegrenzt halten.
3. Pro Feature **Upstream-PR** anbieten (Multi-AMS, Reconcile, Cloud-Fallback, Tag-Lifecycle).
4. Wird es angenommen → Upstream nutzen; sonst **Fork pflegen** (Rebase-fähig halten).

---

## 12. Deployment & Zugriff (Pangolin + SSO)

Die Bridge läuft als **Docker-Container im LAN**; die **Web-UI/PWA** wird bequem und sicher
aufs Handy gebracht über **Pangolin** (self-hosted Reverse-Proxy/Tunnel mit eingebautem SSO).

- **Pangolin „Public Resource"** veröffentlicht die Bridge-UI unter einer echten Domain mit
  **automatischem HTTPS** — was zugleich die **Web-NFC-Voraussetzung (Secure Context, §9.2)**
  erfüllt. Damit funktioniert das **Lesen/Schreiben der Custom-Tags direkt aus der PWA** unterwegs.
- **Pangolin SSO** davor → kein offenes Endpoint im Internet, nur authentifizierter Zugriff.
- **Datenfluss bleibt lokal:** MQTT zum Drucker, Spoolman- und Label-Hub-Calls laufen weiter im
  LAN/Docker-Netz; nur die **UI** wird via Pangolin erreichbar gemacht (kein Cloud-Zwang).
- **Topologie:**
  ```
  Handy (PWA, Web NFC) ──HTTPS+SSO──▶ Pangolin ──▶ Bridge-UI (Docker, LAN)
                                                     │  MQTT → Drucker/AMS
                                                     ├─ REST → Spoolman
                                                     └─ REST → Label-Printer-Hub
  ```
- **Alternativen zu Pangolin:** jeder HTTPS-fähige Reverse-Proxy erfüllt den Web-NFC-Secure-
  Context genauso — **Traefik**, **Nginx Proxy Manager (NPM)** oder **Caddy** (Caddy mit
  Auto-HTTPS am einfachsten). Pangolins Vorteil ist das **eingebaute SSO**; bei Traefik/NPM/Caddy
  ergänzt man Auth bei Bedarf über **Authelia/Authentik** (oder Basic-Auth/mTLS).
  Reine LAN-IP über `http://` scheidet für Web NFC in allen Fällen aus.

---

## 13. Referenzen

- Schwester-Spec (Cloud-REST/Endpoints): `docs/filament-cloud-api-analysis-spec.md`
- AMS-Tray-Felder im Quellcode: `src/slic3r/GUI/DeviceManager.cpp` (Tray-Parsing ~Z. 4100–4217),
  `command_ams_filament_settings` (`DeviceManager.cpp:1667`), `pushall` (`:1314`).
- Lokales Spool-Schema (Mapping-Vorlage): `src/slic3r/GUI/fila_manager/wgtFilaManagerStore.h`.
- Spoolman REST-API: offizielle Spoolman-Doku (`/api/v1/...`).
- **Basis-Projekt (Fork-Kandidat):** `drndos/openspoolman` (Python/Docker, MQTT-LAN→Spoolman).
- **Bambu-RFID per Handy:** `MrBambuSpoolPal` (Android, Bambu-Tags → Spoolman).
- **Offener NFC-Tag-Standard (Dritthersteller):** `spuder/OpenSpool` (NDEF, ESP32+PN532).
- **Etikettendruck:** `strausmann/Label-Printer-Hub` (`POST /print` :8090, Brother PT/QL, Docker).
- **Zugriff/Exposure:** Pangolin (self-hosted Reverse-Proxy/Tunnel + SSO, HTTPS für Web NFC).
- Community-Referenzen für Bambu-MQTT-Parsing: `pybambu`, `bambulabs-api`,
  Home-Assistant-Bambu-Integration.
- Web NFC (PWA): NDEF-only, kein Mifare Classic → Bambu-Tags nicht per Browser lesbar.
