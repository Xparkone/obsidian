# Codex 工作交接

更新时间：2026-09-01 20:06:55 +0800

当前主机：dpdeMacBook-Pro-86.local

项目路径：/Users/lijiaxuan/Documents/hermes

当前分支：main

## 当前目标

整理 GitLab、GitLab Runner 与 Argo CD 从零部署到 GitOps 发布、验收、回滚和审计取证的详细流程，并在现有 Deploy Recorder 基础上设计支持飞书、钉钉审批和多个 Argo CD 环境的发布编排与审计服务。

## 已确认事实

- 笔记库已有 GitLab Compose、Argo CD、海外弹性 Runner、GitLab CI 语法和 Deploy Recorder 示例，缺少一份贯穿三套系统的主流程。
- GitLab 官方当前仍提供 Docker Compose 安装方式，并要求生产环境固定完整镜像版本；`config`、`logs`、`data` 需要持久化。
- GitLab Runner 官方 Kubernetes Helm Chart 使用 `runnerToken`/Runner authentication token；旧 `runnerRegistrationToken` 工作流已不推荐。
- 旧 Runner 文档中发现疑似真实 registration token，已从文档删除并替换为占位符；若该 Token 仍然有效，需要在对应 GitLab 实例旋转。
- Argo CD 官方生产安装优先使用 HA 清单；非 HA `install.yaml` 适合学习和验证。
- 新主文档已加入 `运维笔记/README.md` 的 CI-CD 分类索引。
- GitLab 审计事件、强制 MR/部署审批、实例级审计和外部审计流的能力会受版本与许可证影响，实施前必须按目标实例核对。
- Kubernetes Audit Event 由 kube-apiserver 生成，与普通 Kubernetes Event 不同；托管集群通常需要通过云厂商控制台或 API 开启。
- 现有 Deploy Recorder 可以关联 Pipeline、Deployment、Argo CD Sync 和 audit_logs，但没有独立不可变归档时不能单独作为防篡改审计系统。
- 现有 Deploy Recorder 的部署接口可以直接创建部署记录，所有 API 共用静态 `X-API-Key`，Argo CD Webhook 按最近一条 pending/syncing 记录关联；它适合演示事后记录，不具备审批门禁、多 Argo CD 路由、细粒度授权和可靠幂等能力。
- 飞书审批 v4 支持创建审批实例，并可使用 `uuid` 做调用方关联；审批事件需要完成应用事件订阅和指定审批定义订阅。回调不能只信任请求体，必须验签/解密并主动查询实例详情。
- 钉钉开放平台同时存在新版工作流接口和旧版 OA 审批接口文档；目标企业应用实际可用接口必须以当前 API Explorer 和应用权限为准，不能混用 Token、字段和 SDK。

## 基于证据的判断

- 推荐部署顺序为 GitLab -> GitLab Runner -> Argo CD -> GitOps 仓库接入 -> 首次端到端验收。
- CI 负责测试、BuildKit rootless 构建镜像和更新 GitOps 仓库；Argo CD 负责集群同步，可避免普通 CI Job 长期持有生产集群凭据。
- 应使用源码仓库与 GitOps 仓库分离、Commit SHA/digest 镜像、最小 RBAC、保护分支/环境和短期 Token。
- GitLab 19.1+ 可在严格 allowlist 和目标项目授权下使用跨项目 `CI_JOB_TOKEN` push；低版本应使用短期、最小权限的 Project Access Token。
- 审计设计应以 Source Commit、Pipeline/Job、Image digest、GitOps Commit、Argo CD revision 和 Kubernetes auditID 为主键建立证据关系，而不是只保存页面截图。
- 正式审计需要业务审计库、日志平台/SIEM 和独立 Object Lock/WORM 归档分层；数据库内哈希链只能辅助发现篡改，不能对抗同时控制数据库和哈希计算的管理员。
- 新服务应采用“发布单不可变快照 + 审批适配器 + 持久化状态机 + Transactional Outbox + 环境注册表 + GitOps/Argo CD 适配器”，审批通过只是部署必要条件，部署前仍需复核 payload hash、目标集合、策略版本和环境状态。
- 多 Argo CD 应使用“统一治理、分区执行”：生产/非生产、地域或安全域使用独立控制面，环境映射由服务端注册，调用方只提交 `environment_id`，不得传任意 Argo CD URL。
- 生产优先在审批通过后合并或提交 GitOps 变更，再由目标 Argo CD 调谐；直接调用 Argo CD Sync 只用于明确关闭自动同步且 RBAC 受控的场景。

## 尚未验证的可能性

