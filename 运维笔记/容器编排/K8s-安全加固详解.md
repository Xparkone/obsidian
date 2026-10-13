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
┌──────────────────────────────────────────────────────────────┐
│ Cloud    底座自身可信：节点 OS/内核补丁、云账号、VPC、防火墙      │
│ Cluster  K8s 自身攻击面：apiserver/etcd/kubelet/审计/网络      │
│ Container Pod/运行时攻击面：securityContext/PSA/userns/镜像    │
│ Code     应用层：依赖扫描、SBOM、签名、流水线门禁               │
└──────────────────────────────────────────────────────────────┘
上一层的安全永远依赖下一层——云账号被拿走后，restricted 起步的
namespace 只是摆设；Node 被打穿时，攻击者拿到的是该节点所有 Pod 的凭据。
```

所以本章的组织方式不是「把机制罗列一遍」，而是按攻击面分治：工作负载面（§1 §2）、准入面（§3 §4）、数据面（§5）、供应链（§6）、控制面/节点面（§7），排雷清单（§8）与实验（§9）收尾。

**三扇门回顾（引用第 1 章 §2，只点一句）**：每个写请求过 apiserver 都要依次过三扇门——**认证（你是谁）→ 鉴权（你能干什么，RBAC）→ 准入（对象本身合不合法合不合规）**。第 1 章 §2.3 讲过准入的两相（Mutating 链先改对象，Validating 链后校验定型），本章不复述；本章讲的是**你自己去当那个准入点**——用内置 PodSecurity、CEL 策略，或写一个外部 webhook。

### 0.1 攻击面地图（本章目录就是这张图的展开）

```
攻击面 1 控制面   apiserver（6443、--anonymous-auth、profiling、准入插件链）→ §7
 ├ 控制面数据     etcd 里躺着的 Secret（base64 ≠ 加密）                      → §5
攻击面 2 节点     kubelet(10250/10255)、containerd socket、节点秘密文件      → §7
攻击面 3 工作负载 Pod root/privileged/hostNS：PSA/securityContext/userns 掐掉 → §1 §2
攻击面 4 准入面   webhook/策略引擎自身成短板（锁死、超时、默认 fail-close）    → §3 §4
攻击面 5 供应链   镜像从哪来、被谁签过、SBOM 里有什么                         → §6
攻击面 6 数据平面 Pod↔Pod 通信（NetworkPolicy，已在第 3 章专篇）             → 不复述
```

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `安全/RBAC详解.md` | RBAC 模型与语法（三扇门第二扇） | 只在 §0/各章引用一句，不讲 Role/RoleBinding 语法 |
| `K8s-API机制深入.md`（第 1 章 §2/§5/§8） | 认证/鉴权/准入两相、APF、审计策略全篇 | 只讲 webhook 开发、证书链、生产故障域、CEL 策略引擎——不重述两相协议、APF 机制与审计内容（PSA audit 产物 / CEL validationActions: Audit / webhook patch 审计注解只引用其结论） |
| `K8s-资源全览.md`（§5.4/§5.5） | PSA 标签与 securityContext 的 YAML 使用层写法 | 只讲三档标准的字段级差异与每个字段背后的攻击面语义 |
| `K8s-网络原理详解.md`（第 3 章） | NetworkPolicy 加固 | 数据平面网络策略不复述 |
| `CI-CD/Argo-CD-部署与使用详解.md` | GitOps 工作流 | ESO 与 GitOps 的衔接只在 §5.5 一句引用 |

> ❗ **版本标注约定**：文中形如「v1.36 起 GA」「v1.30 起 Beta」的说法均已对照官方 docs、KEP（kubernetes/enhancements 对应目录）或 k/kubernetes master `pkg/features/kube_features.go` 中的版本注释核实；
> 策略类第三方项目（Gatekeeper/Kyverno/cosign/ESO/kube-bench等）版本以 2026-10 的 upstream release 为准，落地前用文末 §10.3 的链接再确认一次。

---

## 一、Pod Security Standards 与 PSA 实战

Pod Security Standards（PSS，上层标准）与 Pod Security Admission（PSA，内置准入插件）是一体两面：PSS 定义**三档**标准，PSA 是 apiserver 里按 namespace 标签执行标准的内置控制（**PodSecurity 准入插件，v1.23 Beta 默认开 → v1.25 GA**，第 1 章 §2.3 插件表里有它）。

### 1.1 三档标准的差异（逐档批判读）

| 控制面 | privileged | baseline | restricted |
|--------|-----------|----------|------------|
| hostProcess / hostNetwork / hostPID / hostIPC | 放行 | **禁**（hostNetwork/IPC/PID 必须为 false；hostProcess 必须 nil/false） | 禁（同上，且 restricted 合并了 baseline 全部禁区） |
| `privileged: true` | 放行 | **禁** | 禁 |
| capabilities.add | 放行 | 只允许 PSS 白名单（NET_BIND_SERVICE/SYS_CHROOT/KILL 等固定 13 项） | **必须先 drop ALL，只允许 add 回 NET_BIND_SERVICE** |
| hostPath 卷 / hostPort | 放行 | **禁**（hostPort 内置 PSA 只能判「0 或未写」——白名单要策略引擎） | 禁（同上） |
| volume 类型 | 不限 | 不限 | **白名单**：configMap/downwardAPI/emptyDir/ephemeral/PVC/projected/secret/csi（hostPath 等非白名单类型**全禁**） |
| `allowPrivilegeEscalation` | 不限 | 不限 | **必须 false** |
| runAsNonRoot | 不限 | 不限 | **必须 true**（Pod 级或每个容器级） |
| runAsUser | 不限 | 不限 | 不能是 **0**（v1.23+ 起生效的控制） |
| seccompProfile | 不限 | 不许显式写 `Unconfined` | **必须显式写** RuntimeDefault 或 Localhost；不许留空 |
| procMount | 不限 | 只能 Undefined/Default——**禁止 Unmasked**（开了 userns 的 Pod 在 baseline 档下反而放宽，§2.8） | 同 baseline（restricted 档即使用 userns 也仍必须默认 procMount） |
| sysctls | 不限 | 只允许 safe 子集（默认下 net.ipv4.ping_group_range 等几项） | 同 baseline |
| AppArmor / SELinux | 不限 | AppArmor 不许 Unconfined；SELinux type 白名单 container_t 一类 | 同 baseline（见 PSS 页细节） |

两档之外的**决策细节**：baseline 是「防已知提权套路」，不要求你写 securityContext——**一个完全裸 Pod 也是 baseline 合规的**；restricted 是「主动收敛」，每个容器都必须显式写 runAsNonRoot/seccomp/allowPrivilegeEscalation/capabilities 四项。这是生产上「存量应用起不来」事故的来源（§8.1）。

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
- pinned version 的语义：`latest` 跟随集群升级的 PSS 规则集变化——升级后 audit/warn 可能突然多出新报警；**生产上 enforce 建议钉死具体版本**，评审完新规则集再跟进。Pod 更新层面官方给了两个小例外：`activeDeadlineSeconds` 与 `tolerations` 修改不受策略限制，方便运维救急而不用临时降标。

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

# step 2：在审计日志找违规（violation 以 audit annotation
#        "pod-security.kubernetes.io/audit-violations" 记录；kubeadm 集群直看静态 Pod 日志）
kubectl logs -n kube-system kube-apiserver-... 2>/dev/null | grep -i 'audit-violations' | head -5

# step 3：发布前用 server dry-run 过一遍「上了 enforce 后这套模板还起得来吗」
kubectl create deploy probe -n prod --image=nginx --dry-run=server 2>&1 | tail -3

# step 4：钉死版本上 enforce —— 从 baseline 起，不要上来就 restricted
kubectl label ns prod pod-security.kubernetes.io/enforce=baseline \
  pod-security.kubernetes.io/enforce-version=v1.37 --overwrite
```

> ❗ 实践约束：**restricted 起步几乎必然炸存量**（裸 Pod 不满足「必须显式写 runAsNonRoot / seccomp / allowPrivilegeEscalation=false / drop ALL」四件套）——enforce 从 privileged→baseline→restricted 逐档灰度，每档至少跑过一轮业务发版周期。
> 指标面：apiserver 自带 `pod_security_evaluations_total{mode, operation_decision}` / `pod_security_exemptions_total` / `pod_security_errors_total`（监控告警的起点是「豁免量不动但违例持续爆发」，见 §8.2）。

---

## 二、Pod / Container 级最小权限字典（securityContext 进攻面解读）

PSS 是「站在 ns 门口」，securityContext 是「站在容器门口」。这一节按字段拆**每个字段关掉的是哪类攻击**——理解力来自 「如果我不写它，攻击者多了什么武器」。字段 YAML 基础写法见 `K8s-资源全览.md` §5.5，不复述。

### 2.1 字段—武器对照表

| securityContext 字段 | 不写它，攻击者拿到什么 | 写上它的最小代价 |
|---------------------|----------------------|----------------|
| `runAsNonRoot: true`（Pod 或容器级） | 容器内默认 UID 0 = 挂载点全权改写、`chown`、读 hostPath 卷上的秘密文件；从启动那刻起就向「宿主机 root」逼近一大步 | 镜像要能跑 nonroot（多数基础镜像默认 root 设计；DI 阶段优先换 nonroot base，比事后补 Pod 字段干净） |
| `runAsUser: <非 0 uid>` `runAsGroup` `fsGroup` | 容器以运行(undefined) uid 跑，卷上文件属主和宿主 uid 撞车时的越权读写；fsGroup 解决「非 root 用户对卷可写」的问题是它的配套，**fsGroup 触发整卷 chown/chmod 风暴的机制见第 4 章 §3.6**（fsGroupChangePolicy、VOLUME_MOUNT_GROUP） | runAsUser/fsGroup 都是**容器内视角**的 id；带 userns 的 Pod（§2.8）写卷同样只按容器内用户 |
| `allowPrivilegeEscalation: false` | **SUID 提权**（容器里自带 setuid 的 busybox `su`、`sudo` 或后续被打包的 setuid 二进制）——即便 runAsNonRoot 为 true，SUID 链路仍能把进程抬回 root | 几乎零代价，**所有 workload 都该写**；restricted 档强制 |
| `readOnlyRootFilesystem: true` | 越狱后就地写：改业务二进制、落挖矿脚本、写 ssh 私钥、删日志——容器的可写 layer 就是攻击者的工作台 | 应用要把日志/缓存写到 emptyDir/volumeMount；个别运行时（如 Python `__pycache__`、Node cache 目录）要逐个挂 tmp |
| `capabilities: {drop: [ALL], add: [按需]}` | 默认 root 容器集齐 14 个 capability（CHOWN/DAC_OVERRIDE/FOWNER/SETUID/SYS_CHROOT/KILL/MKNOD…）——DAC_OVERRIDE 等于文件权限当空气 | 排查成本在音视频/网络类容器（NET_BIND_SERVICE/KILL/SYS_NICE 常见） |
| `seccompProfile: {type: RuntimeDefault}` | **全 syscall 面**（300+ 可达）；RuntimeDefault 默认把 mount、reboot、kexec、加载内核模块等危险面锁掉 | 对绝大多数业务透明；极少数要走 io_uring 等新版 syscall 的应用需要 Localhost 自聊或 §8.4 的排除 |
| `appArmorProfile: {type: RuntimeDefault}`（v1.31 GA 字段化） | 容器直通宿主文件系统/网络/能力组合——RuntimeDefault 的 cri-containerd.apparmor.d 已能拦许多常用逃逸姿势 | 用 Localhost 自定义 profile 需要节点侧预载（生产手段：Security Profiles Operator） |
| `procMount: Default`（Unmasked 在 baseline 档被禁） | 不上 proc 统称的容器可以 mount /proc 看到内核级信息、调 `/proc/sys/*` 改 sysctl、甚至更极端读 /proc/kcore | 别碰这个字段；userns Pod 是官方认可的例外场景（§2.8） |
| `automountServiceAccountToken: false`（Pod spec 级） | **SA token 默认挂进容器**，一个 RCE = 用该 SA 的 K8s API 权限继续横向 | 不要访问 K8s API 的应用零代价；要访问的显式开 true 并配最小 Role |
| `hostUsers: false`（v1.36 GA，§2.8） | 容器内 root = 宿主机 root（同一 UID 空间）——逃逸即满盘皆属 | 要求 Linux ≥6.3、containerd ≥2.0、runc ≥1.2（crun ≥1.9，荐 1.13+）；有 hostNS/volumeDevices/NFS 限制 |

