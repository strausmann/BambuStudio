# F-08 — PWA Slot-Bind-Flow (Web-UI)

**Type:** feature · **Severity:** 🟡 normal · **Area:** web/pwa · **Status:** open · **Refs:** web/index.html, web/app.js, docs/bambu-spoolman-bridge-concept.md

## Ziel
Web/PWA-Oberfläche zum Binden von Spulen an AMS-Slots (QR/NFC), Anzeige von k-Wert-Status
und Info-Markern für Slots ohne zugeordnetes Profil. Benötigt HTTPS (Pangolin/Traefik/Caddy/NPM).

## Aufgaben
- [ ] Slot-Übersicht (AMS-Identität, Belegung, remain, k-Wert/`calibrated`)
- [ ] Bind-Flow: QR scannen / manuell wählen → Spule↔Slot
- [ ] Info-Marker für Slots ohne Profil/cali_idx
- [ ] PWA-Manifest + Service Worker; HTTPS-Setup dokumentieren
- [ ] API-Key-Handling im Frontend (kein Klartext-Leak)

## Akzeptanzkriterien
- [ ] Bind/Unload über UI funktioniert end-to-end gegen Bridge
- [ ] Installierbar als PWA über HTTPS
