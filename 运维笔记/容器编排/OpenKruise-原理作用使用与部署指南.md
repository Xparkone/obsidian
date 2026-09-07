# OpenKruise：原理、作用、使用与部署指南

> 资料核对日期：2026-09-07
> 官方文档版本：v1.9
> 适用范围：Kubernetes 1.18+、自建集群、K3s、托管 Kubernetes
> 说明：本文的 Helm 命令以 OpenKruise `1.9.0` 为示例。生产部署前请根据目标 Kubernetes 版本检查官方兼容矩阵并固定经过验证的版本。

---

## 1. 先讲结论

OpenKruise 是 Kubernetes 的扩展组件套件，重点解决大规模应用的发布、升级、运维和可用性保护问题。它通过 CRD、控制器和 Admission Webhook 扩展 Kubernetes，而不是替换 Kubernetes 控制面。

最常用的价值有四类：

1. **更平滑的发布**：CloneSet、Advanced StatefulSet、Advanced DaemonSet 支持原地升级、分批并行、最大不可用数、分区发布等策略。
2. **统一的 Pod 扩展**：SidecarSet 按标签向新建 Pod 注入日志、监控、代理等 sidecar，并可以独立滚动升级 sidecar。
3. **集群级运维操作**：ImagePullJob 预热镜像，ContainerRecreateRequest 只重启 Pod 中指定的容器，BroadcastJob 在节点集合上各执行一次任务。
4. **可用性保护**：PodUnavailableBudget（PUB）约束发布、SidecarSet 升级、节点缩容等自愿中断场景；Deletion Protection 防止资源级联删除造成意外影响。

OpenKruise 不是“安装后所有 Deployment 自动变快”的插件。只有把工作负载改为 Kruise CRD，或显式创建 SidecarSet、PUB 等对象，相关能力才会生效。原地升级也有字段限制，不能把所有 Pod 模板变更都当作无重建升级。

---

## 2. OpenKruise 是什么

### 2.1 项目定位

OpenKruise（简称 Kruise）是 CNCF 旗下的 Kubernetes 扩展项目，主要面向大规模应用管理。大多数能力基于 CRD 扩展，可以运行在纯 Kubernetes 集群中，不依赖特定云厂商。

它与 Kubernetes 原生控制器的关系可以理解为：

```text
业务 YAML / GitOps
        |
        v
Kubernetes API Server ---- CRD / Admission Webhook
        |                         |
        |                         +--> SidecarSet 注入 Pod
        v
OpenKruise Controller Manager --+--> CloneSet / Advanced StatefulSet / ...
        |
        +--> KruiseDaemon（按节点运行，负责部分节点级原地操作）
        |
        v
Pod、容器、镜像与可用性状态
```

核心组件通常包括：

| 组件 | 运行方式 | 作用 |
|---|---|---|
| `kruise-manager` | Deployment，默认 2 副本 | 监听 CRD 和原生资源，执行调谐、滚动升级、扩缩容和保护策略 |
| Admission Webhook | 与 manager 同一 Helm Release | 在 Pod 创建/更新时处理 SidecarSet 注入、校验和部分元数据变更 |
| `kruise-daemon` | DaemonSet，每个节点一个 | 访问容器运行时并执行指定容器重建、镜像预热等节点级操作 |
| CRD | 集群级 API 扩展 | 注册 `apps.kruise.io`、`policy.kruise.io` 等资源类型 |
| `ControllerRevision` | Kubernetes 原生资源 | 保存工作负载或 SidecarSet 的版本快照，支持版本识别和回滚相关操作 |

### 2.2 与 Kubernetes 原生资源的关系

| 原生对象 | Kruise 对应能力 | 适用判断 |
|---|---|---|
| Deployment | CloneSet | 无实例顺序要求、希望原地升级或精细控制删除/升级顺序 |
| StatefulSet | Advanced StatefulSet（Kind 仍为 `StatefulSet`） | 需要状态身份、PVC、并行更新或原地更新 |
| DaemonSet | Advanced DaemonSet（Kind 仍为 `DaemonSet`） | 节点级 Agent、镜像预下载、节点范围分批升级 |
| 无直接对应 | SidecarSet | 多个工作负载共用日志、服务网格、监控或安全 sidecar |
| 无直接对应 | UnitedDeployment | 按可用区、节点池或其他域拆分多个子工作负载 |
| Job/DaemonSet 组合 | BroadcastJob | 每个匹配节点运行一次并等待完成 |
| CronJob | AdvancedCronJob | 需要更丰富的并发、失败和历史任务控制 |
| PDB | PodUnavailableBudget | 保护发布、原地升级、HPA 缩容和 drain 等更多自愿中断场景 |