### 2.2 runAsNonRoot / runAsUser / fsGroup：UID 空间怎么算

- **runAsNonRoot 是「启动时核验」的安全网**：kubelet 在启动容器时决定 UID——镜像没有声明 USER 时默认 UID 0，写了 runAsNonRoot 就直接**启动失败**（事件里报 `Error: container has runAsNonRoot and image will run as root`）。**要害：镜像 Dockerfile 里写 `USER appuser`（名字）仍可能被解析成 0——kubelet 对非数值 USER 只能按镜像里的 passwd 推断；工程上写数值 `USER 10001`**。restricted 档的合规姿势 = **镜像里数值 UID + Pod 里写 runAsNonRoot: true**，两个都要，一个防逃逸（镜像立约），一个防回退（PSA 拦截时拒绝）。
- **fsGroup 只动「卷」不动 rootfs**：它决定对卷属主/可写性；**十万级文件的卷配合 `K8s-存储深入.md` §3.6 的 OnRootMismatch / VOLUME_MOUNT_GROUP**——把 Pod 启动耗时从分钟级砍到秒级。runAsGroup 使用面窄，通常与 fsGroup 一起定卷权限。注意：runAsUser/runAsGroup 指向的用户若镜像里没有对应 /etc/passwd 条目，容器启动会失败——用初始化脚本兜。

### 2.3 allowPrivilegeEscalation：no_new_privs 的容器间翻译

`allowPrivilegeEscalation: false` 落地的是内核 flag **no_new_privs**——「这个进程及其子孙不能获得比启动时更高的权限」。一来封 SUID 类提权（容器里自带 setuid 的 busybox `su`、`sudo`、apt 装进来的巨多 setuid 二进制）；二来封 runtime 借 exec 切换用户身份的旁路。它对合法业务流程基本不可见——受限的少数场景是包管理升级（容器里 apt/dnf 需要 suid 或特权升级）与 setcap 标记的二进制。**代价近零，推荐进模板默认值**。

### 2.4 readOnlyRootFilesystem：启动时 vs 运行时

开启后根文件系统**只读**，但应用会失败的地方不少：logging 库写临时目录、Java agent 落 dump、Python `__pycache__`、Node `node_modules/.cache`。摆放姿势：把这些目录逐个以 emptyDir（`medium: Memory` 可上 tmpfs）挂回去——`/tmp`、`/var/run` 是经典样板，`volumeMounts` 与 `volumes` 各加两行即解；`/proc` 本身的默认屏蔽则由 procMount 那一列管（§2.1 表）。

### 2.5 capabilities：五条实战纪律

- **drop ALL + add NET_BIND_SERVICE**：覆盖 95% 业务容器；`NET_BIND_SERVICE` 只用来听 1024 以下端口。
- **SYS_ADMIN** 是「能力里的 root」——社区共识与 privileged 等效，任何策略都应当禁；**SYS_PTRACE** 让进程读其他容器内存（gdb/dump 任意进程）；**NET_ADMIN** 让容器改宿主 iptables/路由；**DAC_OVERRIDE** 让 root 直接绕过文件权限。
- seccomp 与 capabilities 互补：seccomp 锁「能调哪些 syscall」，capabilities 锁「能调出什么特权动作」——**两者都设才是完整姿态**。
- PSA restricted 档的内置姿势就是这个：**强制 drop ALL + 只允许加回 NET_BIND_SERVICE**。

### 2.6 seccompProfile：注解时代 → 字段化

老注解形态：`seccomp.security.alpha.kubernetes.io/pod: runtime/default` / `container.seccomp.security.alpha.kubernetes.io/<name>`（v1.19 起标注 deprecated，PSA 识别它们只是为了兼容）。**字段化（seccompProfile 字段，v1.19 起 Stable）**：

```yaml
securityContext:
  seccompProfile:
    type: RuntimeDefault         # | Localhost | Unconfined
    # localhostProfile: profiles/custom.json   # type=Localhost 时必写
```

注意：

- **kubelet 的 `seccompDefault` 默认 false**（KubeletConfiguration v1beta1 原文）——**「kubelet 默认给全部 workload 上 RuntimeDefault」并不是默认行为**；只能在 kubelet config 里显式开 `seccompDefault: true`（gate 已 GA，非实验项）。集群有没有开它，直接决定了审计「裸容器默认案底」时能不能放心。
- Localhost 需要把 profile 预先放节点 `/var/lib/kubelet/seccomp/profiles/`（或 SPO=Security Profiles Operator 的 CRD 分发——推荐用于多节点集群）。

### 2.7 AppArmor：v1.31 GA，注解→`appArmorProfile` 字段

```yaml
securityContext:
  appArmorProfile:
    type: RuntimeDefault       # | Localhost | Unconfined
    # localhostProfile: k8s-apparmor-example-deny-write   # Localhost 时必写，需要节点上已加载
```

- 可 Pod 级或容器级，容器级覆盖；kubelet 会先用 `/sys/module/apparmor/parameters/enabled` 校验宿主 AppArmor 已开，**Localhost profile 必须已经加载进内核**（没加载的 Pod 被拒于启动时——事件里有 `apparmor profile not found`）。
- 老注解（`container.apparmor.security.beta.kubernetes.io/*`）与字段并存时字段优先——PSA 例外清单里也专门提了 seccomp/AppArmor 注解**保留着更新则仍受 PSS 校验**（v1.37 仍允许注解形式存在以兼容，推荐迁移成字段）。

### 2.8 User Namespaces（v1.25 α → v1.30 β → v1.33 β 默认开 → **v1.36 GA 锁定**，不可关）

如果说 securityContext 是「容器自我节制」，User Namespaces（userns）是「**内核维度的强隔离**」：容器里的 root（UID 0）被映射到宿主机上的一个**非特权高位 UID**。

```yaml
spec:
  hostUsers: false      # opt-in；宿主机上以 e.g. UID 989855744 之类的非零运行
```

机制要点（逐条核对官方 userns 页 + KEP-127 源码注释）：

- **基线版本轨迹**：`UserNamespacesSupport` gate 的注释——v1.25 Alpha，v1.30 Beta（默认关），**v1.33 Beta 默认开**，**v1.36 GA 锁定默认开**（gate 已锁，应视为不可关的行为；计划在 v1.39 删除）。
- **为什么这么设计**：容器逃逸事故的共同根源是「容器 UID 和宿主机 UID 同一个空间」——userns 让**容器内 root 在宿主机上只是无名之辈**；已知若干 HIGH/CRITICAL 级 CVE 在开了 userns 后「不可利用」。`CAP_SYS_ADMIN`/`CAP_SYS_MODULE` 等只对 userns 内有效，离开名字空间无效。
- **kubelet 侧配置**：`/etc/subuid` 与 `/etc/subgid`（要给 `kubelet` 用户分配 UID 区间），每 Pod 默认分配 **65536** 个 ID；v1.33 起 KubeletConfiguration `userNamespaces.idsPerPod` 可调（必须 65536 的倍数）。
- **文件系统要求**：**Linux ≥ 6.3**——tmpfs 在这个版本起支持 idmap mount（ConfigMap/Secret/SA token 都挂 tmpfs）；pod 内所有卷文件系统都要支持 idmap。**NFS 卷不行**（上游内核还不支持 idmap）。
- **运行时要求**：containerd ≥ 2.0、CRI-O ≥ 1.25、runc ≥ 1.2 或 crun ≥ 1.9（**推荐 crun 1.13+**）。
- **PSA 联动（最被低估的收益）**：开了 userns 的 Pod，`runAsNonRoot` / `runAsUser` 约束**被 PSS/PSA 自动放宽**（官方原话级：root in userns 永远映射到宿主机非特权用户，不构成提权风险）；**baseline 档下 procMount 也从「必须 Default」放宽**（restricted 档仍要求默认 procMount）——这是 userns 集群里写 YAML 的真正差异化。
- **硬限制与观察**：不能同时开 `hostNetwork/hostIPC/hostPID`，不能用裸块 volumeDevices；**卷的属主语义是容器内用户**（与非 userns Pod 共享卷要对齐容器内用户，fsGroup 同思路）；kubelet 暴露 `started_user_namespaced_pods_total` / `started_user_namespaced_pods_errors_total` 两计数。

**决策一句话**：集群 ≥ v1.36 且节点内核 ≥ 6.3（Ubuntu 24.04 / RHEL 9.4 / Flatcar 近期镜像都满足）的话，给负载加 `hostUsers: false` 是**零业务侵入、收益最大**的一笔（对照：`runAsNonRoot: true` 需要镜像改造，userns 不用）。

---

## 三、准入 webhook 开发与生产实践

PSA 管不了「强制 requests」「镜像白名单」，策略引擎又要装一套东西——有时**自己写一个 30 行的 webhook 反而最轻**。这一节把开发、证书、部署、故障域全走完。准入两相与「mutating 先于 validating」的协议细节见第 1 章 §2.3，不重述。

### 3.1 两种配置对象的逐字段（核对官方 dynamic-admission 页）

ValidatingWebhookConfiguration 与 MutatingWebhookConfiguration 同构（`admissionregistration.k8s.io/v1`），字段差异只在 mutating 多了 `reinvocationPolicy`：

