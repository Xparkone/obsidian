import json
import logging
import re

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from .agents import DEFAULT_AGENT, HELP_AGENT, REGISTRY, AgentContext
from .config import load_credentials

log = logging.getLogger(__name__)

_MENTION = re.compile(r"@_user_\d+")


def _text_of(message) -> str:
    if message.message_type != "text":
        return ""
    try:
        raw = json.loads(message.content).get("text", "") or ""
    except (TypeError, ValueError):
        return ""
    return _MENTION.sub("", raw).strip()


def _route(text):
    if text.startswith("/"):
        name = text[1:].split(" ", 1)[0]
        if name in REGISTRY:
            return REGISTRY[name]
        return REGISTRY[HELP_AGENT]
    return REGISTRY[DEFAULT_AGENT]


def make_on_event(client):
    def on_event(data: P2ImMessageReceiveV1) -> None:
        event = data.event
        if getattr(event.sender, "sender_type", None) != "user":
            return
        text = _text_of(event.message)
        if not text:
            return
        agent = _route(text)
        ctx = AgentContext(client=client, event=event, text=text)
        try:
            agent.handle(ctx)
        except Exception:
            log.exception("agent %s failed", agent.name)
            try:
                ctx.reply(f"agent `{agent.name}` 处理失败，详情见 feishu-task-agent 日志")
            except Exception:
                log.exception("error reply failed")

    return on_event


def start() -> None:
    app_id, app_secret, source = load_credentials()
    client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(make_on_event(client))
        .build()
    )
    ws = lark.ws.Client(
        app_id,
        app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.INFO,
    )
    log.info(
        "feishu-task-agent 启动: app=%s 凭证来源=%s 已注册 agent=%s 默认 agent=%s",
        app_id, source, sorted(REGISTRY), DEFAULT_AGENT,
    )
    ws.start()
