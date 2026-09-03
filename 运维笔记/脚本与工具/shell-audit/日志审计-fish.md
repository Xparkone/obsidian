```
#!/usr/bin/env bash
#
# setup-fish-audit.sh
#
# 部署一个通过 rsyslog 记录交互式 Fish 命令的审计钩子。
# 名称前缀可自定义（用于 conf.d 脚本名、rsyslog tag、日志目录等）。
#
# 用法:
#   sudo ./setup-fish-audit.sh <前缀名>
#   sudo ./setup-fish-audit.sh zkyhistory
#
# 不传参数时默认使用 "audithist"。
#
# 说明: fish 的系统级自启动脚本目录是 /etc/fish/conf.d/*.fish，
# 会在每个交互式/非交互式 fish 启动时自动加载（这里用 status is-interactive 过滤）。
# 不同于 bash 的 PROMPT_COMMAND 拼接方式，fish 用 --on-event fish_postexec
# 事件钩子，命令内容直接作为参数传入，不需要 HISTCMD 去重技巧。

set -euo pipefail

# ---------- 参数处理 ----------
NAME="${1:-audithist}"

if ! [[ "$NAME" =~ ^[A-Za-z][A-Za-z0-9_]*$ ]]; then
  echo "错误: 名称只能以字母开头，且只包含字母、数字、下划线。你传入的是: $NAME" >&2
  exit 1
fi

if [ "$EUID" -ne 0 ]; then
  echo "错误: 请用 root 权限运行此脚本（sudo）。" >&2
  exit 1
fi

if ! command -v fish >/dev/null 2>&1; then
  echo "警告: 未检测到系统安装 fish，脚本仍会写入配置文件，但请自行确认 fish 已安装。" >&2
fi

FISH_CONF_DIR="/etc/fish/conf.d"
FISH_SCRIPT="${FISH_CONF_DIR}/${NAME}.fish"
RSYSLOG_CONF="/etc/rsyslog.d/${NAME}-fish.conf"
LOG_DIR="/var/log/${NAME}"
LOG_FILE="${LOG_DIR}/fish-history.log"
SYSLOG_FACILITY="local6"

echo "==> 部署 Fish 审计钩子，名称前缀: ${NAME}"
echo "    fish 配置:    ${FISH_SCRIPT}"
echo "    rsyslog 配置: ${RSYSLOG_CONF}"
echo "    日志文件:     ${LOG_FILE}"
echo

# ---------- 第一步: 生成 fish 审计函数 ----------
echo "==> [1/5] 生成 ${FISH_SCRIPT}"

mkdir -p "${FISH_CONF_DIR}"

cat >"${FISH_SCRIPT}" <<EOF
# Log interactive Fish commands through rsyslog.
# 只在交互式 shell 里生效，非交互（脚本执行）不记录。
status is-interactive; or exit 0

function __${NAME}_audit_fish --on-event fish_postexec
    set -l __${NAME}_rc \$status
    set -l __${NAME}_cmd \$argv[1]

    if test -n "\$__${NAME}_cmd"
        logger -p ${SYSLOG_FACILITY}.notice -t ${NAME} -- \\
            "shell=fish user=\$USER uid="(id -u)" pid=\$fish_pid cwd=\$PWD rc=\$__${NAME}_rc cmd=\$__${NAME}_cmd"
    end
end
EOF

chown root:root "${FISH_SCRIPT}"
chmod 0644 "${FISH_SCRIPT}"

if command -v fish >/dev/null 2>&1; then
  fish -n "${FISH_SCRIPT}"
  echo "    OK: 语法检查通过"
else
  echo "    跳过语法检查（本机未安装 fish）"
fi
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

TEST_MSG="setup-fish-verify-$(date +%s)"
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
echo "conf.d 下的脚本会在每个新开的 fish 会话自动加载，无需手动 source。"
echo "如果想让当前已打开的 fish 会话立即生效，可以在该会话里执行:"
echo "    source ${FISH_SCRIPT}"
echo
echo "查看审计日志:"
echo "    tail -f ${LOG_FILE}"
echo
echo "注意: 如果同一台机器上此前部署过 bash 版本的审计脚本，"
echo "两者日志文件是分开的（本脚本单独用 fish-history.log），"
echo "如需合并查看可以 tail -f 两个文件，或让两者写入同一个日志文件。"
echo "==================================================================="
```