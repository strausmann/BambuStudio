# Spec / Konzept: Analyse der Bambu-Cloud-Endpoints für Filament-Management & RFID

> **Zweck dieses Dokuments**
> Dieses Dokument ist als **Auftrag für eine Claude-Code-Session** gedacht. Es beschreibt,
> *was* analysiert werden soll (die undokumentierte Bambu-Cloud-REST-API für Filament-Spools /
> RFID), *was bereits aus dem BambuStudio-Quellcode bekannt ist* und *wie* der HTTPS-Verkehr
> in einem Lab-Setup abgegriffen und in eine saubere API-Spezifikation überführt wird.
>
> **Endziel:** eine vollständige, verifizierte API-Doku (OpenAPI/Markdown), mit der ein
> externes Tool (z. B. ein Spoolman-Sync) die eigenen Cloud-Spool-Daten lesen/schreiben kann.

---

## 0. Rechtlicher / ethischer Rahmen

- Es geht ausschließlich um den **Zugriff auf die eigenen Account-Daten** (eigene Spools,
  eigene RFIDs) zu Interoperabilitätszwecken (Sync mit Spoolman).
- Es ist eine **private, undokumentierte API** — keine Garantie auf Stabilität.
- Kein Massen-Scraping, keine fremden Accounts, keine Umgehung von Rate-Limits.
- Der verwendete Token ist der **eigene** Bambu-Account-Token.

---

## 1. Hintergrund: Was bereits aus dem Quellcode bekannt ist

Diese Erkenntnisse stammen aus dem BambuStudio-Repo und geben der Analyse-Session einen
**Startpunkt** — Claude muss die Endpoints nicht „blind" suchen, sondern kann gezielt
bestätigen/vervollständigen.

### 1.1 Architektur

- GUI ruft `wgtFilaManagerCloudClient` →  `NetworkAgent::{get,create,update,delete}_filament_spool(s)`.
- `NetworkAgent` lädt die **echten HTTP-Funktionen dynamisch aus dem closed-source-Plugin**
  `libbambu_networking` (`get_network_function("bambu_network_get_filament_spools")` etc.,
  siehe `src/slic3r/Utils/NetworkAgent.cpp:356`).
- **→ Konsequenz:** Host + finaler Pfad stehen NICHT im offenen Code und müssen per
  Traffic-Capture ermittelt werden. Alles andere (Methoden, Felder, Query-Params) ist bekannt.

### 1.2 Bekannte Endpoint-Operationen

| Operation        | HTTP-Methode | Hinweis aus Code                                                              |
|------------------|--------------|-------------------------------------------------------------------------------|
| Liste abrufen    | `GET`        | Query-Params: `category`, `status`, `ids`/`spoolId`, `RFIDs`/`rfid`, `offset`, `limit` |
| Spool anlegen    | `POST`       | Body = CreateFilamentV2Req (siehe Feld-Tabelle)                               |
| Spool ändern     | `PUT`        | Route-Familie **`/my/filament/v2`**, `id` (int64) **im Body**, nicht im Pfad  |
| Spools löschen   | `DELETE`     | Body mit `ids` (int64[]) und/oder `RFIDs` (string[])                          |
| Filament-Config  | `GET`        | Marken-/Typ-Katalog (`get_filament_config`)                                   |

Quellen: `src/slic3r/GUI/fila_manager/wgtFilaManagerCloudClient.cpp`,
`src/slic3r/Utils/bambu_networking.hpp:258` (`FilamentQueryParams`, `FilamentDeleteParams`).

### 1.3 Bekanntes Cloud-JSON-Schema (camelCase) — „FilamentV2"

Abgeleitet aus `wgtFilaManagerCloudSync::spool_to_cloud_json()` und der Pull-Parse-Funktion
(`wgtFilaManagerCloudSync.cpp:160-323`). **Diese Tabelle ist die wichtigste Referenz** —
Claude soll die per Capture beobachteten Felder hiergegen abgleichen und Lücken ergänzen.

