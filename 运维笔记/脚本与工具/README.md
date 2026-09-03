# 脚本与工具

按使用场景整理的运维脚本与工具文档。

## kubectl 工具

| 工具 | 用途 | 文档 |
|---|---|---|
| `k` | kubectl 快捷操作、资源查看、Pod 操作、Deployment 操作和 GPU 查看 | [使用说明](kubectl/kubectl-快捷工具-k.md) · [安装说明](kubectl/kubectl-快捷工具-k-安装说明.md) |
| `kf` | 基于 `fzf` 的交互式 kubectl 操作台，支持 Pod、Deployment、Node、Event 和 GPU 视图 | [使用说明](kubectl/kubectl-交互式工具-kf.md) · [安装说明](kubectl/kubectl-交互式工具-kf-安装说明.md) |

## Shell 命令审计

这组脚本通过 Shell 钩子、`logger`、`rsyslog` 和 `logrotate` 记录交互式命令。建议按以下顺序使用：部署 Bash/Fish 审计 → 配置日志轮转 → 验证日志 → 不再使用时卸载。

| 场景 | 文档 |
|---|---|
| Bash 命令审计部署 | [日志审计-bash.md](shell-audit/日志审计-bash.md) |
| Fish 命令审计部署 | [日志审计-fish.md](shell-audit/日志审计-fish.md) |
| 审计日志轮转 | [日志轮转.md](shell-audit/日志轮转.md) |
| 卸载审计钩子 | [卸载审计脚本.md](shell-audit/卸载审计脚本.md) |

> Shell 审计脚本会写入 `/etc`、`/var/log` 并可能重启 `rsyslog`，执行前请确认主机、权限、日志保留策略和变更窗口。
