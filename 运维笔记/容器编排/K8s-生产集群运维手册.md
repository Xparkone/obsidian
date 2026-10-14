# K8s 生产集群运维手册

> 精通路线第 7 章：kubeadm 生产形态、搭建 L2 三节点集群、升级序列、证书与 CA 轮转、控制面调优参数、节点自运维（NPD/draino）、租户治理、灾备恢复编排、大集群设计约束
> 创建时间：2026-10-14
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37；v1.38 尚未发布，升级演练章节给出命令模板并标注「发布后执行」），文中标注「v1.xx 起 Beta/GA」均取自官方文档、KEP 或上游源码，执行时仍以你本地集群版本为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，APF/list-watch/5 分钟历史窗口直接引用不重讲）、`K8s-网络原理详解.md`（第 3 章，CNI 选型只给结论）、`K8s-安全加固详解.md`（第 5 章，PSA/Secret 静态加密/密钥轮换直接引用不重讲）。**本文同时是实验 L2（Multipass 三节点 kubeadm 集群）与 L3（破坏-恢复演练）的操作手册本体**（总纲：`学习/K8s-精通路线-总纲.md`）。

---

## 零、本文定位与边界

### 0.1 为什么必须亲手拥有控制面

用 K3s 或云托管集群时，控制面对你是个黑盒：你想知道 etcd 配额怎么判断、证书如何轮转、升级是按什么顺序滚——你都没地方看。而生产事故永远发生在黑盒里：**API 响应变慢、CSR 卡住、kubelet eviction 连环杀人、升级后静态 Pod 起不来**。前 6 章把对象机制、调度、网络、存储、安全、扩展都讲透了，这一章做一件事：**把「控制面」变成你亲手搭、亲手升、亲手修的东西**。原理不变，差别只在「全链路命令都出自你的手」。

```
你的生产集群问题，最终都会变成这几类：
  "kubeadm init 卡住/preflight 报错"      → 前置准备那一层（swap/sysctl/cgroup driver/镜像/端口）   §2 §10.1
  "节点 join 不上，hash 校验失败"         → discovery-token-ca-cert-hash 原理（CA 公钥钉住防 MITM）   §3.2
  "升级完，我手改的 extraArgs 没了"       → kubeadm upgrade 会重写静态 Pod 清单（配置漂移四坑之一）   §4.3
  "控制面证书还有 30 天过期怎么办"         → check-expiration/renew/静态 Pod 重启三件套               §5.2
  "metrics-server 拉不到 kubelet 指标"    → kubelet serving 证书自签 vs serverTLSBootstrap          §5.3
  "apiserver 429/504，watch 重连风暴"     → inflight/APF 叠合、goaway、etcd compaction 协同面        §6.1
  "节点 MemoryPressure 连环驱逐"          → kubelet eviction 默认表 + requests/limits 生产纪律       §6.4 §8.3
  "整机坏了，从 etcd 快照恢复的正确顺序"   → 恢复优先级表（先静态清单、再 etcd、再 RBAC webhook）     §9 §10
```

### 本文与实验 L2 / L3 的映射

| 总纲实验 | 本文对应章节 | 验证点 |
|---------|-------------|--------|
| **L2**（Multipass 三节点 v1.37 + 升级 v1.38） | §2 §3 → 实验 7.1；§4 → 实验 7.2 | 「从零搭一个三节点集群并完成一次 minor 升级」 |
| **L3**（破坏-恢复演练） | §5.2/5.3 → 实验 7.3（证书）；§6.4 → 实验 7.4（eviction）；§9.4 → 恢复编排 | 「etcd/证书/CNI/kubelet/磁盘/网络的逐个修复 runbook」 |

> 第 2、3 章的实验 2.x / 3.x 都在 kind 上跑；本章实验全部搬到 **Multipass VM** 上跑——这是生产形态与沙箱形态的第一次决分水岭。

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `K8s-etcd详解.md` | etcd 本体运维：快照备份/恢复 etcdctl 命令、NOSPACE 告警、defrag、性能参数 | 本文只讲 **apiserver → etcd 的协同面**（quota 判断、compaction 窗口、升级影响），不复述 etcdctl 细节 |
| `K3s-部署指南.md` | K3s 发行版差异（SQLite default、single binary、内置 addon） | 一句带过：本章是 **kubeadm 生产形态**，不是发行版对比 |
| `K8s-组件详解.md` | 各组件功能与端口总表 | 端口表只列 kubeadm 生产形态必须的（§2.6），组件功能不重复 |
| `Velero-Kubernetes备份恢复与迁移指南.md` | 备份/恢复/迁移全景（BSL/VSL、Data Mover、演练） | 只在 §9 一句衔接：「对象面备份走 Velero，本文管控制面本体」 |
| `监控/`（Prometheus/Victoria 部署篇） | 监控栈怎么部署 | 本文只讲 **控制面组件本身的指标与告警阈值**（§6.2），不讲部署 |
| `云服务/Multipass-使用指南.md` | Multipass 命令速查 | 实验 7.1 一句引用，不重复教程 |

> ❗ **版本标注约定**：文中形如「v1.37 默认开」「X 默认 400」「v1beta3 已移除」的说法均对照官方 docs（kubernetes.io）、command-line-reference 各页或 k/kubernetes release-1.37 源码（`cmd/kubeadm/app/constants/constants.go`、`pkg/features/kube_features.go`）逐条核实；个别字段（feature gate 默认值、镜像 tag）可能随 minor 漂移，落地前用
> ```bash
> kubectl get --raw /api/v1/nodes/<node>/proxy/configz | grep -iE 'featuregate|eviction|containerlog|maxpod' | head
> kubectl get cm kubeadm-config -n kube-system -o=jsonpath='{.data.ClusterConfiguration}'
> ```
> 再确认一次。

---

## 一、 kubeadm 生产形态全认识

### 1.1 kubeadm 做与不做的边界

kubeadm 的官方自我定位是「**cluster lifecycle 的最小构建块**」（GA，create-cluster-kubeadm 页原文）：它只负责「让集群能跑起来 + 维护 subset 的生命周期」，**之外的全部是你自己的运维面**。

| kubeadm 做（GA） | kubeadm 不做 |
|------------------|-------------|
| init/join 引导：TLS bootstrap、生成根 CA 与组件证书、写静态 Pod 清单、启动控制面、注册 Node 对象 | **不管理 CNI**（init 后 CoreDNS 都不 Ready 直到你装 CNI） |
| `kubeadm config`/`token`/`certs`：集群内对象（ConfigMap kubeadm-config、Secret kubeadm-certs、bootstrap token Secret）与 PKI 的运维子命令 | **不装 Ingress / LoadBalancer**（云厂商 cloud-controller-manager 或 MetalLB 自己来） |
| `kubeadm upgrade` 全流程（plan/apply/node/diff） | **不管监控栈**（Prometheus/metrics-server 都是 addon） |
| Reset node（`kubeadm reset`，best-effort 清干净 node 本机的 kubeadm 痕迹） | **不管 scope 外的 HA/LB**：1 node 罢了，3 个控制面 + LB 是你拼出来的（§3.1） |
| 把 InitConfiguration 写进 ConfigMap `kube-system/kubeadm-config`（供 join/upgrade 反查） | **不替你备份 etcd**（§9 的备份是你自己的纪律） |

> ❗ **反直觉的一条**：kubeadm init 时写在 InitConfiguration 里的字段（bootstrapTokens、nodeRegistration 等局部配置）**不会**上传到 kubeadm-config ConfigMap——ConfigMap 里只有 ClusterConfiguration。v1beta4 文档原话："This information IS NOT uploaded to the kubeadm cluster configmap, partly because of its sensitive nature"。想找某节点 init 时的局部配置，去学那台 kubeadm 节点上的 `/etc/kubernetes/admin.conf`、`pki/` 和节点本身的 hostname/criSocket。

### 1.2 六个命令族：一张图读完

```
                        ┌─ kubeadm init      ── 首台控制面（全文的主角）
       引导 / 搭集群 ───┼─ kubeadm join      ── CP join（--control-plane --certificate-key）/ worker join
                        └─ kubeadm reset     ── 干净退出（best-effort，需手工补 iptables/ipvs，见 §3.7）
        对象内省       ─── kubeadm config    ── print init-defaults / migrate 老 API 版本
        token 生命周期   ── kubeadm token     ── create / delete / list（24h TTL 默认）
        证书运维        ── kubeadm certs     ── check-expiration / renew all / generate-csr（§5）
                        ┌─ kubeadm upgrade plan  ── 检查可升版本 + 配置偏移
       升级  ───────────┼─ kubeadm upgrade apply ── 首台控制面升级（含 plan/apply/node/diff + UpgradeConfiguration API）
                        ├─ kubeadm upgrade node  ── 后续 CP // worker 单节点
                        └─ kubeadm upgrade diff  ── 本地清单 vs 目标版本的差
```

每条命令族后面挂着 Phase 机制：`kubeadm init phase <name>`（如 `phase certs all`、`phase kubeconfig all`、`phase etcd local`）——这是能把 kubeadm 当乐高拆着用的关键；`kubeadm certs generate-csr` 跟外部 CA 对接时就靠 phase 命令链拼装凭证（§5.1）。实验 7.1 会反复见到 `--skip-phases`/`--dry-run` 这类边角。

### 1.3 配置文件 API 版本时间线（v1beta3 → v1beta4 官方核实）

| API 版本 | 服役区间 | 退役版本 | 现行状态（v1.37，源码核实） |
|---------|---------|---------|------------------------|
| `v1beta1` | v1.13~v1.21 | **v1.22 移除** | 不能读 |
| `v1beta2` | v1.15~v1.26 | **v1.27 移除** | 不能读 |
| `v1beta3` | v1.22~v1.36 | **v1.37 移除** | release-1.37 源码 `cmd/kubeadm/app/apis/kubeadm/` 只剩 `v1`（internal）+ `v1beta4`，v1beta3 目录已删 |
| `v1beta4` | **v1.31 引入**，现行 | — | 现行唯一可用版本；官方原话「kubeadm v1.31.x and newer can be used to migrate from v1beta3 to v1beta4」 |

> ❗ **为何 v1beta3 上 v1beta4，不只是字符串变了**（v1beta4 的相对增量，逐条来自官方 v1beta4 页）：

| v1.31（v1beta4 首发） 改变 | 内容 |
|--------------------------|------|
| extraArgs 结构化（支持重复 flag） | 旧 `map[string]extraArgs` → 新 `[]Arg{name,value}` 结构化数组，**同名参数允许重复**（v1.31 起 v1beta4；旧 map 写法在 v1beta3 已废） |
| 新增 `ResetConfiguration` / `UpgradeConfiguration` | 首次可 `--config` 到 reset/upgrade |
| `InitConfiguration.dryRun` / `JoinConfiguration.dryRun` | 首次支持 dry-run |
| `ClusterConfiguration.encryptionAlgorithm` | RSA-2048（默认）/ RSA-3072 / RSA-4096 / ECDSA-P256；**v1.34 起再加 ECDSA-P384** |
| `ClusterConfiguration.dns.disabled` / `proxy.disabled` | init 时可禁 CoreDNS/kube-proxy addon |
| `certificateValidityPeriod` / `caCertificateValidityPeriod` | 默认 **8760h（1 年）/ 87600h（10 年）**；非 CA 证可配置 |
| `Timeouts` 结构（`controlPlaneComponentHealthCheck:4m`、`kubenetesAPICall:1m`、`discovery:5m`、`tlsBootstrap:5m`、`upgradeManifests:5m`、`etcdAPICall:2m`、`kubeletHealthCheck:4m`） | `ClusterConfiguration.timeoutForControlPlane` → `Timeouts.controlPlaneComponentHealthCheck`；`JoinConfiguration.discovery.timeout` → `timeouts.Discovery` |
| v1.33 增量 | `UpgradeConfiguration.plan.etcdUpgrade`（控制 plan 是否展示 etcd 升级） |
| v1.35 增量 | `ClusterConfiguration.etcd.external.httpEndpoints`（把 /metrics /health 等 HTTP 流量与 gRPC 分离，对应 etcd `--listen-client-http-urls`） |

### 1.4 v1beta4 配置文件逐字段精读（生产最小样例）

`kubeadm config print init-defaults` 打印官方默认字面值，但生产/实验我们直接给一份**可粘贴的完整样例**（实验 7.1 就是用它起的集群；字段已对照官方 v1beta4 页逐项核实默认值）：

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
bootstrapTokens:                # TTL 默认 24h；usages 默认 authentication+signing
  - token: "lz6t5a.f6n43pdcks1ew4u6"
    ttl: "24h"
nodeRegistration:
  name: "k8s-cp1"               # Node 对象名 + kubelet 客户端证 CN（nodeName 不进 ConfigMap）
  criSocket: "unix:///var/run/containerd/containerd.sock"   # 1.37 只支持 CRI 运行时
  taints: []                    # 不写时控制面自动打 control-plane taint；要允许工作负载则显式 taints=[]
  kubeletExtraArgs:             # []Arg 结构（v1beta4 起）
    - name: node-ip
      value: "10.0.0.11"
    - name: max-pods
      value: "110"
  ignorePreflightErrors: []     # 经典组合：IsPrivilegedUser,Swap；生产别用 all
localAPIEndpoint:               # 本台 apiserver 实例的对外平面
  advertiseAddress: "10.0.0.11"
  bindPort: 6443
# certificateKey:               # 32 字节 hex（kubeadm init 会回显 join 提示里那条 --certificate-key）
# skipPhases: / patches: / timeouts: 用在边角场景，本文默认交给 kubeadm 自动完成
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.37.0"            # 与 kubeadm 同一大版本（一致原则见 §4）
controlPlaneEndpoint: "k8s-cp1:6443"    # 若不上 HA 就写这台名（单 CP）/ 或写 LB DNS（3 CP）
networking:
  podSubnet: "10.244.0.0/16"            # 与 CNI 的 IPAM 段对应（§3.4 装 Cilium 时讲）
  serviceSubnet: "10.96.0.0/12"         # 默认；至少留 10 个 IP（源码最小约束 MinimumAddressesInServiceSubnet=10）
  dnsDomain: "cluster.local"
etcd:
  local:                                # stacked 形态（§3.1 选型表）；external 见该节
    dataDir: "/var/lib/etcd"
apiServer:
  extraArgs:
    - name: authorization-mode
      value: Node,RBAC                  # 官方允许覆盖默认配置的安全例外之一是这条组合（Node + RBAC 强制）
    - name: etcd-compaction-interval
      value: 5m0s                       # 与第 1 章「5 分钟历史窗口」是同一个 flag（§6.1）
  certSANs:                             # ★ 核心：SAN 里必须有 controlPlaneEndpoint
    - "k8s-cp1"                         # 个人实验 VM 名；生产写 LB FQDN + IP
    - "10.0.0.11"
controllerManager:
  extraArgs:
    - name: cluster-signing-duration
      value: 8760h0m0s                  # 默认（kubeadm v1.37 source: ClusterSigningDuration = 365d）
scheduler:
  {}                                    # 用默认 profile；要自定义调度策略走 KubeSchedulerConfiguration（第 2 章 §3）
