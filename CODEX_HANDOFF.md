# Codex 工作交接

更新时间：2026-08-10 19:16 CST
当前主机：本地 macOS；本阶段未使用远程服务器
项目路径：`/Users/lijiaxuan/Documents/hermes`
当前分支：`main`

## 当前目标

编写一套不绑定具体服务器的 Kubernetes + Helm Victoria 全栈生产级监控方案，覆盖指标、日志、告警、外部探测、可选链路追踪、高可用、安全、备份和验收。

## 已确认事实

- 用户明确要求使用 Kubernetes + Helm，且本方案不使用前一阶段检查的具体服务器参数。
- 通用方案采用 `victoria-metrics-k8s-stack` 作为主线，使用 VMAgent、VMSingle/VMCluster、VMAlert、VictoriaLogs、VLAgent、Grafana 和 Blackbox Exporter，VictoriaTraces 与 OpenTelemetry 作为按需增强。
- 方案同时提供标准版和高可用版，不把单机容量参数作为通用默认值。
- VictoriaMetrics 官方 K8s Stack 当前可统一部署指标、日志和 Trace，并自动配置相关 Grafana 数据源。

以下是前一阶段仍然有效的历史记录：

- 远程监控由 `kube-prometheus-stack` 和 `Fluent Bit + VictoriaLogs` 组成。
- Prometheus 12 个 active target 全部为 `up`。
- VictoriaLogs 健康且已有日志；Fluent Bit 当前输出错误、重试和放弃批次均为 0。
- Alertmanager 当前 receiver 为 `null`，没有实际通知出口。
- Prometheus、Alertmanager 无 PVC；Grafana 使用 2Gi PVC；VictoriaLogs 使用 10Gi PVC。
- 远程目录 values 中存在明文弱口令，未写入本地文档或本交接文件。

## 基于证据的判断

- 通用方案需要同时覆盖组件选择、Helm 生命周期、业务接入规范、告警治理和恢复能力，仅安装几个 Chart 不能视为完整监控体系。
- 中小集群和关键生产集群的副本、存储与长期保留需求差异较大，因此采用两档架构更合理。
- 中小集群优先使用 VMSingle + VLSingle；存在明确横向扩展或高可用需求后再使用 VMCluster + VLCluster。
- 生产环境将 VictoriaMetrics Operator 与 K8s Stack 分开部署，更便于管理 CRD、受管 CR 和 Namespace 删除顺序。

以下是前一阶段仍然有效的历史判断：

- 当前属于单节点基础监控方案，可用于日常观察，但不具备生产级高可用和完整告警能力。
- 日志链路早期曾因写入路径缺少 `/insert` 被 VictoriaLogs 拒绝，当前配置已经修正并正常写入。
- `log/values.yaml` 的 hostPath 设计与集群实际 PVC 存储不一致，存在配置漂移。

## 尚未验证的可能性

- 各目标集群的节点规模、日志量、指标基数、StorageClass、Ingress、对象存储和通知渠道尚未给出，方案中的容量值为初始建议，部署前需按实际环境调整。
- Chart 具体版本未锁定；实施时必须选择与目标 Kubernetes 版本兼容并经过测试的版本。

以下是前一阶段遗留的待确认项：

- Grafana 页面中可能手工添加了 VictoriaLogs 数据源，自动 provisioning 中未发现。
- 云安全组或主机防火墙是否允许公网访问 Grafana、VictoriaLogs NodePort 尚未验证。
- `helm list -A` 的 Kubernetes API 资源发现错误根因尚未确认。

## 已完成

- 编写通用 Kubernetes + Helm 生产级监控方案。
- 提供标准版与高可用版架构、组件职责、容量起点和数据流。
- 将原 Prometheus + Loki 主线完整改写为 Victoria 全栈方案。
- 提供 Victoria Stack values、VMServiceScrape、VMRule 等配置模板。
- 补充 VMAgent/VLAgent 持久缓冲、VMAuth、VictoriaLogs、VictoriaTraces 和 Prometheus CRD 转换策略。
- 补充日志、追踪、SLO、告警路由、安全、备份、升级回滚和验收标准。
- 本阶段未修改或查询任何远程服务器。

