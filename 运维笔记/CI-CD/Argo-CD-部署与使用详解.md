# Argo CD 部署与使用详解

> 适用范围：在 Kubernetes 中安装、配置并使用 Argo CD 管理应用持续交付。
>
> 文档核对日期：2026-08-18。示例以 Argo CD 3.x 为基线；执行生产变更前，应再核对目标版本的升级说明。
>
> 官方文档：[Argo CD 文档](https://argo-cd.readthedocs.io/en/stable/)、[GitHub Releases](https://github.com/argoproj/argo-cd/releases)。

## 1. Argo CD 是什么

Argo CD 是运行在 Kubernetes 内的声明式 GitOps 持续交付工具。它持续比较两类状态：

- 期望状态：Git、Helm 仓库或 OCI 中保存的 Kubernetes 清单。
- 实际状态：目标 Kubernetes 集群中正在运行的资源。

两者不一致时，Application 会显示为 `OutOfSync`；资源正常运行时通常显示为 `Healthy`。用户可以手动同步，也可以让 Argo CD 自动同步、删除 Git 中已移除的资源，并修复绕过 Git 的集群内改动。

典型发布过程如下：

```text
开发者提交代码
      │
      ▼
CI 测试并构建镜像
      │
      ▼
CI/自动化更新配置仓库中的镜像标签
      │
      ▼
Argo CD 检测 Git 变化并生成 Kubernetes 清单
      │
      ▼
比较差异 → 同步到目标集群 → 检查健康状态
```

Argo CD 负责 CD，不负责源代码编译和镜像构建。CI 系统不需要直接持有生产集群凭据，只需更新 Git 中的部署配置。

## 2. 核心对象与组件

### 2.1 核心对象

| 对象 | 作用 |
|---|---|
| `Application` | 定义一个应用的来源、目标集群、命名空间和同步策略 |
| `AppProject` | 对一组 Application 限制允许使用的仓库、集群、命名空间和资源类型 |
| `ApplicationSet` | 根据集群、目录、Git 文件、列表等生成多个 Application |
| Repository Secret | 保存 Git/Helm/OCI 仓库地址及访问凭据 |
| Cluster Secret | 保存外部目标集群的 API 地址和访问凭据 |

`Application`、`ApplicationSet` 和 `AppProject` 默认应创建在 Argo CD 所在命名空间，即 `argocd`，它们描述的业务资源则部署到 `spec.destination.namespace`。

### 2.2 主要组件

| 组件 | 作用 | 排障重点 |
|---|---|---|
| `argocd-server` | Web UI、API、CLI 和认证入口 | 登录、Ingress、TLS、RBAC |
| `argocd-application-controller` | 比较期望状态和实际状态并执行同步 | 同步、健康检查、集群连接 |
| `argocd-repo-server` | 拉取仓库并运行 Helm/Kustomize/Jsonnet 生成清单 | 仓库认证、清单渲染、插件 |
| `argocd-applicationset-controller` | 根据生成器创建和维护 Application | 多集群、多环境、批量应用 |
| `argocd-dex-server` | 可选的 OIDC/SAML 身份代理 | SSO 登录 |
| Redis | 缓存及部分临时状态 | 延迟、连接、HA |
| `argocd-notifications-controller` | 根据触发器发送通知 | 通知模板、订阅、密钥 |

## 3. 部署前规划

### 3.1 基础要求

- 已有可用 Kubernetes 集群和 CoreDNS。
- 本机已安装 `kubectl`，`kubeconfig` 指向正确集群。
- 安装者具有创建 CRD、ClusterRole 和 ClusterRoleBinding 的权限；命名空间级安装除外。
- Argo CD Pod 能访问 Git/Helm/OCI 仓库和目标集群 API。
- 生产环境已规划域名、TLS、SSO、RBAC、备份和监控。
- 镜像仓库和 Git 仓库的访问凭据采用最小权限账号。

部署前确认当前上下文：

```bash
kubectl config current-context
kubectl cluster-info
kubectl auth can-i create customresourcedefinitions.apiextensions.k8s.io
kubectl auth can-i create clusterrolebindings.rbac.authorization.k8s.io
```

### 3.2 安装模式选择

| 模式 | 适用场景 | 特点 |
|---|---|---|
| 非 HA 多租户 | 本地、测试、功能验证 | 完整 UI/API，单副本组件，不建议用于生产 |
| HA 多租户 | 生产环境、多个团队 | 多副本和高可用配置，仍需自行设置资源、存储、反亲和等 |
| Namespace 模式 | 团队隔离、平台不给集群级权限 | CRD 需单独安装；权限和可管理范围受限 |
| Core | 管理员个人使用、无 UI/SSO/多集群需求 | 无常驻 API Server 和 UI，主要依赖 Kubernetes RBAC |
| Helm Chart | 希望 values 化管理和升级 | Chart 由 argo-helm 社区维护，Chart 版本与 Argo CD 版本需分别固定 |

生产环境通常选择 HA 多租户模式，并通过 Kustomize 或 Helm 保存所有定制。官方说明见[安装模式](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/)。

## 4. 快速部署：用于学习或测试

### 4.1 安装 Argo CD

```bash
kubectl create namespace argocd

kubectl apply -n argocd \
  --server-side \
  --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

`--server-side` 用于避免较大的 CRD 超过 client-side apply 注解大小限制。`--force-conflicts` 会让官方清单接管冲突字段；如果现有资源由 Helm 或其他工具管理，不要直接混用该命令，应沿用原安装方式。

等待组件就绪：

```bash
kubectl -n argocd get pods
kubectl -n argocd wait \
  --for=condition=Available \
  deployment/argocd-server \
  --timeout=300s
```

### 4.2 安装 CLI

macOS：

```bash
brew install argocd
argocd version --client
```

Linux amd64：

```bash
curl -sSL -o argocd-linux-amd64 \
  https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 0555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64
argocd version --client
```

生产环境应安装与服务端相同次版本的 CLI，并校验官方发布页提供的 checksum 或签名。

### 4.3 临时访问 UI/API

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:443
```

访问 `https://localhost:8080`。默认使用自签名证书，浏览器会提示证书不受信任。

在另一个终端获取初始密码并登录：

```bash
argocd admin initial-password -n argocd

argocd login localhost:8080 \
  --username admin \
  --insecure

argocd account update-password
```

修改密码后删除只用于保存初始明文密码的 Secret：

```bash
kubectl -n argocd delete secret argocd-initial-admin-secret
```

不要把初始密码写入脚本、Git、工单或命令历史。

### 4.4 创建第一个应用

```bash
argocd app create guestbook \
  --repo https://github.com/argoproj/argocd-example-apps.git \
  --path guestbook \
  --revision HEAD \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace default

argocd app get guestbook
argocd app diff guestbook
argocd app sync guestbook
argocd app wait guestbook --sync --health --timeout 300
```

检查实际资源：

```bash
kubectl -n default get deployment,service -l app.kubernetes.io/instance=guestbook
```

完成测试后，如需连同业务资源一起删除：

```bash
argocd app delete guestbook --cascade
```

## 5. 生产部署

### 5.1 固定版本安装 HA 清单

不要在生产环境长期使用会变化的 `stable` 分支。先从[官方 Releases](https://github.com/argoproj/argo-cd/releases)选择受支持的稳定补丁版本，再固定标签。以下版本只是本文核对时的示例：

```bash
export ARGOCD_VERSION=v3.4.6

kubectl create namespace argocd
kubectl apply -n argocd \
  --server-side \
  --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/ha/install.yaml"
```

生产定制建议存入 Git，而不是直接 `kubectl edit`。一个最小 Kustomize 目录可以是：

```text
platform/argocd/
├── kustomization.yaml
├── argocd-cm.yaml
├── argocd-rbac-cm.yaml
├── argocd-cmd-params-cm.yaml
├── ingress.yaml
└── patches/
    ├── resources.yaml
    └── scheduling.yaml
```

`kustomization.yaml` 示例：

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: argocd

resources:
  - https://raw.githubusercontent.com/argoproj/argo-cd/v3.4.6/manifests/ha/install.yaml
  - argocd-cm.yaml
  - argocd-rbac-cm.yaml
  - argocd-cmd-params-cm.yaml
  - ingress.yaml

patches:
  - path: patches/resources.yaml
  - path: patches/scheduling.yaml
```

应用前查看渲染结果和变更：

```bash
kubectl kustomize platform/argocd >/tmp/argocd-rendered.yaml
kubectl diff --server-side -f /tmp/argocd-rendered.yaml
kubectl apply --server-side --force-conflicts -f /tmp/argocd-rendered.yaml
```

### 5.2 使用 Helm 安装

```bash
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update
helm search repo argo/argo-cd --versions | head

helm upgrade --install argocd argo/argo-cd \
  --namespace argocd \
  --create-namespace \
  --version <CHART_VERSION> \
  -f values-production.yaml \
  --wait \
  --timeout 10m
```

必须同时固定 `<CHART_VERSION>` 和 `values-production.yaml` 中所用镜像版本。升级时应使用 Helm，不要再对同一套资源应用官方原始安装清单。

生产 `values-production.yaml` 至少应审查：

- controller、server、repo-server、ApplicationSet controller 的副本、资源请求与限制。
- Pod 反亲和、拓扑分散、PodDisruptionBudget 和优先级。
- Redis HA、安全上下文、NetworkPolicy。
- Ingress、TLS、SSO、RBAC 和监控 ServiceMonitor。
- repo-server 中自定义 Helm 插件或 Config Management Plugin 的供应链安全。

### 5.3 生产验收

```bash
kubectl -n argocd get pods -o wide
kubectl -n argocd get deployment,statefulset,service
kubectl -n argocd get events --sort-by=.lastTimestamp
kubectl -n argocd top pods

argocd version
argocd cluster list
argocd repo list
argocd app list
```

验收标准至少包括：

- 所有必要 Pod 为 `Running` 且 Ready，无频繁重启。
- API/UI 能通过正式域名访问，证书链有效。
- SSO、RBAC、审计和管理员应急账号符合预期。
- 能从私有仓库渲染清单并同步到测试目标命名空间。
- Prometheus 能抓取指标，关键告警和通知能送达。
- 备份导出和恢复流程经过演练。

## 6. 暴露 UI/API 与 TLS

`argocd-server` 同时提供浏览器使用的 HTTP/HTTPS 和 CLI 使用的 gRPC。Ingress 设计需要同时考虑这两类流量。

### 6.1 方案一：TLS Passthrough

由 Argo CD 终止 TLS，单域名同时处理 UI 和 gRPC。ingress-nginx 必须启用 `--enable-ssl-passthrough`。

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server
  namespace: argocd
  annotations:
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/ssl-passthrough: "true"
spec:
  ingressClassName: nginx
  rules:
    - host: argocd.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: argocd-server
                port:
                  name: https
```

此时证书应配置到 `argocd-server-tls` Secret。完整行为以[官方 Ingress 文档](https://argo-cd.readthedocs.io/en/stable/operator-manual/ingress/)为准。

### 6.2 方案二：Ingress 终止 TLS

由 Ingress 终止 TLS，Argo CD 后端运行 HTTP：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
data:
  server.insecure: "true"
```

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: argocd-server
  namespace: argocd
  annotations:
    nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - argocd.example.com
      secretName: argocd-example-com-tls
  rules:
    - host: argocd.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: argocd-server
                port:
                  name: http
```

如果控制器不能在同一域名下正确代理 gRPC，可为 CLI 使用单独的 gRPC Ingress/域名，或登录时尝试：

```bash
argocd login argocd.example.com --grpc-web
```

不要在公网环境使用 `--insecure` 跳过客户端证书校验。`server.insecure: "true"` 只表示集群内 Ingress 到 Argo CD 的后端使用明文 HTTP，两者含义不同。

## 7. 仓库接入

### 7.1 HTTPS 私有 Git 仓库

交互式添加：

```bash
argocd repo add https://git.example.com/platform/gitops.git \
  --username gitops-reader \
  --password '<ACCESS_TOKEN>'
```

GitLab 等服务可能要求仓库 URL 带 `.git`；Argo CD 不会自动跟随所有 `301` 重定向。

声明式 Secret：

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: repo-gitops
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: repository
stringData:
  type: git
  url: https://git.example.com/platform/gitops.git
  username: gitops-reader
  password: <ACCESS_TOKEN>
```

这个示例展示字段格式，不应把真实 Token 明文提交到 Git。生产环境应使用 External Secrets、Sealed Secrets、Vault 插件或其他受控的密钥注入方案。

### 7.2 SSH 私有仓库

```bash
argocd repo add git@git.example.com:platform/gitops.git \
  --ssh-private-key-path ~/.ssh/argocd_gitops
```

不要通过 `--insecure-skip-server-verification` 绕过主机校验。应把 Git 主机公钥加入 `argocd-ssh-known-hosts-cm`，并在变更前核对公钥指纹。

### 7.3 Helm 仓库

```bash
argocd repo add https://charts.example.com \
  --type helm \
  --name internal-charts \
  --username helm-reader \
  --password '<ACCESS_TOKEN>'
```

验证连接：

```bash
argocd repo list
argocd repo get https://git.example.com/platform/gitops.git
```

## 8. 注册目标集群

Argo CD 默认能管理自身所在集群，目标地址使用：

```text
https://kubernetes.default.svc
```

注册外部集群：

```bash
kubectl config get-contexts -o name
argocd cluster add <KUBECONFIG_CONTEXT>
argocd cluster list
```

`argocd cluster add` 默认会在目标集群创建 `argocd-manager` ServiceAccount，并赋予较高权限。生产环境应按实际应用缩小权限范围：写权限只授予允许管理的命名空间和资源；为保持资源发现能力，controller 通常仍需要集群范围的 `get`、`list`、`watch`。

删除注册关系前应确认没有 Application 仍指向该集群：

```bash
argocd app list --output wide
argocd cluster rm <SERVER_OR_NAME>
```

## 9. 用 AppProject 建立边界

不要让所有应用长期使用权限宽泛的 `default` 项目。下面示例只允许团队从指定仓库部署到 `prod` 集群的 `team-a-*` 命名空间，并禁止创建集群级 RBAC：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: team-a
  namespace: argocd
spec:
  description: Team A applications
  sourceRepos:
    - https://git.example.com/team-a/*.git
  destinations:
    - name: prod
      namespace: team-a-*
  clusterResourceBlacklist:
    - group: rbac.authorization.k8s.io
      kind: ClusterRole
    - group: rbac.authorization.k8s.io
      kind: ClusterRoleBinding
  namespaceResourceWhitelist:
    - group: "*"
      kind: "*"
  orphanedResources:
    warn: true
```

再在 Application 中指定：

```yaml
spec:
  project: team-a
```

Project 控制的是 Application 能部署什么；Argo CD RBAC 控制的是用户能对 Application 做什么，两者要同时配置。

## 10. Application 详解

### 10.1 推荐的 Git 目录结构

应用代码仓库与环境配置仓库分离时，可以使用：

```text
gitops-config/
├── apps/
│   └── demo-api/
│       ├── base/
│       │   ├── deployment.yaml
│       │   ├── service.yaml
│       │   └── kustomization.yaml
│       └── overlays/
│           ├── dev/
│           │   └── kustomization.yaml
│           └── prod/
│               └── kustomization.yaml
└── argocd/
    ├── projects/
    ├── applications/
    └── applicationsets/
```

推荐让 CI 更新 `overlays/<env>` 中的镜像 digest 或不可变标签，经 Pull Request 审核后由 Argo CD 发布。

### 10.2 普通 YAML 目录

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo-api-prod
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: team-a
  source:
    repoURL: https://git.example.com/team-a/gitops-config.git
    targetRevision: main
    path: apps/demo-api/manifests/prod
    directory:
      recurse: true
  destination:
    name: prod
    namespace: team-a-prod
  syncPolicy:
    syncOptions:
      - CreateNamespace=true
```

`resources-finalizer.argocd.argoproj.io` 表示删除 Application 时级联删除其管理的资源。是否使用它必须根据应用下线策略决定，尤其要谨慎处理 Namespace、PVC、数据库等有状态资源。

### 10.3 Kustomize 应用

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo-api-prod
  namespace: argocd
spec:
  project: team-a
  source:
    repoURL: https://git.example.com/team-a/gitops-config.git
    targetRevision: main
    path: apps/demo-api/overlays/prod
    kustomize:
      commonLabels:
        environment: prod
      images:
        - registry.example.com/team-a/demo-api@sha256:<IMAGE_DIGEST>
  destination:
    name: prod
    namespace: team-a-prod
```

尽量在仓库中的 `kustomization.yaml` 保存镜像和补丁，让 Git 本身完整表达期望状态；Application 参数覆盖适合临时或平台统一注入，不宜成为不可追踪的长期配置。

### 10.4 Helm 应用

使用 Git 仓库内的 Chart：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: demo-api-prod
  namespace: argocd
spec:
  project: team-a
  source:
    repoURL: https://git.example.com/team-a/gitops-config.git
    targetRevision: main
    path: charts/demo-api
    helm:
      releaseName: demo-api
      valueFiles:
        - values.yaml
        - values-prod.yaml
      parameters:
        - name: replicaCount
          value: "3"
  destination:
    name: prod
    namespace: team-a-prod
```

使用 Helm 仓库：

```yaml
spec:
  source:
    repoURL: https://charts.example.com
    chart: demo-api
    targetRevision: 1.8.3
    helm:
      valueFiles:
        - values-prod.yaml
```

Argo CD 使用 Helm 生成清单，但资源生命周期由 Argo CD 管理，不等价于执行 `helm install` 后维护一个 Helm release。

### 10.5 外部 Chart 配合独立 values 仓库

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus
  namespace: argocd
spec:
  project: platform
  sources:
    - repoURL: https://prometheus-community.github.io/helm-charts
      chart: prometheus
      targetRevision: 27.20.0
      helm:
        valueFiles:
          - $values/monitoring/prometheus/values-prod.yaml
    - repoURL: https://git.example.com/platform/gitops-config.git
      targetRevision: main
      ref: values
  destination:
    name: prod
    namespace: monitoring
```

使用 `sources` 时，`source` 字段会被忽略。多个来源适合“第三方 Chart + 自有 values”；如果组合过多，应用责任边界会变得不清晰，应考虑拆成多个 Application 或使用 ApplicationSet。

## 11. 同步策略

### 11.1 手动同步

适合刚接入、生产审批严格或需要人工确认变更的应用：

```bash
argocd app diff demo-api-prod
argocd app sync demo-api-prod --prune
argocd app wait demo-api-prod --sync --health --timeout 600
```

只同步指定资源：

```bash
argocd app sync demo-api-prod \
  --resource apps:Deployment:demo-api
```

选择性同步可能跳过 hook 或依赖项，故障处置之外不要把它当常规发布方法。

### 11.2 自动同步

```yaml
spec:
  syncPolicy:
    automated:
      enabled: true
      prune: true
      selfHeal: true
      allowEmpty: false
    retry:
      limit: 5
      backoff:
        duration: 5s
        factor: 2
        maxDuration: 3m
    syncOptions:
      - CreateNamespace=true
      - PruneLast=true
      - ApplyOutOfSyncOnly=true
```

字段含义：

| 字段 | 含义 | 风险 |
|---|---|---|
| `enabled` | 开启自动同步 | Git 变更会自动进入集群 |
| `prune` | 删除 Git 中已不存在的资源 | 错误删除清单可能导致线上资源被删 |
| `selfHeal` | 自动修复集群内的手工漂移 | 紧急手改会被恢复，修复也必须回到 Git |
| `allowEmpty` | 允许应用目标资源为空 | 通常保持 `false`，防止路径或渲染错误清空应用 |
| `CreateNamespace=true` | 自动创建目标命名空间 | Namespace 元数据和生命周期仍要规划 |
| `PruneLast=true` | 最后一个同步 wave 再删除资源 | 降低新旧资源切换时的中断风险 |
| `ApplyOutOfSyncOnly=true` | 只 apply 不一致资源 | 大应用可减少 API 压力 |

自动同步默认不会自动 prune，也不会因为集群内漂移而自愈；必须显式开启。详见[自动同步策略](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)和[同步选项](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)。

关键资源可以要求 prune 人工确认：

```yaml
metadata:
  annotations:
    argocd.argoproj.io/sync-options: Prune=confirm
```

### 11.3 同步阶段、Wave 与 Hook

Argo CD 的同步顺序可用阶段和 wave 控制：

- 阶段：`PreSync` → `Sync` → `PostSync`；失败时可运行 `SyncFail`。
- 同阶段内，`argocd.argoproj.io/sync-wave` 数值较小的资源先执行。
- 常见做法：CRD 为 `-2`，基础配置为 `-1`，业务资源为 `0`，验证 Job 为 `1`。

数据库迁移 Job 示例：

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  generateName: demo-api-migrate-
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation,HookSucceeded
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.example.com/team-a/demo-api@sha256:<IMAGE_DIGEST>
          args: ["migrate"]
```

迁移必须向后兼容，并明确失败和重复执行行为。不可逆数据库变更不能只依靠 Kubernetes 应用回滚。

### 11.4 忽略预期差异

HPA、Webhook 或 Operator 可能合法地改写字段。只忽略确定由其他控制器管理的路径：

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
  syncPolicy:
    syncOptions:
      - RespectIgnoreDifferences=true
```

不要粗放忽略整个 `spec`，否则真实配置漂移也会被隐藏。

## 12. ApplicationSet：批量管理环境或集群

下面根据列表生成 dev 和 prod 两个 Application：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: demo-api
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions:
    - missingkey=error
  generators:
    - list:
        elements:
          - env: dev
            cluster: dev
            namespace: team-a-dev
          - env: prod
            cluster: prod
            namespace: team-a-prod
  template:
    metadata:
      name: 'demo-api-{{.env}}'
      labels:
        app.kubernetes.io/name: demo-api
        environment: '{{.env}}'
    spec:
      project: team-a
      source:
        repoURL: https://git.example.com/team-a/gitops-config.git
        targetRevision: main
        path: 'apps/demo-api/overlays/{{.env}}'
      destination:
        name: '{{.cluster}}'
        namespace: '{{.namespace}}'
      syncPolicy:
        automated:
          enabled: true
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

常用生成器：

- `list`：明确列出环境，简单可控。
- `clusters`：为匹配标签的注册集群生成应用。
- `git.directories`：扫描 Git 目录，一目录一应用。
- `git.files`：从 Git 中的 JSON/YAML 配置生成应用。
- `matrix`：组合两个生成器，如“集群 × 应用”。
- `merge`：按 key 合并多个生成器结果。
- `pullRequest`：为 PR 创建临时环境，必须严格限制模板可部署范围。

ApplicationSet 生成的 Application 应由 ApplicationSet 模板管理。直接修改生成结果通常会被控制器覆盖。

## 13. 日常操作

### 13.1 查看状态与差异

```bash
argocd app list
argocd app get demo-api-prod
argocd app get demo-api-prod --show-operation
argocd app diff demo-api-prod
argocd app history demo-api-prod
argocd app resources demo-api-prod
argocd app manifests demo-api-prod
```

刷新仓库和集群状态：

```bash
argocd app get demo-api-prod --refresh
argocd app get demo-api-prod --hard-refresh
```

`--hard-refresh` 会同时清理清单缓存，开销更高，只在普通刷新无法解决缓存问题时使用。

### 13.2 查看日志和事件

```bash
argocd app logs demo-api-prod --follow
kubectl -n team-a-prod get events --sort-by=.lastTimestamp

kubectl -n argocd logs deployment/argocd-server --since=30m
kubectl -n argocd logs statefulset/argocd-application-controller --since=30m
kubectl -n argocd logs deployment/argocd-repo-server --since=30m
kubectl -n argocd logs deployment/argocd-applicationset-controller --since=30m
```

HA 安装的组件类型和名称可能不同，先用 `kubectl -n argocd get deploy,sts` 确认。

### 13.3 暂停自动同步

普通 Application：

```bash
argocd app set demo-api-prod --sync-policy none
```

恢复：

```bash
argocd app set demo-api-prod --sync-policy automated
argocd app set demo-api-prod --auto-prune --self-heal
```

若 Application 由 ApplicationSet 管理，应修改 ApplicationSet 模板或其控制策略；直接修改生成的 Application 可能无效或被覆盖。

### 13.4 回滚

推荐的 GitOps 回滚是撤销 Git 提交：

```bash
git revert <BAD_COMMIT>
git push origin main
argocd app wait demo-api-prod --sync --health --timeout 600
```

Argo CD 也能按历史 ID 回滚：

```bash
argocd app history demo-api-prod
argocd app rollback demo-api-prod <HISTORY_ID>
```

启用自动同步的 Application 不能直接依赖 Argo CD 历史回滚，因为 Git 中仍是新版本，控制器会再次同步。生产回滚应确保 Git 期望状态也回到正确版本。

### 13.5 删除应用

保留业务资源，只删除 Application：

```bash
argocd app delete demo-api-prod --cascade=false
```

级联删除 Application 管理的业务资源：

```bash
argocd app delete demo-api-prod --cascade
```

删除前检查 PVC、Namespace、数据库、CRD 和共享资源。由 ApplicationSet 生成的 Application 应从生成器来源移除，否则可能被重新创建。

## 14. 用户、SSO 与 RBAC

Argo CD 只有一个内置超级用户 `admin`，没有完整的本地用户目录。生产环境推荐接入企业 OIDC/SSO，完成验证后禁用内置 admin。

最小权限 RBAC 示例：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
data:
  policy.default: role:authenticated
  policy.matchMode: glob
  policy.csv: |
    p, role:authenticated, applications, get, */*, allow
    p, role:team-a-deployer, applications, get, team-a/*, allow
    p, role:team-a-deployer, applications, sync, team-a/*, allow
    p, role:team-a-deployer, logs, get, team-a/*, allow
    g, team-a-platform, role:team-a-deployer
```

验证策略：

```bash
argocd admin settings rbac can \
  team-a-platform \
  sync \
  applications \
  'team-a/demo-api-prod'
```

安全要点：

- `policy.default` 只授予所有已认证用户都应该拥有的最低权限。
- `role:admin` 权限不受限，只给少数平台管理员。
- RBAC 的 Application 对象通常按 `<project>/<application>` 匹配。
- 同时用 AppProject 限制仓库和目标位置，避免只依赖用户 RBAC。
- SSO 稳定后禁用 admin，并保留经过审计的紧急恢复流程。

官方完整语法见[RBAC 配置](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)。

## 15. 安全配置

生产环境至少落实以下事项：

1. 固定 Argo CD、Helm Chart 和容器镜像版本，升级前阅读逐版本 breaking changes。
2. UI/API 使用受信任证书，不公开不必要的 Service，不在公网跳过 TLS 校验。
3. 使用 SSO、短会话、MFA 和最小权限 RBAC；限制或禁用内置 admin。
4. Repo 凭据只读、按项目隔离，并定期轮换；不要在 Application 中放密钥。
5. 使用 External Secrets、Sealed Secrets 或 Vault 等管理应用密钥，Git 中只保存加密数据或引用。
6. 外部集群凭据按命名空间和资源类型收敛，限制 Argo CD 的网络访问范围。
7. repo-server 会处理不可信仓库内容，应限制插件、资源、文件系统权限和出网能力。
8. 对 CRD、Namespace、PVC、ClusterRole 等资源设置人工审查或 `Prune=confirm`。
9. 为配置变更、登录、同步、删除和权限变更保留日志并接入告警。
10. 对 Git webhook 使用 Secret，并在 Git 服务端限制目标 URL 和来源。

## 16. Webhook、监控与通知

### 16.1 Git Webhook

Argo CD 会周期性检查仓库。配置 Git webhook 可以更快触发刷新：

```text
https://argocd.example.com/api/webhook
```

在 `argocd-secret` 中配置对应 Git 服务的 webhook Secret，并在 Git 平台使用同一值。不要在文档或 Git 中记录真实 Secret。

### 16.2 Prometheus 指标

Argo CD 的不同组件暴露不同指标端点。Application Controller 指标通常由 `argocd-metrics:8082/metrics` 提供。常用指标包括：

| 指标 | 用途 |
|---|---|
| `argocd_app_info` | 按 `sync_status`、`health_status` 观察应用状态 |
| `argocd_app_condition` | 观察 Application Condition |
| `argocd_app_reconcile` | 观察调谐耗时 |
| `argocd_app_sync_total` | 统计同步次数 |
| `argocd_cluster_connection_status` | 观察目标集群连接状态 |
| `argocd_cluster_cache_age_seconds` | 观察集群缓存新鲜度 |

建议告警：

- Application 长时间 `OutOfSync`、`Degraded`、`Unknown`。
- 同步失败或同步耗时异常。
- 仓库、目标集群连接失败。
- controller 队列或调谐耗时持续增加。
- repo-server、controller、server、Redis 不可用或频繁重启。
- TLS 证书、仓库凭据临近过期。

指标名称和端点可能随版本演进，配置前核对[官方指标文档](https://argo-cd.readthedocs.io/en/stable/operator-manual/metrics/)。

### 16.3 通知

Notifications Controller 可以在同步成功、失败、健康状态变化等事件发生时向 Slack、Teams、邮件、Webhook 等发送通知。推荐：

- 通知服务密钥放 Secret。
- 通知模板和触发器放 Git 管理的 `argocd-notifications-cm`。
- 通过 Application annotation、AppProject 或全局配置订阅。
- 至少验证一次成功通知和一次失败通知。

## 17. 备份、恢复与升级

### 17.1 备份

Argo CD 的业务 Kubernetes 清单本应在 Git 中，但仓库凭据、集群凭据、RBAC、项目和 Application 等 Argo CD 状态仍需备份。

先确认服务端版本，再用相同版本的 CLI 镜像导出：

```bash
argocd version | grep server

export ARGOCD_VERSION=<CURRENT_SERVER_VERSION>

docker run --rm \
  -v ~/.kube:/home/argocd/.kube \
  "quay.io/argoproj/argocd:${ARGOCD_VERSION}" \
  argocd admin export -n argocd >argocd-backup.yaml
```

备份包含敏感信息，应加密存储、限制访问并设置保留周期。恢复前先在隔离环境验证备份：

```bash
docker run --rm -i \
  -v ~/.kube:/home/argocd/.kube \
  "quay.io/argoproj/argocd:${ARGOCD_VERSION}" \
  argocd admin import -n argocd - <argocd-backup.yaml
```

官方恢复说明见[Disaster Recovery](https://argo-cd.readthedocs.io/en/stable/operator-manual/disaster_recovery/)。

### 17.2 升级

升级步骤：

1. 确认当前版本、安装方式和所有本地定制。
2. 阅读每一个跨越版本的升级说明；不要跳过中间次版本说明。
3. 导出 Argo CD 备份并验证可读性。
4. 在测试环境用相同配置演练。
5. 使用原安装方式升级，观察 CRD、controller、repo-server、server 和 Redis。
6. 验证登录、仓库、集群、渲染、同步、通知和监控。

官方清单升级示例：

```bash
export TARGET_VERSION=<TARGET_VERSION>

kubectl diff -n argocd --server-side \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${TARGET_VERSION}/manifests/ha/install.yaml"

kubectl apply -n argocd \
  --server-side \
  --force-conflicts \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${TARGET_VERSION}/manifests/ha/install.yaml"
```

补丁版本原则上不引入 breaking change；次版本和主版本可能有迁移事项。以[官方升级说明](https://argo-cd.readthedocs.io/en/stable/operator-manual/upgrading/overview/)为准。

## 18. 常见故障排查

### 18.1 Application 一直是 `OutOfSync`

检查：

```bash
argocd app get <APP> --refresh
argocd app diff <APP>
argocd app manifests <APP>
kubectl -n <NAMESPACE> get <RESOURCE> <NAME> -o yaml
```

常见原因：

- HPA、Webhook、Operator 或 Kubernetes 默认值持续改写字段。
- Helm 模板包含随机值或时间值，每次渲染结果不同。
- list 顺序、默认字段、聚合 ClusterRole 等导致比较差异。
- 资源同时被 Argo CD 和其他工具管理。

处理方式是找到实际写入者，只对确定的路径配置 `ignoreDifferences`，不要为了变绿而忽略大段资源。

### 18.2 `ComparisonError` 或清单生成失败

```bash
kubectl -n argocd logs deployment/argocd-repo-server --since=30m
argocd app get <APP> --hard-refresh
```

检查仓库认证、Git revision、路径大小写、Chart 版本、values 文件、Kustomize 版本、CRD、插件和 repo-server 的网络/DNS。

本地复现渲染：

```bash
helm template <RELEASE> <CHART_PATH> -f <VALUES_FILE>
kubectl kustomize <OVERLAY_PATH>
```

本地工具版本应与 repo-server 实际使用版本一致，否则结果可能不同。

### 18.3 仓库连接失败

```bash
argocd repo list
argocd repo get <REPO_URL>
kubectl -n argocd logs deployment/argocd-repo-server --since=30m
```

检查：

- GitLab URL 是否缺少 `.git`。
- Token 是否过期、权限是否为只读且覆盖目标仓库。
- SSH known_hosts 和私钥格式是否正确。
- 自签名 CA 是否已加入 `argocd-tls-certs-cm`。
- 集群 DNS、代理、NetworkPolicy 和防火墙是否允许连接。

### 18.4 目标集群不可达或 `Unknown`

```bash
argocd cluster list
argocd cluster get <CLUSTER>
kubectl -n argocd logs statefulset/argocd-application-controller --since=30m
```

检查目标 API 地址、证书链、ServiceAccount Token、RBAC、网络和 API Server 限流。托管集群的短期凭据或认证插件还要检查轮换机制。

### 18.5 同步失败

```bash
argocd app get <APP> --show-operation
kubectl -n <NAMESPACE> get events --sort-by=.lastTimestamp
kubectl auth can-i create <RESOURCE> \
  --as=system:serviceaccount:argocd:argocd-application-controller \
  -n <NAMESPACE>
```

常见原因：

- AppProject 拒绝仓库、目标命名空间或资源类型。
- Argo CD controller 在目标集群中权限不足。
- Admission Webhook、ResourceQuota、LimitRange 或 Pod Security 拒绝资源。
- CRD 尚未建立，导致自定义资源 dry-run 失败。
- hook Job 失败或 wave 依赖不健康。
- 不可变字段变化需要重建资源。

### 18.6 CLI 登录失败或 Ingress 返回 307/502

检查 UI 是否正常、证书 SAN、Ingress 后端协议、TLS 终止位置和 gRPC 支持。必要时测试：

```bash
argocd login argocd.example.com --grpc-web
kubectl -n argocd port-forward svc/argocd-server 8080:443
argocd login localhost:8080 --insecure
```

端口转发可用而 Ingress 不可用，通常说明问题位于 Ingress、负载均衡、DNS 或 TLS 配置，而非 Argo CD 核心组件。

### 18.7 Application 删除卡在 `Terminating`

```bash
kubectl -n argocd get application <APP> -o yaml
kubectl -n argocd describe application <APP>
```

重点检查 finalizer、目标集群连接、待删除资源和 controller 日志。不要直接移除 finalizer，除非已经确认哪些业务资源会被遗留，并接受后续人工清理。

## 19. 推荐落地顺序

1. 在非生产集群安装固定版本，接入测试仓库和命名空间。
2. 先用手动同步，确认 diff、健康检查和删除行为。
3. 建立 AppProject，收紧仓库、集群、命名空间和资源类型。
4. 接入 SSO、最小权限 RBAC、受信任 TLS 和密钥管理。
5. 建立监控、通知、审计、备份和恢复演练。
6. 为低风险环境开启 `selfHeal`，验证漂移修复。
7. 再按应用评估 `prune`，关键资源使用确认或保护策略。
8. 生产环境使用 HA、资源配额、反亲和和固定版本。
9. 将 Argo CD 自身配置也纳入 Git 管理，并保留引导恢复方案。

## 20. 生产检查清单

- [ ] Argo CD 和 Chart 使用固定、受支持的版本。
- [ ] 使用 HA 模式，关键组件有合理的 requests/limits、反亲和和 PDB。
- [ ] 域名、TLS、gRPC、SSO 和应急管理员流程验证通过。
- [ ] `policy.default` 为最低权限，团队权限已实际测试。
- [ ] 每个团队使用独立 AppProject，目标和仓库范围明确。
- [ ] Git、Helm、OCI 和集群凭据不以明文进入 Git。
- [ ] 自动同步、prune、self-heal 和 allowEmpty 均经过逐应用评估。
- [ ] Namespace、PVC、CRD、集群级 RBAC 等关键资源有删除保护。
- [ ] Prometheus、告警和发布通知可用。
- [ ] 备份已加密，恢复流程已在隔离环境演练。
- [ ] 升级、回滚、应用下线和集群移除都有操作手册。
- [ ] CI 只更新 Git 中的部署状态，不直接持有生产集群管理员凭据。

## 21. 官方参考

- [Getting Started](https://argo-cd.readthedocs.io/en/stable/getting_started/)
- [Installation](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/)
- [Declarative Setup](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/)
- [Application Specification](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/)
- [Automated Sync Policy](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [ApplicationSet](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/)
- [Ingress](https://argo-cd.readthedocs.io/en/stable/operator-manual/ingress/)
- [TLS](https://argo-cd.readthedocs.io/en/stable/operator-manual/tls/)
- [RBAC](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
- [Metrics](https://argo-cd.readthedocs.io/en/stable/operator-manual/metrics/)
- [Disaster Recovery](https://argo-cd.readthedocs.io/en/stable/operator-manual/disaster_recovery/)
- [Upgrading](https://argo-cd.readthedocs.io/en/stable/operator-manual/upgrading/overview/)
- [Argo CD Releases](https://github.com/argoproj/argo-cd/releases)
