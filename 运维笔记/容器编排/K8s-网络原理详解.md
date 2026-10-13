# K8s 网络原理详解

> 精通路线第 3 章：网络模型三原则、CNI 规范与调用链、Flannel/Calico/Cilium 深度对比、kube-proxy 三种模式抓链、EndpointSlice、CoreDNS 与 ndots 黑洞、NodeLocal DNSCache、NetworkPolicy 加固、Gateway API 实战
> 创建时间：2026-10-13
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37），文中标注「v1.xx 起 Beta/GA」均取自官方文档、KEP 或各 CNI 官方文档，执行时仍以你本地集群版本为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，list-watch 概念会被 §4 直接引用）、`K8s-调度器深入.md`（第 2 章）。
> 网络基础（包、路由、NAT、conntrack）见 `网络/网络基础与进阶：从数据包到生产排障.md`；DNS 协议细节见 `网络/DNS-详解.md`；抓包命令细节见 `网络/tcpdump-guide.md`。这三篇都只讲通用层，本章不再复述。

---

## 零、本文定位与边界

K8s 网络被传得很玄，但拆到最后其实就**三件事**：

```
①  Pod 怎么有自己的 IP        → CNI（谁调用、谁分配、跨节点怎么通）    §1 §2 §3
②  Service 怎么负载均衡       → kube-proxy 改包 + EndpointSlice 供数    §4
③  名字怎么解析成 ClusterIP   → CoreDNS / NodeLocal DNSCache            §5
```

剩下的都是这三件事的加固与外延：NetworkPolicy 管「谁能跟谁说话」（§6），Gateway API 管「南北向流量怎么进来」（§7），生产上的坑几乎都长在这五条线上（§8）。

```
你的网络问题，最终都会变成这几类：
  "Pod 为什么卡在 ContainerCreating？"      → CNI ADD 失败链            §2.6
  "跨节点 Pod 互相 ping 不通"               → overlay/MTU/路由           §3 §8.2
  "Service 能通但打到错误的后端/不通"        → kube-proxy 链条 + 切片     §4
  "DNS 偶发 5 秒超时"                       → ndots × 重试 × UDP 竞争     §5.3
  "明明没配防火墙，两个 Pod 就是不通"        → NetworkPolicy 静默放行/拦截 §6
  "Ingress/Gateway 到底用哪个、怎么迁"       → 角色分离 + 实战           §7
```

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `K8s-API机制深入.md`（第 1 章） | list-watch / informer / resourceVersion | kube-proxy、EndpointSlice controller、CoreDNS 都靠这些机制拿数据，不重讲原理 |
| `K8s-调度器深入.md`（第 2 章） | 调度循环、抢占、descheduler | 只在 topology-aware 流量（§4.7）点到调度侧配合 |
| `K8s-资源全览.md` | Service / EndpointSlice / NetworkPolicy 的 **YAML 字段速查** | 只讲这些对象背后的数据面机制，不抄字段表 |
| `k8s-常用操作手册.md` | Ingress 使用语法 | Ingress 不是本文领土 |
| `Kubernetes-Ingress-部署与使用详解.md` | Ingress 全面实战 + §16 Gateway API 引介 | 本文 §7 承接其 §16，只写 Gateway API **机制与完整实战**，不重讲 Ingress |
| `Istio-服务网格详解.md` 系列 | Sidecar/Envoy/服务网格 | 本文只讲集群网络层；Cilium 的 L7 能力只到「CNI 原生能做到什么」为止 |
| `脚本与工具/Rancher部署文档.md` | Cilium kube-proxy 替代模式的现网备注 | §8 引用其排障结论，不复述部署流程 |

> ❗ **版本标注约定**：文中形如「v1.33 起 GA」「v1.35 起 Deprecated」的说法均对照官方文档 / KEP / CNI 官方文档核对过（来源见 §10.3）；
> 但 feature gate 默认值可能随 minor 版本漂移，落地前用
> `kubectl get cm kube-proxy -n kube-system -o yaml | grep mode`（kube-proxy 模式）、
> `kubectl get --raw /metrics | grep kubernetes_feature_enabled`（门控状态）再确认一次。

---

## 一、K8s 网络模型三原则与三类网段

### 1.1 官方模型就三句话

Kubernetes 官方《Cluster Networking》模型对所有网络实现提出三条硬要求（官方《Kubernetes 网络模型》文档，多年未变，与具体 CNI 无关）：

1. **每个 Pod 有自己唯一的 IP 地址**（不是网卡，是 IP）——包括同节点上的 Pod 之间也有不同 IP。
2. **Pod 与任意节点上的 Pod 通信不需要 NAT**（集群内部直连，看到的就是对方真实 Pod IP）。
3. **节点上的 agent（kubelet、系统进程）可以与该节点上所有 Pod 通信**。

强制要求的反面是「**不做端口映射**」：Docker 单机默认那套「容器共享宿主机 IP、端口靠 --publish 摇号」的方案被整个丢弃。

**为什么这么设计**（官方设计文档的原意）：

- 端口是稀缺资源，让应用关心「我占了宿主机哪个端口」会把集群级问题（端口协调）甩给每个开发者，规模一大必崩。
- 把 Pod 当「会漂移的 VM」对待：原有的命名、服务发现、负载均衡、应用迁移工具就能原样工作。这是 K8s 对「向后兼容存量应用」最狠的一次坚持，代价全部压给了网络实现层（也就是 CNI，见 §2）。

### 1.2 三类网段：Node / Pod / Service，职责互不重叠

一个集群里同时存在三种 IP 空间，**配置原则是三者两两禁止重叠**：

| 网段 | 谁分配 | 典型配置入口 | 是否可路由 | 备注 |
|------|--------|-------------|-----------|------|
| **Node CIDR** | 基础设施/云（VPC、机房交换机） | 云控制台 / DHCP / kubeadm 管不到 | 集群外可路由 | 节点自己的 IP，唯一不属于 K8s 管理的段 |
| **Pod CIDR** | 看形态：kubeadm 本身不给默认值，由管理员传 `--pod-network-cidr`（kind 帮你默认 `10.244.0.0/16`）；也可以是 CNI 自己的 IPAM 说了算 | 见下「职能划分」 | **由 CNI 决定**（见 §1.3） | 每节点再切一块（host-local 风格常为 /24） |
| **Service CIDR** | apiserver 的 `--service-cluster-ip-range`（kind/kubeadm 默认 `10.96.0.0/12` 或 `10.96.0.0/16`） | 只有 apiserver 消费它 | **默认不可路由**（见 §1.4） | 虚拟 IP 池，没有任何网卡真正持有这些地址 |

**Pod CIDR 的职能划分**（很多人搞混 cloud-controller-manager 和 kube-controller-manager）：

- `kube-controller-manager` 的 **nodeipam / ClusterIpam 控制器**：拿到 `--cluster-cidr` 后，为每个 Node 对象分配一段 PodCIDR，写进 `node.status.podCIDRs`。这是「控制平面代管 IP 池」的形态（kubeadm 默认）。
- `cloud-controller-manager` 的 **route / cloud node 控制器**：在云环境里把各节点的 PodCIDR 写进云路由表（这就是「云上 VPC 原生」的那条路），同时负责给 Node 分内外网 IP、健康云实例。
- **CNI 自己**：也可以完全不理会 podCIDRs 字段（如 Calico/Cilium 用自己的 IPAM 时），IP 池由 CNI 的 IPAM 插件管理。

所以「PodCIDR 是谁分的」没有唯一答案——kubeadm 集群里先由 controller-manager 切给节点，再由每台节点上的 CNI IPAM（host-local 等）从本节点那段里分给 Pod。

**Service CIDR 的职能划分**：只有 kube-apiserver 用 `--service-cluster-ip-range`，Service 创建时由控制平面的 IP 分配器记占用。

- v1.33 起 **MultiCIDRServiceAllocator 升级完成（GA 且锁定，不可关，最早 v1.27 出现）**：分配不再是 etcd 里一张内部位图，而是通过 **`ServiceCIDR` 与 `IPAddress` 两个正式 API 对象**实现——默认存在一个叫 `kubernetes` 的 ServiceCIDR（由 `--service-cluster-ip-range` 生成），管理员可以新建更多段，IPv6 掩码也不再被旧实现的 /108 限制。`kubectl get servicecidrs` / `kubectl get ipaddresses` 现在可以直接看占用。

```bash
# 两个能立刻看到真相的命令
kubectl get servicecidrs                 # 默认 ServiceCIDR(名 kubernetes) + 你加的
kubectl get ipaddresses | head           # 每个 ClusterIP 背后都有一个 IPAddress 对象
```

### 1.3 PodCIDR 到底能不能被集群外路由：overlay vs VPC 原生

这是选型层面的第一刀，一句话定性：

- **Overlay（VXLAN / IPIP / Geneve 封装）**：Pod IP 只有集群内部知道。出集群的流量要 SNAT 成节点 IP；进集群流量必须走 NodePort/LB/Ingress/Gateway。任何二层网络都能跑，代价是封装开销与 MTU 缩水（§3.5、§8.2）。
- **Underlay / VPC 原生（云 VPC CNI、Calico 纯 BGP 直接对 TOR）**：Pod IP 就是底层网络路由表里的一等公民，集群外直连 Pod 没问题，也不存在 SNAT 黑盒；代价是吃云的配额（路由表条目数、ENI 数量）、IP 地址规划必须全公司统一，且常受安全组限制。

> ❗ 判断你的集群属于哪种，看 CNI 和云：`flannel vxlan` / `calico vxlan|ipip` / `cilium tunnel` 都是 overlay；`aws-vpc-cni`、GKE 的 alias-IP、Calico 纯 BGP 都是路由直达。混合形态（Calico **VXLANCrossSubnet**、同子网直通跨子网封装）是常见的折中。

### 1.4 Service IP 为什么「不存在于网络上」

这是理解 §4 的前提：

```
你在 Pod 里访问 10.96.10.100:80（某 ClusterIP）
        │
        ├── 这张网卡上没有这个 IP（arping 十个有九个不会有人应答）
        ├── 节点路由表里没有这条路由（ip route | grep 10.96 通常为空）
        └── 它能通，是因为出网包在 netfilter 钩子上被「目的地址改写」
            ——DNAT 成某个真实 Pod IP。所谓 ClusterIP，
              只是 iptables/nftables/IPVS/eBPF 规则里的一个「匹配条件」。
```

**为什么不把 Service IP 做成可路由地址**：

- 可路由就必须全网唯一且长期稳定，等于把「服务拓扑」硬编码进路由表，扩缩容/多集群复用段全部变难。
- 做成「只存在于改包规则里的虚拟 IP」，则每个集群可以复用同一段 10.96.0.0/12，内存里存规则就够了，增删 Service 零网络参与。

代价同样明显：从**集群外**访问 ClusterIP 没有任何通用方法，所以才有 NodePort / LoadBalancer / externalTrafficPolicy / Gateway 这一整层「南北向补救学」（§4.4、§7）。

### 1.5 版本状态速记

| 特性 | 状态（已核对） |
|------|---------------|
| Kubernetes 网络模型三原则 | 长期稳定，无版本概念 |
| ServiceCIDR / IPAddress（多 Service 网段分配器） | 最早 v1.27，**v1.33 起 GA 且锁定** |
| 老 Endpoints API | **v1.33 起 Deprecated**（EndpointSlice 是 v1.21 GA 的继承者） |
| externalIPs 字段 | **v1.36 起 Deprecated**（迁移到 LB/Gateway） |
| ClusterIP 上/下两段分配（静态段防冲突） | v1.26 起 Stable（静态段大小 `min(max(16, 网段/16), 256)`） |

---

## 二、CNI 规范与调用链

### 2.1 谁真正调用 CNI：不是 kubelet

这是最常见的面试级误解。准确链路（以 containerd 为例）：

```
kubectl create deploy nginx
   ▼
kubelet watch 到 Pod 绑定到本节点
   ▼
kubelet → CRI: RunPodSandbox(pod/nginx-xxx)        ← kubelet 只发 CRI 请求
   ▼
containerd 的 CRI 插件:
   ① 用 runtime 创建 pause 容器（sandbox），**先建好 network namespace**
   ② 读取 /etc/cni/net.d 下第一份（按文件名字母序）网络配置
   ③ 按配置里的插件链逐个执行 CNI 二进制（ADD）
   ▼
sandbox 拿到 eth0 + IP → 后续业务容器全部 --net=container:sandbox 共享这个 netns
```

- **dockershim 时代**（v1.24 移除前）CNI 是 kubelet 里的 dockershim 调的；现在 kubelet 完全不认识 `/etc/cni/net.d`，CNI 是**容器运行时**（containerd / CRI-O）在其 CRI 实现里调的。
- 因此排查 CNI 问题，看的是**容器运行时日志**（`journalctl -u containerd`）和 runtime 产生的事件，不是 kubelet 配置。CRI-O 同理。