certificatesDir: "/etc/kubernetes/pki"  # 默认；external-CA 模式见 §5.1
imageRepository: "registry.k8s.io"      # CI 构建或国内网络才改（实验 7.1 有 sandbox_image 国内加速技巧）
clusterName: "kubernetes"
encryptionAlgorithm: RSA-2048           # 默认；嫌不够可 ECDSA-P256/P384
certificateValidityPeriod: 8760h        # 默认 1 年（CA 是 10 年，没写就是默认）
# 证书有效期=1 年——这是「为什么必须会做 §5 的 renew」的直接原因
---
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
cgroupDriver: systemd                   # ★ 与 containerd 必须一致（§2.3 灾难案例）
maxPods: 110                            # 默认；大节点别随便放大（§6.4）
serializeImagePulls: true               # 默认串行拉镜像；大集群可开 maxParallelImagePulls
clusterDNS: ["10.96.0.10"]              # serviceSubnet 第 10 个 IP（kubeadm 源码 GetDNSIP 规则）
clusterDomain: cluster.local
authentication:
  anonymous: { enabled: false }
  webhook: { enabled: true }            # 默认：TokenReview（kubelet kubeconfig 里连着）
  x509: { clientCAFile: /etc/kubernetes/pki/ca.crt }
authorization:
  mode: Webhook                         # 默认（SubjectAccessReview）
serverTLSBootstrap: false               # 默认 false（kubelet serving 自签）；生产开启见 §5.3
rotateCertificates: true                # kubeadm 帮你写的就是 true（§5.3 的转动开关）
---
apiVersion: kubeproxy.config.k8s.io/v1alpha1
kind: KubeProxyConfiguration
mode: "iptables"                        # 默认（Linux 可 iptables/ipvs/nftables；Windows kernelspace）
clusterCIDR: "10.244.0.0/16"            # 必须与 networking.podSubnet 对齐（kubeadm 会自动配一致性）
```

**逐字段要盯住的生产要点**（每一条都是升级或 join 时的真实出血点）：

| 字段 | 为什么盯 |
|------|---------|
| `InitConfiguration.certificateKey` | 用 `--upload-certs` 把 K8s CA/front-proxy/etcd 家族 keys 上载 Secret `kubeadm-certs` 时用来加密的那把 AES-32 key；**源码默认 Token 有效 2 小时**（`DefaultCertTokenDuration = 2*time.Hour`），过期就只能再发一把新 key/新 token |
| `ClusterConfiguration.controlPlaneEndpoint` | 「换这个值」=换 kubeconfig 与所有组件的 endpoint；**单 CP 且后续可能上 HA 就必须一开始写**（create-cluster 页原话：不写 controlPlaneEndpoint 的单点集群不能平滑转 HA） |
| `ClusterConfiguration.apiServer.certSANs` | apiserver 自签证的 SAN 必须覆盖「用户未来从哪儿控这个 API」的所有形态：hostname、LB FQDN、VIP——改了 SAN 就得 renew + 重启 apiserver（§5.2 流程） |
| `nodeRegistration.kubeletExtraArgs` | v1beta4 起结构化 `[]Arg`；写在上层 `kubelet-config` ConfigMap 之外的**本机覆盖**（如 node-ip / max-pods），升级不会替你润色——这就是升级漂移的来源之一（§4.3） |
| `Certs` 家族面 | `certificatesDir` 默认 `/etc/kubernetes/pki`；`encryptionAlgorithm`/`certificateValidityPeriod` 只在新证书生成时生效（ renew 时读旧证书 attr，§5.2） |

> ❗ **InitConfiguration 的局部性**：从 kubeadm-config ConfigMap 反查配置时，只查得到 ClusterConfiguration。`nodeRegistration.criSocket / name` / `localAPIEndpoint` 都是写进节点本身（`/var/lib/kubelet/config.yaml`、`pki/...`）——这也是为什么 kubeadm 文档反复强调「这些字段 IS NOT uploaded」。

---

## 二、前置准备：每台机器开 kubeadm 之前都要过的 8 件事

本节全部在**裸 Ubuntu 24.04 VM**（实验 7.1 的 Multipass VM；生产换云主机/物理机同理）上按顺序执行。命令可粘贴。每项后面都写了「kubeadm preflight 会怎么查你」，对应 init 时的报错模板。

### 2.1 swap 必关（kubelet `failSwapOn=true` 默认）

```bash
sudo swapoff -a                             # 立即生效
sudo sed -i '/ swap / s/^\(.*\)$/#\1/' /etc/fstab   # 重启后也不回来
free -m | grep -i swap                      # Swap: 0 0 0
```

kubelet 配置字段 `failSwapOn` 默认 **true**（kubelet-config.v1beta1 页核实）：检测到有 swap **直接拒绝启动**——所以这不是「应该是关」，是「kubelet 起不来」。`ignorePreflightErrors: [Swap]` 可以糊弄过 preflight，但糊弄不过 kubelet 自己的 fail-on 检查。官方同时提醒：**v1.37 kubelet 只支持 cgroup v2**（cgroup v1 直接 `FailCgroupV1=true` 拒启动），swap 是同一层面的「基础设施闭环」纪律。

> ❗ 生产上有人想开 `LimitedSwap`（memorySwap.swapBehavior）利用 swap 抗哨兵——那是 Alpha/Beta 且改变 QoS 行为的方向，本章生产纪律仍是「关死」。

### 2.2 内核模块与 sysctl（bridged 流量必须过 iptables）

kubeadm 文档原话：「Most Kubernetes cluster networking implementations will change this setting (if needed), but some might expect the administrator to do it for them」——也就是个别 CNI 会自己写 sysctl，但**你要承担把它写进去并能自证的责任**。container runtimes 页只强制 `ip_forward`；kubeadm preflight 另外查 br_netfilter 与 bridge-nf-call-iptables：

```bash
# ① 内核模块（< 配置文件 > 每次开机也加载）
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
sudo modprobe overlay
sudo modprobe br_netfilter

# ② sysctl 关键键值：bridge 流量过宿主 iptables（CNI/kube-proxy 依赖）；IPv4 转发
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sudo sysctl --system

# ③ 验收（三项都要 == 1）
sysctl net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables net.ipv4.ip_forward
```

**为什么这么设计**：Pod 间的 bridged 二层流量默认走 bridge 自己的过滤链，**不进 netfilter 的 iptables**——而 kube-proxy 的 Service 规则、NetworkPolicy 全靠 iptables 接管。`bridge-nf-call-iptables=1` 拉起 `br_netfilter` 钩子，让 bridge 二层帧过一遍 iptables 链——这是所有 L2 CNI（flannel/host-gw 类）能 work 的隐形前提。

### 2.3 containerd 安装与 SystemdCgroup（运行时与 kubelet 必须同一个 cgroup driver）

cgroup driver 的官方规则（container runtimes 页）：**kubelet 与运行时同一个 driver**；systemd init 系统推荐 `systemd` 而不是默认的 `cgroupfs`——因为 systemd 本身已经是一个 cgroup manager，两个并存会在资源压力下出现「两套资源观点」的不稳定（官方: two views of available and in-use resources）。v1.37 起 kubelet 开门即启用 `KubeletCgroupDriverFromCRI`（Beta 默认开）：能从运行时 CRI 的 `RuntimeConfig` RPC **自动检测** driver 并覆盖 kubelet 自己的配置——**但 containerd 1.x 不支持该 RPC**，仍要靠手工对齐；v1.38 会删掉 fallback，老 containerd 直接 fail。所以现在的生产动作依然是「两边都写死 systemd」：

```bash
# ① 安装 containerd（Ubuntu 官方 repo 或 docker repo；版本建议 2.x）
sudo apt-get update && sudo apt-get install -y containerd

# ② 生成默认配置后改 key——CRI plugin disabled / SystemdCgroup / sandbox_image
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null

sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
# 排雷：不少官方包默认把 cri 加到 disabled_plugins（docs 原话「you may find that the CRI integration plugin is disabled by default」）
sudo sed -i '/^disabled_plugins/ s/^/# /' /etc/containerd/config.toml

sudo systemctl restart containerd && systemctl status containerd --no-pager | head -4
```

containerd 版本差异的 key 位置（官方逐版本给出）：
- **1.x**：`[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]` → `SystemdCgroup = true`
- **2.x**：`[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runc.options]` → `SystemdCgroup = true`

**灾难案例（cgroup driver 不一致）**：kubelet 里 `cgroupDriver: systemd` + containerd 用默认 `cgroupfs`（或反过来）——症状是容器起得来但 `opens`、CPU limit 的 quota cgroup 挂在两套树里，节点内存压力来时 kubelet 认为「Pod 没超限」、systemd 却认为已经超了——出现**容器无限 OOM 循环或 quota 被打到另一颗 cgroup 上**。这就是为什么 §1.4 样例把 `cgroupDriver: systemd` 直接写进 KubeletConfiguration：**一个值，两个系统共用**，别靠运气。

### 2.4 sandbox_image（pause 镜像）与海量国内镜像注意

kubeadm 在 init/join 阶段会拉一组镜像：`registry.k8s.io/kube-apiserver`、`kube-controller-manager`、`kube-scheduler`、`kube-proxy`、`coredns`、`pause`、`etcd`——版本对照由 kubeadm 源码常量决定（v1.37 源码核实：`DefaultEtcdVersion = "3.7.1-0"`、`CoreDNSVersion = "v1.14.7"`、`PauseVersion = "3.10.2"`）。sandbox_image 在 containerd 层单独控制（K8s 官方 sandbox image 现行是 `registry.k8s.io/pause:3.10`——container runtimes 页）：

```bash
# containerd 2.x：改 sandbox_image 指向可访问的 mirror，再重启
sudo sed -i 's#sandbox_image = "registry.k8s.io/pause:3.10[0-9.]*"#sandbox_image = "registry.aliyuncs.com/google_containers/pause:3.10"#' /etc/containerd/config.toml
sudo systemctl restart containerd

# 同样可以 kubeadm 层覆盖全局镜像仓库：ClusterConfiguration.imageRepository
# 国内常用：registry.aliyuncs.com/google_containers / m.daocloud.io/registry.k8s.io
kubeadm config images pull --image-repository registry.aliyuncs.com/google_containers  # 先预热
```

> ❗ 易混点：sandbox_image ≠ containerd pause ≠ kubeadm pause。kubelet allocate pod 时用 CRI 找 sandbox image，走的是 containerd 配置；kubeadm init 侧仅帮控制面静态 Pod 拉镜像。两者只要保证「运行时能拉到 pause 就行」——很多人被坑是因为改过 sandbox_image 但忘重启 containerd。

### 2.5 时间同步（chrony）：证书 notBefore/notAfter 校验的物理前提

API 证书轮转（§5）就是两个时间戳的游戏；apiserver 对 watch 的 RV 窗口、etcd 选举 timeout、leader lease（15s 默认）全都假设**集群时钟同步 ≤ 秒级**：

```bash
sudo apt-get install -y chrony && sudo systemctl enable --now chrony
chronyc tracking | grep -E 'Leap status|System time'   # Leap status: Normal
timedatectl set-timezone Asia/Shanghai                  # 看团队习惯，不强求
```

### 2.6 防火墙/安全组：控制面 vs worker 端口表（对照官方 required-ports 页）

官方只列「必须的」；vendor 附加（etcd metrics、BGP 等）你家环境再补。端口是 **TCP inbound**，自定义的话按你改的平移。

| 范围 | 控制面节点 | 用途 | 该放给谁 |
|------|-----------|------|---------|
| 6443 | ✅ | Kubernetes API server | 所有节点 + 管理员跳板 + LB |
| 2379-2380 | ✅ | etcd client API / peer 流量 | **仅**控制面节点（stacked）/ etcd 节点（external） |
| 10250 | ✅ | kubelet API（read-only 已禁用） | 控制面 ↔ 自身 node（metrics/logs/exec 都走这里） |
| 10259 | ✅ | kube-scheduler（HTTPS/healthz/metrics） | 仅控制面 + 监控 Prometheus |
| 10257 | ✅ | kube-controller-manager（HTTPS） | 仅控制面 + Prometheus |

| 范围 | worker 节点 | 用途 | 该放给谁 |
|------|------------|------|---------|
| 10250 | ✅ | kubelet API（同上） | 控制面 + 本机 + Prometheus |
| 10256 | ✅ | kube-proxy healthz | **仅** LB 健康探针 / 本机 |
| 30000-32767（TCP+UDP） | ✅ | NodePort 默认区间 | 就按「你的入口来源」来收 |

ufw 示例（worker 通用——控制面再加 6443/2379-2380/10257/10259）：

```bash
sudo ufw default deny incoming
sudo ufw allow from <公司出口段> to any port 22 proto tcp
sudo ufw allow 10250/tcp
sudo ufw allow 10256/tcp
sudo ufw allow 30000:32767/tcp; sudo ufw allow 30000:32767/udp
sudo ufw enable
```

> ❗ 云主机场景：上面 ufw 之外还有一层 security group 也要同步放行（6443 只给 API 消费方、2379-2380 只给控制面段）。第 3 章《网络原理详解》讲了 NodePort 的连回路径，这里只守端口面。

### 2.7 其余一票否决项（preflight 见它们就炸）

- **`SELinux=permissive / disabled`**：RHEL/CentOS 要 `setenforce 0` + `/etc/selinux/config` 持久化（Ubuntu AppArmor 默认不影响 kubeadm）。
- **`containerd cri plugin 不在 disabled_plugins 里`**（§2.3 已讲）。
- **`/run/containerd/containerd.sock` 存在且 kubelet 能连**：`crictl --runtime-endpoint unix:///var/run/containerd/containerd.sock info | grep -E 'NAME|CONTAINER_RUNTIME'`，kubeadm init 会用同一 socket。
- **内核版本**：containerd 2.x 需要 linux ≥ 4.x + cgroup v2 mount（runc 2.x 要求）——1.37 起 kubelet 直接 `FailCgroupV1`。

### 2.8 安装 kubeadm / kubelet / kubectl 三件以及 hold

官方包源已经迁到 `pkgs.k8s.io`（旧的 `apt.kubernetes.io/yum.kubernetes.io` 自 2023-09-13 deprecated，换源是运维必修），每个 minor 一个目录：

```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gpg
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key | \
  sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.37/deb/ /' | \
  sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl    # ★ 别被 unattended-upgrades 偷袭
kubeadm version -o short    # 期望 v1.37.x；kubelet 此时会以 crashloop 等待 kubeadm 下发任务，是正常现象
```

> ❗ **hold 的意图**：`kubeadm upgrade` 要求 kubeadm 版本与集群之间的 skew 满足「kubeadm ≥ 控制面 或同 minor +1」（§4.1）；`apt upgrade` 一次性跳过多个 minor 就直接踩进不支持区间，所以在所有节点 hold——升级时手工 `apt-mark unhold` 是唯一的运维入口。

---

## 三、搭建：1 control-plane + 2 worker

### 3.1 stacked etcd vs external etcd 选型（HA 拓扑官方二选一）

官方 ha-topology 页明确只有两种：**stacked**（etcd 与控制面同机，kubeadm 默认）与 **external**（etcd 独立三台）。选型维度一览：

