# RBAC 详解 — 基于角色的访问控制

## 概述

RBAC（Role-Based Access Control，基于角色的访问控制）是一种权限管理模型，核心思想是：**不直接把权限赋给用户，而是把权限赋给角色，再把角色赋给用户**。

```
传统方式：用户 → 权限（每个用户单独配，管理爆炸）
RBAC：    用户 → 角色 → 权限（统一管理角色，用户只关联角色）
```

---

## 一、核心概念

### 1.1 三个基本实体

```
┌──────────┐       ┌──────────┐       ┌──────────┐
│  Subject  │──────▶│   Role   │──────▶│Permission│
│  (主体)   │ 属于  │  (角色)  │ 拥有  │  (权限)  │
└──────────┘       └──────────┘       └──────────┘
   用户/进程           抽象层            具体操作
```

| 实体 | 说明 | 示例 |
|------|------|------|
| **Subject（主体）** | 谁想操作 | 用户、ServiceAccount、进程 |
| **Role（角色）** | 能做什么的集合 | admin、developer、viewer |
| **Permission（权限）** | 对什么资源做什么操作 | 读 Pod、创建 Deployment |

### 1.2 数学模型

```
RBAC 的核心关系：

Subject ←→ Role（多对多）：一个用户可以有多个角色，一个角色可赋给多个用户
Role ←→ Permission（多对多）：一个角色有多项权限，一项权限可属于多个角色

形成了两个多对多关系，中间通过「角色」解耦
```

---

## 二、RBAC 解决了什么问题

### 没有 RBAC 的世界

```
场景：公司有 100 个微服务，每个服务需要访问 3 个不同的 K8s 资源

管理员：
  "Service-A 可以读 Pod、写 ConfigMap、读 Secret"
  "Service-B 可以读 Pod、读 Service、写 Deployment"
  ... × 100 个服务

每个服务的权限都要单独配置，改一个权限要改 100 个地方
```

### 有 RBAC 的世界

```
管理员先定义角色：
  - reader：读 Pod、读 Service、读 ConfigMap
  - writer：写 Deployment、写 ConfigMap
  - secret-reader：读 Secret

然后给服务分配角色：
  Service-A → reader + secret-reader
  Service-B → reader + writer

改 reader 权限只需改一次，所有关联服务自动生效
```

---

## 三、Kubernetes RBAC 详解

K8s 是 RBAC 最典型的应用场景，理解它就理解了 RBAC 的全部。

### 3.1 资源定义

K8s RBAC 有四种 API 资源：

```
┌──────────────────────────────────────────────────────────┐
│                    K8s RBAC 资源                          │
│                                                           │
│  ┌────────────┐    ┌──────────────┐                      │
│  │   Role     │    │ClusterRole   │  ← 定义「能做什么」   │
│  │ (命名空间级) │    │  (集群级)    │                      │
│  └─────┬──────┘    └──────┬───────┘                      │
│        │                  │                               │
│        ▼                  ▼                               │
│  ┌────────────┐    ┌──────────────┐                      │
│  │RoleBinding │    │ClusterRole   │  ← 绑定「谁能做」     │
│  │(命名空间级) │    │  Binding     │                      │
│  └────────────┘    └──────────────┘                      │
└──────────────────────────────────────────────────────────┘
```

| 资源 | 作用范围 | 说明 |
|------|:--:|------|
| **Role** | 命名空间 | 定义在某个 namespace 内的权限 |
| **ClusterRole** | 集群 | 定义集群级别的权限（Node、PV、Namespace 等） |
| **RoleBinding** | 命名空间 | 把 Role 绑定到用户/ServiceAccount |
| **ClusterRoleBinding** | 集群 | 把 ClusterRole 绑定到用户/ServiceAccount |

### 3.2 权限定义（Role / ClusterRole）

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: default          # 只在 default 命名空间生效
  name: pod-reader
rules:
- apiGroups: [""]             # 核心 API 组（空字符串）
  resources: ["pods"]         # 资源类型
  verbs: ["get", "watch", "list"]  # 允许的操作
```

**verbs 常用值：**

| verb | 含义 |
|------|------|
| **get** | 查看单个资源 |
| **list** | 列出所有资源 |
| **watch** | 监听资源变化 |
| **create** | 创建资源 |
| **update** | 更新资源 |
| **patch** | 部分更新 |
| **delete** | 删除资源 |
| **deletecollection** | 批量删除 |
| **\*** | 所有操作 |

### 3.3 绑定（RoleBinding / ClusterRoleBinding）

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: default
subjects:                     # 授权给谁
- kind: ServiceAccount
  name: my-app-sa
  namespace: default
roleRef:                      # 引用哪个角色
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

### 3.4 完整示例

**场景：给 CI/CD 服务只读权限，只能看 Pod 和日志**

```yaml
# 1. 创建 ServiceAccount（服务账号）
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ci-reader
  namespace: default

---
# 2. 定义 Role（能做什么）
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-reader-role
  namespace: default