**为什么这么设计**：kubelet 的职责边界是「Pod 生命周期」，网络隔离域（sandbox）是运行时的内部实现。把 CNI 下放到运行时，意味着换运行时（containerd→CRI-O）不影响 kubelet 一句代码；也解释了为什么「kubelet 打开 hairpin/带宽」这种开关其实都落在 CNI 插件配置上。

### 2.2 CNI 规范（当前 spec 1.1.0）：五个操作 + 一个 STATUS

CNI（Container Network Interface）是 CNCF 维护的「运行时 ↔ 插件」协议：运行时读 JSON 配置，**执行二进制**，通过环境变量 + stdin/stdout 通信。当前规范版本 1.1.0，定义这些操作（来自官方 spec，已核对）：

| 操作 | 何时被调 | 语义要点 |
|------|---------|---------|
| **ADD** | 创建 sandbox 后 | 在容器 netns 里建/调 `CNI_IFNAME`（通常 eth0）接口；同名接口已存在必须报错；同一 `(容器ID, ifname)` 不应重复 ADD |
| **DEL** | 销毁 sandbox 时 | 拆接口/回收 IP；**必须幂等**——netns 没了、IP 早没了都要成功返回；可重复调用 |
| **CHECK** | 可选健康探测 | 对照 `prevResult` 验证接口/路由/防火墙还在；配置 `disableCheck: true` 可全禁 |
| **GC** | 清理孤儿资源 | 运行时告诉插件「还存活的 attachment 清单」，插件回收清单外资源（IPAM 预留等）；**不能当 DEL 的替代** |
| **VERSION** | 探测协议版本 | 返回插件支持的 spec 版本列表 |
| **STATUS** | spec 1.x 新增，**纯信息性** | 探测插件能否服务新 ADD；插件**不得依赖**它被调用 |

规范里还有几条对排障很有用的硬约束（原文译者注）：

- **运行时必须先创建容器的 network namespace，再调任何插件**——所以「netns 不存在」是插件报错的头号嫌疑。
- 同一容器的操作**不得并发**；不同容器可以并发，插件要自己给共享资源（IPAM 数据库）上锁。
- 每次 ADD 必须最终跟一个对应 DEL；DEL 用**逆序**走插件链（带宽、防火墙先撤，主接口最后拆）。
- DEL 即使 ADD 失败过也要执行（「部分建好了也要收干净」）。

### 2.3 `/etc/cni/net.d` 生效规则：字母序，先到先得

containerd/CRI-O 启动时（以及目录变更时）扫描 `cni-conf-dir`（默认 `/etc/cni/net.d`）：

- 取**文件名字典序最小**的合法配置作为「当前网络」——这就是为什么所有 CNI 发行版都抢着叫 `00-xxx`/`01-xxx`/`10-xxx`。
- `.conflist`（conflist 格式，`{plugins: [...]}`）= 插件**链**；老的单文件 `.conf` = 一个插件。链式场景几乎都用 conflist。

```bash
# 一眼看清当前节点上谁会赢
containerd config dump | grep -A4 cni        # 确认 cni 目录配置（containerd v2 配置文件不同版有差异）
ls -la /etc/cni/net.d/                       # 字母序最小者生效
jq '.plugins[].type' /etc/cni/net.d/*.conflist  # 查看插件链构成
```

**生产坑**：节点上同时存在 `10-flannel.conflist` 和 `10-calico.conflist` 时按名字第一个生效（calico 赢）——两套共存、查起来像灵异事件的常见根因。CNI 升级文档（尤其 `kubectl apply` 两套网络组件的讲义）很少警告这一点。

### 2.4 插件三类：Interface / Chained / IPAM

spec 原文把插件分成三类（社区俗名主插件/meta 插件/IPAM）：

| 类别 | 职责 | 代表（containernetworking/plugins 仓） |
|------|------|---------------------------------------|
| **Interface（主插件）** | 在容器里创建网卡并接入网络 | `bridge`（常用）、`ptp`（kindnet 用）、`macvlan`、`ipvlan`、`vlan`、`host-device`、`dummy` |
| **Chained（meta）** | 在已建好的接口上调优 | `tuning`（改 sysctl/MTU）、`bandwidth`（限速）、`portmap`（hostPort 映射）、`sbr`、`firewall` |
| **IPAM（委托型）** | 分配/回收 IP，由主插件代为调用 | `host-local`（本机一段 CIDR）、`dhcp`、`static`；各 CNI 还有自家 IPAM（Calico IPAM、Cilium IPAM…） |

一份 flannel 系典型 conflist 就是这条链：`flannel(main) → portmap(meta) → tuning(meta)`，IPAM 用 `host-local` 由 flannel 委托调用——CNI 规范规定 IPAM 由主插件代为执行（委托协议），运行时自己不直接调 IPAM。

### 2.5 一次 CNI ADD 到底给你的 Pod 干了什么

以最经典的 bridge + host-local 为例（Flannel 系、kindnet 的 ptp 变体大同小异）：

```
宿主机 netns                          Pod sandbox netns
┌──────────────────────────┐        ┌─────────────────────────┐
│   cni0 (bridge)          │        │                         │
│   10.244.1.1/24  ◄───────┼────────┤ eth0 10.244.1.37/24     │
│        │                 │  veth  │        │                │
│        └─ip_forward──────┼─pair───┤     default route       │
│   主网卡 eth0(SNAT出口)   │        │     via 10.244.1.1      │
└──────────────────────────┘        └─────────────────────────┘

CNI ADD 五步（对应可粘贴的验证命令）：
 1. 运行时建好 netns：             ip netns list  (或 lsns -t net)
 2. 建 veth pair，一端进 sandbox： 宿主机 ip link | grep veth
 3. host-local IPAM 分 IP：        /var/lib/cni/networks/<网络名>/<ip> 占位文件
 4. 配置地址+默认路由+ARP：        进 Pod: ip addr; ip route; ip neigh
 5. 宿主侧接通（桥接/路由/MTU）：    ip route | grep cni0 ; bridge link
```

Calico 系则是纯 L3（不建桥）：每 Pod 一对 veth，宿主侧**逐 Pod 一条 /32 路由**，靠 `proxy_arp` 把网关伪装成 `169.254.1.1`（Calico veth 默认行为）——所以 Calico 网络里 `ip neigh` 经常能看到一串 link-local 的 ARP 条目，这是正常设计，不是故障。

### 2.6 CNI 排障抓手（按出现频率排）

| 症状 | 第一现场 | 看什么 |
|------|---------|--------|
| Pod 卡 `ContainerCreating` | `kubectl describe pod` 的 Events | `FailedCreatePodSandBox ... network: failed to find plugin "xxx"`=插件二进制没装；`cannot allocate address`=IPAM 段满 |
| 节点 NotReady，报错带 `cni` | 节点上 `journalctl -u containerd -f` | 运行时读 `/etc/cni/net.d` 失败或插件返回非零 |
| Pod IP 能起但出不了节点 | sandbox 内 `ip route` | 没有默认路由 / MTU 错（见 §8.2） |
| 怀疑换过 CNI 后的残留 | `ls /etc/cni/net.d/` + `/var/lib/cni/` | 旧 conflist 没清、旧 IPAM 占位还占着 |
| 想直接看 CNI 在干嘛 | 插件日志（Cilium/Calico 写进自家 agent 日志；flannel 在 `kube-flannel` Pod 日志） | host-local 之类无日志的，看 `/opt/cni/bin` 与运行时 stderr |

> ❗ 收尾一句通用判断方法：**先 `crictl pods` 找到 sandbox 是否建起来了**。sandbox 都没起来 → 问题在 CRI/CNI ADD；sandbox 起来了但业务容器不通 → 大概率是网络链/策略/路由，退出 CNI 话题进 §3 或 §6。

---

## 三、三大 CNI 实现深度对比：Flannel / Calico / Cilium

### 3.1 Flannel：把「跨节点连通」做到最简单

**架构**：每台节点跑一个 `flanneld` agent（flannel 的 CNI 插件本身极薄，真正的逻辑在 agent 里）。flanneld 从 K8s API（默认，kube subnet manager 模式）或 etcd 读取全网段（默认 `10.244.0.0/16`），为本节点**租**下一段 `/24`（`node.status.podCIDRs` 的历史原型），并 watch 其他节点的段，把它们写成本机后端规则。**不提供 NetworkPolicy**——见 3.4。

**后端（已核对官方 backends 文档）**：

| 后端 | 原理 | 端口/开销 | 适用场景 |
|------|------|-----------|---------|
| **VXLAN**（推荐/默认） | 内核 VXLAN 套壳：Pod 包 → UDP → 对端节点 | Linux 默认 UDP **8472**、VNI 1（Windows 必须 4789）；`DirectRouting` 选项同子网不封装 | 几乎所有网络都能跑，包括云上三层网 |
| **host-gw** | 直接把「其他节点的段 → 对端节点 IP」写成主机路由，**零封装** | 无封装、性能最好 | 要求节点间二层直连（同子网/VPC 同网段），云上跨子网不可用 |
| UDP | 用户态封装 | UDP 8285 | 官方定位「仅调试或老内核」，生产别用 |
| WireGuard / IPIP / IPSec | 加密/简单隧道 | WG 51820 等 | 实验/小众需求，见 backends 文档 |

**为什么这么设计**：Flannel 的问题是「2003 年的问题」——让 Pod 跨节点通，仅此而已。它把控制面极简到「一个 agent + 一张租约表」，换来的代价就是**功能极简**：没有策略、没有观测、没有 BGP、没有加密强制。k3s 默认用它，理由正是「少即是多」的小集群心智。

### 3.2 Calico：策略与路由优先的老牌三层方案

**组件**（Calico Open Source）：

- **calico-node**（每节点 DaemonSet）：核心控制面 agent **Felix**，把「Pod 路由 + Policy」编程到本机数据面；新版 Felix 还支持 nftables 模式。
- **Calico CNI 插件 + 自家 IPAM**：按 block（默认 /26～/32 动态块）给节点分 IP，比 host-local 的整段 /24 更省地址。
- **BIRD BGP 守护进程**：非 overlay 时把「Pod 段的 /32 或 block 路由」通过 BGP 发布给节点或 TOR 交换机。
- 数据面 PPP 可选：**iptables（经典默认）/ nftables / eBPF / VPP / Windows** 五种（已核对官方「产品矩阵」）。eBPF 数据面下可彻底不依赖 kube-proxy iptables 形态做 Service 转发。

**datapath 三形态**（实际就是你选过几次 YAML）：

| datapath | 跨节点怎么通 | 何时选 |
|----------|-------------|--------|
| **封装：VXLAN**（含 **VXLANCrossSubnet**） | UDP 8472（Linux）套壳 | 云三层网络、不想碰底层网络、要和 flannel 一样零门槛 |
| **封装：IPIP** | IP 协议号 4 直接包一层 IP | 比 VXLAN 少 20 字节头；中间设备必须允许 IPIP 协议 |
| **不做封装（纯路由）** | Pod IP 直接出现在网络里：节点间走 Calico 下发的主机路由 + ARP proxy；集群外（可选）靠 BGP 对 TOR | 机房/裸金属追求最低延迟、需要 Pod IP 全公司可路由 |

**为什么这么设计**：Calico 从第一天就把「策略」当一等公民（它的 Felix 比 K8s NetworkPolicy 本身还老），所以它不仅**完整实现 K8s NetworkPolicy**，还扩展出 GlobalNetworkPolicy（集群级）、Staged/干跑策略、Log rule 等一整套企业级语义（开源版；FQDN/DNS 策略以官方当时文档为准）。

### 3.3 Cilium：把数据面整个搬进 eBPF

**架构一句话**：Calico/Flannel 是「内核 netfilter + 路由表 的玩家」，Cilium 是「绕开大部分 netfilter 的 eBPF 玩家」。

- 每 Pod 入口处（veth host 端 / netkit）挂 **TC eBPF 程序**：连接跟踪不用内核 conntrack，而是自己一张 **BPF map（conntrack/LB 表）**；跨节点可达就走隧道（默认 **VXLAN UDP 8472**，Geneve UDP 6081 亦可）或**原生路由**（underlay 可路由时关闭隧道）。
- **kube-proxy 替换（KubeProxyReplacement）**：Service 的 ClusterIP/NodePort/LB 全部在 **Socket LB（cgroup eBPF，connect 时直接改写到后端）+ TC 层**完成——节点上**没有** iptables/nftables 大链条。官方文档明确：它**依赖 Socket LB**，老内核（尤其 cgroup v1 环境）有坑；切换/混部时 kube-proxy 与 Cilium 两张 NAT 表互不知情，**切换瞬间存量连接必断**（详见 §8.8 与本仓库 `脚本与工具/Rancher部署文档.md` 的现网备注）。
- **Hubble**：把每条流（identity → identity、verdict、L7 详情）汇成可观察事件流，Hubble server 4244 / Hubble Relay 4245（已核对官方系统要求页）。
- **策略**：完整 K8s NetworkPolicy + CiliumNetworkPolicy 把粒度过到 **L7 / FQDN**（嵌入式 Envoy 做透明代理，需要 TPROXY 等内核选项）。
- **加密**：Pod 间透明加密二选一 **WireGuard（UDP 51871）** 或 **IPsec ESP**（官方系统要求页已核对端口与 ESP 需安全组放行）。
- 内核要求：v1.20 线官方建议 **≥5.10**（RHEL 8 4.18 亦可），最新特性（netkit device mode）要 ≥6.8。