| 字段 | 语义（已核对） | 坑位 |
|------|---------------|------|
| `webhooks[].name` | 域名格式唯一标识（`pod-policy.example.com`） | mutating webhook **按 name 字典序串行调用**，多个互改的 webhook 共存时顺序敏感 |
| `rules[]` | `apiGroups/apiVersions/operations/resources` + `scope`（`Namespaced`/`Cluster`/`*`） | `scope` 不写 = 都算；resources 支持 `pods/exec` 子资源式粒度 |
| `namespaceSelector` | 按 **ns 标签**过滤（ns 对象本身的请求不受影响） | **排除 `kube-system` 与 webhook 自己所在 ns** 是生产纪律（§8.3 事故复盘主角） |
| `objectSelector` | 按目标对象标签过滤 | 见名救：对 ns 对象不起作用 |
| `matchConditions` | CEL 过滤条件（见第 1 章同语法） | 比 selector 更强的过滤，如按 userInfo.groups 排除 `system:nodes` |
| `failurePolicy` | `Fail`（默认，fail-close）/ `Ignore` | **webhook 挂 + Fail = 匹配范围内一切写请求全拒**（§8.3） |
| `timeoutSeconds` | 1–30 秒，v1 默认 **10** | 超时计为「调用错误」，同样受 failurePolicy 支配；APF 占用见下方 |
| `sideEffects` | **必填**，只能 `None` 或 `NoneOnDryRun` | 有副作用（外部发消息/写库）必须 NoneOnDryRun——否则 dry-run 请求会被拒 |
| `admissionReviewVersions` | **必填**，如 `["v1"]` | 写服务支持的 AdmissionReview 版本 |
| `reinvocationPolicy` | 仅 mutating：`Never`（默认）/ `IfNeeded` | 后面的 webhook 又改了对象时，前面的可再调一次；多注入型 webhook（Istio + Vault）共存必看 |
| `clientConfig` | `service{name,namespace,path,port}` 或 `url` + `caBundle` | caBundle 是**验证 webhook 服务证书**的 CA（PEM base64）——证书轮换后别忘了同步它（§8.4） |

### 3.2 AdmissionReview 协议骨架

```json
// 请求（apiserver → webhook）
{ "apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview",
  "request": { "uid": "705ab4f5-...", "operation": "CREATE",
    "kind": {"group":"apps","version":"v1","kind":"Deployment"},
    "resource": {"group":"apps","version":"v1","resource":"deployments"},
    "name": "my-deploy", "namespace": "default", "userInfo": {...},
    "object": { /* Deployment 全量 */ }, "oldObject": null, "dryRun": false } }
// 响应（允许）
{"apiVersion":"admission.k8s.io/v1","kind":"AdmissionReview",
 "response":{"uid":"705ab4f5-...","allowed":true}}
// 响应（拒绝）
{"response":{"uid":"...","allowed":false,
  "status":{"code":403,"message":"container \"app\" has no resources.requests"}}}
// 响应（mutating 改写）：patch = base64(JSONPatch 数组)，patchType 唯一合法值 JSONPatch
{"response":{"uid":"...","allowed":true, "patchType":"JSONPatch",
  "patch":"W3sib3AiOiJhZGQiLCJwYXRoIjoiL21ldGFkYXRhL2xhYmVscyIsInZhbHVlIjp7ImFwcCI6IngifV0="}}
```

mutating 的产出会被**写进审计注解**（`patch.webhook.admission.k8s.io/round_X_index_Y`），第 1 章 §8 的审计查询里可以直接 grep 出「这个对象被哪个 webhook 加了什么」——生产排障时比 `kubectl get` 齐全。

### 3.3 最小可用 webhook server（Go，stdlib-only，`go build` 实测过）

拦截「Deployment 任一容器没写 `resources.requests`」——与下面 §3.6 的 CEL 版本是**同一条规则**，便于对照：

```go
package main

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
)

// AdmissionReview 最小结构（admission.k8s.io/v1 协议，只留实战用到的字段）
type AdmissionReview struct {
	TypeMeta `json:",inline"`
	Request  *AdmissionRequest  `json:"request,omitempty"`
	Response *AdmissionResponse `json:"response,omitempty"`
}

type TypeMeta struct {
	Kind       string `json:"kind,omitempty"`
	APIVersion string `json:"apiVersion,omitempty"`
}

type AdmissionRequest struct {
	UID       string `json:"uid"`
	Namespace string `json:"namespace"`
	Name      string `json:"name"`
	Object    struct {
		Spec struct {
			Template struct {
				Spec struct {
					Containers []struct {
						Name      string `json:"name"`
						Resources struct {
							Requests map[string]string `json:"requests"`
						} `json:"resources"`
					} `json:"containers"`
				} `json:"spec"`
			} `json:"template"`
		} `json:"spec"`
	} `json:"object"`
}

type AdmissionResponse struct {
	UID     string  `json:"uid"`
	Allowed bool    `json:"allowed"`
	Status  *Status `json:"status,omitempty"`
}

type Status struct {
	Code    int32  `json:"code,omitempty"`
	Message string `json:"message,omitempty"`
}

// validateDeployment：拦截「任一容器没写 resources.requests」的 Deployment
func validateDeployment(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "read body: "+err.Error(), http.StatusBadRequest)
		return
	}
	var review AdmissionReview
	if err := json.Unmarshal(body, &review); err != nil || review.Request == nil {
		http.Error(w, "invalid AdmissionReview", http.StatusBadRequest)
		return
	}

	resp := &AdmissionResponse{UID: review.Request.UID, Allowed: true}
	for _, c := range review.Request.Object.Spec.Template.Spec.Containers {
		if len(c.Resources.Requests) == 0 {
			resp.Allowed = false
			resp.Status = &Status{
				Code:    403,
				Message: fmt.Sprintf("container %q in ns %s/%s has no resources.requests", c.Name, review.Request.Namespace, review.Request.Name),
			}
			break
		}
	}

	out := AdmissionReview{
		TypeMeta: TypeMeta{Kind: "AdmissionReview", APIVersion: "admission.k8s.io/v1"},
		Response: resp,
	}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(out)
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/validate", validateDeployment)

	srv := &http.Server{
		Addr:      ":9443",
		Handler:   mux,
		TLSConfig: &tls.Config{MinVersion: tls.VersionTLS12},
	}
	log.Print("admission webhook listening on :9443")
	// tls.crt/tls.key 来自挂载的 Secret（§9.3 走证书流程生成）
	log.Fatal(srv.ListenAndServeTLS("/etc/webhook/certs/tls.crt", "/etc/webhook/certs/tls.key"))
}
```

> ✅ 本代码已用 `go1.24` 过 `go vet` + `go build`，并用真实 AdmissionReview 报文 curl 过：缺 requests 的返回 `{"allowed":false,...}`，齐全的返回 `{"allowed":true}`。

### 3.4 证书链：CSR API 的 signerName 语义（勘误版：kube-apiserver-client **不能**签 server 证书）

「webhook 服务证书怎么来」通常有三条路：**cert-manager（生产推荐）**、**openssl 自建 CA + caBundle**、**走 certificates.k8s.io CSR API 让控制面签**。第三条路有一个天然的坑：

**内建 signer 的 usage 契约（官方 CSR 页逐条核对 + kcm signer.go 源码）**：

| signerName | 签什么 | 必须 usages | 自动批准？ |
|-----------|--------|-------------|-----------|
| `kubernetes.io/kube-apiserver-client` | apiserver 认的**客户端**证书 | 只能 `[digital signature, key encipherment, client auth]`——**必须含 client auth，不允许任何其他 usage** | 永不自动，`kubectl certificate approve` 人工 |
| `kubernetes.io/kube-apiserver-client-kubelet` | kubelet → apiserver 客户端 | client auth 系；CN/`system:nodes` 受限 | 可自动（kcm 内建 approver） |
| `kubernetes.io/kubelet-serving` | kubelet 服务证书 | server auth 系；CN 必须 `system:node:<name>` | 永不自动 |
| `kubernetes.io/kube-apiserver-serving`（v1.27 α → v1.37 GA） | apiserver serving 证书 | server auth 系 | kcm 不签（管理员自理） |
| `kubernetes.io/legacy-unknown` | 无保证 | 无限制 | **certificates.k8s.io/v1 不允许再用** |

**核心结论**：「用 `kubernetes.io/kube-apiserver-client` 申请 **server 证书**」在 v1.37 会失败——kcm signer 的 `validAPIServerClientUsages` 对 server auth 直接判 `Failed`（`SignerValidationFailure: invalid usage for client certificate: server auth`）。这正是 §9.3 实验第一个「踩坑步骤」，**生产别学**；想要由控制面签 server 证书，正确做法是自定义 signer（如 `exp.example/webhook-serving`）+ 人工签名上传，把「CSR 是协议、签名者是插件」这个事实走通一遍。

### 3.5 生产贴面（故障域，比语法值钱）

- **failurePolicy 的真实风险**：`Fail` + webhook Pod 全挂 = `namespaceSelector` 匹配面内 CREATE/UPDATE 全瘫。案例级：webhook 匹配 `pods`，节点翻新时节点上**所有** DaemonSet Pod 与业务 Pod 都起不来（Cilium/CoreDNS 起不来 → 全体连不上的连环事故）。生产公式：**先用 Ignore + 告警观察 ≥ 两周，稳定后换 Fail 并同步收窄 rules**。
- **把自己/基础设施锁死**：webhook 服务本身的 Pod 如果被自己的 rules 匹配——挂了永远起不来（Kyverno 官方文档把「kyverno 命名空间必须被豁免」写成一级警告正是这个事故史）。纪律三件套：`namespaceSelector` 排除系统 ns 与 webhook 所在 ns；webhook 自身 Pod 打标签 `admission.webhook/ignore: "true"`，并在 selector 里 `NotIn` 排除该标签——「自己权威声明自己的豁免」是最稳的防线。
- **超时与 APF + 监控**：webhook 调用占用 apiserver 的 seat——第 1 章 §5 的 APF 分类排队会把它算进去，慢 webhook 会拖出相关业务泳道的延迟尖峰（建议 timeoutSeconds ≤ 5s，webhook 内部超时再小一档 fast-fail）。监控四件套：`apiserver_admission_webhook_admission_duration_seconds`（延迟）、`apiserver_admission_webhook_admission_step_error_count`、`apiserver_admission_webhook_rejection_count{error_type}`（calling_webhook_error / no_error + rejection_code）、审计注解 `patch.webhook.admission.k8s.io/round_X_index_Y`（mutating 可追溯改动，§3.2）。
- **v1.37 新增防线**：TokenReview/SubjectAccessReview/SelfSubject* 这批虚拟资源**默认不再进入 webhook**（第一节引的官方描述原文——防止 webhook 把 apiserver 自己的认证鉴权链撞死）。老集群升级上 v1.37 如果「有 webhook 匹配 `*`」需要 review：v1.37 之后对 tokenreviews 的 webhook 调用是不会发生的。
- **证书轮换**：替换 Secret 里的 tls.crt 只是第一步，**ValidatingWebhookConfiguration 里的 caBundle 必须同步更新**（否则 apiserver 验签失败 = webhook 变不可用的 = 又一场 failurePolicy 事故）（§8.4）。生产上要 cert-manager 的 `cert-manager.io/inject-ca-from` 这种自动同步器，而不是人肉 patch。

### 3.6 原生替代：CEL 策略（VAP v1.30 GA / MAP v1.36 GA 默认开）