- 尚未在目标 GitLab、Registry 和 Kubernetes 集群执行部署。
- 文档中的 GitLab、Runner Chart 和 Argo CD 版本使用待确认占位符，必须根据目标环境固定并测试。
- BuildKit rootless 是否被目标集群 AppArmor、seccomp、Pod Security 或节点内核阻止，需要现场验证。
- Mermaid 已完成结构检查，但未使用浏览器或 `mmdc` 做渲染级验证。
- 审计留存期、不可变要求、职责分离和审计故障时是否阻断发布，仍需由安全、内审、法务或客户确认。
- GitLab 审计功能、Kubernetes Audit Policy、Argo CD Notifications 和 Deploy Recorder 增强尚未在真实环境配置或验证。
- 发布编排与审计服务目前仅完成设计，没有实现数据库迁移、API、Worker、审批适配器、GitOps/Argo CD 适配器和 Reconciler。
- 尚未在真实飞书/钉钉租户创建审批实例，也未验证审批定义、表单字段、事件订阅、回调网络和目标租户的接口版本。
- 尚未连接任何 Argo CD 实例验证环境路由、项目 Token、TLS、Application、revision 和多目标 wave。

## 已完成

- 新增 1153 行以上的 GitLab、Runner、Argo CD GitOps 主流程文档。
- 增加部署顺序、Runner Job、日常发布、首次验收和回滚 5 张 Mermaid `sequenceDiagram`。
- 覆盖部署前参数/网络规划、GitLab Compose 与 Registry TLS、Runner Token Secret 与 Helm、Argo CD 固定版本安装、Kustomize GitOps 结构、BuildKit rootless Pipeline、分层验收、回滚、故障定位和生产检查。
- 在 Deploy Recorder 示例 README 增加主流程入口，避免把扩展示例误认为基础安装文档。
- 更新海外弹性 Runner 文档的认证提示，删除疑似真实 Token，改用 `runnerToken` 占位符。
- 主文档新增审计落地章节，覆盖审计口径、证据关系、统一字段、GitLab/Runner/Registry/Argo CD/Kubernetes 采集、证据 JSON、dotenv/Artifact、Audit Policy、Deploy Recorder 增强、WORM 归档、职责分离、告警、每日对账和取证演练。
- 增加第 6 张 Mermaid `sequenceDiagram`，描述从 MR、审批、构建、镜像、GitOps、Argo CD、Kubernetes 到 SIEM 和不可变归档的审计过程。
- 新增 803 行《发布编排与审计服务设计：飞书、钉钉审批与多 Argo CD》，覆盖目标边界、不可绕过规则、组件、领域模型、状态机、多 Argo CD 环境路由、飞书/钉钉适配器、API、权限、审计、可靠性、故障行为和三阶段实施计划。
- 新设计包含 3 张 Mermaid `sequenceDiagram`：审批到部署完整时序、Webhook 验签去重与主动确认、多 Argo CD 路由和失败保护。
- 在总 README、GitOps 主流程和 Deploy Recorder README 增加新设计文档入口。

## 修改文件

- `运维笔记/CI-CD/GitLab-ArgoCD-GitLab-Runner-GitOps完整部署流程.md`
- `运维笔记/CI-CD/gitlab-ci-argocd/README.md`
- `运维笔记/CI-CD/海外弹性GitLab-Runner构建方案.md`
- `运维笔记/README.md`
- `运维笔记/CI-CD/发布编排审计服务-多ArgoCD与飞书钉钉审批设计.md`
- `CODEX_HANDOFF.md`

## 验证结果

- 主文档 136 个 Markdown 代码围栏成对。
- 6 个 Mermaid 代码块均为 `sequenceDiagram`，围栏闭合。
- 15 个 YAML 代码块通过 Ruby Psych 语法解析，1 个 JSON 代码块通过 JSON 解析。
- 主文档全部本地 Markdown 链接目标存在。
- 已搜索并确认旧文档中的疑似真实 Runner Token 不再存在。
- `git diff --check` 无错误。
- 没有执行真实安装、GitLab CI Lint、Helm render、Kubernetes server-side dry-run 或业务请求。
- 新设计文档 38 个 Markdown 代码围栏成对，5 个 JSON 代码块通过 JSON 解析，3 个 Mermaid 代码块均为 `sequenceDiagram` 且包含参与者。
- 新增文档入口目标文件均存在；全库 README 的完整本地链接检查仍会命中既有缺失目录 `CI-CD/examples/gitlab-compose/`，该问题不是本阶段引入。

## 未解决问题

- 需要确认目标 GitLab/Kubernetes 版本、域名、可信 CA、镜像仓库、IngressClass、StorageClass、网络策略、Runner 并发和资源额度。
- 需要确认旧 Runner 文档中的 Token 是否对应仍在使用的 GitLab；若是，应立即旋转并检查异常 Runner。
- 需要在测试环境完成真实 Git push、Runner Job、Registry push/pull、GitOps 提交、Argo CD Sync、业务请求和回滚演练。
- 需要确认适用审计制度、保留期限、GitLab 许可证、集群控制面权限、SIEM/对象存储目标、职责分离和 break-glass 流程。
- 需要确认飞书或钉钉作为首个审批渠道、正式审批定义、审批人规则、是否允许一单多环境、生产 wave 和失败回滚策略。
- 需要确认服务实现栈和队列：第一版建议延续 FastAPI/PostgreSQL，并增加独立 Worker 与 Outbox；长流程复杂后再评估 Temporal。

## 下一步

