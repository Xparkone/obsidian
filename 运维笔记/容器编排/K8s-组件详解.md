# Kubernetes（K8s）核心组件详解

> 文档版本：v1.0 | 更新日期：2026-06-24

---

## 一、K8s 架构总览

Kubernetes 集群由两类节点组成，每个节点上运行着不同的核心组件：

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Control Plane（控制平面）                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │  API     │  │  etcd    │  │  Controller  │  │  Scheduler   │   │
│  │  Server  │  │          │  │  Manager     │  │              │   │
│  └──────────┘  └──────────┘  └──────────────┘  └──────────────┘   │
│                            ┌──────────┐                             │
│                            │  Cloud   │                             │
│                            │  CCM     │                             │
│                            └──────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              │  kubelet / kube-proxy
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Worker Node（工作节点）                      │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐                  │
│  │  kubelet │  │  kube-proxy  │  │  Container   │                  │
│  │          │  │              │  │  Runtime     │                  │
│  └──────────┘  └──────────────┘  └──────────────┘                  │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                         │
│  │  Pod A   │  │  Pod B   │  │  Pod C   │  ...                    │
│  └──────────┘  └──────────┘  └──────────┘                         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、Control Plane（控制平面）组件

控制平面负责集群的全局决策（调度）以及检测和响应集群事件。

### 1. kube-apiserver（API 服务器）

| 属性 | 说明 |
|------|------|
| **作用** | 集群的**统一入口**，所有操作都通过它进行 |
| **核心功能** | RESTful API 暴露、认证授权、请求校验、数据持久化到 etcd |
| **通信方式** | 所有组件（kubectl、kubelet、controller-manager 等）都通过它通信 |
| **关键端口** | 默认 6443（HTTPS） |

**工作流程**：
```
kubectl → kube-apiserver → etcd（读写）
kubelet → kube-apiserver → 上报节点状态
Controller → kube-apiserver → Watch 资源变化
```

**高可用**：可横向扩展，前面加 Load Balancer。

---

### 2. etcd（键值存储）

| 属性 | 说明 |
|------|------|
| **作用** | 集群的**唯一数据源**（Source of Truth），所有配置和状态数据存储在这里 |
| **技术栈** | CoreOS 开发的分布式 KV 存储，基于 **Raft 共识算法** |
| **存储内容** | 所有 K8s 资源对象（Pod、Service、Deployment、ConfigMap 等） |
| **关键端口** | 2379（客户端）、2380（Peer 通信） |

**关键特性**：
- 强一致性（CP 系统）
- 高可用要求奇数节点（3/5/7）
- 数据变更通过 **Watch 机制** 通知订阅者
- 生产环境需要定期备份（`etcdctl snapshot save`）

---

### 3. kube-controller-manager（控制器管理器）

| 属性 | 说明 |
|------|------|
| **作用** | 运行多个**控制器**，每个控制器负责将集群从「当前状态」驱动到「期望状态」 |
| **运行方式** | 所有控制器编译为单一二进制，在一个进程中运行 |

**内置控制器列表**：

| 控制器 | 职责 |
|--------|------|
| **Node Controller** | 监控节点健康状态，节点不可达时驱逐 Pod |
| **Replication Controller** | 确保 Pod 副本数符合期望值 |
| **Deployment Controller** | 管理 Deployment 的滚动更新和回滚 |
| **StatefulSet Controller** | 管理有状态应用（有序启动/停止、持久化标识） |
| **DaemonSet Controller** | 确保每个节点运行一个 Pod 副本 |
| **Job Controller** | 管理一次性任务（Job/CronJob） |
| **EndpointSlice Controller** | 为 Service 创建 Endpoint 对象 |
| **ServiceAccount Controller** | 为 Namespace 创建默认 ServiceAccount |
| **Namespace Controller** | 管理 Namespace 生命周期 |
| **PV/PVC Controller** | 绑定 PersistentVolume 和 PersistentVolumeClaim |
| **Garbage Collector** | 清理被删除资源的关联对象 |

**核心机制**：每个控制器都是一个 **控制循环**：
```
for {
    期望状态 = 从 API Server 获取
    当前状态 = 从 API Server 获取
    if 期望状态 != 当前状态 {
        执行操作，使当前状态 → 期望状态
    }
}
```

---

### 4. kube-scheduler（调度器）

