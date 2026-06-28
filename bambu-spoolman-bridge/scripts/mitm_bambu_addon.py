"""mitmproxy addon: auto-capture Bambu cloud filament/preset requests.

Run:
    mitmweb  -s scripts/mitm_bambu_addon.py   --listen-port 8080
    # or headless:
    mitmdump -s scripts/mitm_bambu_addon.py   --listen-port 8080

Then in Bambu Studio: log in, open the Filament Manager, trigger a sync /
add-edit a spool. Matching flows are written to ./captures/:
  - bambu_flows.jsonl     one line per request (method, url, bodies, status)
  - filament_list.json    the most recent GET filament-list response body
                          (ready for the importer's `file` mode)

Auth headers / cookies are redacted. Review before sharing.
Works the same on Linux and Windows (it only needs Python + mitmproxy).
"""
from __future__ import annotations

import json
import os
import pathlib

OUT = pathlib.Path(os.environ.get("BAMBU_CAPTURE_DIR", "captures"))
OUT.mkdir(parents=True, exist_ok=True)
FLOWS = OUT / "bambu_flows.jsonl"
FILAMENT_LIST = OUT / "filament_list.json"

# Hosts/paths we care about.
HOST_HINT = "bambulab"
PATH_HINTS = ("filament", "/my/", "user-service", "iot-service", "slicer/setting", "/v1/")
REDACT = {"authorization", "cookie", "set-cookie", "x-bbl-agora-token", "x-jwt-token"}


def _interesting(host: str, path: str) -> bool:
    if HOST_HINT in host.lower():
        return True
    return any(h in path.lower() for h in PATH_HINTS)


def _headers(h) -> dict:
    out = {}
    for k, v in h.items():
        out[k] = "<redacted>" if k.lower() in REDACT else v
    return out


def _body(msg) -> str:
    try:
        text = msg.get_text(strict=False)
    except Exception:  # noqa: BLE001
        text = None
    return text if text is not None else f"<{len(msg.raw_content or b'')} bytes binary>"


def response(flow):  # mitmproxy hook
    req = flow.request
    if not _interesting(req.pretty_host, req.path):
        return
    rec = {
        "method": req.method,
        "url": req.pretty_url,
        "host": req.pretty_host,
        "path": req.path.split("?")[0],
        "query": dict(req.query),
        "status": flow.response.status_code if flow.response else None,
        "req_headers": _headers(req.headers),
        "req_body": _body(req) if req.raw_content else "",
        "resp_headers": _headers(flow.response.headers) if flow.response else {},
        "resp_body": _body(flow.response) if flow.response else "",
    }
    with FLOWS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Keep the latest filament-list GET handy for the importer's file mode.
    if req.method == "GET" and "filament" in req.path.lower() and flow.response:
        try:
            FILAMENT_LIST.write_text(flow.response.get_text(strict=False) or "", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    print(f"[bambu-capture] {rec['method']} {rec['path']} -> {rec['status']}")