Kruise 可以与 Deployment、Service、HPA、PDB、Argo Rollouts 等共同使用，但要确认每个控制器的 owner、scale 子资源和发布职责，避免多个控制器同时修改同一个字段。

---

## 3. 有什么作用

### 3.1 原地升级（In-place Update）

原地升级尽可能只重启 Pod 中发生变化的容器，不删除并重建整个 Pod。这样可以减少调度、CNI、CSI、Pod IP、挂载卷和连接状态的副作用，适合大规模无状态服务或需要缩短发布窗口的场景。

常见更新类型：

| 类型 | 行为 | 注意事项 |
|---|---|---|
| `ReCreate` | 删除旧 Pod，再创建新 Pod | 兼容性最好，但会产生完整 Pod 重建 |
| `InPlaceIfPossible` | 支持时原地更新，不支持时回退重建 | 常用默认选择；必须验证哪些字段被支持 |
| `InPlaceOnly` | 只能原地更新，不支持的字段会被拒绝 | 适合强约束场景，配置错误会阻塞发布 |
| `OnDelete` | 控制器不主动更新 Pod，由人工删除逐个触发 | 适合需要人工控制节奏的发布 |

当前最常见的原地更新字段是容器镜像及部分容器字段。环境变量、挂载、探针、SecurityContext 等字段是否可以原地处理，取决于工作负载类型和 OpenKruise 版本；不要只根据 YAML 是否能提交来判断发布是否无重建。

### 3.2 发布与扩缩容控制

Kruise 工作负载提供以下常用控制项：

- `maxUnavailable`：升级或扩缩容过程中最多允许多少 Pod 不可用；
- `maxSurge`：允许超过期望副本数额外创建多少 Pod；
- `partition`：保留多少副本在旧版本，实现灰度或分批推进；
- `minReadySeconds`：Pod Ready 后继续观察一段时间再推进下一批；
- `paused`：暂停升级但继续维持副本数；
- `priorityStrategy`、`scatterStrategy`：按标签或顺序控制更新顺序；
- 生命周期 Hook：在 `PreparingUpdate`、`PreparingDelete` 等阶段执行业务摘流、检查或清理。

### 3.3 Sidecar 独立生命周期

SidecarSet 在 Pod 创建时通过 Admission Webhook 注入容器、卷和必要的元数据。业务 Deployment 的模板不需要复制 sidecar 配置，sidecar 的镜像升级也可以独立于业务容器进行。

适合：

- 日志采集 Agent；
- Service Mesh 数据面代理；
- 安全扫描或运行时防护 Agent；
- 统一的可观测性探针。

风险：

- selector 过宽会向不应注入的 Namespace 或 Pod 加容器；
- 新 Pod 才会自动注入，已运行 Pod 的处理取决于更新策略；
- sidecar 的 CPU、内存、镜像拉取权限会直接影响业务 Pod 调度；
- Webhook 不可用或证书过期时，Pod 创建行为可能受 `failurePolicy` 影响，必须做故障演练。

### 3.4 节点级和容器级运维

- **ImagePullJob**：指定镜像和节点，提前拉取大镜像，减少发布时的拉取等待；
- **ContainerRecreateRequest（CRR）**：在不重建 Pod 的情况下，重建指定容器；其他容器继续运行，卷挂载数据保留，但容器 rootfs 中写入的数据会丢失；
- **BroadcastJob**：在每个匹配节点启动一次 Job Pod，适合节点初始化、升级前检查和一次性巡检；
- **ResourceDistribution**：把 Secret、ConfigMap 等资源按规则分发到多个 Namespace；
- **PodProbeMarker / PersistentPodState**：为探针结果和 Pod 状态持久化提供扩展能力。

### 3.5 可用性保护

Kubernetes PDB 主要约束通过 Eviction API 发起的驱逐。PUB 还可以约束工作负载升级、SidecarSet 升级、HPA 缩容等更多自愿中断，避免业务方和平台方同时操作时超出可接受的不可用数。

PUB 只能减少受控的自愿中断，不能阻止节点宕机、内核故障、网络分区、镜像仓库不可用或应用自身崩溃。`maxUnavailable` / `minAvailable` 的计算还会受副本数、selector 和 workload scale 子资源影响。

