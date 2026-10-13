# K8s API 机制深入

> 精通路线第 1 章：对象模型、请求链路、list-watch、GC、APF、聚合层、Raw API、审计
> 创建时间：2026-10-13
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37），文中标注「v1.xx 起 Beta/GA」均取自官方文档，执行时仍以你本地集群版本为准

---

## 零、本文定位与边界

K8s 的一切控制循环，本质上都是同一句话：**某个 client 对 API 做 list-watch，把实际状态（status）拉向期望状态（spec）**。
kubelet、controller-manager、scheduler、ArgoCD、Istiod、你自己写的 Operator——没有例外。
所以 API 机制是理解一切控制器行为、一切性能瓶颈、一切诡异的 409/410/429 报错的地基。

```
你的所有问题，最终都会变成这几类：
  "谁改了我的对象？"        → RequestPath（认证/鉴权/准入/审计）   §2 §8
  "控制器为什么没反应？"     → list-watch / informer / 事件丢失      §3
  "删不掉 / 卡 Terminating？"→ ownerReference / finalizer / GC      §4
  "apiserver 又 429 了"      → APF / watch 风暴 / etcd 压力         §5 §9
  "kubectl top 不工作了"     → 聚合层 APIService 故障               §6
```

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `K8s-组件详解.md` | 组件是什么、端口、kubectl 命令大全 | 不再介绍 apiserver「是什么」，只讲它「怎么处理请求」 |
| `K8s-资源全览.md` | API 版本速查、对象清单、CRD 简介 | 不再罗列资源对象，只讲对象背后的模型 |
| `K8s-Pod生命周期详解.md` | Pod 创建 10 步时间线 | 本文是「另一条时间线」：一次请求在 apiserver 内部的旅程 |
| `K8s-etcd详解.md` | etcd 本身（Raft/备份/调优） | 只讲 apiserver ↔ etcd 的接口面（写、watch、压缩） |

> ❗ **版本标注约定**：文中形如「v1.32 进入 Beta」「v1.29 GA」的说法均已对照官方文档核对过；
> 但功能开关、flag 默认值可能随 minor 版本漂移，落地前用 `kube-apiserver -h` 和
> `kubectl get --raw /version` 再确认一次。

---

## 一、对象模型：一切资源的三段式与身份指纹

### 1.1 GVK 与 GVR：一个资源的两种坐标

```
kubectl 写法         REST 路径
─────────────────────────────────────────────────────────
pods            →   /api/v1/namespaces/default/pods          （core 组，组名为空）
deployments     →   /apis/apps/v1/namespaces/default/deployments
ingresses       →   /apis/networking.k8s.io/v1/namespaces/default/ingresses
clusterroles    →   /apis/rbac.authorization.k8s.io/v1/clusterroles    （集群级，无 ns 段）
```

| 概念 | 含义 | 例子 |
|------|------|------|
| **GVK**（Group/Version/Kind） | 对象的「类型坐标」，写在每个 YAML 的 `apiVersion` + `kind` | `apps/v1, Kind=Deployment` |
| **GVR**（Group/Version/Resource） | 对象的「REST 坐标」，小写复数，用于 URL 和内部路由 | `apps/v1, Resource=deployments` |
| RESTMapper | GVK ↔ GVR 的映射表，来自 apiserver 的 discovery 文档 | kubectl 把 `deploy` 解析成 GVR 就靠它 |

- **core 组（legacy 组）**：组名为空字符串 `""`，路径走 `/api/v1/...`（注意没有 `s`），是历史遗留——Pod/Service/ConfigMap/Node 这些 1.0 时代的元老都在这里
- **命名组**：按域划分（`apps`、`batch`、`networking.k8s.io`、`rbac.authorization.k8s.io`...），路径走 `/apis/<group>/<version>/...`
- **为什么这么设计**：K8s 把自己定位成「API 驱动」而非「资源驱动」——API 组 + 版本是**独立演进单元**，可以单独启用/禁用（`--runtime-config=<group>/<version>=false`）、单独废弃。这就是为什么升级集群时只有某些 YAML 需要改，而不是全部

```bash
# 查看集群当前提供哪些 GVR（三个维度：组、是否 ns 级、动词）
kubectl api-resources --sort-by=name
kubectl api-resources --api-group=apps --verbs=list,watch
kubectl api-resources --namespaced=false -o name

# 查看所有 API 组版本（G/V 纯列表）
kubectl api-versions
```

### 1.2 metadata / spec / status 三段式

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:                    # 身份与元信息（谁、叫什么、属于谁）
  name: web
  namespace: default
  uid: 9a2e3c4e-...          # 服务端分配，集群全时空唯一
  resourceVersion: "812345"  # etcd 里这条 key 的版本号（见 §3 核心）
  generation: 3              # spec 被改过几次（metadata/status 改动不计数）
  labels: {app: web}         # 给「人看的」选择器数据
  annotations: {...}         # 给「工具看的」非结构化数据
  ownerReferences: [...]     # 级联删除依据（见 §4）
  finalizers: [...]          # 删除前置钩子（见 §4）
  managedFields: [...]       # 字段管理者（Server-Side Apply 的记账本）
spec:                        # 期望状态：你声明「我想要什么」
  replicas: 3
  template: {...}
status:                      # 观测状态：控制器报告「现在是什么」
  replicas: 3
  readyReplicas: 2
  observedGeneration: 3      # 控制器已处理到第几代 spec
```

**为什么这么设计（spec/status 分离是控制器模式的合同）**：

- spec 只有用户能写、status 只有控制器能写——API 层面用 **subresource** 把这个合同固化：写 status 要走 `PUT /apis/apps/v1/namespaces/default/deployments/<name>/status`，RBAC 可以只给控制器授 `deployments/status` 权限而不给主资源
- status 更新**不增加 generation**——所以 reconciliation 循环的标准开头是：`if status.observedGeneration == metadata.generation { 没我事, return }`
- spec 与 status 分离也让「读 status 便宜、写 spec 走完整准入」成为可能

### 1.3 四个「身份指纹」：uid / generation / resourceVersion / deletionTimestamp

| 字段 | 由谁写 | 何时变 | 用途 |
|------|-------|--------|------|
| **uid** | apiserver 创建时分配 | 永不变化；删后重建是新 uid | 区分「同名新对象」——GC 靠 uid 确认父子关系没认错人 |
| **generation** | apiserver | spec 变更时 +1（status/metadata 改动不加） | 控制器判断「我处理的是不是最新期望」 |
| **resourceVersion** | etcd（mod_revision） | **任何**写入都变，包括 status、注解 | ① 乐观锁：update 时带上它，冲突返回 409；② watch 游标（§3 的核心） |
| **deletionTimestamp** | apiserver（接到 delete 后） | 一旦设置，对象进入「即将删除」只读态 | finalizer 的触发器：有这个时间戳的对象不会被重新当作活对象 |

```bash
# 亲眼看一下三个字段的关系：改 spec 与改 status 对版本号的不同影响
kubectl get deploy web -o jsonpath='{.metadata.generation} {.metadata.resourceVersion}{"\n"}'
kubectl scale deploy web --replicas=4    # generation +1，resourceVersion 也变
kubectl patch deploy web --type=merge -p '{"metadata":{"annotations":{"x":"1"}}}'   # generation 不变，resourceVersion 变
```

> ❗ 生产上大量「偶发 update 失败」就是乐观锁冲突：`Operation cannot be fulfilled on deployments.apps "web": the object has been modified`。正确姿势是**读-改-写重试**，不是把 resourceVersion 抹掉强写（那是盲写，会覆盖别人的并发修改）。

### 1.4 API 版本演进：alpha → beta → GA 的兼容承诺

官方 API deprecation policy 的核心承诺（已核对）：

| 稳定性 | 命名 | 承诺 | 典型命运 |
|-------|------|------|---------|
| **Alpha** | `v1alpha1` | 可能**随时**在任何版本被移除，不保证兼容 | KCD/PodGroupProtection 之类新特性先在这里试水 |
| **Beta** | `v1beta1` | 宣布废弃后，**9 个月或 3 个 minor 版本**（取长者）才会停止服务 | 特性基本定型但 API 还允许改 |
| **GA** | `v1` | 可标记 deprecated，但**在主版本内不会被移除**（官方声明无近期计划删除 GA API） | 永久向后兼容 |

另有两条硬规则决定了「为什么升级不简单等于改 apiVersion」：

- **round-trip 无损**：同一版本内，对象必须能在各 API 版本间双向转换不丢信息（v1beta1 写的对象，读成 v1 再转回来必须一致）。所以 apiserver 内部有一个 **internal version**（无版本的 Go 结构体），所有外部版本都只是它的投影
- **同一持久化数据的多版本视图**：etcd 里每个对象只按 **storage version** 存一份；你用哪个版本请求，apiserver 就现场转换成哪个版本。**所以「对象升级」其实不需要改写存量数据**——除非 storage version 也变了（此时后台会做存储迁移，大规模集群上要关注迁移窗口）

### 1.5 已移除 API 的年表与迁移工具链

升级集群前必须核对这张表（数据来自官方 Deprecated API Migration Guide）：

| 版本 | 停止服务的 API | 记不住的至少记住这些 |
|------|--------------|---------------------|
| v1.16 | `apps/v1beta1`、`apps/v1beta2`、`extensions/v1beta1` 的 Deployment/RS/DS/STS | selector 变为必填不可变 |
| **v1.22** | Ingress `extensions/v1beta1` & `networking.k8s.io/v1beta1`、CRD `apiextensions/v1beta1`、APIService `apiregistration/v1beta1`、Webhook 配置 `admissionregistration/v1beta1`、RBAC `v1beta1`、CSR `certificates/v1beta1` 等 | **史上最大一波移除**；webhook v1 默认值变化：failurePolicy 默认 `Fail`、timeoutSeconds 默认 `10` |
| v1.25 | PSP `policy/v1beta1`、CronJob `batch/v1beta1`、HPA `autoscaling/v2beta1`、PDB `policy/v1beta1`、Event `events.k8s.io/v1beta1`、EndpointSlice `discovery/v1beta1`、RuntimeClass `node.k8s.io/v1beta1` | PSP 由 Pod Security Admission 取代 |
| v1.26 | HPA `autoscaling/v2beta2`、flowcontrol `v1beta1` | |
| v1.27 | CSIStorageCapacity `storage.k8s.io/v1beta1` | |
| v1.29 | flowcontrol `v1beta2` | APF 进 v1（GA）|
| v1.32 | flowcontrol `v1beta3` | 目前最近一次移除；v1.33+ 暂无新移除 |

**集群里谁在调用旧 API？三个官方探测通道（v1.19 起）**：

| 信号 | 位置 | 用法 |
|------|------|------|
| `Warning` 响应头 | 客户端（kubectl 直接打印黄字） | `kubectl apply` 时留意: `Warning: policy/v1beta1 PodDisruptionBudget is deprecated...` |
| 审计注解 | 审计事件上打 `k8s.io/deprecated: "true"` | 审计日志里 grep（§8）|
| 指标 | `apiserver_requested_deprecated_apis{removed_release="..."}` | `apiserver_requested_deprecated_apis{removed_release="1.32"} * on(group,version,resource,subresource) group_right() apiserver_request_total` |

**离线扫描工具**（CI 里挡住旧 YAML）：

```bash
# kubepug：扫集群存量 + 本地清单，输出 deprecated/deleted
kubepug --k8s-version=v1.37 --input-file=./manifests/

