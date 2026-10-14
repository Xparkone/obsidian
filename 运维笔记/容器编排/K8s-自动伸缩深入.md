# K8s 自动伸缩深入

> 精通路线第 9 章：伸缩三轴（HPA 副本数 / VPA 单副本规格 / CA·Karpenter 节点容量）+ 事件驱动 KEDA 第四件、HPA 算法与启动保护逐参数核实、prometheus-adapter rules 四件套、VPA InPlaceOrRecreate × KEP-1287 现状、CA 扩缩条件表、Karpenter v1 disruption 家族、PDB/发布/descheduler/抢占联动、容量规划公式、生产问题清单与四个实验
> 创建时间：2026-10-14
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37）；生态组件基线：metrics-server v0.9.0、prometheus-adapter v0.12.0、VPA v1.8.0、KEDA v2.21.0、Karpenter（AWS provider）v1.15.0 /（Azure provider）v1.14.5。文中所有 flag 默认值、feature gate 状态、CRD 字段、注解拼写均对照官方 docs（kubernetes.io）、各上游仓库 master 文档与 release notes 逐一核实（见 §10.4）；落地前仍以你本地集群版本与现场输出为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，§6 聚合层——custom/external metrics 的 APIService 机制直接引用不重讲）、`K8s-调度器深入.md`（第 2 章，§6 PriorityClass/抢占、§8 descheduler）、`K8s-生产集群运维手册.md`（第 7 章，§6.4 kubelet eviction、§8 租户治理与 requests/limit 纪律）、`K8s-故障排查方法论.md`（第 8 章，事件/日志排障手法）、`K8s-资源全览.md`（§6 HPA/VPA/CA 的 YAML 入门用法——**本文不复述基本用法，只讲机制、联动与边界**）。总纲：`学习/K8s-精通路线-总纲.md`。

---

## 零、本文定位与边界

### 0.1 伸缩是一条「X × Y × Z 三轴 + 一个扳机」的问题

「上自动伸缩」这句话在面试和生产里都太含糊。拆开看，容量有三个**正交的维度**，每个维度由不同的控制器掌管，各管各的 reconcile 循环：

```
        X 轴：副本数（向外扩）                Y 轴：单副本规格（向上扩）
        ─────────────────────               ─────────────────────
        HPA / KEDA(托管 HPA)                VPA（Recommender→Updater→
        改 .spec.replicas                   Admission 改 requests/limits）
        无状态、可水平分摊负载               单体大进程、有状态单点、
        反应：分钟级（指标链延迟）           长尾调优（历史数据驱动）

        Z 轴：节点容量（底层池子）
        ─────────────────────
        cluster-autoscaler / Karpenter
        改 Node 数量；触发源是「调度不上的 Pod」与「长期低利用的 Node」
        反应：分钟级~10分钟级（云 API + 节点 bootstrap）

        扳机（第四件）：事件驱动
        ─────────────────────
        KEDA：把「队列长度/定时窗口/外部指标」翻译成 HPA 能懂的
        external metrics，并独家掌管 0↔1 的激活
```

四条边界线先画死，后文全部按这张图收敛：

1. **HPA 与 VPA 是扳同一个 Pod 的两个旋钮**：一个改「几个 Pod」，一个改「每个 Pod 多大」。目标维度冲突时（§1.2）不能无脑同开。
2. **CA 不是「资源不够就加机器」的简单循环**：它只看**调度器账本**（requests × Pending），Karpenter 同理。节点上真实用爆了但没 Pending Pod，节点层一件都不会动——那是 HPA/VPA 的事。
3. **指标不是从天上掉下来的**：resource / custom / external 三条链路最终都落在 apiserver 聚合层的三个 API 组（§1.3），链路任何一环挂了，HPA 只会「安静地不工作」。
4. **KEDA 不是 HPA 的替代品，是 HPA 的外包商**：1↔N 仍然由它生成的 HPA 干，它自己只管 0↔1 激活和指标喂数（§3.4）。

### 0.2 与已有笔记的边界（不重复内容）

| 已有笔记 | 它们讲过什么（继续在那篇看） | 本章接管什么 |
|---------|------------------------------|--------------|
| `K8s-资源全览.md` §6 | HPA/VPA/CA 三个 YAML 模板与一分钟上手 | **不复述入门 YAML**；§2 起逐参数精读 HPA 算法与 behavior，§4 讲 VPA 三组件与 InPlace 现状，§5 讲 CA/Karpenter 机制与选型 |
| `K8s-API机制深入.md` §6 | 聚合层（APIService + extension apiserver）代理路径、metrics.k8s.io 故障判读链 | 只引用结论：`metrics.k8s.io`、`custom.metrics.k8s.io`、`external.metrics.k8s.io` 三个组都走同一套 APIService 机制（§1.3）；APIService 故障排查直接看第 1 章 §6.2 |
| `K8s-调度器深入.md` §6、§8 | PriorityClass 数值底座、抢占完整步骤；descheduler 策略全图与部署 | §6.3 只讲「descheduler 与伸缩控制器的兼容战」，§6.4 只讲「PriorityClass + CA 的 overprovisioning 配方」，机制本身引用不重复 |
| `K8s-生产集群运维手册.md` §6.4、§8 | kubelet eviction 阈值与 QoS 序列、LimitRange/ResourceQuota、CPU limit 取消趋势 | §4.5 引用其「memory request==limit / CPU 视情况不写 limit」纪律作 VPA 配方底座；eviction 细节不重讲 |
| `K8s-故障排查方法论.md` | 事件 TTL 1h、先只读后写、症状→控制循环反查 | §8 问题清单按同一体裁组织（症状→根因→定位→处理），排障通用手法引用不重复 |

### 0.3 生态组件版本基线（本章所有「当前状态」以此为准）

| 组件 | 当前版本（2026-10 核实） | 关键版本事实 | 来源（§10.4 同列） |
|------|--------------------------|--------------|--------------------|
| Kubernetes | v1.37（维护 1.35/1.36/1.37） | HPA per-方向 tolerance **GA 于 v1.37**（v1.33 Alpha→v1.34 Beta→v1.37 GA 且 gate 锁定）；HPAScaleToZero **Beta 于 v1.37 默认开**；InPlacePodVerticalScaling **GA 于 v1.35 锁定** | kubernetes.io HPA 页 / resize 页 / kube-controller-manager flag 参考 |
| metrics-server | v0.9.0（2026-07） | 0.9.x 要求 k8s **1.34+**；`--metric-resolution` 默认 **1m0s**（最少 10s） | 仓库 README 兼容矩阵 + command-line-flags |
| prometheus-adapter | v0.12.0（2024-05，版本多年未动但仍是对接事实标准） | custom/external metrics adapter；rules 四件套见 §3.3 | 仓库 docs/config.md |
| VPA | v1.8.0（2026-09） | `InPlaceOrRecreate`：v1.4 Alpha→v1.5 Beta→**v1.6 GA**；`InPlace`：v1.7 Alpha；`Auto` 已 deprecated | autoscaler 仓 VPA docs + releases |
| KEDA | v2.21.0（2026-09） | ScaledObject spec 与 scaler 字段按 2.21 文档核实 | keda.sh docs |
| Karpenter | AWS provider v1.15.0（2026-10）；Azure provider v1.14.5 | API 稳定组 `karpenter.sh/v1`；Balanced consolidation 自 **v1.14.0** 起；Terminate-First disruption v1.15.0 Alpha | karpenter.sh docs + 两仓 releases |
| cluster-autoscaler | 跟随 k8s 版本线发布（与集群同 minor） | scale-down 默认值表见 §5.1（全部核对 FAQ master） | autoscaler 仓 CA FAQ |

❗ 心智前十条（先背再看正文）：①三轴正交，先说清拧的是哪个轴；②HPA 是控制循环不是实时系统，15s sync 只是其中一环；③`Utilization` 的锚是 requests 不是 limits；④HPA 取多指标的**最大值**，缺失指标会保守化而不是报错；⑤VPA 推荐值是「统计量」不是「真理」，Off 模式先观察一周；⑥CA 只看调度账本，Pending 是它的唯一输入；⑦PDB 同时卡 VPA、CA、Karpenter 三家；⑧缩到 0 只有 external/object 指标才行（v1.37 起 Beta 默认开）；⑨KEDA 的 1↔N 还是 HPA 干的，改 ScaledObject 前先看它生成的 HPA；⑩任何伸缩改动，先看 `kubectl describe hpa` 的 conditions 再动 YAML。

---

## 一、伸缩总地图

### 1.1 三轴对象与控制器对照表

| 轴 | 对象 / 组件 | 控制器在哪 | 改的是什么 | 输入信号 | 反应量级 | 典型对象 |
|----|-------------|-----------|------------|----------|----------|----------|
| X（副本数） | HorizontalPodAutoscaler（`autoscaling/v2`） | kube-controller-manager 内的 HPA controller（15s 一轮） | 目标 workload 的 `.spec.replicas`（经 `/scale` 子资源） | resource / custom / external 三组指标 API | 秒级~分钟级（取决于指标链） | Deployment、StatefulSet、任何实现 `/scale` 的 CRD |
| X（副本数） | KEDA ScaledObject（`keda.sh/v1alpha1`） | KEDA operator + KEDA metrics server | 生成并托管一个 HPA（`keda-hpa-<name>`）；0↔1 由 KEDA 自己改 replicas | 60+ 种事件源 scaler（队列/Prometheus/cron…） | pollingInterval（默认 30s）+ HPA 15s | Deployment、StatefulSet、实现 `/scale` 的 CRD；批处理走 ScaledJob |
| Y（单副本规格） | VerticalPodAutoscaler（`autoscaling.k8s.io/v1`，CRD） | vpa-recommender / vpa-updater / vpa-admission-controller 三件套 | Pod 容器的 `resources.requests`（可选 limits） | 历史 + 实时 usage（经 metrics-server 与 API 观察） | 天级收敛；落地时机由 updateMode 决定 | Deployment、StatefulSet、DaemonSet（只读 pod set）等 |
| Z（节点容量） | cluster-autoscaler | 独立 Deployment（通常控制面侧） | 云 node group（ASG/MIG/VMSS）的节点数 | 调度器 Pending（unschedulable pods）+ 节点低利用持续时长 | 扩容 <30s 触发 + 节点 bootstrap 数分钟；缩容默认需 unneeded 10m | 云托管/自建集群 + 云 API |
| Z（节点容量） | Karpenter | 独立 Deployment（in-cluster） | NodeClaim（直连云 API 开/销实例） | 同 CA：unschedulable pods + disruption（consolidation/drift/expire/repair） | 扩容秒级决策 + 实例启动；缩容由 consolidateAfter/budgets 控制 | AWS 最成熟，Azure 跟进中 |

