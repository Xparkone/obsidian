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

apiextensions.k8s.io/v1 强制要求 **structural schema**——apisterver 要能一眼从 schema 推出「这棵对象树上每个节点是什么类型」。官方定义四条规则，违规特征对照表：

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