| 维度 | stacked（默认） | external |
|------|----------------|----------|
| 最小节点数 | 3（3 CP） | 6（3 CP + 3 etcd） |
| 故障耦合 | 一台 CP 挂=丢一个 etcd member + 一个 APIServer → 冗余度双倍受损 | 解耦：CP 挂只累 CP，etcd 挂只累 etcd |
| 资源占用 | etcd 与 CP 争内存/磁盘 IO | etcd 独占 SSD/内存，路径最短 |
| 运维成本 | kubeadm init/join 一条命令起，etcd 由 kubeadm 自动生命周期管理 | etcd 由你另一个工具起（kubeadm 支持，但需手工先搭好 etcd 集群）；外部证书准备复杂 |
| 备份/恢复 | 与 k8s 对象一锅端（快照 + 回同一个 member） | 可以独立轮换 etcd、独立 SLA |
| 升级影响 | kube-apiserver 升级要 stall 一下（§4.3 官方 etcd stall 提醒） | etcd 与 apiserver 互不再生 |
| 适用 | 中小集群（<100 节点）、没钱/碰不上 Graphana 那类级负载 | 大集群/合规苛刻/想单独调 etcd 磁盘 I/O 的场景 |

**生产立场**：先用 stacked 3 CP；超过万级节点/要求 etcd 单独磁盘 SLA 再切 external。**本文实验 7.1 是 1 CP（stacked 单点）**——L2 重在把 kubeadm 流程吃透，HA join 的命令差异只在 `join --control-plane --certificate-key`（§3.3）。

### 3.2 kubeadm init：首台控制面

```bash
# ① 上节表 2.8 装好 kubeadm + 配置文件（§1.4 样例）就位
# ② init（关键参数已写进 config；--upload-certs 是为多 CP/HA 预留）
sudo kubeadm init --config kubeadm-config.yaml --upload-certs

# ③ 输出里三行是钱：
#    mkdir/cp/chown  → 普通用户连 API
#    kubeadm join <cp-endpoint> --token <TOKEN> --discovery-token-ca-cert-hash sha256:<HASH> [--control-plane --certificate-key <KEY>]
#    这两段（token + hash + 可选 certificate-key）就是 join 的全部门票
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# ④ 安装常规工具
kubectl get pods -n kube-system
```

`--upload-certs` 的机制（官方 kubeadm-certs 页 + 源码）：

- kubeadm init 把三类「**控制面间需共享**」的 key（`pki/ca.key`、`pki/front-proxy-ca.key`、`pki/etcd/ca.key`，以及 `pki/sa.key` 这 SA 密钥——加上对应 cert）AES-256-GCM 加密后写入 Secret `kube-system/kubeadm-certs`；
- 加密 key 是 InitConfiguration 里的 32 字节 hex `certificateKey`（1.37 源码 `CertificateKeySize = 32`）；
- Secret 由 `bootstrap token signer` 打上 TTL，**有效期 2h**（`DefaultCertTokenDuration`）——过期就发新 token + 新 key；
- 后续 `kubeadm join --control-plane --certificate-key <key>` 的 CP 解密该 Secret 拿走同一套 CA，从而静态 Pod 清单能直接用这些 cert 起 kube-apiserver。

v1beta4 样例已含 `controlPlaneEndpoint: "k8s-cp1:6443"` 与 `certSANs`——两者一起回答「将来从哪、用什么身份来连 API」：

- `controlPlaneEndpoint` 写进所有 kubeconfig/kube-cert SAN，单点将来迁 HA 必须从头就写——官方原话「Turning a single control plane cluster created without --control-plane-endpoint into a highly available cluster is not supported by kubeadm」；
- `certSANs` 是你未来 LB/跳板/VPN FQDN 的预留位——写少了后面就得 renew + 重启 apiserver 补 SAN。

### 3.3 token + discovery hash：join 节点的防 MITM 原理

bootstrap token（格式 `abcdef.abcdef0123456789`，Secret 存于 kube-system）是 kubelet 「TLS bootstrap（第 5 章 §TLS bootstrapping 页）」的第一身份。此时新节点**还没有任何证书**，它要验证「我对面的 apiserver 是不是我老板」——靠 `--discovery-token-ca-cert-hash sha256:<hash>`：

- CA 公钥钉住（v1beta4 页原话「specifies a set of public key pins to verify when token-based discovery is used; the root CA found during discovery must match one of these values」）；
- hash 是「**CA 证书 DER 编码 SPKI 的 SHA-256 十六进制**」——在控制面节点现场可算：

```bash
openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
  openssl rsa -pubin -outform der 2>/dev/null | \
  openssl dgst -sha256 -hex | sed 's/^.* //'
# 与 kubeadm init 输出的 --discovery-token-ca-cert-hash sha256:<HASH> 必须一致
```

**为什么这么设计**：

- token 本身只是「 authn as system:bootstrappers 」的一张低权限入场券；有了它你能拿 `cluster-info` ConfigMap（kube-public），但**它不含签名防篡改**；
- hash 把「cluster-info 里的 CA 公钥」钉死——即使有人劫持网络伪造 cluster-info，hash 不匹配 kubeadm join 直接拒绝，从而**TOKEN 泄漏不可被换 CA 利用**（MITM 挡死）；
- `unsafeSkipCAVerification: true` 只允许在「内网/实验/有别的带外验证」时用，生产严禁（官方原话：can weaken the security of kubeadm since other nodes can impersonate the control-plane）。

token 过期了、证书泄露了怎么办？两条命令重建：

```bash
kubeadm token list                                # 查剩余 TTL
kubeadm token create --print-join-command         # 重发一个完整 join 命令（新 token + 旧 hash）
kubeadm token delete <TOKEN>                      # 废弃旧 token（协商期满也可）
```

join 命令本体（控制面/worker 差别仅一个 flag）：

```bash
# worker
sudo kubeadm join k8s-cp1:6443 --token $TOKEN --discovery-token-ca-cert-hash sha256:$HASH

# 第 2 台/第 3 台 CP（HA 时；先如 §3.1 备好 etcd 想清楚了再 join）
sudo kubeadm join k8s-cp1:6443 --token $TOKEN --discovery-token-ca-cert-hash sha256:$HASH \
    --control-plane --certificate-key $CERTKEY
```

join 完之后 kubelet 会自动 TLS bootstrap 拿 client 证书，「Ready」状态由 **CNI ready** 决定——下一步装 CNI。

### 3.4 装 CNI：选 Cilium 的一句话

第 3 章《网络原理详解》§4 对比过 Cilium/Calico/Flannel/Istio-CNI——**本章选 Cilium**：eBPF 数据面 + Hubble 免装 sidecar 可见性已经把它从「选项之一」抬到「运维默认」。最小安装命令（与第 3 章实验保持同一版本）：

```bash
helm repo add cilium https://helm.cilium.io/ && helm repo update
helm install cilium cilium/cilium --version 1.20.2 \
  --namespace kube-system \
  --set image.pullPolicy=IfNotPresent \
  --set ipam.mode=kubernetes
cilium status --wait        # 第 3 章已教怎么装 cilium CLI；全绿：Cilium OK / Operator OK
kubectl get nodes           # CNI ready 之前对应 Node 是 NotReady；CNI 起来之后全部 Ready
```

> ★ 注意 §1.4 样例的 `networking.podSubnet: 10.244.0.0/16` 与 Cilium 的 IPAM（kubernetes 模式时直接吃 kadm 下发的 node.Spec.PodCIDRs）呼应——CNI 自己能躲开宿主机网段的合需要靠你提前在 init 时就规划好（create-cluster 页「Pod network must not overlap with any of the host networks」）。

### 3.5 验证集群真正的姿势：`kubectl get cs` 已 deprecated

**不要再 `kubectl get componentstatuses`**（`kubectl get cs`）：官方 v1.19 changelog 明确 deprecated——它报的「Healthy」只对与 apiserver 同机的 scheduler/controller-manager 成立，在非暴露健康端口的形态下根本不准确。替代姿势分三层：

```bash
# ① apiserver 本体 fine-grained readyz（含 etcd + +poststarthooks）
kubectl get --raw='/readyz?verbose' | head -20
# etcd ok, poststarthook/start-kube-apiserver-admission-initializer ok ...（对照第 1 章 §9 readyz 判度）

# ② 各控制面静态 Pod 是否 Running（这是「用户视角」的真实）
kubectl -n kube-system get pods -l tier=control-plane -o wide

# ③ 事件（还是排查首选）
kubectl get events -A --sort-by='.lastTimestamp' | tail -5
```

### 3.6 静态 Pod 清单：控制面四大件是 kubelet 直接管的 Pod

**心智模型**：控制面四大件（kube-apiserver / kube-controller-manager / kube-scheduler / etcd）**不是 Deployment、不归 apiserver 管**——它们以「静态 Pod 清单」形式写在控制面节点的 `/etc/kubernetes/manifests/*.yaml`，由 kubelet 的 static pod manager 直接拉起：

- kubelet 每 20s 扫一次目录（kubelet 配置 `fileCheckFrequency: 20s` 默认）；
- 清单内容变了 → spec hash 变 → **kubelet 直接重建对应 Pod**；=v1.37 audit 页原话 「All containers are restarted after upgrade, because the container spec hash value is changed」；
- 你能在 `kubectl get pods -n kube-system` 里看到它们，是因为 kubelet 以「mirror Pod」反馈到 API——修改/删除这些 Pod 对象**不影响实际进程**，只有清单文件认了才算；
- 相应的运维语法是：
  ```bash
  # ① 改 extraArgs / 证书 / 资源——直接 e.g. vim /etc/kubernetes/manifests/kube-apiserver.yaml
  # ② kubelet 检测到变化，20s 内把 apiserver 重启；期间你能 ls manifests 目录看到时间戳变化感
  # ③ 这就是 §5.2 renew 证书后为什么要「把清单移走再移回来」restart——动态 reload TLS 证书还不支持
  ```
> ❗ 同一目录的反面教训：在清单里塞个「你的钩子 Deployment 替代版研究品」会以「文件夹内所有 yaml 都变 static pod」的方式被 kubelet 反复拉起——**manifests 目录里的文件有结构性约束，`readinessProbe`/选「同样的 name」误配会造成 kubelet apiserver 倒台**；生产管控目录给 git 管起来。

> 📎 到此为止你已经有了 1 CP + 2 worker 的最小拓扑：`kubectl get nodes` 应三行全 Ready。多 CP 的扩展只多一条 join + etcd 拓扑想好（§3.1），剩下的都是第 4~9 章的运维期内容。

---

## 四、集群升级：谁也躲不开的运维最重磅动作

### 4.1 版本偏差政策（v1.37 官方 version-skew-policy 页逐项核实）

| 组件 | 允许的 skew | 本轮升级里你该记住 |
|------|------------|-------------------|
| kube-apiserver（HA） | 新旧实例 **同版本 ±1 minor** | 第一台升完 1.37，剩下可在 1.36/1.37 |
| kubelet | 不比 apiserver 新；可比它老 **≤3 minor**（kubelet ≥1.25 才允许 3） | apiserver=1.37 → kubelet 可 1.34~1.37；**1.37 里 kubelet 若长期落后 3 个 minor，升控制面前必须先补 |
| kube-controller-manager / kube-scheduler / cloud-controller-manager | 不比 apiserver 新；可老 **≤1 minor** | 与 apiserver 同批升是常规动作 |
| kube-proxy | 不比 apiserver 新；可比它老 ≤3；与 node 上 kubelet ±3 | 升级时 DaemonSet image tag 由 kubeadm 同步拉平 |
| kubectl | apiserver **±1 minor** | 你 Mac 上的 kubectl 比集群老/新一档都在支持区间 |
| kubeadm | kubeadm 可部 ≥kubelet；**kubeadm vs 控制面同级或 +1**；kubeadm vs kubeadm join 时同 minor | 升完后 join 新节点必须 ≥「最后一次 init/upgrade 用到的 kubeadm minor」 |
| etcd | kubeadm 源码 v1.37 SupportedEtcdVersion 表：K8s 1.35/1.36/1.37 → **`3.7.1-0`**；external etcd 最小 `3.5.24-0` | 外部 etcd 升级走 etcd 自己的 runbook（你管）；etcd 快照 restore 支持同 major.minor、不同 patch |

「**升组件顺序**」是官方写死的（顺序错了不保证工作）：

```
① 先升所有 apiserver 实例（HA 下可在 1.36 与 1.37 之间并存的窗口期）
② kube-controller-manager / kube-scheduler / cloud-controller-manager（彼此任意顺序/可并行）
③ kubelet（或留老版本，走 §4.2 drain 序列）
④ kube-proxy（DaemonSet，由 kubeadm upgrade apply 同步）
```

官方另外给了两条「升级前好习惯」：
- **把你现在的 minor 升到最新 patch 再升下一个 minor**——直接覆盖最多回归修复；
- 升级期间 admisson webhook 必须能 handle 新 REST 资源和字段（matchPolicy: Equivalent 的 webhook register 是最稳的默认）。

### 4.2 升级序列：首台 CP 先行，逐 CP、逐 worker

「一次过三台」是新年时爽文的写法——生产的 kubeadm upgrade 有明确节奏：**首台 CP 用 `apply`，后续 CP 用 `node`，worker 逐个 `drain→升包→uncordon`**。

**首台控制面节点（完整命令序列）**：

```bash
# ① 替换 apt 仓库里的 v1.36 → v1.37（pkgs.k8s.io 的 per-minor 目录）＋解 hold 装新 kubeadm
sudo sed -i 's|core:/stable:/v1.36|core:/stable:/v1.37|' /etc/apt/sources.list.d/kubernetes.list
sudo apt-mark unhold kubeadm
sudo apt-get update && sudo apt-get install -y kubeadm='1.37.x-*'
sudo apt-mark hold kubeadm
kubeadm version -o short

# ② 升级 plan（检查集群兼容/列出可升版本），加 --config 也可带 UpgradeConfiguration
sudo kubeadm upgrade plan
# 期望输出：Suffix / v1.37.x AND 各 addon 对应版本，以及「配置是否漂移」的表格
sudo kubeadm upgrade diff v1.37.x    # 想看清单差；生产必修一步

# ③ 升级 control plane（会用 Systemd 重新 drop、重写静态清单）
# （官方小贴士：stacked etcd 若包含 etcd 升级，apiserver 升级期间会 stall 几秒——可提前
#  killall -s SIGTERM kube-apiserver && sleep 20 让在飞请求先出，再 kubeadm upgrade）
sudo kubeadm upgrade apply v1.37.x
# 成功标志：[upgrade/successful] SUCCESS! Your cluster was upgraded to "v1.37.x".

# ④ kubeadm 21批次同时把 kubeadm-config ConfigMap 也更新（其它 CP 的 join 基准）
kubectl get cm kubeadm-config -n kube-system -o=jsonpath='{.data.ClusterConfiguration}' | head -1

# ⑤ 升级这台的 kubelet/kubectl（升级 kubelet 前必须 drain）
kubectl drain k8s-cp1 --ignore-daemonsets
sudo apt-mark unhold kubelet kubectl && \
sudo apt-get install -y kubelet='1.37.x-*' kubectl='1.37.x-*' && \
sudo apt-mark hold kubelet kubectl
sudo systemctl daemon-reload && sudo systemctl restart kubelet
kubectl uncordon k8s-cp1
kubectl get nodes k8s-cp1       # Ready，version 已是 v1.37.x
```

