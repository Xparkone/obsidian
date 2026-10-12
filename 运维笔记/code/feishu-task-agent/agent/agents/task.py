import json

import lark_oapi as lark

from . import Agent, register


class TaskAgent(Agent):
    name = "task"
    usage = "/task <事项> — 创建飞书任务待办"

    def handle(self, ctx):
        summary = ctx.payload
        if not summary:
            ctx.reply("用法：/task 事项内容")
            return
        req = (
            lark.BaseRequest.builder()
            .http_method(lark.HttpMethod.POST)
            .uri("/open-apis/task/v2/tasks")
            .token_types({lark.AccessTokenType.TENANT})
            .body({"summary": summary})
            .build()
        )
        resp = ctx.client.request(req)
        data = json.loads(resp.raw.content or b"{}")
        if resp.raw.status_code >= 400 or data.get("code", 0) != 0:
            msg = data.get("msg") or f"HTTP {resp.raw.status_code}"
            ctx.reply(f"创建任务失败：{msg}\n（需在开放平台为应用开通 task 相关权限，见 README）")
            return
        ctx.reply(f"已创建任务：{summary}")


register(TaskAgent())