---

## 4. 主要资源怎么选

| 需求 | 推荐资源 | 关键字段/能力 |
|---|---|---|
| 无状态服务，实例没有固定顺序 | `CloneSet` | 原地升级、`maxUnavailable`、`maxSurge`、`partition`、指定 Pod 删除 |
| 有序身份、稳定网络名和 PVC | `apps.kruise.io/v1beta1` 的 `StatefulSet` | `podUpdatePolicy`、并行更新、`reserveOrdinals`、PVC 策略 |
| 每个节点一个 Agent，需要渐进升级 | `apps.kruise.io/v1beta1` 的 `DaemonSet` | 原地升级、节点 selector、镜像预下载、`maxUnavailable` |
| 每个节点只执行一次任务 | `BroadcastJob` | `completionPolicy`、`parallelism`、节点 selector |
| 给一组 Pod 注入公共容器 | `SidecarSet` | selector、namespaceSelector、RollingUpdate、版本快照 |
| 一个应用分布在多个节点域 | `UnitedDeployment` | subsets、nodeSelectorTerm、每个 subset 的副本策略 |
| 只重启某个容器 | `ContainerRecreateRequest` | `podName`、容器列表、顺序、超时、失败策略 |
| 保护多个中断来源 | `PodUnavailableBudget` | targetRef 或 selector、`maxUnavailable` / `minAvailable` |

不要为了使用某一个高级字段而整体迁移所有工作负载。可以先在测试 Namespace 使用 CloneSet 或 SidecarSet，验证控制器行为、监控指标、GitOps 兼容性和回滚路径，再逐步扩大范围。

---

## 5. 部署前检查

### 5.1 检查集群和工具

```bash
kubectl version
kubectl config current-context
kubectl cluster-info
helm version
helm list -A
```