| 属性 | 说明 |
|------|------|
| **作用** | 将新创建的 Pod **分配到合适的节点**上运行 |
| **决策依据** | 资源需求、亲和性/反亲和性规则、污点容忍、数据局部性等 |

**调度流程**：

```
1. 过滤（Filtering / Predicates）
   └─ 筛选出满足 Pod 运行条件的节点（资源足够、端口可用、污点容忍等）

2. 打分（Scoring / Priorities）
   └─ 对候选节点打分排序（资源均衡度、亲和性匹配、镜像本地性等）

3. 绑定（Binding）
   └─ 选择得分最高的节点，将 Pod 绑定到该节点
```

**常用调度策略**：
- `nodeSelector`：简单节点标签选择
- `nodeAffinity`：节点亲和性（硬/软限制）
- `podAffinity / podAntiAffinity`：Pod 间亲和/反亲和
- `Taints & Tolerations`：污点与容忍
- `TopologySpreadConstraints`：跨拓扑域均匀分布

---

### 5. cloud-controller-manager（云控制器管理器）

| 属性 | 说明 |
|------|------|
| **作用** | 将 K8s 与**云厂商 API** 集成，处理云特定逻辑 |
| **适用场景** | 运行在公有云上（AWS、GCP、Azure、阿里云等） |

**内置云控制器**：

| 控制器 | 职责 |
|--------|------|
| **Node Controller** | 检查云厂商的节点状态（删除已不存在的节点） |
| **Route Controller** | 配置云厂商的路由表（VPC 路由） |
| **Service Controller** | 创建/更新/删除云厂商的 LoadBalancer |
| **Volume Controller** | 创建/挂载云存储卷 |

---

## 三、Node（工作节点）组件

每个工作节点上都运行着以下组件，负责维护 Pod 并为其提供运行时环境。

### 1. kubelet（节点代理）

| 属性 | 说明 |
|------|------|
| **作用** | 节点上的**核心代理**，确保容器按 PodSpec 运行 |
| **注册位置** | 向 API Server 注册节点 |
| **关键端口** | 10250（HTTPS）、10255（HTTP，只读） |

**核心职责**：
- 接收 API Server 分配的 PodSpec
- 调用 Container Runtime 启动/停止容器
- 上报 Pod 和节点状态
- 执行存活探针（Liveness Probe）和就绪探针（Readiness Probe）
- 管理节点上的 Volume 挂载
- 回收节点资源（镜像垃圾回收、容器垃圾回收）

**关键机制**：
```
kubelet 不直接管理自己创建的容器，只管理 API Server 分配给它的 Pod。
```

---

### 2. kube-proxy（网络代理）

| 属性 | 说明 |
|------|------|
| **作用** | 在每个节点上实现**Service 的网络代理**，维护网络规则 |
| **运行位置** | 每个节点一个实例（DaemonSet 或静态 Pod） |

**三种代理模式**：

| 模式 | 原理 | 性能 | 状态 |
|------|------|------|------|
| **iptables** | Linux netfilter 规则，随机负载均衡 | 中等 | 默认（传统） |
| **ipvs** | Linux IPVS 内核模块，支持多种调度算法（rr/lc/dh/sh 等） | 高 | 推荐 |
| **userspace** | 用户态代理，每个请求经 kube-proxy 转发 | 低 | 已废弃 |

**工作流程**：
```
Service: ClusterIP 10.96.0.1:80
         │
         ├── Endpoint Pod A (10.244.1.5:8080)
         ├── Endpoint Pod B (10.244.2.6:8080)
         └── Endpoint Pod C (10.244.1.7:8080)

kube-proxy → 写入 iptables/ipvs 规则 → 将 ClusterIP 流量分发到后端 Pod
```

---

### 3. Container Runtime（容器运行时）

| 属性 | 说明 |
|------|------|
| **作用** | 负责**实际运行容器**的软件 |
| **接口** | 通过 **CRI（Container Runtime Interface）** 与 kubelet 对接 |

**常见运行时**：

| 运行时 | 说明 |
|--------|------|
| **containerd** | CNCF 毕业项目，K8s 默认推荐，轻量高效 |
| **CRI-O** | 专为 K8s 设计的轻量级运行时 |
| **Docker Engine** | 早期默认，K8s 1.24+ 已移除 dockershim 支持 |
| **Kata Containers** | 虚拟机级容器隔离，安全优先 |
| **gVisor** | 用户态内核沙箱，Google 出品 |

