# Codex 工作交接

更新时间：2026-09-01 15:42:20 +0800

当前主机：dpdeMacBook-Pro-86.local

项目路径：/Users/lijiaxuan/Documents/hermes

当前分支：main

## 当前目标

整理一份 GitLab、GitLab Runner 与 Argo CD 从零部署到 GitOps 发布、验收和回滚的详细流程文档，并使用 Mermaid `sequenceDiagram` 表达主要交互过程。

## 已确认事实

- 笔记库已有 GitLab Compose、Argo CD、海外弹性 Runner、GitLab CI 语法和 Deploy Recorder 示例，缺少一份贯穿三套系统的主流程。
- GitLab 官方当前仍提供 Docker Compose 安装方式，并要求生产环境固定完整镜像版本；`config`、`logs`、`data` 需要持久化。
- GitLab Runner 官方 Kubernetes Helm Chart 使用 `runnerToken`/Runner authentication token；旧 `runnerRegistrationToken` 工作流已不推荐。
- 旧 Runner 文档中发现疑似真实 registration token，已从文档删除并替换为占位符；若该 Token 仍然有效，需要在对应 GitLab 实例旋转。
- Argo CD 官方生产安装优先使用 HA 清单；非 HA `install.yaml` 适合学习和验证。
- 新主文档已加入 `运维笔记/README.md` 的 CI-CD 分类索引。

## 基于证据的判断

- 推荐部署顺序为 GitLab -> GitLab Runner -> Argo CD -> GitOps 仓库接入 -> 首次端到端验收。
- CI 负责测试、BuildKit rootless 构建镜像和更新 GitOps 仓库；Argo CD 负责集群同步，可避免普通 CI Job 长期持有生产集群凭据。
- 应使用源码仓库与 GitOps 仓库分离、Commit SHA/digest 镜像、最小 RBAC、保护分支/环境和短期 Token。
- GitLab 19.1+ 可在严格 allowlist 和目标项目授权下使用跨项目 `CI_JOB_TOKEN` push；低版本应使用短期、最小权限的 Project Access Token。

## 尚未验证的可能性

- 尚未在目标 GitLab、Registry 和 Kubernetes 集群执行部署。
- 文档中的 GitLab、Runner Chart 和 Argo CD 版本使用待确认占位符，必须根据目标环境固定并测试。
- BuildKit rootless 是否被目标集群 AppArmor、seccomp、Pod Security 或节点内核阻止，需要现场验证。
- Mermaid 已完成结构检查，但未使用浏览器或 `mmdc` 做渲染级验证。

## 已完成

- 新增 1153 行以上的 GitLab、Runner、Argo CD GitOps 主流程文档。
- 增加部署顺序、Runner Job、日常发布、首次验收和回滚 5 张 Mermaid `sequenceDiagram`。
- 覆盖部署前参数/网络规划、GitLab Compose 与 Registry TLS、Runner Token Secret 与 Helm、Argo CD 固定版本安装、Kustomize GitOps 结构、BuildKit rootless Pipeline、分层验收、回滚、故障定位和生产检查。
- 在 Deploy Recorder 示例 README 增加主流程入口，避免把扩展示例误认为基础安装文档。
- 更新海外弹性 Runner 文档的认证提示，删除疑似真实 Token，改用 `runnerToken` 占位符。

## 修改文件

- `运维笔记/CI-CD/GitLab-ArgoCD-GitLab-Runner-GitOps完整部署流程.md`
- `运维笔记/CI-CD/gitlab-ci-argocd/README.md`
- `运维笔记/CI-CD/海外弹性GitLab-Runner构建方案.md`
- `运维笔记/README.md`
- `CODEX_HANDOFF.md`

## 验证结果

- 主文档 110 个 Markdown 代码围栏成对。
- 5 个 Mermaid 代码块均为 `sequenceDiagram`，围栏闭合。
- 10 个 YAML 代码块通过 Ruby Psych 语法解析。
- 主文档全部本地 Markdown 链接目标存在。
- 已搜索并确认旧文档中的疑似真实 Runner Token 不再存在。
- `git diff --check` 无错误。
- 没有执行真实安装、GitLab CI Lint、Helm render、Kubernetes server-side dry-run 或业务请求。

## 未解决问题

- 需要确认目标 GitLab/Kubernetes 版本、域名、可信 CA、镜像仓库、IngressClass、StorageClass、网络策略、Runner 并发和资源额度。
- 需要确认旧 Runner 文档中的 Token 是否对应仍在使用的 GitLab；若是，应立即旋转并检查异常 Runner。
- 需要在测试环境完成真实 Git push、Runner Job、Registry push/pull、GitOps 提交、Argo CD Sync、业务请求和回滚演练。

## 下一步

1. 收集目标环境参数，固定 GitLab、Runner Chart 和 Argo CD 版本。
2. 若疑似泄露的旧 Runner Token 仍有效，先在 GitLab 旋转或删除对应 Runner。
3. 在测试环境按主文档顺序部署，使用 CI Lint、Helm render 和 server-side dry-run 补足语义验证。
4. 完成一次端到端发布和 Git revert 回滚，记录 Source Commit、Image digest、GitOps Commit、Argo CD revision 和业务结果。

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
