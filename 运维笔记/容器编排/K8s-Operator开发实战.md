# K8s Operator 开发实战

> 精通路线第 6 章：CRD 进阶（structural schema / CEL / 多版本转换）、controller-runtime 架构地图、Reconcile 幂等设计、kubebuilder 全流程、可跑的 WebApp Operator、envtest 与 fake client 测试、生产着陆清单
> 创建时间：2026-10-13
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37）；配套工具链以 2026-10 upstream 为准并逐条标注来源：**controller-runtime v0.25.2**（绑定 k8s.io/* v1.37）、**kubebuilder v4.16.0**（内置 controller-gen v0.22.0）、**kind v0.33.0**（默认 node v1.37.0）、**Go 1.26**
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，§3 list-watch / informer / workqueue 限速、§4 ownerReference / finalizer / GC——本章直接引用概念，重讲必删）、`K8s-安全加固详解.md`（第 5 章 §3 准入 webhook 开发与证书链——本章 webhook 类内容只引用一句）、`go/` 目录的 Go 入门笔记（语法层面不再解释）。

---

## 零、本文定位与边界

Operator 这个词被用得太滥，先钉死定义：

```
Operator = CRD（数据模型） + Controller（调和逻辑） + 运维知识（真正的价值）

  CRD         「你管理的这个东西，在 API 里长什么样」     → §1
  Controller  「实际状态 → 期望状态」的无限循环            → §2 §3 §5
  运维知识     upgrade 顺序、备份策略、故障自愈、resize…
               写进代码的那部分，才是 Operator 和脚本的分水岭
```

前两者 kubebuilder 十分钟能搭出来；第三者决定了你的 Operator 是「又一个 YAML 转换器」还是「真的会干活」。Cert-Manager 管证书全生命周期、Prometheus Operator 把一整套监控栈抽象成几个 CR、CloudNativePG 管 PG 主从切换——它们卖的都是第三条。

**本章交付物**：一个能在 kind 上跑通的 WebApp Operator（Deployment + Service + status conditions + finalizer + printer columns），全部 Go 代码在本机用 **go1.26.0 + controller-runtime v0.25.2 真实 `go vet` / `go build` / `go test` 通过**（§5 开始前会再说明验证环境）。

```
阅读顺序与代价：
  只想要「先跑起来」     → §4 §5 §9（实验三连）
  想知道「为什么这么写」 → §1 §2 §3（设计原理）
  要上线去               → §6 §7 §8（测试、着陆、故障清单）
```

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `K8s-API机制深入.md`（第 1 章） | §3 list-watch 握手 / Reflector→DeltaFIFO→Indexer / WorkQueue 三形态与限速器；§4 ownerReference / 三种级联删除 / finalizer 卡死处置 | controller-runtime 的 Cache 与 workqueue 只说「框架替你包了什么」，机制本身一句话引用 |
| `K8s-资源全览.md`（§十） | CRD 最小 YAML 与常见 CRD 生态 | 不再讲「CRD 是什么」，直接进 structural schema |
| `K8s-调度器深入.md`（第 2 章 §9） | Framework 插件 Go 骨架与「骨架能编译」的标准 | 沿用同标准：本章所有 Go 代码可 `go build` |
| `K8s-安全加固详解.md`（第 5 章 §3） | 准入 webhook 开发、证书链、failurePolicy 故障域 | conversion/validation webhook 只画边界，TLS 与故障域引用一句 |
| `go/` 目录笔记 | Go 语法、模块、interface | 本章 Go 代码按「能读懂标准库」的前设来写 |

> ❗ **版本标注约定**：文中「vX.Y 起 Beta/GA」「某工具当前版本 vX」的说法均已对照官方 docs、GitHub releases 或上游源码核实（§10.3 给出全部链接）；第三方项目发版极快，落地前用链接再确认一次。文中 controller-runtime 的 API 行为均可在本地 module cache 的 `sigs.k8s.io/controller-runtime@v0.25.2` 源码中复核。

---

## 一、CRD 进阶

「会写一段 CRD YAML」和「CRD 在线安全演进」之间隔着这一节。CRD 最小骨架见 `K8s-资源全览.md` §十，不复述。

### 1.1 structural schema：pruning / defaults / validation 三件套的前提

apiextensions.k8s.io/v1 强制要求 **structural schema**——apiserver 要能一眼从 schema 推出「这棵对象树上每个节点是什么类型」。官方定义四条规则，违规特征对照表：

| # | 规则 | 违规写法（典型） |
|---|------|-----------------|
| 1 | 根与每个 object 节点必须声明非空 `type` | 只写 `properties:` 不写 `type: object` |
| 2 | `allOf/anyOf/oneOf/not` 里出现的字段，**必须在这些逻辑体外也声明** | `anyOf: [{properties: {replicas: …}}]` 而外层没有 `replicas` |
| 3 | 约束（如 `description`、`minimum`）不许只写在 `allOf/anyOf/oneOf/not` 内部 | 把 `description` 塞进 `anyOf` 子句 |
| 4 | `metadata` 只允许限制 `name` / `generateName` | 在 schema 里给 `metadata.finalizers` 加规则 |

违规不会拒掉 CRD，而是落在 CRD 的 `status.conditions` 里报 **`NonStructural`** 条件——`kubectl get crd <name> -o jsonpath='{.status.conditions}'` 可查。三个后果：

- **不 pruning**：除 `metadata` 外的未知字段会被**原样存进 etcd**（v1 默认 `preserveUnknownFields: false`，即整树剪枝；但剪枝依赖 schema 完整——structural 才有意义）。
- **不 defaulting**：schema 里的 `default:` 在读取/写入时回填（**v1.17 起 GA**），non-structural 下失效。
- **不能用 `x-kubernetes-validations`（CEL）**：CEL 校验的前提就是 structural schema。

子树豁免：某个字段确实是「自由 JSON」时，在该节点挂 `x-kubernetes-preserve-unknown-fields: true`——只豁免这一棵子树，不伤整树（`additionalProperties: true` 同理仅豁免该层）。**纪律：能写结构就别豁免**，剪枝 + defaults + CEL 是比自由 JSON 值钱得多的三件套。

### 1.2 CEL 内建校验：`x-kubernetes-validations`（版本纠正：v1.25 Beta → **v1.29 GA**）

> ❗ **版本纠正**：很多二手资料写「1.25 起内建 CEL」。官方 CRD 页原文：**Stable since Kubernetes v1.29**（v1.25 首次 Beta）。v1.37 集群里它是稳定特性，放心用。

不用装任何组件，规则就写在 CRD 的 schema 节点上，`self` 绑定到该节点的作用域值：

```yaml
spec:
  type: object
  properties:
    replicas:    { type: integer }
    maxReplicas: { type: integer }
  x-kubernetes-validations:
  - rule: "self.replicas <= self.maxReplicas"
    message: "replicas 不能超过 maxReplicas"
  - rule: "self.image != '' && !self.image.endsWith(':latest')"
    message: "image 必填且不许 :latest"
# 根节点还能访问 metadata（跨字段校验的杀手级用法）：
# 放在根对象上 → rule: "self.metadata.name.startsWith(self.spec.prefix)"
```

关键事实（逐条核对官方 CRD 页「Validation rules」节）：

- **成本上限**：apiserver 在**创建/更新 CRD 时静态估算**每条 rule 的最坏成本，超限直接拒绝写入 CRD，报错形如 `CEL rule exceeded budget by more than 100x (try simplifying the rule, or adding maxItems, maxProperties, and maxLength ...)`。纪律：**凡是被 CEL 遍历的 string/map/list，必须同步写 `maxLength` / `maxProperties` / `maxItems`** 把最坏情况钉死，否则 compile 期就被拒。
- **作用域**：只能看当前对象（+`metadata`），**不能跨对象、不能查外部世界**——这是和第 5 章 §3.6（VAP 只能看请求对象 + namespaceObject + params）同样的边界。要跨对象/查外部，还是得 webhook。
- **oldSelf 过渡规则**：`self.replicas >= oldSelf.replicas`（只升不降）、`self.foo == oldSelf.foo`（不可变）这类引用 `oldSelf` 的规则**只在 update 时评估**，create 时跳过；`optionalOldSelf: true` 允许「旧值缺失也算过」的自定义回退（与 ratcheting 同一特性家族，v1.37 集群可用）。
- **校验回退（ratcheting）**：CRD 的校验变严后，**不动该字段的存量对象不能被「顺手拒之门外」**——`CRDValidationRatcheting`（v1.28 Alpha → v1.30 Beta → **v1.33 GA 默认开**）：更新时若该字段值未变，则该字段上的新校验被跳过。例外（v1.37 实现，官方列明）：`allOf/anyOf/oneOf/not` 量词、list type 变更、`required` 变化、metadata 内建校验**不参与回退**；含 `oldSelf` 的过渡规则永不回退。
- **运行时预算**：单次规则求值也有上限——解释器执行步数超限会被强制 halt 并返回错误（一拒俱拒，静态估算之外的运行时保险丝）。

与 webhook 的分工一句话：**CEL 是准入逻辑的默认起点**（进程内求值、无 HTTPS 服务、不占 seat 网络往返），webhook 只留给 CEL 视野之外的校验（镜像验签、跨对象引用、调公司系统）。

### 1.3 多版本与 conversion webhook

CRD 的 `spec.versions[]` 是列表——多个版本可以**同时 served**，但**有且仅有一个 `storage: true`**（落盘版本）：

```
kubectl 写 v1alpha1 ──┐
                      ├─→ apiserver 转换 ─→ 以 v1（storage）落 etcd
kubectl 读 v1beta1  ──┘        ▲
                               └─ 转换策略（spec.conversion.strategy）：

  None（默认）  只允许「字段完全相同」的机械改名（仅修 apiVersion 字段）
               —— 字段没变的扁平演进用它
  Webhook      结构变了（拆字段/改类型）→ 你起一个 HTTPS 服务做双向转换，
               apiserver 拿着 ConversionReview 报文来问你
```

kubebuilder 的转换接口模式（教程实测骨架，`sigs.k8s.io/controller-runtime/pkg/conversion`）：

```go
// Hub（中心版本，通常是 storage 版本）：一个空标记方法
// api/v1/webapp_conversion.go
func (*WebApp) Hub() {}

// Spoke（其他版本）：实现 Convertible——双向转换
// api/v1alpha1/webapp_conversion.go
func (src *WebApp) ConvertTo(dstRaw conversion.Hub) error   // 我 → hub
func (dst *WebApp) ConvertFrom(srcRaw conversion.Hub) error // hub → 我
```

脚手架命令：`kubebuilder create webhook --group apps --version v1 --kind WebApp --conversion --spoke v2`。与第 5 章 §3 的关系一句：conversion webhook 和 admission webhook 复用同一套 webhook server/证书/故障域知识（第 5 章 §3.5 全部适用），区别只在报文协议（AdmissionReview → ConversionReview）和配置载体（`ValidatingWebhookConfiguration` → CRD 的 `spec.conversion.webhook`）。**生产警示提前说**：conversion webhook 挂掉 = 该 CRD 全版本读写全瘫（§8.7）。

### 1.4 subresources 与 kubectl 体验四件套

| 字段 | 语义（已核对） | 实战价值 |
|------|---------------|---------|
| **`subresources: { status: {} }`** | status 从主对象**拆成独立端点**：写 status 走 PUT `/status`，不 bump `metadata.generation`；主对象的 RBAC 与 `xxx/status` 分开授 | Operator 回写状态的唯一正路（§3.4）；同时普通用户改 spec 不必有 status 权限 |
| `subresources: { scale: { specReplicasPath: .spec.replicas, statusReplicasPath: .status.readyReplicas, labelSelectorPath: .status.selector } }` | 让你的 CR 接管**标准 Scale 子资源** | `kubectl scale webapp xxx --replicas=3`、**HPA 直接以你的 CR 为 scaleTargetRef**——这就是「Operator 化」的临门一脚 |
| `additionalPrinterColumns` | `kubectl get` 多出列：`name/type/JSONPath(/description/format/priority)`（priority>0 只在 `-o wide` 显示） | 把 `.status.url`、`Available` condition 直接拍在列表页（§9.3 实验） |
| `names: { shortNames: [wa], categories: [ops] }` | `kubectl get wa`；`kubectl get ops` 一次拉出整个类别 | 少打字；团队级资源打包查看 |

**为什么这么设计**：这四件套的本质是「让 CR 与内建资源平级」。内建 Deployment 之所以好用，不是它特殊，而是 status/scale/printer columns/categories 全都配齐了——CRD 全都可以有，写完这四件，你的 CR 在 `kubectl`/`HPA`/`K9s`/`ArgoCD` 里就是一等公民。

---

## 二、controller-runtime 架构地图

写 Operator 有两条路：裸 client-go 攒 informer/workqueue（第 1 章 §3 的全家桶自己接），或用 **controller-runtime**——kubebuilder / Operator SDK / 以及你能叫出名的几乎所有 Operator（cert-manager、ArgoCD、Karpenter、prometheus-operator）都是后者。这一节看懂它替你包了什么。本节 API 行为均以本机 `sigs.k8s.io/controller-runtime@v0.25.2` 源码核对。

### 2.1 Manager：进程里的「控制面宿舍」

```
                        ┌──────────── Manager（一个 Go 进程一个就够）────────────┐
                        │                                                        │
  kubeconfig/in-cluster │  Scheme     GVK ↔ Go 类型 ↔ List 类型的注册表           │
        cfg ───────────▶│  Cache      每种被 watch 类型一份 informer（共享）      │
                        │  Client     读走 Cache，写直连 apiserver               │
                        │  EventRecorder  events.k8s.io 事件（v0.23+ 新 API）    │
                        │                                                        │
                        │  Controller A ─ Reconciler A ──┐                       │
                        │  Controller B ─ Reconciler B ──┤ 共享 Cache/Client     │
                        │  Webhook server（9443，可关）  ─┘                       │
                        │  metrics（8443 TLS） healthz/readyz（8081） pprof(关)  │
                        │  LeaderElection（Leases，默认关）                      │
                        └────────────────────────────────────────────────────────┘
```

Manager 的本质是**组件宿舍 + 依赖注入器**：`SetupWithManager(mgr)` 时你的 Reconciler 拿到的 `mgr.GetClient()`、`mgr.GetScheme()`、`mgr.GetConfig()` 都是 Manager 替你实例化好的。第 1 章 §3.6 的 Reflector→DeltaFIFO→Indexer 被 Cache 包在里面，§3.7 的 WorkQueue 藏在每个 Controller 里——你写的是 Reconciler 这一个函数。

### 2.2 Cache vs Client：**读走缓存，写直连**（最容易误解的一条）

| 操作 | 去向 | 后果 |
|------|------|------|
| `client.Get / List`（结构化类型） | **本地 informer cache**（第 1 章 §3 的 Indexer） | 不占 apiserver 配额；但**可能读到秒级旧数据** |
| `client.Create / Update / Patch / Delete` | **直连 apiserver** | 写完立即成功，但**紧接着 Get 可能还没看到**（cache 同步有延迟） |
| status 写（`Status().Update/Patch`） | 直连 apiserver 的 `/status` 端点 | 同样要 CRD 声明了 status 子资源（§1.4） |
| 非缓存读 | `mgr.GetAPIReader()` | 绕过 cache 直连 apiserver——大字段校验/强一致必需时才用 |

三个经典错觉全部来自这张表：

- **「我明明 Create 成功了，Get 却 NotFound」**——写已到 apiserver，cache 还没同步。正确姿势：别在 Create 后立刻读自己写的对象再行动，**把后续动作放进下一轮 reconcile**（事件/返回值会带你回来）。v0.25.0 新增实验特性 `Client.EnableReadYourWritesConsistency: new(true)` 正是治这个病，但**仍是实验 API**（v0.25.2 源码注释），生产先别依赖。
- **「deletionTimestamp 迟迟不见」**——你 watch 的是 cache 视图，delete 事件同步过来需要时间。
- **「List 全量 ConfigMap 把 apiserver 打爆」**——不会，读的是本地 cache；但**你 watch 的类型越多、对象越大，Operator 内存越大**（cache 全量驻留），按 namespace / label 收窄 watch 的旋钮在 `cache.Options.ByObject`（`Namespaces`、`Label`、`Field`、`DisableFor`）。

**Scheme 的作用**：client 只认注册进 Scheme 的类型——`no kind is registered for the type` 报错就是忘了 `AddToScheme`。v0.24 起 apimachinery 的 `scheme.Builder` 被标 deprecated（controller-runtime v0.24.0 release notes「Scheme: Deprecate the scheme builder」），脚手架改用 `runtime.NewSchemeBuilder(func(*runtime.Scheme) error {...})`（§5 的 groupversion_info.go 就是新形态）。

### 2.3 Builder：把「watch 拓扑」声明出来

`SetupWithManager` 里那条链式调用，声明的是**什么事件该把你叫醒**：

```go
ctrl.NewControllerManagedBy(mgr).
    For(&WebApp{}, builder.WithPredicates(predicate.GenerationChangedPredicate{})). // 主对象：只看 spec 变化
    Owns(&appsv1.Deployment{}).                                                     // 我拥有的子对象：任何变化都回链
    Watches(&corev1.ConfigMap{}, handler.EnqueueRequestsFromMapFunc(r.mapConfigMapToWebApps)).
    WithOptions(controller.Options{MaxConcurrentReconciles: 4}).
    Named("webapp").
    Complete(r)
```

三种 handler 的分工（拼写以 v0.25.2 源码为准——注意第三个是复数 **Requests**）：

| handler | 入队什么 | 用在 |
|---------|---------|------|
| `EnqueueRequestForObject` | 事件对象**自己**的 namespace/name | `For()`——主对象的每次变化 |
| `EnqueueRequestForOwner` | 沿 `ownerReferences` 找到 **owner**（`OnlyControllerOwner: true` 默认，只看 `controller: true` 那把） | `Owns()`——子对象被删/被改 → 唤醒亲爹重建 |
| `EnqueueRequestsFromMapFunc` | 你把事件对象映射成**任意一组 Request**（可跨类型、可批量、可空） | `Watches()`——ConfigMap 变了唤醒引用它的 100 个 CR |

**Predicate 速查**（`pkg/predicate`，都是「事件进不进队列」的前置过滤器）：

| predicate | 语义 |
|-----------|------|
| `GenerationChangedPredicate` | Update 只在 `generation` 变化时放行——**主对象几乎必挂**（status/finalizer 写入不 bump generation，挡住自激循环） |
| `LabelChangedPredicate` / `AnnotationChangedPredicate` | 标签/注解变化才放行 |
| `ResourceVersionChangedPredicate` | RV 变就放（聊胜于无） |
| `NewPredicateFuncs(func(client.Object) bool)` | 按对象内容自定义（如「只看带某 label 的」） |
| `predicate.And / Or / Not` | 组合 |

> ❗ 踩过真坑：`WithEventFilter(pred)` 会**无差别加到 For/Owns/Watches 全部 watch 上**——给主对象挂 GenerationChangedPredicate 顺手也挡住了子 Deployment 的 status 事件（Deployment 的 status 变化不动 generation），副本状态永远不对齐。**按 watch 分别挂：用 `builder.WithPredicates(...)` 作为 `For()/Owns()/Watches()` 的第二个参数**（§5 代码即此写法）。

### 2.4 Reconcile 的四种返回：源码级语义（v0.25.2 `reconcileHandler` 原文核对）

```go
// 返回值与队列动作的对照（源码 switch 直译）：
//
// err != nil            → AddRateLimited（退避重试，指标 ReconcileErrors+1）
//                         ⚠️ 若 err 是 reconcile.TerminalError(e)：直接丢弃，永不重试
//                         ⚠️ err 非 nil 时 Requeue/RequeueAfter 一律被忽略（并打 Warning 日志）
// RequeueAfter > 0      → Forget（清退避） + 定时 AddAfter（等外部异步事件的标准姿势）
// Requeue == true       → AddRateLimited（退避重试；字段已 Deprecated：官方指路用
//                         RequeueAfter 表达「等外部事件」，别借用错误重试的退避节
// 全零 + nil            → Forget（退避清零，安静等下一个事件）
```

底下是 client-go 的 typed workqueue + 限速器——机制第 1 章 §3.7 已讲（单项指数退避 5ms→1000s + 全局 10 qps/burst 100，两者取慢），controller-runtime 的默认值就是同款 `MaxOfRateLimiter`（v0.25.2 controller.go 注释原文），可用 `controller.Options.RateLimiter` 换。两个被低估的事实：

- **`MaxConcurrentReconciles` 默认 1**——`make run` 日志里 `Starting workers {"worker count": 1}` 就是这行。CR 一多，先后调谐是排队的；调大要注意 409 冲突概率也随之上升。
- **Priority queue v0.23 起默认开**（`UsePriorityQueue: *bool`，默认 true）——reconcile.Result 新增 `Priority *int` 字段，高优 CR 可以插队；不用就无视这个字段。

### 2.5 leader election / metrics / healthz / pprof

- **Leader election**：`--leader-elect`（scaffold 默认 false 起步）+ `LeaderElectionID`。锁是 **Lease 对象**（coordination.k8s.io，`LeaderElectionResourceLock` 默认 `"leases"`，manager Options 不写时 LeaseDuration/RenewDeadline/RetryPeriod 用 client-go 经典默认 15s/10s/2s）。注意三点：① **standby 副本也会完整拉起 cache/informer**（内存不误省），省的是「写动作」；② 开了选主，RBAC 必须给 `coordination.k8s.io/leases` 的 get/create/update（scaffold 的 `config/rbac/leader_election_role.yaml` 已预置）；③ 优雅退出可选 `LeaderElectionReleaseOnCancel: true`——主动让位，新主不用干等 LeaseDuration。
- **metrics**：当前 scaffold 默认 **`:8443` HTTPS + authn/authz 过滤**（`metricsserver.Options{SecureServing: true}` + `filters.WithAuthenticationAndAuthorization`）；老教程里 `:8080` 明文形态是历史版本，上生产以 HTTPS + RBAC 为准（kustomize 里解除 `[METRICS-WITH-CERTS]` 注释接 cert-manager）。
- **healthz/readyz**：默认 `:8081`（`HealthProbeBindAddress`），`mgr.AddHealthzCheck("healthz", healthz.Ping)` 起步，Cache 未同步时 readyz 自动 500。
- **pprof**：`mgr.Options{PprofBindAddress: ":8082"}`，**默认关**——排查 goroutine/heap 泄漏才开，开完记得关（控制面进程的 profile 也是情报）。

### 2.6 写入策略全景：Update / Patch / SSA 怎么选

| 策略 | 代码形态 | 语义 | 何时用 |
|------|---------|------|--------|
| **Update（read-modify-write）** | `r.Update(ctx, obj)` | 全量覆盖（带 resourceVersion 乐观锁，撞了报 409） | 对象**完全由你这个 controller 拥有**，每轮 reconcile 都是「算出新全量」；§5 用 |
| **Patch（client patch）** | `r.Patch(ctx, obj, client.MergeFrom(orig))` | 三种 patch type：strategic（内建类型，按 patchStrategy 并表）、merge（JSON Merge Patch）、JSONPatch | 与别人**共管**的大对象：以「修改前的快照」为基准算差分，只覆盖你动的字段，别人的字段不伤；`MergeFrom` 最常用 |
| **Server-side Apply（SSA）** | `r.Patch(ctx, obj, client.Apply, client.FieldOwner("webapp-operator"))` | apiserver 按 **field manager** 逐字段仲裁所有权，冲突返回 409 + 字段清单 | 共管对象 + 想显式声明「我拥有哪几个字段」；**v0.23 起 `Status().Patch(..., client.Apply)` 也支持 status 子资源**（v0.23.0 release「Client: Add subresource Apply support」） |

三条纪律：① 别用 Update 去全量覆盖「别人也会改」的对象（manual scale 的 Deployment、HPA 染指的 replicas——那是 §8.6 field manager 冲突的温床）；② SSA 的 apply 对象必须是**只含你拥有的字段的「骨架对象」**，把 Get 出来的对象改两笔就 Apply 是反模式（你没有的字段会被你「认领」）；③ 409 冲突不需要代码里特判——**统一交回给 workqueue 退避重试**，下一轮拿到新 RV 自然收敛。

**为什么这么设计**：Cache/Client 分离 + Builder 声明式 watch + 单一 Reconcile 签名，本质是把控制器最难写对的三件事——事件拓扑、一致性窗口、重试节奏——全部标准化。你的代码只剩**读快照、算差分、写回**。

---

## 三、Reconcile 设计原则（思想章）

代码骨架十分钟能抄，下面这些原则决定你的 Operator 上线后是「自愈」还是「自残」。

### 3.1 level-based，不是 edge-based

`reconcile.Request` 的源码注释原文：「It does NOT contain information about any specific Event or the object contents itself.」——**通知你的不是「发生了什么事」，只是「去看看」**。

```
edge-based（错误心智）：“收到 delete 事件 → 我把状态机切到 Deleting”
   问题：事件会丢（watch 断线 410）、会重复（relist 重发）、会乱序
level-based（正确心智）：“每次 reconcile 把当前快照拉出来，算全量差分并收敛”
   事件只负责把你叫醒；真相永远来自此刻的 Get/List
```

推论：任何「依赖事件序列才能走对」的 Reconcile 都是错的——把每个分支都写成**从快照可独立得出**。

### 3.2 幂等铁律与「小步提交」

- **同一 spec 跑 N 次 reconcile = 跑 1 次**。判断「要不要动手」永远用 Get 出来的现状对比；不能假设「上一轮我刚改过」。
- **每一轮尽量做一小步、做完就提交**（ensure A → ensure B → 写 status），中途出错 return——下一轮从快照重新走，天然续跑。忌讳「攒一大口气全做完才写」——半路崩了状态全丢，恢复逻辑变得不可写。
- **adopt or create**：子对象已存在就校对自己的字段（漂移纠偏），不存在才建——§5 的 ④⑤ 就是这个模式。

### 3.3 `SetControllerReference` 建链（一行代码三个收益）

```go
controllerutil.SetControllerReference(owner, dependent, scheme)
```

`ownerReferences` 结构语义见第 1 章 §4.1（`controller: true` / `blockOwnerDeletion: true` / uid 锚定），不重述。对 Operator 的三收益：① GC 级联删除自动送你（删 CR → Deployment/Service 被收走）；② `Owns()` 事件回链靠它（子对象出事唤醒你）；③ 别的控制器**不敢碰**带 controller owner 的对象（ReplicaSet controller 不会收养，别的 Operator 也不该）。两个坑：**跨 namespace owner 非法**（同 §4.1 的 `OwnerRefInvalidNamespace`）；它返回 error（owner/dependent 不同 ns 或已存在别的 controller owner 时才非 nil），教学代码可 `_ =` 忽略，生产建议把 err 返回出来（撞 owner 是值得 surface 的事故）。

### 3.4 status 与 spec 的「脑体分离」

```
写 spec/metadata        → r.Update / r.Patch          （ bump generation）
写 status               → r.Status().Update / Patch   （不 bump generation）
触发自己的 reconcile    → GenerationChangedPredicate 过滤掉（§2.3）
```

- **status 子资源必须先声明**（§1.4），否则 `Status().Update` 直接被 apiserver 拒。
- **`ObservedGeneration` 纪律**：每轮把当前 `generation` 抄进 status。客户端据此判断「status 是旧 spec 的还是新 spec 的」——`kubectl wait --for=jsonpath='{.status.observedGeneration}'=N` 与 GitOps 健康检查都靠它。
- **`metav1.Condition` 标准**：`meta.SetStatusCondition` 管理；type 如 `Available/Progressing/Degraded`，status 三态 True/False/Unknown；**Reason 命名纪律：PascalCase、稳定枚举、进得了告警规则**（`ReconcileFailed` 可以，`DeploymentCreateTimeoutAfter30Seconds` 不行）；Message 是人话、允许带变量；`ObservedGeneration` 字段每条 condition 都应填。
- **写 status 也要「无变化就不写」的意识**：`meta.SetStatusCondition` 只在条件变化时更新 lastTransitionTime——值没变时新 status 与线上完全一样，但 `Status().Update` 照样要过准入链、bump resourceVersion；风暴期这是 apiserver 的隐形压力（生产上先比较再写：`if apiequality.Semantic.DeepEqual(old.Status, new.Status)` 跳过）。

### 3.5 finalizer 时机表（决策版；机制见第 1 章 §4.3）

| 决策点 | 答案 | 依据 |
|--------|------|------|
| 什么时候需要 finalizer？ | **只有「集群外还有以我为凭据的资源」时**（LB/DNS/云盘/第三方注册） | 纯 ns 内子对象靠 ownerReference + GC 就够，加 finalizer 是给自己添刽子手环节 |
| 什么时候挂？ | 首次 reconcile 见到对象就挂（先挂再干活） | 先干活后挂：删除时清理动作可能永远赶不上 |
| 什么时候摘？ | `DeletionTimestamp != 0` 分支里，清理**成功后**才摘 | 清理失败：把错误写进 condition，重试——**不能放弃式硬摘** |
| 摘除后会发生什么？ | finalizers 清空 → apiserver 真正从 etcd 删除（连对象都 Get 不到） | 摘完再 reconcile 是 404 路径，属于正常 |
| 需要什么权限？ | `resources=xxx/finalizers, verbs=update`（§5 控制器顶部的五条 RBAC marker 之一） | 少了它：更新 finalizers 403，对象卡 Terminating |
| 清理动作本身卡住怎么办？ | 重试 + condition 外显 + 告警；**人工摘 finalizer 是破窗的最后手段**（第 1 章 §4.3 卡死处置表） | 硬摘 = 假装已清理，外部资源变孤儿收费 |

### 3.6 并发与退避的「场景调参」

| 场景 | 调法 |
|------|------|
| CR 数量几百上千、单轮调和快 | `MaxConcurrentReconciles: 8~32` |
| 经常调外部系统（云 API、DNS） | `RequeueAfter` 轮询 + `RateLimiter` 单项上限调低；加抖动 |
| 只关心个别高优 CR | priority queue，`Result.Priority` 插小值 |
| 一个「毒 CR」反复报错 | 无操作——内置退避（5ms→1000s 封顶）已经隔离它；要观测看 `workqueue_retries_total` |

### 3.7 十条反模式（每条都有线上事故原型）

| # | 反模式 | 为什么出事 |
|---|--------|-----------|
| 1 | `For(Secret)/Watches(Pod)` 这类**全量热资源**不加 predicate 与过滤 | watch 大爆炸（第 1 章 §3.8 的 60 进程 × 5000 Pod 事故原型）——list 风暴 + reconcile 风暴 |
| 2 | 用 **Annotation 记「上一轮我做过什么」** 作为状态机 | edge-based 化：事件丢失/重复时行为不可复现；状态必须能从 Get 快照推导 |
| 3 | 把对象从 cache 里 Get 出来**直接改内存再复用** | 你改的是多 goroutine 共享的 informer 存储——污染整个进程的视图（第 1 章 §3.6「严禁直接改缓存对象」）。改之前 `DeepCopy`（client.Get 每次都反序列化新对象，天然安全；`mgr.GetCache().Get` 才会拿到共享体） |
| 4 | 子对象 ownerReference 漏建 / 建错（controller=true 撞车） | 删除 CR 留下满集群孤儿；或两个控制器抢同一个子对象导致反复覆盖 |
| 5 | Update 全量覆盖「共管对象」 | 把 HPA 改的 replicas、webhook 注入的 sidecar 冲掉，跟对方互相打架成 infinite reconcile（§5 实验 6.2 踩坑实录的同款根因在一次真实事故里烧掉过整夜） |
| 6 | err 非 nil 时还设置 RequeueAfter / Requeue | **被静默忽略**（源码打 Warning 日志）——「以为有定时重试其实没有」 |
| 7 | 没有 conditions、没有 events | 用户只能靠 `kubectl describe` 的 events 与 log 猜——oncall 噩梦。Conditions 是 Operator 的「对外 API」 |
| 8 | finalizer 里做长事务 / 同步等待外部资源 | DeletionTimestamp 挂起期间对象「死不透」：ns 删除卡死（第 1 章 §4.3），升级/迁移全部被一扇窗卡住 |
| 9 | 没开 leader election 就跑了 2 副本 | 脑裂（split-brain）：两个 active 互相覆盖子对象（§8.3） |
| 10 | 把 ✨任何✨ 日志/error 里塞 secret/token/整对象 YAML | 控制面日志聚合起来后变成秘密泄漏面（第 5 章 §5 的第三条通道）——只记 name/ns/关键字段 |

**为什么这么设计**：Reconcile 的正确性模型其实是「**高级语言的 declarative runtime**」——K8s 已有的所有控制器（Deployment→RS→Pod 链）都是同型：读快照、算差分、小步提交、限速重试。不按这个模型写，框架替你兜的每一层（cache、queue、predicate）都会反噬成奇葩故障。

---

## 四、kubebuilder 全流程

kubebuilder 是「controller-runtime 的项目脚手架 + 代码发生器管家」——它生成的不是「一套框架」，而是一个普通 Go module：你随时能脱离 CLI 继续写。本节版本均按 2026-10 上游核对：**kubebuilder v4.16.0**（内置 **controller-gen v0.22.0**，生成的 CRD 带 `controller-gen.kubebuilder.io/version: v0.22.0` 注解，与 §5 实产生物一致）。

### 4.1 安装与第一条链

```bash
# macOS：brew install kubebuilder；通用（官方 quick-start 形态）：
curl -L -o kubebuilder "https://go.kubebuilder.io/dl/latest/$(go env GOOS)/$(go env GOARCH)"
chmod +x kubebuilder && sudo mv kubebuilder /usr/local/bin/
kubebuilder version   # v4.16.0

mkdir myop && cd myop
kubebuilder init --domain ops.example.com                     # --repo 指定 module 路径
kubebuilder create api --group apps --version v1alpha1 --kind WebApp   # 问 Create Resource [y/n] → y
```

`--domain` 决定 group 后缀（`apps.ops.example.com`）；不喜欢可随时改（生成物就是纯文本，改完重跑 manifests 即可）。想有第二个 kind 就再跑一次 `create api`。`init` 之后可用 `kubebuilder edit --plugins=...` 追加插件（如 helm/v2-alpha 出 Helm chart）。

### 4.2 骨架目录逐个讲（`kubebuilder init + create api` 产物，v4.16 形态）

```
myop/
├── PROJECT                          # 脚手架元数据（cliVersion/domain/plugins），
│                                    #   后续 create/alpha update 都读它，别删
├── go.mod go.sum                    # 普通 Go module；v4.15+ 骨架 go directive 是 1.26.x
├── cmd/main.go                      # Manager 装配（§2.1 那张图的代码版）
├── api/v1alpha1/
│   ├── groupversion_info.go         # GroupVersion + runtime.NewSchemeBuilder（新版无 scheme.Builder）
│   ├── webapp_types.go              # ★ 你的 spec/status 字段加这里（改完跑 make generate/manifests）
│   └── zz_generated.deepcopy.go     # make generate → controller-gen object 产物（勿手改）
├── internal/controller/
│   ├── webapp_controller.go         # ★ 你的 Reconcile 写这里
│   └── suite_test.go                # envtest 测试壳（§6.2）
├── config/                          # ★ Kustomize 天下：
│   ├── crd/bases/                   # make manifests → CRD 清单（含注解版本金印）
│   ├── rbac/                        # role.yaml（markers 生成）、leader_election_role 等
│   ├── manager/manager.yaml         # controller Deployment（镜像 IMG 由 kustomize 注入）
│   ├── samples/                     # create api 顺手生成的 CR 样例（apply -k config/samples）
│   ├── prometheus/                  # ServiceMonitor；network-policy/ 可选加固
│   └── default/kustomization.yaml   # 总装：crd+rbac+manager(+可选 webhook/certmanager/prometheus)
├── Dockerfile  Makefile  .golangci.yml  .devcontainer/  .github/workflows/
└── test/ (e2e)                      # 可选 e2e 测试模板
```

Makefile 关键目标（与 hand-rolled 命令的对应）：

| 目标 | 展开是 | 何时用 |
|------|--------|--------|
| `make generate` | `controller-gen object paths=./api/...`（deepcopy） | 改 types.go 之后 |
| `make manifests` | `controller-gen crd webhook rbac:roleName=manager-role paths=./...`（CRD+RBAC） | 改 markers/字段之后 |
| `make install` | `kubectl apply -k config/crd` | CRD 进集群（**先于任何 CR**） |
| `make run` | `go run ./cmd`（用本地 kubeconfig 连集群） | 本地调试主战场（§9.2） |
| `make docker-build docker-push IMG=` | 构建并推镜像 | 上线/入集群 |
| `make deploy IMG=` | `kubectl apply -k config/default` | controller 正式进集群 |
| `make build-installer IMG=` | 打出单文件 install.yaml（含 CRD+RBAC+manager） | 发版/交付 |
| `make uninstall` / `make undeploy` | 对应删除链 | §9.1 收尾 |

### 4.3 markers：types.go 上的「注解驱动清单」

```go
// 校验（→ CRD schema）：
// +kubebuilder:validation:Minimum=1 | Maximum=50 | MinLength=1 | MaxLength=64
// +kubebuilder:validation:Pattern=`^...$` | Enum=A;B | XValidation:rule="self.x>0",message="..."
// +kubebuilder:default=1        （→ schema default，v1.17+ 服务端回填）
// +optional / +required / +kubebuilder:validation:Optional
// +listType=map +listMapKey=type（status.conditions 的标配）
// 子资源与展示（→ CRD spec）：
// +kubebuilder:subresource:status
// +kubebuilder:subresource:scale:specpath=.spec.replicas,statuspath=.status.readyReplicas
// +kubebuilder:printcolumn:name="READY",type=integer,JSONPath=`.status.availableReplicas`
// +kubebuilder:resource:shortName=wa,categories={ops},scope=Namespaced
// RBAC（→ config/rbac/role.yaml，写在 controller.go 上）：
// +kubebuilder:rbac:groups=apps,resources=deployments;deployments/status;deployments/finalizers,verbs=get;list;watch;create;update;patch
// webhook（→ 生成 XXXWebhookConfiguration，第 5 章 §3 的协议由框架代写）：
// +kubebuilder:webhook:path=/mutate-...,mutating=true,failurePolicy=Fail,groups=apps,resources=webapps,verbs=create,versions=v1alpha1,name=...
```

**为什么 markers 比手写 YAML 强**：CRD schema / RBAC / webhook 三份清单漂移是常态——markers 让「唯一事实源」回到 Go 类型上，审查 diff 时看得懂。`-XValidation` marker 就是 §1.2 的 CEL 内建规则——marker 形态写出来的是同一棵 schema。

### 4.4 常见「欧洲坑」（按踩中频率排）

| # | 坑 | 现象 → 根治 |
|---|----|------------|
| 1 | **controller-gen 版本与 Go 版本错位** | 老项目 go.mod 还停 go1.21/1.22，新 controller-gen（本机实测 v0.22.0 go.mod 要求 **go1.26.0**；v0.23/v0.24 的 controller-runtime 也逐级抬高）→ `make generate` 报模块/语法错。根治：Makefile 里 `CONTROLLER_TOOLS_VERSION` 钉死，与 kubebuilder 发行注记对齐（v4.15 起骨架 go directive = 1.26.x）；团队统一 `go install sigs.k8s.io/controller-tools/cmd/controller-gen@vX.Y.Z`，不要 `@latest`（go toolchain 自动切换仍要求代理可达） |
| 2 | **CRD 与 controller 分离部署的时序坑** | `make deploy` 同一批对象里含 CRD 和你预填的 CR → CRD 还没到 Established，CR 落地 404/timeout。根治：先 `make install`（只 CRD）→ 等 `kubectl wait --for=condition=Established crd/...` → 再 deploy；GitOps 场景 sync-wave：CRD 波次 < webhook/CR 波次 |
| 3 | **`make run` 跑起来没反应** | controller 起来了但「不调谐」：① 忘 `make install`（CRD 不在）；② kubeconfig context 指错集群（你 watch 的是另一个集群）；③ controller 报 `GetConfigOrDie` / in-cluster config 错误——本地跑依赖 kubeconfig，别在容器里跑 make run（`ctrl.GetConfigOrDie()` 的顺序是 kubeconfig → in-cluster） |
| 4 | **leader-election Role 忘绑** | in-cluster 部署开 `--leader-elect=true` 后 manager 403：`cannot get lease ...`。根治：scaffold 已生成 `config/rbac/leader_election_role(_binding).yaml`，确认 `config/default/kustomization.yaml` 里没被注释 |
| 5 | **webhook 默认拉 cert-manager** | `kubebuilder create webhook` 之后 `make deploy` 才依赖 cert-manager（证书 issuer/注入 caBundle 都是它的活）→ 学习篇本想轻跑却被挂满。经验谈：**学习篇干脆不跑 `create webhook` 这步**（脚手架 webhook 是独立命令，不点这步你的 API/控制器零 webhook 依赖；骨架 main.go 里 webhook server 没有 handler 也无碍，controller-runtime v0.25+ 还可 `--webhook-port=-1` 整个关掉），reconcile 跑通后再回头加 |
| 6 | **kind 拉不到 kindest/node 镜像** | 公司网络/镜像墙；用 `--image` 指定内部 mirror，或 `docker pull` 后 `kind create cluster --wait` 重试，可先 `docker images` 确认 |
| 7 | **改完 types.go 忘 make generate/manifests** | CRD 没更新 → 新字段被 pruning 掉，「写了却不生效」。把 `make generate manifests` 设成编辑器的 save hook 是常见解法 |

### 4.5 什么时候不用 kubebuilder

裸 controller-runtime（或者甚至裸 client-go）写出来的 Operator 完全可以摆脱 kubebuilder：kubebuilder 的价值在**脚手架 + 发版流水线默认值**（Makefile、Dockerfile、CI、lint、golangci-logcheck）。团队已有 Go monorepo / 自研 CI 的，往往选择「照抄骨架文件、弃 CLI」；个人学习与快速出活、中小团队，直接全家桶。Operator SDK = RedHat 在 kubebuilder 之上再封装（多了 helm/ansible operator 与 OLM 打包）——同一套 controller-runtime 底，一句决策：想要 Helm/Ansible operator 或 OLM 生态才上 SDK，否则 kubebuilder 直达。

---

## 五、实战：WebApp Operator（全部代码本机实测）

本章交付一个最小但五脏俱全的 Operator：**一个 WebApp CR → 自动建一个 Deployment + 一个 Service，回写 conditions/URL，删除时 finalizer 清场**。设计取舍：Ingress 故意不纳入（拉 ingress controller 会带偏焦点）；Deployment+Service 已经是「应用型 Operator」的最小内核。

> ✅ **验证环境**：go1.26.0（GOTOOLCHAIN 自动切换）+ **controller-runtime v0.25.2**（k8s.io/* v0.37.0）+ **controller-gen v0.22.0** + **kind v0.33.0（kindest/node v1.37.0）**。三段验证实测通过：`go vet` + `go build` ✅；fake client `go test` ✅；**kind 真实集群 e2e ✅**（CR 创建→子对象自动出现→condition 翻转→漂移纠偏→删除级联，输出节选见 §9.2）。源码：`module example.com/webapp-operator`，`go 1.26.0`。

### 5.1 types.go：字段设计与 markers

```go
// api/v1alpha1/webapp_types.go
package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// WebAppSpec：用户填的期望状态——三个字段各自演示一种校验/默认值写法。
type WebAppSpec struct {
	// 容器镜像（必填，非空——MinLength 是最常被忘写的校验）
	// +kubebuilder:validation:MinLength=1
	Image string `json:"image"`

	// 副本数（可选；指针 + 默认值是「让服务端知道用户没填」的经典姿势）
	// +kubebuilder:validation:Minimum=0
	// +kubebuilder:validation:Maximum=50
	// +kubebuilder:default=1
	// +optional
	Replicas *int32 `json:"replicas,omitempty"`

	// 对外端口
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	// +kubebuilder:default=80
	// +optional
	Port int32 `json:"port,omitempty"`

	// 可选域名；写了就反映到 status.url（低阶校验用 Pattern）
	// +kubebuilder:validation:Pattern=`^(\*\.)?[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$`
	// +optional
	Hostname string `json:"hostname,omitempty"`
}

// WebAppStatus：控制器回写的观测状态。
type WebAppStatus struct {
	// 最后一次调和时看到的 generation：客户端靠它判断 status 是否已追上 spec
	// +optional
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`

	// 就绪副本（直接抄 Deployment 的 status）
	// +optional
	AvailableReplicas int32 `json:"availableReplicas,omitempty"`

	// 对外地址
	// +optional
	URL string `json:"url,omitempty"`

	// 标准条件集：Available / Degraded …
	// +listType=map
	// +listMapKey=type
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:resource:shortName=wa,categories={ops}
// +kubebuilder:printcolumn:name="READY",type=integer,JSONPath=`.status.availableReplicas`
// +kubebuilder:printcolumn:name="URL",type=string,JSONPath=`.status.url`
// +kubebuilder:printcolumn:name="AVAILABLE",type=string,JSONPath=`.status.conditions[?(@.type=="Available")].status`
// +kubebuilder:printcolumn:name="AGE",type=date,JSONPath=`.metadata.creationTimestamp`

// WebApp is the Schema for the webapps API.
type WebApp struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   WebAppSpec   `json:"spec,omitempty"`
	Status WebAppStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// WebAppList contains a list of WebApp.
type WebAppList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []WebApp `json:"items"`
}
```

配套 `groupversion_info.go`（注册进 Scheme；v0.24 之后的新形态，不再用 deprecated 的 scheme.Builder）：

```go
// api/v1alpha1/groupversion_info.go
// Package v1alpha1 contains API Schema definitions for the apps v1alpha1 API group.
// +kubebuilder:object:generate=true
// +groupName=apps.ops.example.com          ← 功能 marker：controller-gen 靠它定 CRD group，漏了会生成错组
package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

// GroupVersion：apps.ops.example.com/v1alpha1——GVK 的 G/V 部分就注册在这里。
var GroupVersion = schema.GroupVersion{Group: "apps.ops.example.com", Version: "v1alpha1"}

// SchemeBuilder 收集本包的类型注册函数；AddToScheme 是「一键注册进 manager scheme」的入口。
var (
	SchemeBuilder = runtime.NewSchemeBuilder(addKnownTypes)
	AddToScheme   = SchemeBuilder.AddToScheme
)

func addKnownTypes(scheme *runtime.Scheme) error {
	scheme.AddKnownTypes(GroupVersion, &WebApp{}, &WebAppList{})
	metav1.AddToGroupVersion(scheme, GroupVersion)
	return nil
}
```

`make generate` 产物 `zz_generated.deepcopy.go`（controller-gen 生成，勿手改；教学上它是对每个字段做深拷贝 + `DeepCopyObject()` 实现 `runtime.Object` 接口）。

### 5.2 Reconcile 完整代码（245 行，本机 `go vet`/`go build`/`go test`/kind e2e 全过）

```go
// internal/controller/webapp_controller.go
// Package controller 实现 WebApp 的调和循环：确保 Deployment / Service 对齐 spec，回写 status。
package controller

import (
	"context"
	"fmt"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/intstr"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"

	appsv1alpha1 "example.com/webapp-operator/api/v1alpha1"
)

// finalizer 命名纪律：限定域名 + 斜杠 + 名字（写进 metadata.finalizers）。
const webappFinalizer = "apps.ops.example.com/webapp-finalizer"

// 条件的 Reason 命名纪律：PascalCase、能进监控告警的稳定枚举值，不许把错误原文塞进去。
const (
	reasonReconciling = "Reconciling"
	reasonAvailable   = "Available"
	reasonError       = "ReconcileError"
)

// WebAppReconciler reconciles a WebApp object.
type WebAppReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// 以下 RBAC markers 由 controller-gen 扫描生成 config/rbac/role.yaml——只声明真正用到的动词。
// +kubebuilder:rbac:groups=apps.ops.example.com,resources=webapps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=apps.ops.example.com,resources=webapps/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=apps.ops.example.com,resources=webapps/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=core,resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile：把集群实际状态拉向 spec；幂等——同样的输入跑 N 次与跑 1 次结果一致。
func (r *WebAppReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := logf.FromContext(ctx)

	// ① 取 CR。NotFound 不是错误：对象已被删（本对象没有 finalizer 来拦），正常结束。
	webApp := &appsv1alpha1.WebApp{}
	if err := r.Get(ctx, req.NamespacedName, webApp); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// ② 删除路径：deletionTimestamp 非零 = 对象正在 Terminating，spec 已冻结。
	if !webApp.DeletionTimestamp.IsZero() {
		// 真实 operator 在这里清理外部世界（LB、DNS、云资源）；本例全靠
		// ownerReference 级联（Deployment/Service 由 GC 回收），直接摘除。
		if controllerutil.ContainsFinalizer(webApp, webappFinalizer) {
			controllerutil.RemoveFinalizer(webApp, webappFinalizer)
			if err := r.Update(ctx, webApp); err != nil {
				return ctrl.Result{}, err
			}
		}
		return ctrl.Result{}, nil
	}

	// ③ 正常路径：先保证 finalizer 在场（第一次调和时补挂）。
	//    就地 Update 后继续本轮——用新 resourceVersion 接着干，不浪费一轮调谐。
	if !controllerutil.ContainsFinalizer(webApp, webappFinalizer) {
		controllerutil.AddFinalizer(webApp, webappFinalizer)
		if err := r.Update(ctx, webApp); err != nil {
			return ctrl.Result{}, err
		}
	}

	// ④ ensure Deployment：adopt-or-create + 漂移回正（幂等核心）。
	dep := &appsv1.Deployment{}
	err := r.Get(ctx, types.NamespacedName{Name: webApp.Name, Namespace: webApp.Namespace}, dep)
	switch {
	case apierrors.IsNotFound(err):
		dep = r.deploymentForWebApp(webApp)
		if err := r.Create(ctx, dep); err != nil {
			return ctrl.Result{}, r.failStatus(ctx, webApp, fmt.Errorf("create Deployment: %w", err))
		}
		log.Info("created Deployment", "name", dep.Name)
	case err != nil:
		return ctrl.Result{}, err
	default:
		if d := desiredDeploymentSpec(webApp); deploymentDrifted(dep, d) {
			// 只回写「本 operator 声明管理」的字段——不要把整个 Template 换成
			// 局部构造的对象：那会把 labels/资源限额/别人注入的 sidecar 一并冲掉
			// （真集群里 template.labels 为 null 直接非法，apiserver 当场拒）。
			dep.Spec.Replicas = d.Spec.Replicas
			c := &dep.Spec.Template.Spec.Containers[0]
			c.Image = d.Spec.Template.Spec.Containers[0].Image
			c.Ports = d.Spec.Template.Spec.Containers[0].Ports
			if err := r.Update(ctx, dep); err != nil {
				return ctrl.Result{}, err
			}
			log.Info("reconciled Deployment drift", "name", dep.Name)
		}
	}

	// ⑤ ensure Service（同一套 adopt-or-create）。
	svc := &corev1.Service{}
	err = r.Get(ctx, types.NamespacedName{Name: webApp.Name, Namespace: webApp.Namespace}, svc)
	switch {
	case apierrors.IsNotFound(err):
		svc = r.serviceForWebApp(webApp)
		if err := r.Create(ctx, svc); err != nil {
			return ctrl.Result{}, r.failStatus(ctx, webApp, fmt.Errorf("create Service: %w", err))
		}
		log.Info("created Service", "name", svc.Name)
	case err != nil:
		return ctrl.Result{}, err
	}

	// ⑥ 回写 status：从 Deployment 抄观测值；只写 status 子资源，不碰 spec。
	webApp.Status.ObservedGeneration = webApp.Generation
	webApp.Status.AvailableReplicas = dep.Status.AvailableReplicas
	if webApp.Spec.Hostname != "" {
		webApp.Status.URL = "http://" + webApp.Spec.Hostname
	} else {
		webApp.Status.URL = ""
	}
	if dep.Status.AvailableReplicas >= deployReplicas(webApp) {
		meta.SetStatusCondition(&webApp.Status.Conditions, metav1.Condition{
			Type: "Available", Status: metav1.ConditionTrue, Reason: reasonAvailable,
			Message:            "Deployment is available",
			ObservedGeneration: webApp.Generation,
		})
	} else {
		meta.SetStatusCondition(&webApp.Status.Conditions, metav1.Condition{
			Type: "Available", Status: metav1.ConditionFalse, Reason: reasonReconciling,
			Message:            fmt.Sprintf("waiting for pods: %d/%d ready", dep.Status.AvailableReplicas, deployReplicas(webApp)),
			ObservedGeneration: webApp.Generation,
		})
	}
	if err := r.Status().Update(ctx, webApp); err != nil {
		return ctrl.Result{}, err // 409 冲突也走统一回错：workqueue 限速重试
	}
	return ctrl.Result{}, nil
}

// failStatus：先把失败落成 Degraded 条件，再把错误还给 workqueue 退避重试。
func (r *WebAppReconciler) failStatus(ctx context.Context, webApp *appsv1alpha1.WebApp, cause error) error {
	meta.SetStatusCondition(&webApp.Status.Conditions, metav1.Condition{
		Type: "Available", Status: metav1.ConditionFalse, Reason: reasonError,
		Message:            cause.Error()[:min(len(cause.Error()), 256)],
		ObservedGeneration: webApp.Generation,
	})
	_ = r.Status().Update(ctx, webApp) // 尽力而为，主错误优先
	return cause
}

// deploymentForWebApp：从 CR 构造期望的 Deployment，并设 controller 级 ownerReference——
// 「建链」三收益：级联删除、Owns() 事件回链、别的控制器不敢碰。
func (r *WebAppReconciler) deploymentForWebApp(webApp *appsv1alpha1.WebApp) *appsv1.Deployment {
	labels := map[string]string{"app.kubernetes.io/instance": webApp.Name, "app.kubernetes.io/managed-by": "webapp-operator"}
	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: webApp.Name, Namespace: webApp.Namespace, Labels: labels},
		Spec: appsv1.DeploymentSpec{
			Replicas: new(deployReplicas(webApp)),
			Selector: &metav1.LabelSelector{MatchLabels: labels},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{{
						Name:  "webapp",
						Image: webApp.Spec.Image,
						Ports: []corev1.ContainerPort{{ContainerPort: webApp.Spec.Port}},
					}},
				},
			},
		},
	}
	_ = controllerutil.SetControllerReference(webApp, dep, r.Scheme) // 同 ns 同 owner 必然成功；err 只在校验失败时出现
	return dep
}

func (r *WebAppReconciler) serviceForWebApp(webApp *appsv1alpha1.WebApp) *corev1.Service {
	labels := map[string]string{"app.kubernetes.io/instance": webApp.Name, "app.kubernetes.io/managed-by": "webapp-operator"}
	svc := &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{Name: webApp.Name, Namespace: webApp.Namespace, Labels: labels},
		Spec: corev1.ServiceSpec{
			Selector: labels,
			Ports: []corev1.ServicePort{{
				Port:       webApp.Spec.Port,
				TargetPort: intstr.FromInt32(webApp.Spec.Port),
			}},
		},
	}
	_ = controllerutil.SetControllerReference(webApp, svc, r.Scheme)
	return svc
}

// desiredDeploymentSpec：漂移对比的基准（只比「我们管」的字段）。
func desiredDeploymentSpec(webApp *appsv1alpha1.WebApp) *appsv1.Deployment {
	return &appsv1.Deployment{
		Spec: appsv1.DeploymentSpec{
			Replicas: new(deployReplicas(webApp)),
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{Containers: []corev1.Container{{
					Name: "webapp", Image: webApp.Spec.Image,
					Ports: []corev1.ContainerPort{{ContainerPort: webApp.Spec.Port}},
				}}},
			},
		},
	}
}

// deploymentDrifted：只比较本篇声明管理的字段——resourceVersion/label/status 一律不看。
func deploymentDrifted(current, desired *appsv1.Deployment) bool {
	if current.Spec.Replicas == nil || *current.Spec.Replicas != *desired.Spec.Replicas {
		return true
	}
	c := current.Spec.Template.Spec.Containers
	if len(c) != 1 || c[0].Image != desired.Spec.Template.Spec.Containers[0].Image {
		return true
	}
	return len(c[0].Ports) != 1 || c[0].Ports[0].ContainerPort != desired.Spec.Template.Spec.Containers[0].Ports[0].ContainerPort
}

// deployReplicas：指针字段 + 服务端默认值的双保险（直连/测试路径可能没经过 defaulting）。
func deployReplicas(webApp *appsv1alpha1.WebApp) int32 {
	if webApp.Spec.Replicas == nil {
		return 1
	}
	return *webApp.Spec.Replicas
}

// SetupWithManager：声明 watch 拓扑——「谁的变化应该唤醒我」。
func (r *WebAppReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&appsv1alpha1.WebApp{}, builder.WithPredicates(predicate.GenerationChangedPredicate{})). // spec 变了才调和；自己回写 status 不触发自己
		Owns(&appsv1.Deployment{}).                                                                  // 子对象任何变化（含 status）都回链 owner
		Owns(&corev1.Service{}).
		Named("webapp").
		Complete(r)
}
```

代码里的四个「不可省略的仪式」：

1. **RBAC markers 五条**：主对象全动词 + `webapps/status` 写 + `webapps/finalizers` update + 每个受管子资源（deployments/services）全动词。少一行 = 403 + 卡死。
2. **`client.IgnoreNotFound`**：竞态的最后一道保险——对象在「事件入队」和「你开始 Get」之间被删掉是常态（尤其不开 finalizer 时），NotFound 不是错误，是正常终点。
3. **漂移只回写管理的字段**：注释里那场 bug 在实验 6.2 被真集群拒过一次——第一版全量替换 Template 把 labels 置 null，apiserver 报 `selector does not match template labels`。这是 §3.7 反模式 5 的原型。
4. **`new(expr)`**：Go 1.26 语法（v4.15+ 骨架同样姿势；v0.24 起官方用 `new(x)` 替代 `ptr.To(x)`）。go.mod `go directive < 1.26` 的老项目继续用 `k8s.io/utils/ptr`。

### 5.3 接线：`cmd/main.go`（与 §2.1 一张图对应的装配）

```go
// cmd/main.go
// main：Manager 装配——scheme、Cache/Client、健康探针、选主，全部在这里接线。
package main

import (
	"flag"
	"os"

	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	appsv1alpha1 "example.com/webapp-operator/api/v1alpha1"
	"example.com/webapp-operator/internal/controller"
)

var (
	scheme   = runtime.NewScheme()
	setupLog = ctrl.Log.WithName("setup")
)

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme)) // 内建类型（Deployment/Service/...）
	utilruntime.Must(appsv1alpha1.AddToScheme(scheme))   // 我们的 CR——不注册，client 遇到它就报 "no kind is registered"
}

func main() {
	opts := zap.Options{Development: true}
	opts.BindFlags(flag.CommandLine) // -zap-devel=true 起步必备
	flag.Parse()
	ctrl.SetLogger(zap.New(zap.UseFlagOptions(&opts)))

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme:                 scheme,
		Metrics:                metricsserver.Options{BindAddress: ":8080"},
		HealthProbeBindAddress: ":8081",
		LeaderElection:         false, // 学习期默认关；上生产 +leader-elect=true + 多副本
		LeaderElectionID:       "webapp.ops.example.com",
	})
	if err != nil {
		setupLog.Error(err, "unable to start manager")
		os.Exit(1)
	}

	if err := (&controller.WebAppReconciler{
		Client: mgr.GetClient(),
		Scheme: mgr.GetScheme(),
	}).SetupWithManager(mgr); err != nil {
		setupLog.Error(err, "unable to create controller", "controller", "WebApp")
		os.Exit(1)
	}

	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		setupLog.Error(err, "unable to set up ready check")
		os.Exit(1)
	}

	setupLog.Info("starting manager")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		setupLog.Error(err, "problem running manager")
		os.Exit(1)
	}
}
```

对照 kubebuilder v4.16 骨架的差异说两句：骨架版更完整（metrics 走 :8443 HTTPS + `filters.WithAuthenticationAndAuthorization`、webhook server、TLS 选项、`LeaderElectionReleaseOnCancel` 开关注释），本例留下最小可讲版本；两者接线方式完全同构，实验 6.1 会把骨架版跑一遍。

### 5.4 生成的 CRD 与 RBAC（controller-gen v0.22.0 实产生物节选）

```yaml
# config/crd/bases/apps.ops.example.com_webapps.yaml（163 行，节选标记落地处）
metadata:
  annotations:
    controller-gen.kubebuilder.io/version: v0.22.0   # ← 版本金印，升级时对照发行注记
spec:
  names: { kind: WebApp, plural: webapps, singular: webapp, shortNames: [wa], categories: [ops] }
  versions:
  - additionalPrinterColumns:    # 四列全部落地（READY/URL/AVAILABLE/AGE）
    - { jsonPath: .status.availableReplicas, name: READY, type: integer }
    - { jsonPath: .status.url, name: URL, type: string }
    ...
    subresources: { status: {} } # ← status 子资源
    # replicas 的 { default: 1, minimum: 0, maximum: 50 }、image 的 minLength、hostname 的 pattern 全部进 schema
```

RBAC 生成物 `config/rbac/role.yaml`：五行 markers → ClusterRole 一群五条 rules。**变化检测**：markers 改动后跑 `make manifests`，git diff 一眼可见——这是 markers 胜于手写 RBAC 的原因。

---

## 六、测试与调试

Operator 的测试金字塔：**fake client 单测（快、逻辑）→ envtest（真 apiserver，验证同集群互动）→ kind e2e（全链）**。前两层进 CI，第三层进流水线晚间档。

### 6.1 fake client 单测（本机实测通过）

`pkg/client/fake` 用 in-memory store 模拟一个 `client.Client`——**快速覆盖「我的业务逻辑」，不验证 apiserver 行为**（不过准入、不过 schema 校验、没有 GC、没有 webhook）。

```go
// internal/controller/webapp_controller_test.go（节选，本机 go test 已实测）
func TestReconcileCreatesChildren(t *testing.T) {
	scheme := runtime.NewScheme()
	_ = clientgoscheme.AddToScheme(scheme)
	_ = appsv1alpha1.AddToScheme(scheme)

	replicas := int32(3)
	webApp := &appsv1alpha1.WebApp{
		ObjectMeta: metav1.ObjectMeta{Name: "demo", Namespace: "default"},
		Spec:       appsv1alpha1.WebAppSpec{Image: "nginx:1.27", Replicas: &replicas, Hostname: "app.example.com"},
	}
	// WithStatusSubresource：不开它，Status().Update 会静默丢 status（fake client 的经典坑）
	cl := fake.NewClientBuilder().
		WithScheme(scheme).
		WithObjects(webApp).
		WithStatusSubresource(&appsv1alpha1.WebApp{}).
		Build()

	r := &WebAppReconciler{Client: cl, Scheme: scheme}
	req := ctrl.Request{NamespacedName: types.NamespacedName{Name: "demo", Namespace: "default"}}
	for i := 0; i < 5; i++ { // finalizer → 建 Deployment → 建 Service → 落定 status
		if _, err := r.Reconcile(context.Background(), req); err != nil {
			t.Fatalf("reconcile round %d: %v", i, err)
		}
	}

	dep := &appsv1.Deployment{}
	_ = cl.Get(context.Background(), types.NamespacedName{Name: "demo", Namespace: "default"}, dep)
	owner := metav1.GetControllerOf(dep) // ownerReference 可断言：Kind=WebApp/Name=demo
	_, _ = owner, dep
}
```

第二个用例值得背（finalizer 删除路径）——fake client 可以**预置 Terminating 对象**（`DeletionTimestamp: &now` + 挂着 finalizer），而且**忠实模拟**「摘完最后一把 finalizer 且 deletionTimestamp 已置位 → 对象直接从存储消失」：断言对象 IsNotFound 即为过（v0.25.2 实测）。**边界一句**：GC 级联、准入控制、PSA、quota、webhook 全都不参与——这些正是 envtest/e2e 的层级。

### 6.2 envtest：起一个真的 apiserver + etcd（本机实测通过）

envtest 是 controller-runtime 的「便携式控制面」：本地下载 `kube-apiserver` + `etcd` 二进制（**无 kubelet/scheduler/kcm**），起进程给你的测试连——多版本矩阵、准入链、CRD 的 defaulting/校验全部真实。

```bash
# 安装（分支对齐 controller-runtime 大版本；v0.25 用 release-0.25）
go install sigs.k8s.io/controller-runtime/tools/setup-envtest@release-0.25

# 下载与集群对齐的资产（本机实测 1.37.0 资产落 ~/Library/Application Support/io.kubebuilder.envtest/）
setup-envtest use 1.37.x!                     # 下载并打印路径
source <(setup-envtest use -i -p env 1.37.x)  # 写入 KUBEBUILDER_ASSETS 环境变量
# kubebuilder v4.15+ 的脚手架会 pin ENVTEST 版本并在 make test 里自动 setup-envtest（use -p path）
```

测试骨架（与 kubebuilder 骨架 `suite_test.go` 同形，**没装资产时自动 Skip，不拖垮普通 `go test`**）：

```go
// internal/controller/webapp_envtest_test.go（节选，本机 go test 已实测，8s 起控制面）
func TestEnvtestEndToEnd(t *testing.T) {
	if os.Getenv("KUBEBUILDER_ASSETS") == "" {
		t.Skip("KUBEBUILDER_ASSETS 未设置：先跑 setup-envtest use 1.37.x! 再重试")
	}
	testEnv := &envtest.Environment{
		// 真集群里 CRD 来自 make install；测试直接喂 make manifests 产物目录
		CRDDirectoryPaths: []string{filepath.Join("..", "..", "config", "crd", "bases")},
	}
	cfg, err := testEnv.Start() // 随机端口 apiserver+etcd，全程本进程
	if err != nil { t.Fatalf("start envtest: %v", err) }
	defer func() { _ = testEnv.Stop() }()

	s := runtime.NewScheme()
	_ = clientgoscheme.AddToScheme(s); _ = appsv1alpha1.AddToScheme(s)
	k8sClient, _ := client.New(cfg, client.Options{Scheme: s})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	mgr, _ := ctrl.NewManager(cfg, ctrl.Options{Scheme: s})
	_ = (&WebAppReconciler{Client: mgr.GetClient(), Scheme: mgr.GetScheme()}).SetupWithManager(mgr)
	go func() { _ = mgr.Start(ctx) }()

	_ = k8sClient.Create(ctx, newDemoWebApp("demo-env"))
	// deadline 轮询：Deployment 应出现且 status 应回写（envtest 无 Deployment 控制器，
	// 所以副本不滚动——验证的是「对象链 + status」而非「真跑起来」）
	_ = mgr
}
```

**它验证什么/不验证什么**：CRD 的 schema/defaulting/CEL（✓）、你的 controller 与真 apiserver 的读写往返与 RBAC（✓）；Pod 调度/容器运行（✗，没有 kubelet）、webhook 通不通（✓ 可测但需启 etcd 注入证书）、云资源（✗）。这一层能抓住 80% 的「fake client 测不出」的坑——尤其是 markers 写错（CRD 建不出来即刻报错）。

### 6.3 本地调试节奏（make run 的正确打开方式）

```bash
# ① 开发档日志（scaffold 的 zap Options.Development=true；生产关掉）
go run ./cmd -zap-devel=true

# ② head-of-herd：盯着 reconciler 流（-zap-devel 下每轮 Reconciling/Error 都可见）
tail -f controller.log | grep -E 'Reconcil|drift|created'

# ③ delve 断点（挂在 make run 等价的进程上）
dlv debug ./cmd -- -zap-devel=true
# (dlv) b internal/controller.(*WebAppReconciler).Reconcile

# ④ 定向观察集群侧（另终端）：
kubectl get events -A --watch
kubectl get webapps -w
```

调试时的三问：事件来没来（watch/predicate 问题）→ 进了 Reconcile 没打日志（业务分支问题）→ 写了没生效（RBAC/409/字段被 pruning）。

---

## 七、生产着陆清单

上生产前逐条打勾，全部是前文的「纪律点」汇总：

| # | 项 | 标准 |
|---|----|------|
| 1 | 镜像 | 固定 digest 引用（`repo@sha256:`）+ 非 root + 只读根（第 5 章 §2 四件套）；`make docker-build docker-push IMG=仓库/webapp-operator:v0.1.0`，交付用 `make build-installer` |
| 2 | registry | 内网镜像仓库 + 拉取凭证（imagePullSecrets）；跨集群交付统一域名别依赖 latest |
| 3 | metrics | `:8443`（authn/authz 过滤）+ **ServiceMonitor**（`config/prometheus/monitor.yaml` scaffold 给好的）；告警三件套：`controller_runtime_reconcile_errors_total`、`workqueue_retries_total`、`controller_runtime_reconcile_time_seconds` P99 |
| 4 | leader election | **生产必开**（`--leader-elect=true` + 2 副本 + `LeaderElectionReleaseOnCancel: true`）；关闭单副本是「接受升级窗口脑停」的自觉选择，不是默认 |
| 5 | 资源请求 | requests/limits 都写：单 CR、少量 watch 的 operator `100m/256Mi` 起步足够；大集群注意 cache 内存**随 watch 对象数线性涨**（§2.2 ByObject 收窄是第一手段），上线后用 `:8443/metrics` + pprof 校准 |
| 6 | RBAC 最小化 | 动词逐个审议；ClusterRole 能收 Role 就收 Role（ns 级 operator）；leases 权限只给锁 ns |
| 7 | 升级策略 | **CRD 先行**（新 CRD 落下 → 等 Established → 再升 controller）；schema 变更必须向后兼容或有 conversion webhook 兜底（§1.3）；回退顺序倒着来 |
| 8 | POD 安全 | manager 容器套用第 5 章 §2 四件套起步（runAsNonRoot/seccomp RuntimeDefault/allowPrivilegeEscalation=false/drop ALL，近年 scaffold 的 `config/manager/manager.yaml` 已按此收敛；旧项目自查）；`automountServiceAccountToken` 保持 true（operator 本体必须访问 API），但在 SA 上只绑第 6 条的最小 RBAC |
| 9 | finalizer 运行手册一页 | oncall 见到「CR 卡 Terminating」时的标准动作：① 看 controller 日志查清理失败原因；② 修原因（云 IAM/配额/依赖粘连）；③ 实在修不了、**确认外部资源已手工处理后**才人工摘 finalizer（接受泄漏）（第 1 章 §4.3 有完整卡死处置表） |
| 10 | 回滚预案 | CRD 改动不可逆为主（加字段安全、删/改字段危险）——上线前把「旧版 controller 能否读写新版 CRD」当成 checklist 一项过 |

---

## 八、常见生产问题清单（Operator 视角）

| # | 症状 | 根因链 | 排查/处置 |
|---|------|--------|-----------|
| 8.1 | **reconcile 风暴**：`controller_runtime_reconcile_total` QPS 异常高、CPU 打满 | watch 拓扑太宽（For 了热资源）；predicate 没挂 GenerationChanged；自己写 status 又触发自己 | `kubectl get --raw /metrics \| grep reconcile`；排查序：先看是哪个 controller（指标 label）→ 看事件源（日志里 Reconciling 的 name 分布是否病态集中）→ 收 predicate/`cache.Options.ByObject`；`MaxConcurrentReconciles` 反而要往下调压峰值 |
| 8.2 | **cache 不同步错觉**：「刚改了 CR，controller 行为像没看到」 | 读走 cache 读的是旧快照；或写完立即读自己写的字段 | 把后续动作放进下一轮（事件会回来）或 `mgr.GetAPIReader()` 强制直读；v0.25.0 实验特性 `Client.EnableReadYourWritesConsistency: new(true)` 专为此生，生产先别依赖 |
| 8.3 | **脑裂**：两个副本同时在工作、互相覆盖子对象 | 直接原因就是没开 `--leader-elect` 又跑了多副本（controller-runtime 拿不到锁会拒绝启动控制器组，不会「开跑」——所以真正的脑裂几乎全是忘开选主）；或 lease 过期面太大掩盖了节点级长断网 | `kubectl get lease -n <部署ns>`——应只有一个 `holderIdentity`；未开选主时副本数上限=1 |
| 8.4 | **finalizer 卡死**：CR 永远 Terminating（实验 6.2 step 8 真实复现过） | 清理逻辑失败 / 外部云资源卡 / **控制器进程没了** / RBAC 缺 `xxx/finalizers:update` | ① `kubectl get <crd> <x> -o jsonpath='{.metadata.finalizers}'` 看是哪把锁；② controller 日志找清理错误；③ 修复根因让清理跑通；④ 确实救不了才人工摘（运行手册 §7.9） |
| 8.5 | **RBAC 事件**：日志报 403 `cannot list resource "xxx" in API group` | markers 没加/生成后没重新 deploy role | `kubectl auth can-i --as system:serviceaccount:<ns>:<sa> <verb> <resource>` 快进定位；update markers → `make manifests deploy` |
| 8.6 | **SSA field manager 冲突**：apply 时报 `conflict with "<other-manager>" using <type>` | 两个控制器「认领」同一字段（经典：operator vs HPA 都管 `replicas`）；或你错误地用「读出来的全量对象」做 Apply（§2.6 纪律 ②——把别人的字段也「认领」了） | `kubectl get <obj> --show-managed-fields -o yaml` 看字段护照；三选一出路：字段放手让给高优先控制器 / 抽成注解或独立字段各管各的 / 用 `--force-conflicts` 宣示主权（慎重） |
| 8.7 | **Conversion webhook 把升级锁死**：升级 CRD 上 conversion webhook 挂了 → **全版本 CR 读写全瘫** | apiserver 每次读写都要调你的 webhook 做版本互转；webhook 挂了 = 整个 CRD 的可用性=webhook 可用性 | 上 conversion webhook = 你的控制器自此升级**顺序死锁**：先升 webhook 新代码（兼容新旧两版）→ 再升 CRD；webhook 服务的 PDB/多副本/HPA 都是硬要求；`failurePolicy` 这里没有 Ignore 的余地（协议层强依赖） |
| 8.8 | **worker 排队感**：某个 CR 10 分钟才轮到 | MaxConcurrentReconciles=1（默认） + 前面挤着一个长事务 | 日志看 `worker count`；指标 `workqueue_depth{controller=...}`；大集群调 4~32 |
| 8.9 | **401 expired kubeconfig**：本地 `make run` 长期挂机后 401 | 云端 kubeconfig token 过期（EKS ExecCredential 15 分钟等） | 重跑 `make run`；生产用 in-cluster SA 不存在此问题 |

---

## 九、实验（kind 沙箱 4 连）

> 环境：docker 运行中、`kubectl`、Go 1.26（GOTOOLCHAIN=auto 可由 1.24 自动切换）、`kind`、（可选）`kubebuilder`。
> 命中版本实测组合（2026-10-14 全走过）：**kind v0.33.0**（默认节点 `kindest/node:v1.37.0`，官方 digest `sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5`）、**controller-runtime v0.25.2**、**controller-gen v0.22.0**、**kubebuilder v4.16.0**。

### 实验 6.1 kubebuilder 从零到 make run（含踩坑表）

```bash
# step 1 集群（不写 --image 即 kind 默认 v1.37.0；官方建议按 digest 钉）
kind create cluster --name op-exp \
  --image kindest/node:v1.37.0@sha256:a1ed56cfb0e7b93589bdf97c8cd566405a265939e3620fc4f5de89adff580ae5

# step 2 脚手架（学习期不跑 create webhook——cert-manager 依赖会带来一波 pre-flight 噪音，§4.4 坑 5）
mkdir memcached && cd memcached
kubebuilder init --domain example.com
kubebuilder create api --group cache --version v1alpha1 --kind Memcached

# step 3 一行不写先全链跑通（骨架 Reconcile 已能终态返回）
make install
kubectl get crd memcacheds.cache.example.com -o jsonpath='{.status.conditions[?(@.type=="Established")].status}'
make run   # 另终端；能看到 Starting workers {"worker count": 1} —— §2.4 的默认值实锤

# step 4 建样例 CR、看状态、收链
kubectl apply -k config/samples/
kubectl get memcacheds.cache.example.com
make uninstall      # 卸 CRD（CR 会同步消失——CRD 删除即清空全部 CR）
make undeploy 2>/dev/null || true
```

踩坑表（按出现频率）：

| 坑 | 现象 | 解 |
|----|------|----|
| `make run` 报 `no kind is registered` | create api 后忘了同步 scheme / 用了陈旧 go build 缓存 | 骨架里 main.go 的 `cachev1alpha1.AddToScheme(scheme)` 在；`go clean -cache` |
| controller-gen 版本错位 | `make manifests` 语法错 | Makefile 钉 `CONTROLLER_TOOLS_VERSION:=v0.22.0`；团队统一 `go install sigs.k8s.io/controller-tools/cmd/controller-gen@v0.22.0`，**勿 @latest**（详见 §4.4 坑 1） |
| CR 落地但 controller 没反应 | context 指错集群 / 忘 install | `kubectl config current-context`；`make install` |
| 骨架 go.mod 要 go1.26 本机只有旧版 | go toolchain 自动切换失败（代理受限） | `GOTOOLCHAIN=auto` + GOPROXY 可达（`goproxy.cn,direct` 实测可行），或本机装 go1.26 |

### 实验 6.2 WebApp Operator 全链（本机真实输出节选）

按 §5 的代码创建一个 module（`go.mod`：`module example.com/webapp-operator` + `go 1.26.0` + `sigs.k8s.io/controller-runtime v0.25.2`）。

```bash
# step 1 装 CRD（§5.4 生成物）
kubectl apply -f config/crd/bases/apps.ops.example.com_webapps.yaml
kubectl api-resources --api-group=apps.ops.example.com
#  NAME      SHORTNAMES   APIVERSION                          NAMESPACED   KIND
#  webapps   wa           apps.ops.example.com/v1alpha1       true         WebApp

# step 2 本地 controller（等价 make run）
go run ./cmd -zap-devel=true   # 前台起步：Starting workers {"worker count": 1}

# step 3 建 CR → 子对象自动出现
cat <<'EOF' | kubectl apply -f -
apiVersion: apps.ops.example.com/v1alpha1
kind: WebApp
metadata: { name: hello }
spec: { image: nginx:1.27, replicas: 2, hostname: hello.ops.example.com }
EOF
kubectl get wa hello
#  NAME    READY   URL                            AVAILABLE   AGE
#  hello           http://hello.ops.example.com   False       7s
kubectl get deploy,svc -l app.kubernetes.io/instance=hello
#  → deployment.apps/hello (0/2 → 稍后 2/2) + service/hello (ClusterIP) 全部就绪

# step 4 condition 翻转（kubectl wait 直接可用！）
kubectl wait webapp hello --for=condition=Available --timeout=120s
kubectl get wa hello
#  NAME    READY   URL                            AVAILABLE   AGE
#  hello   2       http://hello.ops.example.com   True        36s

# step 5 漂移纠偏（人为扰乱 → 被回正）
kubectl scale deploy/hello --replicas=1
sleep 8 && kubectl get deploy hello -o jsonpath='{.spec.replicas}'   # → 2
#  controller 日志：reconciled Deployment drift

# step 6 服务端校验拦截（§1.2 CEL/schema；值超界/格式错当场拒）
kubectl apply -f - <<'EOF'
apiVersion: apps.ops.example.com/v1alpha1
kind: WebApp
metadata: { name: bad }
spec: { image: nginx:1.27, replicas: 99 }
EOF
#  The WebApp "bad" is invalid: spec.replicas: Invalid value: 99: ... should be less than or equal to 50

# step 7 删除清场（finalizer 摘除 + GC 级联）
kubectl delete webapp hello
kubectl get deploy,svc -l app.kubernetes.io/instance=hello
#  No resources found in default namespace.     ← ownerReference 全链清光

# step 8（反向课）控制器挂掉时的 Terminating 死锁：pkill 掉 step 2 进程后 kubectl delete webapp hello
#  → CR 卡在 deletionTimestamp + finalizer，Deployment 留着；
#  → 重启 controller 立即完成摘除+级联。这就是 §8.4 的运行手册活教材。
```

**踩坑实录（本章作者真实踩过）**：漂移纠偏第一版写的是「整个 `dep.Spec.Template` 换成局部构造对象」——真集群里 apiserver 当场拒：`spec.template.metadata.labels: Invalid value: null: selector does not match template labels`，错误日志被 fake client 埋掉（fake 不过这种校验）只能 kind 层现形。**这就是「只回写管理字段」纪律（§3.7 反模式 5）以及「fake→envtest→kind 三层，层层能抓住新病」（§6）的实锤论证**。

### 实验 6.3 printer columns 与 conditions 体验

```bash
# step 1 categories 批量拉取（§1.4）
kubectl get ops   # 一把拉出 categories=[ops] 的所有 WebApp

# step 2 -o wide 观察自定义列（本例列 priority 为 0，全量列默认已显示）
kubectl get webapps -o wide

# step 3 wait 的两种姿势（CI/GitOps 友好）
kubectl wait webapp hello --for=jsonpath='{.status.availableReplicas}'=2 --timeout=60s
kubectl wait webapp hello --for=condition=Available=True --timeout=60s

# step 4 新版 CR 上 CEL（§1.2，以下 YAML 即在 kind v1.37 实测过的原文）
cat <<'EOF' | kubectl apply -f -
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata: { name: celchecks.apps.ops.example.com }
spec:
  group: apps.ops.example.com
  scope: Namespaced
  names: { kind: CelCheck, plural: celchecks, singular: celcheck }
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
              minReplicas: { type: integer }
              replicas:    { type: integer }
              maxReplicas: { type: integer }
            x-kubernetes-validations:
            - rule: "self.minReplicas <= self.replicas"
              message: "replicas 不能小于 minReplicas"
            - rule: "self.replicas <= self.maxReplicas"
              message: "replicas 不能大于 maxReplicas"
EOF
cat <<'EOF' | kubectl apply -f - 2>&1 | head -3
apiVersion: apps.ops.example.com/v1
kind: CelCheck
metadata: { name: c1 }
spec: { minReplicas: 1, replicas: 5, maxReplicas: 3 }
EOF
#  The CelCheck "c1" is invalid: spec: Invalid value: replicas 不能大于 maxReplicas   ← 自定义中文 message 原样返回
kubectl delete crd celchecks.apps.ops.example.com
```

### 实验 6.4 envtest 单测跑通（可选进阶）

```bash
go install sigs.k8s.io/controller-runtime/tools/setup-envtest@release-0.25
setup-envtest use 1.37.x!
export KUBEBUILDER_ASSETS="$(setup-envtest use -i -p path 1.37.x)"
go test ./internal/controller/ -run TestEnvtestEndToEnd -v -count=1
#  === RUN   TestEnvtestEndToEnd
#  --- PASS: TestEnvtestEndToEnd (8.05s)        ← 本机真实输出：8 秒起 apiserver+etcd 全程
go test ./internal/controller/ -v -count=1     # 不含该环境变量时自动 Skip，不拖 CI
```

清理链：`kind delete cluster --name op-exp`；删 envtest 资产 `setup-envtest cleanup <1.37`。

---

## 十、速查表 + 背诵要点 + 参考链接

### 10.1 一页速查

| 主题 | 命令 / 字段 / API（写作时版本） |
|------|--------------------------------|
| 版本栈 | K8s v1.37 · controller-runtime **v0.25.2**（→k8s.io v1.37）· kubebuilder **v4.16.0**（controller-gen v0.22.0）· kind **v0.33.0**（node v1.37.0）· Go **1.26** |
| structural schema 四条 | 每节点非空 type；逻辑体字段外置；约束不进 allOf/anyOf/oneOf/not；metadata 只限 name/generateName；违规 → CRD `NonStructural` 条件 |
| CEL 校验 | `x-kubernetes-validations`：**v1.25 Beta → v1.29 GA**；超限拒写 `CEL rule exceeded budget by more than 100x`；遍历须同步写 maxItems/maxProperties/maxLength；`oldSelf` 过渡规则；`optionalOldSelf` 自定义回退 |
| ratcheting | `CRDValidationRatcheting`：v1.28 Alpha → v1.33 GA 默认开；量词/list-type/required/metadata 内建校验不回退；oldSelf 规则永不回退 |
| 转换 | 多版本 served 并存，**唯一 storage**；strategy `None`（默认）/`Webhook`；接口：`Hub()` 标记 + `Convertible{ConvertTo,ConvertFrom}`（`conversion.Hub`）；`kubebuilder create webhook --conversion --spoke v2` |
| subresources | `status: {}`（分离写/RBAC/不 bump generation）；`scale: { specReplicasPath, statusReplicasPath, labelSelectorPath }`（kubectl scale/HPA 可用） |
| kubectl 体验 | `additionalPrinterColumns`（JSONPath，priority>0 仅 wide）；`shortNames`；`categories`（`kubectl get ops`） |
| Builder 三件 | `For`（EnqueueRequestForObject）· `Owns`（EnqueueRequestForOwner，controllerOnly）· `Watches`（EnqueueRequestsFromMapFunc）；predicate 用 `builder.WithPredicates` 挂到具体 watch，忌 `WithEventFilter` 一把梭 |
| 返回值语义 | err→AddRateLimited；TerminalError→丢弃不重试；RequeueAfter→Forget+定时；`Requeue:true` **已 Deprecated（用 RequeueAfter）**；err 非 nil 时 Requeue/After 被忽略 |
| Cache/Client | **读走 cache 写直连**；`mgr.GetAPIReader()` 强一致；`cache.Options.ByObject` 收窄 watch；`EnableReadYourWritesConsistency` 实验 |
| 并发/限速 | `MaxConcurrentReconciles` 默认 1；默认限速器 = MaxOfRateLimiter（项退避 5ms→1000s + 全局 10qps/100）；priority queue v0.23 默认开，`Result.Priority` |
| leader election | 默认关；`--leader-elect` + `LeaderElectionID` + Leases RBAC；ReleaseOnCancel；standby 也跑 cache |
| 写入策略 | 独占对象→Update / MergeFrom Patch；共管大对象→SSA `client.Apply` + `FieldOwner` + 骨架对象；v0.23 起 status 子资源可 SSA |
| finalizer | 需要外部清理才挂；`deletionTimestamp != 0` 分支；RBAC `xxx/finalizers:update`；摘完即真删 |
| kubebuilder | `init --domain` → `create api` → `make generate manifests` → `make install` → `make run` → `make docker-build/push deploy` → `make uninstall/undeploy/build-installer` |
| 测试三层 | fake client（`WithStatusSubresource` 别忘）→ envtest（`setup-envtest use 1.37.x!` + `KUBEBUILDER_ASSETS`）→ kind e2e；每层能抓新病 |
| 关键指标 | `controller_runtime_reconcile_total/errors_total/time_seconds`、`workqueue_depth/retries_total`；指标名随版本微调，先 `kubectl get --raw /metrics \| grep ...` 按本版核对 |

### 10.2 关键要点（背诵版）

1. **Operator = CRD × Controller × 运维知识**；工具链只交付前两件，第三件靠你写进代码。
2. **structural schema 是三件套前提**：不真 structural 就没有 pruning/defaulting/CEL；CEL **v1.25 Beta → v1.29 GA**，写入 CRD 时就做成本静态估算，超限拒 CRD 本身。
3. **多版本只有一个 storage**；结构变了上 conversion webhook；上了它可用性 = webhook 可用性，升级顺序锁死（先新代码后新 CRD）。
4. **controller-runtime 的核心言行**：读走 cache、写直连、Manager 宿舍、Builder 声明 watch 拓扑、Reconcile 只收 namespace/name。
5. **GenerationChangedPredicate 是主对象的默认安全网**；但要挂在 `For(..., builder.WithPredicates(...))` 上，`WithEventFilter` 会殃及 Owns。
6. **Reconcile 三铁律**：level-based 快照收敛、幂等（adopt-or-create）、小步提交；`Result.Requeue` 已弃用，用 `RequeueAfter`；`TerminalError` 用来标记「别救我」。
7. **`SetControllerReference` 一行三收益**：级联删除、Owns 回链、排他 ownership；status 由 `Status().Update` 写子资源，condition 遵循 `ObservedGeneration` 纪律。
8. **RBAC markers 五条是启动条件**：主对象、status、finalizers，受管子资源全动词；少一条 = 403 或卡死。
9. **测试三层各抓一类病**：fake 抓逻辑、envtest 抓 markers/RBAC/往返、kind 抓「真的能在集群里活」。本章漂移 bug 就是 fake 全绿而 kind 拒写的铁证。
10. **生产四件套**：leader election 开、metrics ServiceMonitor 起、RBAC 最小、CRD 先行的升级链——外加一页「finalizer 卡死」运行手册。

### 10.3 参考链接

| 主题 | 链接 |
|------|------|
| CRD 官方页（structural schema/CEL/ratcheting/subresources/printer columns） | https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/ |
| CRD 版本化（served/storage/conversion） | https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definition-versioning/ |
| Kubebuilder Book（quick start / getting started / multiversion） | https://book.kubebuilder.io/ |
| controller-runtime releases（v0.25.2 = k8s 1.37；v0.24 = 1.36；v0.23 = 1.35） | https://github.com/kubernetes-sigs/controller-runtime/releases |
| controller-runtime 文档（manager/builder/predicates/cache 选项） | https://pkg.go.dev/sigs.k8s.io/controller-runtime@v0.25.2 |
| kubebuilder releases（v4.16.0） | https://github.com/kubernetes-sigs/kubebuilder/releases |
| setup-envtest README（分支安装/KUBEBUILDER_ASSETS/资产目录） | https://github.com/kubernetes-sigs/controller-runtime/tree/main/tools/setup-envtest |
| controller-tools / controller-gen（v0.22.0，markers 参考） | https://github.com/kubernetes-sigs/controller-tools |
| kind releases（v0.33.0 / v1.37.0 digest） | https://github.com/kubernetes-sigs/kind/releases |
| Operator pattern（官方概念） | https://kubernetes.io/docs/concepts/extend-kubernetes/operator/ |
| Operator SDK vs kubebuilder | https://sdk.operatorframework.io/docs/overview/operator-sdk-full-workflow/ |
| API Conventions（status conditions / reason 纪律） | https://github.com/kubernetes/community/blob/master/contributors/devel/sig-architecture/api-conventions.md#typical-status-properties |

---

> 全章 Go（types.go / controller.go / main.go / 两个测试文件）已在 **go1.26.0 + controller-runtime v0.25.2 + k8s v1.37** 上完成 `go vet` / `go build` / `go test`（fake client 与 envtest 双绿），并在 **kind v0.33.0（v1.37.0）** 集群完成 e2e：CR→子对象→condition 翻转→漂移纠偏→删除级联。下一章（总纲第 7 章）推进生产集群运维。