> ❗ **版本纠正**：MutatingAdmissionPolicy 的 GA 版本以官方 docs 为准是 **v1.36（默认开）**，而不是 v1.35；它是 v1.30 首次以 Alpha 出现。VAP 是 v1.30 GA 无误。

**同一条规则的 CEL 版（对照 §3.3 的 Go 版）**：

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: require-resources-requests
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: ["apps"]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["deployments"]
      scope: "Namespaced"
  validations:
    - expression: >-
        object.spec.template.spec.containers.all(
          c, has(c.resources) && has(c.resources.requests) &&
             size(c.resources.requests) > 0)
      message: "every container must set resources.requests (cpu/memory)"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: require-resources-requests-binding
spec:
  policyName: require-resources-requests
  validationActions: [Audit]           # 先 Audit（写进审计日志），稳定后改 [Deny]
  matchResources:
    namespaceSelector:
      matchExpressions:
      - key: kubernetes.io/metadata.name
        operator: NotIn
        values: ["kube-system", "kyverno"]
```

**什么时候 CEL 搞不定、必须得外部 webhook**（官方定位一句话）：CEL 只看**请求对象 + namespaceObject + params + 静态 authorizer**——它看不到外部世界。**镜像验签要查 registry、跨对象引用一致性（A 对象的某字段必须等于 B 对象的）、调公司内部 CMDB/审批系统就要 webhook**（或策略引擎——它自己的 admission controller 本质就是预制的 webhook，§4）。

**MAP（CEL mutating）的一句话能力**：声明式地「给 Pod 加 sidecar」「给标签缺省值」，两种 patchType：`ApplyConfiguration`（SSA merge 语义，只能新增/覆盖元数据、容器、字段，**不能删**——官方明示不能改 atomic struct/map/array 防止误删）与 `JSONPatch`。对比 webhook mutate：无需 HTTPS 服务、不占 seat 的网络往返、CEL 求值成本在 apiserver 内部按 cost-limit 配额结算（KEP-3837 有估算）。

---

## 四、策略引擎选型：Gatekeeper(OPA) vs Kyverno vs 纯 CEL

PSA（§1）管「Pod 权属三档」，CEL（§3.6）管「字段级规则」——但两样都是「组织级策略不可计算」的退化：**要 mutate/generate、例外赦免、按 workflow 定向批量扫存量、复用开源策略库**的时候，策略引擎上场。

### 4.1 Gatekeeper（OPA 系；v3.23.1，本文写作时最新）

Gatekeeper = OPA（Open Policy Agent）+ K8s webhook 壳：**它本身就是一个 mutating + validating webhook**，逻辑宿主是 Kubernetes 里的一套 Deployment。策略对象两步型：

```yaml
# 第一步：ConstraintTemplate（Rego 逻辑 + 参数 schema）
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8srequiredlabels
spec:
  crd:
    spec:
      names: { kind: K8sRequiredLabels }
      validation:
        openAPIV3Schema:
          type: object
          properties: { labels: { type: array, items: { type: string } } }
  targets:
  - target: admission.k8s.gatekeeper.sh
    rego: |
      package k8srequiredlabels
      violation[{"msg": msg}] {
        missing := {l | l := input.parameters.labels[_];
                        not input.review.object.metadata.labels[l]}
        count(missing) > 0
        msg := sprintf("missing labels: %v", [missing])
      }
---
# 第二步：Constraint（模板实例化）
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: all-must-have-owner
spec:
  enforcementAction: deny            # 或 dryrun（=audit）
  match:
    kinds: [{ apiGroups: [""], kinds: ["Namespace"] }]
```

关键机制（都核对过 gatekeeper 官方文档）：

- **部署一条命令**：`kubectl apply -f https://raw.githubusercontent.com/open-policy-agent/gatekeeper/v3.23.1/deploy/gatekeeper.yaml`。
- **audit**：Gatekeeper 周期性地（默认 60s，`--audit-interval`）把集群**存量对象**对照 Constraints 跑一遍，违规落到 Constraint 的 `status.violations` 里——这跟 PSA 只拦准入时刻形成互补：存量违例也能看见。
- **性能陷阱**（生产调优最重头的地方）：所有 admission 调用都经过 Gatekeeper 的服务——**Rego 求值成本随对象大小线性上涨**；`pods/exec` 这类大对象与捕获面过宽的 Constraint，会让 admit 延迟从亚毫秒级涨到十毫秒级。调优顺序：① Constraint 只按需 match kinds；② 大对象用 `objectSelector/namespaceSelector` 收窄；③ non-webhook 化 Constraint 只在背景 audit 跑；④ Constraint 参数与库（library）复用以利用 OPA 缓存。
- **mutate**：Gatekeeper 也支持 Assign/AssignMetadata mutation（`mutations.gatekeeper.sh/v1`），但它本质上不是 mutate-first 产品——「按标签给 Pod 补 securityContext / sidecar」这类高度定制用途，多数团队还是选 Kyverno 或 MutatingAdmissionPolicy。

### 4.2 Kyverno（YAML 原生；v1.19.1，本文写作时最新）

Kyverno 是同一堆 webhook 背后的另一种产品定位：**策略直接写 YAML，不需要学 Rego**。

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationFailureAction: Enforce        # Enforce | Audit（先在 Audit 演练，再翻 Enforce）
  background: true                        # 存量也周期性跑（Output: PolicyReport CRD）
  rules:
  - name: require-not-latest
    match:
      any:
      - resources: { kinds: ["Pod"] }
    validate:
      message: "tag :latest is disallowed"
      pattern:
        spec:
          containers:
          - image: "!*:latest"
```

价值点（逐条核对官方）：

- **四种规则**：validate（本例）/ mutate（补 securityContext、加标签）/ generate（新 ns 自动生 NetworkPolicy、ResourceQuota）/ verifyImages（镜像验签，§6.2）；**generate 是 Kyverno 独有**——Gatekeeper 与 CEL 都没法「建一个新对象」。
- **PolicyException（kyverno.io/v2）**：稀有但清爽的「例外赦免」机制——把「我允许这个 Pod 破例」变成集群内对象（带审计），不像 PSS exemptions 那样写死配置文件里。新版本增推 CEL 化家族（`policies.kyverno.io/v1` 的 ValidatingPolicy/ImageValidatingPolicy 等，**Kyverno 1.13+ 起**，政策对齐 K8s 原生 CEL 的方向）。
- **部署与可用性裁量**（Helm 官方推荐；四件套 Deployment：admission/background/reports/cleanup controller）：
  ```bash
  helm repo add kyverno https://kyverno.github.io/kyverno/ && helm repo update
  helm install kyverno kyverno/kyverno -n kyverno --create-namespace
  ```
  默认 webhook fail-closed + 单副本——生产按官方建议 admissionController 调到 2-3 副本；chart 自带「用 `kubernetes.io/metadata.name` 豁免 kyverno ns 自己」，正是 §3.5 「webhook 不能把自己锁死」的预置解法。

### 4.3 决策树

```
要覆盖的规则纯度先看一遍：
│
├─ 规则只是「字段级 if/then」（requests/白名单 label/禁改 replica）？
│    └─ 是 → **CEL（VAP/MAP 原生）**：零部署、无外部依赖、不占 seat 网络往返
│
├─ 需要 mutate/generate（加 sidecar/补注解/新 ns 生 NetworkPolicy）？
│    └─ 是 → **Kyverno**：YAML 原生，PolicyException 例外机制完整
│
├─ 需要精细 matcher、通用许可语言、已有 OPA 资产（Rego 库/conftest CI 共用）？
│    └─ 是 → **Gatekeeper**：Rego 一套语言统一准入+CI 扫描
│
└─ 例外管理是否企业级（breakglass、限期、审计批）？
     └─ 是 → **Kyverno PolicyException**：例外即集群对象、可审计可限期；
             Gatekeeper 只有命名空间级豁免，弱于 Kyverno 的对象级例外
```

**为什么这么设计**：选型根本分歧不在功能、在**逻辑宿主的信任域**。CEL 跑在 apiserver 进程内——规则就是 API 对象，零网络依赖、零中间组件，但视窗只有请求对象 + namespaceObject + params；Gatekeeper/Kyverno 是集群里的一坨 Deployment——能查外部世界，代价是你要像对待一个「高权限 webhook 服务」那样经营它们的可用性（§3.5 的所有故障域全部适用）。组织成熟后常见混合态：**CEL 规则为底（便宜、首选） + 引擎为补（mutate/generate/例外）**。

### 4.4 一个「反模式」

把 PSA/CEL/引擎混用但口径分离——PSA 管一档（restricted），CEL 管 requests，Kyverno 管镜像白名单，但**三个都没把例外机制拉通**。事故史常见状况：应用队「我跟 PSA 豁免过了」，到 Kyverno 又被拦，根因是没人统一 exemptions——把例外规则**作为集群内对象**（AdmissionConfiguration 里的 PSS 不行时，用 Kyverno PolicyException 或 Gatekeeper Constraint 的 `exemptNamespaces`），形成一本账，而不是散落三处。

---

## 五、Secret 深加固

Secret 默认是 **base64 而不是加密**——`kubectl get secret -o yaml` 看到的内容与 etcd 里躺着的完全一样（明文）。要通过这个对象获得真正的机密性，需要三条柱：**etcd 静态加密**、**消费通道改造**、**外部密钥管理**。

### 5.1 三条泄露通道先认清

| 通道 | 威胁形状 | 对应防御 |
|------|---------|---------|
| **etcd 落盘**（控制面节点磁盘快照被拷） | 攻击者拿到 etcd 数据目录 = 全量 Secret 明文 | **EncryptionConfiguration**（§5.2）/ KMS（§5.3） |
| **K8s API**（RBAC） | 能 list/get secrets 的 SA 或用户 = 明文 | RBAC 最小化（`安全/RBAC详解.md`）+ 限制镜像/域读 Secret 的场景、对 Secret 的日常用只在 volume 通道挂（不 env 不 cat） |
| **Pod 消费**（env vs volume） | env 是把明文写进容器环境——crash dump/`/proc/1/environ`/日志删节常顺手暴露；volume 挂文件模式 tmpfs | **volume（tmpfs）优于 env**；securityContext 里更彻底的做法是「不放进 namespace 级 Secret，用注入驱动（Vault injector/ESO/CSI provider）」 |

### 5.2 EncryptionConfiguration（static key，aescbc/secretbox）+ KMS v2

**providers 速查**（全部核对官方 encrypt-data 页）：

| provider | 强度 | 建议 |
|----------|------|------|
| `identity` | 无（明文） | 迁移期做兜底读用 |
| `aescbc` | 弱（CBC padding-oracle 理论风险，官方明示 "weak，不推荐"） | 旧集群兼容 |
| `aesgcm` | 强但官方要求**每 200k 写次轮换一次同一 key** | 只在有自动轮换机制时使用 |
| `secretbox` | 强（XSalsa20+Poly1305）+ 快 | 不想上 KMS 时的推荐 |
| `kms` v1 / v2 | 最强（信封加密，多 key/KEK/DEK 分层） | 生产推荐；KMS v2 **GA v1.29**；KMS v1 **v1.28 起废弃、v1.29 起默认关**（`--feature-gates=KMSv1=true` 强制开） |

**完整应用流程（kubeadm 单控制面为例）**：

```bash
# ① 生成密钥（32 字节随机 → base64）
KEY=$(head -c 32 /dev/urandom | base64)