| Cloud-Feld (camelCase) | Typ            | Bedeutung / lokales Feld            | Notiz |
|------------------------|----------------|-------------------------------------|-------|
| `id`                   | int64          | Spool-ID (Cloud-PK)                 | bei `PUT` im Body, required |
| `createType`           | string         | `"ams"` (mit gültiger RFID) \| `"manual"` | steuert RFID-Semantik |
| `RFID`                 | string         | RFID-Tag-UID                        | nur gesetzt bei gültiger UID |
| `filamentVendor`       | string         | Marke / `brand`                     | |
| `filamentType`         | string         | Material / `material_type`          | z. B. PLA, PETG |
| `filamentName`         | string         | Anzeigename / `series`              | required; Fallback = filamentType |
| `filamentId`           | string         | Bambu Preset/Setting-ID / `setting_id` | z. B. „GFL99" |
| `isSupport`            | bool           | Support-Material?                   | aus filamentId abgeleitet |
| `color`                | string (hex)   | Primärfarbe / `color_code`          | |
| `colorType`            | int            | 0=gradient, 1=multicolor, 2=single  | |
| `colors`               | string[] (hex) | Mehrfarb-Liste                      | colors[0] == color (Invariante) |
| `trayIdName`           | string         | AMS-Tray-Label                      | |
| `rolls`                | int            | Anzahl Rollen                       | im Code fix = 1 |
| `netWeight`            | int64 (Gramm)  | **aktuelles** Restgewicht (Netto)   | |
| `totalNetWeight`       | int64 (Gramm)  | **Gesamt**-Nettogewicht (volle Rolle) | |
| `status`               | int64          | 0=active, 1=info_needed             | Pull liefert int, Legacy evtl. string |
| `note`                 | string         | Notiz                               | |
| `favorite`             | bool           | Favorit                             | |
| `createdAt`            | int64 (unix s) | Erstellzeit                         | |
| `updatedAt`            | int64 (unix s) | Änderungszeit                       | |

**remain_percent** existiert NICHT in der Cloud — wird lokal aus `netWeight / totalNetWeight * 100` berechnet.

### 1.4 Bekannte Response-Hülle

- Listen-Responses enthalten die Spools unter dem Schlüssel **`filaments`** (Array)
  (`wgtFilaManagerCloudSync.cpp:33`). Paginierung über `offset` / `limit`.

---

## 2. Ziel der Analyse-Session (Deliverables)

Am Ende soll Claude folgende Artefakte erzeugen und ins Repo (Branch) committen:

1. **`docs/bambu-cloud-filament-api.md`** — vollständige Endpoint-Doku:
   - Base-Host(s) pro Region (Global / China)
   - Voller Pfad jeder Operation
   - Auth-Header-Format
   - Query-Parameter (real beobachtet)
   - Request-/Response-Bodies (echte Beispiele, anonymisiert)
   - HTTP-Statuscodes & Fehlerformat
   - Rate-Limit-Header (falls vorhanden)
2. **`docs/bambu-cloud-filament.openapi.yaml`** — maschinenlesbare OpenAPI-3.1-Spec.
3. **Feld-Mapping-Tabelle Cloud ↔ Spoolman** (Vorbereitung des späteren Sync-Tools).
4. **Auth-Flow-Doku**: woher kommt der Token (Cookie `token` von bambulab.com),
   Gültigkeit, Region-Auswahl, Refresh-Verhalten.

> Wichtig: **Alle Tokens, E-Mail-Adressen, RFID-UIDs, Geräte-IDs in den Beispielen
> anonymisieren/redacten**, bevor etwas committet wird.

---

## 3. Lab-Setup (Topologie)

```
┌─────────────────────────┐         ┌──────────────────────────┐
│  Windows 11 PC          │         │  Linux (Ubuntu)          │
│  - Bambu Studio         │  HTTPS  │  - Docker: mitmproxy      │
│  - System-Proxy ──────────────────▶   (Port 8080 + 8081 Web) │
│  - mitm-CA importiert   │  via    │  - Claude Code Session    │
│    (Trusted Root)       │  Proxy  │    analysiert Captures    │
└─────────────────────────┘         └──────────────────────────┘
        gleiches LAN / Subnetz, z. B. 192.168.1.0/24
```

- **mitmproxy** läuft im Docker-Container auf dem Ubuntu-Host (statische IP empfohlen).
- **Bambu Studio (Windows)** wird so konfiguriert, dass es seinen HTTPS-Traffic über den
  Proxy schickt; die mitm-CA wird auf Windows als vertrauenswürdig installiert.
- Die **Claude-Code-Session** läuft auf dem Ubuntu-Host und liest die von mitmproxy
  geschriebenen Capture-Dateien (`.flow` / exportiertes JSON/HAR).

### 3.1 mitmproxy im Docker-Container

```bash
# Capture-Verzeichnis anlegen
mkdir -p ~/bambu-capture && cd ~/bambu-capture

# mitmweb starten (Web-UI auf :8081, Proxy auf :8080),
# Flows persistent in Datei schreiben
docker run --rm -it \
  -p 8080:8080 -p 8081:8081 \
  -v "$PWD:/home/mitmproxy/.mitmproxy" \
  mitmproxy/mitmproxy \
  mitmweb --web-host 0.0.0.0 \
          --save-stream-file /home/mitmproxy/.mitmproxy/bambu.flows \
          --set web_password=changeme
```