📎 DaemonSet 不能被 HPA/VPA 改副本数（没有 `/scale` 语义）；Job 本身适合用 KEDA ScaledJob 而不是 HPA。

### 1.2 为什么 HPA 与 VPA 在生产常常不一起开

这不是经验玄学，是**维度的引用冲突**：

- HPA 的 CPU/内存 `Utilization` = `当前用量 ÷ requests`。**requests 动了，HPA 的分母就动了**。
- VPA 的工作恰恰是根据历史用量**改写 requests**。

两边同开同一个 Deployment 的同一种资源（比如都管 CPU）时的负反馈回路：

```
流量上升 → CPU 用量上升 → VPA 上调 requests
        → HPA 眼里 utilization = 用量/requests 反而“不高”
        → HPA 不扩容或反而缩容
        → 每个 Pod 更挤 → 用量更高 → VPA 继续上调 …
（反向同理：流量下降时 VPA 下调 requests → 利用率虚高 → HPA 误扩容）
```

出路只有三条，生产任选其一并写进团队规约：

1. **维度错峰**（推荐默认）：HPA 只看 **CPU**，VPA（RequestsOnly 或 Off 观察模式）只管 **memory**——两者分母不同，互不干扰。适合「CPU 随流量弹性、内存随数据量缓变」的 Web 服务。
2. **指标分层**：HPA 用**自定义指标**（RPS、队列深度、P99 延迟）而不是 CPU/内存利用率，VPA 管 CPU+内存 requests。HPA 的分母不再是 requests，冲突消失。这是本章 §3 给 prometheus-adapter/KEDA 这么大篇幅的根本原因。
3. **一边只读**：VPA `updateMode: Off` 只出建议不改值，requests 由人按建议定期落地；HPA 正常接管副本。这是「先混熟再放手」的稳妥态。

❗ 例外与边界：VPA 官方明确「HPA 用 CPU/内存利用率时不要与 VPA 同开同资源」；而 VPA 的 `InPlaceOrRecreate`（§4.3）只改 requests 不重启 Pod，并不解除这个冲突——**冲突发生在「分母被改」的数学上，不在「改的时候是否重启」的工程上**。

### 1.3 指标三条链：resource / custom / external 都进同一个门

HPA 不认识 Prometheus，也不认识 metrics-server。它只认识 apiserver 上挂出来的**三个 API 组**——这正是第 1 章 §6 聚合层的三个标准实例：

```
┌──────────────────────┐   metrics.k8s.io/v1beta1   ┌─────────────────┐
│ metrics-server       │ ──────────────────────────►│                 │
│ (watch 各 kubelet     │  只有 Pod/Node 的 CPU/Mem  │                 │
│  /stats/summary)     │                              │  kube-apiserver │
└──────────────────────┘                              │                 │
┌──────────────────────┐  custom.metrics.k8s.io/v1beta1│  聚合层路由：   │
│ prometheus-adapter   │ ──────────────────────────► │  APIService     │──► HPA controller
│ (Helm values 里配     │  “挂在 K8s 对象上”的自定义  │  .spec.service  │    （15s 一轮
│  rules 四件套)        │  指标（pods/ns/ingress…）   │  → extension    │     实时拉取）
└──────────────────────┘                              │  apiserver      │
┌──────────────────────┐  external.metrics.k8s.io/v1beta1│               │
│ KEDA metrics-server  │ ──────────────────────────►│                 │
│ / prometheus-adapter │  “与 K8s 对象无关”的外部值   │                 │
│ (external 部分)       │  （队列长度、云监控值…）    │                 │
└──────────────────────┘                              └─────────────────┘
```

三条链的生态位一句话分工：

| API 组 | 语义 | 官方稳定性 | 谁提供 | HPA 对应 metric source type |
|--------|------|-----------|--------|------------------------------|
| `metrics.k8s.io` | Pod/Node 的 CPU、内存用量 | Beta 组，**HPA 只吃 `v1beta1`（官方明确不支持 v1）** | metrics-server | `Resource` / `ContainerResource` |
| `custom.metrics.k8s.io` | 挂在某个 K8s 对象上的指标（如某 Pod 的 RPS） | v1beta1 | prometheus-adapter（或各监控厂商 adapter） | `Pods` / `Object` |
| `external.metrics.k8s.io` | 与集群对象无绑定的外部值（如 SQS 队列深度） | v1beta1 | KEDA、prometheus-adapter、云厂商 adapter | `External` |

判读动作（与第 1 章 §6.2 同一套）：HPA 报 `FailedGetResourceMetric` / `FailedGetExternalMetric` 时，先 `kubectl get apiservices | grep -E 'metrics'` 看三个 APIService 的 `Available` 条件，再顺 `spec.service` 查 extension apiserver 的 Pod 与 Endpoints——链路图与命令在第 1 章已给全，这里不重复。

❗ **HPA 的 resource metrics 只支持 `metrics.k8s.io/v1beta1`**——这是官方 HPA 页白纸黑字的 NOTE。如果你的监控栈“早已 v1 化”，别去找不存在的 `metrics.k8s.io/v1`：资源指标这个组至今只有 v1beta1 一个版本。

---

## 二、HPA 深入

### 2.1 算法全貌：一个比例式、三条保守化规则

HPA controller 每个 sync 周期（`--horizontal-pod-autoscaler-sync-period`，**默认 15s**，v1.37 kube-controller-manager flag 参考核实）对每个 HPA 对象执行核心比例公式：

```
desiredReplicas = ceil( currentReplicas × currentMetricValue / desiredMetricValue )

例：当前 4 副本，实测均值 250m，目标 100m
    → ceil( 4 × 250/100 ) = ceil(10) = 10 副本

若 ratio 落在 [1±tolerance] 内 → 本次不动
    tolerance 默认 0.1（--horizontal-pod-autoscaler-tolerance）
    即 ratio ∈ [0.9, 1.1] 视为“已达期望”，防抖设计
```

两条常被忽略的计算细节（官方 Algorithm details 节明确写出）：

- **取平均的位置**：配了 `AverageValue` / `Utilization` 时，`currentMetricValue` 是**所有目标 Pod 的均值**，不是副本数无关的总量。总量型指标请用 External + `Value`。
- **`ceil` 的方向**：扩容缩容都向上取整，再交给 behavior policies 限速（§2.4）。

**缺失指标与未就绪 Pod 的保守化**（面试高频、生产误判的重灾区）——HPA 不会报错停摆，而是按方向做保守假设后重算：

| 情形 | 缩容方向的假设 | 扩容方向的假设 | 效果 |
|------|----------------|----------------|------|
| 某 Pod 指标缺失（metrics 链抖动/Pod 刚起） | 按 100% 目标值计 | 按 0% 目标值计 | 缺失越多，动作幅度越小（dampen） |
| 某 Pod not-yet-ready（启动保护窗口内） | 按 0% 计 | 按 0% 计 | 进一步压低扩容量 |
| 重算后方向反转或落入 tolerance | — | — | **本次完全不动** |
| 带删除时间戳的 Pod / Failed Pod | 直接剔除出计算 | 剔除 |  terminating 中的 Ready Pod（external/object 指标）仍计入副本基数 |

**多指标取最大**：`metrics:` 列表里每个指标独立算出一个 desiredReplicas，取**最大**者作为本轮建议。但有一个保护分支：**任何一个指标拉取失败时，如果其余指标的建议方向是缩容，本轮直接跳过**（宁可用旧副本数，也不在信息不全时缩）；扩容方向不受影响——这是「扩容激进、缩容保守」总基调的一部分。

### 2.2 target 三语义与四种 metric source：先想清楚「除以谁」

| target.type | 语义 | 比较对象 | 适用 metric source |
|-------------|------|----------|---------------------|
| `Utilization`（仅 Resource/ContainerResource） | 用量 ÷ **requests** 的百分比均值 | per-Pod 均值 | Resource、ContainerResource |
| `AverageValue` | 指标的 per-Pod 均值（原始值） | 均值 vs 阈值 | Resource、Pods、Object（除 readiness 外会再除以 Pod 数）、External |
| `Value` | 指标总量（原始值，**不除副本数**） | 总量 vs 阈值 | Object、External |

❗ 三个生产级理解：

1. **`Utilization` 的锚是 requests 不是 limits，也不是真实机器**。想把「节点真实水位」维持在 60%，得先把 requests 写成「期望 Pod 正常跑的水位」，否则 utilization 百分比全失真。这也是「裸 Pod 不写 requests 不许上生产」（第 7 章 §8.3）在伸缩侧的闭环理由——**没写 requests 的容器，该 CPU 指标对 HPA 未定义，整份指标被跳过**。
2. **`ContainerResource`（v1.30 起 GA，feature gate 已移除锁死开）让多容器 Pod 按「主容器」伸缩**：sidecar（日志/agent）的资源消耗不再污染分母。注意坑：**改了容器名要先改 HPA（新旧容器名并存一段时间）再改 workload**，顺序反了 HPA 会把「找不到该容器」当指标缺失走保守化。
3. **Object 指标配 `AverageValue` 时会除以「Running 且 Ready 的 Pod 数」**（terminating 但未摘 Ready 的也算）；配 `Value` 则全程不除。写 Ingress QPS 类指标时选错这一项，副本数能差一个数量级。

四种 metric source 速查：

| source type | 数据来自 | 典型写法 | 注意 |
|-------------|----------|----------|------|
| `Resource` | metrics.k8s.io（metrics-server） | `resource.name: cpu, target.type: Utilization` | 只有 cpu/memory；分母含所有容器之和 |
| `ContainerResource` | 同上 | 多指一个 `container: <name>` | 容器不存在于部分 Pod 时这些 Pod 被忽略后重算 |
| `Pods` | custom.metrics.k8s.io | `pods.metric.name: <name>` | 只支持 AverageValue；是 per-pod 自定义指标 |
| `Object` | custom.metrics.k8s.io | `object.metric/describedObject` | 描述的是 ns 内**另一个对象**（如 Ingress） |
| `External` | external.metrics.k8s.io | `external.metric.name/selector` | 匹配多条时**求和**后比较；可同时承担 0↔1（v1.37 Beta，§2.6） |

### 2.3 启动保护：两个只在 kube-controller-manager 上存在的 flag

Java 类应用启动那 2~5 分钟 CPU 打满、readiness 忽上忽下——这种「启动期样本」如果喂给 HPA，会把集群扩成马蜂窝。v1.37 官方 HPA 页与 command-line-reference 双重核实的两个 flag（**只能集群级设置**，改的是控制面）：

