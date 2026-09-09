# GitLab CI + Argo CD + Harbor 生产级 CI/CD 方案与实施验收 Runbook

> 文档状态：方案与实施基线
> 
> 适用范围：已有 GitLab CI、GitLab Runner、Argo CD、Harbor 和 Kubernetes，准备从“流程可用”提升到生产级治理的团队。
> 
> 本文不替代目标环境的版本、容量、网络、许可证、合规和业务确认。所有带有“需要确认”的项目必须在目标环境验证后才能作为生产结论。
> 
> 相关部署教程：[GitLab、GitLab Runner 与 Argo CD 的 GitOps 完整部署流程](GitLab-ArgoCD-GitLab-Runner-GitOps完整部署流程.md)

## 1. 使用方式与标记规则

本文按“目标架构 → 控制要求 → 实施阶段 → 验收证据 → 故障处置”的顺序编写。每个控制项使用以下标记：

- **[必须]**：生产上线前必须满足，否则只能作为测试或预生产环境使用。
- **[强烈建议]**：不一定阻断首次上线，但应在第一个生产迭代内完成。
- **[需要确认]**：依赖现网版本、许可证、组织流程或业务约束，不能直接假定。
- **[禁止]**：会造成不可审计、不可回滚或高风险权限扩散的做法。
- **[证据]**：需要保存的命令输出、日志、链接、MR 或演练记录。

生产级的判断标准不是 Pipeline 变绿，而是一次发布能够被重复构建、审批、同步、验证、回滚和取证。

## 2. 目标和非目标

### 2.1 目标

目标系统应具备以下能力：

1. 相同源码 Commit 可追溯到唯一镜像 Digest 和 GitOps Commit。
2. CI 构建、测试和制品发布与 Argo CD 集群同步职责分离。
3. 生产变更必须经过受保护分支、审批或发布窗口控制。
4. 生产集群不向普通 CI Job 暴露长期有效的管理员凭据。
5. 发布失败可以快速定位，并使用已验证版本回滚。
6. GitLab、Harbor、GitOps 仓库和 Argo CD 的关键数据可备份、可恢复。
7. 发布、审批、镜像、同步和业务验证之间存在可查询的证据关系。

### 2.2 非目标

本文不直接决定：

- 具体云厂商、硬件型号或 Kubernetes 发行版；
- 业务应用的副本数、JVM 参数或数据库拓扑；
- 组织最终采用飞书、钉钉、GitLab 原生审批还是其他审批系统；
- 某个版本的具体默认值。版本相关配置必须按目标实例文档和现场测试确认。

## 3. 目标架构与职责边界

### 3.1 推荐发布流

```mermaid
flowchart LR
    Dev[开发者] --> MR[GitLab Merge Request]
    MR --> CI[GitLab CI]
    CI --> Test[测试与质量门禁]
    Test --> Build[构建一次镜像]
    Build --> Harbor[Harbor 镜像仓库]
    Harbor --> Digest[镜像 Digest/SBOM/签名]
    Digest --> GMR[GitOps Merge Request]
    GMR --> Approval[生产审批与策略检查]
    Approval --> GitOps[GitOps 仓库]
    GitOps --> Argo[Argo CD]
    Argo --> K8s[Kubernetes]
    K8s --> Obs[日志/指标/追踪/审计]
    Obs --> Verify[业务验证与发布结论]
```

### 3.2 系统职责表

| 组件 | 生产职责 | 不应承担的职责 |
|---|---|---|
| GitLab | 源码、MR、Pipeline、审批、审计、制品元数据 | 不直接维护 Kubernetes 实际状态 |
| GitLab Runner | 执行测试、构建、扫描和 GitOps 更新任务 | 不持有长期生产集群管理员凭据 |
| Harbor | 镜像存储、扫描、SBOM、签名、复制、保留 | 不保存 Kubernetes 发布策略 |
| GitOps 仓库 | Helm values、Kustomize overlays、环境配置和变更历史 | 不保存明文密码、Token、私钥 |
| Argo CD | 读取 Git 声明、比较差异、同步和健康检查 | 不编译代码、不构建镜像 |
| Kubernetes | 运行工作负载、执行准入和资源隔离 | 不接受普通 CI Job 的长期管理员操作 |
| 监控与审计平台 | 记录发布结果、系统状态、业务验证和证据 | 不替代 Git 和 Argo CD 的期望状态 |

