# K8s 精通路线 · 总纲

> 定位：从「会用 kubectl、能维护集群」（当前）→「精通：懂原理、能设计、能排障、能扩展、能调优」
> 创建时间：2026-10-13
> 学习基线：**Kubernetes v1.37**（截至 2026-10，官方维护 1.35 / 1.36 / 1.37 三个 minor，[官方发布页](https://kubernetes.io/releases/)）
>
> 📎 前置路线：[[K8s-系统学习路线]]（广度扫盲，5 阶段）。本文档是**精通阶段**的展开：先补 10 个深挖缺口（新建笔记），再用实验和认证验证。

---

## 🧭 什么是「精通」——验收标准

学完全部章节 + 实验后，应当能**不看文档**做到：

| # | 能力 | 验证方式 |
|---|------|---------|
| 1 | 画出任意一次 `kubectl apply` 的完整请求链路（认证→鉴权→准入→etcd→控制器 reconcile） | 白板讲给同事听 |
| 2 | 从零用 kubeadm 搭一个三节点集群，并完成一次 minor 版本升级 | 实验 L2 |
| 3 | etcd 快照备份 + 损坏后恢复；证书过期处理与轮转 | 实验 L3 |
| 4 | 讲清 Pod 到外部流量的完整路径（CNI → kube-proxy → 网关），会抓包验证 | 实验 3.x |
| 5 | 给集群写准入策略：PSA、OPA/Gatekeeper 或 Kyverno 规则各一条 | 实验 5.x |
| 6 | 用 controller-runtime 从零写一个有 CRD 的最小 Operator 并跑通 reconcile | 实验 6.x |
| 7 | 十分钟内定位模拟故障：镜像拉取失败 / CrashLoop / 节点 NotReady / DNS 异常 / 证书报错 | 实验 L3 破坏演练 |
| 8 | 配出基于自定义指标的 HPA，并能解释 HPA/VPA/KEDA/Karpenter 各自适用边界 | 实验 9.x |
| 9 | 给生产集群做容量规划与性能调优设计（apiserver/etcd 瓶颈判断） | 第 7 章评审 |
| 10 | 通过 CKA 模拟考（killer.sh ≥ 80 分），安全方向加考 CKS | 认证 |

---

## 📚 现状盘点（全库 K8s 笔记审计，2026-10-13）

### 已经扎实覆盖（无需重做）

| 主题 | 已有笔记 | 深度 |
|------|---------|------|
| 基础概念 / 架构 / 组件 | `容器编排/K8s-定义.md`、`K8s-组件详解.md`、`k8s-architecture.excalidraw.md`、`Kubernetes-从入门到生产实践*.md` | 中级 |
| 资源对象全谱 + kubectl 操作 | `容器编排/K8s-资源全览.md`、`k8s-常用操作手册.md`、`Docker-K8s-快捷批量操作手册.md` | 中级 |
| Pod 机制 | `容器编排/K8s-Pod生命周期详解.md` | ★ 深入 |
| etcd 机制与运维 | `容器编排/K8s-etcd详解.md` | ★ 深入 |
| 备份恢复 / 迁移 | `容器编排/Velero-Kubernetes备份恢复与迁移指南.md` | ★ 深入 |
| Helm | `容器编排/Helm-3-从入门到生产实践.md` | ★ 深入 |
| 发行版部署 | `容器编排/K3s-部署指南.md`（HA / 离线） | 中级 |
| 入口与流量 | `容器编排/Kubernetes-Ingress-部署与使用详解.md`（含 Gateway API 引介） | 中级-深入 |
| 服务网格 | `容器编排/Istio-服务网格详解.md`、`Istio详细入门与实践指南.md` | 中级 |
| GitOps / CD | `容器编排/Argo-项目详解.md` + `CI-CD/` 下 5 篇 ArgoCD/GitOps 实战 | 中级-深入 |
| 可观测性 | `监控/` 下 Prometheus/Victoria/Loggie/deepflow(eBPF)/Grafana 面板 6+ 篇 | 中级-深入 |
| RBAC 基础 | `安全/RBAC详解.md` | 中级 |
| 扩展工作负载 | `容器编排/OpenKruise-原理作用使用与部署指南.md` | 中级 |
| 镜像供应链 | `CI-CD/` 下 Dockerfile 指南、Kaniko、Skopeo | 中级 |

**结论：你的广度和中级实战已经很强，4 篇笔记已达「深入」级（Pod 生命周期、etcd、Velero、Helm）。缺的全部是机制级深入 + 扩展开发 + 大规模生产治理。**

### 十大深挖缺口（= 精通章节的由来）

1. **API 机制完全空白**：list-watch / informer / APF（API Priority & Fairness）/ 聚合层 / 审计日志，全库零覆盖 —— 而 API 是理解一切控制循环的地基
2. **调度器深入**：scheduling framework 扩展点、抢占机制实现、descheduler、批调度
3. **网络实现原理**：CNI 规范与 Flannel/Calico/Cilium 对比、kube-proxy iptables vs IPVS、eBPF、CoreDNS 原理、Gateway API 实战（Cilium 目前只在 Rancher 文档里有一句备注）
4. **存储深入**：CSI 架构与 driver 模型、PV-PVC 绑定/回收完整生命周期、扩容/克隆、VolumeSnapshot API（现有是 Velero 视角，不是 API 视角）
5. **安全深入**：准入控制 webhook（Mutating/Validating 开发）、OPA/Gatekeeper 与 Kyverno、Secret 静态加密/KMS/Vault/ESO、audit policy
6. **扩展开发零覆盖**：CRD 进阶（structural schema、版本转换）、controller-runtime、kubebuilder、Operator 实战
7. **生产运维深入**：kubeadm 搭建/升级流程、证书轮转（现在只有「查过期」命令，没有轮转流程）、apiserver/etcd/调度器性能调优、大规模集群治理
8. **系统性排障方法论**：现有排障片段散落在 4 篇笔记里，缺少「分域排障树 + 破坏演练」一本通
9. **自动伸缩深入**：HPA 自定义指标、VPA/InPlace 更新、KEDA、Karpenter 均无专篇
10. **多集群**：Karmada / Federation / Cluster API 未提及（现有仅 ArgoCD ApplicationSet、Rancher 工具视角）

---

## 🗺️ 精通章节计划（新建笔记，全部放 `容器编排/`）

按依赖顺序排列 —— **API 是地基放最前；网络/存储的排障建立在二者之上；排障大作殿后**。

| # | 新建笔记 | 核心内容 | 前置 | 配套实验 | 状态 |
|---|---------|---------|------|---------|:---:|
| 1 | `K8s-API机制深入.md` | 对象模型与版本化、RequestPath 全链路、list-watch 与 informer、reflector/store、finalizer 与 ownerReference、GC、APF、聚合层、Raw API 调用、审计日志 | 无 | 抓 watch 请求观察资源版本；用 certs 直接 curl API | ✅ |
| 2 | `K8s-调度器深入.md` | scheduler 架构、Scheduling Framework 18 个扩展点、打分插件、PreBinding→Binding、抢占机制源码视角、descheduler 策略、自定义调度器、批调度（Volcano/Kueue 简介） | 第 1 章 | 写一个寄存式打分插件（或 descheduler 策略实验） | ✅ |
| 3 | `K8s-网络原理详解.md` | K8s 网络模型三原则、CNI 规范、Flannel/Calico/IPIP-BGP/Cilium(eBPF&hubble) 对比、kube-proxy iptables vs IPVS 抓链验证、CoreDNS 原理与排障、NetworkPolicy 加固、Gateway API 完整实战 | 无 | `iptables -t nat -L` 对照 Service；Cilium demo；tcpdump 追包 | ✅ |
| 4 | `K8s-存储深入.md` | CSI 两组件架构（Controller/Node service）、PV-PVC 绑定/回收/Retain-Delete 语义、静态 vs 动态供给、StorageClass 参数含义、扩容/克隆、VolumeSnapshot API、本地存储与拓扑感知 | 无 | CSI driver demo（如 csi-driver-host-path）；快照实验 | ✅ |
| 5 | `K8s-安全加固详解.md` | PSA 实战（enforce/audit/warn）、Mutating/Validating webhook 开发与故障尾、OPA/Gatekeeper、Kyverno、Secret 静态加密（EncryptionConfiguration+KMS）、Vault/ESO 集成、audit policy、镜像签名（cosign）、CIS 基准 | 第 1 章 | 起一台 webhook server 拦截 Deployment；conftest 离线校验 | ✅ |
| 6 | `K8s-Operator开发实战.md` | CRD 进阶（structural schema / 多版本 / conversion webhook）、controller-runtime 架构、reconcile 幂等性、Informer vs Watch、finalizer、kubebuilder 上手、Go 写一个最小应用型 Operator（部署 + 观测 + 重启自愈） | 第 1、2 章 | `kubebuilder init && make run` 全流程 | ⬜ |
| 7 | `K8s-生产集群运维手册.md` | kubeadm 搭集群（v1.37、containerd、etcd 外部/堆叠选型）、升级流程（kubeadm upgrade + drain）、CA/证书轮转（1.35+ 自动轮转行为）、节点自运维（node-problem-detector、draino）、etcd/apiserer/scheduler 性能调优参数、LIMIT ranger/ResourceQuota 治理、大规模集群设计约束 | 第 1 章 | 见下方实验 L2 / L3 | ⬜ |
| 8 | `K8s-故障排查方法论.md` | 分域排障树：控制面 / 节点 / 调度 / Pod-容器 / 网络-DNS / 存储 / 证书七大域；每域「症状→工具→修复」；kubectl debug/ephemeral/nsenter/tcpdump 组合技；kubelet 日志读法；真实事故复盘模板；收敛 `排障进阶-5个冷门kubectl命令` 等内容做成一本通 | 第 1~4、7 章 | 实验 L3 破坏-恢复演练是本篇的实战战场 | ⬜ |
| 9 | `K8s-自动伸缩深入.md` | HPA 算法与冷却窗口、自定义指标（prometheus-adapter/KEDA ScaledObject 对比）、VPA 三种模式与 InPlace 更新、CA vs Karpenter 选型、Karpenter WorkerPool/EC2NodeClass、伸缩对 PDB/滚动更新的联动、容量规划方法 | 第 7 章 | Karpenter（或 CA）+ KEDA 各一个 demo | ⬜ |
| 10 | `K8s-多集群与进阶生态.md` | 多集群痛点与方案谱（Rancher/Fleet/Karmada/OCP/OCM 对比）、多集群 Service/网络（Submariner/云厂商实现）、Cluster API 声明式建集群、设备管理（GPU device plugin、TimeSlicing vs MIG）、kubeedge / 边缘、Wasm/KWasm/Knative、vCluster 虚拟集群 | 第 7、9 章可以之后学 | Karmada 装一套把 Deployment 推到两个 kind 集群 | ⬜ |

**建议学习节奏：每章 = 读笔记 → 做配套实验 → 在仓库里补一节「我已经验证过的」心得 → 勾掉状态。**

---

## 🔬 全局实验计划（贯穿全部章节）

| 实验 | 内容 | 用哪个阶段 |
|------|------|-----------|
| **L1 快速沙箱** | `kind`（多节点、自定义 CNI、kind-network）+ `k3d`，用于各章日常验证 | 各章配套实验 |
| **L2 生产形态集群** | 用 Multipass（你已有 `云服务/Multipass-使用指南.md`）开 3 台 VM：1 control-plane + 2 worker，**kubeadm + containerd + Cilium** 搭集群 v1.37，再升级到 v1.38 | 第 1、3、5、7、9 章实验主场 |
| **L3 破坏-恢复演练** | 在 L2 上系统性搞坏：删 etcd、错证书、卡 CNI、杀 kubelet、挤爆磁盘、过期 Ingress 证书、DNS 故障，逐个排查到恢复，**每一场录成 runbook**（可以归档进 `容器编排/K8s-故障排查方法论.md`） | 第 8 章 |
| **L4 认证** | killer.sh CKA 模拟（买完实名练习 8 套题）；若走安全线补 CKS | 最后验收 |

---

## ⚙️ 顺手要做的笔记维护（审计发现）

| 项 | 位置 | 问题 | 处理 |
|---|------|------|------|
| 1 | `容器编排/K3s-部署指南.md` | 基线 v1.32.3+k3s1，该 minor 已于 2026-02-28 EOL | 升级基线到 1.35+ 并验证命令仍成立 |
| 2 | `容器编排/K8s-资源全览.md` | 小节标题仍写「PodSecurityPolicy / Pod Security Admission」，正文已迁 PSA | 清理标题里的 PSP 字样 |
| 3 | kubectl 速查类 | `k8s-常用操作手册` / `K8s-组件详解§8` / `Docker-K8s-快捷批量` / `排障进阶` 四篇有重叠 | 第 8 章完成后做一次收敛，标明各文档边界 |

---

## 📝 进度追踪清单

```text
总纲（本文件）                 ✅ 2026-10-13
第 1 章 API 机制               ✅ 2026-10-13 → 容器编排/K8s-API机制深入.md
第 2 章 调度器                 ✅ 2026-10-13 → 容器编排/K8s-调度器深入.md
第 3 章 网络原理               ✅ 2026-10-13 → 容器编排/K8s-网络原理详解.md
第 4 章 存储深入               ✅ 2026-10-13 → 容器编排/K8s-存储深入.md
第 5 章 安全加固               ✅ 2026-10-13 → 容器编排/K8s-安全加固详解.md
第 6 章 Operator 开发          ⬜
第 7 章 生产集群运维           ⬜
第 8 章 故障排查方法论         ⬜
第 9 章 自动伸缩               ⬜
第 10 章 多集群与进阶生态      ⬜
实验 L2 kubeadm 集群           ⬜
实验 L3 破坏-恢复 runbook      ⬜
CKA 模拟考                     ⬜
```

---

## 🔗 相关资源

| 资源 | 链接 / 位置 |
|------|-----------|
| K8s 官方文档（刷源码 & 扫概念首选） | https://kubernetes.io/docs/ |
| 官方发布节奏（版本基线核对） | https://kubernetes.io/releases/ |
| scheduler 源码导读（调度 framework） | https://github.com/kubernetes/kubernetes/tree/master/pkg/scheduler |
| controller-runtime 文档 | https://book.kubebuilder.io/ |
| Cilium eBPF 教程 | https://cilium.io/labs/ |
| killer.sh（CKA/CKS 模拟） | https://killer.sh/ |
| 你已有的广度路线 | `学习/K8s-系统学习路线.md` |
| 你已有的综合路线 | `学习/SRE-DevOps-云原生-AI-综合学习路线.md` |