# pluto：Fairwinds 出品，同样支持文件/Helm release 扫描
pluto detect-files -d ./manifests/

# Helm 存量 release 的模板改版本号（不是 kubectl convert）
helm plugin install https://github.com/helm/helm-mapkubeapis
helm mapkubeapis <release-name> -n <ns>
```

> 备注：`kubectl convert` 曾经是内建子命令，后来拆成独立插件（`kubectl-convert`），默认不再随 kubectl 安装——生产迁移优先用 kubepug/pluto 发现 + 修改源仓库清单，而不是在线转换。

### 1.6 三把瑞士军刀：explain / api-resources / --v=8

```bash
# ── kubectl explain：OpenAPI schema 的离线字典 ──
kubectl explain pods.spec.containers --recursive | less
kubectl explain deployment.spec --format=plaintext.openapiv3    # v1.23+ 可看 OpenAPI v3 原始结构

# ── kubectl api-resources：本集群 GVR 活点地图 ──
kubectl api-resources --verbs=list,get      # 谁支持 list/get（写 informer 前必查）
kubectl api-resources --namespaced=false    # 集群级资源清单（GC 跨 ns owner 规则要用）

# ── kubectl -v 日志等级（官方定义）──
#   --v=6  显示请求的 REST 路径        ← 看「kubectl 到底调了什么 API」
#   --v=7  显示 HTTP 请求头            ← 看 Accept/Content-Type/User-Agent
#   --v=8  显示请求/响应体              ← 拆 RequestPath 用（实验 1.3）
#   --v=9  显示完整不截断的请求体
kubectl get deploy web -v=6 2>&1 | grep -E 'GET|PATCH'
```

---

## 二、一次请求的完整链路（RequestPath）

`kubectl apply -f deploy.yaml` 的一个 PATCH 请求，在 apiserver 里走的路：

```
client (kubectl / controller / kubelet)
    │ HTTPS，相互验证：客户端证书/token → apiserver 启动参数 --tls-cert-file 等
    ▼
┌─ handler chain ─────────────────────────────────────────────────────┐
│ ① 解析 RequestInfo：verb=patch, GVR=apps/v1/deployments, ns, name    │
│ ② 流量整形：APF（或老式 --max-requests-inflight）超额 → 429 或排队    │
│ ③ 认证 Authentication：组不出身份 → 401                              │
│ ④ 审计打点 stage=RequestReceived                                    │
│ ⑤ 鉴权 Authorization：无权 → 403                                     │
│ ⑥ 准入第①相：Mutating 链（串行，可改写对象体）                        │
│ ⑦ 解码请求版本 → 转 internal version → 填默认值 → schema 校验（400） │
│ ⑧ 准入第②相：Validating 链（webhook 并行，只读校验）                  │
│ ⑨ 转换为 storage version                                            │
│ ⑩ etcd 事务写入（QUOTA/冲突在这里失败 → 507/409）                     │
│ ⑪ 组装响应（转回请求版本）→ watch 扇出广播 → 审计 stage=ResponseComplete│
└──────────────────────────────────────────────────────────────────────┘
```

> 说明：审计 handler 实际包裹住鉴权之后的整段链路（RequestReceived 只是打点位置示意），
> 各过滤器的精确叠套顺序随版本微调，但**「认证 → 鉴权 → 准入 → 转换 → 存储」这个主干不变**。

### 2.1 认证（Authentication）：你是谁

apiserver 没有用户对象、没有密码体系——「普通用户」由外部系统签发凭证，apiserver 只做校验。
多个认证插件按配置组成**尝试链**，任一成功即得 `{username, uid, groups, extra}`：

| 方式 | 凭证形态 | 典型用途 | 备注 |
|------|---------|---------|------|
| **X.509 客户端证书** | `--client-ca-file` 签署的证书；CN=username，O=groups | 管理员 kubeconfig（kubeadm 的 `kubernetes-admin`，O=system:masters） | 证书没有撤销列表，泄露=换 CA 或靠短有效期 |
| **ServiceAccount Token** | JWT（TokenRequest 颁发的绑定 token / 挂载的 projected token） | Pod 内客户端 | issuer 通过 `--service-account-issuer` 等配置；1.24 起不再自动生成长期 Secret |
| **OIDC** | 外部 IdP 签发的 id_token | 人类 SSO 登录 | flag 配置（`--oidc-*`）或**结构化认证配置文件**（AuthenticationConfiguration，`--authentication-config`，**v1.34 起 GA**，支持多 issuer + CEL 映射） |
| **静态 token 文件** | `--token-auth-file` | 清汤寡水的引导场景 | 改文件不重读 |
| **Bootstrap token** | kube-system 里的 bootstrap Secret | 节点加入 | kubeadm join 用 |
| **Webhook（TokenReview）** | apiserver 把 bearer token 转发给外部服务判定 | 云厂商托管集群（IAM 集成） | 有缓存 TTL 参数 |
| **匿名** | 无凭证 → `system:anonymous` / `system:unauthenticated` | 健康检查、公开端点 | `--anonymous-auth` 默认 `true`；鉴权模式非 AlwaysAllow 时仍然拒绝 |

```bash
# 亲手验证「我是谁」——SelfSubjectReview（v1.28 起 GA）
kubectl auth whoami
# 或 REST 方式
kubectl create --raw /apis/authentication.k8s.io/v1/selfsubjectreviews -f /dev/stdin <<'EOF'
{"apiVersion":"authentication.k8s.io/v1","kind":"SelfSubjectReview"}
EOF
```

### 2.2 鉴权（Authorization）：你能干什么

认证通过后，请求进入鉴权器列表（`--authorization-mode` 配置，**不配置时默认 AlwaysAllow**——不带鉴权模式的 apiserver 等于裸奔）。kubeadm 默认 `Node,RBAC`：

| 模式 | 干了什么 | 组合位置 |
|------|---------|---------|
| **Node** | 专给 kubelet 的细粒度鉴权：只允许读自己节点的 Pod/Secret/ConfigMap、写自己 Node 对象等 | kubelet 流量先进 Node 模式 |
| **RBAC** | Role/ClusterRole + Binding 判定（你已有专篇笔记，不展开） | 其他流量进 RBAC |
| **Webhook** | POST `SubjectAccessReview` 给外部引擎（OPA 等） | 放在最后兜底 |
| AlwaysAllow / AlwaysDeny | 字面意思 | 测试/联调用 |

- 多个模式**按列表顺序命中即返回**：第一个给出明确 Allow 或 Deny 的生效，全部 abstain 则最终拒绝
- ❗ **401 与 403 的分界线**：401=认证失败（没认出你是谁）；403=认证过了但 RBAC 不放行。排障先看 apiserver 日志里那条请求的 `user=` 字段，别一上来就改 ClusterRole
- Node 模式的黄金搭档是 **NodeRestriction 准入插件**（见下表）——一个管「能调用什么 API」，一个管「能改哪些字段」

### 2.3 准入控制（Admission）：最后两道闸

```
                  为什么 Mutating 必须在 Validating 之前？
                  ↓
Mutating 相（串行）        Validating 相（法）  ← 校验者必须看到「最终落库的对象」，
  ├ 内建 mutating 插件     ├ ValidatingAdmissionWebhook（并行调用）   否则校验的是半成品
  ├ MutatingAdmissionWebhook（按 name 排序，串行，可能 reinvoke）
  └ MutatingAdmissionPolicy（CEL）
                  ↓                        ↓
            对象可能被改写                 对象定型，任何拒绝 → 整个请求失败