### 3.3 [禁止] 破坏职责边界的模式

- GitLab CI 在生产 Job 中直接执行 `kubectl apply`。
- GitLab CI 和 Argo CD 同时管理同一组 Kubernetes 资源。
- 生产使用 `latest`、`main` 或其他可变标签。
- 运维人员在 Argo CD UI 临时改参数，却不回写 GitOps 仓库。
- 通过 Pipeline 变量传入任意 Argo CD URL、任意集群地址或任意 Namespace。

## 4. 生产基线与上线阻断项

下表是上线前的最低基线。任一“必须”项没有证据，都应阻断生产发布。

| 分类 | 生产基线 | 上线证据 |
|---|---|---|
| 版本 | GitLab、Runner、Harbor、Argo CD、Kubernetes 固定完整版本 | 版本清单、升级记录 |
| 网络 | GitLab、Harbor、Argo CD 使用受控域名和 TLS；从 Runner、Argo CD、节点分别验证 | DNS、证书、实际请求结果 |
| 构建 | 构建一次，按 Commit SHA 和 Digest 发布 | Pipeline、镜像详情 |
| GitOps | 源码仓库与 GitOps 仓库分离；生产变更走 MR | 仓库结构、MR 记录 |
| 权限 | 分组、项目、Runner、Argo Project、Namespace 最小权限 | RBAC 矩阵、`can-i` 输出 |
| 安全 | 镜像扫描、Secret 扫描、SBOM、签名或等效控制 | 扫描报告、签名校验 |
| 发布 | 生产有审批、窗口、暂停和回滚策略 | 审批单、发布单、回滚记录 |
| 可观测性 | Pipeline、Argo、Kubernetes、应用日志可以关联 | trace/request ID、仪表盘 |
| 备份 | GitLab、Harbor、Argo 配置、GitOps 仓库均有备份 | 备份任务与恢复演练 |
| 演练 | 至少完成一次真实测试环境端到端发布和回滚 | 演练报告 |

## 5. 组织和仓库设计

### 5.1 推荐项目划分

```text
platform/
├── app-demo                 # 应用源码、Dockerfile、测试、CI模板引用
├── app-demo-gitops          # 应用GitOps配置
├── ci-templates              # 组织级CI模板
├── policy-library            # OPA/Kyverno/准入规则
└── platform-runbooks         # 发布、回滚、灾备和审计Runbook
```

**[必须]** 应用源码仓库和 GitOps 仓库分离。生产 GitOps 仓库至少启用：

- 受保护默认分支；
- 禁止直接 Push；
- 至少一名代码所有者审批；
- 强制 Pipeline 成功；
- 生产目录的 CODEOWNERS；
- 合并后保留 MR、Pipeline 和审批记录。

**[强烈建议]** 把 CI 模板、容器基础镜像、策略规则和 Runbook 纳入版本控制，避免每个项目自行复制一套不可维护的 YAML。

### 5.2 GitOps 仓库结构

```text
app-demo-gitops/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   └── kustomization.yaml
├── overlays/
│   ├── dev/
│   ├── test/
│   ├── staging/
│   └── prod/
│       ├── kustomization.yaml
│       ├── namespace.yaml
│       └── values.yaml
├── applicationsets/
└── README.md
```

**[必须]** 生产环境的镜像引用使用 Digest 或由 Digest 固定的版本记录。示例：

```yaml
images:
  - name: registry.example.com/platform/app-demo
    digest: sha256:<IMAGE_DIGEST>
```

**[禁止]** 在生产 overlay 中只写 `newTag: latest`，或让 CI 通过字符串替换任意 YAML 字段。

