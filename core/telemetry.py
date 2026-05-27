import hashlib
import json
import platform
import threading
from datetime import datetime, timezone
import urllib.request

TELEMETRY_URL = "https://api.olinl.com/api/parser"


def _machine_code() -> str:
    try:
        raw = f"{platform.node()}/{platform.system()}/{platform.machine()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    except Exception:
        return "unknown"


def _send(payload: dict) -> None:
    try:
        data = json.dumps(payload, ensure_ascii=False).encode()
        req = urllib.request.Request(
            TELEMETRY_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception:
        pass


def report(text: str, keyword: str) -> None:
    try:
        payload = {
            "machine_code": _machine_code(),
            "send_time": datetime.now(timezone.utc).isoformat(),
            "message": text,
            "keyword": keyword,
        }
        threading.Thread(target=_send, args=(payload,), daemon=True).start()
    except Exception:
        pass
