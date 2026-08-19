# Argo CD 部署与使用详解

> 适用范围：在 Kubernetes 中安装、配置并使用 Argo CD 管理应用持续交付。
>
> 文档核对日期：2026-08-19。示例以 Argo CD 3.x 为基线；执行生产变更前，应再核对目标版本的升级说明。
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

如果控制器不能在同一域名下正确代理原生 gRPC，可为 CLI 使用单独的 gRPC Ingress/域名，或让 CLI 改用 gRPC-Web：

```bash
argocd login argocd.example.com --grpc-web
```

不要在公网环境使用 `--insecure` 跳过客户端证书校验。`server.insecure: "true"` 只表示集群内 Ingress 到 Argo CD 的后端使用明文 HTTP，两者含义不同。

### 6.3 `--grpc-web` 参数用法

Argo CD CLI 默认使用基于 HTTP/2 的原生 gRPC 与 `argocd-server` 通信。某些 Ingress、七层负载均衡器、WAF 或企业代理不能完整转发原生 gRPC，此时可能出现 `404`、`502`、连接被关闭、HTTP/2 协商失败或 `rpc error: code = Unavailable`。`--grpc-web` 会让 CLI 改用对 HTTP/1.1 代理更友好的 gRPC-Web 协议。

它只改变 CLI 到 Argo CD API Server 的通信协议，不会改变 Application 的同步方式，也不等于禁用 TLS。

登录时使用：

```bash
argocd login argocd.example.com --grpc-web
```

使用用户名登录：

```bash
argocd login argocd.example.com \
  --username admin \
  --grpc-web
```

使用 SSO 登录：

```bash
argocd login argocd.example.com \
  --sso \
  --grpc-web
```

`--grpc-web` 是全局参数，可以附加到其他 CLI 命令：

```bash
argocd app list --grpc-web
argocd app get demo-api-prod --grpc-web
argocd app sync demo-api-prod --grpc-web
argocd repo list --grpc-web
argocd cluster list --grpc-web
```

如果当前访问入口始终需要 gRPC-Web，可以通过 `ARGOCD_OPTS` 避免每条命令重复填写：

```bash
export ARGOCD_SERVER=argocd.example.com
export ARGOCD_OPTS='--grpc-web'

argocd login "$ARGOCD_SERVER"
argocd app list
argocd app sync demo-api-prod
```

在 CI 中通常配合环境变量使用：

```bash
export ARGOCD_SERVER=argocd.example.com
export ARGOCD_AUTH_TOKEN='<ARGOCD_TOKEN>'
export ARGOCD_OPTS='--grpc-web'

argocd app get demo-api-prod
argocd app sync demo-api-prod
argocd app wait demo-api-prod --sync --health --timeout 600
```

真实 Token 应由 CI 密钥变量注入，不得明文写进流水线仓库或日志。

如果 Argo CD 通过子路径发布，例如 `https://example.com/argo-cd`，服务端和 CLI 必须使用一致的根路径。服务端示例：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
data:
  server.basehref: "/argo-cd"
  server.rootpath: "/argo-cd"
```

CLI 使用 `--grpc-web-root-path`：

```bash
argocd login example.com \
  --grpc-web \
  --grpc-web-root-path /argo-cd