## 6. GitLab CI 生产化方案

### 6.1 Pipeline 分层

推荐的阶段顺序：

```text
validate
→ unit-test
→ build
→ image-scan
→ integration-test
→ publish-metadata
→ update-gitops
→ deploy-verify
```

其中：

- `validate`：YAML、Dockerfile、Helm、Kustomize、代码格式和依赖锁定检查；
- `unit-test`：快速反馈，失败时不得进入镜像发布；
- `build`：只构建一次并记录 Commit SHA；
- `image-scan`：扫描镜像、依赖、Secret 和 SBOM；
- `integration-test`：在临时 Namespace 或测试环境验证真实依赖；
- `update-gitops`：只提交 GitOps MR，不直接改生产集群；
- `deploy-verify`：由 Argo CD 或发布编排服务返回同步结果后执行业务验证。

### 6.2 Pipeline 参考模板

下面是结构模板，镜像构建工具、扫描器和 GitOps 更新工具必须按现网选择确认。

```yaml
stages:
  - validate
  - test
  - build
  - scan
  - gitops

variables:
  IMAGE_REPOSITORY: "$HARBOR_HOST/$HARBOR_PROJECT/$CI_PROJECT_NAME"
  IMAGE_TAG: "$CI_COMMIT_SHA"

workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - when: never

validate:
  stage: validate
  script:
    - ./ci/validate-manifests.sh
    - ./ci/check-secrets.sh

unit-test:
  stage: test
  script:
    - ./ci/test.sh
  artifacts:
    when: always
    reports:
      junit: reports/junit.xml

build-image:
  stage: build
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
  script:
    - ./ci/build-and-push.sh "$IMAGE_REPOSITORY:$IMAGE_TAG"
    - ./ci/write-image-metadata.sh
  artifacts:
    paths:
      - image-metadata.json

scan-image:
  stage: scan
  needs: [build-image]
  script:
    - ./ci/scan-image.sh image-metadata.json
    - ./ci/generate-sbom.sh image-metadata.json

update-gitops:
  stage: gitops
  needs: [scan-image]
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
  script:
    - ./ci/create-gitops-mr.sh image-metadata.json
```

**[必须]** CI 记录以下字段：

```text
source_commit
pipeline_id
job_id
image_repository
image_tag
image_digest
sbom_reference
scan_result
gitops_commit
target_environment
```

### 6.3 Runner 隔离

至少划分以下 Runner 标签：

| 标签 | 用途 | 权限要求 |
|---|---|---|
| `build-unprivileged` | 普通编译、测试、Lint | 无特权容器 |
| `build-image` | 镜像构建 | 单独节点池和缓存策略 |
| `security-scan` | 漏洞、SBOM、Secret 扫描 | 只读制品权限 |
| `release-metadata` | 更新 GitOps MR | 仅 GitOps 仓库最小写权限 |

**[必须]**：

- Runner 使用 authentication token，并按项目或组限制范围；
- 生产相关 Runner 使用 `protected` 标签；
- 限制 `concurrent`、单 Runner `limit` 和 Job 超时；
- Job 结束后清理工作目录和临时凭据；
- 记录 Runner 版本、执行器、节点和 Job 关联信息。

**[禁止]** 普通项目共享一个具有 `privileged`、宿主机挂载和集群管理员权限的 Runner。

## 7. Harbor 生产化方案

### 7.1 项目和权限

建议按环境或业务域划分 Harbor 项目：

```text
harbor.example.com/platform-dev/
harbor.example.com/platform-test/
harbor.example.com/platform-staging/
harbor.example.com/platform-prod/
```

**[必须]**：

- CI 使用 Robot Account，不使用 Harbor 管理员账号；
- 推送、拉取、删除权限分离；
- 生产项目禁止普通开发者删除镜像；
- 对生产标签启用不可变规则；
- 重要项目启用漏洞扫描和扫描阻断阈值；
- 配置镜像保留策略和垃圾回收窗口。

### 7.2 制品供应链

建议的镜像生命周期：

