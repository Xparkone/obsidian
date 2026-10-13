# K8s 安全加固详解

> 精通路线第 5 章：4C 模型与攻击面地图、Pod Security Standards / PSA 实战、securityContext 最小权限字典、准入 webhook 开发、VAP/MAP(CEL) 原生策略、Gatekeeper vs Kyverno 选型、Secret 静态加密与 KMS/Vault/ESO、cosign 供应链、CIS 节点与控制面加固
> 创建时间：2026-10-13
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37），文中标注「v1.xx 起 Beta/GA」均取自官方文档、KEP 或上游源码，执行时仍以你本地集群版本为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，§2 认证/鉴权/准入两相与 §8 审计直接引用不重讲）、`K8s-存储深入.md`（第 4 章，fsGroup/selinux 挂载行为直接引用不重讲）。

---

## 零、本文定位与边界

「K8s 安全」不是一件事，是四层防御问题逐层叠加。CNCF 的 **4C 模型**把它拆干净（Cloud / Cluster / Container / Code）：

```
┌─────────────────────────────────────────────────────────────┐
│ Cloud   底座自身的可信：节点 OS/内核补丁、云账号、VPC、硬防火墙 │
│  ↑ 底座失守，上面所有 K8s 机制都是沙上之塔                     │
│ Cluster K8s 自身的可被攻击部件：apiserver/etcd/kubelet/审计/网络 │
│  ↑ 本章主战场（集群加固＝把控制面与数据面的弱点一个个掐掉）        │
│ Container Pod/容器运行时的攻击面：securityContext/PSA/userns/镜像 │
│  ↑ 本章主战场（工作负载加固）                                    │
│ Code    应用层：依赖扫描、SBOM、签名、流水线门禁                  │
│  ↑ 本章 §6 供应链把 Code↔Cluster 的缝堵上                      │
└─────────────────────────────────────────────────────────────┘
```

上一层的安全永远依赖下一层——云账号被拿走后，restricted 起步的 namespace 只是摆设；反过来 Node 被打穿时，攻击者拿到的是**该节点上所有 Pod 的凭据**。所以本章的组织方式不是「把机制罗列一遍」，而是按攻击面分治：工作负载面（§1 §2）、准入面（§3 §4）、数据面（§5）、供应链（§6）、控制面/节点面（§7），排雷清单（§8）与实验（§9）收尾。

### 0.1 三扇门回顾（引用第 1 章 §2，只点一句）

每个写请求过 apiserver 都要依次过三扇门：**认证（你是谁）→ 鉴权（你能干什么，RBAC）→ 准入（对象本身合不合法合不合规）**。第 1 章 §2.3 讲过准入的两相（Mutating 链先改对象，Validating 链后校验定型），本章不再复述；本章讲的是**你自己去当那个准入点**——用内置 PodSecurity、CEL 策略，或写一个外部 webhook。

### 0.2 攻击面地图（本章目录就是这张图的展开）

```
攻击面 1 控制面      apiserver（公开端口 6443、--anonymous-auth、profiling、
 │                    准入插件链、etcd 之间的 TLS）               → §7
 ├  控制面数据        etcd 里躺着的 Secret（base64 ≠ 加密）        → §5
攻击面 2 节点        kubelet(10250/10255)、SSH、containerd socket、
 │                    节点上的秘密文件                           → §7
攻击面 3 工作负载    Pod 用 root/privileged/hostNS 跑起来         → §1 §2
 │                    PSA/securityContext/userns 逐个掐
攻击面 4 准入与控制  webhook/策略引擎本身成为新攻击面（锁死、超时、
 │                    默认 fail-close）                         → §3 §4
攻击面 5 供应链      镜像从哪来、被谁签过、SBOM 里有什么           → §6
攻击面 6 数据平面    Pod↔Pod 谁跟谁说话（NetworkPolicy，已见第 3 章）│ 不复述
```

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `安全/RBAC详解.md` | RBAC 模型与语法（三扇门第二扇） | 只在 §0/各章引用一句，不讲 Role/RoleBinding 语法 |
| `K8s-API机制深入.md`（第 1 章 §2） | 认证插件/鉴权模式/准入两相/APF 与 `enable-admission-plugins` 默认列表 | 只讲 webhook 的开发、证书链、生产故障域与 CEL 策略引擎——**不重述两相协议与请求链路**；webhook 与 APF 的联动只引一句指向第 1 章 §5 |
| `K8s-API机制深入.md`（第 1 章 §8） | 审计策略全篇（record levels、event metadata、sink 后端） | 本文只在「PSA audit 模式产物去哪看」「CEL validationActions: Audit」「webhook patch 审计注解」里引用结论，不重开审计章节 |
| `K8s-资源全览.md`（§5.4/§5.5） | PSA 标签与 securityContext 的 YAML 使用层写法 | 只讲三档标准的字段级差异与每个字段背后的攻击面语図 |
| `K8s-网络原理详解.md`（第 3 章） | NetworkPolicy 加固 | 数据平面网络策略不复述 |
| `CI-CD/Argo-CD-部署与使用详解.md` | GitOps 工作流 | ESO 与 GitOps 的衔接只在 §5.5 一句引用 |

