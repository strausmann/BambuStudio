# BR-19 — CORS nicht konfiguriert

**Type:** chore · **Severity:** 🟡 low · **Area:** api · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-19

## Problem
Kein CORS gesetzt; bei Cross-Origin (PWA/ESP32) später nötig.

## Lösung
Bei Bedarf `allow_origins` explizit setzen (kein `*` wegen Auth).