```

- **读写不对称**：准入只作用于 create/update/delete/connect（如 exec），**get/list/watch 完全绕过准入层**——所以「我能 get 但不能 create」是正常现象，不是 bug
- 任一相中任一插件拒绝 → 立即整体拒绝；有 side effect 的插件（典型：ResourceQuota 的计数）自己负责回收，因为它不知道后面的插件会不会拒绝

**v1.37 默认开启的准入插件**（`kube-apiserver -h | grep enable-admission-plugins` 可验）：

| 插件 | 类型 | 干什么 |
|------|------|-------|
| NamespaceLifecycle | V | 正在删除的 ns 禁止新建对象；不存在 ns 拒写；防删 default/kube-system/kube-public |
| ServiceAccount | M+V | 自动挂 SA、生成 token 卷 |
| LimitRanger | M+V | 按 LimitRange 填默认 request/limit、校验上限下限 |
| ResourceQuota | V | 配额核查（超了直接拒） |
| DefaultStorageClass | M | PVC 没写 storageClassName 时补默认值（**PVC 后补默认 ≠ 你可以不写**，改默认 SC 不影响存量） |
| DefaultTolerationSeconds | M | 给 Pod 补 notready/unreachable 的默认容忍秒数（默认 300s） |
| NodeRestriction* | V | kubelet 只能改自己的 Node/绑到自己节点的 Pod，限制可改标签前缀 |
| PodSecurity | V | 按 ns 标签 enforce/audit/warn 三模式执行 Pod 安全标准（**v1.25 起 GA，PSP 的继任者**） |
| PersistentVolumeClaimResize | V | SC 没开 allowVolumeExpansion 就拒扩容 |
| StorageObjectInUseProtection | M | 给新 PV/PVC 自动加 protection finalizer（§4 卡死案例的主角） |
| RuntimeClass / Priority / TaintNodesByCondition | M+V | 填 overhead / priority 值 / 新节点先来 NotReady 污点防调度竞态 |
| CertificateApproval / CertificateSigning / CertificateSubjectRestriction | V | CSR 审批链安全闸（禁止 system:masters 组的 kube-apiserver-client 证书） |
| MutatingAdmissionWebhook / ValidatingAdmissionWebhook | M / V | 挂你自己写的 HTTP webhook（§2.4） |
| ValidatingAdmissionPolicy / MutatingAdmissionPolicy | V / M | CEL 声明式策略，不用起 webhook 服务（GA 时间分别是 **v1.30 / v1.36**）|

*NodeRestriction 不在编译默认列表，但 kubeadm 等发行版会随 `--authorization-mode=Node,RBAC` 一并显式开启。

### 2.4 扩展点：webhook 还是 CEL？

| 维度 | Mutating/ValidatingAdmissionWebhook | Validating/MutatingAdmissionPolicy（CEL） |
|------|------------------------------------|-------------------------------------------|
| 逻辑宿主 | 你部署的 HTTPS 服务 | 集群内对象（`admissionregistration.k8s.io/v1`） |
| 成熟度 | 老牌（1.16 起 v1 GA） | Validating: **v1.30 GA**；Mutating: **v1.36 GA 且默认开** |
| 时延与可用性 | 每次调用一次外部往返，可被打挂 | 进程内 CEL 求值，无网络依赖 |
| 适合场景 | 需要查外部系统、复杂判定、镜像验签 | 「字段级」规则：replicas ≤ 5、强制 label、禁改某字段 |

webhook 的生产故障域（这节比配置语法值钱）：

- **v1 默认 fail-close**：`failurePolicy` 默认 `Fail`、`timeoutSeconds` 默认 10s（v1beta1 时代是 Ignore/30s）。**webhook 服务挂 + failurePolicy=Fail = 匹配范围内的所有写操作全被拒**——自定义 webhook 常见灾难
- 建议：① 用 `namespaceSelector` 排除 `kube-system` 等系统 ns；② 范围用 `objectSelector` 收紧；③ 先以 `failurePolicy: Ignore` + 审计上线，稳定后再 Fail
- **v1.37 起的变化**：TokenReview / SubjectAccessReview / SelfSubject* 这批虚拟资源**默认不再进入 webhook**（防止 webhook 把自己的认证鉴权链锁死）
- mutating webhook 按名字串行调用；若后续 webhook 又改了对象，`reinvocationPolicy` 可让前面的 webhook 被重调一次——多个会注入的 webhook 共存（如 Istio + Vault injector）时顺序敏感

### 2.5 转换与落库

- 请求对象按「请求版本」（如 `apps/v1`）解码 → 转 **internal version** → 准入在 internal 结构上工作 → 校验通过 → 转 **storage version** 写 etcd
- 响应时再从 storage version 转回请求版本。所以你用 `v1` 和 `v2` 读同一个 HPA，看到两种长相的同一份数据（实验见 §7.3）
- 落库失败的两个高频错误：
  - `409 Conflict`：resourceVersion 对不上（乐观锁）
  - `507`/`etcdserver: request is too large`：对象超过 etcd 单次事务上限（默认约 1.5 MiB）——巨型 ConfigMap/Helm release Secret 撞的就是它


---

## 三、list-watch 与 informer：控制器的心跳（本篇核心）

### 3.1 为什么是 list-watch，而不是轮询或消息队列

设计取舍一句话：K8s 把「事件流」建立在**同一个存储（etcd）的版本号**上，而不是另起一套消息系统。

| 方案 | 为什么被淘汰 |
|------|------------|
| 轮询 list | N 个控制器 × 每秒全量读，etcd 早早被打爆；还有天然延迟窗口 |
| 消息队列（Kafka 式） | 引入第二套需要保证不丢、不重的系统；事件与数据分离后还要解决「事件到了但对象已删」的一致性问题 |
| **etcd 版本号 + watch** | 变更天然有序（每个 key 的修改都有全局单调的 mod_revision）；watch 是「带宽友好」的增量推送；客户端断线凭版本号续传，丢不了 |

### 3.2 list + watch 的标准握手

```
client（每个控制器/每个 informer）              kube-apiserver
        │                                            │
        │── LIST /api/v1/pods ──────────────────────▶│  一次性快照
        │◀──── PodList{ metadata.resourceVersion="10245", items:[...] }
        │                                            │  ★ 这个 RV 是「快照时刻」的游标
        │── WATCH /api/v1/pods?watch=true&resourceVersion=10245 ──▶
        │◀──── {"type":"ADDED",    object:{...rv:10596...}}        │
        │◀──── {"type":"MODIFIED", object:{...rv:11020...}}        │  流式增量推送
        │◀──── {"type":"DELETED",  object:{...}}                   │
        │◀──── {"type":"BOOKMARK", object:{...rv:12746...}}        │  （可选）帮你穿越热点静默期
        │                                            │
        │           （连接超时 / 网络抖动断开）         │
        │── WATCH ?resourceVersion=11023 ───────────▶│  从最后收到的 RV 续传
        │                                            │
        │   （若 RV 太老 → 410 Gone → 回 LIST 重来）  │  §3.5
```

**resourceVersion 的本质**：etcd 集群的全局单调修订号（mod_revision），每有任意写就 +1。对 K8s 来说它是
**watch 订阅的「连续游标」**——你持有的 RV 声明了「我已经同步到此刻」，apiserver 只推这之后的变化。
**跨资源不可比**：Pod 的 rv=812345 和 ConfigMap 的 rv=2100 没有任何大小关系，不能拿来做先后推断。

### 3.3 resourceVersion 语义表（读操作）

官方 API Concepts 给出的 get/list 语义（已核对）：

| 参数组合 | 语义 | 从哪服务 | 代价 |
|---------|------|---------|------|
| 不设 rv、不设 limit | **Most Recent（强一致）** | 直接找 etcd 做 quorum 读 | ❗ 最贵：全量对象反序列化 + etcd 压力，大集群高危操作 |
| `resourceVersion=0` | **Any（不旧于任意点）** | 多数命中 apiserver 的 watch cache | 便宜；可能略旧（几百 ms～秒级） |
| `resourceVersion=<v>` + `resourceVersionMatch=Exact` | 精确快照 | cache 没有则查 etcd | 该版本点已不可用 → 410 Gone |
| `resourceVersion=<v>` + `resourceVersionMatch=NotOlderThan` | 不旧于 v | cache 优先 | 官方推荐的一致性/性能折中 |
| `limit=500`（+continue token） | 分页拉取 | 切片返回 | 控制单次内存尖峰；**v1.29 起 GA**（原分页门控已移除） |

watch 的三个要点（不写表格，条列）：

- 指定 `resourceVersion=<v>`：从该修订点之后续传；太老→**410 Gone**
- 指定 `resourceVersion=0`：从 watch cache 的当前状态开始——**cache 会把存量对象先以 ADDED 事件发一遍**，等价于「cache 内的免费 list+watch」
- 不指定 rv：从最新状态开始（不保证包含此刻之前的存量）
- `timeoutSeconds=<n>`：客户端建议的 watch 时长；服务端 `--min-request-timeout`（默认 1800s）在此之上随机化——这是**故意的**，防止所有 client 同时重连打雷

**历史窗口**：etcd3 集群默认只保留**最近约 5 分钟**的变更（apiserver 侧 `--etcd-compaction-interval` 默认 `5m0s` 定时发起压缩；watch cache 窗口也只到最近压缩点）。超过窗口的旧 RV 续传 → 410 Gone。

### 3.4 初始事件：sendInitialEvents 与 WatchList

传统痛点：「list 一次 + watch 间隙」之间会漏事件，所以必须严格「先 list 拿 RV，再用这个 RV watch」。
大集群上 list 本身又贵（几万 Pod 的反序列化内存尖峰）。

**WatchList（流式 list）** 把两步合成一步：

```
GET /api/v1/namespaces/test/pods?watch=1&sendInitialEvents=true
    &allowWatchBookmarks=true&resourceVersion=&resourceVersionMatch=NotOlderThan
---
{"type":"ADDED", ...存量对象 foo...}        ← 初始状态，以合成 ADDED 事件流下发
{"type":"ADDED", ...存量对象 bar...}
{"type":"BOOKMARK", object:{rv:10245}}      ← 告诉客户端：初始状态同步完毕，游标=10245
{"type":"MODIFIED", ...}                    ← 之后就是普通 watch 流
```

- **版本阶段（已核对官方 API Concepts 页）**：v1.27 Alpha → **v1.32 进入 Beta → v1.34 起默认启用**（feature gate `WatchList`）。`sendInitialEvents=true` 时必须搭配 `resourceVersionMatch=NotOlderThan`
- 客户端侧由 client-go 的 `WatchListClient` 门控控制；服务端不支持时 client 自动回退普通 list——升级 client-go 不会打挂老集群
- 配套压缩门控 `WatchListCompression`（watch list 响应压缩）
- 收益：省掉「list 全量驻留客户端内存」的尖峰，对大集群 controller 启动/重连最友好

### 3.5 410 Gone：游标过期后的重建

```
        客户端持有 rv = 10245（离线 10 分钟，或集群变更极快）
                        │
        WATCH ?resourceVersion=10245
                        │
        apiserver：这个版本点早于 watch cache 窗口（已被 etcd 压缩）
                        │
                        ▼
        HTTP 410 Gone  /  Status{reason: Expired, message: "too old resource version..."}
                        │
        client-go Reflector 的标准舞步（也是你手写控制器必须抄的作业）：
           1. 丢弃本地缓存（数据已不可信）
           2. 重新 LIST（通常用 resourceVersion=0，从 cache 拿新快照）
           3. 用新快照的 resourceVersion 重开 WATCH
           4. 期间收到的事件可能与缓存重复 → 控制器逻辑必须幂等
```

> 排查提示：controller 日志里周期性出现 `Failed to watch ... too old resource version`，
> 说明该资源变更速率超过了「5 分钟窗口 × 客户端处理速度」——要么控制器消费太慢（队列堆积），
> 要么该资源被无意义高频刷新（常见于过期清理逻辑反复 patch status）。

### 3.6 client-go 内部：Reflector → DeltaFIFO → Indexer

```
                 ┌─────────────────── 你的控制器进程 ───────────────────┐
                 │                                                     │
 apiserver       │   Reflector（client-go/tools/cache）                 │
 ───LIST──WATCH─▶│      │                                              │
 （一次订阅/资源） │      ▼ 把远端事件转成 Delta（Added/Updated/Deleted/  │
                 │   DeltaFIFO         Replaced/Sync）按 key 去重合并   │
                 │      │ 同一个对象的多次变化在队列里折叠成最后一个      │
                 │      ▼                                              │
                 │   Indexer（线程安全本地缓存 = ThreadSafeStore + 索引） │
                 │      │ 索引器：按 namespace/按 label 字段秒查          │
                 │      ▼                                              │
                 │   ResourceEventHandler（你的 OnAdd/OnUpdate/OnDelete） │
                 │      │ 只负责把 key 扔进 WorkQueue                   │
                 │      ▼                                              │
                 │   WorkQueue ──worker──▶ reconcile(key)：             │
                 │                        从 Lister(只读 Indexer) 取对象  │
                 │                        算 diff → 调 API → 更新 status │
                 └─────────────────────────────────────────────────────┘
