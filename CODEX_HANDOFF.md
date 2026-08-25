# Codex 工作交接

更新时间：2026-08-25 14:33:57 CST
当前主机：dpdeMacBook-Pro-86.local
项目路径：/Users/lijiaxuan/Documents/hermes
当前分支：main

## 当前目标

在运维笔记的监控分类下提供可导入 Grafana 的 Kubernetes 与 Linux 宿主机通用详细仪表盘 JSON。

## 已确认事实

- 原有两份模板：Kubernetes 集群整体监控、Node Exporter 宿主机监控。
- 本阶段新增五份模板：Kubernetes 工作负载与 Pod、节点容量与调度、网络与存储、控制面、Node Exporter 宿主机性能深挖。
- 七份模板共 198 个顶层面板，数据源均通过 `DS_PROMETHEUS` 变量选择。
- 原宿主机概览“最高磁盘使用率”查询存在 PromQL 括号和聚合位置错误，已修正。

## 基于证据的判断

- JSON 结构和变量引用已通过静态检查，可以进入 Grafana 导入验证阶段。
- 控制面、PSI、conntrack、卷统计等面板是否有数据，取决于现场组件是否暴露并抓取对应指标。

## 尚未验证的可能性

- Grafana 现场版本、Prometheus 标签和 kube-state-metrics 版本可能需要适配。
- 部分 cAdvisor 指标可能没有 `node` 标签，节点维度查询可能需要 PromQL 关联或 relabel。

## 已完成

- 新增五份详细 dashboard JSON。
- 新增模板说明文档并更新总 README 索引。
- 完成 JSON 语法、schema、UID、面板 ID、变量引用、PromQL 括号与文档链接静态检查。

## 修改文件

- `运维笔记/README.md`
- `运维笔记/监控/Grafana-Kubernetes与宿主机通用仪表盘模板说明.md`
- `运维笔记/监控/Grafana-Kubernetes-工作负载与Pod详细监控.json`
- `运维笔记/监控/Grafana-Kubernetes-节点容量与调度监控.json`
- `运维笔记/监控/Grafana-Kubernetes-网络与存储详细监控.json`
- `运维笔记/监控/Grafana-Kubernetes-控制面健康监控.json`
- `运维笔记/监控/Grafana-Node-Exporter-宿主机性能深挖仪表盘.json`
- `运维笔记/监控/Grafana-Node-Exporter-宿主机监控仪表盘.json`
- `CODEX_HANDOFF.md`

## 验证结果

- `jq` 可解析全部七份 JSON。
- dashboard UID 和面板 ID 无重复。
- 变量引用完整，说明文档中的七个 JSON 链接均存在。
- `git diff --check` 通过。
- 尚未在真实 Grafana 和 Prometheus 上验证全部查询结果。

## 未解决问题

- 需要现场导入并根据实际 `job`、`instance`、`node` 等标签调整查询。
- 需要确认生产告警阈值；dashboard 展示阈值不能代替告警规则。

## 下一步

1. 先导入集群整体和宿主机概览模板。
2. 在 Grafana Explore 执行说明文档中的最小指标检查。
3. 逐份导入详细模板，记录无数据面板和实际标签。
4. 按现场版本适配 PromQL，再单独设计告警规则与通知验证。

## 重要命令

```bash
jq empty 运维笔记/监控/Grafana-*.json
git -C /Users/lijiaxuan/Documents/hermes diff --check
```

## 注意事项

- 当前工作区包含未提交修改，不要覆盖或清理。
- 无数据只能说明当前查询没有返回序列，不能直接判定服务健康或故障。