# ② 控制面写配置 /etc/kubernetes/enc/enc.yaml（权限 600 给跑 apiserver 的用户）
cat > /etc/kubernetes/enc/enc.yaml <<EOF
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: ["secrets"]
    providers:
      - secretbox:
          keys:
          - name: key1
            secret: ${KEY}
      - identity: {}      # 迁移期兜底：能读旧明文 Secret
EOF

# ③ kube-apiserver manifest 挂 --encryption-provider-config + hostPath（static pod 自动重载）
# ④ 验证：新建一条 Secret + etcdctl 直读看前缀
ETCDCTL_API=3 etcdctl \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  get /registry/secrets/default/secret1 | hexdump -C | head
#    期望前缀：k8s:enc:secretbox:v1:key1:...（aescbc 是 k8s:enc:aescbc:v1:key1:...）
# ⑤ 让存量 Secret 也重写成密文（核心命令：一次 read-modify-write 全部）
kubectl get secrets --all-namespaces -o json | kubectl replace -f -
# ⑥ 全部重写后才能把 identity 兜底撤掉（§8.5 的事故根因就是漏做 ⑤）
```

**加密语义剖开读**（解释「为什么轮换之后还是能读」）：

- **providers 有序**：第 1 个 provider 决定**写**用什么，列表里**所有** provider 都能**读**——这就是「加新 key 到尾部 → 然后把读到的东西用新 key 重写 → 移旧 key」的多步无停机轮换流程的依据。
- **KMS v2 的 key_id 轮换**：KEK 轮换后 KMS 插件的 Status 里 key_id 变了，api server 观察到后自动把 cache 里的 DEK seed 标记 stale——**不用重启 apiserver**；但节奏不是实时的（Status 轮询~1 分钟、故障期 10s、被动迁移窗口约 3+N+M 分钟）。
- **rotate 完整流程命令链**（四步，每步之间重启 apiserver 并验证）：
  ```bash
  # a. 新增 key2 进 providers（置于末尾），重启所有 apiserver
  # b. 把 key2 调到首位（新写入用 key2），重启所有 apiserver
  # c. kubectl get secrets --all-namespaces -o json | kubectl replace -f -   （重写存量）
  # d. etcdctl 抽查只剩 k8s:enc:secretbox:v1:key2，从列表移除 key1
  ```
- **自动重载 flag**：`--encryption-provider-config-automatic-reload=true`（默认关；打开后 apiserver **每分钟长轮询**配置文件变更——轮换重启步骤可以省了；指标 `apiserver_encryption_config_controller_automatic_reload_last_timestamp_seconds`）。
- **KMS v2 部署形态**：KMS provider 必须**跑在每个控制面节点**上（unix socket 直连 apiserver），socket 路径（e.g. `unix:///var/run/kmsplugin/socket.sock`）写进 EncryptionConfiguration。云厂商多给托管 hook（GKE/Azure/阿里的 KMS 集成都是同一系列）。

### 5.3 外部密钥两条主流路线

**HashiCorp Vault** 的两种注入形态对照：

| 维度 | vault-agent-injector（mutating webhook 注入 sidecar） | Vault CSI provider（secrets-store CSI driver） |
|------|-----------------------------------------------------|-----------------------------------------------|
| 机制 | Pod 提交时加 `vault.hashicorp.com/agent-inject: "true"`→ webhook 把 vault-agent sidecar 加进去 → 进程拉密钥写内存卷、续租轮换 | secrets-store.csi.k8s.io driver 按 SecretProviderClass 挂内容到 volume |
| 同步到 K8s Secret | 可选（agent-inject-secret 要 + `vault.hashicorp.com/agent-cache-enable`） | 可选 `secretObjects` 同步 K8s Secret 对象 |
| 运维侵入 | 改造 Pod spec（注解即可） | 只挂 CSI 驱动 + 写 SecretProviderClass |
| 轮换 | sidecar 模板定期重读 Vault（不重启 Pod） | 驱动轮询 volume 更新（可选 alpha 秘钥轮换） |
| 适用 | 已用 Vault / 要 Vault 的 lease、audit、revocation 体系 | 要求 Pod template 侵入最小 |

**ESO（External Secrets Operator，v2.12.0，本文写作时最新）**：**把「外部密钥仓库」与「K8s Secret」对接起来**——对象链三级：

```yaml
# ① SecretStore / ClusterSecretStore：连到 AWS SM/GCP SM/Vault/Azure KV 的认证与端点
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata: { name: aws-sm }
spec:
  provider:
    aws:
      service: SecretsManager
      region: cn-north-1
      auth: { jwt: { serviceAccountRef: { name: eso-sa, namespace: external-secrets } } }
---
# ② ExternalSecret：「把外部 secret 的哪几个 key 同步到哪个 K8s Secret」
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata: { name: db-creds, namespace: app }
spec:
  refreshInterval: 1h
  secretStoreRef: { name: aws-sm, kind: ClusterSecretStore }
  target: { name: db-creds-secret, creationPolicy: Owner }
  data:
  - secretKey: password
    remoteRef: { key: prod/db, property: password }
```

- ESO 的价值与 Vault injector 的场景不冲突——**ESO 把秘密留在「K8s Secret」生态**（reconciler 模式，应用零感知，回滚容易），injector 走「sidecar 注密」生态（应用侧须消费文件）。
- **与 GitOps 的关系一句**：`CI-CD/Argo-CD-部署与使用详解.md` 里 ArgoCD 管的全是**可入 git 的清单**——ESO 的 ExternalSecret 是纯 YAML，可以跟 app 清单一起入 git，真密钥留在 AWS SM 等外部仓库——这是「Secret 不提交库」的实现桥梁（同类形态还有 Sealed Secrets / SOPS＋KMS，走的是「把密文本身入 git」路线）。

**为什么这么设计**：三条路面（静态加密、注入、同步）对应不同信任边界——静态加密防「etcd 磁盘拿走」、注入防「Secret 对象进 API/etcd」、ESO 让密钥的生命周期**在外部 Vault 里统一**。生产组合最深的形态是：**所有三方都上了 + 强 RBAC + audit 审计异常 get/list secrets**（第 1 章 §8 审计策略可以在用 Secret 资源的 verb 打 Metadata）。

---

## 六、镜像与供应链安全

供应链这头，K8s 的拦截面一直在准入层——「这个镜像是谁签的」「这个镜像是不是我在 CI 里扫过的那份」。签名主角是 cosign，执行场是准入层（Kyverno/Gatekeeper）。

### 6.1 cosign：两套方案

**方案 A：keyless（Fulcio + Rekor，推荐云原生/CI 环境）**——构建时用 OIDC 身份短期证书签名，签名进 Rekor 公开透明度日志：

```bash
cosign sign --yes ghcr.io/org/app@sha256:abcd...
cosign verify ghcr.io/org/app@sha256:abcd... \
  --certificate-identity-regexp 'https://github.com/org/repo/.github/workflows/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

要点：没有长期私钥要管理；签发证书去 Fulcio，签名事件进 Rekor（任何人可查，防抵赖）。**cosign v3 起默认以 bundle（sigstore bundle）形式存档签名**（不是老三件套 sig/crt/chain）——升级脚本要注意。安装：`brew install cosign` 或 `go install github.com/sigstore/cosign/v3/cmd/cosign@latest`（本文写作时最新 v3.1.3）。

**方案 B：本地密钥对**——组织内部、没有 OIDC/网络限制严的场景：

```bash
cosign generate-key-pair             # 产 cosign.key（加密私钥）+ cosign.pub
cosign sign --key cosign.key ghcr.io/org/app:1.2.3
cosign verify --key cosign.pub ghcr.io/org/app:1.2.3
# 生产上把私钥放进 KMS/K8s secret、或 cosign 的 --key k8s://ns/name 形式托管
```

**策略一句话**：能 keyless 就 keyless（证书生命周期由 Fulcio/Rekor 托管零运维）；本地密钥对留给全网隔离或必须离线签的场景，私钥必须 KMS/Vault 托管、不入 git。

### 6.2 准入层联动：Kyverno verifyImages（最小可跑例子）

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-cosign-signature
spec:
  validationFailureAction: Enforce
  background: false                     # 验签要调外网 registry，背景扫会周期出网——默认关
  webhookTimeoutSeconds: 15
  failurePolicy: Fail
  rules:
  - name: verify-cosign
    match:
      any:
      - resources: { kinds: ["Pod"] }
    verifyImages:
    - imageReferences: ["ghcr.io/org/*"]
      mutateDigest: true                # 顺手把 tag 改写成 digest（--> 防 tag 重指）
      verifyDigest: true
      required: true
      attestors:
      - entries:
        - keys:
            publicKeys: |-
              -----BEGIN PUBLIC KEY-----
              MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...
              -----END PUBLIC KEY-----
```

要点（来自 Kyverno 官方 verify-images 页）：`mutateDigest/verifyDigest/required` 三个默认真；**imageVerify 规则在 mutation webhook 先执行**（把 digest 写进去），validating webhook 再过 required——这个顺序是设计出来的「先整改后判定」；每策略可配 `imageRegistryCredentials`（仓库认证，secrets 必须在 kyverno ns，1.18 起支持 `namespace/name` 跨 ns 引用）；**有 TTL 验签缓存**（默认开、60m——签名变更要对缓存失效期有预期）。

Gatekeeper 的等价做法说一句：**Gatekeeper 本身没有验签原语**（它的 webhook 不替你调 registry）——要组合 Ratify（Microsoft 主导的 notation/cosign 验证项目，以 external data provider 形态挂进 Gatekeeper constraint）；纯 K8s 原生方向则可看 Kyverno 的 ImageValidatingPolicy（§4.2 提到的 CEL 家族，Kyverno 1.13+）。

### 6.3 三条「仓库治理」硬规则（CEL 化不用引擎也能写）

白名单仓库（VAP 示例）：

```yaml
spec:
  validations:
  - expression: >-
      object.spec.template.spec.containers.all(
        c, c.image.startsWith("registry.corp.example.com/") ||
           c.image.startsWith("ghcr.io/org/"))
    message: "image must come from an approved registry"
```

禁 `:latest`（Kyverno 已在 §4.2 给过 pattern 版；CEL 版一行）：

```yaml
- expression: >-
    object.spec.template.spec.containers.all(c, !c.image.endsWith(":latest"))
  message: "tag :latest is disallowed (pin a version or use digest)"
```

强制 digest（Kyverno 内置 verifyImages 自带；CEL 版一行）：

```yaml
- expression: >-
    object.spec.template.spec.containers.all(c, c.image.contains("@sha256:"))
  message: "image must be referenced by digest"
```

三条规则共同回答「部署到集群里的东西是**可溯源、不可重指、可验签**的」。Kyverno 的 mutateDigest=true 本质上就是把第一条规则自动完成——同一份逻辑不用重复写。