```

每个角色一句话：

| 组件 | 一句话职责 | 记住这一点 |
|------|-----------|-----------|
| **Reflector** | 跑 list-watch 循环，处理 410/重连 | 日志里 `Failed to watch` 就是它的声音 |
| **DeltaFIFO** | 变更事件队列，按 key 折叠去重 | 洪峰时「旧变化被新变化覆盖」= 天然背压 |
| **Indexer / Store** | 本地只读缓存（宅基地），支持索引查询 | list 不花网络、不占 APF 配额 |
| **Lister** | 包在 Store 上的类型化只读接口 | reconcile 里只能读它，不能直接 GET apiserver |
| **WorkQueue** | 解耦「事件到达」与「业务 reconcile」 | 让你的 worker 池可以并发、限速、重试 |

关键纪律：

- **控制器先 `cache.WaitForCacheSync(stopCh, informer.HasSynced)` 再起 worker**——缓存没同步完就 reconcile，会把「没加载完」当成「被删光」，经典自残
- 业务变更**必须走 API 写回**，严禁直接改本地缓存里的对象（store 里的对象是多 goroutine 共享的，要改先 deep-copy）——controller-runtime 的 `client.Patch` 天然规避
- informer 的 `AddEventHandlerWithResyncPeriod`，**不传 resync 就是 0（不周期性 Sync）**——靠 watch 维持真相，不指望周期刷新兜底

### 3.7 WorkQueue 三种形态与限速

| 队列 | API | 场景 |
|------|-----|------|
| basic | `Add / Get / Done` | 纯 FIFO 去重队列 |
| delaying | `AddAfter(key, d)` | 定时重查（如 30s 后再看证书是否签发） |
| rate-limiting | `AddRateLimited / Forget / NumRequeues` | **生产控制器唯一正确选择**：失败退避重试，成功清零 |

client-go 的默认限速器 `DefaultControllerRateLimiter` 是两层叠加（写自定义控制器时若未注入自己的限速器，就是这个行为）：

```
单项退避：失败 1 次 5ms → 2 次 10ms → 20ms … 指数封顶 1000s
全局限速：bucket 限流 10 QPS / burst 100
两者取慢——保证「毒 key 不会打挂整个控制器，也不会拖着其它 key 陪跑」
```

标准 worker type 骨架（伪代码）：

```go
for processNext() {
    key, _ := queue.Get()
    defer queue.Done(key)
    err := reconcile(ctx, key)          // 读 Lister → 算 diff → 调 API
    switch {
    case err == nil:    queue.Forget(key)          // 成功：清退避
    case retriable:     queue.AddRateLimited(key)  // 失败：退避重试
    default:            queue.Forget(key)          // 业务性失败：记日志丢弃
    }
}
```

### 3.8 informer vs 裸 watch：开销与 watch 风暴

**一个 controller 例程一个 watch 即可？错——是一个「GVR × 每个进程」一个 watch。**

```
集群面账（重点理解）：
  N 个节点 kubelet          → 各自 watch（带 fieldSelector 只看自己节点的 pod）
  controller-manager N 副本 → leader 才工作，但 standby 是否跑 informer 依实现而定，别假设
  你的 60 个微服务 Operator → 每个进程对它 watch 的每种 GVR 都是 1 条长连接
  每类资源全量 list/watch   → apiserver watch cache 扇出；连接数、序列化 CPU、内存线性涨

  ❗ 教科书级事故：给每个应用组件都写了「全集群 Pod informer」
     5000 Pod × 全量 YAML × 60 个进程 → 一次 apiserver 重启后的 relist 风暴就能把控制面打翻
```

优化清单（按性价比排序）：

| 手段 | 收益 | 代价 |
|------|------|------|
| **SharedInformerFactory 共享 informer**（同进程同 GVR 只跑一份 watch + cache） | 进程内控制器数量自由 | 无 |
| **fieldSelector/labelSelector 服务端过滤**（kubelet 式：`spec.nodeName=<本节点>`） | 流量、内存骤降 | 注意 selector 变化要重建 informer |
| **大资源只 watch metadata**（`PartialObjectMetadata`，如只关心 ConfigMap 的 label 变化） | 序列化成本降一个量级 | 拿不到 spec/status |
| **list 用 `resourceVersion=0`** | 命中 watch cache，etcd 零压力 | 接受秒级旧数据（控制器场景通常没问题） |
| **开启分页（limit）做冷启动** | 摊平内存尖峰 | 多次往返 |
| **升级到受益的 combo**：v1.34+ WatchList 默认开 + client-go 新版 | relist 大内存尖峰消失 | 升级 management 成本 |
| **关注 `ShardedListAndWatch`**（**v1.36 起 Alpha，默认关**） | 多副本控制器按 uid/ns 哈希各自只收「自己那份」事件流 | Alpha；字段仅支持 uid/namespace |
| **别给每个 Operator 配全 ns 的 informer** | 从源头杜绝风暴 | 架构纪律 |
| watch cache 本身的演进（如门控 `BtreeWatchCache` 用 B 树实现替换 HashMap、`ConsistentListFromCache` 让强一致 list 也走缓存） | 减少 410 Gone 与 etcd 压力 | 阶段随版本变，以你集群的 feature-gates 文档为准 |

> 度量：直连 apiserver 的 `/metrics`，看 `apiserver_watch_events_total`、`apiserver_registered_watchers`（按 GVR 分组的活跃 watch 数）、
> `apiserver_longrunning_requests`。指标名可能随版本微调，先 `kubectl get --raw /metrics | grep -i watch` 确认。

---

## 四、ownerReference 与垃圾回收（GC）

### 4.1 ownerReference：对象的「户口本」

```yaml
apiVersion: v1
kind: Pod
metadata:
  ownerReferences:
  - apiVersion: apps/v1
    kind: ReplicaSet
    name: web-7d9c8b6f5
    uid: 8f7e6d5c-...          # ★ 关键：父子关系锚定的是 uid，不是名字
    controller: true           # 标记「这是管理我的那个控制器」（每对象至多一个）
    blockOwnerDeletion: true   # 前台删除时，本对象会拖住 owner 不被先删
```

| 字段 | 作用 |
|------|------|
| `controller: true` | 「这是亲爹控制器」；对象最多挂一个，kubectl/工具靠它反查 Deployment→RS→Pod 链 |
| `blockOwnerDeletion: true` | 本 dependent 被清掉之前，owner 不能被最终删除（前台删除的水闸）——写它需要 owner 的 `update finalizers` 权限（由 `OwnerReferencesPermissionEnforcement` 准入插件把关） |
| **adoption** | 控制器看到有「母亲-selector 匹配、但没有 ownerReference 」的孤儿 dependent，会收养（写入自己的 ref）；这也是 RS 接管既有 Pod 的机制；**因为锚定 uid，同名重建的对象不会被误认为同一个** |

> ❗ **跨命名空间 owner 是非法的**：namespaced dependent 不能挂「别的 ns 的 owner」或挂集群级 owner。
> v1.20+ 检测到会产生 `OwnerRefInvalidNamespace` 的 Warning Event：
> `kubectl get events -A --field-selector=reason=OwnerRefInvalidNamespace`，这类 dependent 不会被 GC。

### 4.2 三种级联删除策略

```
kubectl delete deploy web            ← 默认 Background
kubectl delete deploy web --cascade=foreground
kubectl delete deploy web --cascade=orphan
```

| 策略 | owner 何时消失 | dependent 的下场 | 用途 |
|------|--------------|------------------|------|
| **Background**（默认） | **立即**从 etcd 删除 | GC 控制器在后台异步逐个删 | 一般操作；返回快 |
| **Foreground** | 先打 `deletionTimestamp` + 挂 `foregroundDeletion` finalizer，**保持可见**直到最后 | GC 先把所有（带 blockOwnerDeletion 且在 GC 缓存中的）dependent 删光，最后才删 owner | 演示/需要观察完整收敛；如「确认全删干净再重建」 |
| **Orphan** | 立即删除 | **留下**——ownerReference 被摘除，变成孤儿 | 接管场景：删 Deployment 留 Pod 给新控制器收养 |

Foreground 的时序（值得背）：

```
1. DELETE 带 propagationPolicy=Foreground
2. apiserver 给 owner 打 deletionTimestamp，加 foregroundDeletion finalizer，owner 仍可读（Terminating）
3. GC 遍历其 dependent（有 blockOwnerDeletion=true 的），逐个删除
4. 全部 dependent 消失后，GC 移除 finalizer
5. owner 真正从 etcd 消失
```

> 注意 GC 的知识盲区：「GC 缓存里不存在的资源类型（不能被 list/watch）」和「与删除并发创建的 dependent」不阻塞前台删除——所以 Foreground 不是严格分布式事务。

### 4.3 finalizer：删除前的「卸任审计」

```
DELETE 请求
   │  对象有 finalizers
   ▼
对象不消失：deletionTimestamp=<现在>，状态 Terminating，新 spec 写入被拒
   │
   ▼
对应控制器 watch 到 deletionTimestamp → 执行清理（释放 LB、回收卷、退注册中心…）
   │
   ▼
