# K8s 调度器深入

> 精通路线第 2 章：调度循环、Scheduling Framework 扩展点、打分策略、延迟绑定、抢占、descheduler、自定义调度器、批调度
> 创建时间：2026-10-13
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37），文中标注「v1.xx 起 Beta/GA」均取自官方文档或上游源码，执行时仍以你本地集群版本为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章）。本章直接引用其中的 list-watch / informer / 队列与退避概念，不再重讲。

---

## 零、本文定位与边界

kube-scheduler 看起来像一个「聪明的放置引擎」，但拆开之后你会发现它的真实身份要朴素得多：

**它是一个「一次性约束求解器 + 持续 requeue 的妥协」。**

- **一次性**：对每一个 `spec.nodeName == ""` 的 Pod，调度器基于**此刻**的缓存视图做一次求解，写回一个 `nodeName`。求完之后它就再也不关心这个 Pod——跑了半年之后节点利用率倾斜了，不是调度器的事（那是 descheduler 的事，见 §8）。
- **约束求解，不是全局优化**：它逐 Pod 串行求解，每个 Pod 只看到「前面 Pod 已经做出的决定」。它**不会**回头重排整盘棋，也不保证全局最优——它保证的是「每个决定当时说得过去」。
- **持续 requeue**：解不出来（节点不够、拓扑不满足、卷还没供给）的 Pod 不会丢，会被塞进队列，等集群事件把它「应该可以了」的信号送回来再试。调度器的大部分代码量都花在「什么时候值得重试」上，而不是「怎么选节点」上。

```
你的调度问题，最终都会变成这几类：
  "Pod 一直 Pending 为什么？"      → Filter 拒绝原因 + 队列在哪一档      §1 §7 §12
  "为什么调度到了这台而不是那台？"   → Score/权重/percentageOfNodesToScore §4 §1.7
  "卷没绑上怎么也 Pending？"        → VolumeBinding + WaitForFirstConsumer §5
  "低优 Pod 被杀了"                 → PostFilter 抢占链                    §6
  "整个集群一端热一端冷"            → 打分策略 + descheduler               §4 §8
  "能不能换个调度逻辑？"            → Framework 插件 / 独立调度器          §2 §9
```

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `K8s-API机制深入.md`（第 1 章） | list-watch / informer / resourceVersion / APF / 审计 | 调度器就是靠这些机制订阅 Pod/Node/PVC，不再重讲 informer 原理 |
| `k8s-常用操作手册.md` | nodeSelector / 亲和反亲和 / 污点容忍 / cordon 的 **YAML 用法** | 只讲这些声明进了调度器之后被哪个插件、以什么机制解释 |
| `K8s-资源全览.md` | PriorityClass / TopologySpreadConstraint 字段速查 | 只讲优先级怎么驱动队列排序和抢占 |
| `K8s-Pod生命周期详解.md` | Pod 创建 10 步时间线 | 本文只把其中「第 3~5 步（调度）」拆到扩展点粒度 |

> ❗ **版本标注约定**：文中形如「v1.34 起 GA」「v1.35 起 Beta 默认开」的说法均对照官方文档或上游源码核对过；
> 但 feature gate 默认值可能随 minor 版本漂移，落地前用
> `kubectl get --raw /metrics | grep -i scheduler_queueing` 和
> `kube-scheduler --help | grep feature-gates` 再确认一次。

---

## 一、调度循环全景：scheduler 只做两件事

### 1.1 先看最外层：watch 未绑定 Pod → 决定 nodeName → 发 Binding

kube-scheduler 对外暴露的接口面小得惊人：

```
etcd (apiserver)
   │  watch Pods where spec.nodeName == ""        ← 唯一入口
   │  watch Nodes / PVC / PV / CSINode / Claim...  ← 决策用缓存
   ▼
kube-scheduler
   │  每个 Pod 跑一次「调度上下文」得出 nodeName
   ▼
POST /api/v1/namespaces/<ns>/pods/<name>/binding   ← 唯一出口（Binding 子资源）
   {"target": {"kind":"Node","name":"node-3"}}
```

API 的事就这一进一出： Pod 的 `spec.nodeName` 不是调度器「编辑」出来的，而是向 apiserver 提交一个 **Binding 子资源**创建的。之后的活（拉镜像、起容器）全部交给目标节点的 kubelet——调度器就此放手。

**为什么这么设计**：

- 调度决策天然需要**全局一致的快照**（全集群每个节点还剩多少资源每个 Pod 才知道往哪放），而执行（起容器）天然是节点本地的事。把「决策」集中、把「执行」下放，是控制循环里少见的一边倒分工。
- 串行决策还省掉了一切分布式事务：同一时刻最多一个 scheduling cycle 在跑（后文 §1.2 说明 binding 例外），生态简单到不会有两个调度决定互相踩踏——这也是为什么「多调度器并存」反而是危险配置（§9.2）。

### 1.2 scheduling cycle（串行） vs binding cycle（并发）

一次完整调度叫一个 **scheduling context**，拆成两段（官方 Scheduling Framework 文档定义）：

```
┌─ scheduling cycle（串行，同一时刻全网只有 1 个在跑）─────────────────┐
│  Pop(pod) → PreFilter → Filter(并发扫节点) → PostFilter(可选)      │
│           → PreScore → Score + NormalizeScore → 选出 nodeName       │
│           → Reserve(占位)                    ──────────────┐        │
└────────────────────────────────────────────────────────────┼────────┘
                                                              ▼
┌─ binding cycle（并发，多个 Pod 的 binding 可以同时飞）──────────────────┐
│             Permit(可等待) → PreBind → Bind(发 Binding) → PostBind      │
└─────────────────────────────────────────────────────────────────────────┘
```

为什么这么分两段：

- **scheduling cycle 串行**：Filter/Score 依赖全局视图，串行就能保证「算出的分数基于确定的前序决定」，不需要锁复杂的共享状态。代价是它是整个集团的吞吐瓶颈——这就是为什么后面有那么多「性能妥协项」（percentageOfNodesToScore、OpportunisticBatching、queueing hints）。
- **binding cycle 并发**：Bind 只是一次 API PATCH（几十毫秒），没必要拖住下一个 Pod 的决策。串行的那半段做完「选谁」的结论写入**内部 cache** 立刻交出去，下一个 Pod 的 scheduling cycle 马上开始。
- **前提是「先占位」**：binding 还没落库前，下一个 scheduling cycle 可能已经看到「那台节点其实已经被分出去 2C」。缓存里这个占位就是 **assume 机制**（§1.3）——失败的占位会被主动回滚。

### 1.3 cache 与 snapshot：把「拍快照」和「记占位」分开

调度器内部维护了三份容易混淆的「视图」：

| 视图 | 一句话作用 | 为什么重要 |
|------|-----------|-----------|
| **informer cache**（第 1 章的 Indexer） | 原始订阅来的 Pod/Node/PVC 等对象本体 | 「真相的来源」，但裸用没有拓扑与预占信息 |
| **scheduler cache** | 节点视角的聚合计数：每节点已请求资源、已绑定 Pod、**assume 中的 Pod** | assume = 「我打算把 Pod 放这」，让下一个串行决策立刻看到 |
| **snapshot** | scheduling cycle 开局时对 cache 拍的只读镜像 | Filter/Score 并发读，期间 assume/bind 继续写入 cache 互不打架 |

关键时序（一次成功调度）：

```
T0  pop pod，snapshot = cache 此刻镜像
T1  Filter/Score 全部读 snapshot（节点表在这十几毫秒里不变，可以放开并发）
T2  选定 nodeName → assume(pod, node) 写 cache（占位，同时跑 Reserve 插件）
T3  binding cycle 并发发出 Binding API 请求；成功后 cache 把 assume 转正
T4  binding 失败（409/超时）→ Unreserve 全部钩子反序回滚 + 取消 assume，Pod 回队列
```

❗ **这张表解释了生产上两类常见现象**：

- 「明明日志说 schedule 成功了，但 Pod 在 Pending 卡了几十秒」——assume 到 bind 之间 Binding 没发出去（API 超时、RBAC、extender bind），最终被 Unreserve 回滚重试。
- 「两个调度器并存时偶发 Pod 数超过节点容量」——每个调度器只在自己的 cache 里占位，互相不见，参考 §9.2。

### 1.4 内部三条队列：activeQ / backoffQ / unschedulableQ

**scheduling queue** 是调度器的发动机室，官方社区文档（`scheduler_queues.md`）把它定义成三个承载：

```
                              Pod 创建 / 更新事件
                                    │
                       （PreEnqueue 插件全绿）│
                                    ▼
              ┌──── activeQ（堆，按 QueueSort 排，默认优先级大先出）───┐
              │        ▲    ▲                                          │
              │        │    │ flushBackoffQ（每 1s 一次）               │
              │        │    └───────────┐                              │
              ▼        │                │ 退避到点                      │
        一次 scheduling cycle           │                              │
              │                  ┌─ backoffQ（堆，按到期时间排）───┐     │
      失败 ────┴───┐             │  后退压力大到就来这排队           │     │
              │   │ 期间来了   │  初始 1s, ×2 递增, 封顶 10s      │     │
              │   │ 集群事件   └──────────────────────────────────┘     │
              ▼   ▼                                                      │
        ┌─ unschedulableQ（map，按插件记忆失败原因）──┐                   │
        │  集群事件命中 QueueingHint 就唤醒到            │                   │
        │  activeQ / backoffQ；                        │                   │
        │  flushUnschedulableQLeftover 每 30s 兜底      │                   │
        │  （在队列躺满 30s 才有机会，最坏 60s）        │                   │
        └──────────────────────────────────────────────┘                   │
                             （还有一种 gated：spec.schedulingGates        │
                               挂门的 Pod，进这个表但不计入调度尝试 §11）   │
```

几条**硬事实**（都已核对官方社区文档与配置参考）：

- **activeQ 是堆不是 FIFO**：顺序由 QueueSort 插件（默认 PrioritySort）给——`Less` 先比 priority，再比入队时间戳。所以「优先级」在第一影响区只在排队，而不在 Filter/Score。
- **backoff 是指数退避**：`podInitialBackoffSeconds`（默认 1s）逐次翻倍，封顶 `podMaxBackoffSeconds`（默认 10s），两个参数都写进 KubeSchedulerConfiguration。10 秒封顶不夸张：调度失败不是业务错误，涨上去主要为了避开风暴场景 self-DDoS。
- **unschedulableQ 不是永远的冷宫**：两个后台协程会兜底搬运——`flushBackoffQCompleted` 每 1s 把到点的 backoff 搬回 activeQ；`flushUnschedulableQLeftover` 每 30s 把躺够 30s 的也搬回去，最坏 60s 重试一次。**队列节奏全是硬编码**：30s/1s 不能配。
- **moveRequestCycle shortcut**：如果 Pod 被判定失败的那一刻，恰好有集群事件触发了「搬运请求」（如节点加入），这次失败的 Pod 不进 unschedulableQ，直接进 backoffQ——即“快到下次再试”，优先吃这次事件的红利。
- **为什么这么设计**：调度失败大多不是「永远不行」而是「此刻不行」（卷在供给、某个 Pod 正要退出）。用三档队列把「立即重试 / 退避重试 / 等有戏再重试」分开，比把失败 Pod 全部无脑重排进 FIFO 高效几个量级。

### 1.5 QueueingHints：事件驱动的「精准唤醒」（v1.28 起 → v1.34 GA）

在 QueueingHints 之前，调度器的唤醒逻辑很粗暴：任何 Pod/Node/PVC 变化都会触发搬运请求，把 unschedulableQ 里**所有**失败 Pod 照搬回 activeQ——一个毫无关系的 ConfigMap 更新都可能让 2000 个 Pending Pod 集体空跑一次调度循环。

**QueueingHint**（**v1.28 首次出现，v1.34 起 Stable/GA 且默认开启**，官方 Scheduling Framework 文档原文）把这个模型翻过来：