**为什么这么设计**：iptables 系的路径是「规则数随 Service+Endpoint 线性膨胀 + 每包顺序匹配」（§4.2 给出量级感受），conntrack 表有上限；把「负载均衡、连接跟踪、策略判定」全改写成 BPF map 的哈希查找，单包路径从 O(n) 变近似 O(1)，同时把观测点天然埋进转发路径（Hubble 白捡的）。代价：**团队必须长出 eBPF 排障技能**（bpftool、cilium monitor、bpf map dump），以及内核版本管理。

### 3.4 三大 CNI 关键差异速查（可直接拍板）

| 维度 | Flannel | Calico OSS | Cilium |
|------|---------|-----------|--------|
| 默认/推荐 datapath | VXLAN（8472），host-gw 可选 | iptables 数据面 + {VXLAN, IPIP, 纯 BGP} 可选 | eBPF + VXLAN 隧道（默认）/ 原生路由 |
| **NetworkPolicy** | ❌ 不原生提供；官方给出补法：`netpol.enabled` 挂 kubernetes-sigs/kube-network-policies 控制器，或上 Calico（Canal）/ Cilium 链式 | ✅ 完整 + 集群级/GlobalNetworkPolicy、Staged、FQDN（以官方文档为准） | ✅ 完整 + L7/FQDN（CiliumNetworkPolicy）+ DNS 感知 |
| 加密 | WireGuard（实验位） | 官方有 WireGuard/数据加密生态（以文档为准） | ✅ WireGuard / IPsec 透明加密，Pod 级零配置 |
| kube-proxy | 必须存在 | 可走 iptables/nftables kube-proxy；eBPF 数据面时可无 kube-proxy | **可整体替换 kube-proxy**（Socket LB）或与其共存 |
| Service 负载均衡后端 | kube-proxy | kube-proxy 或 Calico eBPF | **eBPF 原生**（Maglev 一致性 hash、DSR、SRv6 L3VPN 等高级形态以官方文档为准） |
| 观测 | 几乎没有 | flow logs / Whisker（Cloud Free 起） | **Hubble** L3-L7 流观测 + 服务依赖图 + 指标 |
| Pod IPAM | host-local 整段 /24 | 动态块分配（省地址） | kubernetes / cluster-pool / 云 ENI 多模式 |
| 多集群 | 不做 | 有企业级能力 | ClusterMesh（原生） |
| 学习/排障成本 | 低 | 中（BGP/数据面选型） | 高（eBPF + 内核版本） |
| 适合谁 | 小集群、能跑就行、k3s 默认 | 企业策略管控、机房 BGP、长期主义 | 大规模、要高 PPS、要观测/加密/eBPF 红利的团队 |

**选型建议（经验版，非官方）**：

- 能不能二层直连/云支持 IPIP/需要和物理网打通 → 优先 Calico 纯路由形态。
- 不需要策略，集群就是跑业务 → Flannel 确实够用；但请记住 **6.x 的「CNI 不支持策略 = 静默放行」**（§6.5、§8.5）。
- 集群刚规划，且愿意把团队升级成 eBPF 原住民 → 直接 Cilium，顺手拿 Hubble+加密+替换 kube-proxy 三件套；**先在 kind 把 §9 实验 3.3/3.4 跑一遍再下决心**。

### 3.5 各自 MTU 坑（为什么 overlay 一定要减头部）

物理链路 MTU 常见 1500。overlay 封装要在外层再套头：

| 封装 | 单层开销（外层 IP+UDP/协议头+隧道头） | 经验 Pod 侧 MTU |
|------|--------------------------------------|-----------------|
| VXLAN | 50 B（20 外 IP + 8 UDP + 8 VXLAN + 内层以太 14） | **1450**（Flannel、Calico VXLAN、多数实现默认值） |
| IPIP | 20 B（仅外层 IP 头） | 1480 |
| Geneve（Cilium 可选） | ~50 B 起步（可变长 option，有 DSR 选项时更大） | 1450 或更小 |
| WireGuard/IPsec（叠加在隧道上） | 再减 60~80 B | 需要重新核算 |

**怎么避免变成黑洞**（§8.2 详排障）：

- 让 CNI 自己探测（Flannel/Calico 默认都会按外接口 MTU 自动减，**前提是外接口本身是标准的 1500**）；如果你的 VPC/物理网本来就是 9000 或 1460（不少云是这样），显式把 CNI 的 MTU 写成「外接口 MTU - 封装头」。
- 验证命令（实验 3.2 同款；注意 `-M do` 是 iputils 的参数，busybox 的 ping 不支持，请在节点或用 `nicolaka/netshoot` 这类镜像里跑）：
  ```bash
  # 用不分片大包试跨节点路径（1472+28=1500 是物理 1500 时的边界）
  ping -M do -s 1372 -c 3 <对端PodIP>   # overlay 下应通（1372+78≈1450）
  ping -M do -s 1472 -c 3 <对端PodIP>   # 若失败而 1372 通 → MTU 黑洞实锤
  ```

---

## 四、kube-proxy 与 Service 数据面

### 4.1 ClusterIP 的本质：虚拟 IP + 目的地址重写

请求 `curl http://10.96.10.100`（某 Service 的 ClusterIP）在一个 iptables kube-proxy 节点上的完整路径：

```
            ┌── netfilter nat 表 ───────────────────────────────────┐
你的进程 ──►│ OUTPUT/PREROUTING                                     │
            │   └─► KUBE-SERVICES   （全部 Service 的分发总入口）     │
            │        │  -d 10.96.10.100 --dport 80                  │
            │        ▼                                              │
            │     KUBE-SVC-XXXX（Service"专属链"，负载均衡发生地）    │
            │        │  -m statistic --mode random --probability …  │
            │        ▼           （按概率落到）                      │
            │     KUBE-SEP-YYYY（单个 Endpoint 链，真正做 DNAT）      │
            │        ├─ 若源就是该 Pod 自己 → KUBE-MARK-MASQ 打标记  │
            │        └─ -j DNAT --to-destination 10.244.1.37:80     │
            │ KUBE-POSTROUTING：被打了 MASQ 标记的包做 SNAT           │
            └──────────────────────────────────────────────────────┘
回程无需规则：conntrack 记住这次 DNAT，回包自动反改写 10.96.10.100
```

真实输出长这样（kind 默认 kindnet + iptables kube-proxy 集群里实测可得，实验 3.1 完整步骤）：

```
-A KUBE-SERVICES -d 10.96.10.100/32 -p tcp -m comment --comment "default/web cluster IP" -m tcp --dport 80 -j KUBE-SVC-TCOU7JCQXEZGVUNU
-A KUBE-SVC-TCOU7JCQXEZGVUNU -m comment --comment "default/web -> 10.244.1.3:80" -m statistic --mode random --probability 0.33333333349 -j KUBE-SEP-A1B2C3D4E5F6G7H8
-A KUBE-SVC-TCOU7JCQXEZGVUNU -m comment --comment "default/web -> 10.244.2.3:80" -m statistic --mode random --probability 0.50000000000 -j KUBE-SEP-Z9Y8X7W6V5U4T3S2
-A KUBE-SVC-TCOU7JCQXEZGVUNU -m comment --comment "default/web -> 10.244.2.4:80" -j KUBE-SEP-...
-A KUBE-SEP-A1B2C3D4E5F6G7H8 -s 10.244.1.3/32 -j KUBE-MARK-MASQ
-A KUBE-SEP-A1B2C3D4E5F6G7H8 -p tcp -m tcp -j DNAT --to-destination 10.244.1.3:80
```

几处值得背的机制：

- **负载均衡 = 静态概率，不是 Round Robin**：N 个 endpoint 时，第一条规则概率 1/N，第二条 1/(N-1)，…——每条规则按行匹配，落进就再也不看后面的。效果上均匀，但**没有顺序概念**，所以你不能靠 iptables 轮询做确定性预测。
- **链名后缀**：`KUBE-SVC-` 后是 Service（`namespace/name/port`）的 16 位哈希，`KUBE-SEP-` 后是单个 endpoint（`ip:port`）的哈希——同集群里**同 Service 改名 ≠ 同哈希**，但你重放 YAML 重建同名 Service 哈希不变（确定性 hash），脚本可据此定位具体链。
- **KUBE-MARK-MASQ + KUBE-POSTROUTING**：只有「源 IP 会被对端认不出」的场景（hairpin 自己访问自己、跨节点回程经过自己）才打 `0x4000/0x4000` 标记做 SNAT；纯集群内直通根本不 SNAT——这就是 §1.1 的「Pod 直通免 NAT」原则的底层兑现。
- **conntrack 是回程对称的根基**：DNAT 写一条 conntrack 条目，回包查表反向还原。所以 conntrack 表满/竞争 = Service 间歇性抽风（§8.1）。

**为什么这么设计**：VIP 不存在于任何网卡（§1.4），就只能用 netfilter 钩子「骗包」。iptables 方案赢得在「纯内核态、无用户态进程转发包、零额外延迟线」——当年选它是为了可靠性（用户态代理模式的 kube-proxy 早就是历史了）。

**代价就是它自己的规模问题**（见下节）：规则条数 = Σ(每个 Service 约 2 条 + 每个 endpoint 2 条)，匹配是线性扫描；Service 和 endpoint 都到万级时，单包路径与规则同步都变慢。

### 4.2 三种（两种半）kube-proxy 模式的版本事实（重点红线条目）

这是本章版本事实最多的一节，全部为已核对结论（来源 §10.3）：

| 模式 | 现状（v1.37 基线） | 关键事实 |
|------|-------------------|---------|
| **iptables** | **当前 v1.37 默认**；官方明确「未来版本会把默认切到 nftables」 | 随机选择后端；规则链 O(n) 扫描；自 v1.28 起规则同步改为「最小变更集」不再全量重刷，大集群可用性大幅改善 |
| **nftables** | **GA v1.33**（KEP-3866，alpha v1.29 / beta v1.31 / stable v1.33，gate `NFTablesProxyMode`）；要求内核 ≥5.13 | 官方定位：**iptables 与 IPVS 的共同继任者**；同步更快、可更大规模伸缩；与 iptables 有几处行为差异（见下表） |
| **ipvs** | **v1.35 起 Deprecated**：v1.40 起默认禁用（可用门控 `KubeProxyIPVS` 强行打开），**v1.43 起彻底移除** | 基于内核 LVS，哈希表转发、支持 rr/wrr/lc/wlc/lblc/lblcr/sh/dh/sed/nq/mh 等调度算法；官方废弃理由正文摘录见下 |
| kernelspace | Windows 节点唯一选项 | 与本章主线无关，略 |

**IPVS 为什么被官方亲手放弃**（官方 virtual-ips 文档原话的意译，值得背）：IPVS 当年是为了解决 iptables 的更新性能与吞吐，目标都达到了，但「内核 IPVS API 与 Kubernetes Service API 的表达力**就是不匹配**——一些边角语义（hairpin、端点部分终结、externalTrafficPolicy: Local 的细节）**从来没能全部做对**」。而 iptables 这些年的性能也追上来了，nftables 更是全面更好——所以没有让 IPVS 继续活着的理由。

**如果你的集群还在用 IPVS**：短期不用动（v1.40 前都还能跑），但请把它列入升级路线：**新方向是 nftables（或 Cilium 等 eBPF 替换）**，不是再多花精力调 IPVS 参数。

**nftables 与 iptables 的几处行为差异**（切换前必看，全部官方文档列出）：

| 差异点 | iptables 模式 | nftables 模式 |
|--------|--------------|---------------|
| NodePort 监听地址 | 默认 `all`（所有本地地址都能访问） | 默认 `primary`（仅节点主 IP）。想全听：`--nodeport-addresses 0.0.0.0/0` |
| 对激进本地防火墙的兼容 | 主动为每个 NodePort 加 ACCEPT 放行 | **不加**——本地防火墙/云主机防火墙需要自己放行整个 NodePort 段 |
| 内核 <6.1 conntrack bug 缓解 | 内置 workaround | 默认无；用 `--conntrack-tcp-be-liberal`，依据 `iptables_ct_state_invalid_dropped_packets_total` 指标判断是否需要 |
| localhost（127.0.0.1）访问 NodePort | 默认可通（受 `route_localnet` 与 `--iptables-localhost-nodeports` 控制） | 默认不通；**Alpha v1.37 门控 `KubeProxyNFTablesLocalhostNodePorts`** 打开后经用户态代理可用（性能稍差） |

> ❗ 配合实验 3.1 的体验建议：**iptables → nftables 才是当前应该做的对照实验**；IPVS 在 v1.37 里已只是「能跑得动的历史选项」。

### 4.3 EndpointSlice：Kube-proxy 的数据源如何规模化