控制器 PATCH 摘掉自己那把 finalizer → finalizers 清空 → apiserver 真正从 etcd 删除
```

**典型卡死场景与处置**：

| 症状 | 幕后 | 正确处置 |
|------|------|---------|
| Namespace 永远 Terminating | ns 内某资源 finalizer 未清 / metrics 风格的 APIService 故障拖住发现 | 先找卡住的资源：`kubectl api-resources --verbs=list --namespaced -o name \| xargs -n1 kubectl get -n <ns> --ignore-not-found`，修根因；万不得已才 `kubectl get ns <ns> -o json \| jq 'del(.spec.finalizers)' > ns.json && kubectl replace --raw /api/v1/namespaces/<ns>/finalize -f ./ns.json`（务必先读下面的警告） |
| PV/PVC 卡在删除 | `kubernetes.io/pv-protection` 由 StorageObjectInUseProtection 自动挂的 | 先删使用它的 Pod；没人用了自会释放 |
| 云厂商 LB/PVC 的 Service 删不掉 | cloud-controller 的 finalizer，外部资源释放失败 | 去云控制台/凭据查失败原因，修 IAM/配额 |
| CRD 已卸载，CR 残留 Terminating | 没人来摘 finalizer | 修 CRD 或手动 remove（接受外部资源泄漏） |

> ❗ **为什么强制删 finalizer 是危险动作**：finalizer 的语义是「外部世界还有以我为凭据的资源」。
> 你绕过控制器直接摘掉 = **告诉 K8s 假装已清理**——云盘、LB、DNS 记录不会消失，变成收钱的孤儿。
> 正确顺序永远是：**先修「清理为什么失败」，实在修不了、确认外部资源已手工处理后，才允许手动摘 finalizer**。


---

## 五、APF（API Priority and Fairness）：apiserver 的交通管制

### 5.1 解决什么问题

老式限流只有两闸 `--max-requests-inflight=400`（非变更类）+ `--max-mutating-requests-inflight=200`（默认）：
一个发疯的控制器刷屏 list，照样把 600 个并发全吃光，kubelet 心跳和 leader 选举一起陪葬。

**APF（v1.29 起 GA/Stable，默认开启）**把「总量限流」升级成「分类排队」：

- 开启 APF 后，上述两个 flag 的值**相加**得到总并发预算（600），按 *nominal concurrency shares* 切给各优先级
- 每个优先级自己的并发上限、自己的队列；突发先排队（shuffle sharding 公平调度），排不过才拒（HTTP 429 带 `Retry-After`）
- **watch 请求属于 APF 管辖**（初始事件阶段占座）；`exec`/`logs` 这类**长连接请求不受 APF 也不受 max-inflight 限制**——exec 风暴打的是别的资源，不在本章火力范围
- **seat（舱位）概念**：大对象 list 请求被估算占多个座位，写请求会额外占座以覆盖「给所有 watcher 推通知」的成本——所以 APF 天然惩罚大 list 和高 fanout 写

### 5.2 两个配置对象与匹配链

```
请求进来
  │  按 matchingPrecedence 从小到大逐个 FlowSchema 匹配，首个命中即停
  ▼
FlowSchema（分类器）：subjects(用户/SA/组) × resourceRules(GVR+verb+ns) 或 nonResourceRules
  │  distinguisherMethod: ByUser / ByNamespace / 无（决定"流"内再分几个公平队列）
  ▼
PriorityLevelConfiguration（泳道）：
  type: Queue / Reject            ← 超额进队列还是直接 429
  limited.nominalConcurrencyShares: 30   ← 预算份额（相对权重）
  limited.limitablePercent / lendablePercent / borrowingLimitPercent（v1.26+ 优先级间借调并发）
  queuing: { queues, queueLengthLimit, handSize }   ← shuffle sharding 细调
```

**默认泳道**（`kubectl get prioritylevelconfigurations` 可见）：

| 优先级 | 服务谁 | nominal shares（bootstrap 源码默认） | limitResponse |
|--------|--------|--------------------------|---------|
| `exempt`（mandatory） | `system:masters` 的请求（永不排队） | 不属于有限流体系 | 直通 |
| node-high | kubelet 心跳/状态更新 | 40 | Queue（可借出 25%） |
| system | `system:nodes` 非心跳请求 | 30 | Queue（可借出 33%） |
| leader-election | KCM/scheduler 的 Lease 续租 | 10 | Queue（不外借） |
| workload-high | 内建控制器与 kube-system SA | 40 | Queue（可借出 50%） |
| workload-low | 其他 ServiceAccount（含你的 Pod 内控制器） | 100 | Queue（可借出 90%） |
| global-default | 其余流量（如普通 kubectl） | 20 | Queue（可借出 50%） |
| `catch-all`（mandatory） | 兜底（只有所有 FlowSchema 都没命中才走到） | 5 | **Reject 直接拒** |

> 另有专用 FlowSchema `probes`：GET `/healthz` `/readyz` `/livez` 的请求直接进 `exempt`——健康检查不会被限流掐死。
> LendablePercent 的概念：把本泳道名义并发的一定比例共享给紧张的泳道借用（**v1.26+** 周期调整）。

- mandatory 对象不可改；suggested 对象可被 apiserver **每分钟**重新校准——要固定自定义，
  需打注解 `apf.kubernetes.io/autoupdate-spec: "false"`，否则你的改动会被刷回去

### 5.3 识别与调试 429

症状：客户端日志 `429 Too Many Requests`，响应头带 `Retry-After`，body 里写 `reason: "Too many requests"`。
先分清三种来源（§9 有对照）：

```bash
# ① 是不是 APF 拒的？按 flow_schema/priority_level/reason 看拒绝分布
apiserver_flowcontrol_rejected_requests_total
#    reason ∈ queue-full(队列挤爆) / concurrency-limit(泳道配置为 Reject) / time-out(排队超时) / cancelled

# ② 是不是在排队？（未拒绝但延迟抬升）
apiserver_flowcontrol_current_inqueue_requests      # 各泳道排队深度
apiserver_flowcontrol_request_wait_duration_seconds # 排队耗时直方图

# ③ 泳道利用率与上限
apiserver_flowcontrol_current_executing_seats       # 在执行的座位
apiserver_flowcontrol_nominal_limit_seats           # 名义座椅数
apiserver_flowcontrol_priority_level_seat_utilization
```

处置 playbook：

1. 找到被挤的泳道和罪魁祸首 flow（`rejected_requests_total` + `flow_schema` + ByUser 区分）
2. 短期：给肇事 client 降温（限流 QPS、修重试风暴）；给关键泳道提 `nominalConcurrencyShares` 或允许它从闲置泳道借（v1.26+ `lendablePercent`）
3. 长期：减少昂贵请求——大 list 加分页、改 watch、用 selector 收窄（见 §3.8）
4. 例子：把 default SA 的 list events 隔离进 catch-all 泳道，防止它饿死同 ns 别人的请求（官方文档同款 FlowSchema：`list-events-default-service-account`）

---

## 六、聚合层（Aggregated API）：让第三方 API 住进同一个 endpoint

### 6.1 聚合层 vs CRD

| | CRD | 聚合层（APIService + extension apiserver） |
|--|-----|------------------------------------------|
| 数据存哪 | etcd（走 apiserver 内置 schema） | 你的服务端自由存（通常绕回 K8s API） |
| 请求路径 | apiserver 自己处理 | apiserver **代理转发**给你的 service |
| 版本/转换 | CRD conversion webhook | 你服务端自己实现多版本 |
| 适合 | 声明式对象（绝大多数场景） | 指标类虚拟资源、需要完全自定义行为 |
| 典型实例 | ArgoCD/CRD 全家桶 | **metrics-server**、Prometheus-adapter、OpenShift 部分 API |

### 6.2 APIService 与代理路径

```yaml
apiVersion: apiregistration.k8s.io/v1
kind: APIService
metadata:
  name: v1beta1.metrics.k8s.io        # 命名即路由：/apis/metrics.k8s.io/v1beta1/*
spec:
  group: metrics.k8s.io
  version: v1beta1
  service:
    namespace: kube-system
    name: metrics-server              # 代理目标 Service（可带 port，默认 443）
  groupPriorityMinimum: 100           # 组在 /apis 里的排序
  versionPriority: 100                # 组内版本排序
  caBundle: <PEM>                     # 校验 extension apiserver 服务端证书
  # insecureSkipTLSVerify: false      # 生产勿开（跳过验证=信任裸奔）
```

```
kubectl top node
    │ GET https://<apiserver>/apis/metrics.k8s.io/v1beta1/nodes
    ▼
kube-apiserver：认证 + 鉴权通过（Path 级）
    │  发现该 Path 属于 APIService v1beta1.metrics.k8s.io → 走聚合层
    ▼
kube-aggregator（apiserver 进程内的代理层）
    │  用 --proxy-client-cert-file 客户端证书（front-proxy-client）发起 HTTPS
    │  放请求头：X-Remote-User / X-Remote-Group（原始用户名、组）
    ▼
metrics-server（extension apiserver）
    │  ① 校验来连接证书是否由 requestheader CA 签发、CN 是否在 allowed-names
    │     （从 kube-system/extension-apiserver-authentication ConfigMap 学来）
    │  ② 反查 K8s：SubjectAccessReview（凭 ClusterRole system:auth-delegator）
    │     确认「这个 user 能不能读 nodes.metrics.k8s.io」
    ▼
执行：聚合各 kubelet /stats/summary 计算后返回
```

相关 apiserver flag（kubeadm 默认已配置好，对照 `/etc/kubernetes/manifests/kube-apiserver.yaml`）：

```text
--requestheader-client-ca-file=/etc/kubernetes/pki/front-proxy-ca.crt   # 谁可以被信任作代理
--requestheader-allowed-names=front-proxy-client                        # 允许的代理证书 CN
--requestheader-username-headers=X-Remote-User
--requestheader-group-headers=X-Remote-Group
--requestheader-extra-headers-prefix=X-Remote-Extra-
--proxy-client-cert-file=/etc/kubernetes/pki/front-proxy-client.crt     # apiserver 自己当客户端的证书
--proxy-client-key-file=/etc/kubernetes/pki/front-proxy-client.key
--enable-aggregator-routing=true   # 代理直达 Endpoints IP 而非 Service ClusterIP（无 kube-proxy 场景用）
```

> ❗ **CA 复用警告（官方文档强调）**：`--requestheader-client-ca-file` 与 `--client-ca-file` 必须用不同 CA。
> 若共用，普通客户端证书会先命中 requestheader 规则、因 CN 不在 allowed-names 被拒——kubelet、控制面组件集体 401。
> kubeadm 为此专门建了独立的 `front-proxy-ca`。

### 6.3 故障识别：FailedDiscoveryCheck

```bash
kubectl get apiservice v1beta1.metrics.k8s.io
# 期望: AVAILABLE=True  ；故障: Available=False reason=FailedDiscoveryCheck

