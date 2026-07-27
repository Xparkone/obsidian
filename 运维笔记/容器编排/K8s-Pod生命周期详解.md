# Pod 生命周期深入详解

> 从创建到销毁，完整理解 Pod 的一生  
> 创建时间：2026-07-13

---

## 一、Pod 生命周期全景

```
                         ┌──────────────────────────────────────┐
                         │           Pod 生命周期                │
                         │                                      │
  kubectl apply ──────→  │  Pending  ──→  Running  ──→  Succeeded
                         │     │              │              │
                         │     │              │              │
                         │     └──→ Failed    └──→ Failed    │
                         │                    │              │
                         │                    └──→ Unknown   │
                         └──────────────────────────────────────┘
```

| 阶段 | 含义 | 触发条件 |
|------|------|---------|
| **Pending** | Pod 已被 API Server 接受，但容器尚未创建 | 调度中、拉取镜像、创建容器 |
| **Running** | Pod 已绑定到节点，所有容器已创建，至少一个在运行 | 容器启动成功 |
| **Succeeded** | 所有容器正常终止，且不会重启 | Job/CronJob 完成 |
| **Failed** | 所有容器终止，至少一个以非零状态退出 | 容器崩溃、OOM、退出码非零 |
| **Unknown** | 无法获取 Pod 状态 | 节点失联、kubelet 通信异常 |

---

## 二、Pod 创建全流程（10 个步骤）

```
Step 1: kubectl apply → API Server 验证 + 准入控制
Step 2: API Server 将 Pod 对象写入 etcd（此时 Pod 处于 Pending）
Step 3: Scheduler watch 到未调度的 Pod
Step 4: Scheduler 预选（过滤不合适的节点）→ 优选（打分）→ 绑定节点
Step 5: API Server 更新 Pod 的 nodeName 字段到 etcd
Step 6: 目标节点的 kubelet watch 到分配给自己的 Pod
Step 7: kubelet 调用 CRI（容器运行时）创建容器
Step 8: kubelet 调用 CNI（网络插件）分配 IP、配置网络
Step 9: kubelet 启动探针检查（startup → liveness → readiness）
Step 10: Pod 状态变为 Running
```

### 各步骤可能卡住的原因

| 步骤 | 卡住表现 | 常见原因 |
|:---:|---------|---------|
| 1-2 | 请求被拒 | RBAC 权限不足、资源配额超限、准入 Webhook 拒绝 |
| 3-4 | Pending 状态 | 资源不足、节点选择器不匹配、污点未容忍、PVC 未绑定 |
| 5-6 | Pending 状态 | 节点失联、kubelet 异常 |
| 7 | Pending/ContainerCreating | 镜像拉取失败（ImagePullBackOff）、镜像太大 |
| 8 | ContainerCreating | CNI 插件异常、IP 耗尽 |
| 9-10 | Running 但 NotReady | 探针失败 |

---

## 三、Pod 内部容器状态

一个 Pod 可以有多个容器，每个容器独立管理状态：

```
Pod
├── Init 容器（按顺序执行，所有完成后退出）
│   ├── init-db-check     (等待数据库就绪)
│   └── init-migration    (执行数据库迁移)
│
├── 主容器（并行运行）
│   ├── app               (业务容器)
│   └── sidecar-proxy     (Sidecar 代理，如 Envoy)
│
└── 临时容器（Ephemeral Container，调试用）
    └── debug             (kubectl debug 创建)
```

### 容器状态

| 状态 | 含义 |
|------|------|
| **Waiting** | 正在拉取镜像、等待依赖等 |
| **Running** | 容器正在运行（但不一定健康） |
| **Terminated** | 容器已退出，包含退出码和原因 |

---

## 四、Init 容器

### 4.1 特性

```
┌──────────────────────────────────────────────┐
│  Init 1         Init 2        主容器         │
│  ┌──────┐      ┌──────┐      ┌──────┐       │
│  │ 等DB │ ───→ │ 迁移 │ ───→ │ App  │       │
│  └──────┘      └──────┘      └──────┘       │
│  串行执行       串行执行       并行运行       │
│  失败重试       失败重试       持续运行       │
└──────────────────────────────────────────────┘
```

- **串行执行**：前一个 Init 容器成功退出后才启动下一个
- **失败重试**：Init 容器失败会根据 restartPolicy 重试
- **所有 Init 容器必须成功**，主容器才会启动
- 可以使用与主容器不同的镜像和工具

### 4.2 典型场景

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-init
spec:
  initContainers:
  # Init 1: 等待依赖服务就绪
  - name: wait-for-db
    image: busybox:1.36
    command: ['sh', '-c', 'until nc -z db-service 5432; do sleep 2; done']
  
  # Init 2: 执行数据库迁移
  - name: db-migrate
    image: myapp-migrate:latest
    command: ['./migrate']
  
  containers:
  - name: app
    image: myapp:latest
    ports:
    - containerPort: 8080
