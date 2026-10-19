from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Protocol


# The service evaluates every enabled rule for every command.  Keep the
# expression and rule set bounded because ``re`` from the standard library
# has no per-match timeout and can exhibit catastrophic backtracking for
# user-supplied patterns.
MAX_RULE_PATTERN_LENGTH = 512
MAX_ENABLED_RULES = 256
DEFAULT_ALLOWED_COMMANDS = frozenset({"date", "df", "free", "hostname", "id", "ls", "pwd", "uname", "uptime", "whoami"})
NEVER_ALLOWED_COMMANDS = frozenset({"bash", "csh", "dash", "env", "fish", "ksh", "node", "perl", "python", "python2", "python3", "ruby", "scp", "sh", "sftp", "ssh", "su", "sudo", "tcsh", "zsh"})
MAX_COMMAND_ARGS = 16
MAX_COMMAND_TOKEN_LENGTH = 256
SHELL_SYNTAX = frozenset(";&|$><`'\"\\\n\r\x00(){}[]*?")
SAFE_COMMAND_TOKEN = re.compile(r"[A-Za-z0-9_./:@%+=,-]+\Z")


class RegexValidationError(ValueError):
    """Raised when a rule pattern is too expensive or cannot be compiled."""


class CommandValidationError(ValueError):
    """Raised when a command is outside the structured execution allowlist."""


@dataclass(frozen=True)
class CommandAllowlist:
    """Validate shell-like input as a small, tokenized command allowlist.

    The allowlist intentionally accepts only simple command/argument tokens.
    It does not attempt to make an arbitrary shell script safe; shell syntax is
    rejected before the executor sees the command.
    """

    commands: frozenset[str] = DEFAULT_ALLOWED_COMMANDS
    max_args: int = MAX_COMMAND_ARGS
    max_token_length: int = MAX_COMMAND_TOKEN_LENGTH

    @classmethod
    def from_env(cls) -> "CommandAllowlist":
        raw = os.getenv("AEGIS_ALLOWED_COMMANDS", "")
        commands = frozenset(item.strip() for item in raw.split(",") if item.strip()) if raw.strip() else DEFAULT_ALLOWED_COMMANDS
        return cls(commands=commands)

    def parse(self, command: str) -> tuple[str, ...]:
        if not isinstance(command, str) or not command.strip():
            raise CommandValidationError("命令不能为空")
        if any(char in SHELL_SYNTAX for char in command):
            raise CommandValidationError("命令包含未允许的 Shell 语法")
        try:
            argv = tuple(shlex.split(command, posix=True))
        except ValueError as exc:
            raise CommandValidationError("命令参数无法解析") from exc
        if not argv:
            raise CommandValidationError("命令不能为空")
        command_name = PurePosixPath(argv[0]).name
        if command_name in NEVER_ALLOWED_COMMANDS:
            raise CommandValidationError(f"命令被永久禁止: {argv[0]}")
        if argv[0] not in self.commands:
            raise CommandValidationError(f"命令不在白名单中: {argv[0]}")
        if len(argv) - 1 > self.max_args:
            raise CommandValidationError(f"命令参数不能超过 {self.max_args} 个")
        for token in argv:
            if len(token) > self.max_token_length or not SAFE_COMMAND_TOKEN.fullmatch(token):
                raise CommandValidationError("命令参数包含未允许的字符或长度超限")
        return argv


@dataclass
class _GroupState:
    has_quantifier: bool = False
    has_unbounded_quantifier: bool = False
    has_branch: bool = False


