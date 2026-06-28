# BR-18 — Tailwind Play-CDN → kompiliert

**Type:** chore · **Severity:** 🟡 low · **Area:** web · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-18

## Problem
UI lädt Tailwind vom CDN → offline/LAN unbrauchbar, Drittskript in tokenführender App.

## Lösung
Build-Stage: Tailwind kompiliert ausliefern; CDN-Script entfernen.