---

## 四、Add-on（附加组件）

这些组件不是 K8s 核心，但生产集群几乎必备。

### 1. 网络插件（CNI）

| 组件 | 说明 |
|------|------|
| **Calico** | 基于 BGP，高性能，支持 NetworkPolicy |
| **Flannel** | 简单 overlay 网络（VXLAN/host-gw），入门首选 |
| **Cilium** | 基于 eBPF，高性能 + 可观测性 + 安全 |
| **Weave Net** | 自动发现、加密通信 |

**核心职责**：实现 Pod 跨节点通信，分配 Pod IP 子网。

---

### 2. CoreDNS（服务发现/DNS）

| 属性 | 说明 |
|------|------|
| **作用** | 集群内 **DNS 服务**，为 Service 和 Pod 提供名称解析 |
| **部署方式** | 通常以 Deployment 运行，Service 暴露 ClusterIP |

**DNS 记录格式**：
```
<service-name>.<namespace>.svc.cluster.local
# 示例：my-app.default.svc.cluster.local → 10.96.0.1
```

---

### 3. Ingress Controller（入口控制器）

| 组件 | 说明 |
|------|------|
| **Nginx Ingress** | 最流行，基于 Nginx |
| **Traefik** | 自动发现，支持中间件链 |
| **Istio Gateway** | 服务网格的一部分 |
| **Kong** | API 网关，插件丰富 |
| **HAProxy Ingress** | 高性能 |

**核心职责**：将外部 HTTP/HTTPS 流量路由到集群内 Service，提供 TLS 终止、路径路由、域名虚拟主机等功能。

---

### 4. 仪表盘与监控

| 组件 | 说明 |
|------|------|
| **Kubernetes Dashboard** | 官方 Web UI |
| **Prometheus + Grafana** | 监控告警，K8s 事实标准 |
| **Metrics Server** | 资源指标聚合（HPA 依赖） |
| **ELK / Loki** | 日志收集与查询 |

---

### 5. 存储插件（CSI）

| 组件 | 说明 |
|------|------|
| **NFS CSI** | 基于 NFS 的持久化存储 |
| **Ceph CSI（Rook）** | 分布式块/文件/对象存储 |
| **Longhorn** | 轻量级分布式块存储（Rancher 出品） |
| **Local Path** | 本地路径存储，单节点或开发环境 |

---

## 五、组件通信流程

### Pod 创建完整流程

```
1. kubectl 发送创建请求
   └─→ 2. kube-apiserver 认证/授权/校验
        └─→ 3. 写入 etcd，返回已创建（Pending 状态）
             └─→ 4. kube-scheduler Watch 到未绑定 Pod
                  └─→ 5. 调度算法选择最优节点
                       └─→ 6. 更新 Pod 绑定节点（写入 etcd）
                            └─→ 7. 目标节点 kubelet Watch 到分配给自己的 Pod
                                 └─→ 8. kubelet 调用 CRI 创建容器
                                      └─→ 9. kubelet 上报 Pod 状态（Running）
                                           └─→ 10. kube-proxy 更新网络规则
```

---

## 六、各组件端口汇总

| 组件 | 端口 | 协议 | 用途 |
|------|------|------|------|
| kube-apiserver | 6443 | HTTPS | API 入口 |
| etcd | 2379 | HTTP | 客户端通信 |
| etcd | 2380 | HTTP | Peer 通信 |
| kubelet | 10250 | HTTPS | API（含 exec/logs） |
| kubelet | 10255 | HTTP | 只读（已弃用） |
| kube-scheduler | 10259 | HTTPS | 调度器健康检查 |
| kube-controller-manager | 10257 | HTTPS | 控制器健康检查 |
| kube-proxy | 10256 | HTTP | 健康检查 |
| CoreDNS | 53 | UDP | DNS 查询 |
| NodePort 范围 | 30000-32767 | TCP/UDP | Service NodePort |

---

## 七、生产环境部署建议