- 每个「可能拒绝 Pod」的插件（PreEnqueue/PreFilter/Filter/Reserve/Permit 这一组）实现 **EnqueueExtensions** 接口，在启动时注册：**「我关心什么事件 + 事件命中后我给 Pod 算一个 QueueingHint（重新排队 or 跳过）」**。
- 事件来了，只问这个 Pod 的「拒绝者」们：这次的 Node Add 会不会让你改判？所有有意见的插件都说「可能」才醒；否则继续躺着。
- 例：某 Pod 上次被 NodeResourcesFit（CPU 不足）挡下。一条「Node.Label 变化」事件到来时，不会唤醒它（Label 变化跟 CPU 没关系）；一条「Node.capacity 变大/Node 新加」事件才会。

| 收益 | 体感 |
|------|------|
| 空跑次数骤降 | `scheduler_schedule_attempts_total{result=unschedulable}` 在大集群可降一个量级 |
| 事件发生→重试的延迟更小 | 不用等 30s leftover flush |
| 排队公平性变好 | backoffQ 不再被无关事件驱动的流量塞爆 |

❗ **体感注意**：开了 QHint 之后，「为什么我配的 PVC 绑好了 Pod 还躺着」这类问题大概率是**事件没被任何插件认领**或 hint 判定「这个事件没用」。官方也给指标观察：`scheduler_queue_incoming_pods_total{queue,event}`（重启进各队列的事件统计）和 `scheduler_pod_scheduled_after_flush_total`（30s 兜底搬运的命中数，涨得快说明 hint 配错了或者事件链路有洞）。

### 1.6 大队列吞吐优化：OpportunisticBatching（v1.35 起 Beta，默认开启）

短时间拉起一个 300 副本的 Deployment 时，这 300 个 Pod 的约束**逐字节相同**——逐个全量 Filter/Score 纯属浪费。OpportunisticBatching（feature gate 名 `OpportunisticBatching`，**v1.35 起 Beta 且默认开启**）就是针对这个流量形态：

- Pod 之间如果「调度签名」相同（签名的原料来自各 Filter/Score 插件实现的 Sign 扩展），在 **0.5 秒**缓存窗口内直接复用上一次的 Filter/Score 结果，只对上次选中的节点做 rescore。
- 不适用：有 Pod 亲和/反亲和、topologySpreadConstraints、DRA(ResourceClaim)、由 DRA 支撑的扩展资源的 Pod——这些都会影响邻居 Pod 的决策，没法安全复用。
- 自定义 Filter/Score 插件想吃到这个红利，必须额外实现 **SignPod**（上游接口名 `SignPlugin`），否则调度器会退让到「凡用了开启插件的 Pod 一律不批处理」。

### 1.7 percentageOfNodesToScore：大集群的精度-延迟折中（Kernel 调参项）

默认调度逻辑是「找出全部可行节点再打全部分」——在 5000 节点集群上太贵。`percentageOfNodesToScore`（`KubeSchedulerConfiguration` 顶层或 profile 级）定义「找到多少可行节点就收手」：

| 参数 | 取值逻辑（官方 perf-tuning 文档已核对） |
|------|----------------------------------------|
| 默认值（配置 0） | 随集群规模线性变化：**100 节点→50%、5000 节点→10%、下限 5%** |
| 硬保底 | 至少会检查 **100 个可行节点**（minFeasibleNodesToFind，源码硬编码） |
| 设成 100 | 打全部分——追求最佳放置的场景（如贵重大任务） |
| 设得过低（<10） | 官方明确警告：调度质量可能明显变差，除了「只要塞得下就不挑」的场景别用 |

遍历还有一个细节值得背：调度器扫节点是**按 zone 轮询的 round robin**（…node1@zoneA、node2@zoneB、node3@zoneA、node4@zoneB…），每个 Pod 接着上一个 Pod 停下的位置继续——避免所有 Pod 都集中看 zone 头部节点造成 hotspot。

> ❗ 联动注意 §1.6：OpportunisticBatching 想要最激进的效果，需要你显式关闭内建默认 spread（`defaultingType: List` + 空 `defaultConstraints`）并把 InterPodAffinity 的 `ignorePreferredTermsOfExistingPods` 置 true（官方 perf-tuning 文档注明）。这是因为默认 spread 会在邻居 Pod 落位变化时推翻签名缓存。

---

## 二、Scheduling Framework 完整扩展点地图

Scheduling Framework 自 **v1.19 起 Stable**。理解它一句话就够：**「调度主流程就是一串扩展点排的流水线，绝大多数功能只是流水线上的插件，可以替换、可以加塞」**。调度器本体（那些考虑负载与亲和的家伙）自己也全是插件实现的。

### 2.1 流水线全景

```
                      Pod 进队列
                          │
                    PreEnqueue ──┐
                          │      │ 任一插件非 Success → gated 列表
                          ▼      │  （不会打上 Unschedulable 状态，见 §11）
                    [activeQ 排队]
                          │ QueueSort(Less) 默认 PrioritySort
                          ▼
            ╔═════ scheduling cycle（串行）═════╗
            ║  PreFilter   ──►可为 Filter 预处理、可提前拒绝   ║
            ║  Filter      ──►每节点并发跑；任一拒绝→节点出局  ║
            ║  PostFilter  ──►全部拒绝才调用；抢占就住在这    ║
            ║  PreScore    ──►为 Score 准备 CycleState        ║
            ║  Score       ──►每节点每插件打 [0,100] 整分     ║
            ║  NormalizeScore─►插件内分数映射到 [0,100]        ║
            ║  Reserve     ──►占位；对应 Unreserve 回滚      ║
            ╚═════════════════════════════════════════════╝
                          │
            ╔═════ binding cycle（并发）═════╗
            ║  Permit   ──►approve/deny/wait(超时)      ║
            ║  PreBind  ──►绑定前的实际动作（供给/挂载） ║
            ║  Bind     ──►发 Binding API；一个接手即止  ║
            ║  PostBind ──► informational 收尾          ║
            ╚══════════════════════════════════════════╝

   旁路：EnqueueExtensions（含 QueueingHint）
        插件实现这个接口后，集群事件进来会先过它的 hint 函数，
        决定闷在 unschedulableQ 里的 Pod 是否放回 activeQ/backoffQ
        （§1.5——反向作用于流水线的起点）。
```

### 2.2 扩展点逐条解释（阶段 / 作用 / 失败去向 / 内建插件）

| 扩展点 | 属于哪段 | 干什么 | 失败后的去向 | 内建代表 |
|--------|---------|--------|--------------|---------|
| **PreEnqueue** | 入队前 | 放行/拦截 Pod 进入 activeQ | 任一插件非 Success → gated 列表，Pod 状态 `SchedulingGated`，**不记 Unschedulable** | SchedulingGates（§11） |
| **QueueSort** | activeQ 内 | 给 activeQ 排序，`Less(e1,e2)`，**同一时刻只能启用 1 个** | — | PrioritySort（默认：priority 大在前，平级看入队时间） |
| **PreFilter** | scheduling | 预处理 Pod/集群信息，也可提前拒绝 | 失败 → cycle 中止 | NodeResourcesFit / InterPodAffinity / PodTopologySpread / NodePorts / VolumeBinding（都用它做汇总计算） |
| **Filter** | scheduling | 对每个节点并发判定「能跑/不能跑」；任一插件判负该节点出局 | 全灭 → 转 PostFilter；部分过滤记 `Unschedulable` 或 `UnschedulableAndUnresolvable`（后者连抢占都不试） | TaintToleration / NodeAffinity / NodeResourcesFit / VolumeBinding / NodePorts / NodeName / NodeUnschedulable / Volume* |
| **PostFilter** | scheduling | Filter 全败后的补救路径 | 任一插件返回 Schedulable 就停止；典型实现=**抢占** | DefaultPreemption |
| **PreScore** | scheduling | 给 Score 准备共享状态（CycleState） | 失败 → cycle 中止 | TaintToleration / InterPodAffinity / PodTopologySpread |
| **Score** | scheduling | 每节点每插件打 [0,100] 整分 | 失败 → cycle 中止 | NodeResourcesFit / BalancedAllocation / ImageLocality / NodeAffinity / PodTopologySpread / InterPodAffinity / TaintToleration / VolumeBinding（条件见下） |
| **NormalizeScore** | scheduling | 插件自己的原始分 → [0,100] 归一（每插件每 cycle 一次） | 失败 → cycle 中止 | 大部分 Score 插件都挂这个（官方文档示意用 BlinkingLightScorer 例子） |
| **Reserve / Unreserve** | scheduling 尾 | 「占位」两阶段提交；任何后续失败反序调 Unreserve | Reserve 失败不再执行后续插件，整个 Phase 失败 | VolumeBinding（占位 PVC 假设） |
| **Permit** | scheduling 尾→binding 前 | approve / deny / wait(timeout) 三态 | wait 超时转 deny → Unreserve 后回队列 | 框架自带没有；外部如 Coscheduling(gang) 用它等齐 |
| **PreBind** | binding | 真正动手：供给卷、预留资源等 | 失败 → Pod 回队列 | VolumeBinding（on-the-fly 绑 PVC） |
| **Bind** | binding | 发 Binding 调用；一个插件说「我来」后面全跳过 | Error → Unreserve + 回队列 | DefaultBinder |
| **PostBind** | binding 尾 | informational 清理 | — | — |
| **EnqueueExtensions** | 队列旁路 | 注册事件 + QueueingHint（§1.5），决定被拒 Pod 何时回队 | — | 能拒 Pod 的插件基本都实现（NodeResourcesFit/VolumeBinding/InterPodAffinity…） |

官方文档没有给「扩展点总数≥N」的嘴硬话术，我按 v1.37 配置参考点出来的是上面这 **13 个单 Pod 扩展点 + EnqueueExtensions 反向接口 + placementGenerate/placementScore/podGroupPostFilter 三个 Workload 专用扩展点（§2.3）**。背数字意义不大，背「流水线位置 + 出失败去哪」才有生产力。

**为什么这么设计（三段式回顾）**：

- **PreXxx 存在是为了省 CPU**：PreFilter/PreScore 先把要跑 N 个节点 × 循环计算的公共部分（如「这个 Pod 想要什么端口」「亲和顶点是谁」）算一次塞进 CycleState，后面每个节点复用。
- **Reserve/Permit 存在是为了「可撤销」**：绑定并发意味着「决策→生效」之间有窗口，Reserve 把插件的私有状态先占住，Permit 把「还要不要等外部信号」的暂停交还给插件。
- **Unreserve 反序回调且不允失败**：官方文档原话——「Unreserve 必须幂等且不允许失败」。因为失败路径上能补救的都补救过了，这里只是清扫。

### 2.3 v1.37 新长出来的三个扩展点（Workload/PodGroup 调度）

**v1.37** 起上游开始内置「Workload 级」调度（feature gate `GenericWorkload`，**Beta、默认关**），配套多出三个扩展点（**只在开启 Workload 调度时才有意义**）：

| 扩展点 | 对应关系 | 默认插件 |
|--------|---------|---------|
| **placementGenerate** | 为 PodGroup 生成候选 placement（节点集合/拓扑域集合） | TopologyPlacement |
| **placementScore** | 为可行 placement 打分（类似单 Pod 的 Score 但粒度是组） | PodGroupPodsCount / NodeResourcesFit（MostAllocated 策略） |
| **podGroupPostFilter** | 单 Pod PostFilter 的组级版本（组级抢占） | DefaultPreemption |

兄弟门控：`CompositePodGroup`（**v1.37 起、Alpha、默认关**）支持层级组；`TopologyAwareWorkloadScheduling` 承担拓扑感知的 PodGroup 调度。

> ❗ 现阶段把这三点**当方向而非生产功能**对待：默认关、API 还在 Beta/Alpha。如果你在等「K8s 原生 gang scheduling」，盯的就是这条线，见 §10.4 的收敛判断。

### 2.4 配置层：profiles 与 multiPoint

