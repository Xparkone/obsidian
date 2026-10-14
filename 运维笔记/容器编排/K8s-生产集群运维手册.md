# K8s 生产集群运维手册

> 精通路线第 7 章：kubeadm 生产形态、搭建 L2 三节点集群、升级序列、证书与 CA 轮转、控制面调优参数、节点自运维（NPD/draino）、租户治理、灾备恢复编排、大集群设计约束
> 创建时间：2026-10-14
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37；v1.38 尚未发布，升级演练章节给出命令模板并标注「发布后执行」），文中标注「v1.xx 起 Beta/GA」均取自官方文档、KEP 或上游源码，执行时仍以你本地集群版本为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，APF/list-watch/5 分钟历史窗口直接引用不重讲）、`K8s-网络原理详解.md`（第 3 章，CNI 选型只给结论）、`K8s-安全加固详解.md`（第 5 章，PSA/Secret 静态加密/密钥轮换直接引用不重讲）。**本文同时是实验 L2（Multipass 三节点 kubeadm 集群）与 L3（破坏-恢复演练）的操作手册本体**（总纲：`学习/K8s-精通路线-总纲.md`）。

---

## 零、本文定位与边界

### 0.1 为什么必须亲手拥有控制面

用 K3s 或云托管集群时，控制面对你是个黑盒：etcd 配额怎么判断、证书如何轮转、升级按什么顺序滚——你都没地方看。而生产事故永远发生在黑盒里：**API 响应变慢、CSR 卡住、kubelet eviction 连环驱逐、升级后静态 Pod 起不来**。前 6 章把对象机制、调度、网络、存储、安全、扩展都讲透了，这一章做一件事：**把「控制面」变成你亲手搭、亲手升、亲手修的东西**。原理不变，差别只在「全链路命令都出自你的手」。

```
你的生产集群问题，最终都会变成这几类：
  "kubeadm init 卡住/preflight 报错"      → 前置准备那一层（swap/sysctl/cgroup driver/镜像/端口）   §2 实验 7.1
  "节点 join 不上，hash 校验失败"         → discovery-token-ca-cert-hash 原理（CA 公钥钉住防 MITM）   §3.3
  "升级完，我手改的 extraArgs 没了"       → kubeadm upgrade 会重写静态 Pod 清单（升级四大坑之一）     §4.3
  "控制面证书还有 30 天过期怎么办"         → check-expiration/renew/静态 Pod 重启三件套               §5.2
  "metrics-server 拉不到 kubelet 指标"    → kubelet serving 证书默认自签 vs serverTLSBootstrap       §5.3
  "apiserver 429/504，watch 重连风暴"     → inflight/APF 叠合、goaway、etcd compaction 协同面        §6.1
  "节点 MemoryPressure 连环驱逐"          → kubelet eviction 默认表 + requests/limits 生产纪律       §6.4 §8.3
  "整机坏了，从 etcd 快照恢复的正确顺序"   → 恢复优先级表（先静态清单、再 etcd、再 RBAC webhook）     §9 §10
```

### 本文与实验 L2 / L3 的映射

| 总纲实验 | 本文对应章节 | 验证点 |
|---------|-------------|--------|
| **L2**（Multipass 三节点 v1.37 + 升级 v1.38） | §2 §3 → 实验 7.1；§4 → 实验 7.2 | 「从零搭一个三节点集群并完成一次 minor 升级」 |
| **L3**（破坏-恢复演练） | §5.2/5.3 → 实验 7.3（证书）；§6.4 → 实验 7.4（eviction）；§9.4 → 恢复编排 | 「etcd/证书/CNI/kubelet/磁盘/网络的逐个修复 runbook」 |

> 第 2、3 章的实验 2.x / 3.x 都在 kind 上跑；本章实验全部搬到 **Multipass VM** 上跑——这是生产形态与沙箱形态的分水岭。

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `K8s-etcd详解.md` | etcd 本体运维：快照备份/恢复 etcdctl 命令、NOSPACE 告警、defrag、性能参数 | 本文只讲 **apiserver → etcd 的协同面**（quota 判断、compaction 窗口、升级影响），不复述 etcdctl 细节 |
| `K3s-部署指南.md` | K3s 发行版差异（SQLite 默认、single binary、内置 addon） | 一句带过：本章是 **kubeadm 生产形态**，不是发行版对比 |
| `K8s-组件详解.md` | 各组件功能与端口总表 | 端口表只列 kubeadm 生产形态必须的（§2.6），组件功能不重复 |
| `Velero-Kubernetes备份恢复与迁移指南.md` | 备份/恢复/迁移全景（BSL/VSL、Data Mover、演练） | 只在 §9 一句衔接：「对象面备份走 Velero，本文管控制面本体」 |
| `监控/`（Prometheus/Victoria 部署篇） | 监控栈怎么部署 | 本文只讲 **控制面组件本身的指标与告警阈值**（§6.1/6.2），不讲部署 |
| `云服务/Multipass-使用指南.md` | Multipass 命令速查 | 实验 7.1 一句引用，不重复教程 |