| flag | 默认 | 干什么 | 存在的理由 |
|------|------|--------|-----------|
| `--horizontal-pod-autoscaler-initial-readiness-delay` | **30s** | Pod 启动后这段窗口内，readiness 的首次翻转才被视为「初始就绪」；此前一直 Unready 的 Pod 被视作「还在初始化」 | 防止 readiness 探针在启动期抖动（Ready↔Unready 反复横跳）的 Pod 被过早计入指标均值 |
| `--horizontal-pod-autoscaler-cpu-initialization-period` | **5m** | Pod 启动后 5 分钟内的 CPU 样本被丢弃，除非该样本完整落在「Pod 已 Ready」区间内 | 直接掐掉 JVM 预热/JIT/加载缓存造成的 CPU 尖峰样本 |

配套的最佳实践（官方原文思路）：**让 startupProbe 把高 CPU 阶段关进「未 Ready」**，探针没通过之前 Pod 本来就不计入指标；readinessProbe 同理设好 `initialDelaySeconds`。两个 flag 是兜底，探针才是主防线。

### 2.4 behavior 精读：stabilizationWindow / policies / selectPolicy

`behavior`（autoscaling/v2，v1.23 起 Stable）分 `scaleUp` / `scaleDown` 两个方向，各自三件套：

```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 300   # 回溯窗口：取窗口内「历史建议副本数」的最大值
    policies:                          # 限速策略：本周期最多变化多少
    - type: Percent
      value: 10
      periodSeconds: 60                # 语义：每 60s 最多缩 10%（periodSeconds 上限 1800s）
    - type: Pods
      value: 5
      periodSeconds: 60
    selectPolicy: Min                  # Max（默认）| Min | Disabled：多个 policy 冲突时选谁
  scaleUp: { ... }                     # 同构
```

逐字段的「为什么」：

- **`stabilizationWindowSeconds`（稳定窗口）**：控制循环每轮都会产出「期望副本数」的建议值；窗口开启后，控制器取**过去 N 秒内所有建议值的最大值**（缩容方向用 max、从而达到「缓慢缩」；扩容方向也可以用但取的是 max 反而更激进——所以扩容窗口默认 0）。默认行为里 scaleDown 窗口 300s，根源是更老的集群级 flag `--horizontal-pod-autoscaler-downscale-stabilization`（默认 5m）——**behavior 里的字段优先于该 flag**。
- **`policies` 是速率整形而不是目标**：`Percent 10 / 60s` 的意思是「一次 sync 里最多缩当前副本的 10%，且这个额度每 60s 发放一次」。注意计算基数是**当前**副本数：80 副本的 10% 是 8 个，缩到 39 副本之后 10% 只剩 4 个（先快后慢的自然减速）。
- **`selectPolicy`**：多 policy 并存时默认 `Max`（放得最宽的那条生效），`Min` 取最保守，`Disabled` 直接把该方向锁死。

官方默认 behavior（不显式写时等效配置，背下来）：

```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 300
    policies:
    - { type: Percent, value: 100, periodSeconds: 15 }
  scaleUp:
    stabilizationWindowSeconds: 0
    policies:
    - { type: Percent, value: 100, periodSeconds: 15 }
    - { type: Pods,    value: 4,   periodSeconds: 15 }
    selectPolicy: Max
```

即默认语义：**扩容每 15s 最多翻倍或 +4 取大者（立即、激进）；缩容等 5 分钟稳定窗口，之后 15s 内可以全缩完（被窗口保护着所以并不快）**。

**生产配方：快速放大、慢速缩小**（防突发打挂 + 防毛刺误缩，可直接粘贴）：

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web
  minReplicas: 3
  maxReplicas: 50
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 60
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0        # 扩容不等
      policies:
      - type: Percent
        value: 100
        periodSeconds: 15                  # 每 15s 最多翻倍
      - type: Pods
        value: 4
        periodSeconds: 15                  # 且最多一口气 +4
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300      # 缩容先冷静 5 分钟
      policies:
      - type: Percent
        value: 10
        periodSeconds: 60                  # 之后每分钟最多缩 10%
      selectPolicy: Max                    # 单 policy 时 Max/Min 无差
```

**v1.37 新变量：per-方向 tolerance**。字段 `behavior.scaleUp.tolerance` / `behavior.scaleDown.tolerance` 在 v1.33 Alpha（HPAConfigurableTolerance）、v1.34 Beta、**v1.37 GA 且 feature gate 锁定**（kubernetes.io HPA 页核实）。例：`scaleUp.tolerance: 0.05` 表示只有实测超过目标 5% 以上才扩；不设则回落到集群级 `--horizontal-pod-autoscaler-tolerance`（默认 0.1）。

### 2.5 sync 15s 的体感：端到端延迟预算表

「HPA 多久能反应」不是 15s 一个数能回答的——把整条串行链摆出来（默认值口径；metrics-server 抓取间隔官方默认 **1m** 而非 15s，见其 `--metric-resolution` flag 参考，这是最容易背错的数）：

| 环节 | 默认节奏 | 说明 |
|------|----------|------|
| kubelet 产出容器 stats | ≈10s（housekeeping） | 节点侧本来就快 |
| metrics-server 抓取 | **60s**（`--metric-resolution` 默认 1m0s，可调到最低 10s） | **多数生产把它调到 15s~30s**；不改的话突发第一分钟 HPA 根本看不见 |
| HPA controller sync | 15s（`--horizontal-pod-autoscaler-sync-period`） | 每轮对每个 HPA 重算 |
| behavior 稳定窗口/限速 | 扩容默认 0s，缩容默认 300s | 策略性等待（§2.4） |
| Deployment→RS→Pod 创建 | 秒级 | 控制面动作的尾声 |
| **Pod 冷启动** | **镜像拉取 + 应用初始化，秒级到分钟级** | 端到端里通常最大的变量：大镜像 + 无预热 = 扩容“已发生但不可用” |

**突发流量的真实反应周期 ≈ 指标链 15s~90s + HPA 决策 15s + 冷启动**。所以「HPA 扛突发」的正确解不是把 sync 调成 1s（徒增 apiserver 压力，且指标链跟不上），而是：①指标链提速（metric-resolution 15s）→ ②用 behavior 保留热 buffer → ③镜像预热/瘦身 + startupProbe 把好 readiness → ④实在扛不住的尖峰交给「预置冗余 + PriorityClass 抢占池」（§6.4）。

### 2.6 缩到 0：v1.37 把它扶到了 Beta 默认开

`HPAScaleToZero`：**v1.37 起 Beta、kube-apiserver 与 kube-controller-manager 双侧默认启用**（官方 HPA 页核实）。语义：

- `minReplicas: 0` **仅当配置了至少一条 Object 或 External 指标时合法**（apiserver 会拒绝纯 resource 指标配 0 副本——没 Pod 就没有 CPU 指标，公式无输入）。
- HPA 把副本压到 0 时在 HPA status 上写 `ScaledToZero: True` 条件；重新拉起时写 False（reason `NotScaledToZero`）。这个条件就是给「人为 `kubectl scale --replicas=0`」做区分的：**期望 0 ≠ 自动缩到 0**，后者才是需要告警关注的事件。
- 与「维护模式」的联动细节：若把目标 workload 副本手动打成 0 而 HPA `minReplicas > 0`，HPA 会**停止对该目标的调整**（`ScalingActive=False`）直到你手动把副本或 minReplicas 调回——这是官方给的「临时下线不打 YAML」暗门。

❗ 0↔1 的冷启动代价全部由第一个请求承担（冷启动期间无 Pod 可服务）。队列消费者无所谓（消息会堆着），在线流量型服务慎用——在线服务要「触底不回零」：`minReplicas >= 1`（或 KEDA 的 `minReplicaCount: 1`）。

### 2.7 事件与状态阅读：conditions 是第一证词

```bash
# 持续观察（-w 在 watch 模式下每个 sync 周期刷新 TARGETS 列）
kubectl get hpa web-hpa -w
# 判读链：TARGETS 列 <unknown> / Metrics 行列不出 → ScalingActive=False → 原因在 message
kubectl describe hpa web-hpa
# 直接翻 status（脚本化排障用）
kubectl get hpa web-hpa -o jsonpath='{.status.conditions}' | jq .
kubectl get hpa web-hpa -o jsonpath='{.status.currentMetrics}' | jq .
```

| condition（autoscaling/v2） | 含义 | 异常时的高频原因 |
|---------|------|------------------|
| `AbleToScale` | 能否读写 scale 子资源、是否在 backoff | ReadyForNewScale 之外出现 `FailedUpdateScale`—查 RBAC；`BackoffBoth`—controller 在自我限频 |
| `ScalingActive` | 是否成功算出本轮建议 | **`ValidMetricFound` 才是真健康**；`FailedGetResourceMetric`/`FailedGetExternalMetric` → 对应指标链断（§1.3 查 APIService）；`InvalidMetricSourceType` → source type 拼错/版本不符 |
| `ScalingLimited` | 建议值被 min/max 卡住 | `TooFewReplicas`/`TooManyReplicas`：长期挂 True 说明容量上下限该改 |
| `ScaledToZero`（v1.37 Beta 新增） | 当前处于自动缩零态 | 数据库/有状态服务出现它 = 配错了最小副本 |

📎 HPA 相关 Event（describe 里的 Events 区）有 TTL（默认 1h，apiserver `--event-ttl`），事故复盘要按第 8 章 §1.3 先把 events 存盘。

### 2.8 为什么这么设计

- **比例式而非 PID/深度学习**：K8s controller 设计哲学是「可解释、可回放、可静态审计」。线性比例 + tolerance + 稳定窗口三件套，让任意时刻的副本决策都能用一条日志解释——这对 SRE 的价值大于拟合精度。
- **保守化处理缺失数据**：缩容是把钱和安全边界往后缩的动作，宁可少缩勿错缩；扩容关系可用性，宁可能的扩错也不能不扩。缺失指标的双向假设（§2.1）与「指标失败跳缩容」规则都是这一个原则的两个切面。
- **启动保护放在控制面而不是指标侧**：Pod 启动期是否正常，只有控制面知道其完整的 readiness 历史；metrics-server 是无状态的转发层，做不了也不该做生命周期判断。

---

## 三、自定义指标链路：metrics-server / prometheus-adapter / KEDA 的生态位

### 3.1 生态位大图：一张图记住谁解决什么

```
需求                         该选谁                    它挂的 API 组
─────────────────────────────────────────────────────────────────
“按 CPU/内存伸缩”            metrics-server           metrics.k8s.io/v1beta1
（埋在 kubelet 里的量）       （只此一家，无替代）       只含 Pod/Node 的 cpu/memory

“按应用自定义指标伸缩”         prometheus-adapter      custom.metrics.k8s.io/v1beta1
（RPS、延迟、错误率…           （一个进程吃下整个
  指标与 K8s 对象有对应关系）   Prometheus 指标空间）
                            也能挂 external.metrics…

