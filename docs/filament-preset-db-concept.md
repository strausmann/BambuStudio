# Konzept: Filament-Preset-Datenbank + Preset-Sync ins Bambu-Konto

> Antwort auf: „Gibt es Erfahrungen/Datenbanken für Filament-Presets? Wie füge ich ein Preset
> (Hersteller/Typ/Farbe/K-Wert) hinzu, via API + Docker, idealerweise aus einer Online-DB?"

## 1. Wichtige Klarstellung: Preset ≠ K-Wert

Es gibt **zwei getrennte Ebenen**, die oft verwechselt werden:

| | **Filament-Preset (statisch)** | **K-Wert / Pressure Advance (Kalibrierung)** |
|---|---|---|
| Inhalt | Hersteller, Typ, Farbe, Temps, `filament_flow_ratio`, Dichte, Durchmesser, `filament_id` | Pressure Advance (k), Flow-Dynamics — **pro Filament + Düse + Drucker** |
| Wo gespeichert | Slicer-Preset-JSON; synct als **User-Preset** ins Konto | **Drucker-Kalibriertabelle** (`cali_idx`), nicht im Preset; cloud-synced |
| Bambu-Besonderheit | Bambu-Presets enthalten **kein** `pressure_advance` (nur `filament_flow_ratio`) | K wird per **Flow-Dynamics-Kalibrierung** am Drucker gesetzt, Tray referenziert `cali_idx` |
| OrcaSlicer/Generic | `pressure_advance` **kann** im Filament-Preset stehen | dito, je nach Drucker |

→ **„K-Wert tracken"** heißt: pro (Hersteller, Typ, ggf. Düse) einen kalibrierten k speichern und
ihn entweder (a) in der Drucker-Kalibrierung setzen (MQTT, `cali_idx`) oder (b) bei
Klipper-/Generic-Workflows ins Preset schreiben. Im Bambu-AMS sahen wir `cali_idx` bereits am Tray.

## 2. Gibt es schon Datenbanken? — Ja, mehrere

- **BambuStudio-Bundle (DIESES Repo):** `resources/profiles/<Vendor>/filament/*.json` (2122
  Dateien), via `inherits` verkettet → `scripts/build_catalog.py` ergab **1927 Katalog-Einträge**.
  - **Achtung:** Das ist **inkl. Düsen-/Drucker-Varianten** (z. B. „Bambu PLA Basic @BBL A1",
    „… @BBL A1 0.2 nozzle", „… @BBL H2C" zählen einzeln) → **nicht** 1927 distinkte Filamente.
  - `filament_vendor`-Verteilung: **Bambu Lab 1095, QIDI 640, Generic 85, Polymaker 64,
    Overture 30, eSUN 13**. (Verzeichnisnamen wie Anker/Creality/Elegoo/Prusa ≠ `filament_vendor`;
    deren Profile sind meist Maschinen-/Prozess-Profile bzw. erben Vendor „Bambu Lab"/„Generic".)
  - **OrcaSlicer-Repo** deckt deutlich **mehr echte Hersteller** ab → besserer Seed für Vendor-Breite.
- **OrcaSlicer-Profile** (`SoftFever/OrcaSlicer`, `resources/profiles/`): die **größte offene**
  Preset-DB (viele weitere Vendor + Generic) — idealer zusätzlicher Seed.
- **Bambu-Cloud filament-config** (`get_filament_config`): Marken-/Typ-**Katalog** des Kontos
  (was der Filament Manager zeigt).