```

也可以全局配置：

```bash
export ARGOCD_SERVER=example.com
export ARGOCD_OPTS='--grpc-web --grpc-web-root-path /argo-cd'
```

相关参数不要混淆：

| 参数 | 作用 | 常见场景 |
|---|---|---|
| `--grpc-web` | 使用 gRPC-Web 代替原生 gRPC | 中间代理不支持端到端 HTTP/2 gRPC |
| `--grpc-web-root-path /argo-cd` | 指定 gRPC-Web 的非根 URL 路径 | Argo CD 发布在域名子路径下 |
| `--insecure` | 跳过服务端证书和域名校验 | 仅限临时测试自签名证书，不建议用于生产 |
| `--plaintext` | CLI 到入口不使用 TLS | 仅用于明确为 HTTP 的受控入口 |
| `--port-forward` | 通过 Kubernetes API 临时转发到 `argocd-server` | API 入口未暴露或排除 Ingress 故障 |

判断是否需要该参数：

1. UI 能正常打开，但 CLI 使用默认方式连接失败。
2. 加上 `--grpc-web` 后 CLI 登录和 `argocd app list` 正常。
3. 通过端口转发使用原生 gRPC 正常，只有经过 Ingress/负载均衡器时失败。

满足这些现象时，问题通常是代理协议转发，而不是 Application 或目标集群。仍应检查 Ingress 的 TLS 终止、后端协议、路径重写和超时设置。官方说明见[Ingress 配置](https://argo-cd.readthedocs.io/en/stable/operator-manual/ingress/)和[CLI 环境变量](https://argo-cd.readthedocs.io/en/stable/user-guide/environment-variables/)。

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

### 14.1 `--sso` 的工作方式

`argocd login --sso` 只是让 CLI 发起浏览器登录流程，前提是 Argo CD 服务端已经接入身份提供商。典型过程如下：

```text
argocd CLI 启动本地回调端口 8085
           │
           ▼
浏览器打开 Argo CD 登录地址
           │
           ▼
Argo CD / 身份提供商完成 OIDC 登录
           │
           ▼
浏览器回调 http://localhost:8085/auth/callback
           │
           ▼
CLI 获得登录会话并保存 Argo CD context
```

Argo CD 支持两类 SSO 接入方式：

| 方式 | Argo CD 配置 | 身份提供商回调 | 适用场景 |
|---|---|---|---|
| 直接连接现有 OIDC | `oidc.config` | `/auth/callback` | Keycloak、Okta、Microsoft Entra ID、Auth0 等已经支持 OIDC |
| 通过内置 Dex | `dex.config` | `/api/dex/callback` | LDAP、SAML、GitHub connector 或需要 Dex 转换 claims |

不要把两种回调地址混用。下面以“Keycloak + OIDC + PKCE”为完整示例，因为它同时支持 Web UI 和 `argocd login --sso`。

### 14.2 部署 Keycloak

Keycloak 的部署方式应按用途选择：

| 场景 | 推荐方式 | 数据库 | 说明 |
|---|---|---|---|
| 本机学习、临时联调 | 官方容器 `start-dev` | 内置开发数据库 | 启动快，不能用于生产 |
| Kubernetes 生产环境 | 官方 Keycloak Operator | 外部 PostgreSQL | 推荐，便于升级、滚动发布和声明式管理 |
| 虚拟机或容器平台生产环境 | 自建优化镜像并执行 `start --optimized` | 外部 PostgreSQL | 需要自行负责高可用、TLS、监控和升级 |

本文核对时公开的稳定补丁版本为 `26.7.1`。部署前应从 [Keycloak Releases](https://github.com/keycloak/keycloak/releases)重新确认受支持版本，并固定镜像和 Operator 版本，不使用 `latest`。

#### 14.2.1 Docker 本地验证

```bash
docker run --name keycloak-dev --rm \
  -p 127.0.0.1:8080:8080 \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin \
  -e KC_BOOTSTRAP_ADMIN_PASSWORD='<TEMP_PASSWORD>' \
  quay.io/keycloak/keycloak:26.7.1 \
  start-dev
```

访问：

```text
http://127.0.0.1:8080
http://127.0.0.1:8080/admin/
```

`start-dev` 使用不适合生产的默认配置。它只用于学习 Realm、Client、Group、Role 以及与 Argo CD 的 OIDC 联调。临时密码不要使用真实生产密码，也不要把密码写进脚本或 Git。

停止容器：

```bash
docker stop keycloak-dev
```

由于示例使用 `--rm`，容器停止后开发数据会丢失。

#### 14.2.2 Kubernetes 生产部署架构

推荐结构：

```text
用户
 │ HTTPS
 ▼
LoadBalancer / Ingress
 │ TLS 终止并覆盖 X-Forwarded-* 请求头
 ▼