“按外部事件伸缩”              KEDA                    external.metrics.k8s.io/v1beta1
（SQS/Kafka 队列深度、定时窗口、  （60+ scaler 插件；
  Redis Stream、云监控…）       指标不进 K8s 对象链）
                            + 独家 0↔1 激活控制
```

判断口诀：**指标长在哪决定 adapter 是谁**——长在 kubelet 里用 metrics-server；长在 Prometheus 里且要挂到 Pod/Ingress 上用 prometheus-adapter；长在集群外（或要做 0↔1、定时、队列语义）用 KEDA。

### 3.2 metrics-server：只解决 resource metrics，但全集群依赖它

- 数据链路：各节点 kubelet `/stats/summary` → metrics-server 内存聚合 → `metrics.k8s.io/v1beta1`。它**不存历史、不落盘**（内存态），所以叫 "resource metrics" 而不叫监控——监控/历史请去 Prometheus。
- 兼容矩阵（官方 README 核实）：**metrics-server 0.9.x 要求 k8s 1.34+**，0.8.x 支持 1.31+。v1.37 集群装 0.9.x 是当前标准动作。
- `--metric-resolution` 默认 **1m0s**（下限 10s）；要高敏 HPA 就调它，并同步估算对 kubelet 的抓取压力。
- `kubectl top pod/node` 与 HPA Resource 指标、`kube-state-metrics` 之外的所有「实时用量」口径都来自它——它挂了的判读链见第 1 章 §6.2（APIService `/v1beta1.metrics.k8s.io`）。

### 3.3 prometheus-adapter：rules 四件套逐字段精读

adapter 进程内置一个「规则引擎」：每条 rule 独立完成 **发现(Discovery) → 关联(Association) → 命名(Naming) → 查询(Querying)** 四步。当前版本 v0.12.0（2024-05 后无新版，仍是 custom metrics 对接事实标准）。四件套逐字段（全部对照官方 docs/config.md）：

```yaml
# values.yaml 片段（prometheus-community/prometheus-adapter Helm chart 内嵌 rules 配置）
rules:
  default: false        # 关掉 chart 自带的资源类默认规则，避免与 metrics-server 重复暴露
  custom:
  # —— 示例：http_requests_total{pod,namespace,…} → pods/http_requests_per_second ——
  - seriesQuery: 'http_requests_total{namespace!="",pod!=""}'   # ① Discovery：喂给 Prometheus /api/v1/series 的 series 选择器
    resources:
      overrides:                                                 # ② Association：Prometheus label → K8s 资源
        namespace: {resource: "namespace"}
        pod:       {resource: "pod"}
      # 若 label 命名规整，可用 template 代替 overrides：
      # template: "kube_<<.Group>>_<<.Resource>>"
    name:
      matches: "^(.*)_total$"                                    # ③ Naming：API 里暴露成什么名字
      as: "${1}_per_second"                                      #    （http_requests_total → http_requests_per_second）
    metricsQuery: 'sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)'
                                                                 # ④ Querying：Go template，分隔符 << >>
                                                                 #    .Series=指标名 .LabelMatchers=对象匹配集 .GroupBy=按资源分组