- 配置 API：`kubescheduler.config.k8s.io/v1`（**v1beta3 已在 v1.29 移除**，v1.25 起 v1 Stable）。
- **profiles**：一份进程内可以挂多个 profile（`schedulerName` 各自唯一），Pod 用 `spec.schedulerName` 选择被哪个 profile 调度。❗ 所有 profile **必须共用同一个 QueueSort 插件**（因为调度器内部只有一条队列，见 §1.4）。
- **multiPoint**：插件大多数扩展点都要挂的话用 multiPoint 一次声明；具体扩展点 > multiPoint > 默认插件的优先级顺序生效（源码与官方配置参考均有说明）。
- 最小配置样例：

```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
clientConnection:
  kubeconfig: /etc/kubernetes/scheduler.conf
profiles:
  - schedulerName: default-scheduler        # 缺它谁都没活路：Pod 默认走这个 profile
  - schedulerName: no-scoring-scheduler
    plugins:
      preScore:
        disabled: [{name: '*'}]
      score:
        disabled: [{name: '*'}]
```

❗「default-scheduler 这个 profile 必须存在」不是建议而是硬要求：Pod 不写 `schedulerName` 时 apiserver 会默认填 `default-scheduler`，没这个 profile 的名字任何组件都领不到这些 Pod。

---

## 三、内建插件地图（v1.37 默认开启清单）

全部默认插件及其挂载点（官方 `Scheduler Configuration reference` 已核对，一个插件可以挂多个扩展点）：

| 插件 | 参与的扩展点 | 干什么（一句话） | 备注 |
|------|-------------|------------------|------|
| **PrioritySort** | queueSort | activeQ 顺序：priority 大优先，平级按入队时间 | 你想换排序只能整组换掉（同 profile 只能 1 个） |
| **DefaultPreemption** | postFilter（+podGroupPostFilter） | Filter 全败后尝试赶走低优 Pod 腾位置 | 唯一的抢占实现（§6），可配 `minCandidateNodesPercentage/Absolute` |
| **DefaultBinder** | bind | 真正发 Binding API 请求 | bind 必配；要自定义 Bind 插件也要保留它兜底 |
| **NodeResourcesFit** | preFilter, filter, score（+placementScore） | 看节点剩余资源是否够 Pod 请求；打分 3 策略选 1（§4） | 打分默认 LeastAllocated |
| **NodeResourcesBalancedAllocation** | score | CPU/内存利用率越「持平」分越高 | 防「CPU 满了内存还剩一半」的极端 |
| **NodeAffinity** | filter, score | nodeSelector + nodeAffinity；preferred 项进 score | `addedAffinity`（v1.20 起 Beta）可按 profile 加规则 |
| **InterPodAffinity** | preFilter, filter, preScore, score | Pod 间亲和/反亲和 | 大集群慎用（官方提示数百节点级别就有明显开销） |
| **TaintToleration** | filter, preScore, score | 污点过滤 + PreferNoSchedule 进 score | NoExecute 的来这挡不住已运行 Pod |
| **PodTopologySpread** | preFilter, filter, preScore, score | topologySpreadConstraints 硬过滤 + 软打分 | 默认约束进 §3.1；ClusterAutoscaler 兼容性见 §12 |
| **NodePorts** | preFilter, filter | hostPort / NodePort 冲突检查 | hostNetwork Pod 必检 |
| **NodeName** | filter | `spec.nodeName` 精确匹配 | DaemonSet 的 Pod（controller 填了 nodeName）就是靠它秒过 |
| **NodeUnschedulable** | filter | `kubectl cordon` 打的标记（`spec.unschedulable=true`） | 只挡新进，存量不动 |
| **ImageLocality** | score | 节点上已有的镜像按大小计分（大镜像优先复用） | 粒度粗，常因分镜像_tag 的策略而失效 |
| **VolumeBinding** | preFilter, filter, reserve, preBind, score | PVC/PV 匹配、WFFC 延迟绑定、CSIStorageCapacity 检查 | score 需 `StorageCapacityScoring` 门控（v1.37 Beta 默认开，§4.4） |
| **VolumeRestrictions** | filter | RBD/ISCSI/FC 等「单写多读（RWO）」已占用的冲突检查 | 仍在用的 in-tree 卷类型才相关 |
| **VolumeZone** | filter | PV nodeAffinity 里的 zone 与节点 zone 匹配（legacy in-tree） | 新存储都走 CSI，逐渐退出历史 |
| **NodeVolumeLimits** | filter | 每节点 CSI 挂载卷数量上限（`attachLimit`） | 限幅受 `VolumeLimitScaling` 门控；未装驱动的节点可判负 |
| **EBSLimits / GCEPDLimits / AzureDiskLimits** | filter | 老 in-tree 云盘挂载上限 | 云盘 in-tree 已废（v1.27 移除），往 CSI 迁后只剩装饰 |
| **CinderLimits** | filter（**非默认**，需显式启用） | OpenStack Cinder 卷数上限 | — |
| **SchedulingGates（PreEnqueue）** | preEnqueue | 带 `spec.schedulingGates` 的 Pod 挡在门外 | §11 |
| **TopologyPlacement** | placementGenerate | Workload/PodGroup 候选拓扑 placement（Workload 开启时） | §2.3 |
| **PodGroupPodsCount** | placementScore | 组 placement 打分（按可放置数） | §2.3 |

**这么分层的原因**：让「为什么这台不行」能归因到具体插件——你 `describe pod` 看到的 `Insufficient cpu` 是 NodeResourcesFit.Filter 的返回信息，`node(s) had untolerated taint` 是 TaintToleration.Filter 的返回信息。每条 Pending 报错都能精确对号到上面某一行。

### 3.1 默认的 topologySpread 约束（你配可能根本不知道）

如果你没给 Pod 写 topologySpreadConstraints，也没自己配 PodTopologySpreadArgs，kube-scheduler 使用内建默认约束（**v1.24 起 Stable**）：

```yaml
- maxSkew: 3
  topologyKey: "kubernetes.io/hostname"
  whenUnsatisfiable: ScheduleAnyway
- maxSkew: 5
  topologyKey: "topology.kubernetes.io/zone"
  whenUnsatisfiable: ScheduleAnyway
```

也就是说：**kube-scheduler 天然就是个「轻度倾向于摊开」的调度器**，不是 binpack。想关：pluginConfig 里 `defaultingType: List` + `defaultConstraints: []`。

字段版本（都已核对官方 topology-spread 文档）：

- `matchLabelKeys`：**v1.27 起 Beta 默认开**；v1.34 起 `MatchLabelKeysInPodTopologySpreadSelectorMerge` 把 keys 显式合并进 labelSelector（行为小改动，升级注意）
- `nodeAffinityPolicy` / `nodeTaintsPolicy`（NodeInclusionPolicy 思路）：**v1.26 起 Beta → v1.33 GA**
- `minDomains`：门控从 **v1.28 起默认开**，v1.30 之后不再需要门控
- Pod 亲和的 `matchLabelKeys`/`mismatchLabelKeys`：**v1.29 起 Beta → v1.33 GA 且锁定**（默认值已不可关）

---

## 四、打分与资源拟合：Score 到底在算什么

### 4.1 [0,100] 语义与权重叠加

每个 Score 插件对单个节点返回 `[0,100]` 的整数（上游常量 `MaxScore = 100`、`MinScore = 0`），NormalizeScore 只做「把插件自己的原始值映射回 [0,100]」这一件事。最终节点总分：

```
totalScore(node) = Σ  plugin.Score(node) × plugin.weight
```

权重定义在 plugin 配置里（`plugins.score.enabled[].weight`），只对 Score/PlacementScore 有效，其他扩展点写 weight 没意义。

❗ **默认权重不要背数字**：上游可能微调，而你自己集群默认配置的真实打开方式是：

```bash
kube-scheduler --write-config-to=/tmp/defaults.yaml && cat /tmp/defaults.yaml
# （--write-config-to 是官方支持 flag：把默认配置导出后退出，不动集群）
```

常见默认（仅供体感，以你导出为准）：InterPodAffinity 与 PodTopologySpread 的权重大于 1（历史上为 2），其余插件为 1。

**为什么这么设计（归一化必曲线）**：如果不归一直接求和，某一插件的理论上限变化（ImageLocality 是按「镜像总大小」打的，节点之间可以差出几百）会淹没其他插件的 [0,100]。归一化保证「权重 1 个刻度 = 最高 100 分的可比较贡献」，你乘上去的 weight 才有确定语义。

### 4.2 NodeResourcesFit 三选一：spread 思维 vs binpack 思维

`NodeResourcesFit` 是打分主力，其 `scoringStrategy.type` 三选一（KubeSchedulerConfiguration v1 的 `NodeResourcesFitArgs`，已核对）：

| 策略 | 直觉 | 分数含义 |
|------|------|---------|
| **LeastAllocated**（默认） | **spread** | 节点已请求占比越低 → 分越高；副本论均匀铺开，故障半径小 |
| **MostAllocated** | **binpack** | 节点已请求占比越高 → 分越高；小副本量聚合到少数节点，配合 CA 缩容 |
| **RequestedToCapacityRatio** | **自定义曲线** | 你直接给 `shape` 点列：利用率 x → 分数 y（x:0~100，y:0~10），实现「40%~80% 利用率最优」之类的任意策略 |

配套参数（官方配置参考已核对）：

- `resources`：默认 `cpu` 与 `memory` 各权重 1；允许 1~100 的整数权重
- `ignoredResources` / `ignoredResourceGroups`：**只影响 filter** 不参与打分（如临时屏蔽某 vendor 资源视为「不参与可容纳判断」）
- `RequestedToCapacityRatio.shape`：点必须按 utilization 升序；分数域 0~10（注意域和 [0,100] 的归一是插件自己映射的）

`NodeResourcesBalancedAllocation` 是另一个独立打分插件：分数 = `（1 - |cpuFraction - memoryFraction|) × 100` 直觉——CPU/内存占比越「类似」越高分。它和 LeastAllocated 一起把默认调度塑造成「摊得开又不畸形」的风格。

**为什么这么设计**：调度器没有一个「真正最优」目标，只有多种「说得过去」的目标。LeastAllocated 求稳（副本的故障半径），MostAllocated 求省电（把空节点让出来给 Cluster Autoscaler 收），RequestedToCapacityRatio 求贴合你自己的 SLO 曲线。不存在「正确的默认」，只存在「贴业务的策略」。

### 4.3 亲和类打分实现

- **NodeAffinity(preferred)**：每条满足的 preferred term 把 `weight`（1~100）累加到基础分，再归一。多条 preferred 可以叠加——这是你拿「软偏好」拼策略的主要手段。
- **InterPodAffinity(preferred)**：对每个节点算「这里已经有多少符合你 preferred 条件的关联 Pod」，正相关打高分；`hardPodAffinityWeight`（插件参数）可以让「满足硬亲和的已有 Pod」也参与打分（默认 0）。
- **TaintToleration**：PreferNoSchedule 的污点节点扣分，相当于软反亲和。
- **PodTopologySpread(ScheduleAnyway)**：把「调度过去后 skew 更小」的域名打高分（§3.1 默认约束就是靠这条软性存在）。

### 4.4 VolumeBinding 也加入了打分：StorageCapacityScoring（v1.33 起 → v1.37 Beta 默认开）

历史上打分插件从没考虑过「这台节点还剩多少可供给的存储空间」——Filter 只关心「能不能放」。`StorageCapacityScoring`（此前 v1.32 叫 `VolumeCapacityPriority`、v1.33 改名并加上动态供给支持，**v1.37 起 Beta 且默认开启**）给 VolumeBinding 挂上 score 扩展点：

- 打分依据：该节点可见的 CSIStorageCapacity 剩余容量，针对 Pod 的 WFFC 卷请求，给可供给容量相对充足的节点更高分
- 形状可在 `VolumeBindingArgs.shape` 配：默认 `utilization 0 → 10 分`、`utilization 100 → 0 分`（y 域 0~10 再经插件归一）
- 只对「支持 Storage Capacity 的 CSI 卷」（含 CSI 支撑的本地存储）有意义；`VolumeBindingArgs.bindTimeoutSeconds` 默认 600s 单独管绑卷超时

**收益场景**：本地盘 CSI（LVM/TopoLVM 类）上调度有状态服务时，调度器不再蒙眼选节点——不会把一个 500Gi 的请求往只剩 200Gi 余量的节点上塞（过去要靠 Pending→供给失败→重试的循环兜底）。

