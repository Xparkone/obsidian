#!/usr/bin/env python3
"""触发日报生成，并校验每份报表各自的随机 token。"""
from __future__ import annotations

import hmac
import os
import re
import secrets
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
_VENV = ROOT / "venv"
_VENV_PY = _VENV / "bin" / "python"
if _VENV_PY.exists() and Path(sys.prefix).resolve() != _VENV.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

from flask import Flask, jsonify, request
from dotenv import load_dotenv

from query_perplexitybot import run_report

load_dotenv(ROOT / ".env")

REPORTS = ROOT / "reports"
TOKENS = REPORTS / ".tokens"
STAMP_RE = re.compile(r"^[0-9]{8}-[0-9]{6}(?:-[0-9]+)?$")

app = Flask(__name__)
_generate_lock = threading.Lock()


def _api_token() -> str:
    return (os.getenv("REPORT_API_TOKEN") or os.getenv("REPORT_TOKEN") or "").strip()


def _report_base_url() -> str:
    return (os.getenv("REPORT_URL") or "http://127.0.0.1:8080").rstrip("/")


def _require_api_token():
    expected = _api_token()
    if not expected:
        return None
    got = (
        request.headers.get("X-Api-Token")
        or request.args.get("api_token")
        or ""
    ).strip()
    if not got or not hmac.compare_digest(got, expected):
        return jsonify({"error": "unauthorized"}), 401
    return None


def _write_token(stamp: str, token: str) -> None:
    TOKENS.mkdir(parents=True, exist_ok=True)
    path = TOKENS / stamp
    path.write_text(token, encoding="utf-8")
    path.chmod(0o600)


def _read_token(stamp: str) -> str | None:
    path = TOKENS / stamp
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip() or None


def _stamp_from_uri(uri: str) -> str | None:
    path = urlparse(uri).path
    name = Path(path).name
    if not name.endswith(".html"):
        return None
    stamp = name[:-5]
    if not STAMP_RE.match(stamp):
        return None
    return stamp


@app.get("/healthz")
def healthz():
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/api/generate", methods=["GET", "POST"])
def generate():
    denied = _require_api_token()
    if denied:
        return denied
    token = secrets.token_hex(16)
    try:
        with _generate_lock:
            result = run_report()
            _write_token(result["timestamp"], token)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    print(f"generated {result['timestamp']}", flush=True)
    url = f"{_report_base_url()}/{result['timestamp']}.html?token={token}"
    return jsonify(
        {
            "url": url,
            "timestamp": result["timestamp"],
            "start": result["start"],
            "end": result["end"],
        }
    )


@app.get("/internal/auth")
def auth():
    """nginx auth_request：校验「这份 HTML 自己的随机 token」。"""
    uri = request.headers.get("X-Original-URI") or ""
    stamp = _stamp_from_uri(uri)
    got = (
        request.headers.get("X-Report-Token")
        or request.headers.get("X-Report-Token-Cookie")
        or ""
    ).strip()
    if not stamp:
        print(f"auth deny: bad uri {uri!r}", flush=True)
        return "", 401
    expected = _read_token(stamp)
    if not expected:
        print(f"auth deny: no token file {stamp}", flush=True)
        return "", 401
    if not got or not hmac.compare_digest(got, expected):
        print(f"auth deny: token mismatch {stamp}", flush=True)
        return "", 401
    return "", 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
