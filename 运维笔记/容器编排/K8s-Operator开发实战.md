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
- **oldSelf 过渡规则**：`self.replicas >= oldSelf.replicas`（只升不降）、`self.foo == oldSelf.foo`（不可变）这类引用 `oldSelf` 的规则**只在 update 时评估**，create 时跳过；`optionalOldSelf: true`（v1.33 起 Stable）允许「旧值缺失也算过」的自定义回退逻辑。
- **校验回退（ratcheting）**：CRD 的校验变严后，**不动该字段的存量对象不能被「顺手拒之门外」**——`CRDValidationRatcheting`（v1.28 Alpha → v1.30 Beta → **v1.33 GA 默认开**）：更新时若该字段值未变，则该字段上的新校验被跳过。例外（v1.37 实现，官方列明）：`allOf/anyOf/oneOf/not` 量词、list type 变更、`required` 变化、metadata 内建校验**不参与回退**；含 `oldSelf` 的过渡规则永不回退。
- **Condition 上的 CEL**：apiserver 对每条 rule 有运行时中断（解释器步数超限会 halt 并报错）。

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
// Requeue == true       → AddRateLimited（退避重试；【已 Deprecated】官方说「用 RequeueAfter
//                         表达等待外部事件，不要借用错误重试的退避节
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
| **Patch（client patch）** | `r.Patch(ctx, obj, client.MergeFrom(orig))` | 三种 patch type：strategic（内建类型，按 patchStrategy 并表）、merge（JSON Merge Patch）、JSONPatch | 与别人**共管**的大对象，只不想碰的字段不覆盖；`MergeFrom` 自动算差分，最常用 |
| **Server-side Apply（SSA）** | `r.Patch(ctx, obj, client.Apply, client.FieldOwner("webapp-operator"))` | apiserver 按 **field manager** 逐字段仲裁所有权，冲突返回 409 + 字段清单 | 共管对象 + 想显式声明「我拥有哪几个字段」；**v0.23 起 `Status().Patch(..., client.Apply)` 也支持 status 子资源**（v0.23.0 release「Client: Add subresource Apply support」） |

三条纪律：① 别用 Update 去全量覆盖「别人也会改」的对象（manual scale 的 Deployment、HPA 染指的 replicas——那是 §8.6 field manager 冲突的温床）；② SSA 的 apply 对象必须是**只含你拥有的字段的「骨架对象」**，把 Get 出来的对象改两笔就 Apply 是反模式（你没有的字段会被你「认领」）；③ 409 冲突不需要代码里特判——**统一交回给 workqueue 退避重试**，下一轮拿到新 RV 自然收敛。

**为什么这么设计**：Cache/Client 分离 + Builder 声明式 watch + 单一 Reconcile 签名，本质是把「控制器最难写对的三半」——事件拓扑、一致性窗口、重试节奏——全部标准化。你的 Go 代码只剩**读快照、算差分、写回**三件事。

---

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
- **写 status 也要竞争意识**：条件没变就 status 相同——`meta.SetStatusCondition` 只在变化时改 lastTransitionTime，重复 Update 是无谓写；第 1 章 §2 讲过每次写都要过准入链，风暴期的「无变化 status 写」是 apiserver 的隐形压力（生产上先比较再写：`if apiequality.Semantic.DeepEqual(old.Status, new.Status)` 跳过）。

### 3.5 finalizer 时机表（决策版；机制见第 1 章 §4.3）

| 决策点 | 答案 | 依据 |
|--------|------|------|
| 什么时候需要 finalizer？ | **只有「集群外还有以我为凭据的资源」时**（LB/DNS/云盘/第三方注册） | 纯 ns 内子对象靠 ownerReference + GC 就够，加 finalizer 是给自己添刽子手环节 |
| 什么时候挂？ | 首次 reconcile 见到对象就挂（先挂再干活） | 先干活后挂：删除时清理动作可能永远赶不上 |
| 什么时候摘？ | `DeletionTimestamp != 0` 分支里，清理**成功后**才摘 | 清理失败：把错误写进 condition，重试——**不能放弃式硬摘** |
| 摘除后会发生什么？ | finalizers 清空 → apiserver 真正从 etcd 删除（连对象都 Get 不到） | 摘完再 reconcile 是 404 路径，属于正常 |
| 需要什么权限？ | `resources=xxx/finalizers, verbs=update`（RBAC marker 单独一行，§5 代码③） | 少了它：更新 finalizers 403，对象卡 Terminating |
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
| 10 | 把 ✨任何✨ 日志/error 里塞 secret/token/整对象 YAML | 控制面日志聚合起來後变成秘密泄漏面（第 5 章 §5 的第三条通道）——只记 name/ns/关键字段 |

**为什么这么设计**：Reconcile 的正确性模型其实是「**高级语言的 declarative runtime**」——K8s 已有的所有控制器（Deployment→RS→Pod 链）都是同型：读快照、算差分、小步提交、限速重试。不按这个模型写，框架替你兜的每一层（cache、queue、predicate）都会反噬成奇葩故障。