> ❗ **版本标注约定**：文中形如「v1.37 默认开」「X 默认 400」「v1beta3 已移除」的说法均对照官方 docs（kubernetes.io）、command-line-reference 各页或 k/kubernetes release-1.37 源码（`cmd/kubeadm/app/constants/constants.go`、`pkg/features/kube_features.go`）逐条核实；个别字段（feature gate 默认值、镜像 tag）可能随 minor 漂移，落地前用
> ```bash
> kubectl get --raw /api/v1/nodes/<node>/proxy/configz | grep -iE 'featuregate|eviction|containerlog|maxpod' | head
> kubectl get cm kubeadm-config -n kube-system -o=jsonpath='{.data.ClusterConfiguration}'
> ```
> 再确认一次。

---

## 一、kubeadm 生产形态全认识

### 1.1 kubeadm 做与不做的边界

kubeadm 的官方自我定位是「**cluster lifecycle 的最小构建块**」（GA）：它只负责「让集群能跑起来 + 维护一部分生命周期」，**之外的全部是你自己的运维面**。

| kubeadm 做（GA） | kubeadm 不做 |
|------------------|-------------|
| init/join 引导：TLS bootstrap、生成根 CA 与组件证书、写静态 Pod 清单、启动控制面、注册 Node 对象 | **不管理 CNI**（init 后 CoreDNS 都不会 Running，直到你装 CNI） |
| `kubeadm config`/`token`/`certs`：集群内对象（ConfigMap kubeadm-config、Secret kubeadm-certs、bootstrap token Secret）与 PKI 的运维子命令 | **不装 Ingress / LoadBalancer**（云厂商 cloud-controller-manager 或 MetalLB 自己来） |
| `kubeadm upgrade` 全流程（plan/apply/node/diff） | **不管监控栈**（Prometheus/metrics-server 都是 addon） |
| Reset node（`kubeadm reset`，best-effort 清掉本机的 kubeadm 痕迹） | **不管 HA/LB 拼装**：1 个 CP 是给的，3 个 CP + LB 是你拼的（§3.1） |
| 把集群级配置写进 ConfigMap `kube-system/kubeadm-config`（存 **ClusterConfiguration**，供 join/upgrade 反查） | **不替你备份 etcd**（§9 的备份是你自己的纪律） |

> ❗ **反直觉的一条**：init 时写在 InitConfiguration 里的字段（bootstrapTokens、nodeRegistration、localAPIEndpoint 等**本机局部配置**）**不会**上传到 kubeadm-config ConfigMap——ConfigMap 里只有 ClusterConfiguration。v1beta4 文档原话："This information IS NOT uploaded to the kubeadm cluster configmap, partly because of its sensitive nature"。想找回某节点 init 时的局部配置，只能去那台节点本身看 `/etc/kubernetes/admin.conf`、`/var/lib/kubelet/config.yaml`、`pki/` 与 hostname。

### 1.2 六个命令族：一张图读完

```
                        ┌─ kubeadm init      ── 首台控制面（全文的主角）
      引导 / 搭集群 ────┼─ kubeadm join      ── CP join（--control-plane --certificate-key）/ worker join
                        └─ kubeadm reset     ── 干净退出（best-effort，iptables/ipvs 要手工清，见 §3.7）
      对象内省        ─── kubeadm config     ── print init-defaults / 老 API 版本迁移
      token 生命周期  ─── kubeadm token      ── create / list / delete（默认 TTL 24h）
      证书运维        ─── kubeadm certs      ── check-expiration / renew all / generate-csr（§5）
                        ┌─ kubeadm upgrade plan  ── 检查可升版本 + 组件/配置版本状态表
      升级  ────────────┼─ kubeadm upgrade apply ── 首台控制面升级
                        ├─ kubeadm upgrade node  ── 后续 CP / 每个 worker 单节点
                        └─ kubeadm upgrade diff  ── 当前配置 vs 目标版本的清单差
```

每条命令族后面挂着 **Phase 机制**：`kubeadm init phase <name>`（如 `phase certs all`、`phase kubeconfig all`、`phase etcd local`）——这是能把 kubeadm 当乐高拆着用的关键；对接外部 CA 时（§5.1）就靠 `kubeadm certs generate-csr` 配合 phase 命令链拼装凭证。

### 1.3 配置文件 API 版本时间线（v1beta3 → v1beta4 官方核实）

| API 版本 | 服役区间 | 退役版本 | 现行状态（v1.37，源码核实） |
|---------|---------|---------|------------------------|
| `v1beta1` | v1.13~v1.21 | **v1.22 起不再支持** | 不能读 |
| `v1beta2` | v1.15~v1.26 | **v1.27 起不再支持** | 不能读 |
| `v1beta3` | v1.22~v1.36 | **v1.37 移除** | release-1.37 源码 `cmd/kubeadm/app/apis/kubeadm/` 只剩 `v1`（internal）+ `v1beta4`，v1beta3 目录已删 |
| `v1beta4` | **v1.31 引入**，现行 | — | 现行唯一可用版本；官方原话「kubeadm v1.31.x and newer can be used to migrate from v1beta3 to v1beta4」 |

