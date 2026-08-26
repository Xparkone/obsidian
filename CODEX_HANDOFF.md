# Codex 工作交接

更新时间：2026-08-26
当前主机：dpdeMacBook-Pro-86.local
项目路径：/Users/lijiaxuan/Documents/hermes
当前分支：main

## 当前目标

完善运维笔记库中的 GitLab CI/CD YAML 中文教程，使其适合初学者循序学习，并与 GitLab 19.3 当前官方语法保持一致。

## 已确认事实

- 现有主教程位于 `运维笔记/CI-CD/GitLab CICD YAML详细语法与使用方法.md`，README 已有索引。
- GitLab 19.3 于 2026-08-20 发布。
- GitLab 18.10 引入 job inputs，要求 GitLab Runner 18.9 或更高版本。
- `include:cache` 从 GitLab 19.0 起正式可用，仅适用于 `include:remote`。

## 基于证据的判断

- 原教程语法主体仍有效，主要缺口是初学者学习顺序、job inputs、配置 inputs 的完整说明以及 `include:cache`。

## 尚未验证的可能性

- Self-Managed 实例可能低于 GitLab 19.3，新增语法是否可用需要按实例和 Runner 版本确认。

## 已完成

- 增加六步学习路线和四层验证边界。
- 增加 Job `inputs` 语法、示例、限制及三类参数机制对照。
- 完善 `spec:inputs`、`include:inputs` 示例与作用域说明。
- 增加 `include:cache`、`manual_confirmation` 和关键词速查项。
- 更新官方参考资料与核对日期。

## 修改文件

- `运维笔记/CI-CD/GitLab CICD YAML详细语法与使用方法.md`
- `CODEX_HANDOFF.md`

## 验证结果

- 110 个 YAML 代码块通过 Ruby Psych 语法解析。
- 232 个 Markdown 围栏配对正常。
- 本地 Markdown 链接检查通过。
- `git diff --check` 通过。
- 未连接目标 GitLab 项目执行 CI Lint，也未在真实 Runner 或部署环境运行示例。

## 未解决问题

- 需要在用户实际 GitLab 实例中确认版本、Runner executor、Runner 版本及可用权限。
- 生产部署示例需要替换为用户项目的真实构建、发布、健康检查和回滚命令后再验证。

## 下一步

1. 在练习项目按教程前六个练习逐步提交 `.gitlab-ci.yml`。
2. 每一步使用目标项目 Pipeline editor 的 CI Lint 和 pipeline simulation。
3. 再根据实际技术栈补充 Node.js、Java、Go 或容器镜像构建实例。

## 重要命令

```bash
git diff --check
git status --short
```

## 既有阶段记录（2026-08-25，保留）

此前已完成运维笔记中 Kubernetes 与 Linux 宿主机 Grafana 通用仪表盘的静态交付：

- 原有两份模板，新增 Kubernetes 工作负载与 Pod、节点容量与调度、网络与存储、控制面以及 Node Exporter 宿主机性能深挖五份模板；七份模板共 198 个顶层面板，均使用 `DS_PROMETHEUS` 数据源变量。
- 已修正原宿主机概览“最高磁盘使用率”的 PromQL 括号和聚合位置错误，并完成 JSON 语法、schema、UID、面板 ID、变量引用、PromQL 括号和文档链接静态检查。
- 相关文件位于 `运维笔记/监控/`，总索引为 `运维笔记/README.md`。
- 尚未在真实 Grafana 和 Prometheus 验证全部查询。现场仍需确认 Grafana、kube-state-metrics 版本以及 `job`、`instance`、`node` 等标签；控制面、PSI、conntrack、卷统计等面板是否有数据取决于实际抓取指标。
- dashboard 展示阈值不能代替告警规则；部分 cAdvisor 指标可能缺少 `node` 标签，需要按现场数据做关联或 relabel。

## 注意事项

- 静态 YAML 解析不等于 GitLab CI 语义校验。
- pipeline passed 不等于应用部署后的健康检查通过。
- 不要把密码、令牌或完整认证信息写入 `.gitlab-ci.yml`、日志、cache 或 artifacts。
- 当前工作区包含未提交修改，不要覆盖或清理。
