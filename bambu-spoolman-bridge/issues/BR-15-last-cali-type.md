# BR-15 — _last_cali Typannotation falsch

**Type:** chore · **Severity:** 🟡 low · **Area:** code-quality · **Status:** open · **Refs:** docs/review-findings-backlog.md BR-15

## Problem
`_last_cali: dict[str, int]` speichert ein Tupel `(cali_idx, k)`.

## Lösung
Annotation korrigieren: `dict[str, tuple[int, float | None]]`.