| 组件 | 建议 |
|------|------|
| **etcd** | 3 或 5 节点，SSD 磁盘，独立部署，定期备份 |
| **kube-apiserver** | 3 节点 + LB，启用审计日志 |
| **Controller Manager / Scheduler** | 3 节点，Leader Election 自动选主 |
| **kubelet** | 开启 `--protect-kernel-defaults` 保护内核参数 |
| **CNI** | 生产环境推荐 Calico 或 Cilium |
| **DNS** | CoreDNS 至少 2 副本，配置 `autopath` 缓存 |
| **监控** | Prometheus + Grafana + Alertmanager 不可少 |
| **日志** | EFK/Loki 集中式日志，避免 `kubectl logs` 单点排查 |

---

## 八、kubectl 常见与不常见命令总结

> 按使用频率和场景分级，从日常用到高级排查全覆盖。

### 8.1 常见命令（每日必用）

#### 资源查看（get / describe）

```bash
# 基础查询
kubectl get pods                                    # 当前 namespace 的 Pod
kubectl get pods -A                                 # 所有 namespace 的 Pod
kubectl get pods -o wide                            # 含节点 IP、容器 IP
kubectl get pods -n kube-system                     # 指定 namespace
kubectl get pods -l app=nginx                       # 按标签筛选
kubectl get pods --field-selector status.phase=Running  # 按字段筛选

# 查看各类资源
kubectl get deploy,svc,cm,secret,ingress,pv,pvc     # 一次查看多种资源
kubectl get all                                      # 所有常见资源（不是真正全部）
kubectl get nodes                                    # 节点列表
kubectl get ns                                       # namespace 列表
kubectl get events --sort-by='.lastTimestamp'        # 集群事件（按时间排序）

# 输出格式
kubectl get pods -o yaml                             # YAML 格式
kubectl get pods -o json | jq '.'                    # JSON 格式
kubectl get pods -o jsonpath='{.items[*].status.podIP}'  # jsonpath 提取字段
kubectl get pods -o custom-columns=NAME:.metadata.name,IP:.status.podIP  # 自定义列
kubectl get pods --show-labels                       # 显示标签
kubectl get pods --no-headers                        # 不显示表头

# 详细信息
kubectl describe pod <pod>                           # Pod 详情（事件/状态/容器）
kubectl describe node <node>                         # 节点详情（资源/条件）
kubectl describe deploy <deploy>                     # Deployment 详情（滚动更新状态）
kubectl describe svc <svc>                           # Service 详情（Endpoints）
```

#### 日志与调试（logs / exec）

```bash
# 日志
kubectl logs <pod>                                   # 查看日志（单容器）
kubectl logs <pod> -c <container>                    # 指定容器
kubectl logs <pod> --tail=100                        # 最近 100 行
kubectl logs <pod> --since=5m                        # 最近 5 分钟
kubectl logs <pod> -f                                # 实时跟踪（tail -f）
kubectl logs <pod> --previous                        # 上一个崩溃容器的日志
kubectl logs -l app=nginx --all-containers=true      # 所有标签匹配 Pod 的日志
kubectl logs deploy/<deploy>                         # Deployment 下所有 Pod 日志
kubectl logs job/<job>                               # Job 的日志

# 进入容器
kubectl exec -it <pod> -- /bin/bash                  # 进入容器 shell
kubectl exec -it <pod> -c <container> -- /bin/sh     # 指定容器
kubectl exec <pod> -- ls /app                        # 执行单次命令
kubectl exec <pod> -- cat /var/log/app.log           # 查看容器内文件
kubectl exec -it <pod> -- sh -c 'tail -f /var/log/*' # 执行复合命令
```

#### 资源管理（apply / create / delete / scale）