Keycloak Service
 │
 ├── Keycloak Pod 1
 ├── Keycloak Pod 2
 │
 ▼
外部高可用 PostgreSQL
```

准备条件：

- 具有安装 CRD、ClusterRole 和 Operator 的集群管理权限。
- 已有外部 PostgreSQL；Keycloak Operator 不创建和备份数据库。
- 已准备 `sso.example.com` DNS、受信任 TLS 证书和 Ingress Controller。
- Keycloak 命名空间能访问 PostgreSQL，Ingress 能访问 Keycloak Service。
- PostgreSQL 已创建独立数据库和最小权限账号，并具备备份、PITR 和监控。

#### 14.2.3 安装 Keycloak Operator

以下安装为 namespace-scoped，Operator 只监听 `keycloak` 命名空间：

```bash
kubectl create namespace keycloak

kubectl apply -k \
  'github.com/keycloak/keycloak-k8s-resources/kubernetes?ref=26.7.1'

kubectl -n keycloak get deployment,pod
kubectl get crd | grep keycloak
```

生产环境应把远程 Kustomize 引用保存到平台配置仓库，并在升级前检查 diff。使用 OLM 时应设置手动批准升级，避免 Operator 自动升级时连带升级 Keycloak 和数据库结构。

#### 14.2.4 准备数据库和 TLS Secret

数据库凭据示例：

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: keycloak-db-secret
  namespace: keycloak
type: Opaque
stringData:
  username: <KEYCLOAK_DB_USERNAME>
  password: <KEYCLOAK_DB_PASSWORD>
```

这个 Secret 应由 External Secrets、Sealed Secrets 或其他密钥系统生成，不要将真实密码明文提交到 Git。

TLS Secret 必须与 `Keycloak` CR 位于同一命名空间：

```bash
kubectl -n keycloak create secret tls keycloak-tls \
  --cert=sso.example.com.crt \
  --key=sso.example.com.key
```

更推荐使用 cert-manager 或企业证书平台自动创建和轮换 `keycloak-tls`。证书必须包含 `sso.example.com` 的 SAN。

#### 14.2.5 创建 Keycloak 实例

下面示例使用两个 Keycloak 实例、外部 PostgreSQL、ingress-nginx 边缘 TLS 终止和 `X-Forwarded-*` 请求头：

```yaml
apiVersion: k8s.keycloak.org/v2beta1
kind: Keycloak
metadata:
  name: keycloak
  namespace: keycloak
spec:
  instances: 2

  db:
    vendor: postgres
    host: postgresql-rw.database.svc.cluster.local
    port: 5432
    database: keycloak
    schema: public
    usernameSecret:
      name: keycloak-db-secret
      key: username
    passwordSecret:
      name: keycloak-db-secret
      key: password

  http:
    httpEnabled: true

  ingress:
    enabled: true
    className: nginx
    tlsSecret: keycloak-tls

  hostname:
    hostname: sso.example.com

  proxy:
    headers: xforwarded

  networkPolicy:
    enabled: true
    http:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: ingress-nginx

  resources:
    requests:
      cpu: "1"
      memory: 2Gi
    limits:
      cpu: "2"
      memory: 3Gi

  additionalOptions:
    - name: metrics-enabled
      value: "true"
```

需要替换：

- `postgresql-rw.database.svc.cluster.local`：实际 PostgreSQL 地址。
- `ingress-nginx`：Ingress Controller 所在命名空间。
- CPU、内存和副本数：根据并发、Realm、Client 和会话量压测确定。
- 如果 Ingress 使用 RFC 7239 `Forwarded`，把 `proxy.headers` 改为 `forwarded`。

这个例子采用 edge TLS：外部 HTTPS 在 Ingress 终止，Ingress 到 Keycloak 使用 HTTP，因此设置 `httpEnabled: true`。Ingress 必须覆盖而不是追加客户端提交的 `X-Forwarded-*` 请求头，并通过 NetworkPolicy 防止其他 Pod 绕过 Ingress 伪造这些请求头。