kube-proxy 只做「规则生成器」，真正告诉它「这个 Service 现在有哪些健康 IP」的是 EndpointSlice 控制器：

```
Endpoints 老 API 的三个死穴（官方 service 文档列出）：
 ① 一个对象装不下 → 硬性截断到 1000 个后端，多余的不负载均衡（注解 endpoints.kubernetes.io/over-capacity: truncated）
 ② 没有双栈概念
 ③ 放不下 trafficDistribution 等新特性需要的拓扑信息
且：每个没 selector 的 Endpoints 变更都是整对象重写，业已证实不可扩展。
```

**EndpointSlice（discovery.k8s.io/v1，v1.21 GA）** 把「一个 Service 的全部后端」拆成多片：

- 默认**每片最多 100 个 endpoint**（`--max-endpoints-per-slice` 可调，上限 1000）；IP 族（IPv4/IPv6）不同必然分片。
- 控制器**填片策略为「少写广播片」**：宁愿新开一片也不把已有两片填得更满——因为 kube-proxy 在所有节点 watch 切片，**每片变更都要广播全网**。这是「正确性 vs 更新成本」的经典取舍（官方 endpoint-slices 文档明示）。
- kube-proxy 在内存里聚合所有片并**去重**（切片切换瞬间同一 endpoint 可能同时在新旧两片里）——这正是 `EndpointSliceCache` 存在的意义。
- 头部字段 `nodeName`/`zone` 就是为 §4.7 的 topology 流量而生的。
- 继承链：`Endpoints（v1.33 起 Deprecated，会引发迁移警告）→ EndpointSlice→trafficDistribution`。凡是老组件还在读 Endpoints 的，只会看到最多 1000 行。

```bash
# 看一个 Service 的切片构成与控制
kubectl get endpointslices -l kubernetes.io/service-name=web -n default \
  -o custom-columns=NAME:.metadata.name,TYPE:.addressType,PORTS:'.ports[*].port',ENDPOINTS:'.endpoints[*].addresses'
kubectl get endpointslice <name> -o jsonpath='{.endpoints[*].conditions}'   # ready/serving/terminating
```

**为什么这么设计**：拆成可增量的多对象 = watch fan-out 友好（只传变的一片）+ 双栈/拓扑字段有地方放 + 单对象无 1MiB etcd 上限截断烦恼。

### 4.4 两种 TrafficPolicy：Cluster 与 Local，代价各是什么

| 字段 | 取值 | 作用范围 | 机制代价 |
|------|------|---------|---------|
| `externalTrafficPolicy: Cluster`（默认） | 任意节点接住 NodePort/LB 流量后，**再均衡到全局所有健康端点** | 入向 | 多一跳 + 一次 SNAT（**客户端源 IP 被改写**） |
| `externalTrafficPolicy: Local` | 节点接住后**只打本机的端点** | 入向 | **保留客户端源 IP**（不做第二次 SNAT）；本机无端点则**直接丢**——云 LB 靠 kube-proxy 的 `:10256/healthz`（Local 服务时「健康且有本地端点」才 200）把没端点的节点踢出去，LB 健康检查就成了负载分布的实际掌控者 |
| `internalTrafficPolicy: Cluster`（默认） | 集群内部访问 ClusterIP 均衡到全局端点 | 内访 | 无 |
| `internalTrafficPolicy: Local`（**GA v1.26**） | ClusterIP 也只打**调用方所在节点的端点** | 内访 | 本机无端点直接丢；常被用来做节点级 cache/agent 的拓扑亲和 |

配合机制（**GA v1.28，门控 ProxyTerminatingEndpoints**）：Local 模式下若本机端点全在 terminating，kube-proxy 会把流量打给这些终结中的端点而不是立刻丢——滚动更新期不至于瞬断。

`externalTrafficPolicy: Cluster` 的**源 IP 丢失**是老牌业务痛点（审计、黑白名单、地域统计全失真）；Local 的**代价**（官方与社区共识）：负载不均（以节点为粒度）、健康检查强依赖 LB 语义、滚动更新期健康窗口敏感。这两个政策都要在「要不要源 IP」和「能不能容忍节点粒度不均」之间拍板。

### 4.5 Topology-aware 流量：PreferClose 已过时，PreferSameZone/SameNode 上位

**版本轴（全部核对过官方文档/门控页）**：

- 老机制：**Topology Aware Hints**（注解 `service.kubernetes.io/topology-aware-hints: Auto` → 后更名为 `service.kubernetes.io/topology-mode: Auto`）。特点：按节点可分配 CPU **按比例**往 zone 摊，内置多种「防过载」启发式回退——行为强但很难预测。
- 新机制：**`spec.trafficDistribution` 字段**（门控 `ServiceTrafficDistribution`：alpha v1.30 → beta 默认开 v1.31 → **GA v1.33 锁定**）。v1.37 支持的取值：
  - `PreferSameZone`：客户端 zone 有健康端点就全打本 zone；**没有则回退全网**（不再抱怨比例，简单可预测）。
  - `PreferSameNode`：先同节点，再同 zone，再全网的两级回退。
  - `PreferClose`：**Deprecated 别名**，语义同 `PreferSameZone`，请只在新代码用后者。

机制：EndpointSlice 控制器把「这份切片优先服务哪个 zone/节点」的 **hints 写进切片**，kube-proxy 用 hints 在 EndpointSliceCache 聚合时优先选近端。

❗ 两条易踩的优先级规则（官方文档明示）：

- 注解 `topology-mode: Auto` 如果存在，**优先级高于** `trafficDistribution`（两个都写时以注解为准；注解方向未来可能废弃）。
- `external/internalTrafficPolicy: Local` 是**强约束**：它优先于 `trafficDistribution` 的「软偏好」。

### 4.6 conntrack / 短连接 / 内核 <6.1 的坑（与 NodeLocal DNS 联动）

生产上「Service 间歇 connection reset」的经典三根线：

1. **conntrack 表满**：ClusterIP/NodePort 每个连接写一条 conntrack。表满后新连接被丢（dmesg 有 `nf_conntrack: table full, dropping packet`）。指标/排查见 §8.1；缓解是调大 `nf_conntrack_max` + hashsize + 用 NodeLocal（§5.4）消灭最费表的 UDP DNS 条目（UDP 条目要等 30 秒超时才回收，TCP 连接关了就回收）。
2. **短连接 5-tuple 复用竞争**：客户端高频短连接访问 NodePort（DNAT+SNAT），两个连接在极短时间内向同一个四元组发起，conntrack 竞态挑同一源端口 → 一个被当成冲突包丢弃或 RST。缓解：kube-proxy MASQUERADE 用 `--random-fully`（源端口随机化）、应用侧连接池/keep-alive、必要时迁到 `trafficPolicy: Local`（跳过那次 SNAT）。
3. **内核 <6.1 长连接被 RST 的 bug**：官方 virtual-ips 文档明说——低版本内核的一个 conntrack bug 会让「到 Service IP 的长连接被 Connection reset by peer 断开」，iptables 模式内置 workaround，nftables 默认不带（用 `--conntrack-tcp-be-liberal`）——升级内核到 ≥6.1 是从根上解决。

### 4.7 kube-proxy 观测面（生产必须会）

| 抓手 | 命令/端点 | 看什么 |
|------|-----------|--------|
| 同步性能 | `kubeproxy_sync_proxy_rules_duration_seconds`（:10249/metrics）；`sync_proxy_rules_last_queued_timestamp_seconds` | 平均 > 秒级 = 规则集太大/事件太密，考虑 nftables/Cilium |
| 变化频度 | `kubeproxy_sync_proxy_rules_last_change_timestamp_seconds`、`kubeproxy_sync_proxy_rules_changes_total` | 更新风暴定位 |
| 健康面（LB 健康检查用） | `:10256/healthz`（节点未删除且同步没超时 → 200）/ `/livez` / 指标 `proxy_healthz_total`、`proxy_livez_total` | LB 摘除节点的依据（**健康超时窗口 = 2×iptables.syncPeriod**） |
| 当前真实模式 | `kubectl get cm kube-proxy -n kube-system -o jsonpath='{.data.config\.conf}' \| grep -E '^mode'` | 升级/排查前先确认你以为的模式就是真的 |

---

## 五、CoreDNS 与集群 DNS

### 5.1 部署形态：两套对象，一个 ClusterIP

kubeadm 集群里 DNS 由这几样东西组成（全部可作 `kubectl -n kube-system` 直接查看）：

- **Deployment `coredns`**：默认 **2 副本，软反亲和（preferred，TopologyKey hostname）**——尽量散开，单节点故障不断 DNS。
- **Service `kube-dns`**：固定的 ClusterIP（kubeadm 默认网段里是 **10.96.0.10**）；一切 DNS 流量的 VIP 入口。名字保留 `kube-dns` 是历史包袱（kube-dns 是 CoreDNS 的前任实现）。
- **ConfigMap `coredns`**：Corefile（下节）；kubelet 给每个新 Pod 写 `/etc/resolv.conf` 时把 `nameserver` 指到 `kube-dns` 的 ClusterIP。

```bash
kubectl -n kube-system get deploy coredns -o wide
kubectl -n kube-system get svc kube-dns
kubectl -n kube-system get cm coredns -o yaml          # Corefile 本体
kubectl run -it --rm dnsutils --image=registry.k8s.io/e2e-test-images/dnsutils:1.3 -- cat /etc/resolv.conf
```

### 5.2 Corefile 最小讲法（kubeadm 默认逐段）

默认 Corefile（多年稳定，以你集群实际为准）：

```
.:53 {
    errors                                   # 把 err 打成日志
    health { lameduck 5s }                   # 就绪说「还没好再等我 5s 滚连接」→ 滚动更新不掉查解析
    ready                                    # 就绪探针端口 :8181/ready
    kubernetes cluster.local in-addr.arpa ip6.arpa {
        pods insecure                        # 允许 Pod 也解析出记录
        fallthrough in-addr.arpa ip6.arpa    # 反解 PTR 查不到别卡死，扔给 forward
        ttl 30
    }
    prometheus :9153                         # 自暴露指标
    forward . /etc/resolv.conf {             # 一切非集群域交给节点/上游
        max_concurrent 1000
    }
    cache 30                                 # 结果缓存 30s（默认含负缓存）
    loop                                     # 检测 DNS 转发环，发现就崩给你看而别死循环
    reload                                   # Corefile 改动自动热加载
    loadbalance                              # 多 A 记录轮询打乱顺序（headless 语义必需）
}
```

- `kubernetes` 插件是集群域的权威源：watch apiserver，把 `svc.ns.svc.cluster.local`（以及 headless 的 Pod A 记录）变成响应。除集群域与国内反解段外一律 `forward` 出去。
- `cache 30` 是「重查保护」的关键参数：30s 内同一名称不再问 apiserver/上游；**改 Service 后你可能要等最多 30s 才能解析到新地址**（这是 DNS 缓存的正常语义，不是 bug）。
- `loop` 的存在意义：CoreDNS 发现「forward 目标最终又回头解析到自己」（比如节点 resolv.conf 指向 kube-dns 的 ClusterIP）就直接 crash——这是在防整个集群 DNS 死锁。

### 5.3 ndots:5 黑洞：一次名字查询为什么展开成最多 5 倍

kubelet 给 Pod 生成的 `/etc/resolv.conf`（官方 dns-pod-service 文档原生样例）：

```
nameserver 10.96.0.10
search <namespace>.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

resolver（glibc）规则是：**名字里点的个数 < ndots 时，先把名字拼到每个 search 域上逐个问；全都 NXDOMAIN 最后再问「绝对名字」**。数一数：

```
在 nginx-abc 这个 Pod（default ns）里：ping my-svc
  my-svc.              ← 0 个点 < 5 → 先走 search 域
  ① my-svc.default.svc.cluster.local.   ✅ 命中（目标就是它）
—— 看起来还行？但换成跨 ns 的就翻倍：

ping other-svc.prod              ← 1 个点 < 5 →
  ① other-svc.prod.default.svc.cluster.local   ✗ NXDOMAIN
  ② other-svc.prod.svc.cluster.local           ✅ 命中
—— 2 次。而访问外部域名（2 个点仍 < 5）：

curl api.github.com             ←
  ① api.github.com.default.svc.cluster.local   ✗ NXDOMAIN
  ② api.github.com.svc.cluster.local           ✗ NXDOMAIN
  ③ api.github.com.cluster.local               ✗ NXDOMAIN
  ④ api.github.com.                            ✅ 真去公网了