kubectl get apiservice v1beta1.metrics.k8s.io -o jsonpath='{.status.conditions}'
kubectl describe apiservice v1beta1.metrics.k8s.io
```

**金属原理**：aggregation 发现循环要求 5 秒内从 extension apiserver 拿到 discovery 响应；失败就把整个组标记不可用，
于是 `kubectl top` / HPA 报 `metrics.k8s.io` 不可用（连带 `FailedGetResourceMetric`）。

| 典型原因 | 检查 |
|---------|------|
| metrics-server Pod 没起 / 调度失败 | `kubectl -n kube-system get pods -l k8s-app=metrics-server` 及 logs |
| 证书链不对：服务端证书没被 caBundle 覆盖、SNI 错误 | metrics-server `--kubelet-preferred-address-types` + tls 配置；`insecureSkipTLSVerify` 只能当临时烟幕 |
| Service 无 Endpoints（selector 漂移） | `kubectl -n kube-system get endpoints metrics-server` |
| 网络策略拦截 apiserver↔metrics-server | 检查 NetworkPolicy / 跨 ns 访问 |
| extension 自己的 SAR 被拒 | `kubectl auth can-i get nodes.metrics.k8s.io --as=system:serviceaccount:kube-system:metrics-server` 应为 yes，并确认 `system:auth-delegator` 已 bind |

生产建议：给 APIService 的 Available 配告警（`kube_apiservice_status_condition` 或自探），
metrics.k8s.io 挂的是 HPA 心脏，不只是 `kubectl top` 不好用。


---

## 七、直接操作 Raw API：摘掉 kubectl 的「滤镜」

kubectl 做的所有事都是 HTTP。想当控制器的角色，就得能像控制器一样说话。

### 7.1 三条直连路径

```bash
# ── ① kubectl --raw：带着 kubectl 的认证，手势最轻 ──
kubectl get --raw /version
kubectl get --raw /api/v1/namespaces/default/pods --limit=2
kubectl get --raw '/apis/metrics.k8s.io/v1beta1/nodes' | jq .
kubectl get --raw '/readyz?verbose'                       # 组件级健康细节

# ── ② kubectl proxy：本地起一个免证书代理（默认 8001）──
kubectl proxy --port=8001 &
curl http://127.0.0.1:8001/api/v1/namespaces/default/configmaps
# 适用：临时脚本/学习；生产自动化别用它（多一层单点、token 不会自动轮换）

# ── ③ curl + 双向 TLS：最贴近组件的原始姿势 ──
# （从 kubeconfig 提取证书/上下文，全命令见实验 1.1）
curl --cacert ca.crt --cert client.crt --key client.key $SERVER/api/v1/namespaces/default/configmaps

# ③' SA token 版本（演示 Pod 内客户端同一个姿势）：
TOKEN=$(kubectl create token default -n default)
curl --cacert ca.crt -H "Authorization: Bearer $TOKEN" $SERVER/api/v1/namespaces/default/secrets
#   default SA 无 list secrets 权限 → 403 Forbidden：认证 OK、鉴权拒——亲手看到 §2 两闸门
```

### 7.2 API discovery：apiserver 的「自检报告」

| 端点 | 内容 |
|------|------|
| `/api` | core 组支持的版本列表（`["v1"]`） |
| `/apis` | 所有命名组的 APIGroupList（含聚合层扩展组，如 metrics.k8s.io） |
| `/api/v1`、`/apis/<group>/<version>` | 该组版本下所有资源（APIResourceList：name/singularName/namespaced/kind/verbs） |
| `/openapi/v2` | 聚合的全量 OpenAPI v2 文档（有损：default/nullable 等字段会丢） |
| `/openapi/v3` | **v1.27 起 GA**；按组版本拆分 + hash 的 OpenAPI v3 文档（无损），客户端可按版本缓存 |
| `/version` | 构建版本 |
| `/healthz`、`/livez`、`/readyz` | 健康族谱，`?verbose` 出明细（§9.6） |
| `/metrics` | Prometheus 指标（本文所有排查指标的源头） |

聚合发现（aggregated discovery）：自 **v1.30 GA** 起，`/api` 和 `/apis` 两个端点就能发完全部发现文档——客户端用如下 Accept 头：

```bash
curl -s --cacert ca.crt -H "Authorization: Bearer $TOKEN" \
  -H 'Accept: application/json;v=v2;g=apidiscovery.k8s.io;as=APIGroupDiscoveryList' \
  $SERVER/apis | head -c 400
# 不带这个 Accept 头时，/api /apis 返回老式分级文档（向下兼容）
# 收益：kubectl/discovery 客户端不再为 50+ 个组版本每个发起一次文档请求
```

### 7.3 亲手演示「版本协商」：一份数据、两种视图

HPA 同时服务 `autoscaling/v1` 与 `autoscaling/v2`，是同一份持久化数据的两个投影（§1.4 规则）：

```bash
kubectl create deploy vpa-demo --image=nginx
kubectl autoscale deploy vpa-demo --cpu=60% --min=1 --max=4 --dry-run=client -o yaml > hpa.yaml
kubectl apply -f hpa.yaml

# 同一份数据：
kubectl get --raw /apis/autoscaling/v1/namespaces/default/horizontalpodautoscalers/vpa-demo
kubectl get --raw /apis/autoscaling/v2/namespaces/default/horizontalpodautoscalers/vpa-demo
# 对比输出：v1 只有最简字段（targetCPUUtilizationPercentage），v2 是 metrics 数组结构
# —— apiserver 在 storage version 与请求版本之间做了双向转换，有损字段按兼容规则折叠
```

> 这就是升级时「改 yaml 的 apiVersion」本质：数据没动，只是让 apiserver 以新版本的 schema 读取/校验那同一份 etcd 记录。

---

## 八、审计日志（Audit）：回答「谁、何时、改了什么」

### 8.1 生命周期与策略

每个请求最多记录 4 个 stage（审计 handler 在 handler chain 的很早期生成 `RequestReceived`）：

| stage | 时机 | 说明 |
|-------|------|------|
| RequestReceived | 请求刚到达，还没鉴权/执行 | 抓「来闹事但还没进来」的请求 |
| ResponseStarted | 响应头已发、body 未发 | 只对长请求（watch）有意义 |
| ResponseComplete | 响应完成 | 最常用 |
| Panic | 引起 panic 的请求 | 线上事故必查 |

策略（`--audit-policy-file`，不传 = 完全不审计；rules 不能为空）按规则**从上到下首个命中**，level 决定记多少：

| level | 记什么 |
|-------|-------|
| None | 不记 |
| Metadata | 只记元数据：用户/时间/GVR/verb/响应码 |
| Request | 元数据 + **请求 body**（非资源 URL 不适用） |
| RequestResponse | 元数据 + 请求 body + **响应 body**（最贵，慎用） |

> ❗ **审计不自动脱敏**：你如果把 secrets 配成 RequestResponse，base64 后的密钥就直接落在日志里。
> 官方惯例：secrets/configmaps 只到 `Metadata`；敏感渠道（存储加密 EncryptionConfiguration）交给数据面。

### 8.2 推荐的最小策略 + 两处典型裁剪

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages: ["RequestReceived"]          # 最常见的降噪手段
rules:
  - level: None                           # ① 系统账号的高频 watch 不进审计（价值低）
    users: ["system:kube-proxy", "system:kube-scheduler"]
    verbs: ["watch"]
  - level: None                           # ② 组件间高频自述：leases（leader 选举）
    resources: [{group: "coordination.k8s.io", resources: ["leases"]}]
  - level: RequestResponse                # ③ 进容器/跑命令全套记录
    verbs: ["create", "get"]
    resources: [{group: "", resources: ["pods/exec", "pods/attach", "pods/portforward"]}]
  - level: Metadata                       # ④ 敏感对象只记元数据
    resources: [{group: "", resources: ["secrets"]}, {group: "", resources: ["configmaps"]}]
  - level: Metadata                       # ⑤ 其余一切：兜底
```

### 8.3 后端与默认参数

| 后端 | flag | 要点（已核对官方默认值） |
|------|------|------------------------|
| **log** | `--audit-log-path`（`-` = stdout） | 不设置 = 禁用 log 后端 |
|  | `--audit-log-mode` | 默认 `blocking`（事件写盘阻塞响应）；`batch` 不建议 log 后端；`blocking-strict` 在 RequestReceived 失败时整个请求失败 |
|  | `--audit-log-maxsize/maxbackup/maxage` | 滚动：默认 **100MB / 100 份 / 366 天** |
|  | `--audit-log-truncate-enabled` 等 | 单事件/批次超限截断，默认关 |
| **webhook** | `--audit-webhook-config-file` | 指向 kubeconfig 形态的远端 API；`--audit-webhook-initial-backoff` 失败重试 |
|  | `--audit-webhook-mode` | 默认 `batch`：buffer **10000** 事件、每批最多 **400**、最长攒 **30s**、限流 **10 QPS/burst 15** |

观测：

```bash
# apiserver 内置指标：审计子系统是否健康
apiserver_audit_event_total    # 已产生的审计事件
apiserver_audit_error_total    # 因失败被丢弃的事件（增长 = 后端有问题/写不动）
```

> 静态 Pod 形态部署（kubeadm/kind）时：上面所有文件路径必须额外配置 hostPath 卷挂载到 apiserver 容器，否则改动不生效（详见实验 1.4）。

### 8.4 典型分析场景：「最近谁 exec 进了哪个容器」

```bash
# 从 apiserver 的审计日志里抽取 pods/exec 请求（以 kubeadm 的 /var/log/kubernetes/audit.log 为例）
grep '"subResource":"exec"' /var/log/kubernetes/audit.log | jq -r '
  [ .requestReceivedTimestamp,
    .user.username,
    (.user.groups | map(select(. != "system:masters")) | join(",")),
    .sourceIPs[0],
    (.objectRef.namespace + "/" + .objectRef.name),
    .verb,
    (.responseStatus.code | tostring)
  ] | @tsv' | sort | tail -20

# 配套看「谁在调已废弃 API」（v1.19+ 自动打的注解）
grep 'k8s.io/deprecated' /var/log/kubernetes/audit.log | jq -r '[.requestReceivedTimestamp,.user.username,.requestURI] | @tsv' | sort -u | tail -10
```

另外两个高频问答模板：

- **谁删了 Deployment**：`grep -E '"verb":"delete".*"deployments"' audit.log | jq -r '[.requestReceivedTimestamp,.user.username,.objectRef.name] | @tsv'`
- **服务变更审计**：把 `services, ingresses, networkpolicies` 规则到 Request；在 GitOps 时代主要用来抓「绕过流水线的手工 hotfix」


---

## 九、常见生产问题清单（API 面）

