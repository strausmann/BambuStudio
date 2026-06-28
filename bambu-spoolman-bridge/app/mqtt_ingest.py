"""LAN MQTT ingest for a single Bambu printer (concept §2, §3.1).

Subscribes to device/<serial>/report, requests a full state once connected
(pushall), and parses AMS trays into Tray objects passed to a callback.

Cloud-MQTT fallback (§3.2) is a TODO.
"""
from __future__ import annotations

import json
import logging
import ssl
import threading
from typing import Callable

import paho.mqtt.client as mqtt

from .models import Tray

log = logging.getLogger("bridge.mqtt")

TrayHandler = Callable[[Tray], None]
StatusHandler = Callable[[str, dict], None]  # (printer_serial, print_obj)
VersionHandler = Callable[[str, list], None]  # (printer_serial, [ams module dicts])

# Module name prefix -> friendly AMS model (concept §2.3). See DevAmsType in
# src/slic3r/GUI/DeviceCore/DevFilaSystem.h.
AMS_TYPE_NAMES = {
    "ams": "AMS",
    "n3f": "AMS 2 Pro",
    "n3s": "AMS HT",
    "ams_lite": "AMS Lite",
    "f1": "AMS Lite",
}


def parse_version_modules(info: dict) -> list[dict]:
    """Extract AMS modules from a get_version response: name like 'n3f/0' plus sn."""
    out: list[dict] = []
    for m in info.get("module", []) or []:
        name = str(m.get("name", ""))
        if "/" not in name:
            continue
        prefix, _, idx = name.partition("/")
        if prefix not in AMS_TYPE_NAMES:
            continue
        out.append({
            "ams_id": int(idx) if idx.isdigit() else idx,
            "type": AMS_TYPE_NAMES[prefix],
            "sn": str(m.get("sn", "")),
            "sw_ver": str(m.get("sw_ver", "")),
        })
    return out


def _to_int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def cloud_broker_host(region: str) -> str:
    """EU/US/global share the global broker; CN is separate (concept §3.2)."""
    return "cn.mqtt.bambulab.com" if (region or "").lower() == "cn" else "us.mqtt.bambulab.com"


def jwt_username(token: str) -> str:
    """Derive the cloud MQTT username from the access token's JWT payload.
    Bambu uses a "u_<uid>"-style username carried in the token claims."""
    import base64
    import json as _json

    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # pad base64url
        claims = _json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:  # noqa: BLE001
        return ""
    if claims.get("username"):
        return str(claims["username"])
    for k in ("uid", "sub", "userId"):
        if claims.get(k):
            return f"u_{claims[k]}"
    return ""


def tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class BambuPrinterMQTT:
    """Transport-agnostic MQTT client. Use the for_lan()/for_cloud() factories.

    LAN and cloud differ only in host/credentials/TLS; topics and message
    parsing are identical (concept §3.1/§3.2).
    """

    def __init__(
        self,
        serial: str,
        host: str,
        username: str,
        password: str,
        on_tray: TrayHandler,
        on_status: StatusHandler | None = None,
        on_version: VersionHandler | None = None,
        port: int = 8883,
        tls_insecure: bool = False,
        label: str = "lan",
    ):
        self.serial = serial
        self.host = host
        self.port = port
        self.label = label
        self.on_tray = on_tray
        self.on_status = on_status
        self.on_version = on_version
        self._client = mqtt.Client(client_id=f"bridge-{serial}-{label}")
        self._client.username_pw_set(username, password)
        if tls_insecure:
            self._client.tls_set(cert_reqs=ssl.CERT_NONE)  # printer self-signed cert (LAN)
            self._client.tls_insecure_set(True)
        else:
            self._client.tls_set()  # verify against system CAs (cloud)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._thread: threading.Thread | None = None

    # ---- factories --------------------------------------------------------
    @classmethod
    def for_lan(cls, serial: str, host: str, access_code: str, **kw):
        return cls(serial, host, "bblp", access_code, tls_insecure=True, label="lan", **kw)

    @classmethod
    def for_cloud(cls, serial: str, region: str, token: str, username: str = "", **kw):
        host = cloud_broker_host(region)
        user = username or jwt_username(token)
        return cls(serial, host, user, token, tls_insecure=False, label="cloud", **kw)

    @property
    def report_topic(self) -> str:
        return f"device/{self.serial}/report"

    @property
    def request_topic(self) -> str:
        return f"device/{self.serial}/request"

    def publish_command(self, payload: dict) -> None:
        """Publish a command JSON to device/<serial>/request (write path)."""
        self._client.publish(self.request_topic, json.dumps(payload))

    def start(self) -> None:
        def run():
            try:
                self._client.connect(self.host, self.port, keepalive=60)
                self._client.loop_forever(retry_first_connection=True)
            except Exception:  # noqa: BLE001 - prototype: log and let supervisor restart
                log.exception("[%s] MQTT loop crashed", self.serial)

        self._thread = threading.Thread(target=run, name=f"mqtt-{self.serial}", daemon=True)
        self._thread.start()

    # ---- callbacks --------------------------------------------------------
    def _on_connect(self, client, userdata, flags, rc):
        log.info("[%s] connected rc=%s", self.serial, rc)
        client.subscribe(self.report_topic)
        # Ask for a full state snapshot (must re-send after every reconnect).
        client.publish(self.request_topic, json.dumps({"pushing": {"command": "pushall"}}))
        # Ask for module versions -> AMS type + serial number (concept §2.3).
        client.publish(self.request_topic, json.dumps({"info": {"command": "get_version"}}))

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        info_obj = payload.get("info")
        if isinstance(info_obj, dict) and info_obj.get("command") == "get_version" and self.on_version:
            self.on_version(self.serial, parse_version_modules(info_obj))
            return
        print_obj = payload.get("print")
        if not isinstance(print_obj, dict):
            return
        if self.on_status:
            self.on_status(self.serial, print_obj)
        self._parse_ams(print_obj)

    def _parse_ams(self, print_obj: dict) -> None:
        ams_root = print_obj.get("ams")
        if not isinstance(ams_root, dict):
            return
        for ams in ams_root.get("ams", []) or []:
            ams_id = _to_int(ams.get("id"), -1)
            for tray in ams.get("tray", []) or []:
                self.on_tray(self._tray_from_json(ams_id, tray))

    def _tray_from_json(self, ams_id: int, t: dict) -> Tray:
        cols = [c for c in (t.get("cols") or []) if isinstance(c, str)]
        return Tray(
            printer_serial=self.serial,
            ams_id=ams_id,
            tray_id=_to_int(t.get("id"), -1),
            tag_uid=str(t.get("tag_uid", "") or ""),
            tray_uuid=str(t.get("tray_uuid", "") or ""),
            setting_id=str(t.get("tray_info_idx", "") or ""),
            material=str(t.get("tray_type", "") or ""),
            sub_brands=str(t.get("tray_sub_brands", "") or ""),
            color=str(t.get("tray_color", "") or ""),
            colors=cols,
            remain=_to_int(t.get("remain"), -1),
            tray_weight=_to_float(t.get("tray_weight"), 0.0),
            diameter=_to_float(t.get("tray_diameter"), 1.75),
            cali_idx=_to_int(t.get("cali_idx"), -1),
            k=_to_float(t.get("k"), -1.0),
            n=_to_float(t.get("n"), -1.0),
            nozzle_temp_min=_to_int(t.get("nozzle_temp_min"), 0),
            nozzle_temp_max=_to_int(t.get("nozzle_temp_max"), 0),
        )