```

---

## 五、容器探针（Probes）

### 5.1 三种探针对比

| 探针 | 用途 | 失败后果 | 典型场景 |
|------|------|---------|---------|
| **startupProbe** | 判断容器是否已启动完成 | 重启容器 | 启动慢的应用（如 Java） |
| **livenessProbe** | 判断容器是否存活 | **重启容器** | 死锁、内存泄漏导致假死 |
| **readinessProbe** | 判断容器是否准备好接收流量 | **从 Service 移除** | 预热、依赖未就绪 |

### 5.2 探测方式

| 方式 | 说明 | 适用场景 |
|------|------|---------|
| **exec** | 在容器内执行命令，退出码 0 表示成功 | 自定义健康检查脚本 |
| **httpGet** | HTTP GET 请求，2xx/3xx 表示成功 | Web 应用 |
| **tcpSocket** | TCP 端口是否可连接 | 数据库、消息队列 |
| **gRPC** | gRPC 健康检查协议（K8s 1.24+） | gRPC 服务 |

### 5.3 配置示例

```yaml
containers:
- name: java-app
  image: java-app:latest
  ports:
  - containerPort: 8080
  
  # 启动探针：给 Java 应用足够的启动时间
  startupProbe:
    httpGet:
      path: /health
      port: 8080
    initialDelaySeconds: 0      # 启动后立即开始检查
    periodSeconds: 5             # 每 5 秒检查一次
    failureThreshold: 30        # 最多失败 30 次（即 150 秒）
    # 作用：startup 成功之前，liveness 和 readiness 不会执行
  
  # 存活探针：检测应用是否假死
  livenessProbe:
    httpGet:
      path: /health
      port: 8080
    initialDelaySeconds: 0      # startup 成功后立即生效
    periodSeconds: 15            # 每 15 秒检查一次
    failureThreshold: 3         # 连续失败 3 次→重启容器
    timeoutSeconds: 5           # 超时 5 秒算失败
  
  # 就绪探针：检测是否可接收流量
  readinessProbe:
    httpGet:
      path: /ready
      port: 8080
    periodSeconds: 10
    failureThreshold: 3         # 连续失败 3 次→从 Service 摘除
    successThreshold: 1         # 成功 1 次→重新加入 Service
```

### 5.4 探针配置最佳实践

```
           startupProbe
          ┌────────────┐
          │ 最多等待    │
          │ N × T 秒   │◀── 覆盖应用最长启动时间
          └─────┬──────┘
                │ startup 成功
                ▼
     ┌──────────┴──────────┐
     │                     │
     ▼                     ▼
  livenessProbe        readinessProbe
  ┌────────────┐       ┌────────────┐
  │ 轻量检查    │       │ 检查依赖    │
  │ 快速响应    │       │ 可稍重      │
  │ 失败→重启   │       │ 失败→摘流   │
  └────────────┘       └────────────┘
```

| 建议 | 说明 |
|------|------|
| **有 startupProbe 时，liveness 和 readiness 的 initialDelaySeconds 设 0** | startup 接管了启动等待 |
| **liveness 检查要轻量** | 不要查数据库，用简单的 HTTP 端点或命令 |
| **readiness 可以检查依赖** | 如数据库连接、缓存预热状态 |
| **failureThreshold × periodSeconds > 最长启动时间** | startupProbe 的阈值要覆盖启动时间 |
| **不要用 liveness 探测外部依赖** | 否则依赖故障会导致所有 Pod 重启（雪崩） |

---

## 六、容器重启策略（restartPolicy）

| 策略 | 行为 | 适用场景 |
|------|------|---------|
| **Always**（默认） | 容器退出后总是重启 | 长期运行的服务（Deployment、StatefulSet） |
| **OnFailure** | 仅非零退出码时重启 | Job、CronJob |
| **Never** | 从不重启 | 一次性任务 |

```yaml
spec:
  restartPolicy: OnFailure  # 默认是 Always
  containers:
  - name: batch-job
    image: batch:latest
```

### 重启退避策略（Backoff）

```
容器崩溃后重启的间隔：
  立即 → 10s → 20s → 40s → 80s → ... → 最大 5 分钟

kubelet 会在 10 分钟达到上限后重置计数器
```

---

## 七、Pod 终止流程

```
kubectl delete pod xxx
        │
        ▼
Step 1: API Server 将 Pod 标记为 Terminating
        │
        │  Pod 进入 Terminating 状态，同时：
        │  ├── 从 Service Endpoints 移除（停止接收新流量）
        │  └── 触发 preStop hook
        │
        ▼
