"""Label-Printer-Hub client (concept §10).

POST /print on the hub (default :8090). Returns 200 (sync) or 202 + job_id.
"""
from __future__ import annotations

from typing import Any

import httpx


class LabelClient:
    def __init__(self, base_url: str, template_id: str, enabled: bool = True):
        self.base = base_url.rstrip("/")
        self.template_id = template_id
        self.enabled = enabled
        self._http = httpx.Client(timeout=10.0)

    def print_spool_label(
        self,
        title: str,
        primary_id: str,
        qr_payload: str,
        secondary: list[str] | None = None,
        copies: int = 1,
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        body = {
            "template_id": self.template_id,
            "data": {
                "title": title,
                "primary_id": primary_id,
                "qr_payload": qr_payload,
                "secondary": secondary or [],
            },
            "options": {"copies": copies, "auto_cut": True},
        }
        r = self._http.post(f"{self.base}/print", json=body)
        r.raise_for_status()
        # 202 -> {"job_id": ...}; 200 -> {} or job info
        return r.json() if r.content else {}
