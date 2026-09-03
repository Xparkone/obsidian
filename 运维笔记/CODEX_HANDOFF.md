# Codex 工作交接

更新时间：2026-09-02
当前主机：本地 macOS
项目路径：`/Users/lijiaxuan/Documents/hermes/运维笔记`
当前分支：`main`

## 当前目标

编写 GitLab 详细日志审计的中文运维文档，说明审计事件、结构化组件日志、外部事件流、集中采集和验收流程。

## 已确认事实

- 现有笔记按主题分类，GitLab 文档归入 `CI-CD/`，根目录索引为 `README.md`。
- 当前仓库没有已有 `CODEX_HANDOFF.md`；本文件为本阶段新增交接文件。
- 官方文档当前说明：Audit Events 的 UI/API 能力按版本和套餐变化；实例级外部审计事件流适用于 Ultimate 的 Self-Managed/Dedicated；`audit_json.log`、`api_json.log`、`production_json.log` 等结构化日志按安装方式有不同路径。

## 基于证据的判断

- “开详细审计”应拆成数据库审计事件、GitLab 组件日志和外部集中留存三层，不能依赖单一 debug 日志级别。
- 长期审计应使用外部采集、事件 `id` 去重、`correlation_id` 关联和不可变归档；页面 CSV 不应作为唯一证据。

## 尚未验证的可能性

- 目标 GitLab 实例的 Edition、版本、许可证、安装方式、实际日志挂载、网络出口和 SIEM 接收端尚未现场确认。
- 文档中的命令和验收动作未在真实 GitLab、SIEM、云存储或 Kubernetes 集群执行。

## 已完成

- 新增 `CI-CD/GitLab审计日志详细配置与运维指南.md`。
- 更新 `README.md`，加入新文档索引。
- 完成围栏、Mermaid、内部链接和差异空白静态检查。

## 修改文件

- `CI-CD/GitLab审计日志详细配置与运维指南.md`
- `README.md`
- `CODEX_HANDOFF.md`

## 验证结果

- Markdown 围栏：20 个，成对。
- Mermaid `sequenceDiagram`：1 个。
- 新文档内部链接：未发现缺失。
- `git diff --check`：通过；新文件单独执行差异检查也通过。

## 未解决问题

- 未针对任何具体 GitLab 实例生成可直接执行的变更命令；必须先确认版本、套餐、安装方式和权限。

## 下一步

- 如需落地，先执行文档第 2.3 节只读预检。
- 按目标套餐选择 UI/API、`audit_json.log` 采集或 Ultimate 外部事件流。
- 使用测试 Group/Project 完成第 9 节事件生成、送达、去重、告警和归档验收。

## 重要命令

- Omnibus：`sudo gitlab-rake gitlab:env:info`、`sudo gitlab-ctl status`。
- Docker：`docker ps`、`docker inspect <gitlab-container>`。
- Helm：`kubectl -n <gitlab-namespace> get pods -o wide`、`helm -n <gitlab-namespace> list`。

## 注意事项

- 不在交接文档中记录密码、Token、Cookie、完整认证 Header、云密钥或完整环境变量。
- 不能把“进程健康、HTTP 200、日志文件存在”当作审计端到端成功；需要验证事件生成、落库/文件、外部送达和归档。

## 本阶段：脚本与工具整理（2026-09-03）

### 当前目标

按用途整理 `脚本与工具/` 下的 kubectl 工具和 Shell 命令审计文档，并补充索引。

### 已确认事实

- kubectl 相关文档已归入 `脚本与工具/kubectl/`。
- Bash/Fish 审计、日志轮转和卸载文档已归入 `脚本与工具/shell-audit/`。
- 原有文档内容未改写；迁移后的 6 个已跟踪文件与迁移前内容 SHA-256 一致。
- `脚本与工具/x.md` 的删除状态在本阶段未处理，仍保留为原有工作区变更。

### 已完成

- 新增 `脚本与工具/README.md` 作为分类索引和使用顺序说明。
- 更新根目录 `README.md` 的分类描述与文档路径。

### 验证结果

- 索引中的 8 个相对链接均能解析到现有文件。
- `脚本与工具/` 下 Markdown 代码围栏均成对。
- `git diff --check` 通过，未发现新增尾随空格。

### 下一步

- 若后续将 Markdown 中的脚本提取为独立 `.sh` 文件，需要另行确认命名、执行权限和发布方式；本阶段未做提取或执行验证。
