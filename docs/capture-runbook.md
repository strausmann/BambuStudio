# Runbook: Bambu-Cloud-Filament-API per mitmproxy aufzeichnen (Ubuntu Desktop)

> **Für die Claude-Code-Instanz auf der Ubuntu-VM.** Dieses Dokument ist **eigenständig** —
> du brauchst keinen Vorkontext. Ziel: den **Cloud-Endpoint der Bambu-Filament-Bibliothek**
> (Host + Pfad + Request/Response-Body) aufzeichnen, damit der Importer in
> `tools/bambu-spoolman-bridge` „scharf" gestellt werden kann.
>
> **Rollen:** Schritte mit **[AGENT]** führst du (Claude Code) per Shell aus. Schritte mit
> **[MENSCH]** muss der Nutzer in der GUI klicken — fordere ihn dann klar dazu auf und warte.
>
> **Recht/Datenschutz:** Es geht um die **eigenen** Account-Daten (Interoperabilität). Niemals
> Tokens/Cookies/JWT/Account-IDs in Chat/Repo posten — nur Methoden, Hosts, Pfade, Feldnamen.

---

## 0. Voraussetzungen

- Ubuntu Desktop (VM), Internetzugang, ein **Bambu-Konto** (EU/Global).
- Bambu Studio (Linux) – Installation in Schritt 2.
- Drucker ist **nicht** zwingend nötig (die Filament-Bibliothek ist accountbasiert).

## 1. [AGENT] Tools + Repo

```bash
sudo apt update
sudo apt install -y pipx git curl libfuse2 jq
pipx install mitmproxy || python3 -m pip install --user mitmproxy
# Repo mit dem Tool + Capture-Addon holen (Branch mit der Bridge):
git clone -b claude/dazzling-sagan-vdro2v <DEIN_REPO_REMOTE> ~/bambu || true
ls ~/bambu/tools/bambu-spoolman-bridge/scripts/mitm_bambu_addon.py
mkdir -p ~/capture/captures
```
> Falls kein Repo-Remote vorhanden: die Datei `mitm_bambu_addon.py` ist klein — notfalls aus
> dem Repo kopieren. Sie schreibt Treffer nach `captures/`.

## 2. [AGENT] Bambu Studio installieren — AppImage **extrahieren** (wichtig!)

Das AppImage ist zur Laufzeit **read-only** (squashfs) → man kann das Cert-Bundle darin nicht
patchen. Deshalb **extrahieren** und die entpackte Version starten:

```bash
cd ~/bambu-studio 2>/dev/null || mkdir -p ~/bambu-studio && cd ~/bambu-studio
# AppImage von der offiziellen Bambu-Releases-Seite laden (URL der aktuellen Linux-Version):
#   curl -L -o BambuStudio.AppImage "<offizielle_AppImage_URL>"
chmod +x BambuStudio.AppImage
./BambuStudio.AppImage --appimage-extract        # erzeugt ./squashfs-root
# Cert-Bundle finden (Pfad kann je Version variieren):
find ./squashfs-root -name slicer_base64.cer
```
Start später über: `./squashfs-root/AppRun` (siehe Schritt 5).
> Alternativen (auch ok): `.deb`/Flatpak — dann liegt `slicer_base64.cer` unter
> `/usr/share|/opt|~/.local/share/flatpak/...`. Per `sudo find / -name slicer_base64.cer 2>/dev/null`
> lokalisieren. Bei Flatpak ist Patchen wegen Sandbox umständlicher → AppImage-Extract bevorzugen.

## 3. [AGENT] mitmproxy einmal starten (erzeugt die CA), dann stoppen

```bash
cd ~/capture
timeout 5 mitmdump >/dev/null 2>&1 || true     # erzeugt ~/.mitmproxy/mitmproxy-ca-cert.pem
ls -l ~/.mitmproxy/mitmproxy-ca-cert.pem
```

## 4. [AGENT] Cert-Bundle-Trick + System-Trust

```bash
CERT=$(find ~/bambu-studio/squashfs-root -name slicer_base64.cer | head -1)
echo "Bundle: $CERT"
cp "$CERT" "$CERT.bak"                                  # Backup!
cat ~/.mitmproxy/mitmproxy-ca-cert.pem >> "$CERT"       # mitm-CA anhängen (PEM)
grep -c "BEGIN CERTIFICATE" "$CERT"                     # sollte sich um 1 erhöht haben
# Zusätzlich in den System-Trust (schadet nie):
sudo cp ~/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt
sudo update-ca-certificates
```

## 5. [AGENT] Capture starten + Studio über den Proxy starten

Zwei Terminals (oder tmux):

```bash
# Terminal A — mitmproxy mit unserem Addon (Web-UI auf :8081):
cd ~/capture
BAMBU_CAPTURE_DIR=~/capture/captures \
  mitmweb --listen-port 8080 --web-host 127.0.0.1 \
          -s ~/bambu/tools/bambu-spoolman-bridge/scripts/mitm_bambu_addon.py
```
```bash
# Terminal B — Studio MIT Proxy-Env starten (libcurl des Plugins beachtet die Variablen):
HTTPS_PROXY=http://127.0.0.1:8080 HTTP_PROXY=http://127.0.0.1:8080 \
  ~/bambu-studio/squashfs-root/AppRun
```

## 6. [MENSCH] In Bambu Studio auslösen