### 6.4 角落一句：trivy / SBOM

- **trivy-operator**（aquasecurity，v0.35.0）：装到集群里周期性扫运行镜像的 CVE，出具 VulnerabilityReport CRD；Helm：`helm install trivy-operator aqua/trivy-operator -n trivy-system --create-namespace`。它覆盖「跑着的」这半边，准入的 Kyverno verifyImages 覆盖「进来的」那半边。
- **SBOM（Syft v1.54.1）**：`syft ghcr.io/org/app:1.2.3 -o cyclonedx-json > sbom.json`——合规要求「这镜像里有什么包」的审计材料；cosign 签字时可以把 SBOM 作为 attestation 挂进 registry（`cosign attest`），Kyverno verifyImages 的 attestations 段可直接校验 SBOM 存在与签者。

---

## 七、节点与控制面加固（CIS 基准视角）

前面 §1-§6 都在保护「业务侧」，这一节保护「底座侧」。主线是 CIS Kubernetes Benchmark（kube-bench 官方映射：CIS v2.0 覆盖了 k8s 1.34-1.35；1.36/1.37 当前无专属 profile，先沿用 cis-2.0 比对；kube-bench v0.16.0）。

### 7.1 kubelet：五个必看项（v1beta1 KubeletConfiguration 默认值已核对）

| 项 | 当前默认 | 加固要求 | 为什么 |
|----|---------|---------|--------|
| `authentication.anonymous.enabled` | **false**（默认） | 保持 false | 10250 端口的匿名访问一旦开 = 任意读/exec；历史事故之源（2018 前后多集群事件的根） |
| `authorization.mode` | **Webhook**（默认） | 保持 Webhook；配合 NodeRestriction（§7.2 apiserver 侧） | AlwaysAllow = 拿了 kubelet cert 等于全 node 主宰 |
| `readOnlyPort` | **0（禁）**（v1beta1 明确 default 0） | 保持 0 | 10255 只读端口可泄 Pod 清单/资源情报（供攻击者侦察） |
| `seccompDefault` | **false**（默认） | 验证存量兼容后开 true（对个别 syscall 敏感的 sidecar 先 Localhost 化） | 全量 workload 默认掉 RuntimeDefault seccomp（§2.6） |
| `serverTLSBootstrap` / `rotateCertificates` | false / false | 开 | kubelet 的 client 与 serving 证书都有源可查、有自动轮换 |

> ❗ 「默认就对」的东西最容易在版本升级和配置漂移中被偷改——kube-bench 4.2.x 的全套条目检查的就是这些。

### 7.2 apiserver：关键 flag（默认值核对于官方 command-line-reference）

| flag | 默认 | 加固 |
|------|------|------|
| `--anonymous-auth` | **true**（默认） | 显式 `=false`——匿名请求会以 `system:anonymous` 身份落到 RBAC，集群里任何「system:unauthenticated 可 discover」的默认绑定就成了侦察面 |
| `--enable-admission-plugins` | 一串默认（§1 章 §2.3 表） | 显式串里确认含 `NodeRestriction`、`ValidatingAdmissionWebhook`、`MutatingAdmissionWebhook`、`PodSecurity`、`ResourceQuota`、`LimitRanger`、`DefaultStorageClass`、`ServiceAccount`——四大安全插件必保，kubeadm 落地默认用 Node,RBAC + 上列 |
| `--encryption-provider-config` | 无（Secret 明文） | §5.2 全链 + auto reload |
| `--etcd-cafile`/`--etcd-certfile`/`--etcd-keyfile` | 空 | 必配（kubeadm 默认是 /etc/kubernetes/pki/etcd/{ca.crt,apiserver-etcd-client.crt,.key}）；etcd 自身 **peer 用另一对证书**（`peer-{cert,key}-file`）——两套密钥分开是 CIS 明确要求 |
| `--profiling` | **true**（默认） | `=false`（pprof 输出对攻击者情报价值大，只留排查窗口期临时开） |
| `--disable-insecure-port` / `--insecure-port` | **已不存在** | insecure 8080 于 v1.20 被拔（v1.10 起 deprecated）、v1.24 flag 本体物理移除（PR #106859）——现代检查对象是「ss -lnt 只监听 6443」而不是 flag 值 |
| `--requestheader-client-ca-file` | 空 | 用聚合层（metrics-server 等）才配，否则 proxy-user 可被仿冒 |

### 7.3 kube-bench 跑法（kind/kubeadm 通用 job）

```bash
# 一次性 job（官方 job.yaml 里面带 hostPID/卷映射，可直接用于 kind 控制面节点）
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/v0.16.0/job.yaml
kubectl wait --for=condition=complete job/kube-bench --timeout=120s
kubectl logs job/kube-bench | sed -n '/\[INFO\]/,/\[PASS\]\|\[FAIL\]\|\[WARN\]/p' | head -60

# kubeadm/kind 直接 job.yaml（自动探测版本并映射 cis-2.0 等 profile）；
# EKS/GKE/k3s 等发行版走仓库里对应平台的 job-*.yaml 变体
```

**结果分级处理节奏**（CIS 原生四级）：

- `PASS` 例行记录；`FAIL` 分两类——**配置类可修**（kubelet config/apiserver flag 直接落地）与**环境约束类**（云厂商托管面没法改 apiserver flag 的条目只能「接受 + 声明豁免」）。
- `WARN` 是手动评审项（benchmark 明说就是「需要管理员判断」）——**不是可忽略**，要列入周评审。
- 考 CKS 的话惯例：每跑失败一条都要落 runbook，跑一轮通过后每季度重跑（因为配置漂移真的会发生）。

---

## 八、常见生产问题清单

| # | 症状 | 根因链 | 排查/处置 |
|---|------|--------|-----------|
| 8.1 | PSA 上 enforce 后**老 workload 全部起不来** | 见 §1：restricted 档要求显式 runAsNonRoot/seccomp/allowPrivilegeEscalation/caps 四件套，99% 存量 YAML 裸奔 | `kubectl get events --field-selector reason=FailedCreate -n <ns>`；DaemonSet 起 `nginx:{}` 也有同样问题。**audit 先行四步走（§1.4）是唯一靠谱姿势** |
| 8.2 | `pod_security_evaluations_total` 违例暴增但业务不感知 | enforce 还是 privileged、或 exemptions 写得太宽，违例只留走了 audit/warn 通道 | 按月对 audit 注解 `pod-security.kubernetes.io/audit-violations` 做计数分面——突然飙高就是整改启动信号 |
| 8.3 | webhook 上线后**整个集群写不进**（连自己 Health 起不来） | failurePolicy=Fail + webhook 挂；匹配了 kube-system/自己所在/聚合层 namespace；或 rules 写成 `*` 把 kubelet 心跳 lease 也吞了 | `kubectl get validatingwebhookconfigurations`；**应急**：先 `kubectl patch` 把 failurePolicy 改 Ignore 救活集群，再按 namespaceSelector + objectSelector + matchConditions 三道闸根治 |
| 8.4 | webhook 证书轮换后**apiserver 报 x509**，webhook 看似活着却全 timeout/fail | 服务端 Secret 换了新证书，但 ValidatingWebhookConfiguration 里的 caBundle 没同步 | 对照 Secret `tls.crt` 与 caBundle 是否同一 CA；生产上 cert-manager cainjector 自动注入是标准答案 |
| 8.5 | CEL 规则上线**误伤全 ns** 而不是目标 ns | matchResources/namespaceSelector 写错（label 拼错、NotIn 拼成 In） | **先 Audit（validationActions: [Audit]）**，指标稳定几天再翻 Deny；VAP 的 status.typeChecking.expressionWarnings 会直接揭示字段拼错 |
| 8.6 | KMS plugin 挂/网络断 → **apiserver 起不来或集体 timeout** | providers 里 kms 在首、identity 兜底缺失；启动时 watch cache 全量 decrypt 不动 | 恢复路径：providers 末尾加 identity 兜底 → 重启 apiserver 读旧密文 → 修 KMS → 再 identity 前置改回 kms；KMS v2 的 Status 轮询故障期每 10s 拉一次 |
| 8.7 | 签名 key 轮换后**旧镜像集体验签失败** | cosign publicKey 换了，Kyverno verifyImages 内嵌公钥没更新 | attestors entries 里**新旧公钥并列**（默认全部要过；用 `attestors.count: 1` 只要求任一通过），存量镜像灰度过渡后再撤旧 key |
| 8.8 | mutating webhook 之间「我注入的 sidecar 被后面那个又改了」相互失效 | Istio/Vault 等多注入器共存——mutating 按名字串行，后写入者盖先写入者 | ① 用 `reinvocationPolicy: IfNeeded` 让先序 webhook 被重调；② 规划好 webhook 命名字典序；③ 对每个 webhook 打「只在自己注入字段上动」的幂等约束 |

---

## 九、实验（kind 沙箱 5 连）

> 环境：`kind`（≥ v0.20）、`kubectl`、`docker`、`go`（仅 9.3 用）、`openssl`。命令都可直接粘贴；节点镜像用 `kindest/node:v1.37.0`（Docker Hub 实际可查的 v1.37 tag；不写 --image 则用 kind 自版本默认）。9.1–9.4 共用集群 `sec-exp`，9.5 另起 `sec-enc`（apiserver 启动参数不同）。

### 实验 9.1 PSA drill：audit → 违例 → enforce → 降档

```bash
kind create cluster --name sec-exp --image kindest/node:v1.37.0

# step 1：建 ns，只上 audit/warn
kubectl create ns psa-drill
kubectl label ns psa-drill pod-security.kubernetes.io/audit=restricted \
  pod-security.kubernetes.io/audit-version=latest \
  pod-security.kubernetes.io/warn=restricted --overwrite

# step 2：起一个明知违例的 Deployment（裸 nginx 不满足 restricted）
kubectl create deploy bad-app -n psa-drill --image=nginx
#    期望 kubectl 输出 Warning：would violate PodSecurity "restricted:latest":
#    allowPrivilegeEscalation != false (container "nginx" must set ...), ...

# step 3：升级 enforce —— Deployment 建得起来，但 ReplicaSet 造不出 Pod（关键陷阱！）
kubectl label ns psa-drill pod-security.kubernetes.io/enforce=restricted --overwrite
kubectl delete deploy bad-app -n psa-drill && kubectl create deploy bad-app -n psa-drill --image=nginx
kubectl describe rs -n psa-drill | grep -A5 Events
#    期望：Error creating: pods "bad-app-xxx" is forbidden: violates PodSecurity ...
#    ⚠️ 这就是 §8.1「audit 先行」的根源——enforce 挡在 Pod 而不是 Deployment 阶段

# step 4（stepdown 演练）：把合规版本跑通
cat <<'EOF' | kubectl -n psa-drill apply -f -
apiVersion: apps/v1
kind: Deployment
metadata: { name: good-app }
spec:
  selector: { matchLabels: { app: good } }
  template:
    metadata: { labels: { app: good } }
    spec:
      securityContext: { runAsNonRoot: true, seccompProfile: { type: RuntimeDefault } }
      containers:
      - { name: app, image: nginxinc/nginx-unprivileged:stable,
          securityContext: { allowPrivilegeEscalation: false, capabilities: { drop: ["ALL"] } } }
EOF
kubectl -n psa-drill rollout status deploy/good-app --timeout=90s

# step 5（真正 stepdown）：把 enforce 换成 baseline——不是迁就违例，而是确认「模式还能降回去」
kubectl label ns psa-drill pod-security.kubernetes.io/enforce=baseline --overwrite
kubectl delete ns psa-drill
```