```bash
# 创建资源
kubectl apply -f deployment.yaml                     # 声明式创建/更新（推荐）
kubectl create -f deployment.yaml                    # 命令式创建
kubectl create deploy nginx --image=nginx:latest     # 快速创建 Deployment
kubectl create configmap my-cm --from-file=config.yaml  # 从文件创建 ConfigMap
kubectl create secret generic my-secret --from-literal=key=value  # 创建 Secret
kubectl create namespace dev                         # 创建 namespace
kubectl run nginx --image=nginx --restart=Never      # 快速启动一个 Pod

# 删除
kubectl delete -f deployment.yaml                    # 删除文件中定义的资源
kubectl delete pod <pod>                             # 删除 Pod
kubectl delete pod <pod> --grace-period=0 --force    # 强制立即删除
kubectl delete deploy <deploy>                       # 删除 Deployment
kubectl delete pods -l app=nginx                     # 按标签删除
kubectl delete pods --all                            # 删除当前 namespace 所有 Pod

# 扩缩容
kubectl scale deploy <deploy> --replicas=5           # 调整副本数
kubectl scale --replicas=3 -f deployment.yaml        # 用文件调整副本数
kubectl scale deploy <deploy> --current-replicas=3 --replicas=5  # 条件扩缩（当当前=3时才执行）

# 更新
kubectl set image deploy/<deploy> nginx=nginx:1.21   # 更新镜像
kubectl edit deploy <deploy>                         # 在线编辑 YAML
kubectl patch deploy <deploy> -p '{"spec":{"replicas":3}}'  # JSON patch
kubectl replace -f deployment.yaml                   # 替换整个资源
```

#### 滚动更新（rollout）

```bash
kubectl rollout status deploy/<deploy>               # 查看滚动更新状态
kubectl rollout history deploy/<deploy>               # 查看历史版本
kubectl rollout history deploy/<deploy> --revision=3  # 查看指定版本详情
kubectl rollout undo deploy/<deploy>                  # 回滚到上一版本
kubectl rollout undo deploy/<deploy> --to-revision=2  # 回滚到指定版本
kubectl rollout restart deploy/<deploy>               # 重启 Deployment（滚动重建 Pod）
kubectl rollout pause deploy/<deploy>                 # 暂停滚动更新
kubectl rollout resume deploy/<deploy>                # 恢复滚动更新
```

---

### 8.2 次常见命令（运维常用）

#### 端口转发与代理（port-forward / proxy）

```bash
# 本地端口转发到 Pod
kubectl port-forward pod/<pod> 8080:80               # 本地 8080 → Pod 80
kubectl port-forward deploy/<deploy> 8080:80          # 转发到 Deployment
kubectl port-forward svc/<svc> 8080:80                # 转发到 Service
kubectl port-forward --address 0.0.0.0 pod/<pod> 8080:80  # 绑定所有网卡

# API 代理（本地访问 K8s API）
kubectl proxy --port=8001                             # 启动 API 代理
# 然后 curl http://localhost:8001/api/v1/namespaces/default/pods
```

#### 资源监控（top / describe）

```bash
kubectl top nodes                                     # 节点资源使用（CPU/内存）
kubectl top pods                                      # Pod 资源使用
kubectl top pods -A                                   # 所有 namespace 的 Pod
kubectl top pods --containers                         # 显示每个容器
kubectl top pods -l app=nginx --sort-by=cpu           # 按 CPU 排序
```

#### 节点管理（cordon / drain / taint）

```bash
# 节点维护
kubectl cordon <node>                                 # 标记节点不可调度（已有 Pod 不受影响）
kubectl uncordon <node>                               # 恢复可调度
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data  # 驱逐 Pod 并标记不可调度
kubectl drain <node> --force --grace-period=0         # 强制驱逐（危险！）

# 污点管理
kubectl taint nodes <node> key=value:NoSchedule       # 添加污点
kubectl taint nodes <node> key=value:NoSchedule-      # 删除污点（注意末尾的 -）
kubectl taint nodes <node> key-                       # 删除 key 对应的所有污点
kubectl describe node <node> | grep Taints            # 查看节点污点
```

#### 标签与注解（label / annotate）

```bash
# 标签
kubectl label nodes <node> env=prod                   # 打标签
kubectl label nodes <node> env-                       # 删除标签（末尾 -）
kubectl label pods <pod> app=nginx --overwrite        # 覆盖标签
kubectl get nodes --show-labels                       # 查看所有标签

# 注解
kubectl annotate deploy <deploy> description="my app"  # 添加注解
kubectl annotate deploy <deploy> description-          # 删除注解
kubectl annotate deploy <deploy> description="new" --overwrite  # 覆盖
```

#### 配置与认证（config / auth）