> ❗ **版本标注约定**：文中形如「v1.36 起 GA」「v1.30 起 Beta」的说法均已对照官方 docs、KEP（kubernetes/enhancements 对应目录）或 k/kubernetes master `pkg/features/kube_features.go` 中的版本注释核实；
> 策略类第三方项目（Gatekeeper/Kyverno/cosign/ESO/kube-bench等）版本以 2026-10 的 upstream release 为准，落地前用文末 §10.3 的链接再确认一次。

---

## 一、Pod Security Standards 与 PSA 实战

Pod Security Standards（PSS，上层标准）与 Pod Security Admission（PSA，内置准入插件）是一体两面：PSS 定义**三档**标准，PSA 是apiserver 里按 namespace 标签执行标准的内置控制（**PodSecurity 准入插件，v1.23 Beta 默认开 → v1.25 GA**，第 1 章 §2.3 插件表里有它）。

### 1.1 三档标准的差异（逐档批判读）

| 控制面 | privileged | baseline | restricted |
|--------|-----------|----------|------------|
| hostProcess / hostNetwork / hostPID / hostIPC | 放行 | **禁**（hostNetwork/IPC/PID 必须为 false；hostProcess 必须 nil/false） | 禁（同上，且 restricted 合并了 baseline 全部禁区） |
| `privileged: true` | 放行 | **禁** | 禁 |
| capabilities.add | 放行 | 只允许白名单（NET_BIND_SERVICE、SYS_CHROOT 等 12 个） | **必须先 drop ALL，只允许 add 回 NET_BIND_SERVICE** |
| hostPath 卷 | 放行 | **禁** | 禁 |
| hostPort | 放行 | 默禁（内置 PSA 只能判「0 或未写」——白名单要策略引擎） | 禁（同上） |
| volume 类型 | 不限 | 不限 | **白名单**：configMap/downwardAPI/emptyDir/ephemeral/PVC/projected/secret/csi（hostPath、hostAlias 之类**全部禁**） |
| `allowPrivilegeEscalation` | 不限 | 不限 | **必须 false** |
| runAsNonRoot | 不限 | 不限 | **必须 true**（Pod 级或每个容器级） |
| runAsUser | 不限 | 不限 | 不能是 **0**（v1.23+ 起生效的控制） |
| seccompProfile | 不限 | 不许显式写 `Unconfined` | **必须显式写** RuntimeDefault 或 Localhost；不许留空 |
| procMount | 不限 | 只能是 Default/Unconfined……**禁止 Unmasked**（默认 user namespaces 集群里才例外，§2.8） | 同 baseline |
| sysctls | 不限 | 只允许 safe 子集（默认下 net.ipv4.ping_group_range 等几项） | 同 baseline |
| AppArmor / SELinux | 不限 | AppArmor 不许 Unconfined；SELinux type 白名单 container_t 一类 | 同 baseline（见 PSS 页细节） |

两档之外的**细节决定**：baseline 是「防已知提权套路」，不要求你写 securityContext——**一个完全裸 Pod 也是 baseline 合规的**；restricted 是「主动收敛」，每个容器都必须显式写 runAsNonRoot/seccomp/allowPrivilegeEscalation/capabilities 四个意识值。这是生产上「大庸应用挂不出来」的来源（§8.1）。

### 1.2 三种模式与 namespace 标签的精确语义

每个 ns 五种标签（mode 三种 + 各 mode 的 pinned version）：

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: staging
  labels:
    pod-security.kubernetes.io/enforce: restricted        # 违反 → Pod 创建被拒
    pod-security.kubernetes.io/enforce-version: "v1.37"   # 钉死在集群升级前的规则集
    pod-security.kubernetes.io/audit: baseline            # 违反 → 写进审计日志（第 1 章 §8）
    pod-security.kubernetes.io/audit-version: latest
    pod-security.kubernetes.io/warn: baseline             # 违反 → kubectl 警告头
    pod-security.kubernetes.io/warn-version: latest
