import argparse
import json
import logging
import sys
import urllib.request

from .agents import DEFAULT_AGENT, REGISTRY
from .config import load_credentials


def main() -> None:
    parser = argparse.ArgumentParser(prog="feishu-task-agent", description="飞书消息驱动的多 Agent 服务")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("start", help="启动 WebSocket 长连接，开始接收飞书消息")
    sub.add_parser("agents", help="列出已注册的 agent")
    sub.add_parser("doctor", help="检查凭证加载与飞书连通性")
    args = parser.parse_args()

    if args.cmd == "start":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        from . import server
        server.start()
    elif args.cmd == "agents":
        for name in sorted(REGISTRY):
            mark = " (默认)" if name == DEFAULT_AGENT else ""
            print(f"{name}{mark}  {REGISTRY[name].usage}")
    elif args.cmd == "doctor":
        sys.exit(_doctor())
    else:
        parser.print_help()


def _doctor() -> int:
    try:
        app_id, app_secret, source = load_credentials()
    except Exception as e:
        print(f"[FAIL] 凭证加载失败: {e}")
        return 1
    print(f"[OK] 凭证已加载: app_id={app_id} 来源={source}")

    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[FAIL] 请求 tenant_access_token 出错: {e}")
        return 1
    if data.get("code") != 0:
        print(f"[FAIL] 凭证被飞书拒绝: code={data.get('code')} msg={data.get('msg')}")
        return 1
    print(f"[OK] tenant_access_token 获取成功, 有效期 {data.get('expire')} 秒")
    print("[OK] 可以执行: feishu-task-agent start")
    return 0