---

## 五、VolumeBinding 与延迟绑定：存储拓扑感知

### 5.1 为什么需要 WaitForFirstConsumer

如果 StorageClass 用的是 `volumeBindingMode: Immediate`（默认），PVC 一创建就被 PV controller 绑定/供给——此时还没有任何 Pod 用它，供给器不知道 Pod 会被放到哪：

```
场景：PVC 要求 SSD，集群跨 3 个 zone，provisioner 直接供给在 zone-a
       ↓
Pod 约束/资源打分把它放到 zone-b 的节点
       ↓
PV nodeAffinity = zone-a ≠ Pod 落点 zone-b → VolumeBinding.Filter 永远失败 → 死局
```

**`volumeBindingMode: WaitForFirstConsumer`（WFFC）** 把这个顺序反过来：**先挑 Pod 的节点，再在那个节点能访问的拓扑里供给卷**。

### 5.2 全链路：调度器 × PV controller × external-provisioner

```
  用户创建 Pod（引用 PVC，SC = WFFC）
        │
  VolumeBinding.PreFilter   ── 汇总「这 Pod 需要哪些 PVC / 有哪些已绑哪些没绑」
        │
  VolumeBinding.Filter      ── 对每个节点检查：
        │                     ① 已绑定的 PVC：PV 的 nodeAffinity/zone 是否覆盖此节点
        │                     ② 未绑定的 WFFC PVC：此节点是否在 SC allowedTopologies
        │                        范围内；若驱动开了 StorageCapacity，此节点拓扑里的
        │                        CSIStorageCapacity 够不够（v1.24 起 GA）
        │                     ③ 本地/local 类 PV：是否还在、没被抢
        ▼
  Filter 通过 → 打分（可选 StorageCapacityScoring，§4.4）
        │
  VolumeBinding.Reserve     ── 「占位假设」：把这个 WFFC PVC 的未来写进内部状态
        │
  调度器给 PVC 打注解  volume.kubernetes.io/selected-node: <node-3>
        │   （这是 调度器 → provisioner 的「合同」：卷必须在 node-3 可达的拓扑里供给）
        ▼
  external-provisioner（CSI sidecar）watch 到带注解的 PVC
        │   在 SC 允许的、包含 node-3 的拓扑里 CreateVolume → 生成 PV
        │   （PV 自带正确的 nodeAffinity）
        ▼
  PV controller 把 PVC ↔ PV 真正 Bound
        │
  Pod 的 Bind 早于或晚于 Bound 成功都可能发生；
  若绑定超时（VolumeBindingArgs.bindTimeoutSeconds，默认 600s）→
      取消假设、回队列重试，必要时重选节点
```

**为什么这么设计**：把「选节点」和「供给卷」解耦成两次决策有两个好处：

- 拓扑约束由**供给器自己守**（它最知道自己的盘能从哪访问），调度器只通过一个注解传达意图，不需要懂任何 vendor 知识。
- **CSIStorageCapacity（v1.24 GA）** 允许 CSI 驱动上报「每个拓扑段还剩多少容量」，调度器在 Filter 就做容量粗筛——但官方文档明确写了「只能比较大小，**可能基于过期信息做决策**」，失败再靠重试。这是 Kubernetes 调度里典型的「乐观假设 + 失败重试」模型：求快不求准。

### 5.3 失败侧的两个必知

- **供给失败重选节点**：capacity 信息过期/并发抢盘后，provisioner 在选中拓扑里供不出来 → PVC 的 `selected-node` 注解被撤掉（reset），Pod 回队列重跑调度。日志里会看到卷在「provision → fail → delete → re-provision」的循环。
- **`nodeName` 旁路时 WFFC 死等**：官方 StorageClass 文档明确警告——Pod 直写 `spec.nodeName` 会**绕过调度器**，WFFC 的 PVC 拿不到 `selected-node` 注解，导致 provisioner 永远不供给、Pod 永远 Pending。修：`spec.nodeName` 换成 `nodeSelector: {kubernetes.io/hostname: <node>}`。

### 5.4 其他卷类插件的职责边界

| 插件 | 管哪一段 | 不参与什么 |
|------|---------|-----------|
| VolumeRestrictions | in-tree 卷的「单写多读」冲突（RBD/ISCSI/FC 被另一节点占用） | CSI 卷由自家驱动管，不查这 |
| VolumeZone | 老 in-tree PV 的 zone 标签与节点 zone 匹配 | CSI PV 用 nodeAffinity 表达拓扑，不走它 |
| NodeVolumeLimits | 每节点 CSI attach 数量上限（CSINode 的 attachLimit） | 未装对应 CSI 驱动的节点也会被它判负（受 `VolumeLimitScaling` 门控影响），别把「新加节点没装驱动」当成资源问题查半天 |

---

## 六、抢占（Preemption）机制：被高优 Pod 赶走的那群 Pod 到底经历了什么

### 6.1 触发点与硬原则

- **触发点仅此一个**：PostFilter 扩展点。Filter 全灭（一个 feasible 节点都没有）时才轮到 DefaultPreemption 尝试；但凡有一个节点放得进，抢占**根本不会启动**。
- **硬原则**：`优先级高 → 可抢更低的`，**同优先级互不相抢**（官方文档原话：preemption must not happen when the pending pod has equal or lower priority than the victims）。所以「两个同 100 万优先级的 Deployment 互相驱逐」永远不会发生。
- `preemptionPolicy: Never`（**v1.24 起 GA**）：这个 PriorityClass 的 Pod 排队位置靠前，但**绝不驱逐别人**——适合「我想插到队首但别动线上业务」的批任务心态。注意它自己也**可能被更高优 Pod 抢**（preemptionPolicy 只管它自己是否发起）。

### 6.2 PriorityClass 数值底座（都核对官方文档）

- 取值范围 `[-2^31, 1000000000]`；`system-cluster-critical=2000000000`、`system-node-critical=2000001000` 是集群自带的两个最大级别（保留给系统组件）。
- 不配 `priorityClassName` 时，如果有 `globalDefault: true` 的 PriorityClass 就用它的值，否则为 0。
- 数值直接决定 activeQ 排序（§1.4）与抢占资格——PriorityClass 是「排队位置」和「杀伐权」绑定在同一数字上。

### 6.3 一次抢占的完整步骤（DefaultPreemption 干的事）

```
step 1  Filter 全灭 → DefaultPostFilter(DefaultPreemption) 被调起
step 2  findCandidates（并发干跑 dry-run，对每个候选节点）：
        「把这台节点上所有 priority 低于 P 的 Pod 假装删掉，重跑 P 的 Filter，
         通得过吗」——通不过 → 这节点出局（连尝试都不值）
        （候选规模被 minCandidateNodesPercentage(默认10%) /
          minCandidateNodesAbsolute(默认100) 限制，防全集群干跑）
step 3  遇害者选择：在能成的节点集合里，
        优先「违反 PDB 最少 → 要驱逐的高优 Pod 最少」的节点;
        官方明确：**PDB 是 best effort**——找不到不违反 PDB 的方案照样抢
step 4  发起驱逐：对每个遇害者直接 DELETE 删 Pod（尊重其
        terminationGracePeriodSeconds 优雅退出）——注意抢占**不走
        /eviction 子资源**，PDB 是在 step 3 选遇害者时由调度器自己查的
        （best effort：找不到不违反 PDB 的受害组合就照样抢）
step 5  给 P 记 `status.nominatedNodeName`（官方承诺的可见证据）；
        注意：**此刻不直接 Bind**
step 6  P 回到队列；等遇害者真正腾出位置，下一轮调度把 P 放上候选节点
        （若更高优 Pod 同时抢了同一个节点，P 放弃坐等——也被允许
        中途另选别的节点，官方说明 nominatedNodeName 没强约束力）
```

### 6.4 关键设计问答

- **为什么不直接 Bind、还要主动等待清理**：遇害者的优雅退出可能持续几十秒——位置没腾出来，Bind 了也起不来。把「占位意图」写在 nominatedNodeName + 等待下一轮，比「强写 nodeName 然后尴尬地挂在 Termination 警告里」干净得多。
- **Inter-Pod affinity 上的连环坑**：「Pod P 对节点上某低优 Pod 有亲和关系」时，赶走对方反而让 P 失去调度条件——官方文档指出此时**该节点完全不被考虑**（node ineligible）。
- **不做 cross-node preemption**：P 要落到节点 N、但它的反亲和在**别的节点**——调度器不会去别的节点追杀（官方列出作为 known limitation）。
- **QoS 不参与遇害者选择**：官方明示「preemption logic does not consider QoS」——想要 QoS 保护请走节点压力驱逐（kubelet 那边才是 QoS 顺序）。
- **抢占风暴的成因**：大流量 Pending 高优 Pod + 小节点池 → 候选 dry-run 每次都全集群扫描 → victims 反复被扫 → 大量重复驱逐与 InvalidDisruptionBudget。对治：给优先级分层设计节流（少用顶级 classes、给批任务用 `preemptionPolicy: Never`）、给重要服务配 PDB、让 Cluster Autoscaler 快速补位、以及关注上游 `SchedulerAsyncPreemption` 门控（**已在 v1.37 源码存在，目标就是把干跑/驱逐挪出 scheduling 主线程**——阶段以你集群 feature gates 为准）。

### 6.5 v1.37 的两条新战线（仅简介）

- **async preemption**（门控 `SchedulerAsyncPreemption`）：把昂贵的候选干跑/收口逻辑放进异步 goroutine，scheduling cycle 可以继续处理别的 Pod。配套指标：`scheduler_preemption_goroutines_*`（源码确认已在 release-1.37 注册）。默认状态以你集群为准。
- **workload-aware preemption**（`GenericWorkload` Beta 默认关）：PodGroup 既是抢占者也可以是遇害者；按组的 `disruptionMode` 决定「整组驱逐 / 单 Pod 驱逐」的粒度——这就是 gang 化调度对抢占语义的扩展（§2.3）。

---

## 七、观测与日志：怎么聊到调度器他心里去了

### 7.1 关键指标一览（指标名已对照 release-1.37 源码 `pkg/scheduler/metrics/metrics.go` 核对）

| 指标 | 类型/稳定性 | 看什么 |
|------|------------|--------|
| `scheduler_pending_pods{queue=...}` | Gauge / STABLE | 队列深度。label 有 `active` `backoff` `unschedulable` `gated`（gated 专指 schedulingGates 的卡住的）+ PodGroup 场景的 `incomplete`/`pending` |
| `scheduler_schedule_attempts_total{result=...}` | Counter / STABLE | 尝试总数。result: `scheduled` / `unschedulable` / `error`（这是「调度器健康大盘」第一项） |
| `scheduler_scheduling_attempt_duration_seconds` | Histogram / STABLE | 单次 attempt（scheduling + binding）端到端分布 |
| `scheduler_pod_scheduling_sli_duration_seconds` | Histogram / BETA | **Pod 视角 SLI**：从进队列到被成功调度的时长，含多次重试——衡量「用户感觉到多快」就找它 |
| `scheduler_pod_scheduling_attempts` | Histogram / STABLE | 成功前平均试了几次 |
| `scheduler_framework_extension_point_duration_seconds{extension_point,...}` | Histogram / STABLE | Filter/Score/Permit/PreBind 各扩展点耗时分布 → 定位「哪一点最慢」 |
| `scheduler_plugin_execution_duration_seconds{plugin,extension_point}` | Histogram / BETA | 单插件耗时 → 自定义插件上线必看 |
| `scheduler_queue_incoming_pods_total{queue,event}` | Counter / STABLE | 谁把 Pod 搬进各队列；§1.5 验证 QHint 是否有效就靠它 |
| `scheduler_unschedulable_pods{plugin,...}` | Gauge / BETA | 按插件统计「谁拒绝了这批 Pod」→ 确认天花板是哪个约束 |
| `scheduler_pod_scheduled_after_flush_total` | Counter / ALPHA | 30s 兜底搬运救成功的数，涨得高说明事件/hint 链没抓好现行 |
| `scheduler_preemption_attempts_total` / `scheduler_preemption_victims` | Counter+Histogram / STABLE | 抢占风暴的振幅仪表盘 |
| `scheduler_permit_wait_duration_seconds` | Histogram / BETA | gang 类插件产生的等待时长 |
| `scheduler_goroutines{operation=...}` | Gauge / BETA | binding 等并发 goroutine 数量 |