—— 4 次；再来 A 和 AAAA 各一份 → **8 个 DNS 报文**才点到为止。
```

而最后这个「绝对名字」步骤还有一个更隐蔽的语境：当 search 域里恰好**有记录**（比如你真有个 `api.github.com.svc.cluster.local` 的外部服务不小心叫这个名），请求会被拦截到集群里——这是 ndots 的另一类事故。

**后果与对策**：

- **后果 1：NXDOMAIN 风暴**。每个外流访问放大 3~4 倍；CoreDNS 虽会缓存负响应（`cache`），高 QPS 下依旧是可观的放大量，且一堆 5 秒级超时抖动。
- **后果 2：解析延迟抖动**。每一次 search 失败都花在上游/集群内递归；和重试（`options timeout:5 attempts:2` 默认）叠加，一个 DNS_MISS 可能拖出长尾巴。
- 对策 1（首选）：**对外/跨 ns 一律写 FQDN 并以点结尾**——`api.github.com.`、`my-svc.prod.`。一个尾点直接跳过 search 段，一次查完。
- 对策 2：高频出网负载调 `dnsConfig`：
  ```yaml
  spec:
    dnsConfig:
      options:
      - name: ndots
        value: "2"        # 放宽「先当绝对名字试」的阈值
  ```
  ❗ API 层面 dnsConfig 合并进 Pod 的 resolv.conf（最多 32 条 search、总长 2048，v1.28 起 Stable 的硬上限）；ndots 不是越小越好，toolbox（如 `short-name` 依赖 search 的内部服务）可能因为拿不到 search 后果而改行为。
- 对策 3（大集群）：上 NodeLocal（§5.4），缓存+TCP 直连把这些抖动连根拔。

### 5.4 NodeLocal DNSCache：大集群 DNS 的必装件

**动机（官方文档四条，已核对）**：

1. 最高 QPS 的 Pod 所在节点上可能没有 CoreDNS——本地缓存消灭一次跨节点 DNS。
2. 到 CoreDNS 的 UDP 会走 kube-proxy iptables DNAT + conntrack；本地缓存改走**本地 TCP**，**跳过 DNAT 与 conntrack 竞争**（DNS 的 UDP 条目要等 `nf_conntrack_udp_timeout` 默认 30s 才回收，TCP 连接断了就立刻回收）。
3. UDP→TCP 升级让丢包长尾消失（官方口径：DNS 超时最坏约 30s——3 次重试 × 10s；本地代理吃这个长尾）。
4. 节点级指标与负缓存重新可用，单点 CoreDNS 压力骤降。

**部署形态（DaemonSet，GA v1.18）**：每节点跑一个 `node-local-dns`，监听一个**不与集群任何 IP 冲突的链路本地地址**（IPv4 常选 `169.254.20.10`，示例清单默认值；IPv6 用 ULA `fd00::/8` 段里的地址）。Pod 的 `nameserver` 改成它；本地缓存命中直接回；未命中再**以 TCP** 转 CoreDNS。

- **iptables kube-proxy 模式**：本地代理同时监听 `<本机localdns>` 和 **CoreDNS 的 ClusterIP**（`__PILLAR__CLUSTER__DNS__`），Pod 用哪个地址都行，老 Pod 不用改 resolv.conf。
- **IPVS kube-proxy 模式**：IPVS 把 ClusterIP 绑给内核接口用，本地代理绑不了同一地址 → 只监听 localdns 地址，**需要把 kubelet 的 `--cluster-dns` 改成 localdns 地址**（新建 Pod 生效，存量要重启）。
- manifest 变量三个：`__PILLAR__LOCAL__DNS__`（本机链本地地址）、`__PILLAR__DNS__DOMAIN__`（`cluster.local`）、`__PILLAR__DNS__SERVER__`（kube-dns ClusterIP）——官方教程给了两种 kube-proxy 模式下的 sed 一把梭命令，照抄。

**为什么大集群必装**：DNS 是「每个连接都会先问一次」的流量，它的尾部延迟、UDP 竞争与 CoreDNS 副本压力都随规模线性放大；而 NodeLocal 用极低成本把「最频繁、最敏感」的那部分就近解决掉，是大规模集群的事实标准。

### 5.5 排障三板斧（照抄命令）

```bash
# ① 验证：从一个干净 Pod 里看解析与耗时
kubectl run -it --rm dnsdbg --image=registry.k8s.io/e2e-test-images/dnsutils:1.3 -- sh
# 容器内：
nslookup kubernetes                          # 应命中 kube-dns svc
time nslookup api.github.com                 # 慢就去看 search 展开
cat /etc/resolv.conf                         # 确认 nameserver + ndots

# ② 看 CoreDNS 指标与日志
kubectl -n kube-system port-forward deploy/coredns 9153:9153 &
curl -s 127.0.0.1:9153/metrics | grep -E 'coredns_dns_requests_total|coredns_cache_hits_total|coredns_forward_healthcheck_failures_total' | head
kubectl -n kube-system logs deploy/coredns --tail=100 -f | grep -Ei 'error|timeout|SERVFAIL'
kubectl -n kube-system exec deploy/coredns -- cat /etc/resolv.conf   # forward 上游到底是谁

# ③ 验证上游与转发链：直查 CoreDNS Pod IP（绕开 kube-dns VIP 这条 DNAT 链，能区分 VIP 段问题与 CoreDNS 本身问题）
COREIP=$(kubectl -n kube-system get pods -l k8s-app=kube-dns -o jsonpath='{.items[0].status.podIP}')
kubectl run -it --rm digdbg --image=registry.k8s.io/e2e-test-images/dnsutils:1.3 -- sh
# 容器内：dig @${COREIP} kubernetes.default.svc.cluster.local     # 直查某个 CoreDNS 副本
# 容器内：dig api.github.com.                                     # 尾点测 FQDN（跳过 search 展开）
```

❗ 两个 invisible 陷阱：alpine/musl 镜像的 nslookup/getent **不会回放 TCP**、对尾点/search 的反应与 glibc 不完全一致，排障尽量用 `registry.k8s.io/e2e-test-images/dnsutils` 或 `nicolaka/netshoot`（glibc）；`dig` 默认 **不带 search 域**——业务用 `nslookup/ping/getent` 才更接近 glibc 行为。

---

## 六、NetworkPolicy：白名单模型与「先全拒再放行」基线

### 6.1 模型本质：不是防火墙规则列表，是「选中即隔离」

- NetworkPolicy 通过 `podSelector` 选一组 Pod；**一旦某个方向（ingress 或 egress）被任何策略选中，该方向立即「默认拒绝」，政策里白名单放行的除外**；未被选中的方向维持全通。
- `policyTypes` 不写字段时**按内容推断**：写了 `ingress:` 才有 Ingress、写了 `egress:` 才有 Egress（这是看 YAML 时的第一直觉要校准的地方）。
- 每条 rule 内部是 **AND**，rule 列表之间是 **OR**——这是最易错的一对语义：

```yaml
ingress:
- from:                                # rule 1：「同 ns 且 app=web」的 Pod
  - namespaceSelector: {}
    podSelector:
      matchLabels: {app: web}
- from:                                # rule 2：「本 ns 且 app=client」的 Pod（与 rule 1 是 OR；注意
  - podSelector:                        #  podSelector 不写 namespaceSelector 时只对 policy 所在 ns 求值）
      matchLabels: {app: client}
- ports:                               # 单写 ports 不带 from = 所有来源这个端口放行
  - port: 8080
```

| 易踩点 | 语义 |
|--------|------|
| `namespaceSelector: {}` | 所有 namespace（不是本 ns！）——`{}` = 选全部 |
| `podSelector: {}` | **本** namespace 里的所有 Pod（podSelector 永远在 policy 的 ns 内求值） |
| 同行 `namespaceSelector + podSelector` | AND（那个 ns 里的这批 Pod） |
| 两条 `- from:` 列表项 | OR |
| `ipBlock` 写客户端 CIDR | ⚠️ 看到的是**进入本节点时被 SNAT 后的地址**（见 §4.4）；想保住源 IP，externalTrafficPolicy: Local |
| egress 访问 kube-dns | 需要 `to: - namespaceSelector:`（kube-system ns 按标签选）+ `ports: 53/udp、53/tcp`；装了 NodeLocal 还要加 `169.254.20.10/32` 的 ipBlock（链接本地） |

### 6.2 一份可直接当基线的「先全拒再放行」

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny-all}
spec:
  podSelector: {}                       # 本 ns 全部 Pod
  policyTypes: [Ingress, Egress]        # 双方向全锁
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-same-namespace}
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
  ingress: [{from: [{podSelector: {}}]}]
  egress:  [{to:   [{podSelector: {}}]}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-dns-egress}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
  - to:                                 # kube-dns（按 ns 标签选）
    - namespaceSelector:
        matchLabels: {kubernetes.io/metadata.name: kube-system}
      podSelector:
        matchLabels: {k8s-app: kube-dns}
    ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]
  - to: [{ipBlock: {cidr: 169.254.20.10/32}}]   # NodeLocal（如未装可删）
    ports: [{port: 53, protocol: UDP}, {port: 53, protocol: TCP}]
```

之后按业务事实增量放行（谁调谁、什么端口），拒绝域就是最小面。

**为什么这么设计**：K8s 网络模型本身鼓励「全连」，策略层默认一整张白名单；「先全拒再放行」是唯一能把「新 Pod 默认是安全的」变成默认值的姿态——代价是你的**平台团队必须维护「平台自己的 egress 白名单」**（镜像仓库、API server、监控 exporter 抓取口等），把它当成基线的一部分长期运维。

### 6.3 各 CNI 的支持差异（生产最大坑：静默放行）

| CNI | K8s NetworkPolicy | 超出 K8s 的能力 |
|-----|------------------|-----------------|
| **Flannel** | ❌ **不原生提供**——NetworkPolicy 对象看着正常创建，流量**照样放行**（这是 §8.5 的事故源）。官方补法三种：`netpol.enabled` 的 kube-network-policies 控制器、Calico（Canal）、Cilium 链式 | — |
| **Calico** | ✅ 完整 | GlobalNetworkPolicy（跨 ns 集群级）、Staged（干跑）、Log rule、按域名/FQDN 的 egress（以当时官方文档为准） |
| **Cilium** | ✅ 完整 | CiliumNetworkPolicy：L7（HTTP/gRPC/Kafka…）、FQDN（`toFQDN`，需配置 `rules:[dns]` 先学域名）+ `CiliumClusterwideNetworkPolicy` |
| 其他（kindnet、aws-vpc-cni、azure CNI、VPC 原生等） | 多为「或通过附加组件提供」 | 以各云/发行版文档为准 |

### 6.4 验证流程：要么干跑，要么看命中数

纯 kubectl 层面没有「policy 命中计数器」对象（K8s NetworkPolicy 本身没有 status 计数），所以验证要分两条路：

- **CNI 提供了「观测/干跑」能力的（生产首选）**：
  - **Cilium**：`cilium monitor -t policy-verdict`（DROP/REDIRECT 与 policy 名一行一条）或 `hubble observe --verdict DROPPED`（实验 3.4）；`cilium endpoint list` + `cilium policy get` 看某个端点当前汇聚的策略。
  - **Calico**：Staged NetworkPolicy（`staged: true`）只审计不拦截，配 whisker/流日志看「假设拦截」的结果。
- **没有观测能力的（笨但可靠）**：先在**非生产 ns** 全套照抄 → 用 LoadRunner/业务回放灌流量 → `timeout 5 curl` 一笔笔对账「该通的通、该断的断」（实验 3.4）后再推广。

❗ 迁移期tips：**先写全通 egress 的「显式白名单 policy」再收紧**比「直接 default-deny」更稳——比如第一台先只写「能出网、能访问 API server、能上 DNS」，跑一周中没有它放不出去的正常流量，再把多余项删除。

### 6.5 「不支持 policy 的 CNI」不是安全豁免，是安全负债

重说一遍（这条在生产事故里的权重和「conntrack 表满」一样高）：**NetworkPolicy 是给 CNI 实现的，不是 K8s 自带**。如果你的 CNI 不支持，对象照样创建、kubectl 不报错、审计看不到差异——但**数据面管道没有任何行为变化**。所以「先 CNI 后策略」不是偏好，是硬前置：决定引入 NetworkPolicy 的第一天，先确认 CNI 真的会用数据面去 enforce。

---

## 七、Gateway API 完整实战

> 承上启下：`Kubernetes-Ingress-部署与使用详解.md` §16 已经把 Gateway API 作为「新建平台的推荐方向」**引介**过（选型理由、最小 YAML）。本章只把它落到**机制与全流程实战**；Ingress 的内容不复述。

### 7.1 为什么替代 Ingress：角色分离是本质，不是多几个字段

| 角色 | 关心的对象 | 想改的事 |
|------|-----------|---------|
| **Infra Provider**（集群部署方/云） | **GatewayClass** | 「我们提供哪种数据面」（Envoy/NGINX/云 LB），由它出实现 |
| **Cluster Operator**（平台团队） | **Gateway（+Listener）** | 监听地址/端口/TLS 证书，谁能往里挂 route，命名空间边界 |
| **App Developer**（业务） | **HTTPRoute/GRPCRoute/TCPRoute…** | 按 host/path/header 匹配、分流、熔断、灰度——**不用碰 Gateway** |

Ingress 把这三件东西糊在一个对象里，导致「加个注解找基础设施的人、加个 host 找应用的人」是一个人。对象分开后**每类角色只拿自己能改的权限**，这是 RBAC 领域上更重要的一层，而 HTTPRoute/GRPCRoute 的匹配能力（header/权重/方法 + backendRef 多目标）只是顺带的红利。