**后续 CP 节点**：与上述同序，只是第 ③ 步改为 `sudo kubeadm upgrade node`（取得 kubeadm-config 内容后刷新静态清单；不再需要 plan / CNI 升级）。

**worker 节点（逐台；一次别太多台，保证业务副本够用）**：

```bash
# 在该 worker 上装新版 kubeadm 后
sudo kubeadm upgrade node
kubectl drain <worker> --ignore-daemonsets
sudo apt-mark unhold kubelet kubectl && sudo apt-get install -y kubelet='1.37.x-*' kubectl='1.37.x-*' && \
sudo apt-mark hold kubelet kubectl
sudo systemctl daemon-reload && sudo systemctl restart kubelet
kubectl uncordon <worker>
```

**收尾**：

```bash
kubectl get nodes                                    # 全部 Ready、版本齐
curl -sk https://<controlPlaneEndpoint>:6443/version | jq -r .gitVersion   # API 本体
kubeadm certs check-expiration                       # upgrade 同时自动 renew 过（除非传了 --certificate-renewal=false）
```

### 4.3 升级四大坑与相应预案（生产真实出血点）

| 坑 | 为什么发生 | 预案 |
|----|-----------|------|
| **升级前没备份 etcd** | kubeadm upgrade 只备份本机 etcd（写入 `/etc/kubernetes/tmp/kubeadm-backup-etcd-<ts>`，官方升级页），**它不能替你的集群级快照** | 升前快照 + 离节点拷贝（§9）+ Velero 备份快照（对象面）；etcd restore 流程提前演练 |
| **CNI/CSI 未对齐新版本** | kubeadm 不管 CNI/CSI（§1.1 边界） | 升级当周读 CNI/CSI release notes；先升级 CNI 再升 K8s 或者反过来，按你家的兼容表走 |
| **CRD/准入语义变了** | 新 minor 会引入新字段/砍旧字段；自研 Operator 会 CRD reconcile 卡死 | 升级前 `kubectl get crd` 逐一审；**storageversion 迁移**（K8s-API机制 §3）；CRD 先于集群升级 |
| **静态 Pod 手工塞的 extraArgs 冲掉** | kubeadm upgrade 会重写 `/etc/kubernetes/manifests/kube-apiserver.yaml` 等——**你直接在清单里塞的 `--feature-gates` 或资源配额会丢** | 所有定制必须写进 **ClusterConfiguration.apiServer.extraArgs**（init 时）组件级 extra volumes；顺带用 `kubeadm upgrade diff` 在升级前把差异打成 review 材料 |
| etcd upgrade 期间 apiserver stall | stacked etcd 升级瞬间 kube-apiserver 等 etcd；HA 下受 LB 健康探针遮掩 | 官方 tip：`killall -s SIGTERM kube-apiserver && sleep 20` 先优雅断，避免 stall 叠加（§4.2 注释已含） |

> ❗ 升级期间所有容器都会被重启（spec hash 变），运行时的「short-lived/managed-by-none」一次性容器要事先跟业务对齐；kubelet minor 升级不能「in-place」——官方明确「Before performing a minor version kubelet upgrade, drain pods from that node」。

### 4.4 思想实验：HA 控制面升级期间 API 还有吗？

假设 3 台 CP（stacked）+ 一个 LB。升级序列按 §4.2 跑：

- 升 CP1 时 kubeadm 把 CP1 的静态清单拉走，API 出局——**LB 的 10259/6443 健康探针发现 CP1 挂掉，把流量切到 CP2/CP3，业务上 API 一直可用**；
- etcd 奇数集群（3 member）：CP1 的 etcd 停掉只剩 CP2/CP3 时正好多余 2 个权限——是少数派可用性（3 个 member 坏 1 个 OK）；
- CP1 回装新版回来 → apiserver/CM/scheduler 在 1.37、其它两还在 1.36——官方允许（新版本 vs 旧版本差 1 minor）；
- 升级 etcd（stacked）：单个 member 轮流滚，**事件发生的那 2 秒受 LB 遮掩**；
- **唯一的不可中断性复核点：LB 健康探针本身要能在 10 秒内判定「该 CP 已挂」**。如果你 LB 把「6443 TCP 能通」当作探针而不是 `/readyz`，就会在 20 秒级差里把正在重建的 apiserver 流量踢回去——所以生产 **LB 探针必须直接打 `/readyz`**（或者按 §6 的 goaway+shutdown-delay-duration 优雅摘除）。

HA 的本意就在这儿：**单机升级产生的不可用秒数，被 LB 遮掉了**——这就是为什么生产永远是 3 个 CP。

---

## 五、证书与轮转（HA 运维重头戏）

### 5.1 四把根 CA + SA 密钥对：kubeadm 生成的证书家谱

kubeadm init 在 `/etc/kubernetes/pki` 下生成 **3 个 CA 根**：`ca.crt/ca.key`（CN=kubernetes）+ `etcd/ca.crt`（CN=etcd）+ `front-proxy-ca.crt`（CN=front-proxy）——以及一对重要的「**SA 密钥对**」`sa.key/sa.pub`（不是 CA，是 ServiceAccount JWT 的 sign/verify 密钥）。每把 CA 下辖若干叶证书，整场关系图：

```
(ca.key / ca.crt                                                                    SA 密钥对  sa.key/sa.pub
 CN=kubernetes)              kubeconfig 证书（在 /etc/kubernetes 根目录）                       sa.pub 给 apiserver
    │                                                                                         sa.key 只给 CM 签 token
    ├── apiserver.crt/key            O:-            CN=kube-apiserver      SAN: 节点/endpoint/k8s svc
    ├── apiserver-kubelet-client     O=system:masters      CN=kube-apiserver-kubelet-client  → apiserver→kubelet 的客户端证
    ├── admin.conf                   O=kubeadm:cluster-admins   CN=kubernetes-admin          (bind cluster-admin；你日常 kubectl)
    ├── super-admin.conf             O=system:masters     CN=kubernetes-super-admin          (仅 kubeadm init 节点，破glass)
    ├── controller-manager.conf      O:-             CN=system:kube-controller-manager
    ├── scheduler.conf               O:-             CN=system:kube-scheduler
    ├── etcd-healthcheck-client（etcd 家族？ 见右）
    └── kubelet 层面：每个节点 kubelet 有它自己的客户端证（CN=system:node:<nodeName>, O=system:nodes, 由 kubeadm TLS bootstrap 签发）
(etcd/ca)
 CN=etcd
    ├── server.crt/key        O:-    CN=<hostname>   用 etcd 自己的 server
    ├── peer.crt/key          O:-    CN=<hostname>   用 etcd 内部 peer 通信
    ├── healthcheck-client     O:-    CN=kube-etcd-healthcheck-client   用 apiserver 给 etcd 做 healthcheck？ 实际由 apiserver 侧 probe/health 用
    └── apiserver-etcd-client  O:-    CN=kube-apiserver-etcd-client    用 apiserver→etcd
(front-proxy-ca)
 CN=front-proxy
    └── front-proxy-client     O:-    CN=front-proxy-client    用 apiserver→aggregated apiserver（metrics-server 这类）
```

**为什么分 3 把 CA**：etcd 与 apiserver/front-proxy 的信任边界是**独立的**——etcd 泄漏不该过载 apiserver/front-proxy 的旋转半径（facade）。SA 密钥对是另一个域：它不是 CA，旋转粒度是「全集群 SA token 全量重签」。

| 证书 | CN | O | 默认 usages | 自己签自己吗？ |
|------|----|---|-----------|--------------|
| apiserver.crt | `kube-apiserver` | — | server | ca |
| apiserver-kubelet-client.crt | `kube-apiserver-kubelet-client` | `system:masters` | client | ca |
| apiserver-etcd-client.crt | `kube-apiserver-etcd-client` | — | client | etcd/ca |
| etcd-server.crt | `<hostname>` | — | server, client | etcd/ca |
| etcd-peer.crt | `<hostname>` | — | server, client | etcd/ca |
| etcd-healthcheck-client.crt | `kube-etcd-healthcheck-client` | — | client | etcd/ca |
| front-proxy-client.crt | `front-proxy-client` | — | client | front-proxy-ca |
| admin.conf 内置 cert | `kubernetes-admin` | `kubeadm:cluster-admins` | client | ca |
| super-admin.conf 内置 cert | `kubernetes-super-admin` | `system:masters` | client | ca |
| controller-manager.conf | `system:kube-controller-manager` | — | client | ca |
| scheduler.conf | `system:kube-scheduler` | — | client | ca |
| kubelet.conf（TLS bootstrap） | `system:node:<nodeName>` | `system:nodes` | client | ca（由 CM 签） |
| SA 签发 key | — | — | （不是 X509） | — |

> ❗ `system:masters` 是「绕过整个 RBAC」组（super-admin 别名组），只在 repair/bootstrap 场景用。日常运维请用 admin.conf（绑到 cluster-admin 的 RBAC 组）；**两个 .conf 都不要分享**（PKI 页原话「Do not share」）。

### 5.2 check-expiration / renew / 静态 Pod 重启三件套

**发现过期**：

```bash
sudo kubeadm certs check-expiration
# 输出结构（官方示例）：
# CERTIFICATE                EXPIRES                RESIDUAL TIME  CERT AUTH        EXTERNALLY MANAGED
# admin.conf                 Dec 30 2021 23:36 UTC   364d                            no
# apiserver                  ...                    364d           ca                no
# apiserver-etcd-client      ...                    364d           etcd-ca           no
# apiserver-kubelet-client   ...                    364d           ca                no
# etcd-server                ...                    364d           etcd-ca           no
# ...（kubelet.conf 不列：kubelet 用自动轮转体系）
```

- `EXTERNALLY MANAGED = no` 表示 kubeadm 管（默认情形）；**external CA 签名的是 kubeadm 默认不处理**（官方原话「kubeadm cannot manage certificates signed by an external CA」）；
- 版本对照（§1.4）：非 CA 证书 **1 年**（8760h）、CA 证书 **10 年**（87600h）——源码与 v1beta4 页一致；
- **upgrade 自动 renew**：kubeadm upgrade apply/node 会默认 renew all certificates（过期 180 天内则强行备份重签），`--certificate-renewal=false` 关——这解释了「为什么升过级的集群往往顺便把证书也续了」。

**手动 renew（高危操作前自查：有没有 etcd 快照、当前是否在维护窗口）**：

```bash
sudo kubeadm certs renew all                     # 或 renew apiserver / renew apiserver-etcd-client 单个
# renew 后会从前一份证书里读 CN/O/SAN（rm-configmap 影响最小，v1beta4 页原话“kubeadm certs renew uses the existing certificates as the authoritative source”）
# 静态 Pod 重启：四种离子方法任选
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/  && sleep 20 && sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
sudo mv /etc/kubernetes/manifests/kube-controller-manager.yaml /tmp/ && sleep 20 && sudo mv /tmp/kube-controller-manager.yaml /etc/kubernetes/manifests/
sudo mv /etc/kubernetes/manifests/kube-scheduler.yaml /tmp/ && sleep 20 && sudo mv /tmp/kube-scheduler.yaml /etc/kubernetes/manifests/
sudo mv /etc/kubernetes/manifests/etcd.yaml /tmp/          && sleep 20 && sudo mv /tmp/etcd.yaml /etc/kubernetes/manifests/
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config     # 如果 renew 了 admin.conf，普通用户也换新
```

> 官方 kubeadm-certs 页明确：「dynamic certificate reload is currently not supported for all components」——所以 renew 不会自动七大件生效，**重启静态 Pod 是必走的一步**（kubelet 检测 fileCheckFrequency 20s 后把 Pod 重启）。

### 5.3 kubelet 的 client / serving 证书自轮转（kubeadm 给的默认）

kubelet 有两种证书，轮转条件独立：

| 证书 | kubeadm 默认 | 轮转链 |
|------|------------|--------|
| **client 证书**（kubelet 报 node status 给 apiserver 的凭据） | `rotateCertificates: true`（kubeadm 写入 kubelet-config ConfigMap，§1.4 样例） | 临期 kubelet 创建 CSR（signerName `kubernetes.io/kube-apiserver-client-kubelet`）→ controller-manager 内置 **csrapproving controller**（default 开）走 SubjectAccessReview 批准 `system:certificates.k8s.io:certificatesigningrequests:selfnodeclient` → 自动签发一年新证，故障率低 |
| **serving 证书**（kubelet 10250 上报给 kubelet API 的） | **默认自签**（自签的不是 CA 链背书，所以 metrics-server/kubelet proxy `x509: certificate signed by unknown authority`） | 需要 `serverTLSBootstrap: true`（KubeletConfiguration，§1.4）+ 开启 feature `RotateKubeletServerCertificate`（**v1.37 Beta，默认开**——release-1.37 源码 `kube_features.go`），kubelet 会创建 CSR `signerName: kubernetes.io/kubelet-serving`——**内置 csrapproving controller 出于安全考虑不批准 serving 类 CSR**（官方 TLS bootstrapping 页原话），你需要人工 `kubectl certificate approve` 或部署第三方 approver，例如 `kubelet-csr-approver`（必须验证 CN/system:node:<nodeName>+SAN 都是「这台节点自己的 IP/DNS」） |

三句话复查你的集群当前是什么状态：

```bash
# ① client 轮转钥匙（KubeletConfiguration 应为 true）
kubectl get cm kubelet-config -n kube-system -o=jsonpath='{.data.kubelet}' | grep -E 'rotateCertificates|serverTLSBootstrap'

# ② 已经 approve 的 serving CSR（若 serverTLSBootstrap 开过）
kubectl get csr -o json | jq -r '[.items[].spec.username] | sort | unique[]' | head -5

# ③ kubelet serving 证书现在是什么签发级（用实验 7.3 的 openssl s_client 探件）
```

> ❗ 生产推广 `serverTLSBootstrap: true` 之前，你要先想清「谁来 approve serving CSR」这个环——没有 approver 的集群会在首次 certrotate 后让 metrics-server/kubelet proxy 把 load 打向「未知 CA」误警报。「开 + 配套 approver」是唯一的整包推。

### 5.4 CA 根换新（manual-rotation-of-ca-certificates 完整步骤）

什么时候必须换根 CA？两类：
- **泄漏**：`ca.key` 出现在不该出现的地方（[CI 上传错位置]/某人的 `~/.kube` 目录/备份仓库）；
- **合规轮转**：JIT/审计强制的轮换周期（如「5 年换一次」）；kubeadm 的 CA 默认 10 年寿命见其需要你换才换。

> ❗ **官方假设（manual-rotation 页原话）**：以下流程假设 **HA 集群、多 apiserver、有优雅停机支持**；单 apiserver 会经历 API **不可用窗口**——在 1 CP 集群上执行请接受这一点（实验环境也一样）。

**完整步骤表（1→10，不可倒序）**：