```bash
# kubeconfig 管理
kubectl config view                                    # 查看完整 kubeconfig
kubectl config view --minify                           # 仅当前上下文
kubectl config current-context                         # 当前上下文
kubectl config get-contexts                            # 所有上下文
kubectl config use-context <context>                   # 切换上下文
kubectl config set-context <context> --namespace=dev   # 设置默认 namespace
kubectl config get-clusters                            # 列出集群
kubectl config get-users                               # 列出用户

# 权限检查
kubectl auth can-i create pods                         # 当前用户是否有权限
kubectl auth can-i delete pods --as system:serviceaccount:default:my-sa  # 检查 SA 权限
kubectl auth can-i '*' '*'                             # 是否集群管理员
kubectl auth can-i --list                              # 列出所有权限
```

#### 复制与文件传输（cp）

```bash
kubectl cp <pod>:/app/logs/app.log ./app.log           # Pod → 本地
kubectl cp ./config.yaml <pod>:/app/config.yaml         # 本地 → Pod
kubectl cp <pod>:/data ./backup -c <container>          # 指定容器
kubectl cp <pod>:/app/ ./app-backup --retries=5         # 重试 5 次
```

#### 等待与观察（wait / watch）

```bash
# 等待条件满足
kubectl wait --for=condition=Ready pod <pod>            # 等待 Pod Ready
kubectl wait --for=condition=Available deploy/<deploy> --timeout=300s  # 等待 Deployment 可用
kubectl wait --for=delete pod <pod> --timeout=60s       # 等待 Pod 被删除
kubectl wait --for=jsonpath='{.status.phase}'=Running pod <pod>  # 自定义条件

# 持续观察
kubectl get pods -w                                     # watch 模式（持续输出变化）
kubectl get pods -w -o wide                             # watch + 详细信息
```

---

### 8.3 不常见命令（高级场景）

#### 资源对比（diff）

```bash
# 对比本地文件与集群中的差异
kubectl diff -f deployment.yaml                        # 显示本地与集群 YAML 的差异
kubectl diff -f . -R                                  # 递归对比整个目录
kubectl diff -f deployment.yaml --server-side          # server-side diff
```

#### 调试专用（debug）

```bash
# 创建临时调试容器（K8s 1.23+）
kubectl debug <pod> -it --image=busybox --target=<container>  # 附加到 Pod 的 namespace
kubectl debug node/<node> -it --image=ubuntu           # 在节点上创建调试 Pod（特权模式）

# 在指定节点上启动调试 Pod
kubectl run debug --image=nicolaka/netshoot -it --rm --restart=Never --overrides='{"spec":{"nodeName":"node-1"}}' -- /bin/bash
```

#### 直接 API 调用（raw / proxy）

```bash
# 通过 kubectl 直接调用 K8s API
kubectl get --raw /api/v1/namespaces/default/pods       # 获取原始 JSON
kubectl get --raw /metrics                              # 获取 metrics
kubectl get --raw /api/v1/nodes/<node>/proxy/stats/summary  # 节点 cAdvisor 统计
kubectl get --raw /api/v1/nodes/<node>/proxy/debug/pprof/goroutine?debug=2  # Go 协程 dump

# 带认证的 API 调用
kubectl get --raw /apis | jq '.groups[].name'           # 查看所有 API 组
kubectl api-resources --verbs=list,create,delete        # 按动词过滤 API 资源
```

#### 高级资源操作

```bash
# 创建临时 Job 从 CronJob
kubectl create job my-job --from=cronjob/my-cronjob     # 手动触发 CronJob

# 替换资源（先删除再创建，用于不可变字段修改）
kubectl replace --force -f deployment.yaml              # 强制替换

# 批量 patch
kubectl patch deploy -l app=nginx -p '{"spec":{"template":{"spec":{"nodeSelector":{"env":"prod"}}}}}'  # 批量 patch

# 批量删除
kubectl get pods -l status=Evicted --no-headers | awk '{print $1}' | xargs kubectl delete pod  # 删除所有 Evicted Pod

# 获取资源 YAML 并清理（去除状态字段）
kubectl get deploy <deploy> -o yaml | sed '/status:/,$d'  # 导出不带状态的 YAML

# 生成资源清单
kubectl set image deploy/<deploy> nginx=nginx:1.22 --dry-run=client -o yaml  # 生成 YAML 不执行
kubectl create deploy nginx --image=nginx --dry-run=client -o yaml > deploy.yaml  # 生成部署 YAML
```

#### JSONPath 高级用法