OpenKruise 自 v1.0 起要求 Kubernetes 不低于 1.16；较新的 Kruise 版本对 Kubernetes、CRI 和 KruiseDaemon 有更高要求。以 v1.9 文档为例，官方兼容矩阵覆盖 Kubernetes 1.18、1.20、1.22、1.24、1.26、1.28、1.30、1.32，并明确标注了已测试、可运行和未测试的组合。升级前应检查 [官方兼容矩阵](https://openkruise.io/docs/installation)。

检查节点运行时，避免把 Docker Engine + dockershim 当作默认前提：

```bash
kubectl get nodes -o wide
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.nodeInfo.containerRuntimeVersion}{"\n"}{end}'
```

OpenKruise 1.5 起不再支持 dockershim；如果集群仍使用 Docker Engine，应先迁移到受支持的 CRI 方案，或按官方说明关闭依赖 KruiseDaemon 的能力。

### 5.2 只读确认现有资源

```bash
kubectl get crd | grep -E 'kruise|apps.kruise.io|policy.kruise.io' || true
kubectl get ns kruise-system --ignore-not-found
kubectl get deploy,ds -A | grep -E 'kruise|kruise-manager' || true
helm list -A | grep -i kruise || true
```

同时确认：

- 目标集群是否允许创建 CRD、Webhook、ClusterRole 和 DaemonSet；
- 是否已有其他版本的 Kruise 或同名 Helm Release；
- 节点是否允许 `kruise-daemon` 所需的 HostPath、容器运行时 socket 和权限；
- 镜像仓库是否可以拉取 `openkruise/kruise-manager` 和 `openkruise/kruise-daemon`；
- GitOps 工具是否会管理或回滚 Helm 创建的 CRD；
- 生产集群是否需要企业镜像仓库、镜像签名和出站网络白名单。

---

## 6. 使用 Helm 部署

### 6.1 添加 Chart 仓库并查看版本

```bash
helm repo add openkruise https://openkruise.github.io/charts/
helm repo update
helm search repo openkruise/kruise --versions | head -20
helm show chart openkruise/kruise --version 1.9.0
helm show values openkruise/kruise --version 1.9.0 > /tmp/kruise-values-1.9.0.yaml
```

生产环境应把 Chart、镜像 Tag 和 values 文件纳入 Git，先执行模板渲染与静态检查：

```bash
helm template kruise openkruise/kruise \
  --namespace kruise-system \
  --version 1.9.0 \
  > /tmp/kruise-rendered.yaml

kubectl apply --dry-run=server -f /tmp/kruise-rendered.yaml
```

`kubectl apply --dry-run=server` 需要访问目标 API Server，并且会受到当前身份权限和集群 OpenAPI Schema 影响；它不是对 Webhook、镜像拉取和节点权限的完整验证。

### 6.2 测试集群安装

```bash
helm upgrade --install kruise openkruise/kruise \
  --namespace kruise-system \
  --create-namespace \
  --version 1.9.0 \
  --set installation.namespace=kruise-system \
  --wait \
  --timeout 10m
```

如果测试集群使用私有镜像仓库，可按 Chart values 覆盖 manager、daemon 镜像仓库和 `imagePullSecrets`。不要直接把真实 Secret 内容写入命令历史或文档。

### 6.3 生产安装建议

先保存一份经过评审的 values 文件，例如 `kruise-values.yaml`：

```yaml
installation:
  namespace: kruise-system
  createNamespace: true

manager:
  replicas: 2
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 200m
      memory: 512Mi

# 按实际需要开启，默认空字符串表示使用 Chart 默认 FeatureGates
featureGates: ""
```

再执行：

```bash
helm upgrade --install kruise openkruise/kruise \
  --namespace kruise-system \
  --create-namespace \
  --version 1.9.0 \
  --values kruise-values.yaml \
  --wait \
  --timeout 10m
```

生产值文件至少应评审：

- `featureGates` 是否开启了不兼容或实验特性；
- manager 副本数、资源、拓扑分布和 Pod 安全策略；
- daemon 是否部署在所有节点，是否需要 nodeSelector、tolerations；
- 镜像仓库、签名校验和拉取 Secret；
- Webhook 证书轮换、API Server 到 Webhook 的网络路径；
- metrics、日志、告警和审计采集；
- CRD 是否由 Helm 管理，GitOps 是否会重复应用。

### 6.4 部署验证

```bash
kubectl get crd | grep -E 'kruise|kruise.io'
kubectl get pods -n kruise-system -o wide
kubectl get deploy,ds -n kruise-system
kubectl rollout status deploy/kruise-controller-manager -n kruise-system --timeout=5m
kubectl get validatingwebhookconfiguration,mutatingwebhookconfiguration | grep -i kruise
helm status kruise -n kruise-system
```

重点检查：

1. `kruise-controller-manager` 所有副本为 `Ready`；
2. `kruise-daemon` 在预期节点上为 `Ready`（若启用了该能力）；
3. CRD 的 Established 条件为 True；
4. Webhook 配置存在且没有持续 TLS、连接或拒绝错误；
5. manager 日志没有 RBAC、反序列化或 leader election 错误。

日志查看：

```bash
kubectl logs -n kruise-system deploy/kruise-controller-manager --since=15m
kubectl logs -n kruise-system ds/kruise-daemon --all-containers --since=15m
```

---

## 7. 常用工作负载示例

### 7.1 CloneSet：无状态服务原地升级

```yaml
apiVersion: apps.kruise.io/v1alpha1
kind: CloneSet
metadata:
  name: web
  namespace: demo
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
      - name: web
        image: nginx:1.27.1
        ports:
        - containerPort: 80
        readinessProbe:
          httpGet:
            path: /
            port: 80
          periodSeconds: 5
  updateStrategy:
    type: InPlaceIfPossible
    maxUnavailable: 1
    maxSurge: 1
    inPlaceUpdateStrategy:
      gracePeriodSeconds: 10
```

应用并观察：

```bash
kubectl create namespace demo --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f cloneset-web.yaml
kubectl get cloneset web -n demo -o wide
kubectl get pods -n demo -l app=web -o wide
kubectl describe cloneset web -n demo
```

升级镜像：

```bash
kubectl -n demo set image cloneset/web web=nginx:1.27.2
kubectl get cloneset web -n demo -o jsonpath='{.status.updatedReadyReplicas}{"/"}{.status.replicas}{"\n"}'
kubectl get pods -n demo -l app=web -w
```

说明：`maxSurge` 与 `InPlaceOnly` 不能同时使用；如果更新字段不支持原地处理，`InPlaceIfPossible` 可能回退到 Pod 重建。发布验收应观察 Pod UID、容器重启次数、Ready 状态、Service Endpoint 和业务请求，而不是只看资源对象为 `Updated`。

灰度发布可以使用 `partition`：

```bash
kubectl -n demo patch cloneset web --type=merge \
  -p '{"spec":{"updateStrategy":{"partition":2}}}'
```

对于 3 个副本，`partition: 2` 表示只推进 1 个 Pod 到新版本。推进前要确认新版本健康，再逐步把 partition 调小到 `0`。partition 不定义更新顺序，也不等于流量权重。

### 7.2 Advanced StatefulSet：状态服务并行/原地更新

Advanced StatefulSet 的 Kind 仍然是 `StatefulSet`，区别在于 API Group 和扩展字段：

```yaml
apiVersion: apps.kruise.io/v1beta1
kind: StatefulSet
metadata:
  name: db
  namespace: demo
spec:
  serviceName: db-headless
  replicas: 3
  podManagementPolicy: Parallel
  selector:
    matchLabels:
      app: db
  template:
    metadata:
      labels:
        app: db
    spec:
      readinessGates:
      - conditionType: InPlaceUpdateReady
      containers:
      - name: db
        image: postgres:16.4
        ports:
        - containerPort: 5432
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      podUpdatePolicy: InPlaceIfPossible
      maxUnavailable: 1
      inPlaceUpdateStrategy:
        gracePeriodSeconds: 10
```

使用原地更新时需要在模板中加入 `InPlaceUpdateReady` readiness gate；否则 Pod 可能在更新期间仍被认为可接收流量。数据库升级还必须遵循数据库自身的主从、协议和数据迁移策略，OpenKruise 不会替代数据库 Operator 的一致性控制。

### 7.3 Advanced DaemonSet：节点 Agent 分批升级

```yaml
apiVersion: apps.kruise.io/v1beta1
kind: DaemonSet
metadata:
  name: node-agent
  namespace: demo
spec:
  selector:
    matchLabels:
      app: node-agent
  template:
    metadata:
      labels:
        app: node-agent
    spec:
      containers:
      - name: agent
        image: busybox:1.36
        command: ["sh", "-c", "sleep 3600"]
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      rollingUpdateType: InPlaceIfPossible
      maxUnavailable: 1
```

DaemonSet 的字段以目标 Kruise 版本 CRD schema 为准。节点 Agent 升级前需要确认：旧 Agent 是否能与新 Agent 并存、是否占用 HostPort、是否写入主机目录、是否有节点重启或内核依赖。

### 7.4 SidecarSet：为业务 Pod 注入日志 Agent

```yaml
apiVersion: apps.kruise.io/v1beta1
kind: SidecarSet
metadata:
  name: log-agent
spec:
  namespaceSelector:
    matchLabels:
      kruise-sidecar: enabled
  selector:
    matchLabels:
      log-agent: enabled
  updateStrategy:
    type: RollingUpdate
    maxUnavailable: 1
  containers:
  - name: log-agent
    image: busybox:1.36
    command: ["sh", "-c", "sleep 3600"]
    volumeMounts:
    - name: app-logs
      mountPath: /var/log/app
  volumes:
  - name: app-logs
    emptyDir: {}
```

业务 Pod 只需带上 selector 标签：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-with-agent
  namespace: demo
  labels:
    log-agent: enabled
spec:
  containers:
  - name: app
    image: nginx:1.27.1
```

验证注入：

```bash
kubectl get pod web-with-agent -n demo -o jsonpath='{.spec.containers[*].name}{"\n"}'
kubectl describe pod web-with-agent -n demo
kubectl get sidecarset log-agent -o yaml
```

SidecarSet 默认是集群范围资源。生产环境建议使用 `namespaceSelector` 和足够窄的 Pod selector，并在测试 Namespace 先验证注入顺序、资源总量、私有镜像 Secret、优雅退出和 Webhook 故障行为。

### 7.5 ContainerRecreateRequest：只重建一个容器

```yaml
apiVersion: apps.kruise.io/v1alpha1
kind: ContainerRecreateRequest
metadata:
  name: restart-log-agent
  namespace: demo
spec:
  podName: web-with-agent
  containers:
  - name: log-agent
  strategy:
    failurePolicy: Fail
    orderedRecreate: true
    terminationGracePeriodSeconds: 30
    minStartedSeconds: 10
  activeDeadlineSeconds: 300
  ttlSecondsAfterFinished: 1800
```

```bash
kubectl apply -f crr.yaml
kubectl get crr -n demo
kubectl describe crr restart-log-agent -n demo
```

该能力依赖 `kruise-daemon`。容器 rootfs 中的临时文件会丢失，卷中的数据通常保留；不要把 CRR 当作数据库恢复或 Pod 级故障隔离工具。

### 7.6 PodUnavailableBudget：保护发布期间的可用副本

```yaml
apiVersion: policy.kruise.io/v1alpha1
kind: PodUnavailableBudget
metadata:
  name: web-pub
  namespace: demo
spec:
  targetRef:
    apiVersion: apps.kruise.io/v1alpha1
    kind: CloneSet
    name: web
  maxUnavailable: 1
```

`targetRef` 和 `selector` 二选一。使用 `targetRef` 时，目标工作负载必须提供可用的 scale 子资源；使用 selector 时，要避免把多个不应共享预算的应用混在一起。

---

## 8. 与 GitOps、HPA、Service 和 PDB 配合

### 8.1 GitOps

建议把以下内容纳入 Git：

- OpenKruise Helm Chart 版本和 values；
- CRD 工作负载 YAML；
- SidecarSet、PUB、FeatureGate 配置；
- 版本升级说明和回滚命令；
- 预发布与生产的差异化 values。

Argo CD 或 Flux 管理时，明确 CRD 的安装顺序和 owner。不要让 Helm、GitOps 和人工 `kubectl patch` 同时成为同一字段的长期写入方。对 `partition`、`paused` 这类临时发布字段，要设计发布完成后的归零和审计流程。

### 8.2 HPA

CloneSet、Advanced StatefulSet、UnitedDeployment 等工作负载实现了 scale 子资源，可以作为 HPA 的 `scaleTargetRef`。例如 CloneSet：

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web
  namespace: demo
spec:
  scaleTargetRef:
    apiVersion: apps.kruise.io/v1alpha1
    kind: CloneSet
    name: web
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

HPA 必须与目标工作负载在同一 Namespace，`apiVersion` 必须与实际对象一致。上线前验证 HPA 是否能读到 scale 子资源、扩容是否触发、缩容是否受 PUB 和 `maxUnavailable` 约束。

### 8.3 Service、探针和流量摘除

原地更新期间，Kruise 会结合 Pod 状态和可选的 readiness gate 控制可用性。业务仍必须提供正确的：

- `readinessProbe`：决定 Service 是否发送流量；
- `preStop` 和 `terminationGracePeriodSeconds`：为连接排空留时间；
- `minReadySeconds`：避免刚 Ready 就继续更新；
- Service selector 与 Pod labels：避免升级后流量丢失。

建议验收时同时观察：

```bash
kubectl get pod -n demo -l app=web -o wide
kubectl get endpointslice -n demo -l kubernetes.io/service-name=web -o yaml
kubectl get events -n demo --sort-by=.lastTimestamp | tail -30
```

---

## 9. 升级、回滚与卸载

### 9.1 升级前

```bash
helm get values kruise -n kruise-system -a > /tmp/kruise-values-before.yaml
helm get manifest kruise -n kruise-system > /tmp/kruise-manifest-before.yaml
kubectl get crd -o yaml | grep -n -E 'kruise|apps.kruise.io|policy.kruise.io' > /tmp/kruise-crd-before.txt
```

阅读目标版本 Changelog，重点关注：

- CRD schema 和 API version 变化；
- FeatureGate 默认值；
- Webhook 证书和 selector 行为；
- KruiseDaemon 与 CRI 要求；
- 已存在 CR 是否需要迁移；
- 卸载前置检查和不可逆变化。

升级命令：

```bash
helm repo update
helm upgrade kruise openkruise/kruise \
  --namespace kruise-system \
  --version 1.9.0 \
  --values kruise-values.yaml \
  --wait \
  --timeout 10m
```

从 0.x 升级到 1.x 时，官方说明需要评估是否使用 `--force`；其他升级是否需要该参数，应以 Changelog 和测试结果为准，不要默认添加。

### 9.2 升级后

```bash
helm status kruise -n kruise-system
kubectl get pods -n kruise-system -o wide
kubectl get crd | grep -E 'kruise|kruise.io'
kubectl get events -n kruise-system --sort-by=.lastTimestamp | tail -50
```

在测试 Namespace 做一次最小验证：创建 CloneSet、升级镜像、创建 SidecarSet 注入 Pod、提交 CRR（若启用 daemon），再删除测试资源。生产工作负载还需验证 HPA、Service Endpoint、PDB/PUB、Argo CD 同步和监控告警。

### 9.3 回滚边界

```bash
helm history kruise -n kruise-system
helm rollback kruise <REVISION> -n kruise-system --wait --timeout 10m
```

Helm 回滚只能恢复 Helm 管理的组件和 CRD 定义，不能自动回滚：

- 已发布的业务 Pod 镜像；
- 已修改的 CloneSet/StatefulSet/SidecarSet CR；
- 数据库 schema 和数据；
- 已注入到运行中 Pod 的 sidecar；
- 已执行的 BroadcastJob、CRR 或 ImagePullJob；
- 外部 GitOps、镜像仓库和节点状态。

这些内容要分别定义回滚动作，并在演练中测量恢复时间。

### 9.4 卸载

```bash
helm uninstall kruise -n kruise-system
```

OpenKruise 自 1.7.3 起会在 Helm 卸载前检查是否仍有 Kruise CR。存在 CR 时，卸载可能被阻止，以避免先删除控制器、留下无人管理资源。不要直接删除 CRD 来“强制清理”；先盘点并按业务顺序清理或迁移所有 CloneSet、SidecarSet、PUB 等对象，再按官方步骤卸载。删除 CRD 会删除该类型资源的 API 定义，风险高且可能导致数据丢失。

---

## 10. 常见故障排查

### 10.1 Pod 一直 Pending 或容器无法启动

```bash
kubectl describe pod <pod> -n <namespace>
kubectl get events -n <namespace> --sort-by=.lastTimestamp | tail -50
kubectl get sidecarset -A
```

重点排查：Sidecar 注入后资源请求超过节点容量、私有镜像 Secret 不存在、节点 taint/selector 不匹配、Webhook 注入了错误的卷或安全上下文。

### 10.2 Sidecar 没有注入

```bash
kubectl get sidecarset <name> -o yaml
kubectl get pod <pod> -n <namespace> -o yaml
kubectl get mutatingwebhookconfiguration | grep -i kruise
kubectl logs -n kruise-system deploy/kruise-controller-manager --since=15m | grep -i -E 'sidecar|webhook|error'
```

确认：

- Pod 创建时是否已经匹配 label；
- Namespace 是否匹配 `namespaceSelector`；
- SidecarSet 是否被 `injectionStrategy.paused` 暂停；
- Webhook Service、证书、API Server 网络是否正常；
- Pod 是否在 Webhook 配置的排除范围内；
- 资源版本是 `v1alpha1` 还是 `v1beta1`，字段是否符合目标 CRD schema。

### 10.3 原地升级变成了 Pod 重建

这可能是预期行为。检查：

```bash
kubectl get cloneset <name> -n <namespace> -o yaml
kubectl get pod <pod> -n <namespace> -o jsonpath='{.metadata.uid}{"\n"}'
kubectl describe cloneset <name> -n <namespace>
```

判断依据：更新字段是否在当前版本支持原地更新、是否设置了 `InPlaceOnly`、是否触发了 PVC/卷模板或不可变字段变化、是否因为 readiness 或 `maxUnavailable` 暂停。不要只依据容器 restartCount 判断 Pod 是否重建；同时比较 Pod UID、创建时间、PVC 和 EndpointSlice。

### 10.4 CRR 一直不完成

```bash
kubectl get crr <name> -n <namespace> -o yaml
kubectl get pod -n kruise-system -l app.kubernetes.io/name=kruise-daemon -o wide
kubectl logs -n kruise-system ds/kruise-daemon --since=15m
```

确认 `kruise-daemon` 是否运行、节点上的容器运行时 socket 是否可访问、容器名称是否正确、`activeDeadlineSeconds` 是否过短、Pod 是否正在被删除或驱逐。

### 10.5 发布停在旧版本或不可用数超限

```bash
kubectl get cloneset,statefulset,daemonset -n <namespace> -o yaml
kubectl get pub -n <namespace>
kubectl get pdb -n <namespace>
kubectl get pod -n <namespace> -o wide
```

常见原因：

- `partition` 保留了旧副本；
- `paused: true`；
- `maxUnavailable` 与 PUB/PDB 共同限制，导致没有可操作窗口；
- 新 Pod readinessProbe 失败；
- 镜像拉取、配额、节点容量或反亲和规则阻塞；
- Service 没有可用 Endpoint，生命周期 Hook 一直等待。

### 10.6 Helm 升级或卸载失败

```bash
helm status kruise -n kruise-system
helm get hooks kruise -n kruise-system
kubectl get crd | grep -E 'kruise|kruise.io'
kubectl get cloneset,statefulset,daemonset,sidecarset,pub,crr -A
```

不要直接删除 Webhook、CRD 或 Finalizer。先保存资源 YAML、确认是否有业务对象、检查 manager 日志和 Helm hook，再决定是修复权限/网络、迁移资源，还是按官方卸载流程处理。

---

## 11. 生产落地清单

### 部署前

- [ ] 记录 Kubernetes、CRI、Helm 和 OpenKruise 版本；
- [ ] 对照官方兼容矩阵，确认是否启用 KruiseDaemon；
- [ ] 明确 Helm、GitOps、CRD 和业务 CR 的 owner；
- [ ] 评审 manager/daemon 资源、节点选择、容忍度和安全策略；
- [ ] 准备企业镜像仓库、拉取 Secret、镜像签名和回滚版本；
- [ ] 在测试集群验证 Webhook、Sidecar 注入和原地升级；
- [ ] 为所有新工作负载配置 readinessProbe、优雅退出和监控。

### 发布前

- [ ] 先执行 `helm template`、`kubectl apply --dry-run=server` 和 CRD schema 校验；
- [ ] 明确 `maxUnavailable`、`maxSurge`、`partition`、`minReadySeconds` 的数值；
- [ ] 评估 PUB/PDB/HPA 与发布策略的组合约束；
- [ ] 选择可回滚的镜像 Tag，不使用不可追溯的 `latest`；
- [ ] 验证 Service Endpoint、业务请求、日志和指标；
- [ ] 记录变更窗口、负责人、停止条件和人工回滚命令。

### 运行中

- [ ] 监控 manager/daemon Pod、Webhook 延迟/错误和 CRD reconcile 错误；
- [ ] 监控工作负载的 `updatedReplicas`、`updatedReadyReplicas`、不可用 Pod 和发布时长；
- [ ] 对 SidecarSet 注入范围、容器资源和镜像版本做审计；
- [ ] 定期清理完成的 CRR、BroadcastJob 和 ImagePullJob；
- [ ] 升级前阅读 Changelog 并在隔离环境做回归测试；
- [ ] 定期演练业务发布暂停、Kruise 控制器故障和卸载保护。

---

## 12. 最小命令集

```bash
# 组件状态
kubectl get pods -n kruise-system -o wide
kubectl get deploy,ds -n kruise-system
helm status kruise -n kruise-system

# CRD 与资源
kubectl get crd | grep -E 'kruise|kruise.io'
kubectl api-resources | grep -i kruise
kubectl get cloneset,statefulset,daemonset,sidecarset,pub,crr -A

# 工作负载发布观察
kubectl describe cloneset <name> -n <namespace>
kubectl get pod -n <namespace> -l app=<app> -w
kubectl get endpointslice -n <namespace>

# 日志与事件
kubectl logs -n kruise-system deploy/kruise-controller-manager --since=15m
kubectl logs -n kruise-system ds/kruise-daemon --since=15m
kubectl get events -A --sort-by=.lastTimestamp | tail -100

# Helm 变更
helm history kruise -n kruise-system
helm get values kruise -n kruise-system -a
```

---

## 13. 参考资料

- [OpenKruise 官方介绍](https://openkruise.io/docs)
- [OpenKruise 安装与兼容矩阵](https://openkruise.io/docs/installation)
- [CloneSet](https://openkruise.io/docs/user-manuals/cloneset)
- [Advanced StatefulSet](https://openkruise.io/docs/user-manuals/advancedstatefulset)
- [Advanced DaemonSet](https://openkruise.io/docs/user-manuals/advanceddaemonset)
- [SidecarSet](https://openkruise.io/docs/user-manuals/sidecarset)
- [BroadcastJob](https://openkruise.io/docs/user-manuals/broadcastjob)
- [Container Restart / ContainerRecreateRequest](https://openkruise.io/docs/user-manuals/containerrecreaterequest)
- [PodUnavailableBudget](https://openkruise.io/docs/user-manuals/podunavailablebudget)
- [OpenKruise GitHub 仓库](https://github.com/openkruise/kruise)

本文命令和字段以官方 v1.9 文档为依据；实际使用前仍应以目标集群安装的 CRD schema、Chart values 和 Changelog 为准。