| # | 动作 | 说明/命令 |
|---|------|-----------|
| 1 | 备份 `/etc/kubernetes/pki` 与 kubeconfig | `sudo cp -r /etc/kubernetes/pki /etc/kubernetes/pki.bak.$(date +%s)`；附近目录 offcluster 拷贝 |
| 2 | 生成新 CA（`ca-new.crt/key`、`front-proxy-ca-new.crt/key`，用 openssl/cfssl 或 kubeadm 独立性工具） | 必须在**测试环境先走完一遍** |
| 3 | 把新 CA 公开文件分发到所有 CP 节点 `pki` 目录 | 新旧 CA 各一份并存 |
| 4 | 改 controller-manager：`--root-ca-file` = **旧+新 CA bundle**；重启 CM | root-ca-file 是给 ServiceAccount token 里嵌入的 CA；先让新 SA token 同时信任两 CA |
|    | ⚠️ 已知坑：`/etc/kubernetes/pki/ca.crt` 变 bundle 后，CM 的 `--client-ca-file` 与 `--cluster-signing-cert-file` **不能再指向同一个 bundle**（官方报 `cimcli`/#1350）；把新 CA 复制成 `ca-new.crt` 单独指给它们 | 旧 bundle 清完再合并回来 |
| 5 | 等 controller-manager 把旧+新 CA bundle 写进**所有 ServiceAccount 的 Secret**（`token-ca.crt`） | `kubectl get secrets -A -o jsonpath='{range .items[?(@.type=="kubernetes.io/service-account-token")]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' | head` 抽查 |
| 6 | 重启所有「使用 in-cluster 配置」的 Pod（kube-proxy/CoreDNS/你的节件 Operator/...）让它们的 SA token 重换 | `kubectl delete pod -n kube-system -l k8s-app=kube-dns` 这类；自研 operator 也要（健康检查表 `kubectl get pods -A`） |
| 7 | apiserver/scheduler：**`--client-ca-file` 与 `--kubelet-certificate-authority` 改为 bundle；scheduler 同步换**；重启 apiserver/scheduler（索 §5.2 清单 mv 游戏） | apiserver 接认证与杀 kubelet 都先识两 CA |
| 8 | 用户 kubeconfig 与 SA token 的版本（client-certificate-data）》新 CA 签发的新证；certificate-authority-data 嵌 bundle；`kubeadm kubeconfig user` 发新（可用 §5.1 super-admin 在 break-glass 场景） | 已有的 admin.conf 用户也要轮换 |
| 9 | （可选 cloud-controller-manager 的 `--root-ca-file` 同步并重启） | 无 ccm 可跳 |
| 10 | 各 node：kubelet `clientCAFile` + `kubelet.conf` 的 `certificate-authority-data` 改 bundle；kubelet client 证书轮转由 controller 后续统一发；**重启 kubelet**；检查日志无 TLS 错误 |
| 10+ | **让全节点 Pod 用一个 bundle 删除旧 CA**：所有 pod 重启 ≥1 次；`--client-ca-file/--root-ca-file` 撤成新 CA；所有 daemonset/deployment 再 rollout；bootstrap token 的 `cluster-info` ConfigMap 把 certificate-authority-data 改新 CA base64一程：`base64_encoded_ca=$(base64 -w0 /etc/kubernetes/pki/ca.crt); kubectl get cm/cluster-info -n kube-public -o yaml | sed "s|\(certificate-authority-data:\).*|\1 ${base64_encoded_ca}|" | kubectl apply -f -` |

经验法则（**什么时候要做、多久做一次**，官方有节奏建议）：

- **一年生证书**（默认！）+ CA 10 年：生产上的 CA rotation 不需要常态化——**CA 只在泄漏、合规、算法更换（RSA-2048 → P384）时触发**；一年生的叶证书由 `kubeadm upgrade` 或 `certs renew` 续，与 CA rotation 无关。
- **一次完整 CA rotation 的均值窗口**：3 CP + <=100 节点集群，按官方步骤无自动化时大约 **2~4 小时/人窗口**，多加一小时 Pod 全量 rollout 观察。把它当 **季度级**的深度演练事件，而不是日常动作——这也是实验 L3 证书破坏场景的深层原因。
- 官方 **临别提醒**：「If your cluster lets you, you can also roll it out by replacing nodes rather than reconfiguring them」——如果你能用 IaC/MachineSets 换节点，**整节点替换**会远比 per-node 改文件优雅。

### 5.5 encryption key 轮换（直接引用不重写）

加密面（Secret 静态加密 EncryptionConfiguration + KMS）的**密钥轮换是另一个炸弹**：改 key 之后必须把所有存量 Secret 重写一遍才能彻底拿到新 key 的保护。第 5 章 §5.2 已经把整段（`new key 进尾→调首→rewrite 全部→撤旧`，自动重载 flag）讲透了——这里只再给出轮换一句话的出口命令：`kubectl get secrets -A -o json | kubectl replace -f -`（第 5 章背诵版 #9），不重复。

---

## 六、控制面调优与大集群设计约束

### 6.1 kube-apiserver 关键 flag 与指标（v1.37 官方 command-line-reference 核实）

| flag（v1.37 默认，官方) | 干什么 | 生产上什么时候动 |
|------------------------|--------|----------------|
| `--max-requests-inflight=400`<br>`--max-mutating-requests-inflight=200` | 关 APF 时的两闸；**APF 开着时两值相加=600 nominal concurrency**（默认开 APF，v1.29 GA） | 一般不动；想加大单实例并发优先想「加 CP 实例」而不是调数字 |
| `--watch-cache=true` | 默认开，watch 全靠它吃 etcd | 别关；想精细调整走 `--watch-cache-sizes`（v1.37 里已被简化到「0=关该资源的缓存」） |
| `--etcd-compaction-interval=5m0s` | apiserver 定时发起 etcd compaction（第 1 章「5 分钟历史窗口」的来源） | 一般不动；大集群不摆其他人改 |
| `--min-request-timeout=1800` | watch handler 的最小连接下限（加随机抖动错开重连风暴） | 一般不动；watch 风暴时先检查客户端行为 |
| `--goaway-chance`（min 0 / max 0.02，官方推荐先从 0.001 起） | 多 apiserver + LB 时，**随机发 GOAWAY 让 HTTP/2 客户端重连到别的 apiserver**，把单点倾斜的 watch 分摊 | HA 集群 3 个 apiserver 生产强烈推荐（官方原话「Clusters with single apiservers... should NOT enable」） |
| `--shutdown-delay-duration` | 优雅关闭的牵引窗（readyz 立即失败但继续服请求），被 LB 摘走的用意 | 与 §4.4 思想实验同组一：HA 集群里 apiserver 滚升级前让 LB 先摘 |
| `--storage-media-type=application/vnd.kubernetes.protobuf` | 1.37 默认 protobuf 存储（不算「新 flag」，是 v1.37 的默认切换） | 不用动；注意你 etcdctl dump 时的- 数据不再好读（第 6 章 operator 开发的 Kubernetes API 也依赖 protobuf） |
| `--feature-gates=EtcdRangeStream=true`（v1.37 Beta 默认开） | apiserver → etcd 大集合读改 streamed——**两端内存峰值降低**；etcd 要 ≥3.7 | dashboards/告警要加 `operation="listStream"`，否则你不知道指标里藏了什么 |
| `--min-compatibility-version=kube=1.34..1.37`（默认 1.36） | 混合版本的最低兼容水位 | 升级期间自动加入无需干预 |

** apiserver 生产指标怎么看**（「监控/」目录已有 Prometheus 部署篇；这里只看指标本体）：

| 指标 | 看什么 | 告警阈值建议（经验，非官方） |
|------|--------|-------------------------|
| `apiserver_request_duration_seconds{verb,resource}` Histogram | P99 时长分层：list / watch / mutate | P99 > 2s 且持续 5min 看 etcd |
| `apiserver_flowcontrol_rejected_requests_total{reason}` Counter | APF 按 priority level 拒绝分布（第 1 章 §5） | reason=queue_limit/higher_priority 涨就 has越来越严重 |
| `etcd_request_duration_seconds{operation}` Histogram | etcd 慢一级级传导（ `listStream` 提醒同 6.1 EtcdRangeStream） | P99 > 500ms 连续 5min 大概率 etcd 慢 |
| `apiserver_current_inflight_requests{request_kind}` Gauge | 静态闸占用率（inflight vs 600 total） | > 80% 持续 10min 触发检查 |
| `apiserver_watch_events_total` / `apiserver_watch_events_sizes` | watch fanout 量、事件尺寸分布 | watch 事件平均大小 > 50KB 看看是不是有 giant CRD |

### 6.2 controller-manager / scheduler / kube-proxy 并发与 QPS（v1.37 默认值总表）

**kube-controller-manager**（默认适合中小集群，大集群按经验调——官方大集群文档没给具体数字，以下默认值已核实 v1.37 command-line-reference）：

| flag/config | 默认 | 大集群经验值（经验，不是官方！） |
|-------------|------|------------------------------|
| `--kube-api-qps` / `--kube-api-burst` | **20 / 30** | 大集群起点 **50/100**；超大集群上探 100/200 |
| `--concurrent-deployment-syncs` | **5** | **5~10**（deployment 与 replicaset 是并发熟客） |
| `--concurrent-replicaset-syncs` | **5** | 5~10 |
| `--concurrent-gc-syncs` | **20** | 大集群下升到 **40~50**（ownerReference GC 并发是敏感项） |
| `--concurrent-namespace-syncs` | **10** | 10（namespace 删不掉往往 sys意义上） |
| `--concurrent-cron-job-syncs` | **5** | 5~10 |
| `--concurrent-endpoint-syncs` | **5** | 大集群 endpoint 热一路要动 **10~20** |
| `--concurrent-node-eviction-*`（node-lifecycle） | `--node-monitor-grace-period=50s` / `--node-monitor-period=5s` | 本值就是内部 SLA：50s 内还没刷新就 NotReady → 大网络要稳 |
| 证书签发 | `--cluster-signing-duration=8760h0m0s` | 1 年，与 §5.2 一环 |

**kube-scheduler**（v1.37，默认）：

| flag/config | 默认 | 大集群经验值（经验！） |
|-------------|------|---------------------|
| `--kube-api-qps` / `--kube-api-burst`（flag 已 DEPRECATED，写入 KubeSchedulerConfiguration） | **50 / 100** | 大集群 **100/200** 多半坑在事件更新而不是调度算法 |
| `leader-elect*`（与 CM 同） | 15s/10s/2s | 不改 |
| 指标面（第 2 章 §7 已全表） | — | **调度告警阈值建议**：`scheduler_pending_pods{queue="active"}` ≥ 100 持续 5min；`scheduler_pod_scheduling_sli_duration_seconds` P99 > 60s；`scheduler_schedule_attempts_total{result="error"}` > 1/min 持续 5min；`schedule_attempts_total{result="scheduled"}` 掉 = 集群 sched 压力｜第 2 章 §7 指标主表已写，本表只补阈值 |

**kube-proxy**（v1.37，默认）：

| flag/config | 默认 | 生产调优点 |
|-------------|------|-----------|
| `--kube-api-qps` / `--kube-api-burst` | **5 / 10** | 大集群 Service/Endpoint 翻牌速率上来后 low；可动 **50/100** |
| `--iptables-sync-period` / `--iptables-min-sync-period` | **30s / 1s** | Service 密集集群看 `kubeproxy_sync_proxy_rules_duration_seconds` |
| `--proxy-mode` | `iptables`（Linux 默认） | ipvs/nftables/全去掉（Cilium），第 3 章已选 |
| healthz / metrics | `0.0.0.0:10256` / `127.0.0.1:10249` | LB 健康检查直接打 10256 |

> ❗ QPS/Burst 调优的根本原因链：QPS 决定「api server 涨压」，burst 决定「短时间尖峰门槛」——APF 给每个 finalist client 分配的 share 是有限的（CM/scheduler/proxy/kubelet 有默认 `exempt` 等级，但冲到上限一样 429）；事件中继链是：**QPS 太低 → controller/CM 事件处理迟缓 → 客户端升级等待着 → 显得更慢**；QPS 太高 → apiserver 429 → 更像故障。**先测后调，别拍脑袋**。

### 6.3 etcd 侧：quota、defrag、数据量增长曲线（apiserver→etcd 协同面；etcdctl 运维不重讲）

- **后端 quota**：etcd 默认 `--quota-backend-bytes=2GiB`（K8s-etcd详解.md 已讲），K8s 官方「operating etcd clusters」页推荐静态 5-member、生产任何规模够用，同时**不建议扩缩 etcd**（自动扩缩触发选举、打乱 raft quorum）——扩成 8GiB 只是「表达你想撑大」的手段，但大集群仍官方推荐 2GiB 后拆事件 etcd（§6.5）
- **扩 quota 的判断**：`etcdctl endpoint status` 里 DB SIZE + alarm；事件类对象 (`/registry/events/`) 是唯一的大头——**把 events 拆到独立 etcd 集群**是官方给大集群的标准动作（large cluster 页：store Event objects in a separate dedicated etcd instance），比单调 quota 优雅
- **defrag 周期主张**：官方原话「as infrequently as possible」——碎片率 <50% 不动作；推荐 **`etcd-defrag` CronJob** 按周/月排巡，别手动跑
- **数据量增长曲线经验值**（非官方）：每个 K8s 对象平均 **1.5~2.5 KiB**（带 ownerRef 链、last-applied 注解、status 边角）——约 5 万对象（3 节点小集群 + addon + event 不计）约 **100~150 Mi**；10 万对象 ~500 Mi。**5 分钟 compaction（§6.1 `--etcd-compaction-interval`）只是「旧版本清空」**，当前版本仍计入**这是 v1.37 默认 EtcdRangeStream（§6.1）为什么省内存的原因之一**
- **官方警示**：etcd `mvcc: database space exceeded` 时的恢复纪律（compact + defrag + disarm）——K8s-etcd详解.md §5.4 已讲，不复

### 6.4 kubelet 生产关键配置

