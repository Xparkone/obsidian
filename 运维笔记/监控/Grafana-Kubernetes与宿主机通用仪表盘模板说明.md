# Grafana Kubernetes 与宿主机通用仪表盘模板说明

## 1. 模板清单

这些 JSON 都可以单独导入 Grafana。建议先导入概览，再按排障对象导入详细看板。

| 范围 | JSON | 业务面板数 | 主要用途 |
|---|---|---:|---|
| Kubernetes | [[Grafana-Kubernetes-集群整体监控仪表盘.json]] | 26 | 节点、Pod、工作负载与 API Server 集群总览 |
| Kubernetes | [[Grafana-Kubernetes-工作负载与Pod详细监控.json]] | 25 | Pod/容器 CPU、内存、节流、重启、OOM、工作负载就绪率 |
| Kubernetes | [[Grafana-Kubernetes-节点容量与调度监控.json]] | 25 | 节点可分配量、请求/限制、实际使用、压力状态、调度容量 |
| Kubernetes | [[Grafana-Kubernetes-网络与存储详细监控.json]] | 24 | Pod 网络、Service/Endpoint、PV/PVC、卷容量与健康 |
| Kubernetes | [[Grafana-Kubernetes-控制面健康监控.json]] | 26 | API Server、Scheduler、Controller Manager、etcd |
| Linux 宿主机 | [[Grafana-Node-Exporter-宿主机监控仪表盘.json]] | 19 | CPU、内存、磁盘、网络、进程基础总览 |
| Linux 宿主机 | [[Grafana-Node-Exporter-宿主机性能深挖仪表盘.json]] | 28 | PSI、磁盘时延、IOPS、TCP、丢包、conntrack、文件系统预测 |

“业务面板数”不包含使用说明和分组行。

## 2. 指标来源

| 组件 | 主要指标 | 对应看板 |
|---|---|---|
| Prometheus | 查询和存储所有时序指标 | 全部 |
| kube-state-metrics | Kubernetes 对象状态、请求、限制、容量、条件 | 全部 Kubernetes 看板 |
| kubelet / cAdvisor | 容器 CPU、内存、网络、节流与卷统计 | 工作负载、节点、网络与存储 |
| kube-apiserver | 请求速率、响应码、延迟、并发请求 | 集群整体、控制面 |
| kube-scheduler | 待调度 Pod、调度结果与耗时 | 控制面 |
| kube-controller-manager | workqueue 深度、重试和处理耗时 | 控制面 |
| etcd | Leader、数据库大小、磁盘提交、Peer RTT | 控制面 |
| node-exporter | Linux CPU、内存、磁盘、网络、内核与 PSI | 两份宿主机看板 |

## 3. 导入方法

1. 进入 Grafana 的 **Dashboards → New → Import**。
2. 上传一个 JSON 文件。
3. 在 **Prometheus** 变量中选择实际 Prometheus 数据源。
4. 导入后先检查顶部变量是否有选项，再检查使用说明中的依赖指标。
5. 如需修改模板，建议使用 **Save as** 保存成现场版本，保留原始通用模板。

所有查询都引用 `${DS_PROMETHEUS}`，不会把某个环境的数据源 UID 写死在 JSON 中。

## 4. 导入后的最小验证

在 Grafana Explore 中逐条执行：

```promql
up
count(kube_node_info)
count(kube_pod_info)
count(container_cpu_usage_seconds_total{container!="", image!=""})
count(node_uname_info)
count(kubelet_volume_stats_capacity_bytes)
count(apiserver_request_total)
```

判断方式：

- `kube_node_info`、`kube_pod_info` 无数据：检查 kube-state-metrics target 和 ServiceMonitor。
- `container_cpu_usage_seconds_total` 无数据：检查 kubelet/cAdvisor 抓取和 RBAC。
- `node_uname_info` 无数据：检查 node-exporter target、`job` 与 `instance` 标签。
- `kubelet_volume_stats_*` 无数据：可能没有 PVC，也可能 kubelet 未暴露卷统计，需要结合 PVC 实际情况判断。
- 控制面看板无数据：先看顶部四个 job 变量。托管 Kubernetes 可能不开放 Scheduler、Controller Manager 或 etcd 指标。
- 只有部分节点或 Pod 无数据：检查变量筛选值、Prometheus relabel 配置和指标上的 `node`、`namespace`、`pod` 标签。

## 5. 兼容性与现场适配

模板按 Grafana `schemaVersion: 41` 生成，PromQL 以 kube-state-metrics 2.x、常见 kube-prometheus-stack 和 node-exporter 指标名为基线。

以下内容需要按现场确认：

- 老版本 kube-state-metrics 可能使用 `kube_pod_container_resource_requests_cpu_cores`、`kube_pod_container_resource_requests_memory_bytes` 等旧指标名，而模板使用统一的 `kube_pod_container_resource_requests{resource=...,unit=...}`。
- 部分 cAdvisor 指标没有 `node` 标签，节点维度查询需要通过 `kube_pod_info` 做标签关联，或在 Prometheus 抓取时补充标签。
- 网络面板只使用通用 cAdvisor 指标，不包含 Cilium、Calico 等 CNI 私有指标。
- PSI、conntrack、systemd、thermal 等 node-exporter 指标取决于 collector、内核和宿主机权限；无数据时先确认采集能力。
- 模板中的 70%、85%、90% 等阈值是通用起点，不是已经验证过的生产告警阈值。
- Dashboard 阈值只负责展示，不等于 Grafana Alerting 或 Prometheus 告警规则。

## 6. 验证边界

当前已经完成：

- JSON 语法校验；
- dashboard 标题、UID、schema、面板 ID 唯一性检查；
- Prometheus 数据源变量引用检查；
- 变量引用完整性静态检查；
- 文件名、标题和 README 索引检查。

当前尚未完成：

- 在真实 Grafana 中逐份导入；
- 在真实 Prometheus 上执行全部 PromQL；
- 按现场标签、组件版本和采集权限适配；
- 生产阈值、告警规则和通知送达验证。

