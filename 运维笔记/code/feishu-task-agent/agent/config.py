import base64
import json
import os
import re
import subprocess
from pathlib import Path

LARK_CLI_CONFIG = Path.home() / ".lark-cli" / "config.json"
KEYCHAIN_SERVICE = "lark-cli"
APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / KEYCHAIN_SERVICE
FILE_MASTER_KEY = APP_SUPPORT_DIR / "master.key.file"

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]")


class CredentialsError(RuntimeError):
    pass


def load_credentials():
    """按优先级加载应用凭证，返回 (app_id, app_secret, 来源说明)。

    1. 环境变量 FEISHU_APP_ID / FEISHU_APP_SECRET
    2. lark-cli 配置 ~/.lark-cli/config.json（本机登录 lark-cli 时录过的同一应用）
    """
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if app_id and app_secret:
        return app_id, app_secret, "env(FEISHU_APP_ID/FEISHU_APP_SECRET)"
    if app_id or app_secret:
        raise CredentialsError("FEISHU_APP_ID 与 FEISHU_APP_SECRET 必须同时设置")

    app_id, secret = _load_from_lark_cli()
    if app_id and secret:
        return app_id, secret, "lark-cli config"
    raise CredentialsError(
        "未找到应用凭证。请设置环境变量 FEISHU_APP_ID/FEISHU_APP_SECRET，"
        "或先执行 lark-cli config init 完成应用配置"
    )


def _load_from_lark_cli():
    if not LARK_CLI_CONFIG.exists():
        return None, None
    with open(LARK_CLI_CONFIG, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    apps = cfg.get("apps") or []
    if not apps:
        return None, None
    app = apps[0]
    app_id = app.get("appId") or ""
    if not app_id:
        return None, None
    secret = _resolve_secret_input(app.get("appSecret"), app_id)
    return app_id, secret


def _resolve_secret_input(raw, app_id):
    if isinstance(raw, str) and raw:
        return raw
    if not isinstance(raw, dict):
        return None
    source, ref_id = raw.get("source"), raw.get("id")
    if source == "file" and ref_id:
        with open(os.path.expanduser(ref_id), "r", encoding="utf-8") as f:
            return f.read().strip()
    if source == "keychain" and ref_id:
        expected = f"appsecret:{app_id}"
        if ref_id != expected:
            raise CredentialsError(f"keychain 引用 {ref_id!r} 与 appId 不匹配（期望 {expected!r}）")
        return _keychain_get(ref_id)
    return None


def _keychain_get(account):
    """复刻 lark-cli 的 macOS 存储：密文在 ~/Library/Application Support/lark-cli/<account>.enc，
    AES-256-GCM（IV 12B 前缀 + GCM tag 16B 尾部），主密钥在系统钥匙串（service=lark-cli, account=master.key，
    base64 编码的 32 字节），本地 master.key.file 为回退主密钥。"""
    enc_path = APP_SUPPORT_DIR / (_SAFE_NAME_RE.sub("_", account) + ".enc")
    if not enc_path.exists():
        raise CredentialsError(f"未找到 lark-cli 密文文件: {enc_path}")
    data = enc_path.read_bytes()

    key = _master_key_file()
    if key is not None:
        try:
            return _aes_gcm_decrypt(key, data)
        except Exception:
            pass
    key = _master_key_system()
    return _aes_gcm_decrypt(key, data)


def _master_key_file():
    try:
        raw = FILE_MASTER_KEY.read_bytes()
    except OSError:
        return None
    return raw if len(raw) == 32 else None


def _master_key_system():
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", "master.key", "-w"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise CredentialsError(f"读取系统钥匙串失败: {e}")
    if out.returncode != 0:
        raise CredentialsError(
            "系统钥匙串中没有 lark-cli master.key。"
            "若弹出了钥匙串授权窗口请点击“始终允许”，或改用环境变量提供凭证"
        )
    key = base64.b64decode(out.stdout.strip())
    if len(key) != 32:
        raise CredentialsError("钥匙串中的 master.key 不是有效的 32 字节密钥")
    return key


def _aes_gcm_decrypt(key, data):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(data) < 12 + 16:
        raise CredentialsError("lark-cli 密文长度异常")
    return AESGCM(key).decrypt(data[:12], data[12:], None).decode("utf-8")