```

四字段的「为什么这么设计」：

- **`seriesQuery`** 只做「存在性发现」：adapter 定期问 Prometheus 「有哪些 series 长这样」，缓存其「指标名+label 名」组合，**不关心里面的数值**。所以规则写错了的表象是 `kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1` 里**压根没有你那个资源**。
- **`resources`** 是 adapter 的灵魂字段：label 的值就是对象名（`pod="web-abc"` ↔ Pod web-abc）。custom metrics API 是「面向对象」的 API——`/apis/custom.metrics.k8s.io/v1beta1/namespaces/<ns>/pods/<pod>/<metric>`，所以每个 label 必须能翻译回一个 K8s group-resource。
- **`name.matches/as`** 允许改名：`xxx_total` → `xxx_per_second` 是惯用约定（累计值对 HPA 无意义，rate 才有意义）。`.Series` 模板变量拿到的永远是 **Prometheus 里的原始名**，不是 as 出来的名字。
- **`metricsQuery`** 是最终落地查询：模板展开后必须**每个被请求的对象各返回一个值**；返回多了少了都会在 HPA 侧表现为指标缺失（§2.1 保守化）。高级变量：`LabelValuesByName`（map）、`GroupBySlice`。`seriesFilters: [{is|isNot: <regex>}]` 可在 seriesQuery 之后按指标名二次过滤（防多条 rule 重叠——**rule 之间不允许重叠，重叠日志会报 warning 且行为未定义**）。

三种高频坑（生产真出血点）：

1. **label 没对齐 namespace/pod**：应用直接暴露 `http_requests_total` 但没打 `namespace`/`pod` label（比如 Prometheus 抓取配置没开 `relabel` 注入），seriesQuery 匹配为空 → HPA 报指标缺失。修法：Prometheus 端 `kubernetes_sd_configs` 的默认 relabel 会把 `__meta_kubernetes_*` 写成 `namespace`/`pod` label——**先 `curl '<prom>/api/v1/series?match[]=http_requests_total'` 看 series 真实长相再写规则**。
2. **API 名 vs Prometheus 名记串**：HPA 里写 `pods.metric.name: http_requests_total`（原名）而 adapter 把它重命名成了 `http_requests_per_second`——HPA 永远 YourMetric not found。口诀：**HPA/查询端用 as 后的名，metricsQuery 里用原名**。
3. **应用侧改名/加 label**：升级后 `http_requests_total` 变成 `http_server_requests_total`，或多了 `path` label 导致每个对象返回多序列（sum 虽能兜住，但 by() 分组后语义变了）。把 adapter 的 `--v=4` 日志打开看 `available metrics` 列表变化是最快的取证法。

验证三件套（配完就按这个顺序走）：

```bash
# 1) APIService 登记成功？
kubectl get apiservice v1beta1.custom.metrics.k8s.io
# 2) adapter 发现了哪些指标？（对着规则核名字）
kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq '.resources[].name'
# 3) 直取某 ns/pods 的指标值（数值应该有秒级波动）
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/default/pods/*/http_requests_per_second" | jq .
```

### 3.4 external metrics 与 KEDA：事件驱动那件「第四件」

KEDA（当前 v2.21.0，2026-09 发布）的架构分工一句话：**0↔1 由 KEDA operator 直接改 replicas；1↔N 由 KEDA 生成并托管的 HPA 干活；指标由 KEDA metrics-server 经 `external.metrics.k8s.io/v1beta1` 喂给 HPA**。

```
触发源（SQS/Kafka/Prometheus/cron/…）
      │  每个 pollingInterval（默认 30s）查询一次
      ▼
KEDA operator ── 0↔1：IsActive？直接改 .spec.replicas
      │           （activation threshold 决定 active 与否）
      ├─ 生成 HPA：keda-hpa-<scaledobject-name>
      │           （advanced.horizontalPodAutoscalerConfig.behavior 直透 HPA behavior）
      ▼
KEDA metrics-server ── external.metrics.k8s.io ──► HPA（1↔N 决策）
        指标命名：s<trigger序号>-<scaler名>（源码 GenerateMetricNameWithIndex：
        fmt.Sprintf("s%d-%s", i, name)；例：s0-prometheus、s0-cron）
```

ScaledObject 字段精读（keda.sh/v1alpha1，全部对照 2.21 官方 spec 页）：

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: orders-consumer
spec:
  scaleTargetRef:
    apiVersion: apps/v1        # 可缺省，默认 apps/v1
    kind: Deployment           # 可缺省，默认 Deployment；CRD 目标须实现 /scale 子资源
    name: orders-consumer
  pollingInterval: 30          # 默认 30s：触发源轮询间隔（0↔1 阶段由它驱动）
  cooldownPeriod: 300          # 默认 300s：最后一次 active 之后等多久才允许回 0——只管缩到 0，不管 1↔N
  initialCooldownPeriod: 0     # 默认 0：对象刚建好时的冷却宽限
  minReplicaCount: 0           # 默认 0（KEDA 与原生 HPA 不同，默认就可以缩零）
  maxReplicaCount: 100         # 默认 100；透传给生成的 HPA
  fallback:                    # scaler 连续失败时的保底副本数（cpu/memory 触发器不支持）
    failureThreshold: 3        # 连续失败 N 次触发 fallback
    replicas: 6
    behavior: static           # static（默认）/ currentReplicas / currentReplicasIfHigher
                               # / currentReplicasIfLower / scalingModifiers
  advanced:
    restoreToOriginalReplicaCount: false   # 删 ScaledObject 后是否还原原副本数，默认 false
    horizontalPodAutoscalerConfig:
      name: keda-hpa-orders-consumer       # 缺省 keda-hpa-<scaledObject名>
      behavior:                            # 原样透传给 HPA（§2.4 所有字段通用）
        scaleDown:
          stabilizationWindowSeconds: 300
  triggers:
  - type: cron                 # 见实验 9.3：定时窗口最容易复现
    metadata:
      timezone: Asia/Shanghai
      start: "0 9 * * *"
      end: "0 21 * * *"
      desiredReplicas: "10"
  - type: prometheus
    metadata:
      serverAddress: http://prometheus-operated.monitoring.svc:9090
      query: sum(rate(http_requests_total{deployment="web"}[2m]))
      threshold: "100"              # 每副本承载 100 RPS
      activationThreshold: "5"      # 超过 5 才激活 0→1；默认 0
```

| 字段 | 默认值 | 一句话语义与坑 |
|------|--------|----------------|
| `pollingInterval` | 30s | 0↔1 阶段节奏；`minReplicaCount>=1` 且无缓存/无 scalingModifiers 时 KEDA 不再主动轮询触发源，复用 HPA 的查询（官方 spec 页 NOTE） |
| `cooldownPeriod` | 300s | **只管缩到 0**：从最后一次 active 起算；1↔N 的缩容节奏在生成 HPA 的 behavior 里 |
| `minReplicaCount` / `maxReplicaCount` | 0 / 100 | min≥1 时 scaler 恒 active，activation 参数被忽略 |
| `idleReplicaCount` | 不生效 | 官方限制：受 HPA controller 行为所限只支持 0，基本可忘掉它 |
| `fallback` | 无 | scaler 故障时的「定海神针」：连续 `failureThreshold` 次失败后给 HPA 喂假数据把副本钉在 `replicas`；`behavior` 四选一决定静态/动态水位；scalingModifiers 模式可用 `??` 级联多触发器 |
| `advanced.horizontalPodAutoscalerConfig.behavior` | 无 | 生成 HPA 的 behavior 全字段透传（含 v1.33+ 的 tolerance） |
| paused 注解 | — | `autoscaling.keda.sh/paused: "true"`（保持现状）、`/paused-replicas: "N"`（先缩到 N 再停）、`/paused-scale-in|out`（单方向冻结）；运维冻结首选 |
| `transfer-hpa-ownership` 注解 | — | 接管一个已存在的 HPA：`scaledobject.keda.sh/transfer-hpa-ownership: "true"` + `horizontalPodAutoscalerConfig.name` 指名 |
| 指标命名 | — | HPA 里看到的 external 指标名 = `s<触发器下标>-<scaler类型名>`（如 `s0-prometheus`），多触发器按下标递增；这是查 `kubectl get --raw` 时定位指标的钥匙 |

**Scaler 选型速记**：队列类（aws-sqs/kafka/rabbitmq/redis-streams）按积压深度伸缩；`prometheus` 当「万能胶水」；`cron` 做定时保底（§9.3）；批处理用 **ScaledJob**（不生成 HPA，按事件直接批量创建 Job，长任务场景绕开「HPA 缩容误杀跑了一半的 worker」这个经典坑——官方文档对此有专门一节：要么 preStop/terminationGracePeriod 顶住 SIGTERM，要么直接换 ScaledJob）。

### 3.5 prometheus-adapter vs KEDA：决策树

```
指标已经在 Prometheus 里？
├─ 是 → 指标要“挂在 Pod/Ingress 等对象上”做 per-pod 平均？
│       ├─ 是 → prometheus-adapter（custom metrics 是正解：
│       │       Object/Pods 语义、label 对齐由 rules 保证、不引入第二套控制面）
│       └─ 否（总量型：全站 QPS、全局延迟）→ 两边都行：
│              已装 KEDA → KEDA prometheus scaler（少维护一个组件）
│              未装 KEDA → prometheus-adapter external 规则（不新增控制面）
└─ 否 → 触发源是被 KEDA 原生支持的（队列/定时/云监控）？
        ├─ 是 → KEDA（60+ scaler 无代码对接；错选 prometheus-adapter 等于自写 exporter）
        └─ 否 → 自写 exporter 入 Prometheus → 回到“是”分支
```

互补边界一句话：**prometheus-adapter 是「翻译器」（无控制循环、无副本决策），KEDA 是「控制器 + 翻译器」（有 operator、有 0↔1、还顺手生成 HPA）**。两个都装不冲突——APIService 组不同（custom vs external），但不要让同一个 target 被两边生成的 HPA 同时接管（KEDA 的 `transfer-hpa-ownership` 就是为这种迁移准备的）。

### 3.6 为什么这么设计

- **指标与副本决策解耦**：HPA 只懂三组 API 不懂任何监控后端，指标生态因此可插拔——这是聚合层（第 1 章 §6）思想在伸缩域的直接投影。
- **KEDA 复用 HPA 而不是另起炉灶**：1↔N 的比例计算、稳定窗口、限速策略这些难活一律推给久经考验的 HPA，KEDA 只补 HPA 机制上做不到的两件事——**外部事件源适配**与**0↔1 激活**（原生 HPA 在 v1.37 之前完全没有缩零能力，现在也只是 Beta 且仅限 external/object 指标）。「站在巨人肩膀上只补缺口」是云原生项目收敛的标准姿势。

---

## 四、VPA 深入

### 4.1 三组件分工与一个记忆装置：VerticalPodAutoscalerCheckpoint

VPA（kubernetes/autoscaler 子项目，当前 **v1.8.0**，2026-09 发布）不是 K8s 内置控制器，而是三个 in-cluster 组件的总和（官方 README 核实）：

```
                     ┌─────────────────────┐
                     │  vpa-recommender    │  ①读历史+实时用量（metrics.k8s.io、
                     │  （脑）              │   Pod OOM 事件），为每个 VPA 对象算出
                     │                     │   status.recommendation：
                     │  状态记忆：           │   target / lowerBound / upperBound /
                     │  VerticalPod-        │   uncappedTarget
                     │  AutoscalerCheckpoint │
                     │  （CRD，存直方图）    │──► 重启后从这里恢复，不用重新观察 8 天
                     └─────────┬───────────┘
                               │ recommendation
              ┌────────────────┼────────────────┐
              ▼                ▼                
   ┌────────────────┐  ┌─────────────────┐
   │ vpa-updater    │  │ vpa-admission-   │  ③Mutating Webhook：
   │ （手）          │  │ controller（口）  │  Pod 创建瞬间按最新
   │ 按 updatePolicy │  │                  │  recommendation 改写
   │ 驱逐/in-place   │  │                  │  requests/limits
   │ 改存量 Pod      │  │                  │
   └────────────────┘  └─────────────────┘
```

- **Recommender** 是纯统计机：为每个容器维护 CPU/内存用量**直方图**（decayed histogram），target ≈ 高水位分位数，lowerBound/upperBound 是「再低影响稳定/再高纯浪费」的两条参考线。它选的锚值与 OOM 保护：容器 OOMKill 事件会触发内存推荐值上调（`oomBumpUpRatio`/`oomMinBumpUp` 可调）。
- **VerticalPodAutoscalerCheckpoint（VPA Checkpoint）** 是这个统计机的「存档卡带」——以 CRD 形式把直方图落在 etcd 里（`spec.vpaObjectName/containerName` + `status.cpuHistogram/memoryHistogram/totalSamplesCount`）。没有它，recommender 每重启一次就要从零观察好几天，重启初期推荐值全是噪声。**排障时 `kubectl get vpacheckpoint -A` 能直接告诉你「这个 VPA 攒了多少样本」**。
- **Updater** 负责存量 Pod 的「换规格」动作：按 `updatePolicy` 判断谁该被**驱逐**（eviction API，尊重 PDB 与 `updatePolicy.minReplicas`）或**原地改**（InPlaceOrRecreate/InPlace，见 §4.3）。
- **Admission Controller** 负责增量：新 Pod 落地前把 requests（及默认按比例的 limits）改成推荐值——所以哪怕 Updater 一个 Pod 都不驱逐，**只要滚动发布过一次，新规格就生效了**。「接 VPA 后手动触发一次 rolling restart」就是利用这个口。

### 4.2 updatePolicy.mode 六值（v1 API 全量核实）

`spec.updatePolicy.updateMode` 的取值表（autoscaling.k8s.io/v1，对照官方 api.md）：

| mode | 语义 | 是否动存量 Pod | 当前状态（VPA 版本） |
|------|------|----------------|----------------------|
| `Off` | 只算不推荐落地；status.recommendation 照常更新 | 不动 | 稳定。「dry-run/观察模式」的标准姿势 |
| `Initial` | 只在 Pod 创建时由 admission 写入 | 不动存量 | 稳定 |
| `Recreate`（默认） | 创建时写 + 存量 Pod 超界时驱逐重建 | 驱逐（走 eviction API，尊重 PDB） | 稳定；缺省值 |
| `InPlaceOrRecreate` | 优先经 `/resize` 子资源原地改；不行回落 Recreate | 原地为主、驱逐兜底 | **v1.4 Alpha → v1.5 Beta → v1.6 GA**；要求 k8s ≥1.33 开 InPlacePodVerticalScaling |
| `InPlace` | 只原地改、永不驱逐；失败靠 kubelet 重试机制 | 只原地 | **v1.7 Alpha**；需在 admission/updater 开 `--feature-gates=InPlace=true` |
| `Auto` | 目前等价 Recreate | 驱逐 | **已 Deprecated**（autoscaler issue #8424），新配置别再写 |

驱逐触发的量化条件（Recreate/InPlaceOrRecreate 共同）：容器 requests 落在推荐区间之外、发生 quick OOM、或对长命 Pod（>12h）推荐差值 >10%。`updatePolicy` 里还能配 `minReplicas`（低于这个副本数不驱逐，默认尊重 PDB 之后再加一层保险）与 `evictionRequirements`（例：只在「目标是降规格」时驱逐，纯省钱不冒扩容驱逐的风险）。

### 4.3 InPlaceOrRecreate × KEP-1287：两条战线的当前状态核实

原地改规格是「内核（K8s）× 使用者（VPA）」两个项目各自演进的能力，状态要分开背：

**战线一——K8s 内核（KEP-1287 In-Place Pod Vertical Scaling）**，kubernetes.io resize 页核实：

| 能力 | 状态 |
|------|------|
| `InPlacePodVerticalScaling` 主体（CPU/内存经 `--subresource=resize` 原地改） | **v1.35 起 GA 且 feature gate 锁定**（首见于 v1.27 Alpha）；kubectl 侧 `--subresource=resize` 要求 client ≥ v1.32 |
| 容器 `resizePolicy`：`NotRequired`（默认，不重启应用）/ `RestartContainer`（改内存常需要） | 随同主体 GA |
| `InPlacePodVerticalScalingSchedulerPreemption`（Deferred 的 resize 触发低优 Pod 抢占） | **v1.37 Alpha，默认关** |
| `InPlacePodVerticalScalingMemoryBackedVolumes`（内存介质 emptyDir 的 sizeLimit 原地改） | **v1.37 Alpha，默认关**，要求 cgroup v2 |

内核侧的硬约束（v1.37 官方限制清单）：只支持 CPU/内存；**QoS class 不可因 resize 改变**（Guaranteed 的 requests==limits 约束要在新值上继续保持）；资源**只能改不能删**；Windows 不支持；静态 CPU/Memory manager 策略下的 Pod 不可改；降内存 limit 是 best-effort（当前用量高于新 limit 时 resize 会被跳过、卡在 In Progress）。Pod 状态面：`status.conditions` 里 `PodResizePending`（reason `Infeasible`/`Deferred` 两种）与 `PodResizeInProgress`，配合 `status.containerStatuses[*].resources` 对照读。

**战线二——VPA 对这条内核能力的消化**（官方 features.md 核实）：

- `InPlaceOrRecreate` 在 VPA **v1.6.0 已 GA**（v1.7.0 起连它自己的 feature gate 都被移除，开箱即用）。
- 回落到 Recreate 的五种场景：resize infeasible、deferred 超过 5 分钟、进行中超 1 小时、会改变 QoS class、需要降内存 limit 而容器是 PreferNoRestart 策略。
- `--in-place-skip-disruption-budget`（默认 false）：开启后当 Pod 所有容器两种资源都是 NotRequired（即真·无干扰更新）时跳过 PDB/干扰预算检查——**要清楚自己在干什么才开**。
- 观测指标：`vpa_updater_in_place_updated_pods_total`、`vpa_updater_failed_in_place_update_attempts_total` 等（features.md 列全）。
- v1.7.0 Alpha 新品两个：`InPlace`（永不驱逐，纯原地重试）与 **CPU Startup Boost**（启动期 CPU requests 临时 ×Factor 或 +Quantity，Ready 后 N 秒收回去——专门治 JVM 类「启动猛如虎运行稳如狗」的画像）。

### 4.4 resourcePolicy：minAllowed/maxAllowed 与 LimitRange 的相互作用

`spec.resourcePolicy.containerPolicies[]`（逐一核实 api.md）：

```yaml
spec:
  targetRef: {apiVersion: apps/v1, kind: Deployment, name: web}
  updatePolicy:
    updateMode: InPlaceOrRecreate      # v1.6+ GA，k8s>=1.33
    minReplicas: 2                     # 低于 2 副本不驱逐/不原地改
  resourcePolicy:
    containerPolicies:
    - containerName: web               # 或 "*" 通配兜底
      mode: Auto                       # Off = 此容器不给 VPA 管（sidecar 常用）
      minAllowed:  {cpu: 100m,  memory: 256Mi}
      maxAllowed:  {cpu: "4",   memory: 8Gi}
      controlledResources: ["cpu", "memory"]   # 默认两者
      controlledValues: RequestsOnly           # RequestsAndLimits（默认，limit 按原比例跟涨）
                                               # / RequestsOnly（只动 requests，limits 留给人）
```

与 **LimitRange** 的相互作用规则（官方 features.md「Limits control」节原话，容易背错）：

1. VPA 会尝试把推荐值**夹在命名空间 LimitRange 的 min/max 之间**；
2. **若 LimitRange 与 VPA 自己的 resourcePolicy（minAllowed/maxAllowed）冲突，VPA 以自身 resourcePolicy 为准**——会出现超出 LimitRange 的写入被 LimitRange 准入拒绝的边缘形态，所以两个层级的边界值要人工对齐，别指望它俩自动和解。
3. `controlledValues: RequestsAndLimits`（默认）会保持 Pod 里 limit/request 的原比例——回想第 7 章 §8.3 的纪律「memory request==limit、CPU 视场景不写 limit」，生产上**RequestsOnly + 人工管理 limits** 才是默认推荐。

与 **ResourceQuota** 的碰撞顺带一提：namespace 的 requests 总量配额存在时，VPA 上调 requests 可能顶到 quota 导致新 Pod 建不出来（admission 已改大、quota 不让进）——quota 要给 VPA 的 maxAllowed 留出横移空间。

### 4.5 生产决策：requests 经验法则与「VPA × HPA 分层配方」

**requests 的锚定经验法则**（与第 7 章 §8.3 纪律互为表里）：

| 资源 | 写法 | 理由 |
|------|------|------|
| memory | request == limit，按 P99 峰值 + 20% 定值 | OOM 不可压缩；Burstable 在节点压力驱逐序列里吃亏（第 7 章 §6.4 eviction 排序） |
| CPU | 只写 request（≈ P50~P95 常态水位），limit 只在强多租户隔离场景写 | CPU 可压缩；写死 limit = CFS throttle 换 P99 延迟尖峰（第 7 章 §8.3 已论证）；解 limit 后 HPA 才有「上限内自由发挥」的意义 |

**分层配方（本章的总配方，背下来）**：

1. **VPA 管 requests（Y 轴）**：新服务 `Off` 观察 1~2 周 → 人工落地 → 稳定后 `InPlaceOrRecreate`（k8s≥1.33 + VPA≥1.6），`controlledValues: RequestsOnly`，maxAllowed 给扩容留顶。
2. **HPA 管副本数（X 轴）**：用 CPU `Utilization` 起家；流量画像清晰后升级到自定义指标（§3）摆脱「分母是 requests」的耦合（§1.2）。
3. **CA/Karpenter 兜节点（Z 轴）**：HPA 扩容 → Pending → 节点层加机器；HPA 缩容 + VPA 降 requests → 节点变空 → 节点层收机器。三轴首尾呼应成一个闭环。
4. **启动期尖峰单独治理**：startupProbe 把启动期关进未就绪（§2.3），VPA v1.7+ 可用 CPU Startup Boost 临时加 CPUrequests，而不是把 requests 常年定在启动峰值。

### 4.6 为什么这么设计

- **推荐与执行分离**：Recommender 无状态地「算」，Updater/Admission 小心翼翼地「改」——观测窗口（8 天直方图）与执行窗口（秒级 webhook）完全解耦，各自可独立升级、独立故障。
- **Checkpoint 而不是数据库**：推荐系统的全部状态以 CRD 落 etcd，遵循「K8s 的对象就得是 K8s 对象」哲学——备份（etcd/Velero）、审计（第 1 章 §8）、RBAC 全部免费获得。
- **驱逐走 eviction API 而非 delete**：走的是与 `kubectl drain`、CA 缩容、Karpenter termination 同一条「尊重 PDB 的体面通道」——这是 §6.1「PDB 一并管四家」的机制基础。

---

## 五、节点层伸缩：cluster-autoscaler vs Karpenter

### 5.1 cluster-autoscaler：机制、条件表与拦截清单

CA 的世界观是 **node group 模板**：每种节点组（AWS ASG / GCP MIG / Azure VMSS / 自建的 machine set）由「一个模板 + min/max 边界」描述。它每 `--scan-interval`（**默认 10s**）扫一轮集群（FAQ master 核实，下同）：

**Scale-up 触发**（全部满足才动作）：
1. 存在调度器判定 unschedulable 的 Pod（`Insufficient cpu/memory/…`，第 2 章 §7.3 的 FailedScheduling）；
2. 存在某个 node group，「按它的模板加一台节点」能让这些 Pod 排进去（CA 内置一份调度器模拟器做 dry-run）；
3. 该 group 未达 max、集群未达全局上限。
4. 多 group 可选时由 **expander** 挑：`random` / `most-pods` / `least-waste`（**默认**，选扩容后空闲 CPU 最少的）/ `least-nodes` / `price`（GCE/GKE/Equinix）/ `priority`（按 ConfigMap 优先级，常用于「先 on-demand 后 spot」的顺序）；1.23+ 可链式（`--expander=priority,least-waste`）。

**Scale-down 条件表**（all 同时成立，引用 CA FAQ「How does scale-down work」）：

| # | 条件 | 默认口径 |
|---|------|----------|
| 1 | 节点 requests 水位双低：ΣCPU requests 与 Σmemory requests 均 < allocatable × `--scale-down-utilization-threshold` | **0.5**（DS Pod 与镜像 Pod 计入，可 `--ignore-daemonsets-utilization` / `--ignore-mirror-pods-utilization` 排除） |
| 2 | 其上所有 Pod（除 DS/静态 Pod）都能模拟调度到他处 | CA 用调度器模拟选定「脑内迁移目标」，且**非空节点一次只缩一台**（防空节点可批量，`--max-empty-bulk-delete` 默认 10） |
| 3 | 节点无 `cluster-autoscaler.kubernetes.io/scale-down-disabled: "true"` 注解 | 人工豁免牌 |
| 4 | 低水位持续超过 `--scale-down-unneeded-time` | **10m**（NotReady 节点走 `--scale-down-unready-time` **20m**） |

**「什么 Pod 能挡住 CA 不缩」拦截清单**（FAQ「What types of pods can prevent CA from removing a node?」，§8 问题清单复用）：

| 拦截源 | 说明 | 放行办法 |
|--------|------|----------|
| 限制性 PDB | eviction API 拒绝 | 调 PDB（kube-system 组件想被迁移须配 minAvailable=0 或合理值的 PDB） |
| kube-system 命名空间 Pod（无 PDB） | 默认不迁移 | 给它们配 PDB（CA 0.6+ 起受此约束） |
| 无控制器裸 Pod（非 RS/Job/STS 管理） | 驱逐后无人重建 | 注解 `cluster-autoscaler.kubernetes.io/safe-to-evict: "true"` |
| 带本地存储的 Pod（hostPath、`emptyDir`（非 medium=Memory）） | 数据随节点消失 | 注解 `cluster-autoscaler.kubernetes.io/safe-to-evict-local-volumes: "vol1,vol2"`（须列全）；ConfigMap/Secret/Projected/`medium=Memory` 的 emptyDir 不算本地存储 |
| 调度约束无处可迁（nodeSelector/hostPort/独占型） | 模拟调度失败 | 改亲和约束或加节点 |
| `…/safe-to-evict: "false"` | 明示不许动 | 摘注解 |

缩容动作本身：CA 对节点 taint + 经 **eviction API** 驱逐全部 Pod（尊重 PDB，单个驱逐最多重试 2 分钟；优雅退出给至多 `--max-graceful-termination-sec` **默认 10 分钟**，超时照常停机）。**节点不健康的容错**：unready 节点超过 45% 或 3 台（取大，`--max-total-unready-percentage` / `--ok-total-unready-count`）时 CA 整体停摆自我保护。

**云 provider 配置一句话（各 3 行）**：

| 云 | 要点 |
|----|------|
| AWS | 用 ASG：`--nodes=min:max:<asg名>` 可多个；IAM 需要 autoscaling Describe/SetDesiredCapacity/TerminateInstanceInAutoScalingGroup 权限；EKS 推荐 eksctl/Blueprints 自带 manifest；节点发现靠 tag `k8s.io/cluster-autoscaler/<cluster>=owned` + `k8s.io/cluster-autoscaler/enabled=true` |
| Azure | 用 VMSS：`--nodes=min:max:<vmss名>`（Flexible 编排模式由近年支持线承载）；用集群 autoscaler profile（AKS 托管场景直接在 `az aks` 层面调 `min-count/max-count`，AKS 替你跑 CA）；注意 VMSS Uniform 与 Flexible 的 API 差异 |
| GCP | 用 MIG：`--nodes=min:max:<mig URL/名>`；GKE 场景直接在 node pool 上开 `--enable-autoscaling`（GKE 托管 CA，无需自部署）；自建需给 CA 的 SA 绑 compute.instanceGroupManagers 写权限 |

### 5.2 Karpenter：范式差异——不做 nodegroup，直采云 API

Karpenter（AWS provider 当前 **v1.15.0**，2026-10-10；Azure provider v1.14.5）把 CA 的「模板 group + 云厂商伸缩组」两层模型压缩成一层 CRD：

```
CA：   unschedulable Pod ──► 选 node group（expander）──► ASG +1 ──► 云按启动模板开实例
Karpenter：unschedulable Pod ──► 逐 Pod 计算「要什么机型」──► 直接 CreateFleet/EC2 API 开实例
           （没有 group；NodePool 只是“约束 + 偏好”的声明，不是伸缩组）
```

核心 CRD 两枚（API 组均为稳定 `karpenter.sh/v1`；AWS 侧 NodeClass 为 `karpenter.k8s.aws/v1`）：

| CRD | 角色 | 关键字段 |
|-----|------|----------|
| `NodePool` | 约束域：什么机型可开（requirements）、开多少（limits）、怎么聚合与驱逐（disruption）、权重（weight）、静态池（replicas） | `spec.template.spec.requirements`（instance-family/cpu/arch/zone/capacity-type…) |
| `NodeClaim` | 一个节点一条实例申请单（Karpenter 创建与回收的对象；节点被其 own） | `spec.nodeClassRef`、状态里的 `Launched/Registered/Initialized/Drifted` |
| `EC2NodeClass`（AWS） | AMI/子网/安全组/角色/kubelet 配置 | `amiSelectorTerms`、`subnetSelectorTerms`、`securityGroupSelectorTerms`、`instanceProfile/instanceStorePolicy` 等 |

**consolidation（聚合缩容）三策略**（`spec.disruption.consolidationPolicy`，官方 Disruption 页核实）：

| policy | 语义 | 什么时候选 |
|--------|------|-----------|
| `WhenEmpty` | 只收「空节点」（无 workload Pod 的） | 最保守：绝不驱逐在跑的 Pod |
| `WhenEmptyOrUnderutilized` | 空节点 + 能把负载塞到别处（删）或换更便宜机型（换）的任何节点 | 成本优先，接受驱逐扰动 |
| `Balanced` | **Karpenter v1.14.0 起新增**：按「省的钱 ÷ 驱逐扰动」打分，只做划算的聚合 | 要省钱又嫌上一条太暴力；配合 `karpenter.sh/disruption-cost` 注解标权重 |

配套旋钮：`consolidateAfter`（节点多久没增删 Pod 才纳入聚合，**默认 0s**；`Never` 全停本池聚合）；`expireAfter`（节点寿命上限，**默认 720h=30 天**，`Never` 关）；`terminationGracePeriod`（排水最长时限，到时强删——挡住 PDB/do-not-disrupt 也能封顶）；`budgets`（**缺省一条 `nodes: 10%`**；支持 `reasons: [Empty|Underutilized|Drifted|Unhealthy]`、`schedule: <cron UTC>` + `duration` 做业务时段封网，`nodes: "0"` 即全禁）。

**disruption 全家谱**（按执行顺序，官方 Disruption 页核实：Node Repair → Drift → Consolidation，且任何时刻只进行一种）：

- **Drift**：NodePool/EC2NodeClass 模板哈希对不上的旧节点，按 budget 限速换血（AMI 升级、requirements 变更就靠它滚动）。
- **Expiration**：到达 `expireAfter` 立即开始排水（强制类，**不吃 budgets**，只吃 PDB）。
- **Node Auto Repair**（v1.1.0 起 Alpha，`NodeRepair` gate）：按节点 condition（Ready False/Unknown 30min、GPU/存储/网络/内核/运行时类 condition 30min…）超时后换节点；>20% 池子同病时熔断；`karpenter.sh/do-not-repair: "true"` 可豁免。
- **Terminate-First disruption**（v1.15.0 起 Alpha，`TerminateFirstDrift` / `TerminateFirstRepair`）：容量被占死（ODCR/静态池打满）时允许「先删老的再开新的」——此前只能卡住。
- **Pod 级控制**：`karpenter.sh/do-not-disrupt: "true"`（永久）或 `"30m"`（时长豁免，v1 新形态）；`karpenter.sh/disruption-cost: <int32>`（聚合排序权重，贵的后动）。
- **Spot**：空删默认开；spot→spot 换更便宜实例需 `SpotToSpotConsolidation` gate，且要求 ≥15 个可互换机型的灵活性防「race to the bottom」；中断处理走 SQS（EventBridge→queue，`--interruption-queue`）提前 2 分钟排水。

**与 CA 的逐项异同**：看上报源（同为 unschedulable Pod / 低利用）、看排水通道（同走 eviction API 尊重 PDB）、看对象（一个伸缩组、一个 NodeClaim）、看决策（CA 家 expander 粗粒度到 group，Karpenter 逐 Pod 计算机型组合再比价）。

### 5.3 版本现状与自托管/云上选型

- **AWS**：Karpenter 最成熟（自家后花园，v1.15.0）；CA 是 EKS 老派默认（搭配 Managed Node Groups 时甚至不用自己跑）。
- **Azure**：官方 provider（Azure/karpenter-provider-azure，v1.14.5，活跃）；AKS 另有托管形态（NAP/节点自动供给），经验曲线接近 AWS 的后半程；CA 在 AKS 由控制面托管。
- **GCP**：GKE 托管 CA 非常顺滑；Karpenter 的 GCP provider 长期社区滞后，**生产默认选 GKE 托管 CA**。
- **自托管/on-prem**：CA 有少量裸机 provider（cluster-api/business critical 各厂对接），Karpenter 尚无普适裸机方案；**裸金属世界节点伸缩基本是「容量池水位告警 + 人工/流程扩容」，别硬套云范式**。

**选型决策表**：

| 维度 | 选 CA | 选 Karpenter |
|------|-------|--------------|
| 云上规模小中、节点组画像稳定 | ✅ MNG/ASG 直管 | 也可但收益不大 |
| 机型异构（几十种 SKU 混跑）、spot 占比高 | 可用但 group 数量爆炸 | ✅ 逐 Pod 机型计算是本职 |
| 成本敏感、要空机/低效机自动回收 | scale-down 阈值可调但粗放 | ✅ consolidation 三策略 + budgets 精细 |
| 发布稳定优先、防驱逐 | ✅ 默认偏保守 | 需调 WhenEmpty/budgets 才保守 |
| 多 AZ 均衡、拓扑展开 | 依赖 group 均衡配置 | requirements + topologySpread 原生 |
| 运维惯性/已有 ASG IaC 投入 | ✅ 资产复用 | 重写为 NodePool/NodeClass |
| 非 AWS 主流云 | GKE/AKS 托管 CA 顺滑 | GCP 弱，Azure 跟进期 |

### 5.4 为什么这么设计

- **CA 选「group」是因为云 API 的引用对象是伸缩组**：对它来说节点是「组里 +1 后的同质复制品」，这让模型简单、迁移成本天然为零；代价是无法表达「每个 Pending Pod 的最佳机型」。
- **Karpenter 选「逐 Pod 计算 + 直接开工单」是因为云原生时代机型供给已经是「海量 SKU 超市」**：把调度约束（probe 对 zone/Arch/容量类型/价格）与实例供给在同一次决策里求交集，省掉「人工切 group」这道运维；代价是控制器复杂了几个量级（要模拟调度、比价、处理中断、管 drift），所以选择它的前提是**你的节点画像够异构、账单够肉疼**。

---

## 六、伸缩与其他子系统联动（高阶）

### 6.1 × PDB：四位一体的「体面驱逐」公约

VPA Updater、CA 缩容、Karpenter Termination、`kubectl drain` 四家**走的是同一条 eviction API 通道**——PDB 因此是唯一一个能同时约束四家的对象。两条生产认知：

**① PDB 卡死缩容的排查套路**（以 Karpenter/CA 为例）：

```bash
# 症状：节点明明低利用就是缩不掉
kubectl get pdb -A                                        # 先列 PDB 与 ALLOWED DISRUPTIONS 列
kubectl get pdb -A -o json | jq -r '.items[] | select(.status.disruptionsAllowed==0) | "\(.metadata.namespace)/\(.metadata.name)"'
# ↑ ALLOWED=0 的 PDB 就是拦截者；再对账它的 selector 罩住了哪些 Pod
kubectl get events -A --field-selector reason=Unconsolidatable --sort-by='.lastTimestamp'   # Karpenter 直接把原因写成事件
kubectl describe node <node> | grep -A5 Events            # CA 也会给 ScaleDown 相关 event
```

**② 处置纪律**：`maxUnavailable: 0` / `minAvailable: 100%` 在生产等价于「此应用禁止一切运维动作」——除极少数真正单点，一律改为「minAvailable: N-1」或百分比形态；VPA 的 Recreate/InPlaceOrRecreate、节点更新、CA 缩容全指着这条缝。**发布期配合糟糕的另一个极端是 PDB 太松**：滚动更新 + HPA 缩容 + CA 缩节同时发生时，批次叠加可能突破你的预期底线——发布流程里显式冻结节点层活动（§6.2）。

### 6.2 × 滚动更新：发布期的度量抖动与错峰

发布与伸缩的三个经典冲突：

1. **新 Pod 未就绪先被计入分母/样本**：滚动更新一下拉起一批新 Pod，CPU 启动尖峰会触发 HPA 误判「该扩了」（§2.3 的启动保护就是天然缓冲，但只保 5m 内的 CPU）。
2. **双 RS 并存期指标口径漂移**：滚动中新旧 RS 各一半，HPA 对每个指标的计算对象仍是 Deployment 的**全体** Pod；若新版与老版资源画像差异大（比如新版更省 CPU），扩缩决策会在发布窗口内来回摆动。
3. **发布 × 缩容竞争**：发布本身占住 maxSurge 的名额与资源，恰在此时 HPA 下发缩容或 CA 决定缩节点——名额与席位互相挤。

错峰策略（按序执行）：

```
发布前 → KEDA paused 注解或 HPA minReplicas 临时上调（保发布期冗余）
       → 节点层冻结：CA 加 scale-down-disabled 注解（或 Karpenter budgets.nodes=0）
发布中 → 盯 ScalingActive/ScalingLimited；不接 VPA 落地动作（Updater 会驱逐老 Pod 制造双重滚动）
发布后 → 观察 1~2 个 metric 周期再解冻；如换过容器名/资源画像，同步核对 HPA ContainerResource 引用与 VPA checkpoint 新旧样本
```

📎 迁移期大坑（官方原文强调）：**给已跑的 Deployment 新接 HPA 时，把 manifest 里的 `spec.replicas` 删掉**（否则每次 `kubectl apply` 都会把副本数硬拉回 YAML 值与 HPA 打架）；删字段本身会触发一次「按默认 1」的缩容事故，用官方给的两段式（先 edit 去字段 apply、再从容改 manifest/SSA 转移 ownership）绕开。

### 6.3 × descheduler：一个造新局、一个清旧账

调度器（第 2 章 §1）只看新增 Pod，存量倾斜由 descheduler（第 2 章 §8）清理——它与伸缩体系的共振/冲突清单：

| 场景 | 关系 | 调法 |
|------|------|------|
| descheduler 的 `LowNodeUtilization` 驱逐 | 与 Karpenter consolidation **目的同向、动作竞争**（两边同时选中同一节点驱逐 = 双倍扰动） | 云上 Karpenter 环境建议关掉该策略或把 targetThresholds 提到 70%+，让 Karpenter 主导聚合 |
| descheduler 的 `HighNodeUtilization` | 救 HPA「扩不动」的极端倾斜 | 与 HPA 无冲突，但它驱逐造成的 Pending 高峰可能触发 CA 误扩容——配 `--max-pods-to-evict-per-node` 限流 |
| `RemovePodsViolating*`（拓扑/亲和违例） | 与伸缩正交 | 无特别注意 |
| VPA 落地（驱逐）× descheduler 同刻运行 | 双驱逐源叠加，PDB 是最后防线 | descheduler `evictLocalStoragePods` 等开关与 VPA `updatePolicy.minReplicas` 分别收紧，窗口错开（cron 调度 descheduler） |

一句话：**一个集群同一时刻只保留一个「聚合缩容」的决策者**——Karpenter 在，descheduler 就退到「纠违例、救倾斜」的窄角色。

### 6.4 × PriorityClass/抢占：「占位-被抢-让位」的资源池化配方

经典配方 **overprovisioning（预占节点缓冲）**，目标：消灭「HPA 决策完 → 等节点」的空窗（§2.5 的最后一段延迟）。机制拼装（PriorityClass 数值底座与抢占步骤见第 2 章 §6，不重复）：

```yaml
# ① 一个最低优先级（负数，低于一切业务）
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: {name: overprovisioning}
value: -1
globalDefault: false
description: "占位气球：被任何真实业务抢占"
---
# ② 气球 Deployment：每个 Pod 吃得不多不少，数量让集群常年多留 N 个“座位”
apiVersion: apps/v1
kind: Deployment
metadata: {name: overprovisioning, namespace: kube-system}
spec:
  replicas: 4               # 约等于“常态要预留的节点席位”
  selector: {matchLabels: {app: overprovisioning}}
  template:
    metadata: {labels: {app: overprovisioning}}
    spec:
      priorityClassName: overprovisioning
      containers:
      - name: pause
        image: registry.k8s.io/pause:3.10
        resources:
          requests: {cpu: 500m, memory: 1Gi}   # 单个气球的大小=让 CA 有必要加一台节点的最小步长
---
# ③ 气球自己的 HPA（可选）：业务高峰时多补气球，低谷自动收
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata: {name: overprovisioning, namespace: kube-system}
spec:
  scaleTargetRef: {apiVersion: apps/v1, kind: Deployment, name: overprovisioning}
  minReplicas: 2
  maxReplicas: 20
  metrics:
  - type: Resource
    resource: {name: cpu, target: {type: Utilization, averageUtilization: 10}}
```

运转逻辑：气球 Pending → CA/Karpenter 加节点 → 气球占位运行；真实业务来时挣开气球（**抢占**，因气球优先级最低）→ 业务即刻上节点，气球转 Pending → 节点层再补一台。**「先勤奋扩展、让节点层接嗓、由低优批任务/气球占位被抢」**——同思路另一变体：批任务（`preemptionPolicy: Never`，第 2 章 §6.5 语境）常驻低优吃满闲置容量，在线业务扩容时把批任务挤走，实现「一份池子，两种 SLA」。

---

## 七、容量规划方法

### 7.1 自上而下：从业务指标推副本数（新服务上线前）

```
单 Pod 稳态能力 = 压测拐点（latency SLO 不破 / 错误率不破）对应的 QPS
副本数下限   = ceil( 常态QPS × (1 + 安全系数0.3) / 单Pod能力 )
HPA 目标值   = 单Pod能力的 70% 处对应的指标值（给毛刺留头）
maxReplicas = ceil( 预测峰值QPS × 1.3 / 单Pod能力 )   （安全系数 30%）
```

「安全系数 30%」不是教条而是**端到端延迟预算的产物**（§2.5）：从指标毛刺出现到扩容副本 Ready，分钟级空窗里全靠存量副本的超额水位硬扛——30% 是「空窗期最多涨 30% 流量」的保险。

### 7.2 自下而上：从历史利用率推 requests（存量服务）

```
requests(cpu) = P95(小时粒度, 近14天 usage) × 1.15
requests(mem) = P99(小时粒度, 近14天 usage) × 1.15 + 启动/缓存基线差值
```

- 用「小时粒度分位数」而不是瞬时峰值：瞬时尖刺交给 CPU 超发（不写 limit），常态水位才配进 requests。
- 与 VPA 的同构性：这就是 Recommender 直方图 + decay 半衰期的手工版；上 VPA 后用它的 `target` 与本公式对账，偏差 >20% 时信分位数更细的那个（通常 VPA）。

### 7.3 headroom 与系统预留：给节点层留的 15%

经验值：集群整体的「可调度 requests 水位」控制在 **85%** 上下，即常备 ~15% headroom。它的三个消费者：

1. **突发扩容的空窗座位**（§7.1 的同一份保险，在节点层再看一次）；
2. **系统组件预留**：kubelet/system 的 kube-reserved（第 7 章 §6.4）从 allocatable 里已经切走一块，别再把 headroom 吃满；
3. **碎片**：节点规格与 Pod 规格不可能严丝合缝，装箱率停在 80~90% 是物理常态——剩 10% 碎片是健康不是浪费。

### 7.4 成本维度的三公式

```
单副本小时成本 = (单Pod requests cpu × 单价cpu + 单Pod requests mem × 单价mem) × 利用率折损系数
集群小时成本   = Σ(节点单价) = ceil(总requests/(节点allocatable×装箱率)) × 节点单价
伸缩成本效能   = (峰值容量账单 - 实际容量账单) / 峰值容量账单     ← HPA+CA 的收益度量
                （<10% 说明 maxReplicas/minReplicas 定得太保守或指标目标太松）
```

- spot/RI/savings plan 的混搭比例由 CA 的 `priority` expander 或 Karpenter 的 `capacity-type`/weight 表达（§5）；成本视角的伸缩验收只看一条：**月底的「节点数-时间曲线」应该跟流量曲线形状相似**，若近似一条直线，说明三个轴至少有一个没在转。

### 7.5 为什么这么设计

容量规划的所有公式最终都收敛到两组数：**分位数（过去的尾巴）与延迟预算（未来的空窗）**。把「增几个副本」「留多少 headroom」翻译成「空窗期我要多扛多少流量」，公式就从玄学变成了会计。

---

## 八、常见生产问题清单（症状→根因→定位→处理）

| # | 症状 | 高频根因 | 定位命令 | 处理 |
|---|------|----------|----------|------|
| 1 | HPA 完全不动，TARGETS 显示 `<unknown>` | metrics 链断：metrics-server 没装/APIService 不 Available/NetworkPolicy 拦截 | `kubectl get apiservice v1beta1.metrics.k8s.io`；`kubectl -n kube-system logs -l k8s-app=metrics-server`（链路与判读法见第 1 章 §6.2） | 修 APIService/证书/网络；kind/测试集群记得 `--kubelet-insecure-tls` |
| 2 | HPA 不动但 TARGETS 有值 | ①容器没写 requests（Resource 指标无定义被跳过）②`ScalingActive=False`：目标副本被手动打到 0 进了维护态（§2.6）③ratio 落入 tolerance 0.1 | `kubectl describe hpa` 三 conditions；`kubectl get deploy x -o jsonpath='{.spec.template.spec.containers[*].resources}'` | 补 requests；把期望副本调回 >0；核对目标值与实测的量纲（m vs 整数） |
| 3 | HPA 动了但方向/幅度常「反直觉」 | 缺失指标被保守化（§2.1）；多指标里有一条把建议推大；averageUtilization 分母是 requests 不是 limits | `.status.currentMetrics` 逐项对；`kubectl get --raw /apis/metrics.k8s.io/v1beta1/pods` 人工复算 | 给目标值量纲与分母做单位体检；拆分多指标单独验证 |
| 4 | 自定义指标缺失（FailedGetCustomMetric） | label 没对齐 ns/pod；adapter rules 的 as 名与 HPA 引用名不一致；series 在 Prometheus 里不存在 | §3.3 验证三件套；Prometheus `/api/v1/series` 直查 | 按 §3.3 三坑逐一修；改完 rules 滚动 adapter |
| 5 | metrics-server 数据「慢一拍」 | `--metric-resolution` 默认 60s 未调 | args 里查该 flag | 调到 15s~30s 并评估 kubelet 压力；同时核对 HPA 端到端预算（§2.5） |
| 6 | HPA + VPA 互改 requests「决斗」 | 两轴同管 CPU/内存（§1.2 维度冲突） | VPA `status.recommendation` 与 HPA 目标值交叉排在时间轴上看 | 按 §1.2 三条出路选一条写进规约；首选「HPA 用自定义指标 + VPA 管资源」 |
| 7 | VPA 驱逐循环（Pod 频繁被 evict） | 推荐值在 minAllowed/maxAllowed 边界震荡；OOM 事件注入推高内存推荐反复横跳；`updatePolicy.minReplicas` 未配 | `kubectl get vpa x -o yaml | yq .status.recommendation` 观察 target/uncapped；`kubectl get vpacheckpoint -A` 看样本量 | 加宽 min/maxAllowed；给 updatePolicy 配 minReplicas 与 evictionRequirements；短期改 Recreate→Initial 止血 |
| 8 | CA 缩不动 | PDB 拦截 / kube-system Pod 无 PDB / 本地存储 / 裸 Pod / safe-to-evict:false / 无处可迁 | CA 日志 grep `node ... cannot be removed` 或 pod 级 `unremovable`；§6.1 的 PDB 排查法 | 按 §5.1 拦截清单逐项放行或豁免 |
| 9 | CA 不扩（有 Pending Pod） | node group 到 max；模板塞不进该 Pod（机型太小/约束不符）；云配额（quota）到顶；unready 节点熔断（45%/3） | CA 日志 `--v=4`；`kubectl get events --field-selector reason=NotTriggerScaleUp` 类事件 | 抬 group max/换机型/提云配额/先修 NotReady |
| 10 | Karpenter consolidation 对长时任务「误伤」 | 长 Job/游戏服被 WhenEmptyOrUnderutilized 驱逐 | Pod 事件里 eviction 记录 | 给该 Pod 打 `karpenter.sh/do-not-disrupt: "true"`（或时长形态）；长批处理改 ScaledJob/批队列 |
| 11 | scale-up 后「副本起了但不可用」（镜像冷启风暴） | 大镜像冷拉 × 多副本同刻拉取把节点/仓库打爆；startupProbe 缺失导致未就绪计流 | `kubectl get events --field-selector reason=Pulling`；节点 `crictl images` 核对 | 镜像瘦身/预烘焙进 AMI 或节点预热 DaemonSet；imagePullPolicy 评估；startupProbe 兜底就绪 |
| 12 | 发布期副本数暴涨暴跌 | 滚动更新与 HPA/缩容同时段的度量抖动（§6.2） | 发布时间线 × HPA event 时间线 | 按 §6.2 错峰清单执行；KEDA 环境用 paused 注解 |

---
