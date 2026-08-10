# Codex 工作交接

更新时间：2026-08-10 17:56 CST
当前主机：本地 macOS；只读检查远程主机 175.27.144.105
项目路径：`/Users/lijiaxuan/Documents/hermes`
当前分支：`main`

## 当前目标

总结远程 `/home/ubuntu/monitor` 的 K3s 监控流程与改进方案，并写入本地运维笔记。

## 已确认事实

- 远程监控由 `kube-prometheus-stack` 和 `Fluent Bit + VictoriaLogs` 组成。
- Prometheus 12 个 active target 全部为 `up`。
- VictoriaLogs 健康且已有日志；Fluent Bit 当前输出错误、重试和放弃批次均为 0。
- Alertmanager 当前 receiver 为 `null`，没有实际通知出口。
- Prometheus、Alertmanager 无 PVC；Grafana 使用 2Gi PVC；VictoriaLogs 使用 10Gi PVC。
- 远程目录 values 中存在明文弱口令，未写入本地文档或本交接文件。

## 基于证据的判断

- 当前属于单节点基础监控方案，可用于日常观察，但不具备生产级高可用和完整告警能力。
- 日志链路早期曾因写入路径缺少 `/insert` 被 VictoriaLogs 拒绝，当前配置已经修正并正常写入。
- `log/values.yaml` 的 hostPath 设计与集群实际 PVC 存储不一致，存在配置漂移。

## 尚未验证的可能性

- Grafana 页面中可能手工添加了 VictoriaLogs 数据源，自动 provisioning 中未发现。
- 云安全组或主机防火墙是否允许公网访问 Grafana、VictoriaLogs NodePort 尚未验证。
- `helm list -A` 的 Kubernetes API 资源发现错误根因尚未确认。

## 已完成

- 只读盘点远程目录、Chart、工作负载、Service、PVC、监控 CRD 和关键 ConfigMap。
- 验证 Prometheus、VictoriaLogs、Fluent Bit 当前链路状态。
- 编写监控流程、风险和分阶段改进方案文档。

## 修改文件

- `运维笔记/监控/175.27.144.105-K3s监控流程与方案.md`
- `CODEX_HANDOFF.md`

## 验证结果

- 文档共 354 行，Markdown 标题结构正常。
- `git diff --check` 通过。
- 文档未包含远程 values 中的具体口令。

## 未解决问题

- 未按建议修改远程监控配置；本次范围仅为只读检查和本地文档整理。

## 下一步

1. 轮换 Grafana 管理员密码并移除 values 明文。
2. 配置 Alertmanager 实际 receiver 并验证测试告警。
3. 收紧 NodePort 暴露，补充 HTTPS 和认证。
4. 为 Prometheus、Alertmanager 增加持久化。
5. 解决 Helm API 发现错误并统一实际 release values。

## 重要命令

- `ssh root@175.27.144.105`
- `cd /home/ubuntu/monitor`
- `kubectl get pods,svc,pvc -n monitoring`
- `kubectl get servicemonitor,prometheusrule -A`
- `kubectl logs -n monitoring daemonset/fluent-bit --since=10m`
- `kubectl logs -n monitoring statefulset/kps-log-victoria-logs-single-server --since=10m`

## 注意事项

- 后续变更前先解决 `helm list -A` 报错，并使用 `helm template` 核对渲染结果。
- 不要把 Grafana 密码、Kubernetes Secret 或其他凭据写入 Git 和交接文档。
- VictoriaLogs 当前实际使用 PVC，不是目录文件描述的 `/home/ubuntu/monitor/log/data` hostPath。