> ❗ **v1beta3 → v1beta4 不只是字符串变了**（v1beta4 的相对增量，逐条来自官方 v1beta4 页）：

| 版本 | v1beta4 增量 |
|------|-------------|
| **v1.31（首发）** | ① extraArgs 结构化：旧 `map[string]string` → 新 `[]Arg{name,value}`，**同名参数允许重复**；② 新增 `ResetConfiguration`，`kubeadm reset` 可带 `--config`；③ 新增 `UpgradeConfiguration`，`kubeadm upgrade` 各子命令可带 `--config`；④ `InitConfiguration.dryRun` / `JoinConfiguration.dryRun`；⑤ `ClusterConfiguration.encryptionAlgorithm`（RSA-2048 默认 / RSA-3072 / RSA-4096 / ECDSA-P256）；⑥ `dns.disabled` / `proxy.disabled`（init 时禁 CoreDNS/kube-proxy addon）；⑦ `certificateValidityPeriod` / `caCertificateValidityPeriod`（默认 8760h=1 年 / 87600h=10 年）；⑧ `Timeouts` 结构收拢旧 `timeoutForControlPlane`、`discovery.timeout` 等 |
| **v1.33** | `UpgradeConfiguration.plan.etcdUpgrade`（控制 plan 是否展示 etcd 升级） |
| **v1.34** | `encryptionAlgorithm` 增加 `ECDSA-P384` |
| **v1.35** | `ClusterConfiguration.etcd.external.httpEndpoints`（external etcd 的 /metrics、/health 等 HTTP 流量可与 gRPC 分端口，对应 etcd `--listen-client-http-urls`） |

### 1.4 v1beta4 配置文件逐字段精读（生产可粘贴样例）

`kubeadm config print init-defaults` 打印官方默认字面值；我们直接给一份**实验 7.1 实际使用的完整样例**（字段已对照官方 v1beta4 页逐项核实默认值）：

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
bootstrapTokens:
  - token: "lz6t5a.3j7qk2m9p4xyz8ab"
    ttl: "24h"                        # 默认 24h
    usages:
      - signing
      - authentication                # join 必需的两种 usage（对应官方样例）
    groups:
      - system:bootstrappers:kubeadm:default-node-token
nodeRegistration:
  name: "k8s-cp1"                     # Node 对象名 + kubelet 客户端证 CN；本机配置，不进 ConfigMap
  criSocket: "unix:///var/run/containerd/containerd.sock"
  taints: []                          # 不写 = 控制面自动打 control-plane taint；想放行工作负载就显式置空
  kubeletExtraArgs:                   # v1beta4 起 []Arg 结构，允许同名参数重复
    - name: node-ip
      value: "10.0.0.11"
  ignorePreflightErrors: []           # 经典组合：IsPrivilegedUser,Swap；生产别用 all
localAPIEndpoint:                     # 本台 apiserver 实例的对外平面
  advertiseAddress: "10.0.0.11"
  bindPort: 6443
# certificateKey:                     # 32 字节 hex（init 回显的 join 提示里带 --certificate-key）
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.37.0"
controlPlaneEndpoint: "k8s-cp1:6443"  # ★ 单 CP 也一开始就写：将来才可能平滑扩 HA（§3.2 原因）
networking:
  podSubnet: "10.244.0.0/16"          # 与 CNI 的 IPAM 协调（§3.4）；不得与宿主机网段重叠
  serviceSubnet: "10.96.0.0/12"       # 默认；源码约束至少 10 个 IP（MinimumAddressesInServiceSubnet=10）
  dnsDomain: "cluster.local"
etcd:
  local:                              # stacked 形态（§3.1 选型表）；external 的配置面板见该节
    dataDir: "/var/lib/etcd"
apiServer:
  extraArgs:
    - name: authorization-mode
      value: Node,RBAC                # ★ kubeadm 安全强制项：Node+RBAC 组合不许弱化（v1beta4 页明示的安全例外子集）
    - name: etcd-compaction-interval
      value: 5m0s                     # 与第 1 章「5 分钟历史窗口」是同一个 flag（§6.1）
  certSANs:                           # ★ SAN 必须覆盖「将来用什么身份/地址连 API」的全部形态
    - "k8s-cp1"
    - "10.0.0.11"
controllerManager:
  extraArgs:
    - name: cluster-signing-duration
      value: 8760h0m0s                # controller-manager v1.37 cmdline 默认（与证书 1 年周期配套）
certificatesDir: "/etc/kubernetes/pki" # 默认；external-CA 模式见 §5.1
imageRepository: "registry.k8s.io"     # 国内网络才改（§2.4 有 mirror 写法）
clusterName: "kubernetes"
encryptionAlgorithm: RSA-2048          # 默认；嫌不够可 ECDSA-P256/P384
certificateValidityPeriod: 8760h       # 默认 1 年（CA 另为 10 年）——这是 §5 renew 必会的直接原因
---
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
cgroupDriver: systemd                  # ★ 与 containerd 必须一致（§2.3 灾难案例）
maxPods: 110                           # 默认；大节点别随便放大（§6.4）
serializeImagePulls: true              # 默认串行拉镜像；大集群考虑 maxParallelImagePulls（§6.4）
clusterDNS: ["10.96.0.10"]             # serviceSubnet 第 10 个 IP（kubeadm 源码 GetDNSIP 规则）
clusterDomain: cluster.local
authentication:
  anonymous: { enabled: false }
  webhook: { enabled: true }            # 默认：TokenReview
  x509: { clientCAFile: /etc/kubernetes/pki/ca.crt }
