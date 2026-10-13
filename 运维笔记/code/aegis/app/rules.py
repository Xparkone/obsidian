from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RuleDecision:
    allowed: bool
    rule_id: str | None = None
    reason: str | None = None
    severity: str = "info"


class Rule(Protocol):
    id: str
    name: str

    def evaluate(self, command: str, context: dict[str, Any]) -> RuleDecision: ...


@dataclass(frozen=True)
class RegexDenyRule:
    id: str
    name: str
    pattern: str
    reason: str
    severity: str = "critical"

    def evaluate(self, command: str, context: dict[str, Any]) -> RuleDecision:
        if re.search(self.pattern, command, flags=re.IGNORECASE):
            return RuleDecision(False, self.id, self.reason, self.severity)
        return RuleDecision(True)


def built_in_rules() -> list[RegexDenyRule]:
    return [
        RegexDenyRule("dangerous-filesystem", "危险文件系统操作", r"\brm\s+(-[rf]+\s+)?/|\bmkfs(?:\.|\s)|\bdd\s+if=", "命令可能破坏文件系统"),
        RegexDenyRule("service-disruption", "服务中断操作", r"\b(shutdown|reboot|poweroff|halt)\b|systemctl\s+(stop|disable|mask)", "命令可能中断服务"),
        RegexDenyRule("remote-script", "远程脚本执行", r"(curl|wget)[^\n|;&]*\|\s*(sh|bash)|python\s+<\(curl", "禁止直接执行远程脚本"),
        RegexDenyRule("fork-bomb", "资源耗尽操作", r":\(\)\s*\{.*:\|:.*\};", "命令可能耗尽系统资源"),
    ]