```

机制要点（逐点核对官方 PSA 页）：

- **enforce 只作用于 Pod 对象**，不作用于 Deployment/Job 等工作负载资源；**audit 与 warn 对工作负载资源也会评估**（让你在模板面提前看到「这套模板进集群会怎样」）。
- 三种模式可独立叠加、独立 pin version——「**audit/warn 比 enforce 严一档**」是经典落地姿势：restricted 先只审计不强制，先把隐患扒出来，评估后再收紧 enforce。
- pinned version 的语义：`latest` 跟随集群升级的 PSS 规则集变化——升级后 audit/warn 可能突然多出新报警；**生产上 enforce 建议钉死具体版本**，评审完新规则集再跟进。
- 更新 Pod 的 `spec.activeDeadlineSeconds` 与 `spec.tolerations` 两个字段不受策略限制（官方例外：容忍性和截止时间允许后改），方便运维救急而不用临时降标。

**为什么这么设计**：为什么只有三档而不是开放策略语言？因为 PSS 被刻意设计成「**全 K8s 一线可比的最低语言**」——三档往后走只可加严，厂商、benchmark、策略引擎可以对齐这三档出报告和规则包（PSS 页官方链接了 Kubewarden/Kyverno/Gatekeeper 三个 PSS 落地替代品）。控件之外的需求（镜像白名单、强制 label、按团队豁免）刻意不进 PSS——那是策略引擎的地盘（§3/§4）。
PSP（PodSecurityPolicy）是它的前任：一套完整 RBAC+对象的策略模型，但对象级粒度复杂到绝大多数集群都用错。PSP 在 v1.21 标记废弃、**v1.25 移除**，继任者就是这个按 ns 打标签、用三档内置标准的 PSA（`K8s-资源全览.md` §5.4 有一句过渡提示，API 层面用法就不复述了）。

### 1.3 exemptions 三类（usernames / runtimeClasses / namespaces）

内置 PSA 支持 AdmissionConfiguration 级豁免：

```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: AdmissionConfiguration
plugins:
- name: PodSecurity
  configuration:
    apiVersion: pod-security.admission.config.k8s.io/v1
    kind: PodSecurityConfiguration
    defaults:
      enforce: "baseline"
      enforce-version: "latest"
    exemptions:
      usernames: [ "alice@example.com" ]            # 按认证/冒用用户名
      runtimeClasses: [ "kata" ]                    # 沙箱运行时（gVisor/Kata 天然隔离更高，可豁免）
      namespaces: [ "kube-system" ]                 # 系统 ns
```

注意事项（逐条核对官方）：

- **usernames 豁免只看认证/冒用身份**——用户**直接建 Pod** 才生效；Pod 由 Deployment/Job 控制器代为创建时，创建者已经变成了控制器的 SA（如 `system:serviceaccount:kube-system:replicaset-controller`），豁免用户名拦不住。**官方原话警告：千万别豁免控制器的 SA——等效于豁免全集群任何能建工作负载的用户**。
- 豁免是**整块跳过 PSA 的全部三件事**（enforce/audit/warn 一并退去），不是「放行但审计」——想要「运行时类豁免对外放开但对其他用户保留 audit」，得靠策略引擎或审计日志补一条外部视角。
- namespaces 豁免对「系统 ns 天然需要宿主权限」最实用——kube-system 里特权 Pod 是日常，这也是「除 kube-system 等系统 ns 外，其他 ns 至少 baseline」的推荐读法。

### 1.4 PSA 的三个局限（=策略引擎的存在理由）

① **namespace 粒度太粗**：同 ns 里做不到 A 应用松一点、B 应用严一点。
② **只会拒绝，不会 mutate**：PSA 不替你补字段——「要求 nonroot」跟「替你把 securityContext 填上」是两回事（后者是 MutatingAdmissionPolicy / Kyverno 的活）。
③ **规则集钉死在 PSS**：「镜像必须走公司仓库」「Deployment 必须有 requests」这类组织自定义规则，PSA 管不着。

**落地路径（生产升级四步走，全程避开 enforce 雷区）**：

```bash
# step 1：先上 audit/warn 看现状 —— 不写 enforce
kubectl label ns prod pod-security.kubernetes.io/audit=baseline \
  pod-security.kubernetes.io/audit-version=v1.37 \
  pod-security.kubernetes.io/warn=baseline --overwrite

# step 2：在审计日志里找违规（violation 以 audit annotation
#        "pod-security.kubernetes.io/audit-violations" 记录进审计事件，送到第 1 章 §8 配的 sink）
kubectl logs -n kube-system kube-apiserver-... 2>/dev/null | grep -i 'audit-violations' | head -5

# step 3：发布前用 server dry-run 过一遍「上了 enforce 后这套模板还起得来吗」
kubectl create deploy probe -n prod --image=nginx --dry-run=server 2>&1 | tail -3

# step 4：钉死版本上 enforce —— 从 baseline 起，不要上来就 restricted
kubectl label ns prod pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/enforce-version=v1.37 --overwrite
```

> ❗ 实践约束：**restricted 起步几乎必然炸存量**（裸 Pod 不满足「必须显式写 runAsNonRoot / seccomp / allowPrivilegeEscalation=false / drop ALL」四件套）——enforce 从 privileged→baseline→restricted 逐档灰度，每档至少跑过一轮业务发版周期。
> 指标面：apiserver 自带 `pod_security_evaluations_total{mode, operation_decision}` / `pod_security_exemptions_total` / `pod_security_errors_total`（监控告警的起点是「豁免量不动但违例持续爆发」，见 §8.2）。
