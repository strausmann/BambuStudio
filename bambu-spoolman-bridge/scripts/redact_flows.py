#!/usr/bin/env python3
"""Turn raw captured flows into a SCHEMA-ONLY artifact safe to commit/share.

Input:  captures/bambu_flows.jsonl  (from mitm_bambu_addon.py)
Output: a JSON with, per unique (method, path): method, host, path, query KEY
        names, status, and the request/response body reduced to its *schema*
        (every leaf value replaced by its type: <string>/<int>/<float>/<bool>).

No real values, no headers, no tokens, no RFIDs/ids/emails ever leave — only
structure. This is what the other Claude session needs to build the importer /
OpenAPI; it is NOT your inventory data.

Usage:
    python3 redact_flows.py captures/bambu_flows.jsonl -o ../../analysis/endpoints.schema.json
"""
from __future__ import annotations

import argparse
import json
import pathlib


def schemify(v):
    if isinstance(v, dict):
        return {k: schemify(x) for k, x in v.items()}
    if isinstance(v, list):
        return [schemify(v[0])] if v else []
    if isinstance(v, bool):
        return "<bool>"
    if isinstance(v, int):
        return "<int>"
    if isinstance(v, float):
        return "<float>"
    if v is None:
        return None
    return "<string>"


def body_schema(text: str):
    if not text:
        return None
    try:
        return schemify(json.loads(text))
    except (ValueError, TypeError):
        return f"<non-json {len(text)} chars>"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("flows", help="captures/bambu_flows.jsonl")
    ap.add_argument("-o", "--out", default="endpoints.schema.json")
    args = ap.parse_args()

    seen: dict[tuple[str, str], dict] = {}
    for line in pathlib.Path(args.flows).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        key = (rec.get("method", "?"), rec.get("path", "?"))
        if key in seen:
            continue
        seen[key] = {
            "method": rec.get("method"),
            "host": rec.get("host"),
            "path": rec.get("path"),
            "query_keys": sorted((rec.get("query") or {}).keys()),
            "status": rec.get("status"),
            "request_schema": body_schema(rec.get("req_body", "")),
            "response_schema": body_schema(rec.get("resp_body", "")),
        }

    out = {"endpoints": list(seen.values())}
    pathlib.Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {args.out} with {len(seen)} unique endpoint(s):")
    for e in seen.values():
        print(f"  {e['method']:6} {e['host']}{e['path']}  -> {e['status']}")
    print("\nSafe to commit: schema only, no values/headers/secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