端口与认证：**调度器对外是 HTTPS :10259**（kubeadm 默认），`/metrics`、`/healthz` 走这个端口；pprof 在 `enableProfiling` 开启时可用（`/debug/pprof/`），生产确认是否被你的配置默认关上。

```bash
# 随身快照（kind/kubeadm 通用）
kubectl -n kube-system port-forward pod/kube-scheduler-<node> 10259:10259 &
curl -sk https://127.0.0.1:10259/metrics | grep -E 'scheduler_(pending_pods|schedule_attempts_total|unschedulable_pods)'
```

### 7.2 `--v=4 / --v=5` 日志读法

kube-scheduler 用 klog，层级越大越啰嗦。关键档位体感（以 v1.37 系列行为为例，具体措辞以你版本为准）：

| 档位 | 会看到什么 | 日常用途 |
|------|-----------|---------|
| 默认（2 级） | 每次绑定成功、每次抢占决定、error | 生产长开，只看「成/败」 |
| **`--v=4`** | 每次 scheduling cycle 的入口、QHint 判断、队列活动的摘要 | 「这个 Pod 为什么不醒」的一线排查 |
| **`--v=5`** | Filter 对每个节点的拒绝原因（含插件名）、Score 中间值、绑定详细时间轴 | 「0/3 nodes are available」看不清时,直接看插件为什么拒绝 |

```bash
# kubeadm / kind 静态 Pod 集群改日志档位的最低摩擦做法
# （控制面清单文件在节点上，kubelet 会自动重启）
sed -i 's/- kube-scheduler/- kube-scheduler\n    - --v=5/' /etc/kubernetes/manifests/kube-scheduler.yaml

# 看日志（清单改动后 kubelet 会重启这个静态 Pod，等几秒镜像 Pod 重建）
kubectl -n kube-system logs kube-scheduler-<node> --tail=200 -f | grep -i '<你的pod名>'
```

在 v=5 日志里重点看这几类行（措辞随版本微调，都能 grep 到）：

| 日志线索 | 含义 |
|---------|------|
| `Attempting to schedule pod:` | scheduling cycle 开始（出队了） |
| `Plugin X failed ... insufficient ...` | 某插件判负的具体原因（「Insufficient cpu」就出自 NodeResourcesFit） |
| `Unable to schedule pod ...` + `FitError ...` | 本 cycle 被全灭，附插件聚合原因 |
| `Pod is nominated for node ...` | 抢占成功，写了 nominatedNodeName |
| `Successfully assigned/bound ...` | binding cycle 完成 |

### 7.3 一条「Pod 一直 Pending」的排查链（命令序，照抄）

```bash
# step 1 官方传道：读 events，它已经把「原因」聚合好了
kubectl describe pod <pod> -n <ns>
#   重点看 Events 里的两行（典型样例）：
#     Warning  FailedScheduling   0/3 nodes are available: 1 Insufficient cpu, 2 node(s) had untolerated taint {...}
#     Warning  FailedScheduling   preemption: 0/3 nodes are available: 3 No preemption victims found for incoming pod
kubectl get events -n <ns> --field-selector involvedObject.name=<pod> --sort-by=.lastTimestamp

# step 2 队列视角：它还躺着吗？躺哪一档？（调度器指标走自己的 :10259，
#   不在 apiserver /metrics 里——别找错门）
kubectl -n kube-system port-forward pod/kube-scheduler-<node> 10259:10259 &
curl -sk https://127.0.0.1:10259/metrics | grep scheduler_pending_pods
#   看 active/backoff/unschedulable/gated 四档的规模；gated > 0 请回看 §11

# step 3 -v=5 日志：逐个 Filter 拒绝原因对齐插件表（§3）

# step 4 插件级确认：哪个插件在拒绝
curl -sk https://127.0.0.1:10259/metrics | grep scheduler_unschedulable_pods
kill %1 2>/dev/null
```

**events 读法要点**（生产上火最多的点）：

- `0/3 nodes are available: 1 Insufficient cpu, 2 node(s) had untolerated taint`：**每类插件失败聚合一次**，前面的数字是被它判负的节点数。读法 = 「3 台节点里：1 台被 NodeResourcesFit 以 cpu 不足否决；2 台被 TaintToleration 以未容忍污点否决」——立刻知道先去看 requests 还是污点，而不是瞎猜。
- 后面跟的 `preemption: ...` 是 **PostFilter 的结论**（默认抢占），说的不是「缺资源」而是「即使赶走低优 Pod 也放不下」：

| 抢占消息 | 含义 |
|---------|------|
| `No preemption victims found for incoming pod` | 没有对象可赶（没有更低优先级 Pod、或 Inter-Pod affinity 挡着、或全是 PDB） |
| `Preemption should not happen because (...)` | 不该发起（如同级互不相抢） |
| `not eligible due to preemption result` | 干跑过但失败，换个候选 |

---

## 八、descheduler：调度器只看新增、descheduler 才清存量

### 8.1 它解决什么（与调度器的职责分割）

kube-scheduler 是「一次性」的（§0）：它放进去的 Pod 后续节点再好/再差、标签再变、资源再倾斜，它都不会回头动。descheduler（`kubernetes-sigs/descheduler`，**k8s 1.37 对应 release v0.37**）就是一个**周期驱动的「存量清理者」**：

- 按策略找出「当前已经不合理的存量 Pod」→ 调用 **`/eviction` 子资源**驱逐它们 → 交给 kube-scheduler 重新摆（descheduler 自己不做放置决策，官方 README 原话）。
- 跑法：Job / CronJob / Deployment 都可，生产一般 Deployment + `leaderElection.enabled=true`；
- 默认保护（官方 README 核对）：`system-cluster-critical/system-node-critical` 的 Pod、DaemonSet 的 Pod、使用本地存储的 Pod、裸 Pod、已带 deletionTimestamp 的 Pod **默认不被驱逐**（可用 `podProtections.defaultDisabled` 反选某条）。PDB 一定尊重（走 eviction API 自带语义）。

### 8.2 策略全图（**deschedule 组**＝逐一处理 Pod；**balance 组**＝按分散/收敛意图处理一组 Pod）

| 策略 | 组 | 一句话原理 |
|------|----|-----------|
| RemoveDuplicates | balance | 同工作负载副本挤在同节点 → 驱逐多余的让 scheduler 摊开 |
| LowNodeUtilization | balance | 低于 thresholds 的是「欠用节点」、高于 targetThresholds 的是「过载节点」→ 从过载节点往欠用节点腾 Pod（要配合 requests） |
| HighNodeUtilization | balance | 和 binpack 配套：从「低于阈值」的节点撤 Pod，把节点彻底腾空，交给 Cluster Autoscaler 回收 |
| RemovePodsViolatingInterPodAntiAffinity | deschedule | 节点标签变化后已经违反自身 required Pod 反亲和的历史存量 |
| RemovePodsViolatingNodeAffinity | deschedule | 节点标签变化后已经违反自身 required node 亲和的历史存量 |
| RemovePodsViolatingNodeTaints | deschedule | 节点新增污点后已违反自身容忍规则的历史存量 |
| RemovePodsViolatingTopologySpreadConstraint | balance | 当前 skew 已违反自带 DoNotSchedule spread 的存量 |
| RemovePodsHavingTooManyRestarts | deschedule | 重启超阈值的 Pod（可含 initContainer）→ 让重调度救它到别处 |
| PodLifeTime | deschedule | 按年龄/状态/退出码/owner 清：到点扫街、防「永生 Pod」 |
| RemoveFailedPods | deschedule | 按失败原因/退出码清 Failed Pod |

### 8.3 最小部署（helm，v0.37 chart）＋示例 strategy YAML

```bash
helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm repo update

cat > /tmp/descheduler-values.yaml <<'EOF'
kind: Deployment            # 常驻；默认是 CronJob（每 2 分钟跑一次 Job）
deschedulingInterval: 120s  # Deployment 形态的周期
leaderElection:
  enabled: false            # 单副本可不选举；>1 副本必须 true
deschedulerPolicy:          # descheduler/v1alpha2
  profiles:
  - name: default
    pluginConfig:
    - name: DefaultEvictor
      args: {}
    - name: LowNodeUtilization
      args:
        thresholds:      {pods: 3}   # 利用率 < 3% 视为欠用
        targetThresholds: {pods: 5}  # 利用率 > 5% 视为过载
    plugins:
      balance:
        enabled: [LowNodeUtilization]
EOF

helm install descheduler descheduler/descheduler -n kube-system \
  -f /tmp/descheduler-values.yaml

kubectl -n kube-system logs deploy/descheduler -f | grep -iE 'evicted|strategy'
```

完整实验（含造倾斜的负载）见 §13 实验 2.3。

**为什么这么设计（几个冷启动必知）**：

- **descheduler 不会绕过 PDB**：被 PDB 挡住的 Pod 一次都不会被 evict（官方 README：用的是 eviction 子资源），也别试图通过反复 reschedule 绕过它——这不是 bug。
- **不会去调度替代者**：它只管「腾出」，落点听 scheduler 的——所以用的时候**照常配 Pod 的亲和/拓扑约束**，不要把「descheduler 会把副本摊匀」当成替代 topologySpread 的手段。
- **运行参数与指标**：默认对外暴露 `:10258/metrics`（启动时使用 HTTPS）；指标比如 `pods_evicted_total`、`strategy_duration_seconds`、`loop_duration_seconds` 朴素到只有这些。

---

## 九、自定义调度器三条路径

> 选择前的总原则是：**能挂框架插件就别新起调度器，能独立调度器就别走 Extender**。

### 9.1 路径 A：Framework out-of-tree 插件（推荐默认）

这是「带着自家规则跑在官方调度器里」的正道：Go 写一个实现扩展点接口的包，用 `app.WithPlugin` 注册，编出一个**和原生 kube-scheduler 二进制同宗、多几个插件的**镜像，再用 KubeSchedulerConfiguration 把插件挂进 profile。

**① 最小可编译骨架（接口签名按 v1.37 上游源码核对：fwk 包是 `k8s.io/kube-scheduler/framework`，工厂函数带 ctx 三参）**

```go
// myplugin/score.go —— 一个「优先打 SSD 节点」的自定义 Score 插件
package myplugin

import (
	"context"
	"fmt"

	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/runtime"
	fwk "k8s.io/kube-scheduler/framework"
)

// Name 是插件在 KubeSchedulerConfiguration 里被引用的名字.
const Name = "NodeLabelScore"

// NodeLabelScore 按节点 label example.com/fast-storage 打分.
type NodeLabelScore struct {
	handle fwk.Handle
}

var _ fwk.ScorePlugin = &NodeLabelScore{}

// New 是插件工厂（签名必须是：ctx, args 对象, handle）.
func New(_ context.Context, _ runtime.Object, h fwk.Handle) (fwk.Plugin, error) {
	return &NodeLabelScore{handle: h}, nil
}

func (*NodeLabelScore) Name() string { return Name }

// Score 对每个可行节点返回 [0,100] 的原始分.
func (p *NodeLabelScore) Score(
	ctx context.Context,
	state fwk.CycleState,
	pod *v1.Pod,
	nodeInfo fwk.NodeInfo,
) (int64, *fwk.Status) {
	node := nodeInfo.Node()
	if node == nil {
		return 0, fwk.AsStatus(fmt.Errorf("node info object missing"))
	}
	if node.Labels["example.com/fast-storage"] == "true" {
		return 100, nil
	}
	return 0, nil
}

// ScoreExtensions 挂上 NormalizeScore.
func (p *NodeLabelScore) ScoreExtensions() fwk.ScoreExtensions { return p }

// NormalizeScore 把原始分线性归一到 [0,100]；本例已产出 [0,100]，直接放行.
func (p *NodeLabelScore) NormalizeScore(
	ctx context.Context,
	state fwk.CycleState,
	pod *v1.Pod,
	scores fwk.NodeScoreList,
) *fwk.Status {
	return nil
}
```