Bitte den Nutzer (und warte auf Bestätigung):
1. **Mit dem Bambu-Konto einloggen.**
2. **Filament Manager / Filament-Bibliothek öffnen** (synchronisiert die Liste).
3. **Eine Spule hinzufügen oder bearbeiten** und **speichern** (löst Create/Update aus).
4. (optional) **Eine Spule löschen** (löst Delete aus).

## 7. [AGENT] Treffer einsammeln & auswerten

```bash
cd ~/capture/captures
echo "=== Endpunkte (Methode + Pfad + Status) ==="
jq -r '"\(.method)\t\(.host)\(.path)\t\(.status)"' bambu_flows.jsonl | sort -u
echo "=== Filament-Pfade ==="
jq -r 'select(.path|test("filament";"i")) | "\(.method) \(.host)\(.path)"' bambu_flows.jsonl | sort -u
echo "=== Liste-Response gespeichert? ==="
ls -l filament_list.json 2>/dev/null
```
Erwartung: ein `GET …/filament…` (Liste) sowie `POST/PUT/DELETE …` für Create/Update/Delete.
Den **Host + vollständigen Pfad** des Filament-`GET` notieren (Hypothese war
`/v1/user-service/my/filament/v2`).

## 8. [AGENT] Importer testen (ohne Live-Call) + Endpoint eintragen

```bash
cd ~/bambu/tools/bambu-spoolman-bridge
# a) Mapping gegen die echte Antwort testen (kein Token nötig):
#    erst Spoolman-URL/Felder in data/config.yaml setzen (siehe config.example.yaml)
curl -s -X POST localhost:8099/api/cloud/import \
  -H 'Content-Type: application/json' \
  -d "{\"source\":\"file\",\"path\":\"$HOME/capture/captures/filament_list.json\",\"dry_run\":true}" | jq .
# b) bestätigten Pfad eintragen:
#    config.yaml -> cloud_library.endpoint: "<der echte Pfad aus Schritt 7>"
```

## 9. [AGENT] Ergebnisse über GitHub austauschen — **nur Schema, keine Daten**

Der Austausch mit der Design-Session läuft ausschließlich über den Ordner `analysis/`
(Regeln: `analysis/README.md`). **Niemals** Tokens/Cookies/JWT, rohe Flows
(`bambu_flows.jsonl`), `filament_list.json`, Dumps oder echte RFIDs/IDs committen — die
`analysis/.gitignore` blockt das defensiv.

```bash
cd ~/bambu
# Rohflows -> reines Schema (jeder Wert -> <string>/<int>/… ; keine echten Werte):
python3 tools/bambu-spoolman-bridge/scripts/redact_flows.py \
    ~/capture/captures/bambu_flows.jsonl -o analysis/endpoints.schema.json
# analysis/ENDPOINTS.md ausfüllen (Host, Pfade, Query-Keys, Status, Auffälligkeiten — in Worten)
git add analysis/endpoints.schema.json analysis/ENDPOINTS.md
git commit -m "analysis: captured filament endpoint schema (sanitized)"
git push
```

Die Design-Session liest dann `analysis/endpoints.schema.json` + `ENDPOINTS.md`, stellt
`cloud_library.endpoint` ein und antwortet über dieselben Dateien / den Code.

> `filament_list.json` bleibt **lokal** auf der VM und wird **nur lokal** vom Importer
> (`file`-Modus, Schritt 8) genutzt — es verlässt die Maschine nicht.

---

## Troubleshooting

- **Kein Bambu-Traffic in mitmweb:**
  - Studio wirklich aus **Terminal B mit den `*_PROXY`-Variablen** gestartet? (Nicht über Desktop-Icon.)
  - Test: `HTTPS_PROXY=http://127.0.0.1:8080 curl -s https://example.com >/dev/null` → erscheint in mitmweb?
  - Fallback **transparenter Proxy** (App ignoriert Proxy-Env):
    ```bash
    mitmweb --mode transparent --listen-port 8080 -s .../mitm_bambu_addon.py
    sudo sysctl -w net.ipv4.ip_forward=1
    sudo iptables -t nat -A OUTPUT -p tcp --dport 443 -m owner ! --uid-owner $(id -u mitmproxy 2>/dev/null || echo 0) -j REDIRECT --to-port 8080
    ```
- **TLS-Handshake-Fehler / „certificate"-Meldung im Studio-Log:**
  - Cert-Bundle-Trick auf die **richtige** `slicer_base64.cer` angewandt? (`find` erneut; bei
    AppImage nur die **extrahierte** Kopie zählt). PEM ohne BOM angehängt?
  - Wenn es bleibt → **echtes Public-Key-Pinning** möglich. Dann ohne Proxy weiter:
    - `strace -f -e trace=connect -p $(pgrep -f AppRun)` → bestätigt zumindest Host/IP.
    - `SSLKEYLOGFILE=/tmp/keys.log <…>/AppRun` + Wireshark (falls OpenSSL dynamisch).
    - `gcore $(pgrep -f bambu)` → `strings core.* | grep -aiE "bambulab|/v1/|filament"` (entpackte
      URLs liegen im Dump im Klartext).
- **Wiederherstellen:** `cp "$CERT.bak" "$CERT"` setzt das Original-Bundle zurück.

## Sicherheits-/Aufräumhinweise
- Nach der Analyse: Proxy-Env nicht dauerhaft setzen; Cert-Bundle ggf. zurücksichern.
- `bambu_flows.jsonl` kann Header enthalten — das Addon redigiert `authorization/cookie`, aber
  vor dem Teilen trotzdem prüfen.
