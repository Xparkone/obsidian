```
 #!/usr/bin/env bash
#
# setup-bash-audit.sh
#
# 部署一个通过 rsyslog 记录交互式 Bash 命令的审计钩子。
# 名称前缀可自定义（用于 profile.d 脚本名、rsyslog tag、日志目录等）。
#
# 用法:
#   sudo ./setup-bash-audit.sh <前缀名>
#   sudo ./setup-bash-audit.sh zkyhistory
#
# 不传参数时默认使用 "audithist"。

set -euo pipefail

# ---------- 参数处理 ----------
NAME="${1:-audithist}"

# 简单校验：只允许字母数字下划线，避免生成非法文件名/变量名
if ! [[ "$NAME" =~ ^[A-Za-z][A-Za-z0-9_]*$ ]]; then
  echo "错误: 名称只能以字母开头，且只包含字母、数字、下划线。你传入的是: $NAME" >&2
  exit 1
fi

if [ "$EUID" -ne 0 ]; then
  echo "错误: 请用 root 权限运行此脚本（sudo）。" >&2
  exit 1
fi

PROFILE_SCRIPT="/etc/profile.d/${NAME}.sh"
RSYSLOG_CONF="/etc/rsyslog.d/${NAME}.conf"
LOG_DIR="/var/log/${NAME}"
LOG_FILE="${LOG_DIR}/history.log"
SYSLOG_FACILITY="local6"

echo "==> 部署审计钩子，名称前缀: ${NAME}"
echo "    profile 脚本: ${PROFILE_SCRIPT}"
echo "    rsyslog 配置: ${RSYSLOG_CONF}"
echo "    日志文件:     ${LOG_FILE}"
echo

# ---------- 第一步: 生成 profile.d 脚本 ----------
echo "==> [1/5] 生成 ${PROFILE_SCRIPT}"

cat >"${PROFILE_SCRIPT}" <<EOF
# Log interactive Bash commands through rsyslog.
[ -n "\${BASH_VERSION:-}" ] || return 0
case \$- in
  *i*) ;;
  *) return 0 ;;
esac

# Keep every interactive command in Bash history so the audit hook can see it.
HISTCONTROL=
HISTIGNORE=
shopt -s cmdhist

__${NAME}_audit_bash() {
  local __${NAME}_status=\$?
  local __${NAME}_histcmd=\${HISTCMD:-0}
  local __${NAME}_command

  if [ "\$__${NAME}_histcmd" != "\${__${NAME^^}_LAST_HISTCMD:-}" ]; then
    __${NAME^^}_LAST_HISTCMD=\$__${NAME}_histcmd
    __${NAME}_command=\$(builtin fc -ln -1 2>/dev/null || true)
    __${NAME}_command=\${__${NAME}_command#"\${__${NAME}_command%%[![:space:]]*}"}
    __${NAME}_command=\${__${NAME}_command//\$'\n'/ }

    if [ -n "\$__${NAME}_command" ]; then
      /usr/bin/logger -p ${SYSLOG_FACILITY}.notice -t ${NAME} -- \\
        "shell=bash user=\${USER:-unknown} uid=\${EUID:-unknown} pid=\$\$ cwd=\${PWD:-unknown} rc=\$__${NAME}_status cmd=\$__${NAME}_command"
    fi
  fi

  return "\$__${NAME}_status"
}

__${NAME^^}_LAST_HISTCMD=\${HISTCMD:-0}
case ";\${PROMPT_COMMAND:-};" in
  *';__${NAME}_audit_bash;'*) ;;
  *) PROMPT_COMMAND="__${NAME}_audit_bash\${PROMPT_COMMAND:+;\$PROMPT_COMMAND}" ;;
esac
EOF

chown root:root "${PROFILE_SCRIPT}"
chmod 0644 "${PROFILE_SCRIPT}"
bash -n "${PROFILE_SCRIPT}"
echo "    OK: 语法检查通过"
echo

# ---------- 第二步: 创建日志目录和文件 ----------
echo "==> [2/5] 创建日志目录与文件"

install -d -m 0750 -o syslog -g adm "${LOG_DIR}"
touch "${LOG_FILE}"
chown syslog:adm "${LOG_FILE}"
chmod 0640 "${LOG_FILE}"
echo "    OK: ${LOG_FILE}"
echo

# ---------- 第三步: 写入 rsyslog 配置 ----------
echo "==> [3/5] 生成 rsyslog 配置"

cat >"${RSYSLOG_CONF}" <<EOF
${SYSLOG_FACILITY}.notice   ${LOG_FILE}
& stop
EOF
echo "    OK: ${RSYSLOG_CONF}"
echo

# ---------- 第四步: 校验并重启 rsyslog ----------
echo "==> [4/5] 校验并重启 rsyslog"

if command -v rsyslogd >/dev/null 2>&1; then
  rsyslogd -N1
else
  echo "    警告: 未找到 rsyslogd，跳过语法检查" >&2
fi

systemctl restart rsyslog
sleep 1
if systemctl is-active --quiet rsyslog; then
  echo "    OK: rsyslog 运行正常"
else
  echo "    错误: rsyslog 未能正常启动，请检查 systemctl status rsyslog" >&2
  exit 1
fi
echo

# ---------- 第五步: 端到端验证 ----------
echo "==> [5/5] 验证链路"

TEST_MSG="setup-verify-$(date +%s)"
logger -p ${SYSLOG_FACILITY}.notice -t "${NAME}" "${TEST_MSG}"
sleep 1

if grep -q "${TEST_MSG}" "${LOG_FILE}" 2>/dev/null; then
  echo "    OK: logger -> rsyslog -> 日志文件 链路正常"
else
  echo "    警告: 未在 ${LOG_FILE} 中找到测试消息，请手动检查 rsyslog 配置" >&2
fi

echo
echo "==================================================================="
echo "部署完成。"
echo
echo "新开的 SSH/终端会话将自动生效。当前会话如需立即生效，请执行:"
echo "    source ${PROFILE_SCRIPT}"
echo
echo "查看审计日志:"
echo "    tail -f ${LOG_FILE}"
echo "==================================================================="

```