| # | 症状 | 根因链 | 排查动作 | 处置 |
|---|------|--------|---------|------|
| 9.1 | etcd 磁盘暴涨 / `mvcc: database space exceeded`；`etcdserver: request is too large` 拒绝写 | ① 单对象超过 etcd 事务上限（默认约 1.5 MiB）：巨型 ConfigMap / Helm release Secret；② Event 高频（探针风暴、镜像拉取回退刷屏） | `etcdctl endpoint status -w=table` 看 DB 大小与 alarm；`kubectl get events -A --sort-by=.lastTimestamp \| tail` | 拆大对象；events 从 v1beta1 迁 `events.k8s.io/v1` 减量；定期 compact+defrag（详见你的 etcd 笔记） |
| 9.2 | 控制器重启引发「重启风暴」：全组件 CPU/内存瞬间拉满 | 每个进程 informer 首次 list 是全量读；N 副本同时启动 → watch 雪崩 | 监控 `apiserver_registered_watchers`、`apiserver_longrunning_requests`、apiserver 内存曲线 | 副本错峰启动；共享 informer；selector 收窄；大资源只 watch metadata（§3.8） |
| 9.3 | 客户端报 `429 Too Many Requests`，带 `Retry-After` | 三种来源： ① APF 按优先级拒绝（§5）； ② 关 APF 时 max-inflight 到顶； ③ **新版行为**：watch cache 未初始化时，WATCH 和未分页/带 selector 的 LIST 直接 429（保护 etcd 不被打爆，防 APF 占座饿死） | `apiserver_flowcontrol_rejected_requests_total` 看 reason；apiserver 日志 `RequestInfo` 确认客户端 | 客户端必须尊重 `Retry-After` + 指数退避（client-go 已内建）；分页拉取；等待 readyz 503→200 再发起 |
| 9.4 | `kubectl top` 报 `Metrics API not available`；HPA `FailedGetResourceMetric` | 聚合层发现失败（§6.3：metrics-server/证书/Endpoint/网络策略） | `kubectl get apiservice v1beta1.metrics.k8s.io`；describe 看 `FailedDiscoveryCheck` message | 按 §6.3 表修 root cause；常规命根：Pod 挂了 / selector 漂移 / NetworkPolicy |
| 9.5 | apiserver 全面慢（所有请求时延升、watch 延迟） | etcd 慢传导：磁盘 fsync 拉高 → etcd 请求变慢 → apiserver 队列堆积 → APF 占座时间拉长 | `etcd_request_duration_seconds`、`apiserver_request_duration_seconds`、节点 iostat | 上 SSD/独占盘；看是否大 list 风暴（§3.8）；必要时水平扩 apiserver 副本 |
| 9.6 | 想知道 apiserver 此刻活得好不好 | 健康三件套读法（见下） | 见 9.6.1 | — |

### 9.6.1 健康与性能端点读法（kubectl 一句话就够）

```bash
# 组件级健康（verbose 出每个 dependency：etcd / informer-sync / healthz 等）
kubectl get --raw='/readyz?verbose'
# 期望全 [+]；故障时打印 [−] 项
#   [+]ping ok / [+]etcd ok / [+]etcd-readiness ok / [+]informer-sync ok / [+]poststarthook/... ok

# 活的（不需要被重启）——不查依赖，失败才重启
kubectl get --raw='/livez?verbose'

# 指标：所有 §5/§9 的指标都从这里出
kubectl get --raw='/metrics' | grep -E 'apiserver_(flowcontrol|request_total|watch|longrunning|audit)' | head -20
```

**readiness 判度差异（特别在 APF + watch cache 时代）**：`/readyz` 包含 informer-sync 和 etcd-readiness——
所以「apiserver 进程在但 readyz 失败」是针对性保护：watch cache 还没灌满前直接 429（见 9.3③），
让 LB/Ingress 把流量切到别的 apiserver 副本，这对 HA 控制面是生存机制，不是故障。

---

## 十、实验（kind/k3d 沙箱 4 连）

> 环境：本机有 `kind` v0.2x+（k3d 同理，路径差异我会标注）与 `jq`。
> 实验 1.1/1.2/1.3 在任何集群上都能做；1.4 需要重建控制面（kind 一把重置）。

### 实验 1.1 用集群 CA 证书 + curl 直连 apiserver 读写 ConfigMap

**第 0 步：从 kubeconfig 提三件套（kind/k3d/kubeadm 通用）**

```bash
# 证书/密钥都内嵌在 kubeconfig 里（kind/kubeadm 管理员 config 默认如此）：
mkdir -p /tmp/k8s
kubectl config view --minify --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > /tmp/k8s/ca.crt
kubectl config view --minify --raw -o jsonpath='{.users[0].user.client-certificate-data}' | base64 -d > /tmp/k8s/client.crt
kubectl config view --minify --raw -o jsonpath='{.users[0].user.client-key-data}'         | base64 -d > /tmp/k8s/client.key
SERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
echo $SERVER    # kind 默认 https://127.0.0.1:<随机端口>（除非 kind config 固定了 apiServerPort）
```

**凭证物理路径对照表**（想从「文件」而不是「kubeconfig」取时）：

| 发行版 | CA | 管理员客户端证书 | 备注 |
|--------|-----|----------------|------|
| kind | 节点容器内 `/etc/kubernetes/pki/ca.crt` | `/etc/kubernetes/pki/apiserver-kubelet-client.crt`（CN 受限）或直接用 `admin.conf` 提取 | host 端 kubeconfig 已内嵌等价证书，本实验无需进容器 |
| kubeadm | `/etc/kubernetes/pki/ca.crt` | `/etc/kubernetes/pki/admin.conf`（内嵌 cert/key） | `~/.kube/config` 默认为其副本 |
| k3s | `/var/lib/rancher/k3s/server/tls/client-ca.crt` | `/etc/rancher/k3s/k3s.yaml`（内嵌） | k3s.yaml 即 kubeconfig |

**第 1 步：读、写、改、删一个 ConfigMap**

```bash
# ① 读（GET）：打印 jq 过滤后的对象
curl -s --cacert /tmp/k8s/ca.crt --cert /tmp/k8s/client.crt --key /tmp/k8s/client.key \
  $SERVER/api/v1/namespaces/default/configmaps/curl-cm

# ② 写（POST）：Content-Type 必须声明 application/json
curl -s --cacert /tmp/k8s/ca.crt --cert /tmp/k8s/client.crt --key /tmp/k8s/client.key \
  -X POST -H 'Content-Type: application/json' \
  -d '{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"curl-cm","namespace":"default"},"data":{"hello":"raw-api"}}' \
  $SERVER/api/v1/namespaces/default/configmaps

# ③ 改（PATCH，merge 类型）：
curl -s --cacert /tmp/k8s/ca.crt --cert /tmp/k8s/client.crt --key /tmp/k8s/client.key \
  -X PATCH -H 'Content-Type: application/merge-patch+json' \
  -d '{"data":{"extra":"patched-via-curl"}}' \
  $SERVER/api/v1/namespaces/default/configmaps/curl-cm

# ④ 确认 kubectl 也看得到（证明走的就是同一条 REST 通道）
kubectl get cm curl-cm -o yaml

# ⑤ 删（DELETE）：
curl -s --cacert /tmp/k8s/ca.crt --cert /tmp/k8s/client.crt --key /tmp/k8s/client.key \
  -X DELETE $SERVER/api/v1/namespaces/default/configmaps/curl-cm
```

预期看到：②返回 201 + 完整对象；③返回 200 + resourceVersion 自增——拿它和 kubectl 输出对照，亲手验证「kubectl 就是 HTTP」。

### 实验 1.2 抓 watch：观察 resourceVersion 游标

两个终端：A 起 watch，B 制造变更。

```bash
# 终端 A：从「此刻快照的 RV」开始 watch（取 LIST 自己的 resourceVersion，即快照游标）
RV=$(kubectl get cm -n default -o jsonpath='{.metadata.resourceVersion}')
echo "baseline RV=$RV"
curl -sN --cacert /tmp/k8s/ca.crt --cert /tmp/k8s/client.crt --key /tmp/k8s/client.key \
  "$SERVER/api/v1/namespaces/default/configmaps?watch=true&resourceVersion=$RV&allowWatchBookmarks=true"
```

```bash
# 终端 B：制造几次变更，观察 A 屏幕上逐条 JSON 事件
kubectl create cm w1 --from-literal=a=1
kubectl patch cm w1 --type=merge -p '{"data":{"a":"2"}}'
kubectl annotate cm w1 x=y
kubectl delete cm w1
```

**你要看懂的输出**（每行一条独立 JSON，无换行包裹的数组）：

```json
{"type":"ADDED",   "object":{"kind":"ConfigMap",...,"metadata":{"resourceVersion":"81250",...}}}
{"type":"MODIFIED","object":{...,"resourceVersion":"81255",...}}     ← patch 后 rv +?（整数递增）
{"type":"MODIFIED","object":{...,"resourceVersion":"81258",...}}     ← annotate 也算 MODIFIED
{"type":"DELETED", "object":{...}}
{"type":"BOOKMARK","object":{...,"resourceVersion":"81290"}}         ← 服务端不保证固定间隔，通常分钟级（官方明示不要依赖频率）
```

**再看 410 Gone（可选）**：

```bash
# 用一个明显很旧的 RV 续 watch：
curl -s --cacert /tmp/k8s/ca.crt --cert /tmp/k8s/client.crt --key /tmp/k8s/client.key \
  "$SERVER/api/v1/namespaces/default/configmaps?watch=true&resourceVersion=1"
# 典型返回：{"kind":"Status","status":"Failure","code":410,"reason":"Gone",
#   "message":"too old resource version: 1 (xxxxx)"}
# 若你的 fresh 集群还没压缩到那里（5 分钟窗口内侥幸没过期），把 RV 记录等 10 分钟再试即可必现。
```

> `kubectl get cm -w -v=7` 也行：v=7 输出会打印它实际发的 `GET ...?watch=true&resourceVersion=...`，
> 对比 curl 的原始流，能看到 kubectl 在那一层做了什么过滤（客户端表格化）。

### 实验 1.3 `kubectl apply -v=8` 拆解 RequestPath

```bash
cat > /tmp/k8s/reqpath-demo.yaml <<'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: reqpath-demo, namespace: default}
spec:
  replicas: 1
  selector: {matchLabels: {app: reqpath-demo}}
  template:
    metadata: {labels: {app: reqpath-demo}}
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
EOF

kubectl apply -f /tmp/k8s/reqpath-demo.yaml -v=8 2>&1 | tee /tmp/k8s/apply-v8.log | less
# 重点检索（-v=8 输出每行都带 "I1013 ... round_trippers.go" 前缀，按关键字捞）：
grep -E 'GET https|PATCH https|POST https|Response Status|Content-Type|Warning' /tmp/k8s/apply-v8.log
```

把看到的行对号入座（对照 §2 链）：