authorization:
  mode: Webhook                         # 默认：SubjectAccessReview
serverTLSBootstrap: false               # 默认 false（kubelet serving 自签）；生产开启见 §5.3
rotateCertificates: true                 # kubeadm 写入的默认就是 true（client 证自轮转，§5.3）
---
apiVersion: kubeproxy.config.k8s.io/v1alpha1
kind: KubeProxyConfiguration
mode: "iptables"                       # Linux 默认（可 iptables/ipvs/nftables；Windows 只 kernelspace）
clusterCIDR: "10.244.0.0/16"           # 必须与 networking.podSubnet 对齐
```

**逐字段要盯住的生产要点**（每一条都是升级或 join 时的真实出血点）：

| 字段 | 为什么盯 |
|------|---------|
| `InitConfiguration.certificateKey` | `--upload-certs` 把共享证书/密钥上载成 Secret `kubeadm-certs` 时的加密 key（32 字节 AES）；**源码默认上传 token 有效期 2 小时**（`DefaultCertTokenDuration = 2*time.Hour`），过期要重新发 token + key |
| `ClusterConfiguration.controlPlaneEndpoint` | 写进所有 kubeconfig 与证书 SAN；**单 CP 集群没写它，将来无法平滑转 HA**（官方 create-cluster 页原话） |
| `ClusterConfiguration.apiServer.certSANs` | apiserver 证书的 SAN 必须覆盖未来访问 API 的所有形态：hostname、LB FQDN、VIP——改 SAN = renew + 重启 apiserver（§5.2） |
| `nodeRegistration.kubeletExtraArgs` | 写进本机 kubelet 参数文件（`kubeadm-flags.env`）的**本机覆盖**（如 node-ip / max-pods）——升级时 kubeadm 只刷新集群级 `kubelet-config` ConfigMap，本机值不会替你润色或对齐（§4.3 配置漂移的高发地） |
| 证书相关字段 | `certificatesDir` 默认 `/etc/kubernetes/pki`；`encryptionAlgorithm` / `certificateValidityPeriod` 只在**生成新证书**时生效；renew 时以旧证书的 CN/O/SAN 为准（§5.2） |

---

## 二、前置准备：每台机器开 kubeadm 之前都要过的 8 件事

本节全部在**裸 Ubuntu 24.04 VM**（实验 7.1 的 Multipass VM；生产换云主机/物理机同理）上按顺序执行。命令可粘贴。

### 2.1 swap 必关（kubelet `failSwapOn=true` 默认）

```bash
sudo swapoff -a                                       # 立即生效
sudo sed -i '/ swap / s/^\(.*\)$/#\1/' /etc/fstab     # 重启后也不回来
free -m | grep -i swap                                # Swap 行应全 0
```

kubelet 配置字段 `failSwapOn` 默认 **true**（kubelet-config.v1beta1 页核实）：检测到 swap **直接拒绝启动**——所以这不是「建议关」，是「kubelet 起不来」。`ignorePreflightErrors: [Swap]` 可以糊弄过 preflight，但糊弄不过 kubelet 自身的 fail-on 检查。同层面的另一条硬约束：**v1.37 kubelet 只支持 cgroup v2**（cgroup v1 主机直接 `FailCgroupV1=true` 拒启动），

> ❗ 生产上有人想开 `LimitedSwap`（`memorySwap.swapBehavior`）利用 swap 扛毛刺——那是另一个方向（v1.37 仍 Beta）且改变 QoS 行为，本章生产纪律仍是「关死」。

### 2.2 内核模块与 sysctl（bridged 流量必须过 iptables）

官方 container runtimes 页原话：「Some might expect the administrator to do it for them」——个别 CNI 会自己写 sysctl，但**你要承担「写进去并能自证」的责任**。该页只强制 `ip_forward`；kubeadm preflight 另外查 `br_netfilter` 与 `bridge-nf-call-iptables`：

```bash
# ① 内核模块（写进配置文件，开机也加载）
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
sudo modprobe overlay
sudo modprobe br_netfilter

# ② sysctl 三件套：bridge 流量过宿主 iptables（CNI/kube-proxy 依赖）+ IPv4 转发
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sudo sysctl --system