rules:
- apiGroups: [""]
  resources: ["pods", "pods/log"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["services", "configmaps"]
  verbs: ["get", "list"]

---
# 3. 绑定（谁能做）
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-reader-binding
  namespace: default
subjects:
- kind: ServiceAccount
  name: ci-reader
  namespace: default
roleRef:
  kind: Role
  name: ci-reader-role
  apiGroup: rbac.authorization.k8s.io
```

### 3.5 ClusterRole 示例

**场景：给监控服务读取所有 namespace 的 Pod 和 Node 信息**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring-reader
rules:
- apiGroups: [""]
  resources: ["pods", "nodes", "services", "endpoints"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["nodes/metrics"]    # 集群级资源，只能用 ClusterRole
  verbs: ["get"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: monitoring-reader-binding
subjects:
- kind: ServiceAccount
  name: prometheus-sa
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: monitoring-reader
  apiGroup: rbac.authorization.k8s.io
```

---

## 四、API Groups 和 Resources 对照表

| API Group | Resources | 说明 |
|-----------|-----------|------|
| `""`（核心组） | pods, services, nodes, configmaps, secrets, namespaces, pvc, endpoints | 基础资源 |
| `apps` | deployments, statefulsets, daemonsets, replicasets | 工作负载 |
| `batch` | jobs, cronjobs | 批处理任务 |
| `networking.k8s.io` | ingresses, networkpolicies | 网络 |
| `rbac.authorization.k8s.io` | roles, rolebindings, clusterroles, clusterrolebindings | RBAC 自身 |
| `apiextensions.k8s.io` | customresourcedefinitions | CRD |
| `policy` | poddisruptionbudgets | 策略 |

---

## 五、常见 RBAC 模式

### 5.1 最小权限原则（Least Privilege）

```yaml
# ❌ 坏做法：给 cluster-admin
kind: ClusterRoleBinding
roleRef:
  name: cluster-admin     # 等于给了 root 权限

# ✅ 好做法：只给需要的权限
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]   # 只能读，不能写
```

### 5.2 按角色分层

```
┌──────────────────────────────────────────────┐
│  cluster-admin          ← 集群管理员（全部权限）│
│    ├── namespace-admin  ← 命名空间管理员       │
│    │   ├── developer    ← 开发（读写工作负载）  │
│    │   └── viewer       ← 只读               │
│    └── monitoring       ← 监控（只读所有资源）  │
└──────────────────────────────────────────────┘
```

### 5.3 聚合 ClusterRole（Aggregated）

```yaml
# 通过标签自动聚合多个 ClusterRole 的权限
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: monitoring
  labels:
    rbac.authorization.k8s.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]

---
# 另一个 ClusterRole 也打上同样的标签
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-monitoring
  labels:
    rbac.authorization.k8s.io/aggregate-to-monitoring: "true"
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]

# 结果：monitoring ClusterRole 自动聚合了 pods + nodes 的权限
```

---

## 六、查看和调试 RBAC

```bash
# 查看当前用户能做什么
kubectl auth can-i create deployments
kubectl auth can-i delete pods --as=system:serviceaccount:default:ci-reader

# 查看某个 ServiceAccount 的权限
kubectl auth can-i --list --as=system:serviceaccount:default:ci-reader

# 查看所有 Role
kubectl get roles --all-namespaces

# 查看所有 ClusterRole
kubectl get clusterroles

# 查看 RoleBinding
kubectl get rolebindings --all-namespaces

# 查看某个 Role 的详细权限
kubectl describe role pod-reader -n default

# 查看谁绑定了某个 ClusterRole
kubectl get clusterrolebindings -o wide
```

---

## 七、那篇海外方案中的 RBAC 分析

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gitlab-runner
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin          # ⚠️ 最大权限！
subjects:
- kind: ServiceAccount
  name: default
  namespace: gitlab
```

**这段配置的含义：**

> 把 `cluster-admin`（K8s 最高权限，相当于 root）赋给了 `gitlab` 命名空间下的 `default` ServiceAccount。

**为什么这么做？**

GitLab Runner 的 K8s Executor 需要动态创建/删除 Job Pod，操作 PVC、Secret 等资源。直接给 `cluster-admin` 最简单粗暴，但安全风险大。

**更好的做法（最小权限）：**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: gitlab-runner-role
rules:
- apiGroups: [""]
  resources: ["pods", "pods/exec", "pods/attach", "pods/log", "secrets", "services", "configmaps"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  verbs: ["get", "list", "create", "delete"]
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["get", "list", "create", "delete"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gitlab-runner-binding
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: gitlab-runner-role
subjects:
- kind: ServiceAccount
  name: default
  namespace: gitlab
```

---

## 八、总结

```
RBAC 的核心公式：

  Subject（用户/SA） + Role（角色） + Binding（绑定） = 权限

三个关键原则：
  1. 最小权限：只给完成任务所需的最小权限，别给 cluster-admin
  2. 角色抽象：相同权限打包成角色，不要给每个用户单独配置
  3. 命名空间隔离：能用 Role + RoleBinding 就别用 ClusterRole（作用范围更小更安全）
```

---

*文档创建时间：2026-07-02*