- **SpoolmanDB (Online-DB für Spoolman):** `Donkie/SpoolmanDB`
  (https://donkie.github.io/SpoolmanDB/) — zentrale Hersteller-/Filament-DB im Spoolman-Format.
  Dazu gibt es einen **fertigen Docker-Importer** `fwartner/spoolman-importer`, der Vendors +
  Filamente daraus in deine Spoolman-Instanz anlegt. → **Für die Spoolman-Seite nichts neu bauen:
  SpoolmanDB + Importer nutzen.** (Bestätigt — der Nutzer lag richtig.)
- **Spoolman selbst:** Inventar-DB; speichert pro Filament Vendor/Material/Dichte/Durchmesser/
  Farbe/Temps + **Extra-Fields** (dort legen wir `k_value`/`cali_idx` ab).
- Community: `filamentcolors.xyz` (Farben), OpenTag (Tag-Spec/DB), `filaman.app` — kein k-Fokus.

> Eine **einzige** maßgebliche „Online-DB mit K-Werten pro Vendor" gibt es nicht — weil k
> drucker-/düsenspezifisch ist. OrcaSlicer-Repo ist die beste Preset-Basis; die k-Ebene bauen
> wir selbst (unsere Kalibrierwerte).

## 3. Ein Preset hinzufügen — Format (Bambu/Orca)

Presets sind JSON mit `inherits`-Kette (Nozzle-Variante → `@base` → `fdm_filament_<typ>`).
Minimal für ein neues Vendor-Filament:

```json
{
  "type": "filament",
  "name": "eSUN PLA+ Grün @BBL X1C",
  "inherits": "fdm_filament_pla",
  "filament_vendor": ["eSUN"],
  "filament_type": ["PLA"],
  "filament_id": ["P<eigene-id>"],
  "nozzle_temperature": ["215"],
  "hot_plate_temp": ["60"],
  "filament_flow_ratio": ["0.98"],
  "filament_density": ["1.24"],
  "filament_diameter": ["1.75"],
  "filament_max_volumetric_speed": ["12"],
  "default_filament_colour": ["#00AE42"],
  "compatible_printers": ["Bambu Lab X1 Carbon 0.4 nozzle"]
}
```
- **Supporteter Weg ins Konto:** in Bambu Studio importieren/anlegen → als User-Preset speichern
  → **Auto-Cloud-Sync** (Spec §1.6). Kein RE nötig.
- **Per API:** `put_setting` (Plugin-Export bestätigt) → Route-Familie
  `/v1/iot-service/api/slicer/setting`. Endpoint/Body erst per Capture bestätigen (Spec).

## 4. Architektur: eigene Katalog-DB + Docker-Tool + Online-Feed

```
[Online-Katalog-DB]            (git-Repo aus JSON  ODER kleiner REST-Service)
  vendor/type/color/hex/temps/flow/density/diameter/recommended_k/source/notes
        │  (seed: OrcaSlicer + Bambu-Bundle via build_catalog.py + eigene Kalibrierungen)
        ▼
[preset-tool  (Docker)]
  ├─ generiert Bambu/Orca-Preset-JSON (inherits → richtige Basis)
  ├─ push ins Konto via put_setting  (nach RE)   ── ODER ── Export zum manuellen Import
  ├─ legt/aktualisiert Spoolman-Filament an (k als Extra-Field)
  └─ (optional) setzt Flow-Dynamics/k am Drucker via MQTT (cali_idx)
        ▼
[Bambu-Konto / Spoolman / Drucker]
```

- **Idempotent:** Presets über `name`/`filament_id` erkennen; Spoolman über vorhandene Felder.
- **Online-Feed:** Katalog als versioniertes JSON-Repo (einfach, diffbar, PR-fähig) — bei Bedarf
  später ein kleiner FastAPI-Service mit `/catalog`-Endpoint.
- **Wiederverwendung:** baut auf der bestehenden `tools/bambu-spoolman-bridge` auf (gleicher
  Spoolman-Client, gleiche Docker-Logik).

## 5. Schema der eigenen DB (Seed liegt schon vor)

`catalog.json` (von `build_catalog.py`), pro Eintrag:
`name, vendor, type, filament_id, flow_ratio, density, diameter, nozzle_temp, bed_temp,
max_vol_speed, color_hex, k_value(null→eigene Kalibrierung)`.

→ **Erweitern um:** `color_name`, mehrere `k_value` pro Düse (0.2/0.4/0.6/0.8), `source`,
`verified`, `notes`. Damit ist die DB sofort nutzbar und wächst mit deinen Kalibrierungen.

## 6. Erscheinen die Filamente im Drucker-Display (AMS-Slot-Auswahl)?

**Ja** — die Filamentliste, die der Drucker bei der AMS-Slot-Zuordnung am **Display** zeigt, ist
die **vom Bambu-Konto synchronisierte** Preset-Liste (Bambu-System-Presets + deine **User-Presets**).
Sobald ein Dritthersteller-Preset als **User-Preset im Konto** liegt, taucht es dort (unter
„Custom"/Benutzer) auf und ist auswählbar — genau für deinen Workflow (Fremdspule einlegen → am
Display das passende Filament wählen).

- **Zuverlässiger Weg:** in Bambu Studio als User-Preset speichern → Auto-Cloud-Sync → Display.
- **Automatisierbar:** per `put_setting`-API (Endpoint via Capture bestätigen).
- Hinweis: RFID-Auto-Erkennung bleibt Bambu-Spulen vorbehalten; Fremdfilament wählst du aus der
  (jetzt größeren) Liste manuell.

## 7. Tool-UX: Hersteller + Typ wählen → anlegen

Geplanter Ablauf im Tool (baut auf `tools/bambu-spoolman-bridge` auf):
1. **Auswahl:** Hersteller (eSUN, Polymaker, …) + Typ (PLA/PETG/…) — Quelle: **SpoolmanDB**
   (Spoolman-Filamente) **+** unser `catalog.json` (Bambu `filament_id` + Flow/Temps fürs Preset).
2. **Anlegen:**
   - **Spoolman-Filamente** via SpoolmanDB/`spoolman-importer` bzw. Spoolman-REST.
   - **Bambu-Preset** (für Display) aus `catalog.json` generieren → Studio-Import / `put_setting`.
3. **Verwenden:** Fremdspule onboarden (RFID-Bind/QR) → Spool referenziert die richtige Sorte.

## 8. cali_idx / k-Wert überwachen — **k-Lesen implementiert**

**Wichtiger Fund:** Der AMS-Tray liefert im `push_status` nicht nur `cali_idx`, sondern **`k` und
`n` direkt** (`DeviceManager.cpp:4097`). Lesen ist also fast geschenkt — kein Extra-Request nötig.

Die Bridge liest jetzt pro Tray **`cali_idx`, `k`, `n`** und schreibt bei Änderung in die
Spoolman-Spule die Extra-Felder **`cali_idx`**, **`calibrated`**, **`k_value`**, **`n_coef`**.
So siehst du je geladener Spule den **echten k-Wert** und ob am Drucker kalibriert ist.

**Was davon ist „offen"? — präzise:**
- ✅ **k der geladenen Spule lesen** — erledigt (aus dem Tray).
- ⛔ **Volle PA-Tabelle lesen** (auch für *nicht* geladene Filamente): braucht den Request
  `extrusion_cali_get` + Parsen der Async-Antwort `extrusion_cali_get_result` — **noch nicht
  implementiert** (optional; nur nötig, wenn man die ganze Tabelle will, nicht nur Geladenes).
- ⛔ **k *setzen*/schreiben** vom Tool: Payload ist bekannt (`extrusion_cali_set` mit `k_value`,
  `n_coef` — Bambu fixiert `n=1.4`; bzw. Batch `command_set_pa_calibration`) — **nicht
  implementiert**; Schreibpfad ggf. **LAN/Developer-Mode-abhängig** (beim Capture verifizieren),
  und überschreibt aktiv die Drucker-Kalibrierung → vorsichtiger als Lesen.
- ⛔ **k in der Katalog-DB pflegen** pro (Vendor/Typ/Düse): `catalog.json` hat noch `k_value=null`;
  ein Mechanismus „beobachtetes k aus Spoolman → Katalog zurückschreiben" fehlt.
- ℹ️ **n** wird von Bambu beim Setzen fix auf **1.4** gesetzt (nicht frei) — relevant fürs Schreiben.

### 8.1 Prozess: cali_idx / k-Wert am Drucker erstellen (Flow Dynamics / Pressure Advance)

**In Bambu Studio (Standardweg):**
1. **Kalibrierung → „Dynamischer Fluss" / Flow Dynamics (Pressure Advance)**.
2. Drucker, **Düsendurchmesser** und das/die geladenen **Filament(e)** wählen → **Start**.
3. **X1/X1C:** misst k automatisch per Lidar. **P1/A1:** druckt ein Test-Muster → beste Linie
   wählen (oder Auto). Ergebnis = **k** (und `n`).
4. **Speichern unter Namen** → der Eintrag landet in der **PA-Tabelle des Druckers** mit einem
   `cali_idx`, gebunden an `setting_id` (= Filament-Preset) **+ Düsendurchmesser**.
5. Beim Einlegen einer Spule **dieses Filaments** matcht der Drucker per `setting_id` und wendet
   die Kalibrierung automatisch an → der Tray meldet den `cali_idx` (das liest unsere Bridge).
- **Manuell:** Geräte-/AMS-Material-Einstellung → **k direkt eingeben** (intern
  `command_extrusion_cali_set(tray, setting_id, name, k, n, …)`).
- **Programmatisch (unser Tool, MQTT):** `command_start_pa_calibration` →
  `command_set_pa_calibration(PACalibResult{k,n,setting_id,name,nozzle_diameter})` →
  `command_get_pa_calibration_tab` / `command_select_pa_calibration(cali_idx)`.
  *(Auf neuerer Firmware ggf. LAN-/Developer-Mode-abhängig — beim Capture verifizieren.)*

**Geltungsbereich — gilt der k pro Spule oder pro Filament?**
- **Pro Filament(-Preset) + Düsendurchmesser — NICHT pro physischer Spule.**
- Eine Kalibrierung für **„Bambu PLA Basic" @0.4** gilt für **alle Farben** dieses Filaments
  (Grau, Rot, …) und **alle Spulen** davon. **Nicht** pro neuer Spule wiederholen. Farbe hat
  i. d. R. **vernachlässigbaren** Einfluss auf k.
- **Neu kalibrieren** nur bei: **Düsenwechsel (Größe)**, **deutlich anderem Material/Marke**
  (z. B. PLA Matte vs PLA Basic vs PLA-CF; eSUN vs Bambu), oder sichtbaren PA-Artefakten.
- Bambu hält **mehrere** Einträge (je Filament+Düse); das AMS wählt automatisch den passenden
  via `setting_id` → daher der `cali_idx` am Tray.

→ Für unsere Katalog-DB heißt das: **ein `k_value` pro (Vendor/Typ/Düse)** genügt — nicht pro Spule.

## 9. Lizenzen: dürfen wir die Presets kopieren?

| Quelle | Lizenz | Verwenden/Anpassen | Weiterverteilen |
|--------|--------|--------------------|-----------------|
| **OrcaSlicer-Profile** | **AGPL-3.0** | ✅ | nur unter **AGPL-3.0** (Copyleft + Quelloffenlegung, auch „über Server") + Attribution |
| **BambuStudio-Profile** (dieses Repo) | **AGPL-3.0** | ✅ | dito |
| **SpoolmanDB** | **MIT** | ✅ | ✅ sehr frei (nur Copyright-/Lizenzhinweis behalten) |

**Konsequenzen:**
- **OrcaSlicer-Presets „einfach kopieren": ja zum Nutzen/Anpassen** — aber **Weiterverteilen löst
  AGPL-3.0 aus** (Tool/Repo muss AGPL-kompatibel sein und Quelle bereitstellen).
- **Da unser Tool ohnehin in diesem AGPL-3.0-Repo lebt, ist das Bundeln/Ableiten AGPL-konsistent**
  (Attribution nicht vergessen). Für ein **permissiv** lizenziertes Standalone-Tool die
  AGPL-Profile **nicht** bundlen — stattdessen zur Laufzeit aus der lokalen Studio/Orca-Installation
  des Nutzers lesen (keine Weiterverteilung) **oder** nur **SpoolmanDB (MIT)** nutzen.
- **Reine Fakten** (Temperatur, Dichte) sind nicht urheberrechtlich schützbar; die **JSON-Dateien
  + die Zusammenstellung** aber schon → im Zweifel **AGPL behandeln**.

**Empfehlung (sauber & lizenzkonform):**
- **Spoolman-Seite:** **SpoolmanDB (MIT)** → unkompliziert in jedes Tool.
- **Bambu-Preset-Seite:** Katalog/Generator **in diesem AGPL-Repo** halten (passt), oder Presets
  beim Nutzer lokal aus Studio/Orca lesen statt sie zu redistribuieren.

## 10. Status / nächste Schritte

- [x] Seed-Katalog aus Repo-Profilen (`build_catalog.py`, 1927 Einträge).
- [x] k/cali-Tracking pro Spule → Spoolman-Extra `cali_idx`/`calibrated`/`k_value`/`n_coef` (aus MQTT-Tray).
- [ ] Spoolman-Anlage nach Hersteller/Typ über **SpoolmanDB + `spoolman-importer`** (kein Eigenbau).
- [ ] OrcaSlicer-Profile als zusätzlichen Seed einlesen (mehr Vendor).
- [ ] Preset-Generator (Katalog-Eintrag → Bambu/Orca-JSON) für Display/Konto.
- [ ] `put_setting`-Endpoint per Capture bestätigen (Spec) → Preset-Push ins Konto.
- [x] **k lesen** (aus MQTT-Tray) + **k-Katalog** pro (Vendor/Typ/Düse) (`app/kcatalog.py`, `/api/kcatalog`).
- [x] **k setzen** an den Drucker (`/api/cali/set` → `extrusion_cali_set`), gated `ams.allow_k_write`.
- [ ] volle PA-Tabelle (nicht geladene Filamente) lesen; Dev-Mode-Verifikation fürs Schreiben.