**与 Ingress 相比的新事实**：截至写作时 Gateway API 最新稳定版 **v1.6.3**（2026-10-06 发布；下一版 v1.7.0-rc.1 预发布中）。**v1.6.0 把 TCPRoute、UDPRoute 从 experimental 升到 GA（用 `v1` API 版本）**——以前只能用 Ingress/Service 求 L4 的诉求第一次有了「标准官方答案」。CRD 渠道仍是两条：

- `standard-install.yaml`：稳定 API（GatewayClass/Gateway/HTTPRoute/GRPCRoute/ReferenceGrant/TCPRoute/UDPRoute/ListenerSet 等）。
- `experimental-install.yaml`：含 Standard 全部 + 实验字段与 TLSRoute/XBackend/XTelemetryPolicy 等。**生产选 standard 渠道；想尝新用独立集群玩 experimental 渠道**（渠道之间的 CRD 不能直接互装混用，官方有 safe-upgrades VAP 守门）。

### 7.2 对象速览

| 对象 | 版本/渠道 | 一句话 |
|------|----------|--------|
| GatewayClass | `v1`（standard） | 「哪种实现」——控制器方部署，类比 IngressClass |
| Gateway | `v1`（standard） | 「在哪个端口听什么协议、什么证书」——平台方部署 |
| **HTTPRoute** | `v1`（standard） | L7 路由：match（hostname/path/header/method/query）+ filter + backendRef 多后端 + `weight` 权重 |
| **GRPCRoute** | `v1`（standard，v1.1 起 GA） | gRPC 专属 match（service/method） |
| **TCPRoute / UDPRoute** | **`v1`（standard，v1.6 起 GA）** | L4 直通，权重多后端 |
| TLSRoute | `v1alpha3`（experimental） | TLS passthrough/SNI 分流 |
| ReferenceGrant | `v1beta1`（standard） | **跨 ns 引用的显式授权书**（HTTPRoute 要指向别的 ns 的 Service/Gateway 引用别的 ns 的 Secret 时必须存在） |
| BackendTLSPolicy | `v1alpha3`（experimental） | 控制 Gateway ↔ 后端之间的 TLS（CA、SNI） |
| ListenerSet | standard（v1.5 起晋升） | 把超多的 listener 从 Gateway 里拆出来按 ns 管理 |

### 7.3 实战全流程（选 Envoy Gateway，命令可粘贴）

环境：一套 kind 或多节点集群（1.35+），已装 `kubectl`/`helm`。Envoy Gateway 当前稳定版 **v1.9.2**（官方 quickstart 同源；helm chart bundle 了 standard channel 的 Gateway API CRDs）。

```bash
# ① 装 Gateway API standard CRDs（显式锁版本；EG 的 chart 也自带一份兜底，但生产建议显式装）
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.3/standard-install.yaml
kubectl wait --for=condition=Established --all crd --timeout=60s

# ② 装 Envoy Gateway（helm chart oci 在 docker.io，不依赖 helm repo add）
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.2 -n envoy-gateway-system --create-namespace
kubectl wait --timeout=5m -n envoy-gateway-system deploy/envoy-gateway --for=condition=Available

# ③ 官方 quickstart（含 demo 应用 + GatewayClass(eg) + Gateway + HTTPRoute 一套）
kubectl apply -f https://github.com/envoyproxy/gateway/releases/download/v1.9.2/quickstart.yaml -n default
kubectl wait --for=condition=Programmed gateway/eg --timeout=90s || kubectl describe gateway/eg

# ④ 验证（kind/无 MetalLB 环境用 port-forward 走 Envoy svc，云上直接看 gateway.status.addresses）
export GATEWAY_HOST=$(kubectl get gateway/eg -o jsonpath='{.status.addresses[0].value}')
curl -s --header "Host: www.example.com" http://${GATEWAY_HOST:-127.0.0.1:8888}/get | head
# kind 备用：
ENVOY_SVC=$(kubectl get svc -n envoy-gateway-system \
  --selector=gateway.envoyproxy.io/owning-gateway-namespace=default,gateway.envoyproxy.io/owning-gateway-name=eg \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n envoy-gateway-system port-forward service/${ENVOY_SVC} 8888:80 &
curl -s --header "Host: www.example.com" http://127.0.0.1:8888/get
```

到这一步你已经走过「装 CRDs → 装实现 → GatewayClass/Gateway/HTTPRoute → 验证」的最小闭环。

#### 7.3.1 路径/header 匹配 + 灰度权重（canary 80/20）

```yaml
# 先准备两个版本后端（v1/v2），然后：
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
spec:
  parentRefs: [{name: eg}]
  hostnames: ["api.example.com"]
  rules:
  - matches:
    - path: {type: PathPrefix, value: /v1}
      headers: [{name: x-canary, value: "true"}]     # 精确匹配 header，先打给 v2
    backendRefs:
    - {name: api-v2, port: 80, weight: 100}
  - matches:
    - path: {type: PathPrefix, value: /}
    backendRefs:
    - {name: api-v1, port: 80, weight: 80}           # 主力 80%
    - {name: api-v2, port: 80, weight: 20}           # 灰度 20%
```

验证分流的正确姿势：**让两端返回体本身可区分**（实验 3.5 用两个 http-echo 后端做了完整统计），或用访问日志看 upstream cluster 命中比；闲时最直接的判据是 `kubectl describe httproute api-canary` 的 `ResolvedRefs=True` + 后端 Pod 的日志计数（`kubectl logs deploy/api-v1 | wc -l` 对比 `api-v2`）。

**为什么这么设计**：权重在 `backendRef` 上而不在 rule 上——意味着「同一 match 内部的版本分流」和「不同 match 走不同后端」是两件事，canary 与 AB 测试（header 灰度）共用一个对象模型。

#### 7.3.2 TLS terminate（secret 挂到 Gateway 上）

```bash
# 造一个自签 cert（实验用；生产换 cert-manager 下发的 Secret，结构一样）
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -subj '/CN=api.example.com' -addext 'subjectAltName=DNS:api.example.com' \
  -keyout /tmp/api.key -out /tmp/api.crt
kubectl create secret tls api-tls --cert=/tmp/api.crt --key=/tmp/api.key
```

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata: {name: eg}
spec:
  gatewayClassName: eg
  listeners:
  - name: https
    port: 443
    protocol: HTTPS
    hostname: api.example.com
    tls:
      mode: Terminate
      certificateRefs: [{kind: Secret, name: api-tls}]   # 同 ns 时无需 ReferenceGrant
  # 保留下方 HTTP listener 继续服务（quickstart 已有）
  - name: http
    port: 80
    protocol: HTTP
```

```bash
kubectl apply -f <上面的gateway.yaml>
kubectl -n envoy-gateway-system port-forward service/${ENVOY_SVC} 8443:443 &
curl -sk --resolve api.example.com:8443:127.0.0.1 https://api.example.com/get -o /dev/null -w '%{http_code}\n'   # 200
```

#### 7.3.3 状态判读（出事先看 status，不看日志）

| 该看的位置 | 关键 condition | 含义 |
|-----------|---------------|------|
| `kubectl describe gateway eg` | `Accepted=True` `Programmed=True` | 被控制器接管 + 数据面已下发 |
| `kubectl describe httproute <name>` | `Accepted` + `ResolvedRefs` | 挂载上了 + backendRef/parentRef 都解得开 |
| 跨 ns 引用失败后端 503 | `ResolvedRefs=False` + reason `RefNotPermitted` | 缺 **ReferenceGrant** |

### 7.4 与 Ingress 的迁移衔接（一段就好）

- Ingress API 稳定但已冻结（`Kubernetes-Ingress-部署与使用详解.md` §16 已述）；新平台直接 Gateway。
- 迁移路径：先并行搭 Gateway + 对应实现，业务按域逐个切 DNS/LB 指向 Gateway 地址；官方提供 `ingress2gateway` 作为**起点转换器**（生成 YAML 供人工审查，不可盲 apply）——控制器专有注解都需要人工对应到 HTTPRoute 的 filter/扩展。
- 不急着迁的集群：继续用 Ingress 没问题，网关演进以「新接入走 Gateway，存量慢慢平移」的节奏最稳。

---

## 八、常见生产问题清单（网络面）

| # | 症状 | 根因链 | 排查动作 | 处置 |
|---|------|--------|---------|------|
| 8.1 | 大规模下新建连接间歇 RST / `dial tcp: connect: cannot assign requested address` 一类 | **conntrack 表满或哈希冲突**；每个经过 ClusterIP/NodePort 的连接都写一条 conntrack，表满即丢（dmesg: `nf_conntrack: table full, dropping packet`）；UDP DNS 条目要等 30s 才回收最费表 | `conntrack -S`（看 `insert_failed`）；`sysctl net.netfilter.nf_conntrack_max net.netfilter.nf_conntrack_buckets`；`dmesg -T \| grep conntrack` | 双放大 max/buckets；上 NodeLocal（§5.4）根治 UDP DNS；应用 keep-alive 减少新建率 |
| 8.2 | 小包通、大包死（ping 通、TLS handshake 超时、下载卡死）；跨节点才出现 | **MTU 黑洞**：overlay 隧道往外套 50/20 字节头，Pod eth0 按 1500 发 → 中间某跳静默丢大包（PMTUD 被拦） | 节点用 iputils `ping -M do -s 1472/1372 对端PodIP`（实验 3.2）；`ip link` 看 Pod eth0 与外接口 MTU；对端抓包看大包有没有裸奔出去 | 显式把 CNI MTU 写成「外接口 MTU - 头」；修了也确保 PMTUD 所需的 ICMP 不被拦 |
| 8.3 | Service/Endpoint 多起来后 API 侧更新慢、规则同步以秒计 | **iptables 规则数 O(n) 膨胀**（Service+ endpoint 线性，万级时单包扫描与同步都变慢）；iptables kube-proxy 只做到了「最小变更集」而已 | `iptables -t nat -S KUBE-SERVICES \| wc -l`；指标 `kubeproxy_sync_proxy_rules_duration_seconds`（均值 >1s 是阈值信号） | 升 nftables 模式（GA v1.33）；或直接计划迁 eBPF（Cilium）；**别在 v1.37 新上 IPVS** |
| 8.4 | DNS 偶发 5s/10s/30s 超时，成功率随 QPS 波动 | **ndots × 重试 × UDP 竞争**：每次外名查询 3~4 倍展开 + UDP conntrack 30s 窗口内竞争 | §5.5 三板斧；看 `coredns_cache_hits_total` 与 `coredns_forward_*`；NodeLocal 装没装 | FQDN 尾点 / 调 ndots / NodeLocal（大集群三管齐下） |
| 8.5 | 「全集群只有我能上的网络」上线，结果**什么都没拦住** | **CNI 不支持 NetworkPolicy**：对象创建成功、数据面静默放行（Flannel 经典） | 判定 CNI：§6.3 表；在干净 ns 做 deny-all 测试（实验 3.4 第一步） | 换/补能 enforce 的方案（§6.3）；Flannel 就按官方三种补法上 |
| 8.6 | 双栈集群里某些 Service 只有一族可达 / 新 Service 分不到 v6 | **各族管线没全配**：apiserver `--service-cluster-ip-range` 只写了一族；kubelet `--node-ip` 没指定双栈；Pod CIDR 单栈 | `kubectl get svc <name> -o jsonpath='{.spec.clusterIPs}'`（看实际分到几族）；`kubectl get servicecidrs`；node.status.addresses | 按 §1.2 三类网段双栈齐配；Service 用 `ipFamilies: [IPv4,IPv6]` 显式声明（PreferDualStack 默认行为以「平台是否双栈」为先决） |
| 8.7 | Cilium（kube-proxy 替换模式）集群里 `curl 127.0.0.1:<NodePort>` 不通、`ss`/`iptables` 看不到监听 | **kube-proxy 已不存在**，NodePort 由 eBPF socket LB 提供：不绑端口、不写 iptables、不为回环提供服务 | 先 `kubectl get cm cilium-config -n kube-system \| grep kube-proxy-replacement`；Pod 侧用节点 IP/ClusterIP 测 | 这是正常行为不是故障（本仓库 `脚本与工具/Rancher部署文档.md` 所述）；迁移期注意两套 NAT 互不知情，切换瞬间存量连接全部重置 |
| 8.8 | `externalTrafficPolicy: Local` 的 LB 服务，部分节点被打爆/部分冷 | Local 模式**节点粒度均衡**：源 IP 保住了，但 LB 按节点健康检查结果分流量，节点间 Pod 数不均就倾斜 | 看 LB 健康检查（kube-proxy :10256/healthz）与每个节点端点数；滚动更新窗口观察 | 接受不均可加 Pod 反亲和/扩缩让端点均摊；或对均匀性要求高的服务回到 Cluster + 用 PROXY/protocol 类 LB 保源 IP |

---

## 九、实验 5 连（kind 多节点全部可复现）

> 环境：本机装 `kind`（v0.2x+）、`kubectl`、`helm`、`docker`。基线镜像版本以 kind 当期默认 k8s 版本为准（可用 `kind create cluster --image kindest/node:v1.37.x` 指定）。
> 约定：实验集群都叫 `net-exp`，实验 3.1/3.2/3.3+3.4/3.5 各用一套，做完即删。macOS 上 node 容器命令一律用 `docker exec <node容器>` 下钻。
> tcpdump/ipvsadm 若 node 镜像里没有：`docker exec -it <node> bash -c 'apt-get update && apt-get install -y tcpdump ipvsadm'`（ kindest/node 常见版本自带，缺了再装）。

### 实验 3.1 kube-proxy 抓链：iptables 看一眼，nftables/IPVS 对照一眼

**step 1：一套默认 kindnet（ iptables kube-proxy ）集群**

```bash
cat > /tmp/net-iptables.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes: [{role: control-plane}, {role: worker}, {role: worker}]
EOF
kind create cluster --name net-exp --config /tmp/net-iptables.yaml

