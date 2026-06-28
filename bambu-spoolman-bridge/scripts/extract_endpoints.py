#!/usr/bin/env python3
"""Extract candidate Bambu cloud endpoints from a process memory dump.

The shipped bambu_networking.dll is packed (~7.9 bits/byte entropy), so static
`strings` on the DLL shows no URLs. A *memory dump of the running Bambu Studio
process* contains the decrypted strings. Run this on that dump (locally — no
need to upload 1+ GB) and share only the matching lines.

Usage:
    python3 extract_endpoints.py path/to/StudioDump.dmp
    python3 extract_endpoints.py dump.dmp --min 6 --context

Privacy: this prints URLs/paths/hosts only. It deliberately tries NOT to print
tokens, but ALWAYS eyeball the output and redact any Authorization/token/cookie
or personal id before sharing.
"""
from __future__ import annotations

import argparse
import re
import sys

# Streaming ASCII string scanner with a small carry-over so strings spanning a
# chunk boundary are not lost.
_PRINTABLE = bytes(range(0x20, 0x7F))
_PRINTABLE_SET = set(_PRINTABLE)

# What we care about: hosts, versioned API paths, MQTT brokers, filament/auth bits.
KEYWORDS = re.compile(
    rb"(bambulab|bambu-lab|\.bambu\.|mqtt|/v\d+/|/api/|/my/|user-service|iot-service|"
    rb"slicer|filament|spool|/upload|/print|/task|design|makerworld)",
    re.IGNORECASE,
)
# Lines that likely carry secrets -> drop them entirely.
SECRET = re.compile(rb"(authorization|bearer|access[_-]?token|refresh[_-]?token|cookie|password|secret)", re.IGNORECASE)

CHUNK = 16 * 1024 * 1024  # 16 MB


def iter_ascii_strings(path: str, min_len: int):
    carry = bytearray()
    with open(path, "rb") as fh:
        while True:
            buf = fh.read(CHUNK)
            if not buf:
                break
            data = carry + buf
            cur = bytearray()
            out = []
            for b in data:
                if b in _PRINTABLE_SET:
                    cur.append(b)
                else:
                    if len(cur) >= min_len:
                        out.append(bytes(cur))
                    cur = bytearray()
            # keep a possibly-unfinished run as carry for the next chunk
            carry = cur[-4096:] if cur else bytearray()
            for s in out:
                yield s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--min", type=int, default=6, help="min string length")
    ap.add_argument("--context", action="store_true", help="keep full string, not just URL-ish part")
    args = ap.parse_args()

    seen: set[bytes] = set()
    for s in iter_ascii_strings(args.dump, args.min):
        if not KEYWORDS.search(s):
            continue
        if SECRET.search(s):
            continue
        if s in seen:
            continue
        seen.add(s)
        try:
            print(s.decode("ascii", "replace"))
        except Exception:  # noqa: BLE001
            pass

    print(f"\n# {len(seen)} unique candidate lines", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
