# F-05 — Cloud-Library-Import scharfschalten

**Type:** feature · **Severity:** 🟡 normal · **Area:** import · **Status:** open · **Refs:** app/cloud_library.py, F-03

## Ziel
Nach F-03 den Live-Import der eigenen Cloud-Filamentbibliothek nach Spoolman aktivieren
(Vendor→Filament→Spool, extra-fields, idempotent).

## Aufgaben
- [ ] Bestätigten Endpoint + Auth (Token aus Studio-Login-Mechanik) anbinden
- [ ] Idempotenz über `cloud_id`-extra-field (Update statt Duplikat)
- [ ] Pagination (offset/limit) berücksichtigen (vgl. BR-13)
- [ ] Dry-Run-Modus + Zusammenfassung (added/updated/skipped)

## Akzeptanzkriterien
- [ ] Zweiter Lauf erzeugt keine Duplikate
- [ ] Dry-Run zeigt geplante Änderungen ohne Schreibzugriff