kubectl create deploy web --image=nginx --replicas=3
kubectl expose deploy web --port=80
kubectl get svc web   # 记下 CLUSTER-IP，例如 10.96.10.100
```

**step 2：在 node 容器里抓链条（三处对应看）**

```bash
docker exec net-exp-worker iptables-save -t nat | grep -E 'KUBE-SERVICES|KUBE-SVC-|KUBE-SEP-|KUBE-MARK-' | head -30
# 你应看到三段：
#  ① KUBE-SERVICES: -d 10.96.10.100/32 ... -j KUBE-SVC-XXXXXXXXXXXXXXXX
#  ② KUBE-SVC-…: -m statistic --mode random --probability 0.33333333349 -j KUBE-SEP-…   （3 个 endpoint: 1/3、1/2、兜底）
#  ③ KUBE-SEP-…:  [-s <PodIP>/32 -j KUBE-MARK-MASQ] + [-p tcp -j DNAT --to-destination <PodIP>:80]

docker exec net-exp-worker iptables -t nat -L KUBE-SERVICES -n | grep '<你的CLUSTER-IP>'
docker exec net-exp-worker iptables -t nat -L <你的KUBE-SVC-链名> -n --line-numbers
```

**step 3：生成流量并看计数器**

```bash
kubectl run curler -it --rm --image=busybox --restart=Never -- sh -c 'for i in $(seq 1 30); do wget -qO- http://<CLUSTER-IP>/ >/dev/null; done'
# 再看各 KUBE-SEP 链的 pkts 计数是否均匀分布（随机不是轮询，30 次不会均分，别误判）
docker exec net-exp-worker iptables -t nat -L <你的KUBE-SVC-链名> -n -v
```

**step 4：对照 nftables 模式（当前的新选项）**

```bash
kind delete cluster --name net-exp
cat > /tmp/net-nft.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking: {kubeProxyMode: "nftables"}   # kind 文档允许 iptables/nftables/ipvs/none
nodes: [{role: control-plane}, {role: worker}, {role: worker}]
EOF
kind create cluster --name net-exp --config /tmp/net-nft.yaml
kubectl create deploy web --image=nginx --replicas=3 && kubectl expose deploy web --port=80

docker exec net-exp-worker nft list tables | grep -i kube
docker exec net-exp-worker nft list table ip kube-proxy | head -60     # 表名以你实际输出为准（双栈时 v4/v6 两张）
```

❗ nftables 与 iptables 并存于内核并不冲突，kube-proxy 只会用自己那一张——对照的要点是「**Service 表达方式**从链变成了 nftable 的 map/element」。

**step 5（存量对照/不推荐新用）：再看一眼 IPVS**

```bash
kind delete cluster --name net-exp
sed 's/kubeProxyMode: "nftables"/kubeProxyMode: "ipvs"/' /tmp/net-nft.yaml > /tmp/net-ipvs.yaml
kind create cluster --name net-exp --config /tmp/net-ipvs.yaml
kubectl create deploy web --image=nginx --replicas=3 && kubectl expose deploy web --port=80

docker exec net-exp-worker ipvsadm -Ln | head
# TCP  <CLUSTER-IP>:80 rr
#   -> 10.244.x.x:80  Masq 1 0 0   （默认调度器 rr；改 scheduler: sh 可看源地址哈希粘性）
docker exec net-exp-worker ip link show kube-ipvs0    # dummy 接口，ClusterIP 挂这里让 IPVS 能匹配
docker exec net-exp-worker ipset list | head          # NodePort/ClusterIP 经 ipset + 少量 iptables 进入 IPVS
```

记住 §4.2 的红线：**IPVS 已官方 Deprecated（v1.35 起），这个对照是为了认识存量系统，新集群别选它**。

**清理**：`kind delete cluster --name net-exp`

### 实验 3.2 跨节点抓包看封装（VXLAN 外层包）

**step 1：disableDefaultCNI + Flannel（VXLAN）集群**

```bash
cat > /tmp/net-flannel.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  disableDefaultCNI: true       # kindnet 不是 overlay，看封装必须换 flannel/cilium
nodes: [{role: control-plane}, {role: worker}, {role: worker}]
EOF
kind create cluster --name net-exp --config /tmp/net-flannel.yaml

# 双值守：kind 里 br_netfilter 模块有时不在；flannel ≥1.30 kubeadm 不再代查
for n in net-exp-control-plane net-exp-worker net-exp-worker2; do
  docker exec $n modprobe br_netfilter
done

kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
kubectl wait --for=condition=Ready node --all --timeout=120s
kubectl -n kube-flannel get pods
```

**step 2：起两个跨节点 Pod + 服务，拿流量**

```bash
kubectl create deploy web --image=nginx --replicas=2
kubectl expose deploy web --port=80
kubectl run cli --image=busybox --command -- sleep 3600
kubectl get pods -o wide   # 记下 web 的 PodIP 与所在节点、cli 所在节点；确保 cli 跨节点访问
```

**step 3：抓外层封装包（对照看内层）**

```bash
SVCIP=$(kubectl get svc web -o jsonpath='{.spec.clusterIP}')
PODIP=$(kubectl get pods -l app=web -o jsonpath='{.items[0].status.podIP}')

# 终端 A：在 cli 所在 node 的容器里抓 VXLAN 端口（flannel/Cilium 默认都是 UDP 8472；Cilium Geneve 是 6081）
docker exec net-exp-worker2 tcpdump -i any -nn -c 6 'udp port 8472'

# 终端 B：发起跨节点直连 Pod（看得到 VXLAN）与走 Service（先 DNAT 再 VXLAN）各一次
kubectl exec cli -- wget -qO- http://$PODIP/ >/dev/null
kubectl exec cli -- wget -qO- http://$SVCIP/  >/dev/null
```

**你要看到的关键证据**：

- tcpdump 里抓到的是 **node IP → node IP 的 UDP 8472**；解封装（`tcpdump -i any -nn -e -vvv udp port 8472`）能看到 **VNI=1** 的 VXLAN 头和真正的内层 **PodIP → PodIP**。
- 对照命令 `docker exec net-exp-worker2 ip -d link show flannel.1`（VXLAN 设备参数）与 `ip route`（其他节点的 /24 走 flannel.1）。
- 顺手验证 MTU 黑洞的边界（busybox 的 ping 不支持 `-M do`，用 node 容器里 Ubuntu 自带的 iputils ping 打跨节点 Pod IP）：
  ```bash
  docker exec net-exp-worker2 ping -M do -s 1372 -c 2 $PODIP      # 应通（封装内总包 ≈ 1450）
  docker exec net-exp-worker2 ping -M do -s 1472 -c 2 $PODIP      # 应败（1500 - VXLAN 50 装不下）
  kubectl exec cli -- ip link show eth0                            # 看 CNI 给 Pod 的 MTU 是不是 1450
  ```

**清理**：`kind delete cluster --name net-exp`

### 实验 3.3 Cilium + Hubble：eBPF 一眼流

**step 1：安装 Cilium（官方 kind 文档同源步骤，已核对）**

```bash
cat > /tmp/net-cilium.yaml <<'EOF'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking: {disableDefaultCNI: true}
nodes: [{role: control-plane}, {role: worker}, {role: worker}]
EOF
kind create cluster --name net-exp --config /tmp/net-cilium.yaml

helm repo add cilium https://helm.cilium.io/ && helm repo update
helm install cilium cilium/cilium --version 1.20.2 \
  --namespace kube-system \
  --set image.pullPolicy=IfNotPresent \
  --set ipam.mode=kubernetes
```

**step 2：装 cilium CLI（macOS 一行命令版本）并看状态**

```bash
CILIUM_CLI_VERSION=$(curl -s https://raw.githubusercontent.com/cilium/cilium-cli/main/stable.txt)
CLI_ARCH=amd64; [ "$(uname -m)" = "arm64" ] && CLI_ARCH=arm64
curl -L --remote-name-all https://github.com/cilium/cilium-cli/releases/download/${CILIUM_CLI_VERSION}/cilium-darwin-${CLI_ARCH}.tar.gz{,.sha256sum}
shasum -a 256 -c cilium-darwin-${CLI_ARCH}.tar.gz.sha256sum
sudo tar xzvfC cilium-darwin-${CLI_ARCH}.tar.gz /usr/local/bin && rm cilium-darwin-${CLI_ARCH}.tar.gz*

cilium status --wait     # 全绿：Cilium OK / Operator OK / Hubble（下一步点亮）
# （可选）跑连通性全测： cilium connectivity test
```

**step 3：开 Hubble 并 observe**

```bash
cilium hubble enable     # 打开 Hubble server + Relay（4244/4245）；需要 UI 加 --ui
HUBBLE_VERSION=$(curl -s https://raw.githubusercontent.com/cilium/hubble/master/stable.txt)
HUBBLE_ARCH=amd64; [ "$(uname -m)" = "arm64" ] && HUBBLE_ARCH=arm64
curl -L "https://github.com/cilium/hubble/releases/download/$HUBBLE_VERSION/hubble-darwin-${HUBBLE_ARCH}.tar.gz" | tar xz
sudo mv hubble /usr/local/bin/ && rm -f hubble

cilium hubble port-forward &    # 后台挂 hubble-relay
kubectl create deploy web --image=nginx --replicas=2 && kubectl expose deploy web --port=80
kubectl run curler --image=busybox --restart=Never --rm -it -- sh -c 'wget -qO- http://web/ >/dev/null'

hubble observe --last 20
# 你会看到 identity 维度（不是裸 IP）的三元组：<src identity> → <dst identity>  端口  verdict
hubble observe --verdict FORWARDED --last 10
hubble observe --protocol http --last 10     # L7 视角（有 L7 policy 后信息更多）
```

**清理**：`kind delete cluster --name net-exp`（hubble port-forward 进程会随集群失效退出，`kill %1` 兜底）

### 实验 3.4 NetworkPolicy 三板斧（复用 3.3 的 Cilium 集群）

**step 1：deny-all → 预计 curl 超时**

```bash
kubectl create deploy web --image=nginx --replicas=1 && kubectl expose deploy web --port=80
kubectl run good --image=busybox --labels=role=client --command -- sleep 3600

cat <<'EOF' | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny-ingress}
spec:
  podSelector: {matchLabels: {app: web}}
  policyTypes: [Ingress]
EOF

kubectl exec good -- timeout 5 wget -qO- http://web/ ; echo "exit=$?"   # 应为 timeout 非 0
```

**step 2：观测侧先看到 DROP 再放行**

```bash
# 终端 A：观测 DROP（验证 policy 的确被 enforce，而不是「CNI 静默放行」）
kubectl -n kube-system exec ds/cilium -c cilium-agent -- cilium monitor -t drop &
# 终端 B：再放行 client
cat <<'EOF' | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-client-to-web}
spec:
  podSelector: {matchLabels: {app: web}}
  policyTypes: [Ingress]
  ingress:
  - from: [{podSelector: {matchLabels: {role: client}}}]
    ports: [{port: 80, protocol: TCP}]
EOF

kubectl exec good -- timeout 5 wget -qO- http://web/   # 现在应通
hubble observe --pod default/web --last 10             # 能看到先 DROPPED 后 FORWARDED 的时间线
```

**step 3：反向验证「没被选中的不受影响」**

```bash
kubectl run rogue --image=busybox --command -- sleep 3600    # 没有 role=client 标签
kubectl exec rogue -- timeout 5 wget -qO- http://web/; echo "exit=$?"   # 应依然超时
kubectl delete netpol default-deny-ingress allow-client-to-web
```

> 实验收获：把 NetworkPolicy 从「对象被创建」号准到「数据面明确看到 DROP」——这一步在 §8.5 的事故里能救命。

**清理**：`kind delete cluster --name net-exp`

### 实验 3.5 Gateway API 全流程（对应 §7）

**step 1：fresh kind 集群 + CRDs + Envoy Gateway**

```bash
kind create cluster --name net-exp
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.3/standard-install.yaml
helm install eg oci://docker.io/envoyproxy/gateway-helm --version v1.9.2 -n envoy-gateway-system --create-namespace
kubectl wait --timeout=5m -n envoy-gateway-system deploy/envoy-gateway --for=condition=Available
kubectl apply -f https://github.com/envoyproxy/gateway/releases/download/v1.9.2/quickstart.yaml -n default
kubectl wait --for=condition=Programmed gateway/eg --timeout=90s