### 实验 9.2 CEL（VAP）：强制 requests，Audit → Deny

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata: { name: require-requests }
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups: ["apps"]
      apiVersions: ["v1"]
      operations: ["CREATE", "UPDATE"]
      resources: ["deployments"]
  validations:
  - expression: >-
      object.spec.template.spec.containers.all(
        c, has(c.resources) && has(c.resources.requests) &&
           size(c.resources.requests) > 0)
    message: "every container must set resources.requests"
EOF
# CEL 的 typeChecking 会在对象 status 里直接报字段拼错：
# kubectl get vap require-requests -o jsonpath='{.status.typeChecking}'

cat <<'EOF' | kubectl apply -f -
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata: { name: require-requests-binding }
spec:
  policyName: require-requests
  validationActions: [Audit]          # 先只审计
  matchResources:
    namespaceSelector:
      matchExpressions:
      - { key: kubernetes.io/metadata.name, operator: NotIn, values: [kube-system] }
EOF

# 违例 Deployment 建起得起来（Audit 不拒）
kubectl create deploy cel-audit-test -n default --image=nginx

# 查审计：violation 变成 audit annotation（kind 直看 apiserver 静态 Pod 日志）
kubectl logs -n kube-system kube-apiserver-sec-exp-control-plane 2>/dev/null | grep -i 'require-requests' | tail -3

# 第二步：翻 Deny
kubectl patch validatingadmissionpolicybinding require-requests-binding \
  --type=json -p='[{"op":"replace","path":"/spec/validationActions","value":["Deny"]}]'

# 现在违例的被拒；合规的能建
kubectl create deploy deny-test -n default --image=nginx 2>&1 | tail -2
kubectl delete deploy deny-test cel-audit-test --ignore-not-found
cat <<'EOF' | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata: { name: ok-with-requests }
spec:
  selector: { matchLabels: { app: ok } }
  template:
    metadata: { labels: { app: ok } }
    spec:
      containers:
      - { name: app, image: nginx,
          resources: { requests: { cpu: 50m, memory: 64Mi } } }
EOF
kubectl rollout status deploy/ok-with-requests --timeout=60s
# 清理
kubectl delete deploy ok-with-requests deny-test cel-audit-test --ignore-not-found
kubectl delete validatingadmissionpolicy require-requests validatingadmissionpolicybinding require-requests-binding
```

### 实验 9.3 webhook server 全链（§3.3 骨架 + 证书 + caBundle + §3.4 signer 陷阱）

**step 1：先把 signer 陷阱踩一遍（证明 §3.4 结论）**

```bash
# 生成 CSR（CN/SAN 指向将来 service 的 DNS 名）
openssl req -new -newkey rsa:2048 -nodes -keyout /tmp/server.key \
  -subj "/CN=webhook-svc.default.svc" \
  -addext "subjectAltName=DNS:webhook-svc.default.svc" -out /tmp/server.csr

cat <<EOF | kubectl apply -f -
apiVersion: certificates.k8s.io/v1
kind: CertificateSigningRequest
metadata: { name: webhook-server-csr }
spec:
  request: $(base64 /tmp/server.csr | tr -d '\n')
  signerName: kubernetes.io/kube-apiserver-client
  expirationSeconds: 86400
  usages: ["digital signature", "key encipherment", "server auth"]
EOF
kubectl certificate approve webhook-server-csr
sleep 3; kubectl get csr webhook-server-csr
#   期望：CONDITION 列出现 Failed（显示为 "Approved,Failed"）；
#   describe 里 Status: Failed  Reason: SignerValidationFailure
#   Message: invalid usage for client certificate: server auth
kubectl delete csr webhook-server-csr
# ➜ 结论（§3.4）：kube-apiserver-client 只签 client auth——生产正路是 cert-manager，实验正路在下一节
```

**step 2：正路——本地 CA 自签（cert-manager 的底层形态）**

```bash
# 自建一个 CA（password 只作演示，生产上 CA 私钥离线）
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -subj "/CN=My Webhook CA" -keyout /tmp/ca.key -out /tmp/ca.crt
# 用 CA 签 server 证书（SAN 对上 service DNS）
openssl x509 -req -in /tmp/server.csr -CA /tmp/ca.crt -CAkey /tmp/ca.key \
  -CAcreateserial -days 365 \
  -extfile <(printf "subjectAltName=DNS:webhook-svc.default.svc") \
  -out /tmp/tls.crt
cp /tmp/server.key /tmp/tls.key

kubectl create secret tls webhook-certs -n default --cert=/tmp/tls.crt --key=/tmp/tls.key
```

**step 3：编译并部署 §3.3 的 webhook**

```bash
mkdir -p /tmp/wh && cd /tmp/wh
# 把 §3.3 的完整 Go 代码保存为 main.go（已 go vet + go build 过；生产建议换
# k8s.io/api/apiserver 的 AdmissionReview 结构，本章保持零依赖最小 struct）
go mod init wh && CGO_ENABLED=0 go build -o webhook .

cat > Dockerfile <<'EOF'
FROM gcr.io/distroless/static-debian12:nonroot
COPY webhook /webhook
ENTRYPOINT ["/webhook"]
EOF
docker build -t wh-admission:1.0 .
kind load docker-image wh-admission:1.0 --name sec-exp

kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata: { name: webhook-dep }
spec:
  replicas: 1
  selector: { matchLabels: { app: wh } }
  template:
    metadata: { labels: { app: wh } }
    spec:
      containers:
      - name: wh
        image: wh-admission:1.0
        imagePullPolicy: IfNotPresent
        volumeMounts: [{ name: certs, mountPath: /etc/webhook/certs, readOnly: true }]
        ports: [{ containerPort: 9443 }]
      volumes:
      - name: certs
        secret: { secretName: webhook-certs }
---
apiVersion: v1
kind: Service
metadata: { name: webhook-svc }
spec:
  selector: { app: wh }
  ports: [{ port: 443, targetPort: 9443 }]
EOF
kubectl rollout status deploy/webhook-dep --timeout=120s
```

**step 4：写 ValidatingWebhookConfiguration（caBundle 注入 = 机器配一步）**

```bash
CA=$(base64 /tmp/ca.crt | tr -d '\n')
kubectl apply -f - <<EOF
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata: { name: require-resources-hook }
webhooks:
- name: requirepods.example.com
  clientConfig:
    service: { namespace: default, name: webhook-svc, path: "/validate" }
    caBundle: ${CA}
  rules:
  - apiGroups: ["apps"]
    apiVersions: ["v1"]
    operations: ["CREATE", "UPDATE"]
    resources: ["deployments"]
    scope: "Namespaced"
  admissionReviewVersions: ["v1"]
  sideEffects: None
  failurePolicy: Fail
  timeoutSeconds: 5
  namespaceSelector:    # ⚠️ 纪律：排除 kube-system 与自己所在 ns（本实验观察动 default）
    matchExpressions:
    - { key: kubernetes.io/metadata.name, operator: NotIn, values: ["kube-system"] }
EOF
```

**step 5：双端验证（curl + kubectl 创建拦截）**

```bash
# 从集群里直接 curl webhook（验证 TLS + 协议）
kubectl run curltest --rm -it --image=curlimages/curl --restart=Never -- \
  sh -c 'curl -sk https://webhook-svc.default.svc/validate \
    -H "Content-Type: application/json" \
    -d "{\"apiVersion\":\"admission.k8s.io/v1\",\"kind\":\"AdmissionReview\",\"request\":{\"uid\":\"t1\",\"namespace\":\"default\",\"name\":\"x\",\"object\":{\"spec\":{\"template\":{\"spec\":{\"containers\":[{\"name\":\"a\",\"resources\":{}}]}}}}}}"'
#   期望返回：{"allowed":false,"status":{"code":403,"message":"container \"a\" ... has no resources.requests"}}

# 创建违例 Deployment → 被 webhook 拒
kubectl create deploy hook-test --image=nginx 2>&1 | tail -2
#   期望 Error from server (Forbidden): admission webhook "requirepods.example.com" denied the request:
#   container "nginx" in ns default/hook-test has no resources.requests

kubectl delete validatingwebhookconfiguration require-resources-hook
kubectl delete deploy/webhook-dep svc/webhook-svc secret/webhook-certs curltest deploy hook-test --ignore-not-found 2>/dev/null
```

### 实验 9.4 Kyverno 部署 + 禁 `:latest`（对照 §4.2）

```bash
# step 1：部署（与官方 install.yaml 等价的版本化途径；Helm 生产推荐 helm install kyverno kyverno/kyverno）
kubectl create -f https://github.com/kyverno/kyverno/releases/download/v1.19.1/install.yaml
kubectl -n kyverno rollout status deploy/kyverno-admission-controller --timeout=180s

# step 2：策略
kubectl apply -f - <<'EOF'
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata: { name: disallow-latest }
spec:
  validationFailureAction: Enforce
  background: true
  rules:
  - name: no-latest
    match:
      any:
      - resources: { kinds: ["Pod"] }
    validate:
      message: "tag :latest is disallowed"
      pattern:
        spec:
          containers:
          - image: "!*:latest"
EOF

# step 3：验证放行/拒绝两类
kubectl run latest-pod --image=busybox:latest --restart=Never 2>&1 | tail -3   # 被拒
kubectl run pinned-pod --image=busybox:1.36 --restart=Never --command -- sleep 30
kubectl get pod pinned-pod
# 顺手看一眼报告（background: true 时存量也被扫）
kubectl get policyreports -A 2>/dev/null | head

kubectl delete clusterpolicy disallow-latest pod latest-pod pinned-pod --ignore-not-found
kubectl delete -f https://github.com/kyverno/kyverno/releases/download/v1.19.1/install.yaml
```

### 实验 9.5 EncryptionConfiguration：aescbc + etcdctl 眼见为实

```bash
# step 1：生成 key 与 enc.yaml，放在宿主机挂载进 control-plane 的目录
mkdir -p /tmp/enc && KEY=$(head -c 32 /dev/urandom | base64)
cat > /tmp/enc/enc.yaml <<EOF
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: ["secrets"]
    providers:
      - aescbc:
          keys:
          - name: key1
            secret: ${KEY}
      - identity: {}
EOF

# step 2：kind 集群启动即配 apiserver --encryption-provider-config（kubeadmConfigPatches）
cat > /tmp/kind-enc.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
kubeadmConfigPatches:
- |
  kind: ClusterConfiguration
  apiServer:
    extraArgs:
      encryption-provider-config: /etc/kubernetes/enc/enc.yaml
    extraVolumes:
    - name: enc
      hostPath: /etc/kubernetes/enc
      mountPath: /etc/kubernetes/enc
      readOnly: true