| kubelet 配置（默认值来自 v1beta1 配置页，全部核实） | 默认 | 生产什么时候动 |
|----------------------------------------------------|------|--------------|
| `maxPods` | **110** | 大节点（16C+/32G+）上常见 **250~500**；110 这个数字的原始本意是「单 apiserver level 上限」（large cluster 页），而不是性能结论——你要与你的 CNI IPAM、节点 CIDR、节点 conn track 一起想 |
| `podsPerCore` | 0（不限制） | 小核多 pod 场景防过度调度时再动 |
| `imageGCHighThresholdPercent` / `imageGCLowThresholdPercent` | **85 / 80** | 磁盘压力表来的；可查 `kubelet_image_gc_duration_seconds` 验证有效 |
| `containerLogMaxSize` / `containerLogMaxFiles` | **10Mi / 5** | 每个容器最多 50Mi 日志——**日志风暴容器**（应用打 INFO+上 DEBUG）2 分钟就满了，这时更要upstream 到集中日志（Fluent-bit/ELK)；挂 CS-01 runbook 「`kubectl logs` 看不到完整应用日志」 |
| `serializeImagePulls` | true | 大集群/巨型镜像场景关它换上 **`maxParallelImagePulls`**；kubelet v1.37 还要 aware `registryPullQPS=5 / registryBurst=10` |
| `evictionHard` 默认表 | **memory.available<100Mi（Linux）/ 500Mi（Windows）**<br>**nodefs.available<10%**<br>**imagefs.available<15%**<br>**nodefs.inodesFree<5%**<br>**imagefs.inodesFree<5%（Linux）** | 加了自定义 thresholds 必须 **mergeDefaultEvictionSettings: true**（否则其它默认全部清 0）——这是取代「为什么 eviction 已经不 kill pod 了」的第一原因 |
| `evictionPressureTransitionPeriod` | **5m** | 与 eviction 状态机联动；`kubectl describe node` 里 NodeCondition 每次切换会emit Node Condition Event 到 event 流 |
| eviction 选 Pod 顺序 | **是否超 requests → Priority →（requests 以下的同级）usage/requests** | 官方原话「kubelet does not use the pod's QoS class to determine the eviction order」——**QoS 只是估算重要性的近似量**，真正排序用 usage 超 requests 与否 + Priority；见实验 7.4 |
| kubelet OOM 保护 | Guaranteed -997 / Burstable formula / BestEffort 1000 / `system-node-critical` Priority Pod **也按 -997** | 第一起「系统 Pod 最先被 kill」的事故的原因表；K8s-调度器深入.md §6.2 已覆盖 PriorityClass 数值 |
| `cgroupDriver`（kubelet 层） | `cgroupfs`（但 kubeadm 配 systemd；`KubeletCgroupDriverFromCRI` v1.37 Beta 默认开会 autodetect） | 同 §2.3 灾难案例；不一致=资源 quota 混乱 |

**inode 与 imagefs 未分离的经典事故**（`nodefs / imagefs` 共享同盘）：

- 事故发生链：容器镜像持续拉取膨胀 → `imagefs.available` 掉下 15% → kubelet 销毁**一向**没用过的镜像 → 没用的镜像的 attach 链路被回收（第 4 章 CSI/CSI driver mount 目录在 imagefs）→ **新的 Pod 进来根本拉不到镜像**（你的仓库在 benelux）。`kubectl describe node` 会同时给你 `DiskPressure=True` 与「整体 Node NotReady」的 Event——而**磁盘里到底是被镜像塞死还是被日志塞死**，kubelet 自己分不清
- **生产简规**：worker 上至少把 `/var/lib/containerd` 独立挂一块盘（production ready 给个 50~100 GB 专用 volume），事实上 imagefs/containerfs 与 rootfs 分盘在官方「node-pressure eviction」页有结构性地提案（**v1.37 KubeletSeparateDiskGC Beta 默认开**），大集群已是同款式标配

### 6.5 大集群设计约束：官方数字 + 这个数是怎么推算的

官方 large cluster document（v1.37 仍是同一数字堆）：

```
   Kubernetes v1.37 supports clusters with up to 5,000 nodes.
   More specifically, all of the following must hold:
     • No more than 110 pods per node
     • No more than 5,000 nodes
     • No more than 150,000 total pods
     • No more than 300,000 total containers
```

**为什么是这四个数的乘积——可以反过来从控制面推算**（经验推导，非官方/仅当理解框架用）：

1. **etcd 事件速率 vs watch fanout**：官方解释在**每分钟新增 Pod ≤ 数千** 的流上——这不叫「支持 150000 pods」，是「Pod 创建/更新事件的 eta 速率支持」；每个对象再生成一次 etcd 写（第 1 章 list-watch 的 fanout），8 MiB/Raft 传播
2. **apiserver 内存 = 对象数 × 对象大小**：粗略 `15 万 Pod × 1.5 KiB(object+status) ≈ 220 Mi`，**只对「那个资源」的 watch cache 是这样算**；实际 apiserver 还缓存所有 Nodes、Deployments、Endpoints、EndpointSlice（EndpointSlice ≈ Pod 数 × 100 endpoints per slice 平均昭来）——这是「为什么你想多一部 apiserver 时它并不线性 scale」的直接缘由
3. **每节点 110 pods** 是从 kube-proxy/iptables 的规则链长度、kubelet 的一次 status sync 大小、cAdvisor 指标起调功耗决定——是大集群的硬压底线，不是推荐最佳实践（第 5 章选中每节点最小单位 256 node 以下）
4. **300000 containers**：对象是 Pod 2×——因为每个 Pod 至少一个 pause + 一个跑容，「(pause + app) × 150000」的结论是整底600min 的一个尺度估计（K8s-组件详解.md 的 sandbox/Pod 结构）

超过这张表的路线只有两条：**events/etcd 拆转（§6.3）+ 多集群**（第 10 章 Karmada/Fleet 领域——不在本章）。

---

## 七、节点自运维生态：NPD + draino + 自愈节奏

### 7.1 node-problem-detector（NPD）：把「节点的病」变成 NodeCondition/Event

NPD 官方定义（`monitor-node-health` 页）：「Node Problem Detector is a daemon for monitoring and reporting about a node's health…reports these conditions to the API system as Node Conditions or as Events」。

四种 problem daemon（官方分类）：

| daemon | 抓什么 | 典型产出 |
|--------|--------|---------|
| **SystemLogMonitor** | 系统日志（filelog/kmsg/kernel/abrt/systemd） | 内核 OOPS、ext4-err、XFS 崩、KernelDeadlock |
| **SystemStatsMonitor** | 各种健康统计指标（load、mem、fd、disks、cpu） | `Node` 级 Prometheus 指标 |
| **CustomPluginMonitor** | 你自己写的脚本（遵循「exit code + stdout」协议） | 「某挂载点没有权限」「TimeSync 偏了 5s」类你定制 |
| **HealthChecker** | kubelet 与 container runtime 的健康 | KubeletReady / ContainerRuntimeReady 异常 |

exporter（把 condition/event 往哪发）：K8s exporter（Event 解决临时事情、NodeCondition 解决持续常态）、Prometheus exporter、Stackdriver exporter。

最小落地（两种官方途径）：

```bash
# ① 官方 DaemonSet 一键（文档带 manifest；适合「先看它能干什么」）
kubectl apply -f https://k8s.io/examples/debug/node-problem-detector.yaml

# ② Helm 形态（deliveryhero repo 的正式社区 chart——artifacthub 有收录，v2.4.1 以上验证）
helm repo add deliveryhero https://charts.deliveryhero.io/ && helm repo update
helm upgrade --install npd deliveryhero/node-problem-detector -n kube-system \
  --set metrics.enabled=true    # 顺手把 Prometheus exporter 打开
kubectl -n kube-system get pods -l app.kubernetes.io/name=node-problem-detector
```

> ❗ NPD 本身不 drain、不重启 kubelet——它是感知层。**把「感知」接到「行动」**需要下一节的 draino。

### 7.2 draino：NodeCondition → cordon + drain 的自动化

draino 是 Cloudflare 开源的「节点 drain 自动化器」：

> ❗ **可用性预警（自写时记）**：原仓库 `github.com/cloudflare/draino` 在写本文时**已 404**，存在多份活跃 fork（artifacthub/GitHub 搜索可见 `planetlabs/draino` 等）。落地前**核实当前活跃 fork/上游归属**——但核心语义是一致且简单的，学会语义不因仓库变动失效。

draino 语义（社区 fork 统一行为）：

| 阶段 | 做什么 |
|------|--------|
| 观察 | watch Node.Condition（如 `KernelDeadlock=True`、`ReadonlyFilesystem=True`、NPD 上报的 —） |
| 决策 | 满足条件 → 给 node 打 label（默认 `draino` = 派生出自己的「我修你先你修」坐标） |
| 行动 | `cordon` + `drain`，尊重 **PodDisruptionBudget**（PDB 不漂强就不会有强drain） |
| 安全 | leader election（别 2 个 draino 一起打）、`dry-run` / `label-suppression` 观察模式、超时 |

**标准联动（NPD + draino + K8s 控制面）**：

```
   node 的内核/磁盘出了问题
              │
   NPD (DaemonSet)
     SystemLogMonitor/HealthChecker 看到
              │
     报 K8s：NodeCondition KernelDeadlock=True（+ Event）
              │
   draino（Deployment，看这类 condition）
     决策 + leader election + dry-run 检查
              │
     kubectl cordon <node> + drain --ignore-daemonsets（尊重 PDB）
              │
   Cluster workloads migrate（Pod 被 controller 重新抱有在新 node）
              │
   Node autoscaler / 你的 IaC 把 node 替换（kubeadm 手动：kubeadm reset + 新 VM）
```

### 7.3 自愈节奏建议（生产振散与 reconciliation 时间窗的经验纪律）

「看到 NodeCondition 立刻 drain」往往会把小问题放大（etcd leader 刚稳定、正好业务高峰、刚豪车更新过等）。生产推荐 **溢出型（cushioned）节奏表**：

| 阶段 | 时长窗口（经验） | 动作 |
|------|---------------|------|
| **观察** | 5 分钟 | 只 cordon（NPD 打 label `maintenance: true`，你的 PagerDuty/SRE 立牌——draino 也可以先只输出日志）；查 `kubectl describe node` 里 Condition 历史 |
| **决策** | 下一个 5 分钟 | 同 condition 持续 → 进入 drain；消失 → 复盘 |
| **drain** | 一次一台 / 一次一个 zone | 重 PDB（第 8 章节 8.4）；`kubectl drain --ignore-daemonsets --delete-emptydir-data` |
| **修复/替换** | 保电 15 分钟 | 云主机：API 重建。裸机：硬件报修；`kubeadm reset` + 重新 `kubeadm join`（status 未变 model）|

> ❗ 自愈不是「封杀」——事件的**再发源地**是「NPD 看到的 conditions 与 draino 的 schedule conditions 是同一张 matrix」：内生条件（ReadonlyFilesystem、KernelDeadlock）应直接进 draino；佐证型条件（MetricsServerDown、PrometheusDown）则先警，别自动 drain 控制面节点。

---

## 八、租户治理生产配置（PriorityClass / NetworkPolicy 基线 / PSA 参考第 2、3、5 章）

### 8.1 ResourceQuota：namespace 边界的总量天花板

ResourceQuota 是 kube-controller-manager 的 admission-time 总量围栏——「请求 + 限制 + 存储 + 对象数量 + 类优先级」五个维度都能绑。生产强度结构：

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: prod-quota, namespace: prod-team-a }
spec:
  hard:
    # 总量（requests + limits 只算 Pod）
    requests.cpu: "40"
    requests.memory: "64Gi"
    limits.cpu: "80"
    limits.memory: "128Gi"
    # 存储：PVC 数 + 总量 + 单 StorageClass 限量
    persistentvolumeclaims: "20"
    requests.storage: "2Ti"
    gold.storageclass.storage.k8s.io/requests.storage: "500Gi"
    # 对象数量上限
    count/pods: "200"
    count/services: "20"
    count/secrets: "100"
    count/configmaps: "100"
    count/deployments.apps: "30"
    services.loadbalancers: "2"
    services.nodeports: "5"
  scopeSelector:      # 只对「符合 scope 的 Pod」计入（v1.32+ GA 的 PriorityClass scope）
    matchExpressions:
      - scopeName: PriorityClass
        operator: NotIn
        values: ["system-cluster-critical", "system-node-critical"]   # 系统 Pod 不进团队配额
