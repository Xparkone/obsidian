from . import Agent, register


class EchoAgent(Agent):
    name = "echo"
    usage = "/echo <文本> — 原样回显"

    def handle(self, ctx):
        ctx.reply(ctx.payload or "(空)")


register(EchoAgent())