ENVOY_SVC=$(kubectl get svc -n envoy-gateway-system \
  --selector=gateway.envoyproxy.io/owning-gateway-namespace=default,gateway.envoyproxy.io/owning-gateway-name=eg \
  -o jsonpath='{.items[0].metadata.name}')
kubectl -n envoy-gateway-system port-forward service/${ENVOY_SVC} 8888:80 &
curl -s --header "Host: www.example.com" http://127.0.0.1:8888/get | head -3   # 200 + JSON 响应
```

**step 2：换一个后端两个版本，完成 canary 80/20（对应 §7.3.1 的 YAML）**

```bash
kubectl create deploy api-v1 --image=hashicorp/http-echo --port=5678 -- -text='{"v":1}'
kubectl create deploy api-v2 --image=hashicorp/http-echo --port=5678 -- -text='{"v":2}'
kubectl expose deploy api-v1 --port=80 --target-port=5678
kubectl expose deploy api-v2 --port=80 --target-port=5678

cat <<'EOF' | kubectl apply -f -
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata: {name: api-canary}
spec:
  parentRefs: [{name: eg}]
  hostnames: ["api.example.com"]
  rules:
  - matches: [{path: {type: PathPrefix, value: /}}]
    backendRefs:
    - {name: api-v1, port: 80, weight: 80}
    - {name: api-v2, port: 80, weight: 20}
EOF
kubectl wait --for=condition=Accepted httproute/api-canary --timeout=60s

# 统计分布（看 v1:v2 ≈ 4:1）
for i in $(seq 1 200); do curl -s --header "Host: api.example.com" http://127.0.0.1:8888/; done | sort | uniq -c
```

**step 3：header 灰度（同 host 全量走 v2）**

```bash
kubectl patch httproute api-canary --type=json -p='[{
  "op":"add","path":"/spec/rules/0","value":{
    "matches":[{"path":{"type":"PathPrefix","value":"/"},"headers":[{"name":"x-canary","value":"true"}]}],
    "backendRefs":[{"name":"api-v2","port":80,"weight":100}]
  }}]'
curl -s --header "Host: api.example.com" --header "x-canary: true" http://127.0.0.1:8888/    # 100% v2
```

**step 4（选做）：TLS terminate**——按 §7.3.2 造自签证书 + HTTPS listener + `curl --resolve` 验证；最后 `kubectl describe gateway eg` 看 `Programmed=True`。

**清理**

```bash
kill %1 2>/dev/null    # 收 port-forward
helm uninstall eg -n envoy-gateway-system
kubectl delete -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.3/standard-install.yaml
kind delete cluster --name net-exp
```

---

## 十、速查表 + 参考链接

### 10.1 一页速查

| 主题 | 命令 / 关键值 |
|------|--------------|
| Pod 卡 ContainerCreating | `kubectl describe pod` Events → `containerd` 日志 → `ls /etc/cni/net.d` / `/var/lib/cni/` |
| 当前 CNI 配置 | `ls /etc/cni/net.d/`（字母序最小生效）；`crictl pods` 看 sandbox |
| 三类网段 | Node（基础设施）/ Pod（--pod-network-cidr）/ Service（--service-cluster-ip-range）；`kubectl get servicecidrs`（多段分配器 GA v1.33） |
| ClusterIP 本质 | 不存在于任何网卡；只是 `KUBE-SERVICES → KUBE-SVC-* → KUBE-SEP-*` 的 DNAT 匹配条件 |
| kube-proxy 模式 | v1.37 默认 iptables；nftables GA v1.33、内核≥5.13、未来默认；**IPVS 已废弃（v1.40 默认关，v1.43 移除）** |
| 抓链 | node 上 `iptables-save -t nat \| grep KUBE-`；概率均衡 `statistic mode random probability`；nftables 用 `nft list table ip kube-proxy` |
| EndpointSlice | v1.21 GA；每片≤100（`--max-endpoints-per-slice`≤1000）；老 Endpoints **v1.33 Deprecated**、1000 行截断 |
| 流量上下车 | `externalTrafficPolicy: Local`（保源 IP，节点粒度均衡）；`internalTrafficPolicy: Local`（GA v1.26，只打本机端点） |
| 拓扑流量 | `trafficDistribution: PreferSameZone/PreferSameNode`（GA v1.33 锁定）；`PreferClose` 已旧（勿新用）；`topology-mode: Auto` 注解优先于字段 |
| kube-proxy 健康 | `:10256/healthz`（LB 摘节点依据）、`/livez`；超时窗口 2×syncPeriod；指标 `kubeproxy_sync_proxy_rules_duration_seconds` |
| DNS 部署 | Deployment coredns 2 副本软反亲和 + Service kube-dns（默认 10.96.0.10）；`kubectl -n kube-system get cm coredns` 看 Corefile |
| ndots:5 黑洞 | 少于 5 个点先按 search 展开 → A+AAAA 放大 3~8 倍；写 FQDN 尾点，或 `dnsConfig.options ndots:2` |
| NodeLocal | GA v1.18；169.254.20.10 链路本地；iptables 模式双监听（LocalIP+kube-dns ClusterIP），IPVS 模式只监听 LocalIP 且要改 kubelet `--cluster-dns` |
| NetworkPolicy 模型 | 选中即隔离（按方向）；AND 在 rule 内、OR 在 rule 间；`{}` = 全部对象；默认放行的是「未被选中的方向」 |
| NetworkPolicy 各 CNI | Flannel 不原生支持（必补）；Calico 全功能 + Staged/Global/FQDN；Cilium 全功能 + L7/FQDN |
| CNI 三大件 | Flannel（VXLAN 8472，简单）；Calico（{VXLAN、IPIP、BGP}×{iptables/nftables/eBPF/VPP}）；Cilium（eBPF，VXLAN 8472/Geneve 6081，Hubble 4244/4245，WG 51871） |
| MTU | VXLAN 减 50（1450）、IPIP 减 20（1480）；`ping -M do -s 1472/1372` 验证 |
| conntrack | `conntrack -S` 看 insert_failed；UDP DNS 条目 30s；内核 <6.1 有 Service 长连接 RST bug |
| Gateway API | 最新 stable **v1.6.3**；TCP/UDPRoute v1.6 起 GA 用 `v1`；standard vs experimental CRD 渠道；Envoy Gateway v1.9.2 官方 quickstart 步骤 |

### 10.2 关键要点（背诵版）

1. K8s 网络就三件事：**Pod IP（CNI）/ Service 负载均衡（kube-proxy+EndpointSlice）/ 域名解析（CoreDNS）**——NetworkPolicy 与 Gateway 是加固与外延。
2. 网络模型三原则：Pod 唯一 IP、跨节点免 NAT、节点 agent 可及所有 Pod；三类网段（Node/Pod/Service）两两不重叠；**Service CIDR 是虚拟的**（只存在于改包规则里），ServiceCIDR/IPAddress 多段分配器 **v1.33 GA 锁定**。
3. **CNI 是运行时（containerd/CRI-O）调的，不是 kubelet**；spec 1.1.0 五操作 ADD/DEL/CHECK/GC/VERSION + STATUS；`/etc/cni/net.d` 字母序最小生效；DEL 必须幂等；运行时先建 netns。
4. 选 CNI 先看三个问题：**要不要 NetworkPolicy？（Flannel 出局）要不要 overlay？（机房 BGP 直通 vs 云封装）团队是否能 hold eBPF？（Cilium 红利与代价同源）**。MTU 默认按「外接口 - 50/20」自动减，VPC 外 MTU 非 1500 时必须显式配置。
5. kube-proxy 三模式（v1.37）：iptables（默认）/ **nftables（GA v1.33、未来默认）** / IPVS（**已 Deprecated，别新建**）。ClusterIP = 虚拟 IP + DNAT；负载均衡是 `statistic probability` 随机非轮询；回程对称靠 conntrack。
6. EndpointSlice（v1.21 GA）取代 Endpoints：每片 100 端点、按 IP 族分片、控制器宁开新片减少广播；kube-proxy 端点聚合自动去重。
7. `externalTrafficPolicy: Local` 保源 IP 但节点粒度不均 + 本机无端点就丢；`internalTrafficPolicy: Local`（GA v1.26）节点内闭环；`trafficDistribution: PreferSameZone/Node`（GA v1.33）是 topology-aware 的正解，`PreferClose` 旧名、`topology-mode: Auto` 注解优先且趋旧。
8. CoreDNS 痛点 = **ndots:5 × A/AAAA × search 域 × 重试**：对外名字写 FQDN 尾点最省；NodeLocal（GA v1.18）消灭跨节点 DNS + UDP conntrack 竞争 + 长尾超时，大集群必装。
9. NetworkPolicy = **选中即隔离**；`policyTypes` 按内容推断；AND 在 rule 内 OR 在 rule 间；CNI 不支持 = **静默放行**（非报错），生产上线前必须做 deny-all 反向验证。
10. Gateway API 用**角色分层**（GatewayClass/Gateway/HTTPRoute）取代 Ingress 的单一对象；CRD 分 standard/experimental 渠道；v1.6 起 TCP/UDPRoute GA；迁移用 `ingress2gateway` 做起点但**必须人工审查**。

### 10.3 参考链接

| 主题 | 链接 |
|------|------|
| Cluster Networking（模型与三类网段、双栈要求） | https://kubernetes.io/docs/concepts/cluster-administration/networking/ |
| Service（类型、EndpointSlice 速查、trafficDistribution、ServiceCIDR） | https://kubernetes.io/docs/concepts/services-networking/service/ |
| Virtual IPs and Service Proxies（kube-proxy 三模式、nftables 差异、健康端口、traffic distribution） | https://kubernetes.io/docs/reference/networking/virtual-ips/ |
| EndpointSlices（分片策略、复制与去重、mirroring 弃用） | https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/ |
| DNS for Services and Pods（resolv.conf 样例、ndots、dnsConfig、search 上限） | https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/ |
| Using NodeLocal DNSCache（动机、iptables/IPVS 差异、manifest 变量） | https://kubernetes.io/docs/tasks/administer-cluster/nodelocaldns/ |
| Network Policies | https://kubernetes.io/docs/concepts/services-networking/network-policies/ |
| 门控查册：ServiceTrafficDistribution（v1.30 alpha / v1.31 beta 默认开 / v1.33 GA 锁定） | https://kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/ |
| KEP-3866：nftables kube-proxy（alpha v1.29 / beta v1.31 / **GA v1.33**） | https://github.com/kubernetes/enhancements/tree/master/keps/sig-network/3866-nftables-proxy |
| CNI 规范（当前 1.1.0：操作、配置、委托 IPAM、执行序） | https://www.cni.dev/docs/spec/ |
| CNI 官方插件仓（bridge/ptp/tuning/bandwidth/portmap/host-local…） | https://github.com/containernetworking/plugins |
| Flannel（README：不原生 NetworkPolicy；backends：VXLAN 8472/host-gw/UDP 8285） | https://github.com/flannel-io/flannel |
| Calico（关于页：数据面矩阵；选择最佳组网：VXLAN/IPIP/BGP/Canal） | https://docs.tigera.io/calico/latest/about/ 与 https://docs.tigera.io/calico/latest/networking/determine-best-networking |
| Cilium kube-proxy 替换（socket LB 依赖、切换与混部警告） | https://docs.cilium.io/en/stable/network/kubernetes/kubeproxy-free/ |
| Cilium 系统要求与防火墙端口（VXLAN 8472/Geneve 6081/WG 51871/Hubble 4244-45） | https://docs.cilium.io/en/stable/operations/system_requirements/ |
| Cilium kind 安装（disableDefaultCNI + helm + CLI + connectivity test） | https://docs.cilium.io/en/stable/installation/kind/ |
| Gateway API 官方文档与版本 | https://gateway-api.sigs.k8s.io/ 与 https://github.com/kubernetes-sigs/gateway-api/releases |
| Envoy Gateway quickstart（当前 v1.9.2） | https://gateway.envoyproxy.io/docs/tasks/quickstart/ |
| ingress2gateway（Ingress → Gateway 迁移起点转换器） | https://github.com/kubernetes-sigs/ingress2gateway |
| kind 配置（kubeProxyMode iptables/nftables/ipvs/none、disableDefaultCNI） | https://kind.sigs.k8s.io/docs/user/configuration/ |

> 下一章预告：`K8s-存储深入.md`（第 4 章）——网络层之下就是持久化：CSI 两组件、PV/PVC 生命周期、StorageClass、快照与扩容、本地存储与拓扑感知。网络这一章留给你的最后一个冷知识是：Storage 里的「拓扑感知」（WFFC + selected-node）与网络这一章的「topology 流量」（trafficDistribution）共用同一套 zone/node 标签语言，建议连着看。