```

**生产要点**：

- **requests+limits 最好配一对**——只配 `limits.cpu` 会导致 Pod requests=limits 自动从 limits 推入（LimitRanger 默认），把配额装成「它本来就用的总量」；两个都配是「上限与请求额分层管理」
- **scopeSelector 把系统 Pod/豁免 Pod 从 quota 里摘出去**——否则某个 DaemonSet 增加会让整个 ns 塞死（生产事故频发款）
- `count/* 与 requests.storage` 会把 e.g. 创建 1 个 PVC 的请求拒绝在 admission——**kubectl 给出 403 Forbidden 事件**而不是 Pending spinloop，告警直接打 Events 而不要荧 Pending
- 请配合 **SpanQuota**（无字段，是指：多 quota 对象并存时取交集）制度管理

### 8.2 LimitRange：单 Pod/容器级的默认与最大最小

LimitRange 是 admission-time 的「单容器函数」：

```yaml
apiVersion: v1
kind: LimitRange
metadata: { name: prod-limits, namespace: prod-team-a }
spec:
  limits:
    - type: Container          # 单容器 default 请求 + 额度
      default:                 # limit（没写 spec.resources.limits 的容器认领）
        cpu: "1"
        memory: "1Gi"
      defaultRequest:          # request（没写 requests 的认领）
        cpu: "200m"
        memory: "256Mi"
      min:
        memory: "128Mi"
      max:
        cpu: "4"
        memory: "8Gi"
      maxLimitRequestRatio:
        cpu: "4"               # limit/request ≤ 4（burst 节制）
    - type: Pod                # Pod 合计同样规则
      max: { cpu: "8", memory: "16Gi" }
    - type: PersistentVolumeClaim
      min: { storage: "1Gi" }
      max: { storage: "500Gi" }
```

**为什么这么设计**：

- `defaultRequest` 与 `default` **成对**——节约「裸写成绩 Pod 没 resources」变成配额被填 0 的 admission 报错；
- `maxLimitRequestRatio` 是**超售反制**——你多买「请求等于 11 节点跑满」，他多买「burstable limit 上天」，两者一起出现时节点面对一个 **超售率超过上限** 的黑洞；
- 多 LimitRange 对象并存，检查对每个 type 取**严格最严格**（取所有匹配的交集 最严），这与 ResourceQuota 的交集很不一样。

### 8.3 requests / limits 生产纪律表（为什么 CPU limit 有争议）

| 纪律 | 边界 | 直接的 bug 场景（真实事故模型） |
|------|------|------------------------------|
| **memory request == memory limit**（多数生产物种） | 内存 limit 是 cgroup `memory.max` 依托，超了直接 OOMKill；request=limit 才能是 Guaranteed 级 + 必有 eviction 保护（§6.4 oom_score_adj=-997） | limit > request 时 Burstable 级，内存压力大时被先选为 evicted |
| **CPU 只配 request 不配 limit**（生产主流！） | CPU limit 走 CFS throttling——**推荐区部场景（二倍超售集群）才写**；CPU request 决定调度（权重 shares），limit 会导致**间歇性延迟尖峰**（large concurrency Go 程序常见） | CPU limit = 4 + 高峰期容器 >4 CFS quota 每 100ms → `container_cpu_cfs_throttled_periods_total` 增长 + P99 延迟 ⋅10 |
| **裸 Pod 禁止**（requests 必填纪律） | LimitRange 的 defaultRequest 救急 | 业务没写 request → 调度器 quota 口径全面失真 → 一个节点「配额过度声称」 |
| **资源不平等的 pod 用 PriorityClass**（第 2 章 §6） | `system-cluster-critical=2000000000`、`system-node-critical=2000001000` | 业务 pod 与监控 agent 同 default Priority → 节点压力来时 CoreDNS 跟业务同顺位被 evict |

> ❗ **CPU limit 争议**的实践结：在控制 limit（v1.37 era）里写 limit=4 意味着「这个进程每 100ms 不能用超过 400ms 的 CPU」——业务进程的 GC/STW 阶段一旦超就折断 quota，但调度器/其它 Pod 看到的是「半边节点是 free 的」。生产上 **memory limit 照写 + CPU limit 不照写** 是主流 sound；但你必须同时有 `container_cpu_cfs_throttled_periods_total` 告警——你默认不是把 CPU burst 平台偷光了，而是显式在「与 Priority 绑定的 burst 预算」观念上运行。

### 8.4 配套：PriorityClass 与 NetworkPolicy/PSA 基线（引用不重复）

- **PriorityClass** 生态与 preemption 细节直接引用第 2 章 §6.2 ——`preemptionPolicy: Never` 是批任务的冰山一角
- **NetworkPolicy 基线**（default-deny + explicit allow）引用第 3 章 §NetworkPolicy——Cilium 上警用 `CiliumNetworkPolicy` 时的区别
- **PSA**（`pod-security.kubernetes.io/enforce: restricted`）引用第 5 章 §1~§2——net/system 程序命名空间用 label 豁免路径

---

## 九、灾备与恢复编排（备份铁三角 → L3 演练计划）

### 9.1 备份铁三角（K8s-etcd详解.md / Velero 笔记已详解，这里给动作）

| 面 | 负责什么 | 最小频率建议 |
|----|---------|-------------|
| **etcd 快照** | 控制面 state 真源；restore 单文件回来 | **每小时**（CronJob 带点 `etcd-defrag`的节奏） + 升级前后手动一次 |
| **基建层** | TLS/版証/VPN/安全组/LB/IaC——「我能重新画出这台机器」 | 每次变更自动触发 Terraform apply log/architecture state 文件 |
| **Velero** | 对象面 + PV 快照——Pod/PVC 级别恢复 | **每日** + 升职前增量；备份位置与集群故障域分离（BSL，Velero 笔记 §6） |

> ❗ 三者替换关系：**etcd 快照不能恢复 PV 里的业务数据**（那是盘的事）；**Velero 不能恢复「你的 etcd 被格式化」**（要 restore etcd 快照后再 Velero restore 对象）；**IaC 不能恢复数据**。事故里三钟混备导致 RPO 不可控。

### 9.2 恢复优先级表（灾难时刻逐个上来）

```
P0 (根)  → 控制面静态清单(/etc/kubernetes/manifests) + pki 目录在场
             └── 没有它们，apiserver 起不来 → 任何时候无法掌操你集群
P1        → etcd 数据（stacked 在 /var/lib/etcd；用 etcd snapshot restore 从前一晚快照）
             └── 恢复前：停所有 apiserver（官方 configure-upgrade-etcd 页原话）
P2        → apiserver/kube-scheduler/controller-manager 启动 + 证书活着
             └── 用了 admin.conf / 官方 of if kubeadm reset 再装
P3        → RBAC、webhook（cluster 条目：NetworkPolicy / PSA / validate CNI）
             └── 它们挂了，apiserver 起来了但 EVERY WRITE NOR 会 500/403
P4        → CNI、CoreDNS、kube-proxy、CSI
             └── 「网络平面平地集高峰恢复」；CoreDNS Running 是集群真正可操作的标志
P5        → 业务（按 PriorityClass 高→低恢复；）
```

### 9.3 「node down 5 分钟自愈」的检查表

| 检查项 | 为什么它保证5分钟法生器来一次 | 落地规则 |
|--------|---------------------------|---------|
| **控制器 / PDB 完整** | decide 是控制器把 Pod 抱起来 | 关键业务 PDB minAvailable ≥1/at 25% |
| **节点标签/拓扑可行** | scheduler 才能找到替代落点 | `topology.kubernetes.io/zone`、nodeSelector 别绑死一台 |
| **镜像 registry 冗余** | node 新来拉镜像不能卡住 | registry 高可用或 imagePullSecrets 预先送达各 node（本节点 image GC 不应手工动 NOW） |
| **存储多副本或云盘 attach** | PV 要能漂起来 | RWO 块盘会卡在 multi-attach 5 min+；要么 RWX/NFS 要么 Event-based replacement |
| **NPD/draino 节奏（§7）** | node condition 到 cordon 链路兑现 | draino dry-run 常设→达标后打 prod label |

### 9.4 整机恢复演练计划（实验 L3 主体）

实验 L3 是本演习的 ramp：《总纲》里给的 7 大破坏场景逐一来（每一场写成 runbook 之后丢进 `容器编排/K8s-故障排查方法论.md` 第 8 章）：

| # | 破坏脚本（一句话） | 破损后现象 | 恢复动作（参考到此章节） |
|---|-------------------|-----------|----------------------|
| 1 | 删 etcd data dir（单 CP！） | apiserver crashloop、`kubectl get` 全部 ETCD timeout | 停 apiserver → 上晚快照 restore snapshot → 起 apiserver（§9.2 P1 + §9.1） |
| 2 | 交换 apiserver.crt 为不发证 | `x509: certificate signed by unknown authority` / curl 413 | kubeadm certs renew apiserver + 静态 Pod 重启（§5.2） |
| 3 | 卡 CNI（cilium Pod kill 锁） | Node NotReady + Pending Pods 大涨 | kubelet restart → cilium operator 自愈 → 最后兜底 `kubectl delete pod -l k8s-app=cilium` 重起 |
| 4 | kubelet kill -STOP | Node NotReady（40s 后）/ node-lifecycle taint | systemctl restart kubelet；练记事 kubelet code 50s（§6.2） |
| 5 | 塞爆根盘（fallocate 20G） | DiskPressure → eviction 连环 → kubelet 死 | 清盘 + 校验 eviction 默认表（§6.4） |
| 6 | 期 Ingress 证书（含 SAN 过期） | `curl -k https://` 不可控 `;kubectl` 报证书过期 | §5.2 renew 条数 + Ingress TLS secret rotate |
| 7 | 删 CoreDNS / 拦 6443 安全组 | 业务全部 cluster.local 解析失败 / API 不可达 | 恢复安全组 + CoreDNS 增补：第 3 章 DNS 排障 + §2.6 PORT 表 |

> ❗ L3 的每一场你都要在笔记本里写三行：「破坏前我做了什么快照/备份」「破坏中 `kubectl get --raw=/readyz?verbose` 与 `kubectl get events -A` 放射么」「恢复中哪个对象是最大因果」——三行齐备，你的 runbook 就真正 Net-a-Porter.

---

## 十、实验（实验 L2、L3 的操作本体）

以下 4 个实验都在 **Multipass VM**（参照 `云服务/Multipass-使用指南.md`）上完成——Mac 本机不在跑 kubeadm。

### 实验 7.1 Multipass 三节点完整搭建记录（L2 上篇：v1.37 三节点 kubeadm 集群）

**step 0：宿主机一台过（macOS）**——`multipass version` 能动就成。

```bash
# step 1：三台 VM（1 cp + 2 worker），Ubuntu 24.04 LTS（noble）
multipass launch 24.04 --name k8s-cp1  --cpus 2 --memory 4G --disk 20G
multipass launch 24.04 --name k8s-w1   --cpus 2 --memory 4G --disk 20G
multipass launch 24.04 --name k8s-w2   --cpus 2 --memory 4G --disk 20G
multipass list       # 记下三台 IP：10.x.x.x 映射自己的私网段
```

**step 2：每台 VM 跑前置准备（§2 八件事一次过）**——`multipass shell k8s-cp1` 进去或 `multipass exec` 逐台执行；成品脚本你直接 `multipass transfer` 过去：

```bash
# 2A swap + 内核/sysctl（§2.1 §2.2 命令合写）
sudo swapoff -a && sudo sed -i '/ swap / s/^\(.*\)$/#\1/' /etc/fstab
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
sudo modprobe overlay && sudo modprobe br_netfilter
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
EOF
sudo sysctl --system

# 2B containerd + SystemdCgroup（§2.3）
sudo apt-get update && sudo apt-get install -y containerd
sudo mkdir -p /etc/containerd && containerd config default | sudo tee /etc/containerd/config.toml >/dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
sudo sed -i '/^disabled_plugins/ s/^/# /' /etc/containerd/config.toml
sudo systemctl restart containerd

# 2C chrony（§2.5） + kubeadm/kubelet/kubectl（§2.8）
sudo apt-get install -y chrony && sudo systemctl enable --now chrony
sudo apt-get install -y apt-transport-https ca-certificates curl gpg
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key | \
  sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.37/deb/ /' | \
  sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update && sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```

**step 3：k8s-cp1 上 init（用的 §1.4 v1beta4 完整样例；`controlPlaneEndpoint` 写 `k8s-cp1:6443`，advertiseAddress 写 VM 私网 IP）**：

```bash
sudo kubeadm init --config kubeadm-config.yaml --upload-certs 2>&1 | tee /tmp/kubeadm-init.log
mkdir -p $HOME/.kube && sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && \
sudo chown $(id -u):$(id -g) $HOME/.kube/config
kubeadm token create --print-join-command    # 复制 worker join 命令（--token + --discovery-token-ca-cert-hash）
```

**step 4：CNI（Cilium，§3.4 同样的安装命令，哪台但只要有 kubectl 的位置都行）**：

```bash
helm repo add cilium https://helm.cilium.io/ && helm repo update
helm install cilium cilium/cilium --version 1.20.2 -n kube-system \
  --set image.pullPolicy=IfNotPresent --set ipam.mode=kubernetes
cilium status --wait
```

**step 5：w1/w2 join（`multipass shell k8s-w1` / `k8s-w2`，粘 join 命令并完成他们各自的 §2 前置）**。

**step 6：验收三行**：

```bash
kubectl get nodes -o wide                                  # 3 行 Ready，ROLES 分别 control-plane/<none>
kubectl -n kube-system get pods -o wide | grep -E 'cilium|coredns|kube-proxy'
kubectl get --raw='/readyz?verbose' | tail -6              # etcd/poststarthook 全 ok
```

> ❗ 多虚拟机下本实验的 kick 闷都 cloak 在 `/tmp/kubeadm-init.log` 与 `journalctl -u kubelet -f`——那两条奢侈的故障促派信（ImagePullBackOff、daemon reset）都在这两个文件里首发，别从 stdout 猜原因。

**实验收获**：你能从 blank VM走到 `kubectl version` 3-Ready 的完整二不发生每一次事故发生点；下一步所有章节都以这个集群为主场。

### 实验 7.2 升级演练模板（L2 下篇：v1.37 → v1.38，**v1.38 发布后执行，到时替换占位符**）

> ❗ v1.37 是当前最新发布版，1.38 尚未发布。下方命令里 `1.38.x-*` `/v1.38` 都是占位符——届时用 `apt-cache madison kubeadm` 找到最新的 v1.38 patch。

```bash
# ========== k8s-cp1（首台控制面） ==========
# ① （可选但推荐）etcd 手动快照——不是 kubeadm 的备份，是独立的证据辈记忆
sudo ETCDCTL_API=3 etcdctl snapshot save /tmp/snapshot-pre-upgrade.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# ② 表 Minor：pkgs.k8s.io 的 1.38 目录
sudo sed -i 's|core:/stable:/v1.37|core:/stable:/v1.38|' /etc/apt/sources.list.d/kubernetes.list
sudo apt-mark unhold kubeadm
sudo apt-get update && sudo apt-get install -y kubeadm='1.38.x-*'
sudo apt-mark hold kubeadm
kubeadm version -o short

# ③ plan + apply（apply 参数包含 etcdUpgrade/certificateRenewal 默认 true）
sudo kubeadm upgrade plan
sudo kubeadm upgrade diff v1.38.x           # 着清单差
sudo kubeadm upgrade apply v1.38.x
# 期望尾两行：
#   [upgrade/successful] SUCCESS! Your cluster was upgraded to "v1.38.x".
#   [upgrade/kubelet] Now that your control plane is upgraded...

# ④ drain → kubelet/kubectl 升 → uncordon
kubectl drain k8s-cp1 --ignore-daemonsets
sudo apt-mark unhold kubelet kubectl && \
sudo apt-get install -y kubelet='1.38.x-*' kubectl='1.38.x-*' && \
sudo apt-mark hold kubelet kubectl
sudo systemctl daemon-reload && sudo systemctl restart kubelet
kubectl uncordon k8s-cp1

# ========== k8s-w1 / k8s-w2（逐台；XXX 表示 worker 名） ==========
multipass exec k8s-w1 -- sudo bash -c "apt-mark unhold kubeadm && apt-get update && apt-get install -y kubeadm='1.38.x-*' && apt-mark hold kubeadm"
multipass exec k8s-w1 -- sudo kubeadm upgrade node
kubectl drain k8s-w1 --ignore-daemonsets
multipass exec k8s-w1 -- sudo bash -c "apt-mark unhold kubelet kubectl && apt-get install -y kubelet='1.38.x-*' kubectl='1.38.x-*' && apt-mark hold kubelet kubectl && systemctl daemon-reload && systemctl restart kubelet"
kubectl uncordon k8s-w1
# 同一序拓 k8s-w2

# ========== 收尾验证 ==========
kubectl get nodes -o wide                       # 三行均为 v1.38.x Ready
kubeadm certs check-expiration                  # renew 全部在，残留 364d/365d 左右
kubectl get --raw='/readyz?verbose' | tail -3  # 仍是 ok
```

> 想要 reverse 练习（v1.37 → v1.37 patch）时，把目标容器从 `v1.38.x` 换成下一个 patch 并重跑同样序列即可——**顺序不变**。**`multipass snapshot` 用不了了后**，请用 VM 级快照代替 etcd 快照（etcd restore 也不支 VM snapshot 时间导中的时间点，但是「物理上恢复 VM」+「控制面数据这只等上快递达人天然差」是不可替换的两层）。

### 实验 7.3 证书实验（L3 中篇）

```bash
# ① 查表
sudo kubeadm certs check-expiration
# ② 单件 renew（break-glass 后记得验旧）
sudo kubeadm certs renew apiserver
# ③ 静态 Pod 重启（四件分别重覆他们檔）
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/ && sleep 20 && \
  sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
# ④ 验证新证书 SAN 在
openssl s_client -connect 127.0.0.1:6443 -servername k8s-cp1 </dev/null 2>/dev/null | \
  openssl x509 -noout -subject -ext subjectAltName -dates
# ⑤ kubelet serving 证书自签验证（kubelet 自带的）
openssl s_client -connect 127.0.0.1:10250 </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates
# ⑥ client 证轮转开关确认
kubectl get cm kubelet-config -n kube-system -o=jsonpath='{.data.kubelet}' | grep -E 'rotateCertificates|serverTLSBootstrap'
```

> ❗ 第 ⑤ 步期望看到 `subject=CN=k8s-cp1@<timestamp>`、`issuer=CN=k8s-cp1-ca@<timestamp>`——**自签证据**摆在眼前：metrics-server 试图多家里长些时它也会那天性 out--`x509: certificate signed by unknown authority`——第 ⑥ 步把 `serverTLSBootstrap: true` 起之后时间 mutual _state。

### 实验 7.4 eviction 实验：上个内存炸弹看 kubelet evict（观察 QoS 顺序）

```bash
# ① 一个 Burstable Pod 大内存（linux.org 容器，尽量小镜像）
kubectl apply -f - <<'YAML'
apiVersion: v1
kind: Pod
metadata: { name: mem-bomb }
spec:
  containers:
  - name: bomb
    image: polinux/stress
    command: ["stress"]
    args: ["--vm", "1", "--vm-bytes", "3G", "--vm-hang", "120"]   # 3G 内存开局
    resources:
      requests: { memory: "128Mi", cpu: "100m" }                  # 一请求 Burstable
      limits:   { memory: "4Gi" }                                  # limit比 node 小，才能看到 kubelet evict 而不是 cgroup OOM
YAML

# ② 观察队列与 QoS
kubectl get pod mem-bomb -o jsonpath='{.status.qosClass}{"\n"}'   # Burstable

# ③ 观察 eviction 反应（mem-bomb 在 node 看成 message）
kubectl describe node k8s-w1 | grep -A5 -E 'Conditions|MemoryPressure|evict'
kubectl get events -A --sort-by='.lastTimestamp' | grep -iE 'evict|memory'
```

**观察要点**（对照 §6.4 eviction 排序）：

- mem-bomb 的 **usage(3G) > requests(128Mi)** 是第一排 evict 候选——QoS 要等 Usage 超 request 才轮到；
- 同时排一个 BestEffort Pod（无 resources）会**先于** Burstable 被 evict（usage 永远 > 0 request；它是「usage > request」）
- 升级 Pod 的 priorityClassName 到 `system-node-critical` 再跑一次——kubelet oom_score_adj=-997 上升、OOM 方向由 eviction 切换；卷积 Priority 后最后的 Guaranteed Pod（requests=limits 且 usage ≤ requests）才会在广东成为 evict 候选；
- 静电 Pod 与静态 Pod（/etc/kubernetes/manifests/）会被 evict 之后kubelet 仍强生重新拉起（node-pressure eviction 页原话：static Pod 代表「要该 node 上跑的 intent」）

**清理**：

```bash
kubectl delete pod mem-bomb --force --grace-period=0
kubectl describe node k8s-w1 | grep -iE 'MemoryPressure|eviction manager'
```

> 实验收获：把「QoS/Priority/usage 三者」的 eviction 排序亲手看到了——这通观点在生产的 「MemoryPressure 致节点 Banner」告警链里会被你原样认出来。

---

## 十一、速查表 + 背诵要点 + 参考链接

### 11.1 一页速查（按主题）

| 主题 | 命令 / 字段 / 默认值 |
|------|---------------------|
| kubeadm 六大族 | `init / join / reset / token / certs / upgrade`；`kubeadm config print init-defaults / join-defaults` |
| 配置 API | `kubeadm.k8s.io/v1beta4` 现行（v1.37 起 v1beta3 移除——release-1.37 源码 `cmd/kubeadm/app/apis/kubeadm/` 只剩 v1+v1beta4） |
| v1beta4 关键字段 | `InitConfiguration.certificateKey`(AES-32B hex，2h token)；`ClusterConfiguration.controlPlaneEndpoint`（HA 必须在 init 写）；`apiServer.certSANs`（SAN 未来路径）；`encryptionAlgorithm`（RSA-2048 默认，**v1.34 起含 ECDSA-P384**）；`certificateValidityPeriod` 8760h / `caCertificateValidityPeriod` 87600h（默认 1y/10y） |
| swap / cgroup / sysctl | `failSwapOn=true` 默认；`cgroupDriver: systemd` 与 containerd `SystemdCgroup=true` 配钦；sysctl 三件 `bridge-nf-call-iptables / bridge-nf-call-ip6tables / ip_forward` |
| 端口表（v1.37 official） | 控：6443 / 2379-2380 / 10250 / 10257 / 10259；worker：10250 / 10256 / 30000-32767（TCP+UDP）；kubeadm 附加：etcd metrics 2381、kubelet healthz 10248 |
| 静态 Pod 心智 | `/etc/kubernetes/manifests/*.yaml` → kubelet 每 20s 扫（fileCheckFrequency）→ spec hash 变即重启；修改 API 对象没用，改文件才算 |
| join 防 MITM | `--discovery-token-ca-cert-hash sha256:<hash>`；hash = CA 公钥 SPKI SHA-256：`openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt \| openssl rsa -pubin -outform der 2>/dev/null \| openssl dgst -sha256 -hex` |
| 版本偏差（v1.37） | apiserver 同 HA ±1；kubelet ≤ apiserver 殒3 minor；CM/scheduler ≤ 1 老；kubectl ±1；kubeadm vs 控制面 同/+1 |
| 升级序列 | ① etcd 快照 + 参考 plan → ② 首台 CP `apply` → ③ 后续 CP `node` → ④ drain → ⑤ 升 kubelet/kubectl 包+hold → ⑥ uncordon → ⑦ worker 重复 |
| upgrade 边界 | 不恢复手工 extraArgs；重写静态清单；同时自动 renew 证书（`--certificate-renewal=false`关）；备份在 `/etc/kubernetes/tmp/kubeadm-backup-*` |
| 证书家谱 | 3 把 CA（kubernetes-ca / etcd / front-proxy）+ SA 密钥对；admin.conf=B移栽 `kubeadm:cluster-admins`、super-admin=breakglass `system:masters` |
| check/renew | `kubeadm certs check-expiration`；`kubeadm certs renew all`；renew 后重启四静态 Pod（mv 清单 trick，20s+20s） |
| kubelet 证 | client：`rotateCertificates: true` kubeadm 默认 + csrapproving selfnodeclient 自动批；serving：默认自签，生产 `serverTLSBootstrap: true` +**外置 approver**（kubernetes.io/kubelet-serving 不自动批） |
| CA 根 rotation | 10 步流程（新 CA→SDP-bundle→重发SA→重启组件→kubelet bundle→apiserver重签→Pod rollout→清旧 CA）；泄漏/合规才做，常态不轮 |
| apiserver flag 默认 | inflight 400/200（APF=600 total）；watch-cache true；etcd-compaction-interval 5m0s；min-request-timeout 1800；goaway-chance 0~0.02（先用 0.001）；shutdown-delay-duration 用于 HA 摘除 |
| CM/scheduler/proxy QPS | CM：20/30；scheduler:50/100；kube-proxy：5/10（flag 层，配置层默认对齐）；CM concurrent-*：deployment/replicaset 5、gc 20、endpoint 5、namespace 10 |
| etcd 大集群策略 | 静态 5-member；事件拆事件 etcd；quota 默认 2GiB；defrag 程序化 CronJob（官方「as infrequently as possible」） |
| kubelet 调优点 | maxPods=110（官方硬上限）；imageGCHigh/Low=85/80；containerLogMaxSize=10Mi×5=50Mi；evictionHard 四条默认 + mergeDefaultEvictionSettings；serializeImagePulls=true |
| 节点自运维 | NPD 4 daemon + 3 exporter（k8s/prometheus/stackdriver）；draino=watch condition→label+drain，重 PDB+leader election；原仓 cloudflare/draino 已 404，自選活跃 fork（如 planetlabs/draino） |
| 大规模数字（v1.37 official） | ≤5000 节点 / ≤150000 Pod 总量 / ≤300000 容器 / **≤110 Pod per node** |
| 租户治理 | ResourceQuota（requests+limits+storage+count+scopeSelector）＋LimitRange（defaultRequest/default/min/max/maxLimitRequestRatio）＋requests/limits 纪律（memory limit照写；CPU limit只在「超售受限」时照写） |
| 灾备铁三角 | etcd 快照（每小时+升级前）＋基建 IaC（reload）＋Velero（对象面每日）；恢复优先序：静态清单 → etcd → 组件 → RBAC webhook → CNI/DNS/proxy → 业务 |

### 11.2 关键要点（背诵版）

1. **kubeadm 只做 cluster lifecycle 的 subset**：init/join/upgrade/certs/token/reset；CNI、Ingress、监控、etcd 备份是你的运维边界（§1.1）。配置文件 **`v1beta3` 已在 v1.37 移除**，v1beta4 是唯一选择（release-1.37 源码核实）。
2. **前置准备 = 8 件套**：swap off + sysctl 三联 + containerd **SystemdCgroup=true** 与 kubelet 一致 + sandbox_image 国内加速 + chrony + 端口开放 + pkgs.k8s.io 安装 + `apt-mark hold`。**cgroup driver 不一致是 quota 黑洞型故障的典型根源**（§2.3）。
3. **`controlPlaneEndpoint` 在 init 就写**——单点将来上 HA 可谓必写；`certSANs` 决定 apiserver 自签证的 SAN 覆盖，之后改就要 renew+重启（§5.2）。
4. **join 防 MITM 的双保险**：token=入场券（authn 低权限），`--discovery-token-ca-cert-hash`=钉住 CA 公钥（可验防篡改，公式是 CA SPKI SHA-256）——`kubeadm token create --print-join-command` 一条重发全套。
5. **升级序列是官方写死的**：apiserver（首 CP apply / 后续 CP node）→ CM/scheduler → kubelet → kube-proxy；**kubeadm upgrade 不支持重配**（reconfigure 是另一套）、重写静态清单=你手工塞的 extraArgs 会丢、同过自动 renew 证书；etcd 快照是必走的第一步（§4.3）；**HA 集群里 API 在升级期间的连续可用性靠 LB 的 readyz 探针遮住（§4.4 实验）**。
6. **证书一年、CA 十年**（源码：8760h / 87600h）；renew 用旧证书 attr 而**不读 kubeadm-config ConfigMap**；四静态 Pod 必重启——mv 清单 20 s 等 fileCheckFrequency。
7. **kubelet 证**：client default 自动轮转 + csrapproving 自动批（selfnodeclient）；serving 默认自签（`x509 unknown authority` 的常见画面）——生产开 `serverTLSBootstrap: true` 必配**第三方 approver**（kubernetes.io/kubelet-serving 不会自动批）。`RotateKubeletServerCertificate` **v1.37 Beta 默认开**。
8. **CA 根换新是 10 步黑白序**（bundle 期 → 全 Pod token 重签 → 重建配置 → 筛旧 CA）；常态不轮，泄漏或合规才轮——一次 2~4 小时窗口+全 rollout 是经验值；encryption key 轮换引用第 5 章 §5.2（不重写）。
9. **大规模数字是「支持上限」不是推荐**：≤5000 nodes / ≤150k pods / ≤300k containers / **≤110 pods per node**（官方 large cluster 页，v1.37 仍是同数）——它们的反面是**每节点微型化 + 事件总量**与 apiserver watch 缓存内存的物理约束（§6.5）。
10. **權配·防线·备災**：ResourceQuota/LimitRange 与 PriorityClass 权量（第 2 章 §6.2 已定 system-cluster/node-critical 两个 cone 级）＋ NPD→draino 7 顺位（探测→label→drain）的**标注-dependent 而不是「任何 condition 都自动 drain」**＋ 备份铁三角（etcd 快照 + IaC + Velero）——备没找到前别升没倒表的集群。

### 11.3 参考链接

| 主题 | 链接 |
|------|------|
| kubeadm config API（v1beta4，逐字段+增量） | https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/ |
| kubeadm config API（v1beta3，deprecation 与「1.34 or later 移除」声明） | https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta3/ |
| kubeadm-certification 管理（check-expiration / renew / serverTLSBootstrap / super-admin.conf） | https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/ |
| kubeadm upgrade 全流程（v1.37 页） | https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/ |
| kubeadm 建集群（controlPlaneEndpoint / join 命令 / admin.conf 警告） | https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/ |
| HA topology（stacked vs external etcd 官方二选一） | https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/ha-topology/ |
| 版本偏差政策（同联组件 skew 表与升级顺序） | https://kubernetes.io/releases/version-skew-policy/ |
| 端口与协议（6443/2379-2380/10250/10257/10259/10256/NodePort 30000-32767） | https://kubernetes.io/docs/reference/networking/ports-and-protocols/ |
| kube-apiserver flags（max-requests-inflight 400/200、goaway-chance、shutdown-delay-duration、min-compatibility-version） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-apiserver/ |
| kube-controller-manager flags（kube-api-qps 20/burst 30、concurrent-*、cluster-signing-duration） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-controller-manager/ |
| kube-scheduler flags（kube-api-qps 50/burst 100） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-scheduler/ |
| kube-proxy flags（kube-api-qps 5/burst 10、mode iptables） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-proxy/ |
| KubeletConfiguration v1beta1（maxPods/imageGCHigh/containerLogMaxSize/evictionHard/failSwapOn/failCgroupV1/hugepages） | https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/ |
| Node-pressure eviction（evictionHard 五条默认、排序规则、OOM scores、HugepageAwareEviction Beta v1.37） | https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/ |
| Manual CA rotation（10 步 + #1350 坑） | https://kubernetes.io/docs/tasks/tls/manual-rotation-of-ca-certificates/ |
| TLS bootstrapping（csrapproving 默认开、kubelet serving 不自动批、kubelet-csr-approver 要点） | https://kubernetes.io/docs/reference/access-authn-authz/kubelet-tls-bootstrapping/ |
| PKI 证书需求表（3 把 CA + 各 cert CN/usage 对照） | https://kubernetes.io/docs/setup/best-practices/certificates/ |
| Large clusters（5000 节点 / 150000 Pod / 110 per node / 事件拆 etcd / PriorityClass 建议） | https://kubernetes.io/docs/setup/best-practices/cluster-large/ |
| Operating etcd clusters for K8s（5-member 推荐、etcdctl vs etcdutl、EtcdRangeStream v1.37 Beta） | https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/ |
| Monitor Node Health（NPD 4 daemon 与 3 exporter） | https://kubernetes.io/docs/tasks/debug/debug-cluster/monitor-node-health/ |
| NPD Helm chart（deliveryhero repo，artifacthub 收录） | https://artifacthub.io/packages/helm/deliveryhero/node-problem-detector |
| Container runtimes（containerd 1.x vs 2.x SystemdCgroup、KubeletCgroupDriverFromCRI、pause 3.10、cgroup v1 已废） | https://kubernetes.io/docs/setup/production-environment/container-runtimes/ |
| kubeadm 常数（release-1.37 源码：etcd 3.7.1-0 / CoreDNS v1.14.7 / Pause 3.10.2 / certValidityPeriod / 计时器默认） | https://raw.githubusercontent.com/kubernetes/kubernetes/release-1.37/cmd/kubeadm/app/constants/constants.go |
| 源码：kubeadm API 目录仅含 v1+v1beta4（v1beta3 已移除） | https://github.com/kubernetes/kubernetes/tree/release-1.37/cmd/kubeadm/app/apis/kubeadm |
| ComponentStatus deprecated 来源（v1.19 changelog） | https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.19.md |
| draino 原仓与 fork（原仓 cloudflare/draino 已 404，兼容 fork 需自选） | https://artifacthub.io/?q=draino / https://github.com/search?q=draino |

---

> 下一章预告：`K8s-故障排查方法论.md`（第 8 章）——本手册中各章出现的「破坏场景」（kubeadm init fail、证书过期、eviction storm、etcd quota、CNI 不通）会在第 8 章整理成**症状→工具→修复**的分域排障树，实验 L3 的 runbook 本体则要归档。
