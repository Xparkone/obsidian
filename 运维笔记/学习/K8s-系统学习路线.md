# K8s 系统学习路线

> 起点：掌握 kubectl、Pod/Deployment/Service 基础  
> 目标：能独立运维 K8s 集群、排查故障、设计云原生架构  
> 创建时间：2026-07-13
> 
> 📎 这是 [[SRE-DevOps-云原生-AI-综合学习路线]] 中「云原生」领域的详细展开，建议先看综合路线了解全局，再回到这里深入 K8s。
> 🎯 本路线完成后进入精通阶段：[[K8s-精通路线-总纲]]（差距分析 + 10 章深挖笔记计划 + 实验与认证验收）。

---

## 📚 你已有的知识储备（无需重复学习）

| 文档 | 覆盖内容 |
|------|---------|
| **K8s-定义.md** | K8s 是什么、核心概念、通俗解释 |
| **K8s-组件详解.md** | 控制平面（API Server / etcd / Controller / Scheduler）、Worker 节点组件 |
| **K8s-资源全览.md** | 全部资源类型、YAML 模板、命令速查 |
| **k8s-常用操作手册.md** | kubectl 常用命令、标签、注解、污点容忍等 |

---

## 🗺️ 学习路线图

```
Phase 1 ──── Phase 2 ──── Phase 3 ──── Phase 4 ──── Phase 5
深入理解      网络与存储    调度与弹性    运维实战      云原生生态
(2周)        (2周)        (2周)        (3周)        (持续)
```

---

## Phase 1：深入理解 K8s 核心（2 周）

> 从「会用」到「理解为什么」

### 1.1 控制平面工作原理

| 主题 | 要点 | 你已有的笔记 |
|------|------|:---:|
| API Server 的请求处理流程 | 认证→鉴权→准入控制→etcd 写入 | ✅ 组件详解 |
| etcd 深入 | 数据模型、watch 机制、备份与恢复 | ⚠️ 需补充 |
| Controller Manager 控制循环 | ReplicaSet、Deployment 控制器如何工作 | ⚠️ 需补充 |
| Scheduler 调度流程 | 预选→优选→绑定，自定义调度器 | ⚠️ 需补充 |

### 1.2 Pod 生命周期深入

| 主题 | 要点 |
|------|------|
| Pod 生命周期 | Pending → Running → Succeeded/Failed，各阶段含义 |
| 探针（Probes） | liveness / readiness / startup 的区别与最佳实践 |
| Init 容器与 Sidecar | 使用场景与模式 |
| QoS 与资源管理 | Guaranteed / Burstable / BestEffort，OOM 评分 |

### 1.3 阿里云课程推荐

- **云计算、容器和云原生基础课程**（2,776 学员）— 帮你从云视角理解 K8s 定位

---

## Phase 2：网络与存储（2 周）

### 2.1 K8s 网络模型

| 主题 | 要点 |
|------|------|
| CNI 网络插件对比 | Flannel / Calico / Cilium 的原理与选型 |
| Service 四种类型 | ClusterIP / NodePort / LoadBalancer / ExternalName |
| Ingress 与 Gateway API | 七层路由、TLS 终止、流量分割 |
| NetworkPolicy | 网络隔离策略，Pod 间流量控制 |
| CoreDNS | 集群内 DNS 解析机制 |

### 2.2 K8s 存储体系

| 主题 | 要点 |
|------|------|
| Volume 类型 | emptyDir / hostPath / configMap / secret / PVC |
| PV & PVC 生命周期 | 静态/动态供给，StorageClass |
| CSI 驱动 | 云盘、NAS、OSS 的 CSI 接入方式 |

### 2.3 阿里云课程推荐

- **5 分钟玩转阿里云容器服务**（5,925 学员）— 了解 ACK 网络与存储集成

---

## Phase 3：调度与弹性伸缩（2 周）

### 3.1 调度策略

| 主题 | 要点 |
|------|------|
| 节点选择 | nodeSelector / nodeName / 亲和性（affinity） |
| 污点与容忍（Taint & Toleration） | 专用节点、隔离策略 |
| 拓扑分布约束 | topologySpreadConstraints，跨可用区均匀分布 |
| 优先级与抢占 | PriorityClass，资源紧张时的抢占行为 |

### 3.2 弹性伸缩

| 主题 | 要点 |
|------|------|
| HPA（水平自动伸缩） | 基于 CPU/内存/自定义指标的扩缩容 |
| VPA（垂直自动伸缩） | 自动调整 Pod 的 requests/limits |
| Cluster Autoscaler | 节点级别的自动扩缩 |
| KEDA | 事件驱动的弹性伸缩 |

### 3.3 阿里云课程推荐

- **容器应用的高弹性架构**（425 学员）— HPA 实战
- **容器应用更新与灰度发布**（570 学员）— 蓝绿、金丝雀发布

---

## Phase 4：运维实战（3 周）

### 4.1 部署策略