- CA-Zertifikat liegt nach dem ersten Start unter
  `~/bambu-capture/mitmproxy-ca-cert.cer` (für Windows-Import).
- Web-UI: `http://<ubuntu-ip>:8081`.
- **Hinweis:** falls Bambu Studio **Certificate Pinning** macht, schlägt die TLS-Interception
  fehl → siehe Abschnitt 6 (Troubleshooting).

### 3.2 Windows 11 konfigurieren

1. CA-Datei `mitmproxy-ca-cert.cer` auf den Windows-PC kopieren.
2. `certmgr.msc` → **Vertrauenswürdige Stammzertifizierungsstellen** → **Zertifikate** →
   importieren. (Alternativ: Doppelklick → „Zertifikat installieren" → Lokaler Computer →
   Speicher „Vertrauenswürdige Stammzertifizierungsstellen".)
3. **System-Proxy** setzen: Einstellungen → Netzwerk & Internet → Proxy →
   „Proxyserver verwenden" → Adresse = `<ubuntu-ip>`, Port = `8080`.
   *(Falls Bambu Studio den System-Proxy ignoriert: Umgebungsvariablen
   `HTTPS_PROXY=http://<ubuntu-ip>:8080` / `HTTP_PROXY=...` testen oder
   Proxifier einsetzen.)*
4. Bambu Studio **neu starten**, damit Proxy + CA greifen.

---

## 4. Capture-Plan: Welche Aktionen in Bambu Studio auslösen

Claude soll die Session anweisen (bzw. der Mensch führt aus), **jede Aktion einzeln und
zeitlich getrennt** auszulösen, damit die Flows eindeutig zuordenbar sind. Vor jeder Aktion
in mitmweb einen Marker/Filter setzen (Uhrzeit notieren).

| # | Aktion in Bambu Studio                                  | Erwartete Operation         | Fokus |
|---|---------------------------------------------------------|-----------------------------|-------|
| 1 | Login (frisch, ausgeloggt → einloggen)                  | Auth / Token-Flow           | `get_my_token`, Token-Format |
| 2 | Filament Manager öffnen                                 | `GET` Liste + `GET` Config  | Pagination, Base-URL |
| 3 | Manuelle Spool **anlegen** (ohne RFID)                  | `POST` create (`createType=manual`) | Body-Felder |
| 4 | Spool **bearbeiten** (Gewicht/Notiz ändern)            | `PUT` update                | id im Body, Patch-Felder |
| 5 | Spool als Favorit markieren                             | `PUT` update                | `favorite` |
| 6 | Mehrfarb-/Gradient-Spool anlegen                        | `POST` create               | `colors[]`, `colorType` |
| 7 | **AMS-Sync mit RFID-Spule** (echte Bambu-Rolle im AMS)  | `POST`/`PUT` (`createType=ams`) | **`RFID`-Feld, RFID-Format** |
| 8 | Spool(s) **löschen**                                    | `DELETE`                    | `ids` vs `RFIDs` |
| 9 | Liste filtern (status/category)                         | `GET` mit Query-Params      | Query-Param-Namen |
| 10| Region wechseln (falls möglich) / China-Account         | Base-Host                   | Global vs CN Host |

> **RFID-Schwerpunkt (Punkte 7):** Hier ist besonders zu dokumentieren, *wie* die RFID-UID
> kodiert ist (Hex-String? Länge?), ob die Cloud zusätzliche RFID-Metadaten (Hersteller-Tag,
> tray_info_idx, Material-Detektion) zurückgibt, und wie `createType=ams` vs `manual` das
> Verhalten ändert.

---

## 5. Pro Endpoint zu extrahieren (Analyse-Checkliste)

Für **jeden** beobachteten Flow soll Claude strukturiert festhalten:

- [ ] **Vollständige URL**: Schema, Host, Port, Pfad
- [ ] **HTTP-Methode**
- [ ] **Request-Header** — insbesondere:
  - `Authorization` (Format: `Bearer <jwt>`? Custom-Header?)
  - `Content-Type`, `User-Agent`, evtl. `X-*`-Custom-Header
- [ ] **Query-Parameter** (Namen + Beispiel-Werte) → mit `FilamentQueryParams` abgleichen
- [ ] **Request-Body** (JSON, vollständig, anonymisiert) → mit Feld-Tabelle §1.3 abgleichen
- [ ] **Response-Status** (200/201/4xx/5xx)
- [ ] **Response-Body** (Struktur, Wrapper-Keys wie `filaments`, Paginierungs-Felder)
- [ ] **Fehlerformat** (Body bei 400/401/403 — wie sieht Fehlermeldung aus?)
- [ ] **Rate-Limit-/Pagination-Header**
- [ ] **Token-Decode**: JWT (Header.Payload.Signature) dekodieren → `exp`, `iss`, Region-Claims
      (NUR den eigenen Token, Payload-Claims dokumentieren, Signatur nicht teilen)

### 5.1 Auswertung der Flows in der Claude-Session (Ubuntu)

Die `bambu.flows`-Datei kann von Claude analysiert werden:

```bash
# Flows als lesbares JSON exportieren (im Container oder mit lokal installiertem mitmproxy)
docker run --rm -v "$PWD:/data" mitmproxy/mitmproxy \
  mitmdump -nr /data/bambu.flows \
  --set flow_detail=4 > /data/bambu-flows.txt

# Nur Filament-relevante Flows filtern
docker run --rm -v "$PWD:/data" mitmproxy/mitmproxy \
  mitmdump -nr /data/bambu.flows "~u filament" --set flow_detail=3
```

Claude soll daraus die Tabellen/OpenAPI in §2 generieren und gegen die bekannten
Code-Felder (§1.3) gegenprüfen — Abweichungen/neue Felder explizit markieren.

---

## 6. Troubleshooting / bekannte Fallstricke

- **Kein Traffic sichtbar / TLS-Fehler in Bambu Studio:** wahrscheinlich **Cert-Pinning**
  in `libbambu_networking`. Optionen:
  - Prüfen, ob nur ein Teil (Account/REST) gepinnt ist und MQTT separat läuft.
  - SSLKEYLOGFILE / andere Interception-Methoden evaluieren.
  - Falls Pinning hart ist: API-Pfade alternativ aus Community-Projekten
    (`pybambu`, `bambulabs-api`) verifizieren und nur die **Felder** per Code (§1.3) bestätigen.
- **Bambu Studio ignoriert System-Proxy:** Proxifier / explizite `HTTPS_PROXY`-Env testen.
- **Token läuft ab (~3 Monate):** im Auth-Doku festhalten, wie er erneuert wird
  (Cookie `token` neu aus dem Browser ziehen).
- **Region falsch:** Global- (`.com`) vs China- (`.cn`) Host strikt trennen.

---

## 7. Konkreter Prompt für die Claude-Code-Session

> Du analysierst die undokumentierte Bambu-Cloud-REST-API für Filament-/Spool-/RFID-Verwaltung.
> Lies dieses Dokument (`docs/filament-cloud-api-analysis-spec.md`) als Auftrag.
> 1. Hilf mir, das mitmproxy-Docker-Setup (§3) zu starten und zu verifizieren.
> 2. Führe mich durch den Capture-Plan (§4) — sag mir bei jedem Schritt, worauf ich achten soll.
> 3. Analysiere die erzeugte `bambu.flows`-Datei (§5.1) und extrahiere pro Endpoint die
>    Felder aus der Checkliste (§5).
> 4. Gleiche alles gegen das bekannte Code-Schema (§1.3) ab und markiere neue/abweichende Felder.
> 5. Erzeuge die Deliverables aus §2 (`bambu-cloud-filament-api.md` + OpenAPI-YAML +
>    Cloud↔Spoolman-Mapping) und committe sie.
> Wichtig: alle Tokens / E-Mails / RFID-UIDs / Geräte-IDs in Beispielen redacten.

---

## 8. Referenzen im BambuStudio-Quellcode

| Was | Datei |
|-----|-------|
| Cloud-Client-Aufrufe (Methoden, Query-Params, `/my/filament/v2`) | `src/slic3r/GUI/fila_manager/wgtFilaManagerCloudClient.cpp` |
| Cloud-JSON-Mapping (create/update/parse, alle Feldnamen) | `src/slic3r/GUI/fila_manager/wgtFilaManagerCloudSync.cpp` |
| Param-Structs (`FilamentQueryParams`, `FilamentDeleteParams`) | `src/slic3r/Utils/bambu_networking.hpp:258` |
| NetworkAgent → closed-source-Plugin-Bindung | `src/slic3r/Utils/NetworkAgent.cpp:356` |
| Lokales Spool-Schema (für Sync-Mapping) | `src/slic3r/GUI/fila_manager/wgtFilaManagerStore.h` / `.cpp` |
| Lokale Datei | `<data_dir>/filament_inventory/spools.json` |