```go
// cmd/scheduler/main.go —— 注册 + 跑起来
package main

import (
	"os"

	"k8s.io/component-base/cli"
	"k8s.io/kubernetes/cmd/kube-scheduler/app"

	"example.org/my-scheduler/myplugin"
)

func main() {
	command := app.NewSchedulerCommand(
		app.WithPlugin(myplugin.Name, myplugin.New),
	)
	code := cli.Run(command) // 等价于 cobra 的 Execute() + 退出码
	os.Exit(code)
}
```

模块依赖（v1.37 基线）：`go.mod` 里 `require k8s.io/kubernetes v1.37.x`（staging 包会被 `replace` 到对应 tag——直接抄 `scheduler-plugins` 仓库 v1.37 对应分支的 go.mod 模板最稳）。

**② 用 KubeSchedulerConfiguration 挂进 profile：**

```yaml
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
- schedulerName: default-scheduler          # 默认 profile 里追加（也可以另起名字）
  plugins:
    score:
      enabled:
      - name: NodeLabelScore
        weight: 2                            # 字面就是乘以 2
```

**③ 跑起来的两条路**：

- **同进程多 profile**：直接把 `second-scheduler` profile 写进原调度器配置，Pod 用 `spec.schedulerName: second-scheduler` 分流（官方 `Scheduler Configuration` 支持单进程多 profile）。
- **独立 Deployment 跑第二个调度器**：包成镜像 + 按 §9.2 的方式起在集群里（同一 KubeSchedulerConfiguration 也可以带 profiles 区分名字）。