1. 确认首期范围：飞书或钉钉、目标 Argo CD 实例、环境表、审批规则、GitOps 模式和审计策略。
2. 先设计 Alembic 数据库迁移与 OpenAPI，建立 `release_requests`、目标、审批、环境、事件、Webhook 和 Outbox 表。
3. 实现发布状态机、幂等、非法跳转保护和 Reconciler，再接审批与部署适配器。
4. 在测试环境演练审批通过、拒绝、撤回、超时、伪造/重复回调、服务重启、多目标 wave 和回滚。
5. 完成一次真实 GitOps 发布和取证，记录 Source Commit、Image digest、payload hash、审批实例、GitOps Commit、Argo CD revision 和业务结果。

## 重要命令

```bash
git -C /Users/lijiaxuan/Documents/hermes status --short
git -C /Users/lijiaxuan/Documents/hermes diff --check
docker compose config
helm search repo gitlab/gitlab-runner --versions
kubectl -n gitlab-runner get pods
kubectl -n argocd get deployment,statefulset,pod
argocd app get demo-api-production
```

## 既有阶段记录（2026-09-01，Kubernetes Ingress，保留）

- 已完善 `运维笔记/容器编排/Kubernetes-Ingress-部署与使用详解.md`，README 已建立索引。
- 文档区分 Ingress 声明式路由与 Ingress Controller 实际代理，增加客户端请求和配置调谐 2 张 Mermaid `sequenceDiagram`。
- 增加 Traefik 与 F5/NGINX 示例、IngressClass、LoadBalancer/NodePort/MetalLB、TLS、验证和迁移边界。
- 已完成 Markdown、Mermaid、YAML、本地链接和 `git diff --check` 静态检查；尚未在真实集群安装和执行端到端请求。
- Kubernetes 社区 `kubernetes/ingress-nginx` 已于 2026 年 3 月停止维护，新部署应重新评估仍维护的 Controller 或 Gateway API。

## 既有阶段记录（2026-08-26，GitLab CI/CD，保留）

此前已完善运维笔记库中的 GitLab CI/CD YAML 中文教程，使其适合初学者循序学习，并与 GitLab 19.3 当时官方语法保持一致：

- 主教程位于 `运维笔记/CI-CD/GitLab CICD YAML详细语法与使用方法.md`，README 已有索引。
- GitLab 19.3 于 2026-08-20 发布。
- GitLab 18.10 引入 job inputs，要求 GitLab Runner 18.9 或更高版本。
- `include:cache` 从 GitLab 19.0 起正式可用，仅适用于 `include:remote`。
- 已增加六步学习路线和四层验证边界、Job `inputs`、`spec:inputs`、`include:inputs`、`include:cache`、`manual_confirmation` 和关键词速查项。
- 110 个 YAML 代码块通过 Ruby Psych 语法解析，232 个 Markdown 围栏配对正常，本地 Markdown 链接和 `git diff --check` 通过。
- 尚未连接目标 GitLab 项目执行 CI Lint，也未在真实 Runner 或部署环境运行示例。
- Self-Managed 实例可能低于 GitLab 19.3，新增语法是否可用需要按实例和 Runner 版本确认。
- 后续应在练习项目逐步提交 `.gitlab-ci.yml`，使用目标项目 Pipeline editor 的 CI Lint 和 pipeline simulation，再结合实际技术栈补充构建、发布、健康检查和回滚命令。

## 既有阶段记录（2026-08-25，Grafana 仪表盘，保留）

此前已完成运维笔记中 Kubernetes 与 Linux 宿主机 Grafana 通用仪表盘的静态交付：

- 原有两份模板，新增 Kubernetes 工作负载与 Pod、节点容量与调度、网络与存储、控制面以及 Node Exporter 宿主机性能深挖五份模板；七份模板共 198 个顶层面板，均使用 `DS_PROMETHEUS` 数据源变量。
- 已修正原宿主机概览“最高磁盘使用率”的 PromQL 括号和聚合位置错误，并完成 JSON 语法、schema、UID、面板 ID、变量引用、PromQL 括号和文档链接静态检查。
- 相关文件位于 `运维笔记/监控/`，总索引为 `运维笔记/README.md`。
- 尚未在真实 Grafana 和 Prometheus 验证全部查询。现场仍需确认 Grafana、kube-state-metrics 版本以及 `job`、`instance`、`node` 等标签；控制面、PSI、conntrack、卷统计等面板是否有数据取决于实际抓取指标。
- Dashboard 展示阈值不能代替告警规则；部分 cAdvisor 指标可能缺少 `node` 标签，需要按现场数据做关联或 relabel。

## 注意事项

- 当前只完成文档和静态验证，没有实际部署或修改 Kubernetes 集群。
- 不得把密码、Token、Cookie、私钥、TLS 私钥或完整认证头补写到文档和交接文件中。
- Helm 返回成功、Pod Ready、Ingress 有地址都不等于业务已经端到端可用，必须发起实际 Host/SNI 请求。
- 不要在没有盘点业务 Ingress 的情况下卸载或替换 Controller。
- 当前工作区可能受自动 `vault backup` 任务影响；继续修改前重新读取文件并检查 Git 状态。