nodes:
- role: control-plane
  extraMounts:
  - hostPath: /tmp/enc
    containerPath: /etc/kubernetes/enc
EOF
kind create cluster --name sec-enc --config /tmp/kind-enc.yaml --image kindest/node:v1.37.0

# step 3：造一个 Secret 与一个 ConfigMap（后者未进加密列表，形成对照）
kubectl create secret generic s1 --from-literal=password=topsecret
kubectl create configmap cm1 --from-literal=note=plain-text-marker

# step 4：直查 etcd（secret 应密文、configmap 应明文 —— 对称两条命令）
CID=$(docker exec sec-enc-control-plane crictl ps --name etcd -q)

docker exec sec-enc-control-plane crictl exec "$CID" sh -c \
  'ETCDCTL_API=3 etcdctl --cacert=/etc/kubernetes/pki/etcd/ca.crt \
     --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key \
     get /registry/secrets/default/s1' | hexdump -C | head -4
#   期望：value 前缀 k8s:enc:aescbc:v1:key1:<密文...>

docker exec sec-enc-control-plane crictl exec "$CID" sh -c \
  'ETCDCTL_API=3 etcdctl --cacert=/etc/kubernetes/pki/etcd/ca.crt \
     --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key \
     get /registry/configmaps/default/cm1' | hexdump -C | head -4
#   期望：value 直接是 {"apiVersion":"v1",... note: plain-text-marker ...} 明文

# step 5：API 层面读起来完全无感（加密只发生在 etcd 层）
kubectl get secret s1 -o jsonpath='{.data.password}' | base64 -d; echo   # topsecret
# step 6：重写存量（生产必做；本实验 Secret 在加密后建成故非必需，仅演示命令）
kubectl get secrets --all-namespaces -o json | kubectl replace -f -

kind delete clusters sec-enc sec-exp; rm -rf /tmp/enc /tmp/wh /tmp/server.* /tmp/ca.* /tmp/tls.*
```

---

## 十、速查表 + 背诵要点 + 参考链接

### 10.1 一页速查

| 主题 | 命令 / 字段 / 对象 |
|------|-------------------|
| PSA 标签 | `pod-security.kubernetes.io/{enforce,audit,warn}(-version)` ∈ privileged/baseline/restricted；enforce 只看 Pod，audit/warn 也看 workload；改写 `activeDeadlineSeconds`/`tolerations` 不受限 |
| PSS restricted 四件套 | runAsNonRoot: true + seccompProfile: RuntimeDefault + allowPrivilegeEscalation: false + capabilities.drop: ["ALL"]（+ 可选 add NET_BIND_SERVICE） |
| PSS exemptions | usernames（注意控制器 SA 陷阱）/ runtimeClasses / namespaces；指标 `pod_security_evaluations_total` / `exemptions_total` / `errors_total` |
| securityContext 纪律 | readOnlyRootFilesystem + automountServiceAccountToken: false；runAsUser 用数值；镜像 USER 用数值 UID；fsGroup 衔接存储章 §3.6 提速 |
| seccomp/AppArmor | 字段化 seccompProfile（v1.19 GA）/appArmorProfile（v1.31 GA）；kubelet `seccompDefault` 默认 false，需要显式开 |
| User Namespaces | `hostUsers: false`；v1.36 GA 锁定；要内核 ≥6.3、containerd ≥2.0、runc ≥1.2/crun ≥1.9；NFS 与 hostNS/volumeDevices 互斥；PSA 对 runAsNonRoot 放宽 |
| webhook 必备 | `sideEffects: None`（或 NoneOnDryRun）+ `admissionReviewVersions` + `timeoutSeconds ≤5s` + namespaceSelector 排 kube-system/自己；`failurePolicy: Fail` 默认 |
| CSR signer 语系 | kube-apiserver-client **只能 client auth**（+certificate approve 必人工）；server cert 走 cert-manager/自建 CA/custom signer 手工签；kcm 要 `--cluster-signing-cert-file`（kubeadm/kind 有） |
| CEL 策略 | VAP GA v1.30；MAP GA v1.36 默认开；validationActions: [Deny/Warn/Audit]（Deny+Warn 不能同列）；binding 必配；status.typeChecking 盯 warning |
| Gatekeeper / Kyverno | Gatekeeper：ConstraintTemplate（Rego）+ Constraint，install v3.23.1；Kyverno：ClusterPolicy validate/mutate/generate/verifyImages，PolicyException(kyverno.io/v2)，helm install kyverno kyverno/kyverno |
| EncryptionConfiguration / KMS | `apiserver.config.k8s.io/v1`，providers 有序第一写其余读、identity 兜底、前缀 `k8s:enc:{aescbc|secretbox|kms}:v1:key1:`；KMS v2 GA v1.29、v1 v1.28 废弃/v1.29 默认关；rotate：新 key 进尾→调首→rewrite全部→撤旧 |
| cosign / Kyverno 验签 | v3 keyless `cosign sign --yes` 或本地 `--key cosign.key`；verifyImages: imageReferences+attestors.keys.publicKeys，mutateDigest 自动落 digest |
| kubelet 四面 | anonymous.enabled false（默认）；authorization.mode Webhook（默认）；readOnlyPort 0（默认）；seccompDefault 显式开 |
| apiserver 关键 | `--anonymous-auth=false`（默认 true）；`--profiling=false`（默认 true）；NodeRestriction 常在显式 plugins 串里；etcd peer/client 双密钥 |
| CIS/kube-bench | CIS v2.0 ↔ k8s 1.34-1.35；kube-bench v0.16.0 job.yaml 一键跑；PASS/FAIL/WARN 分级处理 |

### 10.2 关键要点（背诵版）

1. **4C 分治**：Cloud 底座/Cluster 控制面/Container 运行时/Code 应用——上层的所有机制只有在下层可信时才有效。本章按攻击面展开：工作负载（§1-2）→ 准入（§3-4）→ 数据（§5）→ 供应链（§6）→ 节点与控制面（§7）。
2. **PSA 三模式三标签五键位**：enforce 只作用于 Pods，audit/warn 对 workload 也评估；`enforce-version` 生产必钉；exemptions 三类整块跳过，**不能豁免控制器的 SA**（等效于豁免所有 workload 创建者）。
3. **restricted 档是四件套**：runAsNonRoot、seccomp、allowPrivilegeEscalation=false、capabilities drop ALL；**enforce 从 baseline 起步**，audit 先行，否则存量全炸。生产升级四步走：audit → 修违例 → server dry-run → enforce。
4. **User Namespaces（v1.36 GA 锁定）**是 ROI 最高的内核级加固：容器 root → 宿主非特权映射，PSA 对 runAsNonRoot 自动宽松；硬限制 hostNS/volumeDevices/NFS；要内核 6.3+ 与新运行时。
5. **webhook 是控制面的一部分**：sideEffects 必填、timeout ≤5s、failurePolicy 默认 Fail + selector 三重排除纪律；**证书轮换 = Secret + caBundle 双同步**；v1.37 起 apiserver 默认不让 webhook 撞认证鉴权虚拟资源（TokenReview/SAR 系）。
6. **CSR signer 语义是契约**（v1.37 事实）：`kube-apiserver-client` 只能签 client auth——用它申请 server 证书会被 signer 的 SignerValidationFailure 拒；server 证书正路是 cert-manager/自建 CA 或 custom signer 手工签。
7. **VAP v1.30 GA / MAP v1.36 GA 默认开**：CEL 策略进程内执行不依赖网络，「字段级规则先用 CEL」；webhook 只在 CEL 查不到外部世界时用（镜像验签、跨对象、公司系统）。
8. **Gatekeeper vs Kyverno 决策树**：纯字段规则→CEL；要 mutate/generate→Kyverno；有 OPA 资产→Gatekeeper；例外治理要 Kyverno PolicyException。
9. **Secret 三层防御**：etcd 静态加密（EncryptionConfiguration，provider 顺序决定读写）→ 消费通道改造（volume tmpfs 优于 env）→ 外部密钥管理（Vault injector / CSI provider / ESO）；**轮换核心命令 `kubectl get secrets -A -o json | kubectl replace -f -`**。
10. **cosign 本地化是不得已**：能 keyless 就 keyless；Kyverno verifyImages 在准入层强制验签+落 digest；**验签 key 轮换用多 attestors 灰度**，否则存量镜像集体进不来。
11. **kubelet/apiserver 默认值≠安全**：`--anonymous-auth` 默认 true、`--profiling` 默认 true 要显式关；insecure port v1.20 已拔 v1.24 flag 已删；etcd peer/client 双密钥分离；kube-bench 跑 cis-2.0 对齐，FAIL 修配置类、WARN 周评审。

### 10.3 参考链接

| 主题 | 链接 |
|------|------|
| Pod Security Admission（PSA 标签、豁免、指标） | https://kubernetes.io/docs/concepts/security/pod-security-admission/ |
| Pod Security Standards（三档字段清单） | https://kubernetes.io/docs/concepts/security/pod-security-standards/ |
| User Namespaces（hostUsers、节点要求、PSA 联动） | https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/ |
| feature-gate 版本注释（UserNamespacesSupport） | https://github.com/kubernetes/kubernetes/blob/master/pkg/features/kube_features.go |
| Dynamic Admission Control（webhook 配置、协议、监控指标） | https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/ |
| Validating / Mutating Admission Policy（v1.30 / v1.36 GA） | https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/ + .../mutating-admission-policy/ |
| CSR 与 signer（内建 signer 契约）+ Manage TLS in a Cluster（手工签名流程） | https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/ + https://kubernetes.io/docs/tasks/tls/managing-tls-in-a-cluster/ |
| kcm signer 源码（validAPIServerClientUsages） | https://github.com/kubernetes/kubernetes/blob/master/pkg/controller/certificates/signer/signer.go |
| Encrypting Confidential Data at Rest + KMS provider（轮换、auto-reload、key_id） | https://kubernetes.io/docs/tasks/administer-cluster/encrypt-data/ + .../kms-provider/ |
| AppArmor（v1.31 GA，appArmorProfile 字段） | https://kubernetes.io/docs/tutorials/security/apparmor/ |
| KubeletConfiguration + kube-apiserver flags（默认值来源） | https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/ + https://kubernetes.io/docs/reference/command-line-tools-reference/kube-apiserver/ |
| kube-bench（CIS 支持矩阵：cis-2.0 ↔ 1.34-1.35） | https://github.com/aquasecurity/kube-bench |
| Gatekeeper（v3.23.1 安装与 ConstraintTemplate） | https://open-policy-agent.github.io/gatekeeper/website/docs |
| Kyverno（v1.19.1 安装、verifyImages、PolicyException） | https://kyverno.io/docs/ |
| sigstore cosign（v3.1.3，keyless/bundle） | https://docs.sigstore.dev/ |
| External Secrets Operator（v2.12.0，SecretStore/ExternalSecret 链） | https://external-secrets.io/ |
| trivy-operator（v0.35.0）/ syft（v1.54.1） | https://github.com/aquasecurity/trivy-operator / https://github.com/anchore/syft |