# ③ 验收（三项都要 == 1）
sysctl net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables net.ipv4.ip_forward
```

**为什么这么设计**：Pod 间 bridged 的纯二层流量默认走 bridge 自己的转发路径，**不过 netfilter**——而 kube-proxy 的 Service 规则、NetworkPolicy 全靠 iptables 链接管。`bridge-nf-call-iptables=1` 通过 `br_netfilter` 钩子让 bridge 帧也过一遍 iptables——这是所有桥接类 CNI 能 work 的隐形前提。

### 2.3 containerd 安装与 SystemdCgroup（运行时与 kubelet 必须同一个 cgroup driver）

官方规则（container runtimes 页）：**kubelet 与容器运行时同一个 cgroup driver**；systemd 作 init 的系统推荐 `systemd`——因 systemd 自身就是 cgroup manager，再叠一个 cgroupfs 就是「两个 manager 两套资源视图」，官方明说：节点在资源压力下会变不稳定（two views of the available and in-use resources）。v1.37 起 kubelet 的 `KubeletCgroupDriverFromCRI`（Beta，默认开）能通过 CRI 的 `RuntimeConfig` RPC **自动探测** runtime 的 driver——**但 containerd 1.x 不支持该 RPC**，且官方注明 **v1.38 会删掉这个 fallback**，老 containerd 届时直接起不来。所以当下生产动作仍是「两边都写死 systemd」：

```bash
# ① 安装 containerd（建议 2.x）
sudo apt-get update && sudo apt-get install -y containerd

# ② 生成默认 config 后改三处：SystemdCgroup、disabled_plugins(auto-cri)、sandbox_image
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
# 排雷：不少官方包默认把 cri 加进 disabled_plugins（docs 原话「you may find that the CRI integration plugin is disabled by default」）
sudo sed -i '/^disabled_plugins/ s/^/# /' /etc/containerd/config.toml
sudo systemctl restart containerd && systemctl status containerd --no-pager | head -4
```

SystemdCgroup 写在哪个 TOML 节点，**按 containerd 主版本分开**（官方逐版本给出）：

- **1.x**：`[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]` → `SystemdCgroup = true`
- **2.x**：`[plugins.'io.containerd.cri.v1.runtime'.containerd.runtimes.runc.options]` → `SystemdCgroup = true`

**灾难案例（cgroup driver 不一致）**：kubelet `cgroupDriver: systemd` + containerd 默认 `cgroupfs`（或反过来）。症状不是「立刻起不来」而是**两套记账体系并存**：Pod 的 cgroup 被 systemd 单位管理，kubelet 按 cgroupfs 口径统计——节点内存压力时，kubelet 认为「Pod 未超 requests」、systemd 处却在按另一套 quota 回收；表现为容器无端 OOM 抖动、CPU throttle 数据与 kubelet 统计对不上、eviction 决策放大。这就是为什么 §1.4 把 `cgroupDriver: systemd` **硬编码进 KubeletConfiguration**——一个值，两个系统共用，别靠运气。

### 2.4 sandbox_image（pause 镜像）与国内镜像加速注意

kubeadm 在 init/join 阶段拉一批镜像：`registry.k8s.io/kube-apiserver`、`kube-controller-manager`、`kube-scheduler`、`kube-proxy`、`coredns`、`pause`、`etcd`——版本由 kubeadm 源码常量决定（v1.37 release 分支核实：`DefaultEtcdVersion = "3.7.1-0"`、`CoreDNSVersion = "v1.14.7"`、`PauseVersion = "3.10.2"`）。而 sandbox_image 是 **containerd** 这一层单独控制的（container runtimes 页现行值 `registry.k8s.io/pause:3.10`）：

```bash
# containerd 2.x：sandbox_image 指向可访问的 mirror，改完必须重启
sudo sed -i 's#sandbox_image = "registry.k8s.io/pause:3.10[0-9.]*"#sandbox_image = "registry.aliyuncs.com/google_containers/pause:3.10"#' /etc/containerd/config.toml
sudo systemctl restart containerd