```bash
# 提取 Pod IP
kubectl get pods -o jsonpath='{.items[*].status.podIP}'

# 提取所有 Ready 节点
kubectl get nodes -o jsonpath='{.items[?(@.status.conditions[?(@.type=="Ready")].status=="True")].metadata.name}'

# 提取 Deployment 的镜像
kubectl get deploy -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[*].image}{"\n"}{end}'

# 提取 Pod 的容器名 + 镜像
kubectl get pods -o custom-columns=NAME:.metadata.name,IMAGES:.spec.containers[*].image,NODE:.spec.nodeName
```

#### 集群诊断

```bash
# 集群信息
kubectl cluster-info                                    # 集群基本信息
kubectl cluster-info dump                               # 导出集群诊断信息（日志/配置）
kubectl cluster-info dump --output-directory=/tmp/k8s-dump  # 导出到指定目录
kubectl version                                         # 客户端 + 服务端版本
kubectl version --short                                 # 简洁版本

# API 资源探索
kubectl api-resources                                   # 所有 API 资源
kubectl api-resources --namespaced=false                # 非 namespace 资源
kubectl api-resources --api-group=networking.k8s.io     # 指定 API 组
kubectl api-versions                                    # 所有 API 版本
kubectl explain pod                                     # 查看资源字段说明
kubectl explain pod.spec.containers                     # 递归查看字段
kubectl explain pod.spec.containers --recursive         # 递归查看所有字段
```

#### 证书管理

```bash
# 查看证书过期时间
kubectl get cm kubeadm-certs -n kube-system -o jsonpath='{.data}'
kubeadm certs check-expiration                          # kubeadm 集群证书检查

# 手动批准 CSR
kubectl get csr                                         # 查看证书签名请求
kubectl certificate approve <csr>                       # 批准 CSR
kubectl certificate deny <csr>                          # 拒绝 CSR
```

#### 高级调度操作

```bash
# 手动重新调度 Pod（驱逐 Pod 让 Scheduler 重新调度）
kubectl delete pod <pod>                                # 让 Deployment 重建 Pod 到其他节点

# 查看 Pod 调度失败原因
kubectl describe pod <pod> | grep -A5 Events

# 查看调度器评分
kubectl get events --field-selector reason=FailedScheduling

# 强制 Pod 不退出的优雅终止（查看为什么卡住）
kubectl get pod <pod> -o json | jq '.status.conditions'
```

#### etcd 备份与恢复

```bash
# 备份 etcd（需在 etcd 节点上执行）
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%Y%m%d).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 查看快照状态
ETCDCTL_API=3 etcdctl snapshot status /backup/etcd.db --write-out=table

# 恢复 etcd
ETCDCTL_API=3 etcdctl snapshot restore /backup/etcd.db --data-dir=/var/lib/etcd-restore
```

#### 插件与扩展（plugin / krew）

```bash
# kubectl 插件列表
kubectl plugin list                                    # 列出已安装插件

# 常用 krew 插件（需安装 krew 包管理器）
kubectl krew install ctx ns view-secret node-shell      # 安装常用插件
kubectl ctx                                             # 切换上下文（krew）
kubectl ns                                              # 切换 namespace（krew）
kubectl view-secret <secret>                            # 解码 Secret（krew）
kubectl node-shell <node>                               # SSH 到节点（krew）
kubectl whoami                                          # 查看当前用户身份（krew）
```

#### 其他罕见命令

```bash
# ServiceAccount Token 创建（K8s 1.24+）
kubectl create token <sa-name>                          # 创建临时 Token
kubectl create token <sa-name> --duration=24h           # 指定有效期

# 资源驱逐
kubectl delete pod <pod> --force --grace-period=0       # 强制立即删除（绕过优雅终止）

# 查看 Pod 安全上下文
kubectl get pod <pod> -o jsonpath='{.spec.securityContext}'

# 查看容器资源限制
kubectl get pods -o custom-columns=NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu,CPU_LIM:.spec.containers[*].resources.limits.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory,MEM_LIM:.spec.containers[*].resources.limits.memory

# 批量重启 Deployment（滚动更新触发）
kubectl rollout restart deploy -n <ns>                  # 重启指定 namespace 所有 Deployment

# 查看节点上所有 Pod
kubectl get pods --all-namespaces -o wide --field-selector spec.nodeName=<node>

# 统计集群资源
kubectl get pods -A --no-headers | wc -l                # Pod 总数
kubectl get nodes --no-headers | wc -l                  # 节点总数
kubectl get pods -A -o json | jq '[.items[] | .spec.nodeName] | group_by(.) | map({node: .[0], count: length})'  # 每个节点 Pod 分布

# 直接修改已运行资源（不推荐）
kubectl edit deploy <deploy>                            # 打开编辑器修改（关闭后自动应用）
kubectl set env deploy/<deploy> ENV=prod                # 设置环境变量
kubectl set resources deploy/<deploy> --limits=cpu=500m,memory=1Gi  # 设置资源限制
kubectl set serviceaccount deploy/<deploy> my-sa        # 设置 ServiceAccount
kubectl set subject clusterrolebinding <name> --user=<user>  # 修改绑定主体
```

