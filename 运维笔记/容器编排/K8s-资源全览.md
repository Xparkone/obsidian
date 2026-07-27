# Kubernetes 资源全览

> 一份面向运维与开发的 K8s 资源速查手册，涵盖所有核心资源类型、YAML 模板、常用命令和最佳实践。

---

## 目录

1. [资源分类总览](#一资源分类总览)
2. [Workloads（工作负载）](#二workloads工作负载)
3. [Service & Networking（服务与网络）](#三service--networking服务与网络)
4. [Config & Storage（配置与存储）](#四config--storage配置与存储)
5. [RBAC & Security（权限与安全）](#五rbac--security权限与安全)
6. [Autoscaling（弹性伸缩）](#六autoscaling弹性伸缩)
7. [Scheduling（调度）](#七scheduling调度)
8. [Observability（可观测性）](#八observability可观测性)
9. [Batch（批处理）](#九batch批处理)
10. [Custom Resources（自定义资源）](#十custom-resources自定义资源)
11. [常用命令速查](#十一常用命令速查)

---

## 一、资源分类总览

```
Kubernetes 资源层级
═══════════════════════════════════════════════════════════════

Cluster (集群)
├── Node (节点)
├── Namespace (命名空间)
│   ├── Workloads
│   │   ├── Pod                        ← 最小调度单元
│   │   ├── Deployment / StatefulSet / DaemonSet / Job / CronJob
│   │   └── ReplicaSet (由 Deployment 管理)
│   ├── Network
│   │   ├── Service / Endpoints / EndpointSlice
│   │   ├── Ingress / Gateway API
│   │   └── NetworkPolicy
│   ├── Config
│   │   ├── ConfigMap / Secret
│   │   └── ServiceAccount
│   ├── Storage
│   │   ├── PersistentVolume / PersistentVolumeClaim
│   │   └── StorageClass
│   └── Autoscaling
│       ├── HorizontalPodAutoscaler (HPA)
│       └── VerticalPodAutoscaler (VPA)
└── Cluster-wide
    ├── ClusterRole / ClusterRoleBinding
    ├── PriorityClass
    ├── ResourceQuota / LimitRange
    └── CustomResourceDefinition (CRD)
```

### 资源 API 版本速查

| 资源 | API 版本 | 说明 |
|------|---------|------|
| Pod | `v1` | 核心资源，稳定 |
| Deployment / StatefulSet / DaemonSet | `apps/v1` | 稳定 |
| ReplicaSet | `apps/v1` | 稳定 |
| Job / CronJob | `batch/v1` | 稳定 |
| Service | `v1` | 稳定 |
| Ingress | `networking.k8s.io/v1` | 稳定 |
| NetworkPolicy | `networking.k8s.io/v1` | 稳定 |
| HPA | `autoscaling/v2` | 稳定 |
| CSI / StorageClass | `storage.k8s.io/v1` | 稳定 |
| Gateway API | `gateway.networking.k8s.io/v1` | 较新 |

---

## 二、Workloads（工作负载）

### 1. Pod — 最小调度单元

**用途**: 一个或多个容器的集合，共享网络和存储。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-pod
  labels:
    app: nginx
spec:
  # 容器列表
  containers:
  - name: nginx
    image: nginx:1.25
    ports:
    - containerPort: 80
      protocol: TCP
    # 资源限制
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        cpu: 500m
        memory: 256Mi
    # 存活探针
    livenessProbe:
      httpGet:
        path: /healthz
        port: 80
      initialDelaySeconds: 10
      periodSeconds: 15
    # 就绪探针
    readinessProbe:
      httpGet:
        path: /ready
        port: 80
      initialDelaySeconds: 5
      periodSeconds: 10
    # 环境变量
    env:
    - name: ENV
      value: "production"
    - name: DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: db-secret
          key: password
    # 挂载卷
    volumeMounts:
    - name: config
      mountPath: /etc/nginx/conf.d
    - name: data
      mountPath: /data
  volumes:
  - name: config
    configMap:
      name: nginx-config
  - name: data
    emptyDir: {}
  # 重启策略
  restartPolicy: Always
  # 优雅终止时间
  terminationGracePeriodSeconds: 30
```

**Pod 生命周期**:

```
Pending → Running → Succeeded (restartPolicy=Never/OnFailure)
                   → Failed    (restartPolicy=Never/OnFailure)
         Running → Terminating → Terminated

Container 状态:
Waiting → Running → Terminated
```

**Pod 状态排查**:

```bash
kubectl describe pod <name>    # 查看 Events
kubectl logs <pod> -c <container> --previous  # 查看崩溃前日志
kubectl get pod <name> -o yaml  # 完整状态
```

### 2. Deployment — 无状态应用

**用途**: 管理 ReplicaSet，支持滚动更新和回滚。

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  labels:
    app: api-server
spec:
  replicas: 3
  # 选择器必须匹配 Pod 模板的标签
  selector:
    matchLabels:
      app: api-server
  # 更新策略
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1          # 滚动更新时最多多出几个 Pod
      maxUnavailable: 0    # 滚动更新时最多几个 Pod 不可用
  # Pod 模板
  template:
    metadata:
      labels:
        app: api-server
        version: v1
    spec:
      containers:
      - name: app
        image: harbor.example.com/app/api:v1.2.3
        ports:
        - containerPort: 8080
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1Gi
  # 保留历史版本数（用于回滚）
  revisionHistoryLimit: 10
```

**Deployment 常用操作**:

```bash
# 查看状态
kubectl rollout status deployment/api-server
kubectl rollout history deployment/api-server

# 更新镜像
kubectl set image deployment/api-server app=xxx:v1.3.0

# 回滚
kubectl rollout undo deployment/api-server          # 回滚到上一个版本
kubectl rollout undo deployment/api-server --to-revision=2

# 暂停/恢复
kubectl rollout pause deployment/api-server
kubectl rollout resume deployment/api-server

# 重启（重新创建所有 Pod）
kubectl rollout restart deployment/api-server

# 缩容/扩容
kubectl scale deployment/api-server --replicas=5
```

### 3. StatefulSet — 有状态应用

**用途**: 数据库、消息队列等需要稳定网络标识和持久存储的应用。

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
spec:
  # 必须指定 Service（Headless Service）
  serviceName: redis-headless
  replicas: 3
  # Pod 管理策略
  podManagementPolicy: OrderedReady  # OrderedReady / Parallel
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        ports:
        - containerPort: 6379
        volumeMounts:
        - name: data
          mountPath: /data
  # 持久卷模板（每个 Pod 独立 PVC）
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: ssd
      resources:
        requests:
          storage: 10Gi
```

**StatefulSet 特性**:

| 特性 | 说明 |
|------|------|
| 稳定网络标识 | Pod 名称: `redis-cluster-0`、`redis-cluster-1`、`redis-cluster-2` |
| 稳定存储 | 每个 Pod 绑定独立的 PVC，Pod 重建后仍挂载同一块盘 |
| 有序部署 | 从 0 到 N-1 依次启动（`OrderedReady`） |
| 有序缩容 | 从 N-1 到 0 依次删除 |
| 滚动更新 | 从 N-1 到 0 依次更新 |

```bash
# 扩容
kubectl scale statefulset redis-cluster --replicas=5

# StatefulSet 不支持 --force 删除 PVC
# 需要手动删除 PVC:
kubectl delete pvc data-redis-cluster-3
```

### 4. DaemonSet — 每个节点运行一个 Pod

**用途**: 日志采集、监控 Agent、网络插件、存储插件。

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluentd
spec:
  selector:
    matchLabels:
      name: fluentd
  template:
    metadata:
      labels:
        name: fluentd
    spec:
      # 容忍所有污点（确保每个节点都运行）
      tolerations:
      - operator: Exists
      containers:
      - name: fluentd
        image: fluentd:v1.16
        resources:
          requests:
            cpu: 100m
            memory: 200Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
```

### 5. ReplicaSet — Pod 副本控制器

通常由 Deployment 自动管理，**不直接创建**。

```yaml
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: frontend
spec:
  replicas: 3
  selector:
    matchLabels:
      app: frontend
  template:
    # ... Pod 模板
```

---

## 三、Service & Networking（服务与网络）

### 1. Service — 服务发现与负载均衡

```yaml
# ClusterIP（默认）— 集群内部访问
apiVersion: v1
kind: Service
metadata:
  name: api-service
spec:
  type: ClusterIP
  selector:
    app: api-server
  ports:
  - name: http
    port: 80          # Service 暴露的端口
    targetPort: 8080  # Pod 上容器的端口
    protocol: TCP
  # 会话亲和性
  sessionAffinity: None  # None / ClientIP

---
# NodePort — 通过节点 IP + 端口暴露
apiVersion: v1
kind: Service
metadata:
  name: api-nodeport
spec:
  type: NodePort
  selector:
    app: api-server
  ports:
  - port: 80
    targetPort: 8080
    nodePort: 30080   # 30000-32767

---
# LoadBalancer — 云厂商负载均衡器
apiVersion: v1
kind: Service
metadata:
  name: api-lb
spec:
  type: LoadBalancer
  selector:
    app: api-server
  ports:
  - port: 443
    targetPort: 8080
  # 外部流量策略
  externalTrafficPolicy: Local  # 保留客户端源 IP

---
# Headless Service — 无 ClusterIP，直接返回 Pod IP
apiVersion: v1
kind: Service
metadata:
  name: db-headless
spec:
  clusterIP: None
  selector:
    app: redis
  ports:
  - port: 6379
```

**Service 类型对比**:

| 类型 | 访问范围 | 场景 |
|------|---------|------|
| ClusterIP | 集群内部 | 微服务间通信 |
| NodePort | 集群外部（nodeIP:port） | 开发/测试 |
| LoadBalancer | 外部 LB | 生产环境 |
| ExternalName | DNS 别名 | 外部服务映射 |
| Headless | Pod IP 直连 | StatefulSet |

### 2. Ingress — HTTP/HTTPS 路由

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: api-service
            port:
              number: 80
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend-service
            port:
              number: 80
```

### 3. NetworkPolicy — 网络隔离

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-network-policy
spec:
  podSelector:
    matchLabels:
      app: api-server
  policyTypes:
  - Ingress
  - Egress
  # 入站规则
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: frontend
    - podSelector:
        matchLabels:
          app: gateway
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 8080
  # 出站规则
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: database
    ports:
    - protocol: TCP
      port: 5432
```

### 4. Endpoints & EndpointSlice

```yaml
# 自动由 Service 管理，通常不需要手动创建
# EndpointSlice 是 Endpoints 的替代品，性能更好
apiVersion: discovery.k8s.io/v1
kind: EndpointSlice
metadata:
  name: api-service-abc
  labels:
    kubernetes.io/service-name: api-service
addressType: IPv4
ports:
- name: http
  port: 8080
  protocol: TCP
endpoints:
- addresses:
  - 10.244.1.5
  - 10.244.2.3
  conditions:
    ready: true
```

---

## 四、Config & Storage（配置与存储）

### 1. ConfigMap — 非敏感配置

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  # 键值对
  app.properties: |
    server.port=8080
    log.level=info
    db.host=postgres-service
  # 单独值
  MAX_CONNECTIONS: "100"
  LOG_LEVEL: "debug"
---
# 使用方式 1: 环境变量
env:
- name: LOG_LEVEL
  valueFrom:
    configMapKeyRef:
      name: app-config
      key: LOG_LEVEL

# 使用方式 2: 全部环境变量
envFrom:
- configMapRef:
    name: app-config

# 使用方式 3: 挂载为文件
volumeMounts:
- name: config
  mountPath: /app/config
volumes:
- name: config
  configMap:
    name: app-config
    items:
    - key: app.properties
      path: application.properties
```

### 2. Secret — 敏感配置

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-secret
type: Opaque  # Opaque / kubernetes.io/tls / kubernetes.io/dockerconfigjson
data:
  # 值必须 base64 编码
  username: YWRtaW4=
  password: cGFzc3dvcmQxMjM=
---
# 使用方式同 ConfigMap
env:
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: db-secret
      key: password

# TLS 证书类型的 Secret
apiVersion: v1
kind: Secret
metadata:
  name: tls-secret
type: kubernetes.io/tls
data:
  tls.crt: <base64-encoded-cert>
  tls.key: <base64-encoded-key>
```

**Secret 类型**:

| 类型 | 用途 |
|------|------|
| `Opaque` | 通用键值对 |
| `kubernetes.io/tls` | TLS 证书 |
| `kubernetes.io/dockerconfigjson` | 镜像仓库认证 |
| `kubernetes.io/basic-auth` | 基础认证 |
| `kubernetes.io/ssh-auth` | SSH 私钥 |

### 3. PersistentVolume (PV) & PersistentVolumeClaim (PVC)

```yaml
# PV — 集群管理员创建
apiVersion: v1
kind: PersistentVolume
metadata:
  name: nfs-pv
spec:
  capacity:
    storage: 100Gi
  accessModes:
  - ReadWriteMany
  persistentVolumeReclaimPolicy: Retain  # Retain / Delete / Recycle
  storageClassName: nfs
  nfs:
    server: 192.168.1.100
    path: /data/nfs

---
# PVC — 用户申请存储
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-pvc
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: ssd
  resources:
    requests:
      storage: 10Gi
  # 选择特定 PV
  selector:
    matchLabels:
      type: ssd

---
# Pod 中使用 PVC
volumes:
- name: data
  persistentVolumeClaim:
    claimName: data-pvc
```

**accessModes 说明**:

| 模式 | 缩写 | 说明 |
|------|------|------|
| ReadWriteOnce | RWO | 单节点读写 |
| ReadOnlyMany | ROX | 多节点只读 |
| ReadWriteMany | RWX | 多节点读写 |
| ReadWriteOncePod | RWOP | 单 Pod 读写 (K8s 1.22+) |

### 4. StorageClass — 动态存储

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ssd
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer  # Immediate / WaitForFirstConsumer
allowVolumeExpansion: true
mountOptions:
- discard
```

---

## 五、RBAC & Security（权限与安全）

### 1. ServiceAccount — Pod 身份

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: api-sa
  namespace: default
---
# Pod 中使用
spec:
  serviceAccountName: api-sa
  # 不自动挂载 API token
  automountServiceAccountToken: false
```

### 2. Role / ClusterRole — 权限定义

```yaml
# 命名空间级别
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: default
  name: pod-reader
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list"]

---
# 集群级别
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-reader
rules:
- apiGroups: [""]
  resources: ["nodes", "nodes/metrics"]
  verbs: ["get", "list", "watch"]
```

### 3. RoleBinding / ClusterRoleBinding — 权限绑定

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: default
subjects:
- kind: ServiceAccount
  name: api-sa
  namespace: default
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

### 4. PodSecurityPolicy / Pod Security Admission

```yaml
# K8s 1.25+ 使用 Pod Security Admission
# 命名空间标签控制
apiVersion: v1
kind: Namespace
metadata:
  name: secure-ns
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: baseline
    pod-security.kubernetes.io/warn: restricted
```

### 5. SecurityContext — 安全上下文

```yaml
# Pod 级别
spec:
  securityContext:
    runAsUser: 1000
    runAsGroup: 3000
    fsGroup: 2000
    runAsNonRoot: true

# 容器级别
containers:
- name: app
  securityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
      - ALL
      add:
      - NET_BIND_SERVICE
    seccompProfile:
      type: RuntimeDefault
```

---

## 六、Autoscaling（弹性伸缩）

### 1. HorizontalPodAutoscaler (HPA)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-server
  minReplicas: 2
  maxReplicas: 20
  metrics:
  # CPU 指标
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  # 内存指标
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
  # 自定义指标
  - type: Pods
    pods:
      metric:
        name: http_requests_per_second
      target:
        type: AverageValue
        averageValue: "1000"
  # 伸缩行为
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300   # 缩容稳定窗口 (5 分钟)
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 60    # 扩容稳定窗口
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15
      - type: Pods
        value: 4
        periodSeconds: 15
      selectPolicy: Max
```

### 2. VerticalPodAutoscaler (VPA)

```yaml
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: api-vpa
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-server
  updatePolicy:
    updateMode: Auto  # Off / Initial / Recreate / Auto
  resourcePolicy:
    containerPolicies:
    - containerName: app
      minAllowed:
        cpu: 100m
        memory: 128Mi
      maxAllowed:
        cpu: 2000m
        memory: 4Gi
```

**HPA vs VPA**:

| 维度 | HPA | VPA |
|------|-----|-----|
| 作用 | 调整 Pod 数量 | 调整 Pod 资源请求/限制 |
| 适用 | 无状态应用 | 所有应用 |
| 副作用 | 无 (水平扩展) | 可能需要重启 Pod |
| 触发 | 实时指标 | 历史资源使用分析 |

### 3. Cluster Autoscaler

```yaml
# 不是 K8s 原生资源，通常通过云厂商或 Karpenter 实现
# 自动调整 Node 数量
```

---

## 七、Scheduling（调度）

### 1. NodeSelector / NodeAffinity — 节点选择

```yaml
# 简单选择器
spec:
  nodeSelector:
    disktype: ssd

# 节点亲和性（更灵活）
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: topology.kubernetes.io/zone
            operator: In
            values:
            - us-east-1a
            - us-east-1b
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 1
        preference:
          matchExpressions:
          - key: instance-type
            operator: In
            values:
            - c5.xlarge
            - c5.2xlarge
```

### 2. PodAffinity / PodAntiAffinity — Pod 间亲和性

```yaml
spec:
  affinity:
    # Pod 亲和性（把 Pod 调度到一起）
    podAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app: redis
        topologyKey: kubernetes.io/hostname
    # Pod 反亲和性（分散 Pod）
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app: api-server
          topologyKey: kubernetes.io/hostname
```

### 3. Taints & Tolerations — 污点与容忍

```bash
# 给节点打污点
kubectl taint nodes node1 key=value:NoSchedule
# NoSchedule / PreferNoSchedule / NoExecute
```

```yaml
# Pod 容忍污点
spec:
  tolerations:
  - key: "key"
    operator: "Equal"
    value: "value"
    effect: "NoSchedule"
  - key: "node.kubernetes.io/not-ready"
    operator: "Exists"
    effect: "NoExecute"
    tolerationSeconds: 300
```

### 4. PriorityClass — 优先级

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
globalDefault: false
description: "用于核心服务"
---
# Pod 中使用
spec:
  priorityClassName: high-priority
```

### 5. TopologySpreadConstraints — 拓扑分布

```yaml
spec:
  topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule  # DoNotSchedule / ScheduleAnyway
    labelSelector:
      matchLabels:
        app: api-server
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        app: api-server
```

---

## 八、Observability（可观测性）

### 1. Events — 事件

```yaml
# 自动生成，记录集群中发生的重要事件
# 查看: kubectl get events --sort-by='.lastTimestamp'
```

### 2. 指标资源 (metrics.k8s.io)

```bash
# 通过 Metrics Server 提供
kubectl top nodes
kubectl top pods
```

### 3. 自定义指标 (custom.metrics.k8s.io)

```yaml
# 通过 Prometheus Adapter 等提供
# 用于 HPA 的自定义指标
```

---

## 九、Batch（批处理）

### 1. Job — 一次性任务

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: data-migration
spec:
  # 最大执行次数
  backoffLimit: 4
  # 完成次数
  completions: 1
  # 并行度
  parallelism: 1
  # 完成后保留时间
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never  # Never / OnFailure
      containers:
      - name: migration
        image: migrate:v1.0
        command: ["python", "migrate.py"]
```

### 2. CronJob — 定时任务

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-backup
spec:
  # Cron 表达式
  schedule: "0 2 * * *"
  # 时区 (K8s 1.27+)
  timeZone: "Asia/Shanghai"
  # 并发策略
  concurrencyPolicy: Forbid  # Allow / Forbid / Replace
  # 历史保留
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  # 启动截止时间
  startingDeadlineSeconds: 300
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: backup
            image: backup-tool:latest
            command: ["/bin/sh", "-c", "backup.sh"]
```

**Cron 表达式**:

```
┌───────────── 分钟 (0-59)
│ ┌───────────── 小时 (0-23)
│ │ ┌───────────── 日 (1-31)
│ │ │ ┌───────────── 月 (1-12)
│ │ │ │ ┌───────────── 星期 (0-6, 0=周日)
│ │ │ │ │
* * * * *
```

---

## 十、Custom Resources（自定义资源）

### 1. CustomResourceDefinition (CRD)

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: backups.example.com
spec:
  group: example.com
  names:
    kind: Backup
    listKind: BackupList
    plural: backups
    singular: backup
    shortNames:
    - bk
  scope: Namespaced  # Namespaced / Cluster
  versions:
  - name: v1
    served: true
    storage: true
    schema:
      openAPIV3Schema:
        type: object
        properties:
          spec:
            type: object
            properties:
              schedule:
                type: string
              target:
                type: string
            required:
            - target
```

### 2. 常见 CRD 生态

| CRD | 所属项目 | 用途 |
|-----|---------|------|
| VirtualService / DestinationRule | Istio | 服务网格 |
| Certificate / Issuer | cert-manager | TLS 证书管理 |
| Prometheus / ServiceMonitor | Prometheus Operator | 监控 |
| Application | ArgoCD | GitOps |
| IngressRoute | Traefik | 高级路由 |
| SealedSecret | Bitnami | 加密 Secret |

---

## 十一、常用命令速查

### 资源查看

```bash
# 查看所有资源类型
kubectl api-resources

# 查看资源详情
kubectl explain pod.spec.containers
kubectl explain deployment --recursive

# 查看资源
kubectl get pods -n <namespace>
kubectl get pods -o wide
kubectl get pods -o yaml
kubectl get pods -o jsonpath='{.items[*].status.podIP}'
kubectl get pods -l app=nginx
kubectl get pods --field-selector status.phase=Running
kubectl get pods --sort-by=.metadata.creationTimestamp

# 查看所有命名空间的资源
kubectl get pods --all-namespaces
kubectl get pods -A  # 简写

# 实时监控
kubectl get pods -w
```

### 资源操作

```bash
# 创建/应用
kubectl apply -f deployment.yaml
kubectl create -f deployment.yaml  # 不可重复执行
kubectl apply -k ./overlays/production  # Kustomize

# 编辑
kubectl edit deployment/api-server
kubectl patch deployment api-server -p '{"spec":{"replicas":5}}'

# 删除
kubectl delete -f deployment.yaml
kubectl delete pod nginx-pod
kubectl delete pod nginx-pod --grace-period=0 --force
kubectl delete pods -l app=nginx

# 日志
kubectl logs <pod>
kubectl logs <pod> -c <container>
kubectl logs <pod> --tail=100
kubectl logs <pod> --since=1h
kubectl logs -f <pod>  # 实时跟踪
kubectl logs <pod> --previous  # 崩溃前日志

# 进入容器
kubectl exec -it <pod> -- /bin/bash
kubectl exec -it <pod> -c <container> -- /bin/sh
kubectl exec <pod> -- ls /app

# 端口转发
kubectl port-forward pod/nginx-pod 8080:80
kubectl port-forward svc/api-service 8080:80

# 复制文件
kubectl cp <pod>:/path/to/file ./local-file
kubectl cp ./local-file <pod>:/path/to/file

# 调试
kubectl debug pod/nginx-pod -it --image=busybox
kubectl run debug --rm -it --image=busybox -- /bin/sh
```

### 资源配置

```bash
# 查看资源使用
kubectl describe deployment/api-server
kubectl describe pod <pod>

# 查看事件
kubectl get events --sort-by='.lastTimestamp'
kubectl get events --field-selector involvedObject.name=nginx-pod

# 查看 API 资源版本
kubectl api-versions

# 查看集群信息
kubectl cluster-info
kubectl version
kubectl config view
```

### 诊断命令

```bash
# Pod 无法启动
kubectl describe pod <pod> | grep -A 10 Events
kubectl get pod <pod> -o jsonpath='{.status.conditions}'

# 检查节点状态
kubectl describe node <node>
kubectl get nodes -o wide

# 检查资源配额
kubectl describe resourcequota
kubectl get resourcequota

# 检查 RBAC 权限
kubectl auth can-i create deployments
kubectl auth can-i get pods --as system:serviceaccount:default:api-sa

# 检查 PVC 状态
kubectl get pvc
kubectl describe pvc data-pvc
```

---

## 附录：YAML 模板速查

### 最小 Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      containers:
      - name: app
        image: nginx:latest
        ports:
        - containerPort: 80
```

### 最小 Service

```yaml
apiVersion: v1
kind: Service
metadata:
  name: my-service
spec:
  selector:
    app: my-app
  ports:
  - port: 80
    targetPort: 80
```

### 最小 Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
spec:
  ingressClassName: nginx
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-service
            port:
              number: 80
```

### 最小 ConfigMap + Secret

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  KEY: value
---
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
stringData:  # 明文输入，自动 base64
  password: mypassword
```

### 最小 PVC

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
```

### 最小 HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### 最小 CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: my-cron
spec:
  schedule: "0 * * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
          - name: task
            image: busybox
            command: ["echo", "hello"]
```