# kubeadm 层也可以整体换镜像仓库：ClusterConfiguration.imageRepository
# 国内常用：registry.aliyuncs.com/google_containers、m.daocloud.io/registry.k8s.io
kubeadm config images pull --image-repository registry.aliyuncs.com/google_containers   # 换源前先预热
```

> ❗ 易混点：sandbox_image（containerd 配置）≠ pause（kubeadm 拉取列表）。kubelet 起 Pod 的沙箱容器时通过 CRI 找 runtime 的 sandbox image；kubeadm 只帮控制面静态 Pod 拉镜像。两者只要保证「运行时能拉到同一个 pause」——最多人踩的坑是改了 sandbox_image 但忘了 `systemctl restart containerd`。

### 2.5 时间同步（chrony）：证书 notBefore/notAfter 校验的物理前提

证书轮转（§5）就是两个时间戳的游戏；watch 的 RV 窗口、etcd 选举 timeout、leader lease（15s 默认）全都假设**集群时钟同步到秒级**：

```bash
sudo apt-get install -y chrony && sudo systemctl enable --now chrony
chronyc tracking | grep -E 'Leap status|System time'   # Leap status: Normal
```

### 2.6 防火墙/安全组：控制面 vs worker 端口表（对照官方 required-ports 页）

官方只列「必须的」；vendor 附加（etcd metrics 2381、kubelet healthz 10248、kubeadm 源码常量）自己再加。端口是 **TCP inbound**，改过端口按你的值平移。

| 端口 | 控制面 | 用途 | 放给谁 |
|------|--------|------|--------|
| 6443 | ✅ | Kubernetes API server | 所有节点 + 管理员跳板 + LB 后端 |
| 2379-2380 | ✅ | etcd client API / peer 流量 | **仅**控制面节点（stacked）/ etcd 节点（external） |
| 10250 | ✅ | kubelet API | 控制面（metrics-server）、监控、本机 |
| 10259 | ✅ | kube-scheduler（HTTPS healthz/metrics） | 仅控制面 + Prometheus |
| 10257 | ✅ | kube-controller-manager（HTTPS） | 仅控制面 + Prometheus |

| 端口 | worker | 用途 | 放给谁 |
|------|--------|------|--------|
| 10250 | ✅ | kubelet API | 控制面 + 本机 + Prometheus |
| 10256 | ✅ | kube-proxy healthz | **仅** LB 健康探针 / 本机 |
| 30000-32767（TCP+UDP） | ✅ | NodePort 默认区间 | 按你的入口来源收敛 |

ufw 示例（worker 上加这三条；控制面再加 6443/2379-2380/10257/10259）：

```bash
sudo ufw default deny incoming
sudo ufw allow from <公司出口段> to any port 22 proto tcp
sudo ufw allow 10250/tcp
sudo ufw allow 10256/tcp
sudo ufw allow 30000:32767/tcp; sudo ufw allow 30000:32767/udp
sudo ufw enable
```

> ❗ 云主机场景：ufw 之外还有一层 security group 也要同步放行（6443 只给 API 消费方、2379-2380 只给控制面段）。第 3 章《网络原理详解》讲了 NodePort 的连回路径，这里只守端口面。

### 2.7 其余一票否决项（preflight 见它们就炸）

- **SELinux=permissive/disabled**（RHEL 系）：`setenforce 0` + `/etc/selinux/config` 持久化（Ubuntu AppArmor 默认不挡 kubeadm）。
- **containerd CRI 插件不在 disabled_plugins 里**（§2.3 已讲）。
- **`/run/containerd/containerd.sock` 存在且可连**：`crictl info | grep -E 'NAME|containerRuntime'`，kubeadm init 会用同一 socket。
- **内核**：containerd 2.x 需要较新的 linux + cgroup v2 mount——v1.37 kubelet 遇到 cgroup v1 直接 `FailCgroupV1`。

### 2.8 安装 kubeadm / kubelet / kubectl 三件并 hold

官方包源已迁到 `pkgs.k8s.io`（旧 `apt.kubernetes.io`/`yum.kubernetes.io` 自 2023-09-13 deprecated，2023-09 之后的版本只在新源），**每个 minor 一个目录**：

```bash
sudo apt-get update && sudo apt-get install -y apt-transport-https ca-certificates curl gpg
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key | \
  sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.37/deb/ /' | \
  sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl     # ★ 别被 unattended-upgrades 偷袭
kubeadm version -o short                       # 期望 v1.37.x
```

> ❗ 此时 kubelet 会以 crashloop 反复重试——它在等 kubeadm 下发本地配置，这是**正常的预期状态**（创建集群文档原话）。hold 的意图：kubeadm 与集群的 skew 规则（§4.1）要求 kubeadm 与集群同 minor 或高一个；`apt upgrade` 一次跳多个 minor 会直接踩进不支持区间，所以全部 hold——升级时手工 `apt-mark unhold` 是唯一的运维入口。

---

## 三、搭建：1 control-plane + 2 worker

### 3.1 stacked etcd vs external etcd 选型（HA 拓扑官方二选一）

官方 ha-topology 页明确只有两种：**stacked**（etcd 与控制面同机，kubeadm 默认）与 **external**（etcd 独立三台）。逐项对比：

| 维度 | stacked（默认） | external |
|------|----------------|----------|
| 最小节点数 | 3（3 CP） | 6（3 CP + 3 etcd） |
| 故障耦合 | 一台 CP 挂 = 同时丢一个 etcd member + 一个 apiserver → 冗余度双倍受损 | 解耦：CP 挂只损 CP，etcd 挂只损 etcd |
| 资源占用 | etcd 与控制面组件争内存/磁盘 IO | etcd 独占 SSD/内存，路径最短 |
| 运维成本 | kubeadm init/join 一条命令起，etcd 生命周期由 kubeadm 管 | etcd 集群要自己先搭好再喂给 kubeadm；证书签发/分发复杂 |
| 备份/恢复 | 与集群对象一锅端 | etcd 可独立于 K8s 轮换、独立 SLA |
| 升级影响 | kubeadm upgrade 时 apiserver 会等本地 etcd 重启（官方 stall 提醒，§4.2） | 两者互不粘滞，升级可选集更灵活 |
| 适用 | 中小集群（<100 节点）、无强 etcd 磁盘 SLA 诉求 | 大集群/合规苛刻/想跟 etcd 磁盘 IO 单独治理的场景 |

**生产立场**：先用 stacked 3 CP；规模上来或对 etcd 磁盘 IO 有单独 SLA 再切 external。**本文实验 7.1 是 1 CP（stacked 单点）**——L2 重在把 kubeadm 流程吃透；HA 大约就在「多 join 两台」的那一步（§3.3）。

### 3.2 kubeadm init：首台控制面

```bash
# ① 前置 8 件事做完（§2），§1.4 的 v1beta4 配置文件就位
# ② init（--upload-certs 是为将来多 CP/HA 预留一步）
sudo kubeadm init --config kubeadm-config.yaml --upload-certs