```text
源码 Commit
→ 镜像构建
→ 镜像 Digest
→ 漏洞扫描
→ SBOM
→ 签名
→ 推送到非生产项目
→ 预生产验证
→ 复制或晋级到生产项目
→ Kubernetes 准入校验
```

**[强烈建议]** 生产环境只允许通过 Digest 部署，并在准入层校验签名、来源仓库和漏洞策略。

**[需要确认]** Harbor 的扫描器、签名方式、复制策略、对象存储和保留期限要结合 Harbor 版本、许可证和现有存储容量确定。

### 7.3 Harbor 备份

备份范围至少包括：

- Harbor 数据库；
- Registry 镜像数据或对象存储桶；
- Harbor 配置和证书；
- 项目、Robot Account 和复制规则；
- 扫描结果和审计记录（按合规要求）。

备份成功不等于可恢复。**[必须]** 定期在隔离环境恢复一个项目、拉取一个镜像并验证 Digest 一致性。

## 8. Argo CD 生产化方案

### 8.1 AppProject 权限边界

每个业务域或环境建立独立 `AppProject`，限制：

- 允许的 Git 仓库；
- 允许的目标集群和 Namespace；
- 允许创建的资源类型；
- 是否允许 Cluster-scoped 资源；
- 项目角色和 Token 权限。

**[必须]** 调用方只能提交服务端注册的 `environment_id` 和应用标识，不能提交任意 Argo CD 地址、任意集群地址或任意 Namespace。

### 8.2 同步策略

| 环境 | 自动同步 | 自动修复 | 自动清理 |
|---|---:|---:|---:|
| dev | 是 | 是 | 可选 |
| test | 是 | 视资源类型 | 谨慎开启 |
| staging | 可选 | 谨慎开启 | 谨慎开启 |
| prod | 审批后同步 | 按应用确认 | 默认关闭或白名单 |

**[注意]** 对生产启用 `prune` 前，必须确认 Application 管理边界。误配置可能删除 StatefulSet、PVC、Ingress 或外部系统创建的资源。

### 8.3 多应用和发布顺序

对有依赖关系的应用使用明确的同步顺序：

```text
Namespace / RBAC
→ Secret / ConfigMap
→ CRD / Operator
→ Database migration
→ Service / Deployment
→ Ingress / Gateway
```

不要用不透明的资源名称或人工点击顺序代替声明式依赖。需要更细粒度流量控制时，评估 Argo Rollouts 或服务网格，并把健康指标写入发布方案。

### 8.4 Argo CD 高可用

**[需要确认]** 是否使用 HA 安装取决于应用数量、仓库数量、集群数量、同步频率和可用性目标。生产至少应评估：

- controller 副本和分片；
- repo-server 副本、缓存和仓库并发；
- server 副本和入口高可用；
- Redis 高可用或故障恢复方式；
- Pod 反亲和、节点分布和 PDB；
- Argo CD 配置、Repository、Project、Application 的备份。

## 9. Kubernetes 运行基线

### 9.1 工作负载要求

每个生产 Deployment 至少应定义：

- `resources.requests` 和 `resources.limits`；
- `readinessProbe`、`livenessProbe`，必要时增加 `startupProbe`；
- `securityContext`；
- `terminationGracePeriodSeconds`；
- `topologySpreadConstraints` 或等效分布策略；
- PodDisruptionBudget；
- 生产日志格式和请求关联 ID。

### 9.2 命名空间隔离

生产 Namespace 应配置：

- `ResourceQuota`；
- `LimitRange`；
- `NetworkPolicy`；
- ServiceAccount 最小权限；
- Pod Security 标准或等效准入策略；
- 镜像来源、签名和标签策略。

### 9.3 配置与 Secret

**[禁止]** 将密码、Token、私钥、完整 `.env` 或生产 kubeconfig 提交到 GitOps 仓库。

推荐使用：

- External Secrets Operator；
- Vault 或云密钥服务；
- Kubernetes Secret 加密存储；
- 只在发布时注入的短期凭据。

