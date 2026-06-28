# Analysis exchange (between Claude sessions, via GitHub)

This folder is the **only** channel through which the capture/analysis session (Claude Code on
the Ubuntu VM) hands results back to the design session. Everything here is committed to git, so
it must be **sanitized — schema/structure only, never data**.

## Hard rules

**NEVER commit:**
- access tokens, JWTs, cookies, passwords, API keys
- raw captures (`bambu_flows.jsonl`), `filament_list.json`, memory dumps (`*.dmp`, `core*`)
- the mitmproxy CA or any `*.pem`/`*.crt`
- real RFIDs / tag UIDs, cloud spool ids, account ids, emails, device serials

`.gitignore` here blocks those patterns defensively — do not override it.

**DO commit (sanitized):**
- `endpoints.schema.json` — produced by `scripts/redact_flows.py`
  (every leaf value reduced to `<string>/<int>/<float>/<bool>` — no real values).
- `ENDPOINTS.md` — the human-readable findings (method · host · path · status + notes).

## Workflow

1. **VM session** captures (see `docs/capture-runbook.md`), then:
   ```bash
   python3 scripts/redact_flows.py \
       ~/capture/captures/bambu_flows.jsonl -o analysis/endpoints.schema.json
   # fill in analysis/ENDPOINTS.md (paths confirmed, anomalies, status codes)
   git add analysis/endpoints.schema.json analysis/ENDPOINTS.md
   git commit -m "analysis: captured filament endpoint schema"
   git push
   ```
2. **Design session** pulls, reads `endpoints.schema.json` + `ENDPOINTS.md`, sets
   `cloud_library.endpoint` / write schemas, and replies via the same files / code.

> If you ever need to share a concrete value (e.g. an enum like `createType`), describe it in
> words in `ENDPOINTS.md` — do not paste raw response bodies.