| -v=8 输出片段 | 对应链路位置 | 说明 |
|---------------|-------------|------|
| `GET https://...:6443/api?timeout=32s`、`GET .../apis?timeout=32s`、`GET .../openapi/v2` | 客户端阶段：discovery（RESTMapper） | kubectl 先问「有哪些 GVR、Deployment 对应哪个 URL」——不属于对象链路 |
| `GET https://.../apis/apps/v1/namespaces/default/deployments/reqpath-demo` | 进入 handler chain 的第一次**读** | apply 判断「存在吗」；会走 ②③④⑤（流量整形/认证/审计/鉴权） |
| `PATCH .../deployments/reqpath-demo?fieldManager=kubectl-client-side-apply&force=true`<br>`Content-Type: application/apply-patch+yaml` | **写**进入：同上 + 准入 ⑥⑦⑧ | Server-Side Apply；v=8 能看到完整请求体与响应体 |
| 响应头/日志里的 `Warning: 299 - "... is deprecated ..."` 行 | 服务端规则：deprecated API 提醒 | 该对象用了将被移除的版本就会打这个 RFC7234 Warning 头（§1.5） |
| 响应 2xx + 完整对象 JSON | 链尾：转换回请求版本 → 响应 | 留意 `metadata.managedFields` 里 `kubectl-client-side-apply` 的账目 |

再看一个拒绝路径的对照（可选）：

```bash
# 造一个一定会被 PodSecurity restricted 拒绝的 ns + 违规 Pod，看 apiserver 在哪个环节拒
kubectl create ns psa-deny
kubectl label ns psa-deny pod-security.kubernetes.io/enforce=restricted
kubectl -n psa-deny run bad --image=nginx:1.27 --privileged -v=8 2>&1 | grep -E 'PATCH|POST|Forbidden|denied|violates'
# 预期：HTTP 403 + 含 "violates PodSecurity" 的 message → 定位在 §2 链的「准入第②相 Validating（PodSecurity 插件）」
```

### 实验 1.4 开启审计并复盘 exec/logs 足迹

**A. kind 最小配置**（官方示例的裁剪版，只保留必要项）：

```bash
mkdir -p /tmp/k8s/audit && cd /tmp/k8s/audit

cat > audit-policy.yaml <<'EOF'
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages: ["RequestReceived"]
rules:
  - level: RequestResponse
    verbs: ["create", "get"]
    resources:
    - group: ""
      resources: ["pods/exec", "pods/log", "pods/attach", "pods/portforward"]
  - level: Metadata
EOF

cat > kind-audit-config.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: ClusterConfiguration
    apiServer:
      extraArgs:
        audit-log-path: /var/log/kubernetes/kube-apiserver-audit.log
        audit-policy-file: /etc/kubernetes/policies/audit-policy.yaml
      extraVolumes:
      - name: audit-policies
        hostPath: /etc/kubernetes/policies
        mountPath: /etc/kubernetes/policies
        readOnly: true
        pathType: "DirectoryOrCreate"
      - name: audit-logs
        hostPath: /var/log/kubernetes
        mountPath: /var/log/kubernetes
        readOnly: false
        pathType: "DirectoryOrCreate"
  extraMounts:
  - hostPath: ./audit-policy.yaml
    containerPath: /etc/kubernetes/policies/audit-policy.yaml
    readOnly: true
EOF

# 若当前目录不是工程目录，把 hostPath 写成绝对路径再 create
kind create cluster --name audit-demo --config kind-audit-config.yaml

# 验证 flag 和挂载确实生效：
docker exec audit-demo-control-plane grep -E 'audit-(log|policy)' /etc/kubernetes/manifests/kube-apiserver.yaml
```

**B. kubeadm 静态 Pod 的配置要点**（自己集群上操作，改动生效靠 kubelet 自动重启静态 Pod）：

在 `/etc/kubernetes/manifests/kube-apiserver.yaml` 的 `command:` 加：

```yaml
    - --audit-policy-file=/etc/kubernetes/audit/policy.yaml
    - --audit-log-path=/var/log/kubernetes/audit.log
    - --audit-log-maxsize=100
    - --audit-log-maxbackup=10
```

并在 `volumeMounts:` 加两个挂载、`volumes:` 加对应两个 hostPath（`File`/`DirectoryOrCreate`）。
文件落到宿主机：policy 放 `/etc/kubernetes/audit/policy.yaml`，日志宿主机路径同上。

**C. 触发事件并读审计**：

```bash
kubectl -n default run audit-test --image=busybox:1.36 --restart=Never -- sleep 3600
kubectl exec audit-test -- ls /
kubectl logs audit-test

# kind 集群：直接在控制面容器里看（审计 JSON 是单行结构，subResource 即 exec/log 子资源）
docker exec audit-demo-control-plane \
  grep -E '"subResource":"(exec|log)"' \
  /var/log/kubernetes/kube-apiserver-audit.log \
  | jq -r '[.stage,.requestReceivedTimestamp,.user.username,.objectRef.namespace,.objectRef.name,.verb,.responseStatus.code] | @tsv'
# 期望输出（典型）：
# ResponseComplete  2026-10-13T08:12:03Z  kubernetes-admin  default  audit-test  create  101/200/...
# ResponseComplete  2026-10-13T08:12:20Z  kubernetes-admin  default  audit-test  get     101/200/...
```

**D. 收尾**：

```bash
kind delete cluster --name audit-demo
rm -rf /tmp/k8s
```

> 读数公式（与 §8.3 对照）：本实验的 exec 记录来自 RequestResponse 规则；日志行的 `user.username`
> 就是审计回答「谁干的」的核心字段；`annotations` 里还能看到 PodSecurity/VAP 记下的拒绝原因。

---

## 十一、速查表 + 参考链接

### 11.1 一页速查

| 主题 | 命令 / 端点 / 指标 |
|------|-------------------|
| 版本与发现 | `kubectl version`；`kubectl api-resources`；`kubectl get --raw /version` |
| 直接调 API | `kubectl get --raw /path`；`kubectl proxy --port=8001`；curl + ca/client.crt（实验 1.1） |
| 看请求链 | `-v=6 URL`；`-v=7 头`；`-v=8 体`；实验 1.3 对号入座 |
| RV 语义 | unset=list 强一致；`rv=0`=本地缓存快读；`rv=特定值+Exact`=快照；watch 续传过旧=410 |
| WatchList | `?watch=true&sendInitialEvents=true&resourceVersionMatch=NotOlderThan`（v1.34+ 默认启用） |
| 不用但重要 | `--etcd-compaction-interval=5m0s`（历史窗口）；`--request-timeout=1m0s`；`--min-request-timeout=1800` |
| GC | `--cascade=background/foreground/orphan`；finalizer 卡死先看 `kubectl get events -A` 找 OwnerRef 问题 |
| APF | `kubectl get flowschemas`、`prioritylevelconfigurations`；指标 `apiserver_flowcontrol_*`；默认豁免 `exempt/probes` |
| 聚合层 | `kubectl get apiservice`；`FailedDiscoveryCheck` → 查 metrics-server Pod/证书/Endpoint/网络 |
| 审计 | `--audit-policy-file` 必须给；指标 `apiserver_audit_event_total` / `apiserver_audit_error_total`；实验 1.4 模板 |
| 健康 | `/livez`（活）、`/readyz?verbose`（就绪+依赖）、`/metrics`（指标源头） |

### 11.2 关键要点（背诵版）

1. K8s 所有控制循环=**list 快照 + watch 增量 + reconcile 写回**；掌握了 list-watch 就掌握了 80% 的控制器机制
2. **resourceVersion 是乐观锁 + watch 游标**：409 是锁冲突，410 是游标过期，5 分钟窗口由 etcd 压缩决定
3. spec/status 分离 = 期望与观测的合同；status 走 subresource，不动 generation
4. 认证给身份，鉴权给许可，准入在最后两相：先 Mutating 改对象，再 Validating 定最终形态；读操作完全绕过准入
5. v1.30 起 CEL ValidatingAdmissionPolicy GA、v1.36 起 Mutating GA——新策略优先写 CEL，不要轻易起一个会挂的 webhook
6. APF 把总并发按优先级分泳道：watch 受管、exec/logs 不受管、大 list 占多座；429 要带 `Retry-After` 指数退避
7. 聚合层是「第三方 API 住进 apiserver」：APIService + front-proxy CA + extension 反查 SAR；`FailedDiscoveryCheck` 照着 §6.3 查
8. finalizer 是「外部资源未清」的承诺，强删 = 假装已清 → 云资源泄漏；先修为什么清不掉
9. 审计不自动脱敏：secrets 只 Metadata；exec/log 是敏感操作，RequestResponse 记录全套
10. 一切 API 行为都可被观测：`--v=8` 看客户端视角、`/metrics` 看服务端视角、审计日志看历史视角

### 11.3 参考链接

| 主题 | 链接 |
|------|------|
| Kubernetes API 总览（discovery/OpenAPI v2/v3/版本策略） | https://kubernetes.io/docs/concepts/overview/kubernetes-api/ |
| API Concepts（list/watch/RV 语义/分块/WatchList/410/书签） | https://kubernetes.io/docs/reference/using-api/api-concepts/ |
| API deprecation policy（alpha/beta/GA 兼容承诺） | https://kubernetes.io/docs/reference/using-api/deprecation-policy/ |
| 已移除 API 迁移指南（按版本的年表） | https://kubernetes.io/docs/reference/using-api/deprecation-guide/ |
| 认证（X.509/SA/OIDC/结构化认证配置） | https://kubernetes.io/docs/reference/access-authn-authz/authentication/ |
| 准入控制器全集 + v1.37 默认插件 | https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/ |
| ValidatingAdmissionPolicy（GA v1.30） | https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/ |
| MutatingAdmissionPolicy（GA v1.36） | https://kubernetes.io/docs/reference/access-authn-authz/mutating-admission-policy/ |
| APF 概念/配置/指标 | https://kubernetes.io/docs/concepts/cluster-administration/flow-control/ |
| APF bootstrap 默认对象源码（泳道 shares） | https://github.com/kubernetes/apiserver/blob/master/pkg/apis/flowcontrol/bootstrap/default.go |
| 垃圾回收（ownerReference/级联/finalizer） | https://kubernetes.io/docs/concepts/architecture/garbage-collection/ |
| 聚合层总览 | https://kubernetes.io/docs/concepts/extend-kubernetes/api-extension/apiserver-aggregation/ |
| 配置聚合层（front-proxy 信任链） | https://kubernetes.io/docs/tasks/extend-kubernetes/configure-aggregation-layer/ |
| 审计（策略/后端/默认参数） | https://kubernetes.io/docs/tasks/debug/debug-cluster/audit/ |
| kube-apiserver flag 全量参考（默认值来源） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-apiserver/ |
| feature gates 总表 | https://kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/ |
| kind 审计开启官方示例 | https://kind.sigs.k8s.io/docs/user/auditing/ |
| kubectl quick reference（--v 日志等级） | https://kubernetes.io/docs/reference/kubectl/quick-reference/ |

> 下一章预告：`K8s-调度器深入.md`——Scheduling Framework 的 18 个扩展点会大量使用本篇的 informer/watch 与 APF 概念。