## 10. 安全、权限和审计

### 10.1 最小权限矩阵

| 主体 | 允许操作 | 不允许操作 |
|---|---|---|
| 开发者 | 提交分支、创建 MR、查看非生产日志 | 直接合并生产、读取生产 Secret |
| 代码所有者 | 审查代码和配置 | 绕过 Pipeline 保护 |
| 发布人员 | 审批生产发布、触发回滚 | 修改集群管理员权限 |
| GitLab CI | 构建、扫描、更新 GitOps MR | 直接写生产 Kubernetes |
| Argo CD | 同步已授权 Application | 访问未注册集群和 Namespace |
| 集群管理员 | 平台运维和 break-glass | 使用共享账号执行日常发布 |

### 10.2 发布证据链

每次生产发布至少关联以下字段：

```text
source_commit
pipeline_id
job_id
image_digest
sbom_digest
signature_reference
gitops_commit
approval_id
approver
argocd_application
argocd_revision
argocd_operation_id
kubernetes_audit_id
business_verification_id
rollback_revision
```

**[强烈建议]** 将关键审计事件写入独立日志平台或不可变对象存储。数据库内哈希链只能辅助发现篡改，不能替代独立的不可变归档。

### 10.3 审计告警

建议对以下事件告警：

- 生产分支保护被修改；
- Runner 注册、删除或标签变化；
- Robot Account 权限变化；
- Harbor 生产镜像删除或复制失败；
- Argo CD Application 进入 `OutOfSync` 超过阈值；
- 生产资源被集群外部修改；
- 生产发布未经过审批；
- 回滚频率异常升高；
- 审计或日志采集链路中断。

## 11. 可观测性和 SLO

### 11.1 最小监控面板

#### CI/CD 平台

- Pipeline 成功率和平均耗时；
- 队列等待时间；
- Runner online 数量、忙碌数量和失败 Job；
- Harbor 推送、拉取、扫描和复制错误；
- Argo CD 同步成功率和 `OutOfSync` 持续时间；
- 生产发布次数、失败次数和回滚次数。

#### Kubernetes 和业务

- 节点 CPU、内存、磁盘、网络和不可调度状态；
- Pod 重启、Pending、CrashLoopBackOff；
- Deployment 可用副本和发布进度；
- 应用错误率、延迟、吞吐和关键业务指标；
- 发布前后对比窗口。

### 11.2 推荐发布 SLO

具体数值需要按业务确认，可以先建立以下指标：

| 指标 | 定义 |
|---|---|
| 发布成功率 | 成功完成业务验证的生产发布 / 总生产发布 |
| 变更失败率 | 触发回滚、热修复或重大告警的发布 / 总生产发布 |
| 发布耗时 | 从批准到业务验证完成的时间 |
| 恢复时间 | 从发现故障到恢复稳定版本的时间 |
| 漂移修复时间 | Argo CD 检测到漂移到恢复期望状态的时间 |

## 12. 发布、回滚与故障处置

### 12.1 标准生产发布

1. 开发者创建源码 MR。
2. CI 执行校验、测试、构建和扫描。
3. 生成镜像 Digest、SBOM 和签名。
4. CI 创建 GitOps MR，写入目标环境和 Digest。
5. 代码所有者和发布人员审批。
6. 合并 GitOps MR，触发 Argo CD 同步。
7. 检查 Argo CD 同步状态、Workload 健康和业务请求。
8. 记录发布结论与证据链接。

### 12.2 发布阻断条件

遇到以下情况应暂停发布：

- 镜像扫描严重漏洞未豁免；
- 镜像签名或来源校验失败；
- GitOps 差异包含未授权的 Cluster-scoped 资源；
- Argo CD 处于异常、漂移或同步队列积压；
- 业务错误率、延迟或资源使用已超过阈值；
- 备份、审计或告警链路不可用；
- 审批人、目标环境或发布 Digest 与变更单不一致。

### 12.3 回滚方法

优先使用 GitOps 回滚：