---

### 8.4 kubectl 小技巧

#### 别名与快捷键

```bash
# 常用别名（放入 ~/.bashrc 或 ~/.zshrc）
alias k='kubectl'
alias kg='kubectl get'
alias kgp='kubectl get pods'
alias kgd='kubectl get deploy'
alias kgs='kubectl get svc'
alias kd='kubectl describe'
alias krm='kubectl delete'
alias ka='kubectl apply -f'
alias kl='kubectl logs'
alias ke='kubectl exec -it'
alias kpf='kubectl port-forward'
alias kns='kubectl config set-context --current --namespace'

# 快速切换 namespace
kns dev         # 切换到 dev
kns default     # 切回 default
```

#### 自动补全

```bash
# bash
source <(kubectl completion bash)
echo "source <(kubectl completion bash)" >> ~/.bashrc

# zsh
source <(kubectl completion zsh)
echo "source <(kubectl completion zsh)" >> ~/.zshrc

# 配合别名
complete -o default -F __start_kubectl k
```

#### 输出美化

```bash
# 彩色输出
kubectl get pods -o wide --show-labels | column -t -s $'\t'

# 用 jq 处理 JSON 输出
kubectl get pods -o json | jq -r '.items[] | "\(.metadata.name) \(.status.podIP)"'

# stern 多 Pod 日志聚合（需安装 stern）
stern -n default "nginx-.*"                            # 聚合所有 nginx Pod 日志
stern -n default "nginx-.*" --since 5m                 # 最近 5 分钟
```

---

### 8.5 命令分类速查索引

| 场景 | 常用命令 | 不常用命令 |
|------|----------|------------|
| **资源查看** | `get`, `describe`, `-o wide/yaml/json` | `jsonpath`, `custom-columns`, `field-selector` |
| **日志调试** | `logs`, `logs -f`, `exec -it` | `logs --previous`, `logs -l`, `logs --all-containers` |
| **创建更新** | `apply`, `create`, `delete`, `scale` | `replace --force`, `create job --from=cronjob`, `patch --type=merge` |
| **滚动更新** | `rollout status`, `rollout undo` | `rollout pause`, `rollout resume`, `rollout history --revision` |
| **节点管理** | `cordon`, `uncordon`, `drain`, `taint` | `drain --force`, `drain --delete-emptydir-data` |
| **端口转发** | `port-forward` | `proxy` |
| **监控** | `top nodes`, `top pods` | `top pods --sort-by`, `top pods --containers` |
| **配置** | `config view`, `config use-context` | `config set-context --namespace`, `config get-clusters` |
| **权限** | `auth can-i` | `auth can-i --as`, `auth can-i --list` |
| **文件传输** | `cp` | `cp --retries` |
| **调试** | `describe` | `debug`, `get --raw /proxy/stats`, `get --raw /debug/pprof` |
| **证书** | — | `certificate approve`, `csr`, `kubeadm certs check-expiration` |
| **etcd** | — | `etcdctl snapshot save/restore/status` |
| **插件** | — | `krew install`, `ctx`, `ns`, `view-secret`, `node-shell` |
| **等待** | — | `wait --for=condition`, `wait --for=delete` |
| **对比** | — | `diff`, `diff --server-side` |
| **Token** | — | `create token`, `create token --duration` |

---

## 参考资源

- [Kubernetes 官方文档](https://kubernetes.io/docs/concepts/overview/components/)
- [CNCF Landscape](https://landscape.cncf.io/)
- [Kubernetes the Hard Way](https://github.com/kelseyhightower/kubernetes-the-hard-way)