前一阶段已完成：

- 只读盘点远程目录、Chart、工作负载、Service、PVC、监控 CRD 和关键 ConfigMap。
- 验证 Prometheus、VictoriaLogs、Fluent Bit 当前链路状态。
- 编写监控流程、风险和分阶段改进方案文档。

## 修改文件

- `运维笔记/监控/Kubernetes-Helm生产级监控方案.md`
- `运维笔记/监控/175.27.144.105-K3s监控流程与方案.md`
- `CODEX_HANDOFF.md`

## 验证结果

- Victoria 全栈方案文档共 1348 行，Markdown 标题结构正常。
- 通用方案未写入密码、Token、Webhook 或其他凭据。
- `git diff --check` 通过。

前一阶段验证结果：

- 文档共 354 行，Markdown 标题结构正常。
- `git diff --check` 通过。
- 文档未包含远程 values 中的具体口令。

## 未解决问题

- 尚未针对某个目标 Kubernetes 环境生成最终 values 文件，也未执行 Helm 安装；当前交付范围为通用方案文档。
- 未按建议修改远程监控配置；本次范围仅为只读检查和本地文档整理。

## 下一步

1. 收集目标集群规模、Kubernetes 版本、StorageClass、Ingress、域名和通知渠道。
2. 选择 VMSingle + VLSingle 标准版或 VMCluster + VLCluster 高可用版，并锁定 Chart 版本。
3. 根据目标环境拆分 Operator、Stack、Secret 引用、VMRule 和 Dashboard 文件。
4. 在测试集群执行 lint、template、diff、安装和故障演练。
5. 通过验收后再推广到生产集群。

## 重要命令

- `helm lint <chart> -f <values-file>`
- `helm template <release> <chart> --namespace observability --version <locked-version> -f <values-file>`
- `helm upgrade --install <release> <chart> --namespace observability --version <locked-version> -f <values-file> --atomic --timeout 15m`
- `helm show crds vm/victoria-metrics-k8s-stack --version <target-version> | kubectl diff -f -`
- `helm show crds vm/victoria-metrics-k8s-stack --version <target-version> | kubectl apply -f - --server-side`
- `helm history <release> -n observability`
- `helm rollback <release> <revision> -n observability --wait --timeout 15m`

前一阶段远程检查命令：

- `ssh root@175.27.144.105`
- `cd /home/ubuntu/monitor`
- `kubectl get pods,svc,pvc -n monitoring`
- `kubectl get servicemonitor,prometheusrule -A`
- `kubectl logs -n monitoring daemonset/fluent-bit --since=10m`
- `kubectl logs -n monitoring statefulset/kps-log-victoria-logs-single-server --since=10m`

## 注意事项

- 通用方案中的容量是初始建议，必须依据 active series、日志日增量、Trace 采样率和实际磁盘增长调整。
- Chart 字段会随版本变化，部署前必须依据锁定版本执行 `helm lint`、`helm template` 和 diff。
- Helm 不会自动升级已有 VictoriaMetrics CRD，Stack 升级前必须单独执行 CRD diff、备份和 server-side apply。
- 生产管理端口默认使用 ClusterIP，只通过 Ingress、TLS 和身份认证开放。
- 不要把 Secret 写入 Git、values、日志、Dashboard 或交接文档。

前一阶段注意事项：

- 后续变更前先解决 `helm list -A` 报错，并使用 `helm template` 核对渲染结果。
- 不要把 Grafana 密码、Kubernetes Secret 或其他凭据写入 Git 和交接文档。
- VictoriaLogs 当前实际使用 PVC，不是目录文件描述的 `/home/ubuntu/monitor/log/data` hostPath。