```text
确认故障版本和影响范围
→ 找到上一个已验证 GitOps Commit
→ 创建回滚 MR
→ 审批并合并
→ Argo CD 同步
→ 验证业务和数据一致性
→ 记录回滚原因与后续修复项
```

**[注意]** 数据库迁移可能不可逆。应用回滚前必须确认旧版本能读取当前数据库结构，必要时采用向前兼容迁移和分阶段清理。

### 12.4 Break-glass

紧急情况下允许的临时权限必须满足：

- 有明确的事件编号和授权人；
- 使用个人账号或短期身份，不使用共享密码；
- 操作全量审计；
- 事后回写 GitOps 状态；
- 结束后立即回收权限；
- 在复盘中确认为什么正常发布流程无法处理。

## 13. 备份、恢复和灾难演练

### 13.1 备份对象

| 对象 | 备份内容 | 恢复验证 |
|---|---|---|
| GitLab | 数据库、仓库、附件、Artifact、配置和密钥材料 | 登录、拉取仓库、查看 Pipeline |
| Harbor | 数据库、镜像对象、配置、证书和复制规则 | 拉取指定 Digest 并校验 |
| GitOps | Git 仓库及远程副本 | 恢复到临时仓库并由 Argo CD 渲染 |
| Argo CD | Application、Project、Repository、集群注册和配置 | 重建控制面并同步测试应用 |
| Kubernetes | etcd 或云厂商备份、PV 数据和外部依赖 | 恢复 Namespace、工作负载和业务数据 |
| 审计 | 日志、发布记录、审批记录和不可变归档 | 按发布 ID 查询完整证据链 |

### 13.2 恢复目标

**[需要确认]** 由业务和管理制度确定 RPO/RTO。至少记录：

- GitLab 不可用时如何提交紧急变更；
- Harbor 不可用时是否有镜像副本；
- Argo CD 重建后如何恢复 Application；
- Kubernetes 恢复后如何恢复外部 DNS、证书、存储和数据库；
- 审计系统不可用时是否阻断生产发布。

### 13.3 演练频率

建议至少每季度完成一次以下演练：

1. GitLab 备份恢复；
2. Harbor 项目和镜像恢复；
3. Argo CD 重建和 GitOps 同步；
4. 单个应用版本回滚；
5. Runner 大面积离线；
6. 审计日志或通知链路中断。

## 14. 分阶段实施计划

### 阶段一：职责和发布入口统一

目标：停止直接生产部署，建立清晰 GitOps 入口。

- [ ] 源码仓库与 GitOps 仓库分离；
- [ ] 生产分支和 GitOps 生产目录启用保护；
- [ ] CI 只构建、测试、扫描并创建 GitOps MR；
- [ ] Argo CD 成为生产唯一持续同步控制器；
- [ ] 所有应用固定镜像 SHA 或 Digest；
- [ ] 完成一次测试环境端到端发布。

### 阶段二：安全和质量门禁

目标：让不符合策略的制品不能进入生产。

- [ ] Harbor Robot Account 和最小权限；
- [ ] 镜像漏洞扫描和阻断阈值；
- [ ] Secret、SAST、依赖扫描；
- [ ] SBOM 生成和归档；
- [ ] 镜像签名和准入校验；
- [ ] Runner 隔离和特权任务收敛；
- [ ] Namespace 资源、网络和 Pod 安全策略。

### 阶段三：发布治理和可观测性

目标：生产发布可控、可观测、可回滚。

- [ ] 生产审批、变更窗口和发布冻结；
- [ ] AppProject、ApplicationSet 和多环境映射；
- [ ] 发布前后业务验证；
- [ ] 失败自动暂停和人工回滚；
- [ ] Pipeline、Argo、Kubernetes、应用日志关联；
- [ ] 关键指标和发布告警上线；
- [ ] 建立 DORA 和平台 SLO。

### 阶段四：高可用和灾备

目标：平台故障时能够恢复发布能力和审计能力。