def _has_dangerous_quantifier(pattern: str) -> bool:
    """Detect unbounded repetition of a quantified or branched group.

    This deliberately stays a small, conservative scanner instead of relying
    on ``sre_parse`` (a deprecated private parser).  It understands escapes,
    character classes and nested groups well enough to reject the classic
    ``(a+)+``/``([a-z]*){2,}`` and ``(a|aa)+`` ReDoS shapes while keeping
    ordinary shell rules such as ``[^\\n|;&]*`` valid.  Bounded outer repeats
    and optional groups are allowed because they cannot grow the backtracking
    tree without bound (for example the built-in ``(-[rf]+\\s+)?`` rule).
    """
    groups: list[_GroupState] = []
    closed_group_has_quantifier = False
    closed_group_has_unbounded_quantifier = False
    closed_group_has_branch = False
    in_class = False
    escaped = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if char == "\\":
            closed_group_has_quantifier = False
            closed_group_has_unbounded_quantifier = False
            closed_group_has_branch = False
            escaped = True
            index += 1
            continue
        if in_class:
            if char == "]":
                in_class = False
                closed_group_has_quantifier = False
                closed_group_has_unbounded_quantifier = False
                closed_group_has_branch = False
            index += 1
            continue
        if char == "[":
            closed_group_has_quantifier = False
            closed_group_has_unbounded_quantifier = False
            closed_group_has_branch = False
            in_class = True
            index += 1
            continue
        if char == "(":
            closed_group_has_quantifier = False
            closed_group_has_unbounded_quantifier = False
            closed_group_has_branch = False
            groups.append(_GroupState())
            # ``(?:`` is the only non-capturing group form accepted by the
            # API.  Skip its ``?`` marker so it is not mistaken for a
            # quantifier belonging to the group body.
            if pattern.startswith("?:", index + 1):
                index += 3
                continue
            index += 1
            continue
        if char == ")" and groups:
            state = groups.pop()
            closed_group_has_quantifier = state.has_quantifier
            closed_group_has_unbounded_quantifier = state.has_unbounded_quantifier
            closed_group_has_branch = state.has_branch
            if groups and state.has_quantifier:
                groups[-1].has_quantifier = True
            if groups and state.has_unbounded_quantifier:
                # The parent now contains a quantified sub-expression.  If a
                # quantifier follows the parent's closing ``)``, the pair is
                # nested even when the inner quantifier was in a child group.
                groups[-1].has_unbounded_quantifier = True
            if groups and state.has_branch:
                groups[-1].has_branch = True
            index += 1
            continue
        if char == "|" and groups:
            closed_group_has_quantifier = False
            closed_group_has_unbounded_quantifier = False
            closed_group_has_branch = False
            groups[-1].has_branch = True
            index += 1
            continue
        if char in "*+?" or char == "{":
            # ``{`` only denotes a quantifier when it closes with ``}`` and
            # starts with a decimal bound.  Invalid forms are left to re.
            is_quantifier = char != "{" or bool(re.match(r"\{\d+(?:,\d*)?\}", pattern[index:]))
            if is_quantifier:
                unbounded = char in "*+"
                if char in "*+?" and index + 1 < len(pattern) and pattern[index + 1] == "?":
                    # Lazy suffix; it is part of the same quantifier.
                    index += 1
                if char == "{" and "}" in pattern[index:]:
                    bound = pattern[index : pattern.index("}", index) + 1]
                    unbounded = bound.endswith(",}")
                    index = pattern.index("}", index)
                if (closed_group_has_quantifier or closed_group_has_branch) and unbounded:
                    return True
                if groups:
                    groups[-1].has_quantifier = True
                    groups[-1].has_unbounded_quantifier |= unbounded
                closed_group_has_unbounded_quantifier = False
                closed_group_has_quantifier = False
                closed_group_has_branch = False
            index += 1
            continue
        # Any ordinary token means a following quantifier applies to this
        # token, not to the group closed earlier.
        closed_group_has_unbounded_quantifier = False
        closed_group_has_quantifier = False
        closed_group_has_branch = False
        index += 1
    return False


def compile_rule_pattern(pattern: str) -> re.Pattern[str]:
    """Validate and compile a user supplied case-insensitive rule pattern."""
    if not isinstance(pattern, str) or not pattern.strip():
        raise RegexValidationError("pattern 必须是非空字符串")
    if len(pattern) > MAX_RULE_PATTERN_LENGTH:
        raise RegexValidationError(f"pattern 长度不能超过 {MAX_RULE_PATTERN_LENGTH}")
    # Backreferences make the matching cost difficult to bound and are not
    # needed for command deny rules.  Reject them explicitly before compile so
    # legacy data follows the same safety policy as newly created rules.
    if re.search(r"\\(?:[1-9][0-9]*|g<[^>]+>|k<[^>]+>)", pattern):
        raise RegexValidationError("pattern 不支持反向引用")
    if re.search(r"\(\?(?!:)", pattern):
        raise RegexValidationError("pattern 不支持高级回溯构造")
    try:
        compiled = re.compile(pattern, flags=re.IGNORECASE)
    except (re.error, TypeError) as exc:
        raise RegexValidationError("pattern 不是有效正则") from exc
    if _has_dangerous_quantifier(pattern):
        raise RegexValidationError("pattern 含有可能导致匹配超时的重复结构")
    return compiled


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
    _compiled: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_compiled", compile_rule_pattern(self.pattern))

    def evaluate(self, command: str, context: dict[str, Any]) -> RuleDecision:
        if self._compiled.search(command):
            return RuleDecision(False, self.id, self.reason, self.severity)
        return RuleDecision(True)


def built_in_rules() -> list[RegexDenyRule]:
    return [
        RegexDenyRule("dangerous-filesystem", "危险文件系统操作", r"\brm\s+(-[rf]+\s+)?/|\bmkfs(?:\.|\s)|\bdd\s+if=", "命令可能破坏文件系统"),
        RegexDenyRule("service-disruption", "服务中断操作", r"\b(shutdown|reboot|poweroff|halt)\b|systemctl\s+(stop|disable|mask)", "命令可能中断服务"),
        RegexDenyRule("remote-script", "远程脚本执行", r"(curl|wget)[^\n|;&]*\|\s*(sh|bash)|python\s+<\(curl", "禁止直接执行远程脚本"),
        RegexDenyRule("fork-bomb", "资源耗尽操作", r":\(\)\s*\{.*:\|:.*\};", "命令可能耗尽系统资源"),
    ]