依赖的「完整版」参考：[`scheduler-plugins` 仓库](https://github.com/kubernetes-sigs/scheduler-plugins)的 README 与 `cmd/scheduler/main.go` 就是上面的形态，里面挂了 Coscheduling、Trimaran、NodeResourceTopology、PreemptionToleration、CapacityScheduling、NetworkAware 等官方维护的 out-of-tree 插件；社区还维护兼容矩阵（**README 中发布节奏落后于 k8s minor**：最新表列 v0.35 配 k8s 1.35，跑 v1.37 集群需要时间跟上主仓的 main）。

### 9.2 路径 B：完整独立的二次调度器

**分流原理一句话**：每个 Pod 用 `spec.schedulerName` 声明「哪个调度器领我」——内置 `default-scheduler` 是默认值，apiserver 发现没人填就补上；你起的调度器进程在 informer 里过滤属于自己名字的 Pod 即可。

```yaml
spec:
  schedulerName: my-scheduler      # 不写永远是 default-scheduler
```

并存时必须记住的三条（官方 multiple schedulers 文档 + 工程常识）：

1. **调度器之间互不可见**：你自定义的调度器建立自己的 informer/cache，它看不到也管不着默认调度器 assume 中的占位——两个调度器可能同一瞬间决定把不同 Pod 发向同一节点。
2. **Binding 冲突由 apiserver 兜底、最后一个赢**：两个 scheduler 同时提交 Binding，只有一个 201；另一个会收到 **409 Conflict**（对象的 nodeName 已经被占上，乐观锁兜住）——收到 409 的那侧必须重新排队调度，否则 Pod 会悬空。框架自带这套重试（返回 Error → 回队列）；你手写调度器要自己处理 409。
3. **RBAC 别自己造**：官方做法是 `system:kube-scheduler` 和 `system:volume-scheduler` 两个 ClusterRoleBinding 直接 bind 到你的 SA，多个 leader-electing 调度器并存时按你 `resourceName` 扩 `system:kube-scheduler` 的 `resourceNames`。

适用场景：调度目标**和默认调度器完全不同**（如 Spark 应用内对 Executor 的二级调度、批量作业的 gang），别拿来做「给默认调度器加一条规则」——那是框架插件的饭。

### 9.3 路径 C：Extender / Webhook（遗留路线，简述历史）

- **来历**：2015 年的老机制（KEP-1819 是为了留下其存在做的追溯 KEP）。让调度器在 Filter / Prioritize / Bind / Preempt 四个点对**外部 HTTP 服务**发「帮我再拍一下板」，extender 返回节点子集或打分修正。
- **现状**：`extenders` 字段仍然躺在 `kubescheduler.config.k8s.io/v1` 的 `KubeSchedulerConfiguration` 里，依然工作；但官方文档侧已经不再讲它（docs 里没有任何 extender 教程页），社区共识视作 **legacy 而非活跃演进**——新建项目不建议再选它。
- **为什么不推荐（KEP 自己都写的缺点）**：① 每个调度决定多一次出进程调用，时延与可靠性受制于外部服务；② 缓存一致性问题——extender 和调度器各看一份节点状态，容易产生「你过滤了半天我这边变过了」的鬼故事；③ 语言和表达能力任意，但错误/超时只能配置 `ignorable` 兜底。
- **仍适用的唯一场景**：「我不能重新编译/不想维护自定义 kube-scheduler，只是想临时挂一个轻钩子做 PoC」。生产一旦验证，应迁回框架插件（§9.1）。

---

## 十、批调度 / HPC 简介：gang scheduling 的两个主流答案

### 10.1 为什么需要 gang：离线训练的「All-or-Nothing」

MPI/TF 分布式训练要求 N 个 worker **同时**就绪才开始 step——只调度起 5/8 个 worker 不但没用，还会占着资源等另外 3 个而形成**资源死锁**：

```
默认调度器：逐 Pod 决策
  worker-0..4 已起 → 占住 5×8 卡；worker-5..7 Pending
  worker-5..7 等的资源被别的 Pod 抢走 → 永远差两张卡 → 整个作业 0 产出且占着 40 卡
```

gang scheduling 的补救：**要么 8 个全起、要么一个都不起**（All-or-Nothing）。

### 10.2 Volcano（PodGroup/Queue）

- **定位**：CNCF incubating 的批调度平台，自带 `volcano-scheduler`（独立于 kube-scheduler 的第二个调度器，§9.2 形态）+ controller + admission webhook，是一个覆盖 **VolcanoJob/TFJob/MPIJob/RayJob/Spark** 等批负载形态的完整世界。
- **核心概念**：
  - **PodGroup**（`scheduling.volcano.sh/v1beta1`）：一组 Pod 的「整队」，字段含 `minMember`（最小同时起数）、`minResources`（最小资源阈值）、`queue`、`priorityClassName`；状态机会经历 `pending → inqueue → running`。
  - **Queue**：租户级资源队列，配 reclaim/preempt/capability。
  - **VolcanoJob**：把传统 Job 包装成 PodGroup 驱动的形态（也支持直接给 Pod 写 PodGroup 注解）。
  - **actions + plugins**：cycle 按 enqueue → allocate → backfill → preempt → reclaim 动作流执行，每动作可挂 gang/drf/proportion/priority/topology 等插件（策略密度比主社区高）。
- **兼容**：README 矩阵显示 master 支持 k8s 1.36/1.35...，发布版 v1.15 对齐 k8s 1.35 系。
- **适用**：AI 训练、生物信息、Spark/Flink、真正的 HPC——你要的是「作业管理 + 组调度 + 队列治理」全家桶。

### 10.3 Kueue（ClusterQueue/Cohort）

- **定位**：sig-scheduling 自家子项目、**不替换 kube-scheduler**——把「是否允许这个 Workload 开始」一层 admission 叠加在默认调度器上。Kueue 给 Workload 打 schedulingGates（§11），配额到了才放行、放行后照常用 kube-scheduler 摆放。
- **核心概念**：
  - **Workload**（CRD）：一个 Job 的 Kueue 侧影子，含 Pod 模板摘要和配额请求。
  - **LocalQueue**：ns 级入口，用户往里投工作。
  - **ClusterQueue**：集群级配额池（按 ResourceFlavor 分 GPU/CPU 等），定义 preemption 策略（withinClusterQueue、withinCohort）与 fair sharing。
  - **Cohort**：ClusterQueue 之间互相借贷的同盟，配合 `lendingLimit`。
  - **ResourceFlavor**：节点池/架构/spot 等「风味」映射，决定 fallback 顺序（flavor fungibility）。
- **适用**：你要的是「配额 + 公平共享 + 优先级抢占」的**多租户治理**，同时不想换掉默认调度器、也尽量保留现有 Job 控制器（Kueue 为 batch Job、JobSet、Kubeflow、Ray、Deployment、StatefulSet、Pod 都有稳定集成，`TrainJob`（Kubeflow Trainer v2）已 Alpha 支持）。

### 10.4 一句话选型 + 收敛趋势

| 你要什么 | 去哪 |
|---------|------|
| gang/队列/作业生命周期全套；接 MPI/TF/Spark | **Volcano** |
| 配额治理 + fair share + 不想动默认调度器 | **Kueue** |
| 只想给某些 Job 做「凑齐再跑」 | 等/试上游 Workload API（§2.3），或 `scheduler-plugins` 的 Coscheduling 插件（gang 一条） |

趋势备注：`GenericWorkload`（v1.37 Beta 默认关）+ PodGroup + workload-aware preemption 的路线，就是上游把 gang 调度引进官方框架的方向——现阶段若生产急用仍选 Volcano/Kueue，长期看工作负载调度会向这条主线收敛。

---

## 十一、SchedulingGates 与 DRA：把 Pod 卡在大门外的两种新玩法

### 11.1 SchedulingGates：v1.30 起 GA 的「大门外等待区」

**Pod Scheduling Readiness（v1.30 起 Stable/GA）** 允许你在创建 Pod 时就写明「先别调度」：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: held
spec:
  schedulingGates:
  - name: example.com/wait-for-quota
  containers:
  - name: pause
    image: registry.k8s.io/pause:3.10
```

机制（官方文档核对）：

- scheduler 的 PreEnqueue 扩展点上挂 **SchedulingGates** 插件：带 gates 的 Pod 根本不进 activeQ，落在 gated 状态，**Pod 状态显示 `SchedulingGated`**；它不会消耗调度尝试（§7.1 有专属指标 `scheduler_pending_pods{queue="gated"}`）。
- gates 字段**只能在创建时初始化**（用户直写或准入改）；**之后只能删不能加**（少了「又给塞一个门」的把戏）。
- 你想放行它：`kubectl patch pod held --type=json -p='[{"op":"remove","path":"/spec/schedulingGates/0"}]'`（或 apply 整个不带 gates 的 spec）。
- **Pod Readiness 联动**：常见模式是同时挂 `readinessGates`（比如起一个类似 `schedulingReady` 的自定义 gate），让 Pod 在被放行且完成调度前保持 NotReady——Kueue 这类准入型组件就是用这个组合，先把 Job 的 Pod 卡在这里等配额。
- 带 gates 期间改 Pod 的调度指令是允许的但**只能收紧**（加 nodeSelector/加表达式、不能放宽），官方明确这是防止「Pod 被卡在门外的期间被偷偷放大可选节点范围」。

为什么值得这个设计：**准入决策不该让默认队列承担**。配额未批、集群正在扩、image 还没预热……过去这些状态只能靠「Pending 等死 + Cluster Autoscaler 被误唤醒」糊弄；现在「待令 Pod」和「待位置 Pod」在调度器里就变成两个一眼能分的群体。

### 11.2 DRA 对调度链路的影响（简介，不深入）

Dynamic Resource Allocation（DRA）：**v1.30 首次出现（Alpha），v1.35 起 Stable/GA 且已锁定（不可关）**。本章只点它对调度的影响：

| DRA 要素 | 对调度的影响 |
|---------|-------------|
| `ResourceClaim` / `ResourceClaimTemplate` | Pod 的资源需求不再只有「cpu/mem/扩展资源计数」这一种形态——可以是「一块带特定属性（CEL 表达式筛选）的设备」 |
| `ResourceSlice`（驱动发布） / `DeviceClass`（归类） | 调度器在 Filter 里对每个节点评估「这里有没有满足 claim 的可用 slice」（CEL 求值 + 用量检查），默认 filterTimeout 10s（`DynamicResourcesArgs.filterTimeout`） |
| 分配延迟 | 选中节点后 claim 才真正 allocated 到该节点上，bind 前 PreBind 等设备的 `BindingConditions`（`bindingTimeout` 默认 10min） |
| 不支持抢占 | 官方原文：「The Kubernetes scheduler doesn't support preemption for DRA resources」——高优 Pod 要等占用 DRA 设备的 Pod 自己退出 |
| 打分参与 | 参与 Filter 多于参与 Score；延迟分配 + 容量过筛是主基调，和 WFFC 的精神一致 |

深入请自己开新篇笔记（`K8s-存储深入.md` 或设备管理专章）——本章只在「调度链路受影响」层面点到。

---

## 十二、常见生产问题清单（调度面）

| # | 症状 | 根因链 | 排查动作 | 处置 |
|---|------|--------|---------|------|
| 12.1 | Pod 一直 Pending | **四类根因**（按 §1 的 Filter 分组）：① 资源类：requests 超限/extended 资源被 DRA 卡住/hostPort 冲突；② 拓扑类：节点亲和/污点/Pod 反亲和/topologySpread；③ 存储类：PVC 未绑、PV nodeAffinity 与落点 zone 冲突、容量不足；④ 准入类：SchedulingGates、卷 provisioning 在转 | §7.3 排查链照做：events → 队列指标 → -v=5 日志 → 单插件指标 | 按拒绝插件的那一行（§3）去改 Pod 或改集群；别上来就重启调度器 |
| 12.2 | `0/3 nodes are available: 1 Insufficient cpu` 但你算出来明明够 | **scheduler 看到的是「节点 allocatable - 已分配 requests」**，不是真实使用率。常见的坑：① 节点上有 requests 很大的「占位 Pod」（如 kube-proxy、device plugin）；② DaemonSet 的基础开销被漏算；③ requests 正好压线，被 NodeResourcesFit 在边界处判负 | `kubectl get node <n> -o jsonpath='{.status.allocatable}'` + `kubectl describe node <n>` 看 Allocated resources | 给节点池留 requests 水位线；真要按真实使用率调，去看 §9.1 的 trimaran 类 out-of-tree 插件（LoadAware）或 Karpenter |
| 12.3 | 节点利用率一端热一端冷 | **默认计分是 LeastAllocated + 只有 Pod 创建时刻参与决定**——运行期倾斜没人管；另有 ImageLocality/亲和半套规则把热点拉歪 | Grafana 落 requests 与 usage 面板；descheduler 指标 `pods_evicted_total` | 生产组合：descheduler + LowNodeUtilization（requests 维度）+ 必要的 HighNodeUtilization 腾出收缩位；长期分散用 topologySpread 硬约束 |
| 12.4 | 镜像不存在/私有仓库 Secret 未建，Pod Pending 很久 | 这 **不归调度器管**：调度器已经把它放上去了，是 kubelet 拉镜像失败（ImagePullBackOff）。但**寒意延伸到调度**：同 replicaset 新起的替代 Pod 仍然会被 scheduler 反复摆 | `kubectl describe pod` 看 Events 是谁的错（Failed vs FailedScheduling） | 不要试图用调度约束解决镜像问题——先修镜像；QHint 时代「ImagePullBackOff 反复重试」也不会把调度队列搅浑，§1.5 |
| 12.5 | 抢占风暴：大量 Pod 被打上 Preempted，业务抖动 | 高优 Pod 大量出现 + 资源紧张 + PDB 太宽 → DefaultPostFilter 每 cycle 都全集群干跑 | `scheduler_preemption_attempts_total` / `preemption_victims` 曲线；事件 grep `Preempted` | 优先级分层节流（顶层只给基础设施）、PDB、批任务 preemptionPolicy: Never、CA 快速补容 |
| 12.6 | 「为什么挂了 SchedulingGated 但没人认领」 | gate 写上了但没人删：用 Kueue 的话看它是不是 healthy（ClusterQueue 没配额/localqueue 挂错）；用 Pod 手写的话是忘了删 | `kubectl get pod <p> -o jsonpath='{.spec.schedulingGates}'` | 排查顺序：Kueue workload → clusterqueue 配额 → admission controller 写 gate 的地方 |
| 12.7 | events 说 `0/5 nodes are available`，但 `kubectl get node` 看到几十台 | **这是这个 Pod 的「可行域」**只有 5 台——nodeSelector/亲和/污点已经把其他筛完了；Filter 对这 5 台全部判负 | 把 unit 读成「在这个 Pod 的可行节点集合里」再逐条 Filter 读（§7.3 的读法） | 扩「可行域」（放宽 nodeSelector/加容忍/加节点池），或者在可行域里腾资源 |
| 12.8 | QHint 上线后事件明明发生，Pod 不醒 | ① 事件不是任何拒绝插件注册的（见 §1.5）；② 你自定义插件 EnqueueExtensions 没写全（如返回了空事件列表 = 永远不醒，官方接口注释原话） | `scheduler_queue_incoming_pods_total{queue,event}` 看事件到达与进队；`scheduler_pod_scheduled_after_flush_total` 变高说明只靠 30s 兜底 | 修自定义插件的 EventsToRegister；内置场景跑 issues 查是不是已知 hint bug |

---

## 十三、实验（kind 沙箱 4 连）

> 环境：本机装 `kind`（v0.2x+）、`kubectl`、`helm`、`docker`。四个实验都用同一份 kind 配置：`1 control-plane + 2 worker`。
> 所有命令均可直接粘贴。基线镜像版本以 kind 当期默认 k8s 版本为准（可用 `kind create cluster --image kindest/node:v1.37.x` 指定）。

### 实验 2.1 抓一次完整调度的 scheduling/binding 两段

**step 1：起一个 3 节点 kind 集群，把 scheduler 日志打到 v=5**

```bash
mkdir -p /tmp/sched-exp && cd /tmp/sched-exp

cat > kind-sched.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    scheduler:
      extraArgs:
        v: "5"          # kube-scheduler 日志档位
- role: worker
- role: worker
EOF

kind create cluster --name sched-exp --config kind-sched.yaml
kubectl get nodes   # 1 control-plane + 2 worker 就绪
```

**step 2：造一个普通 Deployment，同时开第二个终端盯日志**

```bash
kubectl create deploy demo --image=nginx --replicas=2
```

```bash
# 第二个终端：盯调度器对这个 Pod 的所有决定（措辞随版本微调，都能 grep）
kubectl -n kube-system logs kube-scheduler-sched-exp-control-plane -f \
  | grep -E 'demo|schedul|bind|Bound|queue' | head -40
```

**step 3：把看到的行对号入座**

| 日志里你会看到的片段类别 | 属于哪一段 | 怎么读 |
|-------------------------|-----------|--------|
| `Attempting to schedule pod: default/demo-...` | 出队 → scheduling cycle 开始 | 这个 Pod 真的排队排到了 |
| 若干 `Plugin <name> finished with unschedulable` / `insufficient ...` | Filter 阶段 | 哪些插件拒绝了哪些节点 |
| `Score node ... - [list]` 之类中间值 | Score 阶段 | 节点间差多少分（权重乘前的原始分） |
| `Selected node: sched-exp-worker` | scheduling cycle 结论 | assume 完，准备进 binding cycle |
| `Successfully bound pod: default/demo-...` | binding cycle 结束 | Binding API 已发；之后 kubelet 接管 |

**step 4：对照指标看大盘**

```bash
# 调度器 metrics 走 :10259 HTTPS 端口；用 port-forward 看
kubectl -n kube-system port-forward pod/kube-scheduler-sched-exp-control-plane 10259:10259 &
curl -sk https://127.0.0.1:10259/metrics \
  | grep -E '^scheduler_(pending_pods|schedule_attempts_total|scheduling_attempt_duration_seconds)' | head -20
kill %1
```

**step 5：看 events 的「0/2 nodes are available」句式**（可选）

```bash
# 造一个 cpu 请求超能力的 Pod，观察官方返回的信息聚合格式
kubectl run over --image=nginx --overrides='{"spec":{"containers":[{"name":"over","image":"nginx","resources":{"requests":{"cpu":"999"}}}]}}'
kubectl describe pod over | tail -5
kubectl delete pod over
```

> 实验收获：把 `describe` 的聚合信息 ➜ Filter 插件拓扑表（§3）➜ 队列指标（§7）➜ -v=5 的逐条原因（§7.2）连成一条链，之后任何 Pending 你都有一线可走。

**清理**

```bash
kind delete cluster --name sched-exp    # 不影响本机其他集群；后面实验会重建同名集群
```

### 实验 2.2 抢占实验：小节点打满，看高优 Pod 怎么赶走低优

**step 1：重建 3 节点集群（同实验 2.1）+ 两个 PriorityClass**

```bash
kind create cluster --name sched-exp --config kind-sched.yaml

cat > pc.yaml <<'EOF'
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: {name: low}
value: 1000
globalDefault: false
description: "低优先级：将被高优 Pod 抢占"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata: {name: high}
value: 1000000
globalDefault: false
description: "高优先级：会发起抢占"
EOF
kubectl apply -f pc.yaml
kubectl get priorityclass
```

**step 2：集中装僵尸：只用一台 worker 装填**

```bash
# 另一台 worker 先挡在外
kubectl cordon sched-exp-worker2

# 在 worker1 上塞低优副本：requests.cpu=1 × 副本数≈allocatable.cpu
ALLOC_CPU=$(kubectl get node sched-exp-worker -o jsonpath='{.status.allocatable.cpu}')
echo "worker allocatable cpu = $ALLOC_CPU"

kubectl create deploy fillers --image=busybox --replicas=${ALLOC_CPU}
kubectl patch deploy fillers --type=json -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/args","value":["sleep","3600"]},
  {"op":"add","path":"/spec/template/spec/containers/0/command","value":["sh","-c"]},
  {"op":"add","path":"/spec/template/spec/nodeSelector","value":{"kubernetes.io/hostname":"sched-exp-worker"}},
  {"op":"add","path":"/spec/template/spec/priorityClassName","value":"low"},
  {"op":"add","path":"/spec/template/spec/containers/0/resources","value":{"requests":{"cpu":"1","memory":"64Mi"}}}
]'
kubectl wait deploy fillers --for=condition=available --timeout=120s || true
kubectl get pods -o wide | head -15    # 大部分 Running 在 worker，少数可能已 Pending（正常）
```

**step 3：丢一个高优 Pod 进去，掐表看抢占**

```bash
kubectl run vip --image=busybox --overrides='{
  "spec": {
    "nodeSelector": {"kubernetes.io/hostname":"sched-exp-worker"},
    "priorityClassName": "high",
    "containers": [{"name":"vip","image":"busybox","command":["sh","-c","sleep 600"],
                    "resources":{"requests":{"cpu":"1","memory":"64Mi"}}}]
  }}'

# 连环看：事件 + Pod 状态
kubectl get events --sort-by=.lastTimestamp | tail -20
kubectl get pods -o wide -w
```

**你要看到的关键证据**

- `events` 里低优 Pod 的 `Preempted` 记录（按 §6.5 顺序产）：`... Preempted by default/vip ...`
- 被赶的低优 Pod 先 Terminating（它还有自己的 graceful period），随后被 Deployment 重排到别处 Pending
- `vip` 上 `nominatedNodeName: sched-exp-worker`（可选 `kubectl get pod vip -o jsonpath='{.status.nominatedNodeName}'`）
- `vip` 在腾出后 **下一轮** 被 Bind、Running——不是立刻

**step 4（可选）：同优先级互不相抢的反面验证**

```bash
# 把 vip 换成 priorityClassName: low 再来一个，观察 events 的 preemption 行写「不发起」
kubectl run no-host --image=busybox --overrides='{
  "spec": {
    "nodeSelector": {"kubernetes.io/hostname":"sched-exp-worker"},
    "priorityClassName": "low",
    "containers": [{"name":"no-host","image":"busybox","command":["sh","-c","sleep 600"],
                    "resources":{"requests":{"cpu":"1","memory":"64Mi"}}}]
  }}'