Step 2: kubelet 发送 SIGTERM 信号给容器主进程
        │
        │  ┌─ 宽限期（terminationGracePeriodSeconds，默认 30s）
        │  │  应用在这段时间内：
        │  │  ├── 关闭新连接
        │  │  ├── 完成正在处理的请求
        │  │  └── 清理资源
        │  └────────────────────────────────
        │
        ▼
Step 3: 宽限期过后，发送 SIGKILL 强制终止
        │
        ▼
Step 4: API Server 从 etcd 删除 Pod 对象
```

### 优雅终止配置

```yaml
spec:
  terminationGracePeriodSeconds: 60  # 宽限期 60 秒（默认 30）
  containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command: 
          - /bin/sh
          - -c
          - |
            # 1. 通知负载均衡摘除自己
            curl -X POST http://localhost:8080/drain
            # 2. 等待正在处理的请求完成
            sleep 15
```

### 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| Pod 删除卡在 Terminating | 应用不响应 SIGTERM | 检查应用是否捕获信号，加 preStop hook |
| 请求丢失 | 摘除和终止有竞态 | preStop 中 sleep 等负载均衡更新 |
| 强制删除 | `kubectl delete pod --force --grace-period=0` | 跳过优雅终止，数据可能丢失 |

---

## 八、Pod QoS（服务质量等级）

K8s 根据资源的 requests/limits 配置将 Pod 分为三个等级：

```
                    OOM 优先级（低 → 高，数字越小越先被杀）
                    
  BestEffort ──────── Burstable ──────── Guaranteed
  (最先被杀)                                (最后被杀)
```

| 等级 | 条件 | 被杀优先级 |
|------|------|:---:|
| **Guaranteed** | 每个容器都设置了 CPU 和内存的 request = limit | 最低 |
| **Burstable** | 至少一个容器设置了 request，但不符合 Guaranteed | 中等 |
| **BestEffort** | 没有任何容器设置 request 和 limit | 最高 |

```yaml
# Guaranteed
spec:
  containers:
  - name: app
    resources:
      requests:
        cpu: "500m"
        memory: "512Mi"
      limits:
        cpu: "500m"      # request == limit
        memory: "512Mi"   # request == limit

# Burstable
spec:
  containers:
  - name: app
    resources:
      requests:
        memory: "256Mi"   # 有 request
      limits:
        memory: "512Mi"   # 但 request ≠ limit

# BestEffort（不设置任何 resources）
spec:
  containers:
  - name: app
    # 没有 resources 字段
```

---

## 九、常见故障排查

| 现象 | 排查思路 |
|------|---------|
| **Pending** | `kubectl describe pod` 查看 Events → 是否资源不足、节点选择器、PVC 未绑定 |
| **ImagePullBackOff** | 镜像名拼写错误、私有仓库未配置 Secret、网络不通 |
| **CrashLoopBackOff** | 容器启动后立即退出 → `kubectl logs` 查看启动日志、检查命令是否正确 |
| **OOMKilled** | 超出内存 limit → 增加内存 limit 或排查内存泄漏 |
| **Running 但 NotReady** | readinessProbe 失败 → `kubectl describe pod` 查看探针失败原因 |
| **Terminating 卡住** | 应用不响应 SIGTERM → 检查 preStop hook、`kubectl delete --force` |
| **Evicted** | 磁盘压力、内存压力导致驱逐 → 检查节点资源 |

---

## 十、速查命令

```bash
# 查看 Pod 状态
kubectl get pods -o wide
kubectl describe pod <pod-name>          # 重点看 Events 部分

# 查看容器日志
kubectl logs <pod-name>                  # 当前容器
kubectl logs <pod-name> -c <container>   # 指定容器
kubectl logs <pod-name> --previous       # 上一个退出的容器（排查崩溃）

# 进入容器调试
kubectl exec -it <pod-name> -- /bin/sh
kubectl exec -it <pod-name> -c <container> -- /bin/sh

# 临时调试容器（K8s 1.23+）
kubectl debug <pod-name> -it --image=busybox --target=<container>

# 查看 Pod 退出原因
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState}'

# 强制删除卡住的 Pod
kubectl delete pod <pod-name> --force --grace-period=0
```

---

## 十一、关键要点

1. **理解 Pod 创建全流程**，出问题时能快速定位卡在哪个步骤
2. **startupProbe + livenessProbe + readinessProbe 三件套**，缺一不可
3. **liveness 不要探测外部依赖**，否则依赖故障会导致雪崩重启
4. **优雅终止**：preStop hook + 合理的 terminationGracePeriodSeconds
5. **生产环境必须设置 resources**，至少设置 request，避免变成 BestEffort 被优先驱逐