如果使用 TLS passthrough，不应配置 `proxy.headers`，而应让 Keycloak 自己提供 TLS；如果要求 Ingress 到 Keycloak 之间也加密，应采用 re-encrypt 并分别配置前端和后端证书。完整差异见 [Keycloak 反向代理文档](https://www.keycloak.org/server/reverseproxy)。

应用并观察状态：

```bash
kubectl apply -f keycloak.yaml

kubectl -n keycloak get keycloak/keycloak
kubectl -n keycloak get pod,service,ingress
kubectl -n keycloak describe keycloak keycloak
kubectl -n keycloak logs deployment/keycloak-operator --since=30m
```

查看 Operator 报告的条件：

```bash
kubectl -n keycloak get keycloak/keycloak \
  -o go-template='{{range .status.conditions}}{{.type}}={{.status}} {{.message}}{{"\n"}}{{end}}'
```

当 `Ready=True` 且 DNS 已指向 Ingress 后，访问：

```text
https://sso.example.com
https://sso.example.com/admin/
```

#### 14.2.6 获取初始管理员

未显式配置 `spec.bootstrapAdmin` 时，Operator 会创建 `<CR名称>-initial-admin` Secret。本例为：

```bash
kubectl -n keycloak get secret keycloak-initial-admin \
  -o jsonpath='{.data.username}' | base64 --decode

kubectl -n keycloak get secret keycloak-initial-admin \
  -o jsonpath='{.data.password}' | base64 --decode
```

初始账号是临时管理入口。首次登录后应：

1. 创建实名管理账号和管理员组。
2. 启用 MFA。
3. 验证至少两个管理员账号可用。
4. 限制管理控制台来源。
5. 按安全流程处理初始凭据，不要记录到工单、Git 或普通日志。

#### 14.2.7 健康检查和监控

Keycloak 的业务端口默认是 `8443`，启用 HTTP 时是 `8080`；管理接口默认使用 `9000`，提供健康检查和指标。管理端口不应暴露给公网。

临时检查健康状态：

```bash
kubectl -n keycloak port-forward service/keycloak-service 9000:9000
curl -fsS http://127.0.0.1:9000/health/ready
curl -fsS http://127.0.0.1:9000/health/live
curl -fsS http://127.0.0.1:9000/metrics | head
```

启用 `metrics-enabled` 后，如果集群已安装 Prometheus Operator 的 `ServiceMonitor` CRD，Keycloak Operator 可以生成对应 ServiceMonitor。生产告警至少覆盖：

- Keycloak 实例不可用、登录错误率和响应延迟。
- PostgreSQL 连接、连接池耗尽、慢查询、存储和复制延迟。
- Pod 重启、OOM、CPU throttling 和 JVM GC。
- TLS 证书、数据库凭据和管理账号状态。

#### 14.2.8 生产检查清单

- [ ] 使用固定且受支持的 Keycloak/Operator 版本，升级使用手动审批。
- [ ] 至少两个 Keycloak 实例分散到不同节点或可用区。
- [ ] PostgreSQL 独立部署且具备高可用、备份、PITR 和恢复演练。
- [ ] 外部只开放 HTTPS，不暴露管理端口 `9000` 和数据库端口。
- [ ] `hostname`、证书 SAN、Ingress Host 和 Argo CD `issuer` 完全一致。
- [ ] Ingress 覆盖可信代理头，NetworkPolicy 限制只能从指定入口访问。
- [ ] 初始管理员已替换，正式管理员启用 MFA，并保留应急恢复流程。
- [ ] 资源、拓扑分散、PodDisruptionBudget 和升级窗口经过验证。
- [ ] 健康检查、Prometheus 指标、日志和告警已接入。
- [ ] Realm、Client、Group、Role 的变更和数据库恢复流程有审计记录。

### 14.3 Keycloak 创建 OIDC 客户端

在目标 Realm 中创建客户端：

```text
Client type: OpenID Connect
Client ID: argocd
Client authentication: Off
Standard flow: On
PKCE method: S256
```

这里使用不保存 client secret 的公开客户端和 PKCE。根据官方 Keycloak 集成说明，需要 CLI 登录时应选择 PKCE 方式。

以 Argo CD 地址 `https://argocd.example.com` 为例，Keycloak 客户端至少配置：

```text
Root URL: https://argocd.example.com
Home URL: https://argocd.example.com/applications
Web origins: https://argocd.example.com

Valid redirect URIs:
https://argocd.example.com/auth/callback
https://argocd.example.com/pkce/verify
http://localhost:8085/auth/callback

Valid post logout redirect URIs:
https://argocd.example.com/applications
```

说明：

- `/auth/callback` 用于 Argo CD 的 OIDC 回调。
- `/pkce/verify` 用于 PKCE Web UI 流程。
- `http://localhost:8085/auth/callback` 用于 CLI；`8085` 是 `--sso-port` 的默认端口。
- 生产环境不要使用 `https://argocd.example.com/*` 这类过宽回调地址。
- 如果 Argo CD 发布在 `/argo-cd` 子路径，应把 Web 回调改成 `https://example.com/argo-cd/auth/callback` 和 `https://example.com/argo-cd/pkce/verify`；CLI 本地回调不变。

### 14.4 配置 Keycloak 的 `groups` claim

如果要按 Keycloak 组授权，需要让 ID Token 中包含 `groups`：

1. 创建名为 `groups` 的 Client Scope。
2. 添加 `Group Membership` Mapper。
3. 将 `Token Claim Name` 设置为 `groups`。
4. 建议关闭 `Full group path`，使 claim 为 `ArgoCDAdmins`，而不是 `/ArgoCDAdmins`。
5. 将该 Client Scope 添加到 `argocd` 客户端的 Default 或 Optional scopes。
6. 如果设为 Optional，Argo CD 的 `requestedScopes` 必须包含 `groups`。

可先创建测试组，例如：

```text
ArgoCDAdmins
team-a-platform
```

将测试用户加入对应组。最终 RBAC 中的组名必须与 ID Token 的 `groups` claim 完全一致，包括大小写和可能存在的前导 `/`。

### 14.5 配置 Argo CD OIDC

把下面内容合并到已有 `argocd-cm`，不要覆盖其中仍然有效的其他配置：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-cm
    app.kubernetes.io/part-of: argocd
data:
  url: https://argocd.example.com
  oidc.config: |
    name: Keycloak
    issuer: https://keycloak.example.com/realms/platform
    clientID: argocd
    enablePKCEAuthentication: true
    refreshTokenThreshold: 2m
    requestedScopes:
      - openid
      - profile
      - email
      - groups
      - offline_access
```

参数说明：

| 参数 | 说明 |
|---|---|
| `url` | 用户实际访问的 Argo CD 外部地址，必须与 TLS 域名和回调地址一致 |
| `issuer` | OIDC Issuer，Keycloak 17+ 通常为 `https://<host>/realms/<realm>` |
| `clientID` | Keycloak 中创建的客户端 ID |
| `enablePKCEAuthentication` | 开启 PKCE；Keycloak 侧也必须配置 `S256` |
| `refreshTokenThreshold` | 在 Token 到期前刷新，必须短于身份提供商的 Token 生命周期 |
| `requestedScopes` | 请求用户信息、组和刷新能力；实际支持范围取决于身份提供商 |

先验证 Keycloak 的 OIDC Discovery 地址可从 `argocd-server` 所在网络访问：

```text
https://keycloak.example.com/realms/platform/.well-known/openid-configuration
```

如果使用传统 confidential client 而不是 PKCE 公开客户端，Secret 不应直接写入 ConfigMap。将它保存在 `argocd-secret` 或其他带 Argo CD 标签的 Secret 中：

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: argocd-oidc-secret
  namespace: argocd
  labels:
    app.kubernetes.io/part-of: argocd
type: Opaque
stringData:
  clientSecret: <OIDC_CLIENT_SECRET>
```

然后在 `oidc.config` 中引用：

```yaml
data:
  oidc.config: |
    name: ExampleOIDC
    issuer: https://idp.example.com
    clientID: argocd
    clientSecret: $argocd-oidc-secret:clientSecret
    requestedScopes: ["openid", "profile", "email", "groups"]
```

示例中的 `<OIDC_CLIENT_SECRET>` 不能明文提交到 Git。生产环境应由 External Secrets、Sealed Secrets 或其他密钥系统生成该 Secret。直接连接 Keycloak 的 PKCE 示例不需要 client secret。

应用配置：

```bash
kubectl apply -f argocd-cm.yaml
kubectl -n argocd get configmap argocd-cm -o yaml
kubectl -n argocd logs deployment/argocd-server --since=10m
```

Argo CD 通常会监听配置变化。如果登录页没有出现 Keycloak、登录循环或持续返回 `401`，在确认配置无误后重启 API Server：

```bash
kubectl -n argocd rollout restart deployment/argocd-server
kubectl -n argocd rollout status deployment/argocd-server --timeout=300s
```

### 14.6 配置 SSO 组权限

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
  scopes: '[groups, email]'
  policy.csv: |
    p, role:authenticated, applications, get, */*, allow
    p, role:team-a-deployer, applications, get, team-a/*, allow
    p, role:team-a-deployer, applications, sync, team-a/*, allow
    p, role:team-a-deployer, logs, get, team-a/*, allow
    g, team-a-platform, role:team-a-deployer
```

在这个例子中，Keycloak 组 `team-a-platform` 会映射到 `role:team-a-deployer`。不要在 SSO 刚接入时直接把普通业务组映射为 `role:admin`。

验证策略：

```bash
argocd admin settings rbac can \
  team-a-platform \
  sync \
  applications \
  'team-a/demo-api-prod' \
  --namespace argocd

argocd admin settings rbac validate --namespace argocd
```

### 14.7 使用 CLI 执行 SSO 登录

Argo CD 直接暴露且原生 gRPC 可用：

```bash
argocd login argocd.example.com --sso
```

经过只适合 gRPC-Web 的 Ingress 或代理：

```bash
argocd login argocd.example.com \
  --sso \
  --grpc-web
```

命令会在本机监听 `127.0.0.1:8085` 并打开浏览器。完成 Keycloak 登录后，浏览器回调到 CLI，终端显示登录成功。验证当前身份和权限：

```bash
argocd account get-user-info --grpc-web
argocd app list --grpc-web
```

本机 `8085` 已占用时可改端口，但必须把相同回调地址加入 Keycloak：

```bash
argocd login argocd.example.com \
  --sso \
  --sso-port 18085 \
  --grpc-web
```

对应回调地址：

```text
http://localhost:18085/auth/callback
```

不自动打开浏览器：

```bash
argocd login argocd.example.com \
  --sso \
  --sso-launch-browser=false \
  --grpc-web
```

命令会输出登录 URL。浏览器必须能够访问执行 CLI 的本地回调端口；如果 CLI 在远程服务器而浏览器在个人电脑，需要安全的 SSH 本地端口转发，或直接在有浏览器的本机执行 CLI。

如果还使用 URL 子路径：

```bash
argocd login example.com \
  --sso \
  --grpc-web \
  --grpc-web-root-path /argo-cd
```

`--sso` 负责身份认证，`--grpc-web` 负责 CLI 通信协议，两者互不替代。完整 gRPC-Web 说明见 [6.3 `--grpc-web` 参数用法](#63---grpc-web-参数用法)。

### 14.8 验证后禁用内置 admin

必须先用至少两个 SSO 管理员账号验证登录和权限，再禁用 admin：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-cm
    app.kubernetes.io/part-of: argocd
data:
  admin.enabled: "false"
```

保留经过审计的恢复方案，确保身份提供商故障或 RBAC 配置错误时仍能安全恢复管理权限。

### 14.9 常见 SSO 故障

| 现象 | 常见原因 | 检查方向 |
|---|---|---|
| 登录页没有 SSO 按钮 | `oidc.config` 解析失败或 `url` 缺失 | `argocd-cm`、server 日志 |
| Keycloak 报 `invalid_redirect_uri` | 回调地址未登记或路径/协议不一致 | `/auth/callback`、`/pkce/verify`、CLI localhost 回调 |
| CLI 一直等待回调 | 8085 被占用、浏览器不在 CLI 所在机器 | `--sso-port`、本地防火墙、SSH 端口转发 |
| `Missing parameter: code_challenge_method` | Keycloak 与 Argo CD 的 PKCE 配置不一致 | 两端均启用 PKCE，方法为 `S256` |
| 登录成功但没有权限 | `groups` claim 缺失或 RBAC 组名不匹配 | Token claims、`scopes`、`policy.csv` |
| 登录循环或 `401` | issuer、时间同步、Cookie、代理头或旧会话异常 | OIDC Discovery、NTP、私密窗口、server 日志 |
| `x509: certificate signed by unknown authority` | Argo CD 不信任身份提供商证书 | 配置受信任根 CA，不要长期跳过校验 |

排查命令：

```bash
kubectl -n argocd get configmap argocd-cm -o yaml
kubectl -n argocd get configmap argocd-rbac-cm -o yaml
kubectl -n argocd logs deployment/argocd-server --since=30m

argocd login argocd.example.com \
  --sso \
  --grpc-web \
  --loglevel debug
```

调试日志可能包含用户标识、URL 或会话相关信息，分享前应脱敏。

安全要点：

- `policy.default` 只授予所有已认证用户都应该拥有的最低权限。
- `role:admin` 权限不受限，只给少数平台管理员。
- RBAC 的 Application 对象通常按 `<project>/<application>` 匹配。
- 同时用 AppProject 限制仓库和目标位置，避免只依赖用户 RBAC。
- SSO 稳定后禁用 admin，并保留经过审计的紧急恢复流程。

官方完整语法见[用户管理](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/)、[Keycloak 集成](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/keycloak/)和[RBAC 配置](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)。

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

如果只有 `--grpc-web` 可用，检查代理是否支持原生 HTTP/2 gRPC；如果使用子路径，还应确认 `--grpc-web-root-path` 与服务端 `server.rootpath` 一致。端口转发可用而 Ingress 不可用，通常说明问题位于 Ingress、负载均衡、DNS 或 TLS 配置，而非 Argo CD 核心组件。完整参数说明见 [6.3 `--grpc-web` 参数用法](#63---grpc-web-参数用法)。

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
- [CLI Environment Variables](https://argo-cd.readthedocs.io/en/stable/user-guide/environment-variables/)
- [CLI Login Command](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_login/)
- [Automated Sync Policy](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [ApplicationSet](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/)
- [Ingress](https://argo-cd.readthedocs.io/en/stable/operator-manual/ingress/)
- [TLS](https://argo-cd.readthedocs.io/en/stable/operator-manual/tls/)
- [User Management and SSO](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/)
- [Keycloak Integration](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/keycloak/)
- [RBAC](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
- [Keycloak Container](https://www.keycloak.org/server/containers)
- [Keycloak Operator Installation](https://www.keycloak.org/operator/installation)
- [Keycloak Operator Basic Deployment](https://www.keycloak.org/operator/basic-deployment)
- [Keycloak Reverse Proxy](https://www.keycloak.org/server/reverseproxy)
- [Keycloak Releases](https://github.com/keycloak/keycloak/releases)
- [Metrics](https://argo-cd.readthedocs.io/en/stable/operator-manual/metrics/)
- [Disaster Recovery](https://argo-cd.readthedocs.io/en/stable/operator-manual/disaster_recovery/)
- [Upgrading](https://argo-cd.readthedocs.io/en/stable/operator-manual/upgrading/overview/)
- [Argo CD Releases](https://github.com/argoproj/argo-cd/releases)