---

---

## 四、kubebuilder 全流程

kubebuilder 是「controller-runtime 的项目脚手架 + 代码发生器管家」——它生成的不是「一套框架」，而是「一个普通 Go module**：你随时能脱离它继续写。本节版本均按 2026-10 上游核对：**kubebuilder v4.16.0**（内置 **controller-gen v0.22.0**，生成的 CRD 带 `controller-gen.kubebuilder.io/version: v0.22.0` 注解，与 §5 实产生物一致）。

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

`--domain` 决定 group 后缀（`apps.ops.example.com`）；不喜欢可随时改（生成物是普文本）。想有第二个 kind 就再跑一次 `create api`。`init` 之后可改用 `--plugins` 启用 helm/v2-alpha（出 Helm chart）等插件。

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
| 2 | **CRD 与 controller 分离部署的时序坑** | `make deploy` 同一批对象里含 CRD 和你预填的 CR → apiserver 还没 Established CR，CR 落地 404/timeout。根治：先 `make install`（只 CRD）→ 等 `kubectl wait --for=condition=Established crd/...` → 再 deploy；GitOps 场景 sync-wave：CRD 波次 < webhook/CR 波次 |
| 3 | **`make run` 跑起来没反应** | controller 起来了但「不调谐」：① 忘 `make install`（CRD 不在）；② kubeconfig context 指错集群；③ `make run` 在把自己当成集群内 Pod 读 in-cluster config 失败——本地跑务必走 kubeconfig（scaffold 的 `ctrl.GetConfigOrDie()` 自动优先 kubeconfig） |
| 4 | **leader-election Role 忘绑** | in-cluster 部署开 `--leader-elect=true` 后 manager 403：`cannot get lease ...`。根治：scaffold 已生成 `config/rbac/leader_election_role(_binding).yaml`，确认 `config/default/kustomization.yaml` 里没被注释 |
| 5 | **webhook 默认拉 cert-manager** | `kubebuilder create webhook` 后 `make deploy` 依赖 cert-manager 存在（证书 issuer/注入 caBundle 都是它的活）→ Learning 阶段本想轻跑却被挂满。建议：**学习篇先 `--webhooks=false` 不 create webhook**（骨架 main.go 里 webhook server 无 handler 也无碍；v0.25+ 还可 `--webhook-port=-1` 整个关掉），跑通 reconcile 后再加 |
| 6 | **kind 拉不到 kindest/node 镜像** | 公司网络/镜像墙；用 `--image` 指定内部 mirror，或 `docker pull` 后 `kind create cluster --wait` 重试，可先 `docker images` 确认 |
| 7 | **改完 types.go 忘 make generate/manifests** | CRD 没更新 → 新字段被 pruning 掉，「写了却不生效」。把 `make generate manifests` 设成编辑器的 save hook 是常见解法 |

### 4.5 什么时候不用 kubebuilder

裸 controller-runtime（或者甚至裸 client-go）写出来的 Operator 完全可以摆脱 kubebuilder：kubebuilder 的价值在**脚手架 + 发版流水线默认值**（Makefile、Dockerfile、CI、lint、golangci-logcheck）。团队已有 Go monorepo / 自研 CI 的，往往选择「照抄骨架文件、弃 CLI」；个人学习与快速出活、中小团队，直接全家桶。Operator SDK = RedHat 在 kubebuilder 之上再封装（多了 helm/ansible operator 与 OLM 打包）——同一套 controller-runtime 底，一句决策：想要 Helm/Ansible operator 或 OLM 生态才上 SDK，否则 kubebuilder 直达。

---

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
package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
)

var GroupVersion = schema.GroupVersion{Group: "apps.ops.example.com", Version: "v1alpha1"}

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
2. **`client.IgnoreNotFound`**：racestance 的最后一道保险（对象在你 Get 和 Delete 之间消失）。
3. **漂移只回写管理的字段**：注释里那场 bug 在实验 6.2 被真集群拒过一次——第一版全量替换 Template 把 labels 置 null，apiserver 报 `selector does not match template labels`。这是 §3.7 反模式 5 的原型。
4. **`new(expr)`**：Go 1.26 语法（v4.15+ 骨架同样姿势；v0.24 起官方用 `new(x)` 替代 `ptr.To(x)`）。go.mod `go directive < 1.26` 的老项目继续用 `k8s.io/utils/ptr`。

### 5.3 接线：`cmd/main.go`（与 §2.1 一张图对应的装配）

```go
// cmd/main.go
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

对照 kubebuilder v4.16 骨架的差异说两句：骨架版更完整（metrics 走 :8443 HTTPS + `filters.WithAuthenticationAndAuthorization`、webhook server、TLS 选项、`LeaderElectionReleaseOnCancel` 开关注释），本例留下最小可讲版本；骨架版两段大同小异，实验 6.1 会把它跑一遍。

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