| 主题 | 要点 |
|------|------|
| 滚动更新 | maxSurge / maxUnavailable 参数调优 |
| 蓝绿部署 | 两套环境切换，快速回滚 |
| 金丝雀发布 | 渐进式流量切换，Argo Rollouts / Istio |
| Helm | Chart 开发、仓库管理、多环境部署 |

### 4.2 可观测性

| 主题 | 要点 |
|------|------|
| 日志收集 | Fluentd / Filebeat + Elasticsearch / Loki |
| 监控 | Prometheus + Grafana，核心指标与告警规则 |
| 链路追踪 | Jaeger / Tempo，分布式调用链分析 |
| 事件审计 | K8s Audit Log 的配置与分析 |

### 4.3 安全

| 主题 | 要点 |
|------|------|
| RBAC | ServiceAccount / Role / ClusterRole / RoleBinding |
| Pod 安全 | PodSecurityPolicy → Pod Security Standards |
| Secret 管理 | 加密存储、外部 Secret 管理（Vault / Sealed Secrets） |
| 镜像安全 | 镜像扫描、签名、最小化镜像 |

### 4.4 故障排查方法论

| 主题 | 要点 |
|------|------|
| 排障流程 | `kubectl describe` → `kubectl logs` → `kubectl exec` → 事件分析 |
| 常见问题 | ImagePullBackOff / CrashLoopBackOff / Pending / OOMKilled |
| 节点故障 | NotReady 排查、kubelet 日志、磁盘/内存压力 |

### 4.5 阿里云课程推荐

- **企业级运维之云原生与 Kubernetes 实战课程**（3,720 学员）⭐ 重点
- **容器应用与集群管理**（3,600 学员）
- **可观测 Grafana 入门课程**（2,642 学员）
- **基于 Docker 与 Jenkins 实现自动化部署**（3,666 学员）— CI/CD 实战

---

## Phase 5：云原生生态（持续学习）

### 5.1 服务网格

| 主题 | 要点 |
|------|------|
| Istio 入门 | Sidecar 注入、流量管理、安全通信 |
| 你已有的笔记 | ✅ **Istio-服务网格详解.md** |

### 5.2 GitOps

| 主题 | 要点 |
|------|------|
| ArgoCD | 声明式持续交付，Application 资源 |
| Flux | 另一套 GitOps 工具 |
| 你已有的笔记 | ✅ **Argo-项目详解.md** / **gitlab-ci-argocd/** |

### 5.3 阿里云课程推荐

- **CNCF Alibaba 云原生技术公开课**（24,054 学员）⭐ 最全面
- **云原生实践公开课**（3,653 学员）
- **云原生技术趋势与行业发展解读**（5,711 学员）

---

## 🏆 认证路径

| 认证 | 备考课程 | 说明 |
|------|---------|------|
| **阿里云云原生工程师 ACA** | 阿里云云原生工程师 ACA 认证课程（3,425 学员） | 入门级，适合检验基础 |
| **CKA**（Certified Kubernetes Administrator） | 官方文档 + killer.sh 模拟 | 国际认证，含金量高 |
| **CKAD**（K8s 应用开发者） | 官方文档 | 侧重应用开发 |
| **CKS**（K8s 安全专家） | 官方文档 | 安全方向，需先有 CKA |

---

## 📅 建议学习节奏

| 周次 | 阶段 | 重点 | 每天约 |
|:---:|------|------|:---:|
| 1-2 | Phase 1 | 控制平面原理、Pod 生命周期 | 1h |
| 3-4 | Phase 2 | 网络插件、Service/Ingress、PVC | 1h |
| 5-6 | Phase 3 | 调度、HPA/VPA、灰度发布 | 1h |
| 7-9 | Phase 4 | 部署策略、监控日志、安全、排障 | 1h |
| 10+ | Phase 5 | Istio、GitOps、CNCF 公开课 | 灵活 |

每阶段结束建议：**搭建一个实验集群**（用 kind/k3s/minikube），把学到的内容动手验证一遍。

---

## 🔗 相关资源

| 资源 | 链接 |
|------|------|
| 阿里云容器课程 | https://edu.aliyun.com/explore/?tags=661300%3D661808 |
| K8s 官方文档 | https://kubernetes.io/docs/ |
| K8s 官方教程 | https://kubernetes.io/docs/tutorials/ |
| CNCF 云原生路线图 | https://landscape.cncf.io/ |
| Killer.sh（CKA 模拟） | https://killer.sh/ |
| Play with K8s（在线实验） | https://labs.play-with-k8s.com/ |

---

## 📝 你的笔记中待补充的主题

根据你的现有笔记，以下主题建议新建文档：

| 建议新建 | 说明 |
|---------|------|
| **K8s-网络详解.md** | CNI 插件对比、Service 原理、NetworkPolicy |
| **K8s-存储详解.md** | PV/PVC/StorageClass、CSI |
| **K8s-调度详解.md** | 亲和性、污点容忍、拓扑分布、优先级 |
| **K8s-安全详解.md** | RBAC、Pod Security、Secret 管理 |
| **K8s-排障手册.md** | 常见故障模式与排查步骤 |
| **K8s-可观测性.md** | Prometheus + Grafana + Loki 集成 |