kubectl describe pod no-host | grep -A3 Events
kubectl delete pod no-host --wait=false
```

**清理**

```bash
kubectl delete deploy fillers
kubectl delete pod vip --ignore-not-found
kubectl delete priorityclass low high
kind delete cluster --name sched-exp
```

> ❗ 本实验的稳定性取决于你主机资源：kind 节点共享主机内核，`allocatable.cpu` 就是主机核数——核数大时 ${ALLOC_CPU} 会很大，可改成 requests `cpu: "2"` 并把 replicas 设成 `${ALLOC_CPU}/2` 等比例放大压力，本文每条命令只依赖「填满一台节点」这一件事。

### 实验 2.3 descheduler：LowNodeUtilization 看驱逐摆平

**step 1：重建集群 + 装 descheduler（直接用 §8.3 的 YAML）**

```bash
kind create cluster --name sched-exp --config kind-sched.yaml

helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm repo update

cp /tmp/descheduler-values.yaml .  # 或者用 §8.3 的那段重新写一份
helm install descheduler descheduler/descheduler -n kube-system -f descheduler-values.yaml
kubectl -n kube-system rollout status deploy/descheduler --timeout=90s
```

**step 2：造倾斜负载——先停 worker2，全部塞在 worker1**

```bash
kubectl cordon sched-exp-worker2
kubectl create deploy skew --image=busybox --replicas=10
kubectl patch deploy skew --type=json -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/command","value":["sh","-c","sleep 3600"]},
  {"op":"add","path":"/spec/template/spec/containers/0/resources","value":{"requests":{"cpu":"100m","memory":"32Mi"}}}
]'
kubectl wait deploy skew --for=condition=available --timeout=120s
kubectl get pods -o wide | grep skew | awk '{print $7}' | sort | uniq -c   # 10/10 都在 worker1
```

**step 3：放活 worker2，等 descheduler 出手**

```bash
kubectl uncordon sched-exp-worker2
kubectl -n kube-system logs deploy/descheduler -f | grep -E 'LowNodeUtilization|evicted'
```

**你要看到的关键证据**

- 日志按 `pods` 维度算出 worker1 利用率 > 5%、worker2 < 3%，开始从 worker1 驱逐部分 skew Pod（`... evicted pod ...`）
- 被驱逐的 Pod 重建后落在 worker2 上
- `kubectl get pods -o wide | grep skew | awk '{print $7}' | sort | uniq -c` 倾斜比从 `10:0` 变成接近均衡（descheduler 每 2 分钟一轮）

**清理**

```bash
helm uninstall descheduler -n kube-system
kubectl delete deploy skew
kind delete cluster --name sched-exp
```

### 实验 2.4（进阶可选）自定义 Score 插件：编译 + 跑起来

> 目标：把 §9.1 的 NodeLabelScore 编成一个自定义 kube-scheduler，让它在 kind 里 Service。环境成本高（要 Go 工具链 + vendor k8s 源码），对版本敏感，**跑不通也不影响走读**——把骨架读明白更重要。

```bash
# step 1 搭骨架（基于官方仓为模子，省 go.mod 四处 replace 的痛苦）
git clone --depth 1 --branch v0.35.7 https://github.com/kubernetes-sigs/scheduler-plugins.git
cd scheduler-plugins    # 它 aligned 的 k8s 版本看 README 兼容表；v1.37 集群需要追 main

# step 2 把你的插件塞进 pkg/，参考 §9.1 骨架；并在 cmd/scheduler/main.go 里追加：
#   app.WithPlugin(myplugin.Name, myplugin.New),

# step 3 构建（Makefile 会产出 kube-scheduler 与 controller 两个镜像）
make local-image   # 产出 localhost:5000/scheduler-plugins/kube-scheduler:latest

# step 4 让 kind 集群用上（kind load 把镜像塞进节点容器运行时）
kind load docker-image localhost:5000/scheduler-plugins/kube-scheduler:latest --name sched-exp

# step 5 写一个 KubeSchedulerConfiguration + Deployment 作为第二调度器部署
#   （参考 §9.1 ② 配置、§9.2 的 ServiceAccount/ClusterRoleBinding 两条绑定）
#   跑通后，Pod 用 spec.schedulerName: <你 profile 的名字> 分流过来

# step 6 验证：给节点打 label example.com/fast-storage=true 并调度测试 Pod，
#   在 -v=5 日志里看到你的 NodeLabelScore 分与实际落点
```

**没跑通时按这个顺序查**：

- 构建错：90% 是 go.mod 版本和集群用的 k8s minor 不齐——按 scheduler-plugins README 兼容表对齐
- 镜像起不来：kind 里 `kubectl -n kube-system logs deploy/<你的调度器>`，多半是 config 或 RBAC
- Pod 永远 Pending：schedulerName 没对、profile 里 plugins score 拼写错、或者你启了全部默认 Bind 又把 DefaultBinder 也禁了

---

## 十四、速查表 + 参考链接

### 14.1 一页速查

| 主题 | 命令 / 端点 / 指标 |
|------|-------------------|
| 队列健康 | `scheduler_pending_pods{queue=active/backoff/unschedulable/gated}` |
| 尝试大盘 | `scheduler_schedule_attempts_total{result=scheduled/unschedulable/error}` |
| 端到端耗时 | `scheduler_scheduling_attempt_duration_seconds`；Pod 视角 SLI：`scheduler_pod_scheduling_sli_duration_seconds` |
| 慢在哪 | `scheduler_framework_extension_point_duration_seconds`、`scheduler_plugin_execution_duration_seconds` |
| 谁在拒绝 | `kubectl describe pod` 的事件聚合行 → §3 表格对号；`scheduler_unschedulable_pods{plugin}` |
| QHint 觉醒验证 | `scheduler_queue_incoming_pods_total{queue,event}`；兜底命中：`scheduler_pod_scheduled_after_flush_total` |
| 抢占压力 | `scheduler_preemption_attempts_total`、`scheduler_preemption_victims`；事件里 `Preempted` |
| Pending 排查链 | §7.3：events → 队列指标 → -v=5 → 单插件指标 |
| 导出真实默认配置 | `kube-scheduler --write-config-to=/tmp/defaults.yaml` |
| 调度器健康端点 | HTTPS `:10259` `/healthz` `/metrics`；pprof 依 `enableProfiling` |
| 队列节奏硬编码 | backoff 1s ×2 到 10s 封顶；flush backoff 每 1s；flush unschedulableQ 每 30s（最坏 60s） |
| percentageOfNodesToScore | 默认：100 节点 50%、5000 节点 10%、下限 5%、保底查 100 个可行节点 |
| SchedulingGates | `spec.schedulingGates` 只能创建时加、之后只能删；队列标签 queue="gated" |
| volumeBindingMode | Immediate（默认）/`WaitForFirstConsumer`；WFFC + nodeName 时 PVC 死等（绕行后没人打注解） |
| Pod 指定调度器 | `spec.schedulerName: <profile 名>`；不写默认 `default-scheduler` |
| descheduler 版本对应 | 集群 v1.37 ↔ descheduler v0.37.x；暴露 `:10258/metrics` |

### 14.2 关键要点（背诵版）

1. kube-scheduler 就是一个「**一次性约束求解器**」：watch 未绑定 Pod → 决定 nodeName → 发 Binding。调度器不管「摆好之后对不对」（那是 descheduler），也不管「起了之后怎么活」（那是 kubelet）
2. scheduling cycle **串行**、binding cycle **并发**；中间用 assume + snapshot 解耦——snapshot 只在 scheduling cycle 开头拍一次
3. 队列三档：activeQ（堆，优先级排）/ backoffQ（1s ×2 到 10s）/ unschedulableQ（map，事件唤醒）；QueueingHints（v1.28 起，**v1.34 GA 默认开**）把「全唤醒」改成「精准唤醒」
4. Scheduling Framework（v1.19 GA）= 13 个单 Pod 扩展点 + EnqueueExtensions + 3 个 Workload 扩展点（placementGenerate/placementScore/podGroupPostFilter）；背位置 + 失败去向，不背个数
5. 单 Pod 调度失败的两类语义：`Unschedulable`（可让抢占一试）vs `UnschedulableAndUnresolvable`（连试都省）；事件里 Filter 聚合 + `preemption:` 行可以一线读穿
6. Score 是 [0,100] × 权重求和；默认策略 LeastAllocated + BalancedAllocation + 内建 spread 默认约束，**kube-scheduler 天生『轻度摊开』不是 binpack**；想换策略改 `scoringStrategy` 或调 profile
7. WaitForFirstConsumer + CSIStorageCapacity（v1.24 GA）+ StorageCapacityScoring（v1.37 Beta）构成了「卷的分治」：调度器传达意图、provisioner 按拓扑落地；nodeName 绕开会死等
8. 抢占在 PostFilter；只抢更低的、同级不抢；**有等待期不占位**；PDB best effort；QoS 不参与遇害者选择；无 cross-node preemption
9. 自定义路径优先级：**Framework out-of-tree 插件 > 独立二次调度器 > Extender**（第三大 legacy，不建议新用）
10. 离线 gang scheduling：Volcano（全家桶）与 Kueue（配额+fair share+不换 scheduler）各有千秋；上游正沿着 GenericWorkload（v1.37 Beta 默认关）的路线收敛

### 14.3 参考链接

| 主题 | 链接 |
|------|------|
| Scheduling Framework 概念（扩展点、QHint、StorageCapacityScoring） | https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/ |
| Scheduler Configuration（默认插件、profiles、multiPoint、Workload 扩展点） | https://kubernetes.io/docs/reference/scheduling/config/ |
| kube-scheduler 配置 API 参考 v1 | https://kubernetes.io/docs/reference/config-api/kube-scheduler-config.v1/ |
| kube-scheduler 总览（filter+score 两步、percentageOfNodesToScore） | https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/ |
| Scheduler Performance Tuning（OpportunisticBatching、遍历方式） | https://kubernetes.io/docs/concepts/scheduling-eviction/scheduler-perf-tuning/ |
| Pod Priority and Preemption | https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/ |
| Pod Scheduling Readiness（SchedulingGates） | https://kubernetes.io/docs/concepts/scheduling-eviction/pod-scheduling-readiness/ |
| Dynamic Resource Allocation | https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/ |
| Pod Topology Spread Constraints（matchLabelKeys/minDomains/默认约束） | https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/ |
| Storage Capacity（CSIStorageCapacity） | https://kubernetes.io/docs/concepts/storage/storage-capacity/ |
| Storage Classes（volumeBindingMode/WFFC 警告） | https://kubernetes.io/docs/concepts/storage/storage-classes/ |
| Assigning Pods to Nodes（nodeSelector/亲和/nominatedNodeName） | https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/ |
| Configure Multiple Schedulers | https://kubernetes.io/docs/tasks/extend-kubernetes/configure-multiple-schedulers/ |
| 调度队列设计文档（activeQ/backoffQ/unschedulableQ） | https://github.com/kubernetes/community/blob/master/contributors/devel/sig-scheduling/scheduler_queues.md |
| scheduler 指标源码（release-1.37） | https://github.com/kubernetes/kubernetes/blob/release-1.37/pkg/scheduler/metrics/metrics.go |
| kube-scheduler framework 接口源码（release-1.37） | https://github.com/kubernetes/kubernetes/blob/release-1.37/staging/src/k8s.io/kube-scheduler/framework/interface.go |
| KEP-1819 Scheduler Extender（历史与接口） | https://github.com/kubernetes/enhancements/blob/master/keps/sig-scheduling/1819-scheduler-extender/README.md |
| descheduler | https://github.com/kubernetes-sigs/descheduler |
| scheduler-plugins（out-of-tree 插件仓） | https://github.com/kubernetes-sigs/scheduler-plugins |
| Volcano | https://volcano.sh/en/docs/podgroup/ |
| Kueue | https://kueue.sigs.k8s.io/docs/overview/ |

> 下一章预告：`K8s-网络原理详解.md`——到这里调度器已经把一个空白 `nodeName` 填上了，下一步 kubelet 拿到的 Pod 怎么经历 CNI → kube-proxy → Service 之前的那一段，都是网络篇的事。
