import json

import lark_oapi as lark
from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody


class AgentContext:
    def __init__(self, client, event, text):
        self.client = client
        self.event = event
        self.text = text

    @property
    def payload(self):
        t = self.text
        if t.startswith("/"):
            t = t.split(" ", 1)[1] if " " in t else ""
        return t.strip()

    def reply(self, text, msg_type="text"):
        req = (
            ReplyMessageRequest.builder()
            .message_id(self.event.message.message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type(msg_type)
                .content(json.dumps({"text": text}, ensure_ascii=False))
                .build()
            )
            .build()
        )
        resp = self.client.im.v1.message.reply(req)
        if not resp.success():
            raise RuntimeError(f"reply failed: code={resp.code} msg={resp.msg}")


class Agent:
    name = ""
    usage = ""

    def handle(self, ctx):
        raise NotImplementedError


REGISTRY = {}
DEFAULT_AGENT = "task"
HELP_AGENT = "help"


def register(agent):
    REGISTRY[agent.name] = agent


def _build_help():
    class HelpAgent(Agent):
        name = "help"
        usage = "/help — 列出所有可用 agent"

        def handle(self, ctx):
            lines = ["可用 agent:"]
            for name in sorted(REGISTRY):
                a = REGISTRY[name]
                if name == HELP_AGENT:
                    continue
                lines.append(f"  {a.usage}")
            lines.append("不带前缀的消息默认走 task agent")
            ctx.reply("\n".join(lines))

    register(HelpAgent())


from . import echo, task  # noqa: E402,F401

_build_help()