# ③ 输出里这三段是钱：
#    mkdir/cp/chown 指导                  → 普通用户连 API
#    kubeadm join <endpoint> --token <TOKEN> --discovery-token-ca-cert-hash sha256:<HASH>
#    （若带 HA 还有一条 --certificate-key <KEY>）
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
kubectl get pods -n kube-system
```

`--upload-certs` 的机制（官方 kubeadm-certs 页 + v1.37 源码）：

- init 时 kubeadm 把**控制面间需共享**的文件（`pki/ca.*`、`pki/front-proxy-ca.*`、`pki/etcd/ca.*`，以及 `pki/sa.*` 这对 SA 密钥）用 AES-256 加密后写入 Secret `kube-system/kubeadm-certs`；
- 加密 key 就是 InitConfiguration 里的 32 字节 hex `certificateKey`（源码 `CertificateKeySize = 32`）；
- 上传权限经 bootstrap token 约束，**有效期 2 小时**（源码 `DefaultCertTokenDuration`）——过期要重发 token + key 重新下载；
- 后续 `kubeadm join --control-plane --certificate-key <key>` 的 CP 解密该 Secret，拿到同一套 CA，让本机静态 Pod 直接用这些证书起 apiserver。

样例里那两行（`controlPlaneEndpoint` + `certSANs`）回答的其实是同一个问题「**将来从哪、用什么身份连 API**」：

- `controlPlaneEndpoint` 写进所有 kubeconfig 与 apiserver 证书 SAN——官方 create-cluster 页原话：**没有 controlPlaneEndpoint 的单点集群没法平滑转 HA**；
- `certSANs` 是未来 LB/跳板/VPN FQDN 的预留位——少写一项，后面就靠 renew + 重启 apiserver 补上（§5.2 流程）。

### 3.3 token + discovery hash：join 的防 MITM 原理

bootstrap token（格式 `abcdef.abcdef0123456789`，Secret 存于 kube-system）是 kubelet 走「TLS bootstrap」（官方 TLS bootstrapping 页）的第一身份。此时新节点**还没有任何证书**，它要回答「对面的 apiserver 是不是真是我老板」——靠 `--discovery-token-ca-cert-hash sha256:<HASH>`：

- 本质是 **CA 公钥钉住**（v1beta4 页原话「public key pins to verify when token-based discovery is used; the root CA found during discovery must match one of these values」）；
- hash 是「CA 证书 DER 编码 SPKI（Subject Public Key Info）的 SHA-256 十六进制」，在控制面现场可算：

```bash
openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
  openssl rsa -pubin -outform der 2>/dev/null | \
  openssl dgst -sha256 -hex | sed 's/^.* //'
# 与 kubeadm init 输出的 --discovery-token-ca-cert-hash sha256:<HASH> 必须一致
```

**为什么这么设计**：

- token 本身只是「认证为 system:bootstrappers 成员」的低权限入场券：有了它你能读到 kube-public 的 `cluster-info` ConfigMap，但**该 ConfigMap 内容本身无防篡机制**；
- hash 把「cluster-info 里返回的 CA 公钥」钉死——网络被劫持换 CA 时 hash 不匹配，join 直接拒绝；**TOKEN 泄漏不构成换 CA 攻击面**；
- `unsafeSkipCAVerification: true` 只在「内网/实验/有别的带外验证」时用，生产严禁（官方：能弱化到「别的节点伪装控制面」的程度）。

token 过期/误泄漏时的重发与废弃：

```bash
kubeadm token list                              # 查剩余 TTL
kubeadm token create --print-join-command       # 重发完整 join 命令（新 token + 原 hash）
kubeadm token delete <TOKEN>                    # 废弃旧 token
```

join 命令本体（控制面/worker 差别仅两个 flag）：

```bash
# worker
sudo kubeadm join k8s-cp1:6443 --token $TOKEN --discovery-token-ca-cert-hash sha256:$HASH

# 第 2/3 台 CP（HA；前提是 §3.1 的 etcd 拓扑已想好，且 LB 已就位）
sudo kubeadm join k8s-cp1:6443 --token $TOKEN --discovery-token-ca-cert-hash sha256:$HASH \
    --control-plane --certificate-key $CERTKEY
```

join 之后 kubelet 自动 TLS bootstrap 拿 client 证书；Node 到 **Ready** 的最后一公里由 **CNI 就绪**决定——下一节装 CNI。

### 3.4 装 CNI：选 Cilium 的一句话

第 3 章《网络原理详解》§4 对比过 Cilium/Calico/Flannel/Istio-CNI——**本章选 Cilium**：eBPF 数据面 + Hubble 免装 sidecar 可见性，已经把它从「选项之一」抬到「运维默认」。最小安装命令（与第 3 章实验同一版本）：

```bash
helm repo add cilium https://helm.cilium.io/ && helm repo update
helm install cilium cilium/cilium --version 1.20.2 \
  --namespace kube-system \
  --set image.pullPolicy=IfNotPresent \
  --set ipam.mode=kubernetes