- [ ] GitLab、Harbor、Argo CD 高可用设计；
- [ ] 备份与异地或独立存储；
- [ ] 恢复演练和 RPO/RTO 验证；
- [ ] 镜像跨仓库或跨地域复制；
- [ ] Break-glass 流程和权限回收；
- [ ] 审计证据不可变归档；
- [ ] 完成一次完整灾难演练。

## 15. 上线验收清单

### 15.1 静态检查

- [ ] GitLab CI YAML 通过目标实例 CI Lint；
- [ ] Helm/Kustomize 渲染成功；
- [ ] Kubernetes Server-side dry-run 成功；
- [ ] 生产 Manifest 不包含明文 Secret；
- [ ] 镜像引用不使用 `latest`；
- [ ] GitOps MR 能够展示清晰差异；
- [ ] Markdown、YAML、Mermaid 和本地链接检查通过。

### 15.2 端到端测试

- [ ] 提交测试 Commit；
- [ ] Runner 成功领取并执行 Job；
- [ ] 镜像推送到 Harbor；
- [ ] Harbor 扫描、SBOM 和签名成功；
- [ ] GitOps MR 自动或按规则创建；
- [ ] 审批拒绝时发布不会继续；
- [ ] 审批通过后 Argo CD 同步；
- [ ] Workload Ready、探针正常、业务请求成功；
- [ ] 生产或预生产回滚成功；
- [ ] 全链路证据可查询。

### 15.3 故障注入

- [ ] Runner 离线；
- [ ] Harbor 暂时不可用；
- [ ] Argo CD repo-server 不可用；
- [ ] Kubernetes 节点不可调度；
- [ ] 新版本 Readiness 失败；
- [ ] 镜像签名校验失败；
- [ ] GitOps 产生未授权资源；
- [ ] 审批回调重复或乱序；
- [ ] 发布后业务错误率升高。

## 16. 每周、每月和每季度检查

### 每周

- [ ] 检查 Pipeline 失败率、Runner 队列和积压；
- [ ] 检查 Harbor 存储、扫描失败和复制失败；
- [ ] 检查 Argo CD `OutOfSync`、健康异常和同步失败；
- [ ] 检查生产 Namespace 的 Pod 重启、资源超限和事件；
- [ ] 检查最近生产发布是否都有审批和业务验证证据。

### 每月

- [ ] 检查项目成员、组成员和 Token 到期时间；
- [ ] 检查 Runner 标签、特权配置和未使用 Runner；
- [ ] 检查 Harbor Robot Account、保留策略和漏洞豁免；
- [ ] 检查 Argo CD Project、Repository 和 Cluster 权限；
- [ ] 执行一次 GitOps 漂移和回滚抽查；
- [ ] 检查备份成功率和存储增长。

### 每季度

- [ ] 执行 GitLab、Harbor、Argo CD 恢复演练；
- [ ] 轮换高风险凭据和检查历史凭据是否仍有效；
- [ ] 复核 RBAC、网络策略和生产审批人；
- [ ] 复核版本支持周期和升级路径；
- [ ] 做一次发布故障或节点故障演练；
- [ ] 更新 RPO/RTO、SLO 和容量预测。

## 17. 实施前必须补齐的现网参数

以下信息未确认前，本文只能作为方案基线，不能直接作为变更单执行稿：

```text
GitLab Edition与完整版本：
GitLab Runner版本、Executor和并发：
Harbor版本、存储后端和扫描器：
Argo CD版本、Application数量和目标集群数量：
Kubernetes版本、节点池和准入策略：
GitLab/Harbor/Argo CD域名和证书来源：
生产Namespace与资源配额：
镜像保留期限与漏洞阻断阈值：
审批系统与审批人规则：
日志、指标、审计和不可变归档位置：
RPO/RTO、发布窗口和回滚时限：
```

**最终验收原则：** 只有在真实目标环境完成“提交代码 → Pipeline → Harbor → GitOps MR → 审批 → Argo CD 同步 → 业务验证 → 回滚/取证”的完整演练后，才能把系统标记为生产就绪。