cilium status --wait        # 全绿：Cilium OK / Operator OK；装 CLI 见第 3 章
kubectl get nodes           # CNI 起来前 Node 是 NotReady；起来后全部 Ready
```

> ★ 与 §1.4 样例呼应：`networking.podSubnet: 10.244.0.0/16` 是 Cilium kubernetes IPAM 模式直接吃 kubeadm 下发的 node.Spec.PodCIDRs——**想躲开宿主机网段，必须在 init 时就规划好 podSubnet**（create-cluster 页：Pod network must not overlap with any of the host networks）。

### 3.5 验证集群真正的姿势：`kubectl get cs` 已 deprecated

**不要再用 `kubectl get componentstatuses`**（`kubectl get cs`）：官方 v1.19 changelog 明确 deprecated——它只在「scheduler/controller-manager 与 apiserver 同机、且暴露未加密健康端口」的时代有意义，是现在对照安全的 kube-controller-manager 的 /healthz（HTTPS + SBOM）形态下的误导信源。替代姿势分三层：

```bash
# ① apiserver 本体 fine-grained readyz（含 etcd 与 poststart hook 链）
kubectl get --raw='/readyz?verbose' | head -20
# etcd ok / [+]poststarthook/start-kube-apiserver-admission-initializer ok ... （对照第 1 章 §9 readyz 判读）

# ② 控制面静态 Pod 是否 Running（用户视角的真实）
kubectl -n kube-system get pods -o wide | grep -E 'kube-apiserver|kube-controller-manager|kube-scheduler|etcd'

# ③ 事件（排查首选）
kubectl get events -A --sort-by='.lastTimestamp' | tail -5
```

### 3.6 静态 Pod 清单：控制面四大件是 kubelet 直接管的 Pod

**心智模型**：控制面四大件（kube-apiserver / kube-controller-manager / kube-scheduler / etcd）**不是 Deployment、不归 apiserver 管**——它们以「静态 Pod 清单」写在控制面节点的 `/etc/kubernetes/manifests/*.yaml`，由 kubelet 的 static pod manager 直接拉起：

- kubelet 每 **20s** 扫一次目录（kubelet 配置 `fileCheckFrequency: 20s` 默认）；
- 清单内容变了 → spec hash 变 → **kubelet 直接重建对应 Pod**（kubeadm upgrade 页原话：「All containers are restarted after upgrade, because the container spec hash value is changed」——upgrade 能让你版本升起来的同时所有容器全重启，光靠的就是这个 hash）；
- `kubectl get pods -n kube-system` 能看到它们，是 kubelet 以 **mirror Pod** 反哺到 API 层——你 delete 这些「镜像对象」**不会影响实际进程**，只有清单文件认了才算；
- 另一条生产语法是：**manifests 目录的读取方向是 kubelet → 文件**（不是 API → 文件），所以它不受 apiserver 停机影响——这正是「apiserver 也能被 kubelet 自己拉起来」的元动力；

> ❗ **灾难形态**（一个真实出血点）：用它理解「**为什么 kubelet 停不了 apiserver 的重启**」——你 cp 一个「半成品的 kube-apiserver.yaml」进 manifests（资源写错、`extraArgs` 拼写错误、证书路径指丢），kubelet 20s 检测后立刻按残文件重建；残文件起不来就会变成 apiserver 连环 crashloop，而你的 `kubectl` 控制面没起连意思是「整个集群等级挂」——这就是实验 7.3「证书实验」的第一步必先看 manifests。**manifests 目录请 git 管起来**，任何变更要进入版本管架，别靠 hist 与非一见生效。

### 3.7 拆除集群：kubeadm reset 与手工清理

重建才有价值的东西必须先可拆。官方 cleanup 页给出的表单（实测 v1.37 一致）：

```bash
# ① 先从集群视角淡出本节点（避免别的 CP 或 LB 把流量踢来）
kubectl drain <node> --delete-emptydir-data --force --ignore-daemonsets

# ② 本机 reset（best-effort）：清 etcd 数据目录、PKI、kubeconfig、静态清单等
sudo kubeadm reset

# ③ ★ 两处 kubeadm reset 不管、手册明确说「手动清理」的：
sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X
sudo ipvsadm -C 2>/dev/null || true     # ipvs 模式才需要；默认 iptables 模式可跳过

# ④ 集群对象里删掉 Node 记录（用有权限的 kubeconfig 在别处执行）
kubectl delete node <node>

# ⑤ 计划搬走整机时直接 multipass delete <node> + multipass purge（实验 7.1 的役毕回收）
```

> ❗ `kubeadm reset` 不会替你静默掉「iptables 还挂着一堆 kube-proxy 旧链」——不做第 ③ 步，新 kubeadm init 起集群后 kube-proxy 规则与旧的纠缠，表现是「**东西半通**」——Service 能解析但某些 endpoint 不通，最难定位。

---

