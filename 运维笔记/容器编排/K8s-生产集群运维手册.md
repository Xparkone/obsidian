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

kubelet 配置字段 `failSwapOn` 默认 **true**（kubelet-config.v1beta1 页核实）：检测到 swap **直接拒绝启动**——所以这不是「建议关」，是「kubelet 起不来」。`ignorePreflightErrors: [Swap]` 可以糊弄过 preflight，但糊弄不过 kubelet 自身的 fail-on 检查。同层面的另一条硬约束：**v1.37 kubelet 只支持 cgroup v2**（cgroup v1 主机直接 `FailCgroupV1=true` 拒启动）。

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
- 清单内容变了 → spec hash 变 → **kubelet 直接重建对应 Pod**（kubeadm upgrade 页原话：「All containers are restarted after upgrade, because the container spec hash value is changed」——这就是升级时所有容器必重启的根因）；
- `kubectl get pods -n kube-system` 能看到它们，是 kubelet 以 **mirror Pod** 反哺到 API 层——你 delete 这些「镜像对象」**不会影响实际进程**，只有清单文件认了才算；
- **manifests 目录的读取方向是 kubelet → 文件**（不是 API → 文件）——apiserver 本身停机也不影响 kubelet 拉它，这正是「控制面四大件能被 kubelet 自己拉起」的元动力；

> ❗ **灾难形态**：手改清单时拼写错一个字符（`extraArgs` 名、证书路径），kubelet 20s 后按残文件重建 apiserver——apiserver 连环 crashloop、整个控制面不可达；此时 kubectl 全废，只能上节点看 `journalctl -u kubelet` 与清单本身——这就是实验 7.3 第一步先审 manifests 的原因。**manifests 目录必须当生产配置对待**：任何变更进版本库（或至少先 `cp kube-apiserver.yaml{,.bak}`），别一次性信任手改。

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


## 四、集群升级：谁也躲不开的运维重磅动作

### 4.1 版本偏差政策（v1.37 官方 version-skew-policy 页逐项核实）

| 组件 | 允许的 skew | 本轮升级里你该记住 |
|------|------------|-------------------|
| kube-apiserver（HA） | 新旧实例 **±1 minor** | 第一台升完 1.37，其余实例允许 1.36/1.37 并存 |
| kubelet | 不得新于 apiserver；可至多老 **3 minor**（kubelet <1.25 时代只允许 2） | apiserver=1.37 → kubelet 可在 1.34~1.37；官方警告：长期落后 3 个 minor 的 kubelet，**升控制面前必须先补** |
| kube-controller-manager / kube-scheduler / cloud-controller-manager | 不得新于 apiserver；可至多老 **1 minor** | 与 apiserver 同批升是常规动作 |
| kube-proxy | 不得新于 apiserver；可至多老 3 minor；与本机 kubelet ±3 | 由 kubeadm upgrade 以 DaemonSet 形态同步拉平 |
| kubectl | apiserver **±1 minor** | 本机 kubectl 比集群老/新一档都在支持区间 |
| kubeadm | kubeadm vs 控制面：同级或 +1；kubeadm vs kubelet：kubelet 同级或至多老 3 minor；kubeadm vs kubeadm：升/连必须同 minor 或比「上次 init/upgrade 的」最多高 1 | 升完后 join 新节点用的 kubeadm 必须 ≥ 上次 init/upgrade 的 minor |
| etcd | kubeadm 源码 v1.37 表：K8s 1.35/1.36/1.37 → **`3.7.1-0`**；external etcd 最小 `3.5.24-0` | etcd 快照 restore 支持同 major.minor、不同 patch |

「**升级顺序**」是官方写死的（顺序错了不保证工作）：

```
① 先升所有 apiserver 实例（HA 下允许 1.36 与 1.37 短暂并存）
② kube-controller-manager / kube-scheduler / cloud-controller-manager（彼此任意顺序、可并行）
③ kubelet（皇家每节点：drain → 升包 → uncordon；不可 in-place minor 升）
④ kube-proxy（DaemonSet，kubeadm 在 apply 阶段同步）
```

官方另外两条「升级前好习惯」：

- **先把当前 minor 升到最新 patch，再升下一个 minor**——最大限度吃到回归修复；
- 自建的 admission webhook 要能 handle 新版 REST 资源和字段（用 `matchPolicy: Equivalent` 注册是最稳的默认姿势，官方从 v1.15 起提供）。

### 4.2 升级序列：首台 CP 用 apply，后续 CP / worker 用 node

生产的 kubeadm upgrade 有明确节奏：**首台 CP 用 `apply`，后续 CP 用 `node`，worker 逐个 `drain → 升包 → uncordon`**。完整命令序列（首台控制面）：

```bash
# ① 换 apt 源 minor 目录（pkgs.k8s.io 按 minor 分目录）+ 解 hold 装新 kubeadm
sudo sed -i 's|core:/stable:/v1.36|core:/stable:/v1.37|' /etc/apt/sources.list.d/kubernetes.list
sudo apt-mark unhold kubeadm
sudo apt-get update && sudo apt-get install -y kubeadm='1.37.x-*'   # x = 当时最新 patch
sudo apt-mark hold kubeadm
kubeadm version -o short

# ② plan：检查集群可升级状态 + 各组件版本表；diff：看清单差
sudo kubeadm upgrade plan
sudo kubeadm upgrade diff v1.37.x

# ③ apply：重写静态清单、升控制面组件（stacked etcd 若同时升 etcd，官方建议先
#    killall -s SIGTERM kube-apiserver && sleep 20 让在飞请求出锅，再 kubeadm upgrade apply）
sudo kubeadm upgrade apply v1.37.x
# 成功标志：[upgrade/successful] SUCCESS! Your cluster was upgraded to "v1.37.x".

# ④ apply 同时会更新 kubeadm-config ConfigMap（后续 CP 的 join/upgrade 基准）
kubectl get cm kubeadm-config -n kube-system -o=jsonpath='{.data.ClusterConfiguration}' | head -2

# ⑤ 本机 kubelet/kubectl：先 drain，再升包，再重启，最后 uncordon
kubectl drain k8s-cp1 --ignore-daemonsets
sudo apt-mark unhold kubelet kubectl
sudo apt-get install -y kubelet='1.37.x-*' kubectl='1.37.x-*'
sudo apt-mark hold kubelet kubectl
sudo systemctl daemon-reload && sudo systemctl restart kubelet
kubectl uncordon k8s-cp1
kubectl get nodes k8s-cp1        # Ready，version 已是 v1.37.x
```

**后续 CP 节点**：与上述同序，只是 ③ 改为 `sudo kubeadm upgrade node`（读 kubeadm-config ConfigMap 刷新静态清单）；不再跑 plan，CNI 也不用管。

**worker 节点（逐台；保证业务副本余量）**：

```bash
sudo kubeadm upgrade node
kubectl drain <worker> --ignore-daemonsets
sudo apt-mark unhold kubelet kubectl
sudo apt-get install -y kubelet='1.37.x-*' kubectl='1.37.x-*'
sudo apt-mark hold kubelet kubectl
sudo systemctl daemon-reload && sudo systemctl restart kubelet
kubectl uncordon <worker>
```

**收尾**：

```bash
kubectl get nodes                                  # 全部 Ready、版本齐
curl -sk https://<controlPlaneEndpoint>:6443/version | jq -r .gitVersion
kubeadm certs check-expiration                     # upgrade 默认同时 auto-renew（除非 --certificate-renewal=false）
```

### 4.3 升级四大坑与预案（生产真实出血点）

| 坑 | 为什么发生 | 预案 |
|----|-----------|------|
| **升级前没备份 etcd** | kubeadm upgrade 只把本机 etcd 拷到 `/etc/kubernetes/tmp/kubeadm-backup-etcd-<ts>`（官方升级页明说），**它不是集群级保护措施**，且官方要求用后手工清 | 升前 `etcdctl snapshot save` + 离机拷贝（§9）；Velero 对象面备份照常；etcd restore 流程提前在 L3 演练过 |
| **CNI/CSI 未对齐新版本** | kubeadm 生命周期里不含 CNI/CSI（§1.1 边界） | 升级当周读 CNI/CSI release notes；按你家的兼容表决定「先 CNI 后 K8s」还是「先 K8s 后 CNI」 |
| **CRD/准入语义变了** | 新 minor 引入新字段/砍掉旧字段；自研 Operator 的 reconcile 会卡 | 升级前 `kubectl get crd` 逐一审；动 storageversion 迁移的组件先升级；CRD **先于**集群升级 |
| **手工塞的 extraArgs 冲掉** | kubeadm upgrade 会**重写** `/etc/kubernetes/manifests/kube-apiserver.yaml` 等——直改清单的 `--feature-gates`/资源/卷挂载会丢 | 所有定制必须进 **ClusterConfiguration.apiServer.extraArgs / extraVolumes**（init 时就写下）；用 `kubeadm upgrade diff` 在升级前把「清单会被改成什么样」打成 review 材料 |

补充三条官方明写的实做细则（升级期间）：

- **所有容器都会被重启**——spec hash 变了（§3.6）；「short-lived/managed-by-none」的一次性容器要在排程前跟业务对齐；
- **kubelet minor 升级不能 in-place**——官方原话「Before performing a minor version kubelet upgrade, drain pods from that node」；
- **upgrade 会自动 renew kubeadm 管的叶证书**（可用 `--certificate-renewal=false` 关）；另有一条**180 天特判**：apiserver 证书距到期不足 180 天会**提前备份重签**（升级页 How it works 节）。

### 4.4 思想实验：HA 控制面升级期间 API 还有吗？

假设 3 台 CP（stacked）+ 一个 LB，升级序按 §4.2 跑：

1. 升 CP1 时，CP1 的清单被拉走，API 出局——**LB 健康探针（应打 `/readyz` 而非 TCP 443）发现 CP1 挂掉，把流量切到 CP2/CP3。业务上 API 一直可用**；
2. etcd 是三 member——CP1 的 etcd 停了后 quorum 仍余 2/3（3 member 可容 1 故障），etcd 层不丢可用性；
3. CP1 回装上 1.37，其它两还在 1.36——官方允许（apiserver HA ±1 minor）；
4. 升级 etcd（stacked）：单个 member 轮流滚，**瞬断受 LB 遮掩**；
5. **唯一可能翻车点**：LB 健康探针打得不够准。如果你的 LB 把「6443 TCP 能通」作为探针而不是 `/readyz`——kubeadm 正在重建 apiserver 时 TCP 可能半通，LB 就把流量踢回正在重建的实例，造成「业务看到 5-20s 的 API 半瘫」。所以 HA 集群生产硬规矩：**LB 探针必须直接打 `/readyz`**（或 apiserver 侧走 `--shutdown-delay-duration` 优雅摘流，见 §6.1）。

HA 的本意就在这：**单机升级产生的不可用秒数，被 LB 遮掉了**——这就是为什么生产永远是 3 个 CP。

---

## 五、证书与轮转（HA 运维重头戏）

### 5.1 四把根 CA + SA 密钥对：kubeadm 生成的证书家谱

kubeadm init 在 `/etc/kubernetes/pki/` 下生成 **3 把 CA 根**（`ca.crt/ca.key`、`etcd/ca.crt/ca.key`、`front-proxy-ca.crt/ca.key`）＋一对 **SA 密钥对**（`sa.key/sa.pub`，ServiceAccount JWT 的 sign/verify 密钥——不是 CA，是给 controller-manager 签 token、给 apiserver 验 token 用）。家谱图：

```
ca.crt/ca.key (CN=kubernetes)
├── apiserver.crt/key                CN=kube-apiserver / O:-     usages=server  SAN=节点/endpoint/k8s svc
├── apiserver-kubelet-client         CN=kube-apiserver-kubelet-client / O=system:masters   usages=client
├── admin.conf                       CN=kubernetes-admin / O=kubeadm:cluster-admins  （绑 cluster-admin；你日常 kubectl 用）
├── super-admin.conf                 CN=kubernetes-super-admin / O=system:masters  （仅 init 节点；break-glass）
├── controller-manager.conf          CN=system:kube-controller-manager / O:-
├── scheduler.conf                   CN=system:kube-scheduler / O:-
└── kubelet.conf（TLS bootstrap 产出）CN=system:node:<nodeName> / O=system:nodes  （CM 一年一签）
etcd/ca.crt/ca.key (CN=etcd)
├── server.crt/key                   CN=<hostname>   usages=server,client（etcd 自检过 client/peer 两用）
├── peer.crt/key                     CN=<hostname>   usages=server,client
├── healthcheck-client.crt/key       CN=kube-etcd-healthcheck-client   （apiserver → etcd 健康探针用）
└── apiserver-etcd-client.crt/key    CN=kube-apiserver-etcd-client     （apiserver → etcd 客户端证）
front-proxy-ca.crt/ca.key (CN=front-proxy)
└── front-proxy-client.crt/key       CN=front-proxy-client  （apiserver → aggregated apiserver，如 metrics-server）
```

**为什么分 3 把 CA**：etcd / 主集群 / front-proxy 的**信任边界独立**——etcd 密钥泄漏的旋转半径不该蔓延到 apiserver 域。SA 密钥对是另一个域：它不是 CA，旋转粒度是「全集群 SA token 全量重签」（§5.4 步骤 4~5）。

逐证书对照表（kubeadm v1.37 生成件；CN/O/SAN 均从源码常量与官方 PKI 页对照核实）：

| 证书 | CN | O | usages | 签发 CA |
|------|----|---|--------|--------|
| `apiserver.crt` | `kube-apiserver` | — | server | ca |
| `apiserver-kubelet-client.crt` | `kube-apiserver-kubelet-client` | `system:masters` | client | ca |
| `apiserver-etcd-client.crt` | `kube-apiserver-etcd-client` | — | client | etcd/ca |
| `etcd/server.crt` | `<hostname>` | — | server, client | etcd/ca |
| `etcd/peer.crt` | `<hostname>` | — | server, client | etcd/ca |
| `etcd/healthcheck-client.crt` | `kube-etcd-healthcheck-client` | — | client | etcd/ca |
| `front-proxy-client.crt` | `front-proxy-client` | — | client | front-proxy-ca |
| `admin.conf` 内嵌证 | `kubernetes-admin` | `kubeadm:cluster-admins` | client | ca |
| `super-admin.conf` 内嵌证 | `kubernetes-super-admin` | `system:masters` | client | ca |
| `controller-manager.conf` | `system:kube-controller-manager` | — | client | ca |
| `scheduler.conf` | `system:kube-scheduler` | — | client | ca |
| `kubelet.conf`（自动签发） | `system:node:<nodeName>` | `system:nodes` | client | ca（CM 签） |
| SA 签发 keypair | — | — | （非 X.509） | — |

> ❗ `system:masters` 是「绕过整个 RBAC 层」的组——只在 break-glass（RBAC 挂死了）场景用。日常运维请用 admin.conf（绑 cluster-admin 的 RBAC 组）。**这两份 .conf 都不要分享**（官方 PKI 页原话「Do not share」。）

### 5.2 check-expiration / renew / 静态 Pod 重启三件套

**发现过期（一年一续的例行功课）**：

```bash
sudo kubeadm certs check-expiration
# 输出结构（官方示例，列名固定）：
# CERTIFICATE                EXPIRES                RESIDUAL TIME  CERT AUTH        EXTERNALLY MANAGED
# admin.conf                 Dec 30 2021 23:36 UTC   364d                            no
# apiserver                  ...                    364d           ca                no
# apiserver-etcd-client      ...                    364d           etcd-ca           no
# etcd-server                ...                    364d           etcd-ca           no
# front-proxy-client         ...                    364d           front-proxy-ca    no
# ...（kubelet.conf 不列：kubelet 走 §5.3 的自动轮转体系）
```

- `EXTERNALLY MANAGED = no` = kubeadm 管；**外部 CA 签发的 kubeadm 默认不处理**（官方：kubeadm cannot manage certificates signed by an external CA）。
- 有效期对照（§1.4 + 源码）：叶证 **1 年**（8760h）/ CA 证 **10 年**（87600h）。
- **upgrade 自动 renew**：`kubeadm upgrade apply/node` 默认 renew 全部叶证（§4.3 说过；`--certificate-renewal=false` 可关）——这解释了「升过级的集群往往顺便把证书也续了」。

**手动 renew（高危动作前自查：有没有 etcd 快照、不在业务高峰）**：

```bash
sudo kubeadm certs renew all             # 或 renew apiserver / apiserver-etcd-client 等单个
# renew 以「旧证书」为准读 CN/O/SAN/usages——不读 kubeadm-config ConfigMap（v1beta4 页原话：
#   "kubeadm certs renew uses the existing certificates as the authoritative source for attributes"）
# 重启四静态 Pod（文件移走-等 20s-移回；kubelet fileCheckFrequency 检测后重启）：
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/ && sleep 20 && sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
sudo mv /etc/kubernetes/manifests/kube-controller-manager.yaml /tmp/ && sleep 20 && sudo mv /tmp/kube-controller-manager.yaml /etc/kubernetes/manifests/
sudo mv /etc/kubernetes/manifests/kube-scheduler.yaml /tmp/ && sleep 20 && sudo mv /tmp/kube-scheduler.yaml /etc/kubernetes/manifests/
sudo mv /etc/kubernetes/manifests/etcd.yaml /tmp/ && sleep 20 && sudo mv /tmp/etcd.yaml /etc/kubernetes/manifests/
# 若 renew 涉及 admin.conf：普通用户 ~/.kube/config 也换
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

> 官方 kubeadm-certs 页明确：「dynamic certificate reload is currently not supported for all components」——renew 不会自动让四大件生效，**重启静态 Pod 是必走的一步**。

### 5.3 kubelet 的 client / serving 证书自轮转（kubeadm 默认给的什么）

kubelet 有两种证书，轮转链完全独立：

| 证书 | kubeadm 默认 | 轮转链 |
|------|------------|--------|
| **client 证书**（kubelet 报 node 状态给 apiserver 的凭据） | `rotateCertificates: true`（kubeadm 写入 kubelet-config ConfigMap；§1.4 样例同） | 临期 kubelet 创建 CSR（signerName `kubernetes.io/kube-apiserver-client-kubelet`）→ CM 内置 **csrapproving controller（默认开，官方 TLS bootstrap 页）** 走 SubjectAccessReview 批准 `system:certificates.k8s.io:certificatesigningrequests:selfnodeclient` → 自动签发 1 年新证 |
| **serving 证书**（kubelet 10250 的 HTTPS 面；metrics-server/exec/logs 都走这里） | **默认自签**（不是 CA 链背书——`x509: certificate signed by unknown authority` 刷屏之源） | 需 `serverTLSBootstrap: true`（KubeletConfiguration）+ `RotateKubeletServerCertificate`（**v1.37 Beta，默认开**，release-1.37 源码 `kube_features.go`）→ kubelet 创建 CSR `signerName: kubernetes.io/kubelet-serving`——**内置 approver 出于安全原因不批准这一类**（官方 TLS bootstrap 页原话）→ 必须人工 `kubectl certificate approve` 或部署第三方 approver（如 `kubelet-csr-approver`；发货规则：CN=`system:node:<nodeName>` + SAN 只有本机 IP/DNS） |

三句话复查你的集群现状：

```bash
# ① client 轮转开关（应为 true）
kubectl get cm kubelet-config -n kube-system -o=jsonpath='{.data.kubelet}' | grep -E 'rotateCertificates|serverTLSBootstrap'

# ② pending 的 CSR（serverTLSBootstrap 开过的话会有 serving 类在等待）
kubectl get csr

# ③ kubelet serving 证书当前是什么签发级（实验 7.3 用 openssl s_client 实探）
openssl s_client -connect 127.0.0.1:10250 </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates
```

> ❗ 生产推广 `serverTLSBootstrap: true` 之前，先想好「**谁来 approve serving CSR**」——没配 approver 的集群，serving 首次轮转时 CSR 会卡 Pending，metrics-server/`kubectl logs` 那一线全部断。「开 + 配套 approver」是唯一的整包推。

### 5.4 CA 根换新（manual-rotation-of-ca-certificates 完整步骤）

什么时候必须换根 CA？两类触发：

- **泄漏**：`ca.key` 出现在不该出现的地方（误传 CI、误发他人、备份目录未加密）；
- **合规**：内审/外审强制的轮换周期（如「每 5 年换一次」）；kubeadm 默认 CA 寿命 10 年，平常不必动它。

> ❗ **官方前置假设（manual-rotation 页原话）**：以下流程假定为 **HA 集群、多 apiserver，且 apiserver 可优雅停机**；**单 apiserver 集群执行时 API 会有不可用窗口**（实验环境也一样，接受再做）。

**完整步骤表（顺序不可乱；「bundle」= 旧 CA + 新 CA 并列同一文件）**：

| # | 动作 | 说明 |
|---|------|------|
| 1 | **备份** `/etc/kubernetes/pki` 与所有 kubeconfig | `sudo cp -r /etc/kubernetes/pki /etc/kubernetes/pki.bak.$(date +%s)`，并离机拷贝 |
| 2 | 生成**新 CA**（`ca-new.crt/key`、`front-proxy-ca-new.crt/key`） | 用 openssl/cfssl；先在测试环境完整走一遍 |
| 3 | 新 CA 的**公开文件分发到所有 CP** 的 `pki` 目录 | 新旧并存（先不合 bundle） |
| 4 | 改 controller-manager：`--root-ca-file` = **旧+新 CA bundle**，重启 CM | 此后新签 SA token 同时携带两 CA |
| 4⚠️ | 已知坑：`pki/ca.crt` 变 bundle 后，CM 的 `--client-ca-file`、`--cluster-signing-cert-file` **不允许是 bundle**（官方列 kubeadm issue 1350） | 把新 CA 拷成 `ca-new.crt` 单独指给这两个 flag；旧 CA 清完再改回指原文件 |
| 5 | 等 CM 把 bundle 写进**所有 SA 的 token Secret**（字段 `ca.crt`） | `kubectl get secrets -A` 抽查几份含 token 的 Secret |
| 6 | **重启所有用 in-cluster 配置的 Pod**（kube-proxy、CoreDNS、自研 Operator——让它们重读 SA token 拿 bundle） | `kubectl delete pod -n kube-system -l k8s-app=kube-dns` 等逐个滚；聚合层 apiserver/webhook 也在此列 |
| 7 | apiserver：`--client-ca-file` 与 `--kubelet-certificate-authority` 改 bundle；scheduler：`--client-ca-file` 改 bundle；一并重启（用 §5.2 清单移走-移回法） | apiserver 认证层与 kubelet 调用层同时认两 CA |
| 8 | 用户 kubeconfig 的 `certificate-authority-data` 改嵌 bundle；需要换证的由 `kubeadm kubeconfig user` 重签（super-admin 仅 break-glass 用） | 日常管理员的 admin.conf 也要滚 |
| 9 | （无则跳过）cloud-controller-manager 的 `--root-ca-file` 同步 bundle 并重启 | 外网版本同样适用 |
| 10 | **各节点**：kubelet 的 `clientCAFile` + `kubelet.conf` 的 `certificate-authority-data` 改 bundle；**重启 kubelet**；apiserver 用新 CA 重签自身证书（apiserver/apiserver-kubelet-client/front-proxy-client 三件，私钥可复用）并重启；scheduler 一并重启信任新 CA | 生产上按 CP 滚动，用 LB 摘流；`watch -n1 kubectl get nodes` 盯 |
| 11 | **确认运行后撤旧 CA**：全 Pod roll 一遍（确保 Pod 内 SA 只剩新 CA）；撤组件 `--client-ca-file/--root-ca-file` 里的旧 CA；bootstrap token 的 `cluster-info` ConfigMap 换成新 CA base64： | 官方给的替换命令：`base64_encoded_ca="$(base64 -w0 /etc/kubernetes/pki/ca.crt)"`；`kubectl get cm/cluster-info -n kube-public -o yaml \| sed "s/\(certificate-authority-data:\).*/\1 ${base64_encoded_ca}/" \| kubectl apply -f -` |

经验法则（什么时候、多久一次）：

- **1 年叶证 + 10 年 CA 的组合下，CA 互换不属常态动作**——只在「泄漏 / 合规 / 算法更换（RSA-2048 → ECDSA-P384）」时触发；年叶证由 `kubeadm upgrade` 或 `certs renew` 续，与 CA rotation 无干。
- **一次完整 CA rotation 的时间窗**（3 CP + ≤100 节点、无工程化自动化时）：约 **2~4 小时/人** + 1 小时全 rollout 观察；把它当**季度级深度演练**事件，这是实验 L3 证书破坏场的深层缘由。
- 官方临别提醒（manual-rotation 页最后一段）：「If your cluster lets you make this change, you can also roll it out by replacing nodes rather than reconfiguring them」——能用 IaC/MachineSet 换节点，**整节点替换远比 per-node 改文件优雅**。

### 5.5 encryption key 轮换（直接引用不重写)

加密面（EncryptionConfiguration + KMS）的密钥轮换是另一类炸弹：改 key 后必须把所有存量 Secret **重写一遍**才完全拿到新 key 的保护。第 5 章 §5.2 已把整段（新 key 进尾→调首→rewrite 全部→撤旧、auto-reload flag）讲透——这里只给轮换的出口命令做指针：`kubectl get secrets -A -o json | kubectl replace -f -`，不重写。

---

## 六、控制面调优与大集群设计约束

### 6.1 kube-apiserver 关键 flag 与指标（v1.37 官方 command-line-reference 核实）

| flag（v1.37 默认；已对照官方页） | 干什么 | 生产什么时候动 |
|---------------------------------|--------|----------------|
| `--max-requests-inflight=400`<br>`--max-mutating-requests-inflight=200` | 关 APF 时的两闸；**APF 开（v1.29 起 GA 默认开）时两值相加=600 总 nominal concurrency** | 一般不动；单实例并发不够优先「加 CP 实例」而不是调数字 |
| `--watch-cache=true` | 默认开，watch 扇出全靠它吃 etcd | 别关；finer 走 `--watch-cache-sizes`（v1.37 语义已简化到「0 = 关该资源的缓存」） |
| `--etcd-compaction-interval=5m0s` | apiserver 周期性发起 etcd compaction——**第 1 章「历史窗口 ≈ 5 分钟」的出处** | 一般不动 |
| `--min-request-timeout=1800` | watch handler 的最小连接下限（在此之上随机抖动错开重连风暴） | 一般不动；watch 风暴先查客户端行为 |
| `--goaway-chance`（min 0 / max 0.02，官方建议 0.001 起步） | 多 apiserver + LB 时**随机发 GOAWAY 让 HTTP/2 客户端重连分摊** | HA + LB 强烈推荐；单机/无 LB 别开（官方原话：should NOT enable） |
| `--shutdown-delay-duration` | 优雅停机牵引窗：`/readyz` 立刻失败但继续服请求 | HA 里 apiserver 滚动升级前让 LB 先摘（§4.4 联合使用） |
| `--storage-media-type=application/vnd.kubernetes.protobuf` | v1.37 的默认——对象以 protobuf 存进 etcd | 不用动；但 `etcdctl get` 直接 dump 到的 **不再是人-readable JSON**，排障时要意识到 |
| `--feature-gates=EtcdRangeStream=true`（**v1.37 起 Beta 默认开**） | apiserver→etcd 的大集合读取改 streamed——两侧内存峰值降；需 etcd ≥3.7 | 看板/告警补 `operation="listStream"`，不然 list 指标会漏这块 |
| `--min-compatibility-version=kube=1.34..1.37`（默认 1.36） | 混版期间的兼容水位线 | 升级期间自动带入，无需干预 |

**apiserver 生产指标本体**（「监控/」目录已有 Prometheus 部署篇，这里只看指标与阈值；阈值是经验值，非官方）：

| 指标 | 看什么 | 告警阈值建议 |
|------|--------|-------------|
| `apiserver_request_duration_seconds{verb,resource}` | P99 时延按 verb 分层（list/watch/mutate） | P99 > 2s 且持续 5min：下一步看 etcd |
| `apiserver_flowcontrol_rejected_requests_total{reason}` | APF 按 priority level/reason 拒绝分布（第 1 章 §5） | `reason=queue_limit` 或 `time_exceeded` 连续上涨：优先度反抢或容量不足 |
| `etcd_request_duration_seconds{operation}` | etcd 慢的传导链（与上条联动；注意 `listStream`，§6.1 说明） | P99 > 500ms 连续 5min：etcd 慢 |
| `apiserver_current_inflight_requests{request_kind}` | 两闸/APF 水位（总 600 nominal） | > 80% 持续 10min：查突变流量来源 |
| `apiserver_watch_events_total` / `apiserver_watch_events_sizes` | watch 事件的量与大小分布 | 平均事件体积出现异常尖峰：查是否有巨型 CRD/大对象在 fanout |

### 6.2 controller-manager / scheduler / kube-proxy 的并发与 QPS（v1.37 默认总表）

**kube-controller-manager**（默认值已核实 v1.37 command-line-reference；「经验值」列非官方）：

| flag | 默认 | 大集群经验值 |
|------|------|-------------|
| `--kube-api-qps` / `--kube-api-burst` | **20 / 30** | 大集群起点 **50/100**；超大上探 100/200 |
| `--concurrent-deployment-syncs` / `--concurrent-replicaset-syncs` | **5 / 5** | 5~10（deployment/rs 是日常热面） |
| `--concurrent-gc-syncs` | **20** | 40~50（ownerReference GC 在「级联删作业」场景是敏感项） |
| `--concurrent-namespace-syncs` | **10** | 10（namespace 删除慢通常不是这个闸的问题） |
| `--concurrent-endpoint-syncs`（Endpoints 面） | **5** | 大集群 endpoint 热 10~20 |
| `--concurrent-cron-job-syncs` | **5** | 5~10 |
| node-lifecycle | `--node-monitor-grace-period=50s` / `--node-monitor-period=5s` | 对「node 失联多久判 NotReady」强相关（kubelet lease 40s）；大网络抖动环境才有动它的理由 |
| CSR 签发时长 | `--cluster-signing-duration=8760h0m0s` | 与 §5.2 证书一年一续周期天然耦合 |

**kube-scheduler**（v1.37 默认）：

| flag/配置 | 默认 | 大集群经验值 |
|-----------|------|-------------|
| `--kube-api-qps` / `--kube-api-burst`（flag 已 DEPRECATED，正式应写进 KubeSchedulerConfiguration） | **50 / 100** | 大集群 100/200（瓶颈常出在节点/Pod 状态上行而不是调度算法本身） |
| leader election | `--leader-elect-lease-duration=15s` / `renew=10s` / `retry=2s` | 不动（与 CM 同内核） |
| 指标面 | 第 2 章 §7 已写主指标表 | **告警阈值建议**：`scheduler_pending_pods{queue="active"}` ≥100 持续 5min；`scheduler_pod_scheduling_sli_duration_seconds` P99 >60s；`scheduler_schedule_attempts_total{result="error"}` >1/min 持续 5min |

**kube-proxy**（v1.37 默认）：

| flag/配置 | 默认 | 生产调优点 |
|-----------|------|-----------|
| `--kube-api-qps` / `--kube-api-burst` | **5 / 10** | Service/Endpoint 密集集群调到 50/100 |
| `--iptables-sync-period` / `--iptables-min-sync-period` | **30s / 1s** | Service 密集集群看 `kubeproxy_sync_proxy_rules_duration_seconds` 再动 |
| `--proxy-mode`（Linux） | `iptables`（可选 ipvs/nftables） | 第 3 章已选 Cilium——kube-proxy 走了就被它替换 |
| healthz / metrics | `0.0.0.0:10256` / `127.0.0.1:10249` | LB 健康探针直接打 10256；metrics 要外收需改 bind |

> ❗ QPS/Burst 生效链：QPS 定「长期平均访问速率」，burst 定「短时尖峰额度」；APF 给各 client 分配 nominal share 是有限的（系统组件多为 `exempt`/高泳道，但泳道再宽不是无限——第 1 章 §5）。调优反馈环：**QPS 过低 → controller/CM 处理状态更新排队 → 觉得「集群反应慢」；QPS 过高 → apiserver 超水位 429 → 仍觉得慢**。先测后调，别拍脑袋。

### 6.3 etcd 侧：quota、defrag、数据量经验值（apiserver→etcd 协同面；etcdctl 运维细节不重讲）

- **后端 quota 默认 2 GiB**（`--quota-backend-bytes`，K8s-etcd详解.md 已讲）。K8s 官方「operating etcd clusters」页推荐**静态 5-member、生产任何官方支持规模够用，并明确不要自动扩缩 etcd**（扩缩触发重新选举、扰动 Raft quorum）——quota 不够时，**官方给大集群的标准动作是把 Event 对象拆到独立的 etcd 实例**（large cluster 页原话），而不是单调 quota。
- **何时该动 quota**：`etcdctl endpoint status` 看 DB SIZE + ALARM 列——对 K8s 来说真正的大头是 `/registry/events/`；NOSPACE 处置链（compact + defrag + disarm）已写在 `K8s-etcd详解.md` §5.4，不重讲。
- **defrag 周期主张**：官方原话「as infrequently as possible」——推荐用 **`etcd-defrag` 类工具以 CronJob 定期执行**（官方 configure-upgrade-etcd 页点名），别作为人肉 cron。
- **对象体积经验值**（非官方，作量级估算用）：一个带完整 ownerRef/status 的 K8s 对象平均 **1.5~2.5 KiB**——5 万对象（3 节点小集群 + addon，不含 event）约 **100~150 Mi**；50 万+对象的大集群叠加起来才是 GB 级。和 `etcd-compaction-interval=5m`（§6.1）协同读：**每 5 分钟一次的旧版压缩解决的是「历史副本堆积」，当前版本体积才是常驻内存/磁盘的主体**。
- **官方限值提醒**：K8s 官方建议生产最低 etcd 版本 **3.4.29+ / 3.5.11+**（configure-upgrade-etcd 页）；升 etcd 也一样先备份。

### 6.4 kubelet 生产关键配置（默认值已核实 kubelet-config.v1beta1 页 + node-pressure-eviction 页）

| 配置 | 默认 | 生产什么时候动 |
|------|------|----------------|
| `maxPods` | **110** | 大节点（如 16C/32G+）上常见调大；110 的原始语境是「大集群官方支持的每节点上限」（§6.5），而不是性能结论——动它要同时想清楚 CNI IPAM 的 node CIDR、conntrack、kubelet status sync 体积 |
| `podsPerCore` | 0（不限制） | 小核多 pod 爆炸场景再加 |
| `imageGCHighThresholdPercent` / `imageGCLowThresholdPercent` | **85 / 80** | 磁盘压力场景；用 `kubelet_image_gc_duration_seconds` 等指标验证有效性 |
| `containerLogMaxSize` / `containerLogMaxFiles` | **10Mi / 5**（即每容器最多 50Mi 日志） | 日志洪峰容器（跑 DEBUG 的应用）瞬间填满，靠日志集中（Fluent-bit/Loki）顶上——别把这两个数当作撑住「全量日志永远可读」的解法 |
| `serializeImagePulls` / `maxParallelImagePulls` | true / nil | 大集群/巨型镜像考虑 `maxParallelImagePulls`；同时要知道 `registryPullQPS=5` / `registryBurst=10` 这两个闸的存在 |
| `evictionHard` 默认表 | **memory.available<100Mi（Linux）/ 500Mi（Windows）**、**nodefs.available<10%**、**imagefs.available<15%**、**nodefs.inodesFree<5%**、**imagefs.inodesFree<5%（Linux）** | 自定义任一阈值后必须连设 **`mergeDefaultEvictionSettings: true`**（否则其它默认一律清零——这是「为什么自定义后 eviction 反而不见动作」的第一嫌疑）；kubelet 配置 v1beta1 页的跨平台默认值列其中 4 条，官方 node-pressure-eviction 页给出全 5 条（含 Linux/Windows 分列） |
| `evictionPressureTransitionPeriod` | **5m** | 防震荡窗；配合 `kubectl describe node` 看 condition 抖动 |
| eviction 选 Pod 顺序 | 按「**usage 是否超 requests** → **Priority** → **同级内 usage/requests 比**」排序 | 官方原话「kubelet does not use the pod's QoS class to determine the eviction order」——QoS 只是估算排序的近似量；**这是生产 MemoryPressure 驱逐误解的第一层**（实验 7.4 实测） |
| kubelet OOM 保护（oom_score_adj） | Guaranteed=-997 / Burstable=公式 / BestEffort=1000 / `system-node-critical` 的 Pod 也 -997 | 系统关键 Pod 被 oom_killer 杀的事故大类；PriorityClass 数值见第 2 章 §6.2 |
| `cgroupDriver`（kubelet 侧） | `cgroupfs`（kubeadm 派写 `systemd`；v1.37 起 `KubeletCgroupDriverFromCRI` Beta 默认开可自动探测 CRI） | 必须同 containerd 一致——§2.3 灾难案例 |
| 超大页内存 | `HugepageAwareEviction`（v1.37 **Beta 默认开**） | Node 上有 hugepages 时内存统计更准；之前版本曾因此漏判 OOM |

**imagefs 与 rootfs 未分离的经典事故**（kubelet 把三者当同盘看）：

- 链条：容器镜像持续膨胀 → `imagefs.available` 掉过 15% → kubelet 按顺序清无用的容器与镜像（官方：先 GC 死掉的 Pod/容器，再删 unused images）→ **新 Pod 被拖进磁盘风暴后仍拉不动镜像**（nodefs.available 已见底）→ `DiskPressure=True` + eviction 发生 → kubelet 连环驱逐；
- **生产简规**：worker 至少把 `/var/lib/containerd` 独立挂一块盘（50~100GB 专用 volume）；官方 node-pressure-eviction 页明确写了三种文件系统布局（rootfs 一体化 / imagefs 分盘 / imagefs+containerfs 再分盘），**v1.37 `KubeletSeparateDiskGC` Beta 默认开**，大集群分盘已是事实标配。

### 6.5 大集群设计约束：官方数字 + 「这些数是怎么来的」

官方 large cluster document（v1.37 原样断言）：

```
   Kubernetes v1.37 supports clusters with up to 5,000 nodes.
   More specifically, all of the following must hold:
     • No more than 110 pods per node
     • No more than 5,000 nodes
     • No more than 150,000 total pods
     • No more than 300,000 total containers
```

**这四个数字背后的物理约束——怎么推出来的**（以下为机制反推，官方页未逐点解释；标注为经验推导）：

1. **etcd 写速 × watch 扇出**：Pods 的生命事件（创建/绑定/status 更新）每起一次就是一笔 etcd 写 + N 个 watcher 的扇出分发——真正的限幅不是「150000 个 Pod」，而是「这些 Pod 的**变更率**落在 etcd 与 apiserver 的预算内」。
2. **apiserver 内存 ≈ ∑ watch 对象 × 1.5~2.5 KiB**：150000 Pod ≈ 0.2~0.4 GB，但 apiserver 还要缓存 Nodes/Deployments/EndpointSlice 等（EndpointSlice 上限约 Pod 的 1.2 倍——默认每 slice 100 个 endpoint，CM flag `--max-endpoints-per-slice=100`）——**这就是多副本 apiserver 不线性 scale 的本来缘由**。
3. **每节点 110 pods**：kubelet status sync 体积 + cAdvisor 采集成本 + kube-proxy 规则链长度共同卡定的「官方支持套餐」，不是性能最优设置。
4. **300000 containers ≈ Pod × 2**（每 Pod 至少 1 个 pause + 1 个业务容器）——把「Pod 数」换算成 kubelet/CRI 真正驱动的工作单位（起停、probe、stats）。

超过这张表的两条路：**events 拆独立 etcd（§6.3）** 与 **多集群**（总纲第 10 章 Karmada/Fleet 领域，不在本章）。

---

## 七、节点自运维生态：NPD + draino + 自愈节奏

### 7.1 node-problem-detector（NPD）：把「节点的病」变成 NodeCondition/Event

官方定义（monitor-node-health 页）：「a daemon for monitoring and reporting about a node's health……reports these conditions to the API server as Node Conditions or as Events」。四种 problem daemon（官方分类）：

| daemon | 抓什么 | 典型产出 |
|--------|--------|---------|
| **SystemLogMonitor** | 系统日志（filelog/kmsg/kernel/abrt/systemd 五种来源） | 内核 OOPS、ext4 error、KernelDeadlock、ReadonlyFilesystem |
| **SystemStatsMonitor** | 各类系统健康统计（load/mem/fd/disk/cpu） | 节点级 Prometheus 指标 |
| **CustomPluginMonitor** | 你自己写的探件脚本（exit code + stdout 协议） | 「某挂载点权限异常」「时偏 >5s」这类你定制的 |
| **HealthChecker** | kubelet 与 container runtime 健康 | KubeletReady / ContainerRuntimeReady 异常 |

exporter（condition/event 干什么）：K8s exporter（**临时问题报 Event、永久问题报 NodeCondition**——官方措辞）、Prometheus exporter、Stackdriver exporter。

最小落地：

```bash
# ① 官方一键（文档自带 manifest；先看它能干什么）
kubectl apply -f https://k8s.io/examples/debug/node-problem-detector.yaml

# ② Helm 化（deliveryhero repo 的 chart；artifacthub 收录「node-problem-detector 2.4.1」（写本文时））
helm repo add deliveryhero https://charts.deliveryhero.io/ && helm repo update
helm install npd deliveryhero/node-problem-detector -n kube-system
kubectl -n kube-system get pods -l app.kubernetes.io/name=node-problem-detector
```

> ❗ NPD 本身不 drain、不重启 kubelet——它是**感知层**。把「感知」接到「行动」，需要下一节的 draino（或你自己的反操作循环）。

### 7.2 draino：NodeCondition → cordon + drain 的自动化

draino 是 Cloudflare 开源的「节点 drain 自动化器」。**可用性预警（写本文时记）**：原仓 `github.com/cloudflare/draino` 当前 **404**，存在多份活跃 fork（`planetlabs/draino` 等）；落地前**核实活跃 fork 与上游归属**——但它的核心语义简单固定，因仓库归属变化不影响你学其机制。

draino 语义（社区 fork 的共同形态）：

| 阶段 | 做什么 |
|------|--------|
| 观察 | watch Node Condition（如 NPD 上报的 `KernelDeadlock=True`）命中预定义清单 |
| 决策 | 给 node 打 draino 状态 label（可用作 PDB/自动化的判定锚） |
| 行动 | `cordon` + `drain`（**遵守 PDB**：走 eviction API 的 PDB 语义，PDB 不放行就持续等待） |
| 安全 | leader election（多副本只一台在动）、`dry-run` 观察模式、按 label 过滤动/不动 |

**NPD + draino 标准联动**（感知 → 行动 → 替换）：

```
   节点内核/磁盘/网络出问题
              │
   NPD（DaemonSet，日志/健康探件）
     SystemLogMonitor / HealthChecker 捕获
              │
     上报 K8s：NodeCondition（+ Event）
              │
   draino（Deployment；leader + dry-run 先起步）
     命中 condition → label node → cordon + drain（遵守 PDB）
              │
   Pod 被 workload controller 重投到新节点（第 2 章调度）
              │
   节点替换：云 API 重建 / IaC 换 VM / 裸机报修（kubeadm：reset + rejoin，§3.7）
```

### 7.3 自愈节奏建议（经验纪律）

「看到 condition 立刻 drain」往往会把小问题放大（正好业务高峰、正好在滚动发布窗口）。生产推荐**缓冲型节奏**：

| 阶段 | 建议时间窗 | 动作 |
|------|-----------|------|
| 观察 | 5 分钟 | 只 cordon 与告警（NPD 指标/ Event 先到 PagerDuty）；draino 先打 dry-run；`kubectl describe node` 看 Condition 历史是否反复 |
| 决策 | 再 5 分钟 | condition 持续 → 转 draino 真干；自然消失 → 复盘（经常能捡到线索：磁盘限额先撑后舍、内核临时 OOPS 类） |
| drain | 一次一台 / 一次一个 zone | `kubectl drain --ignore-daemonsets --delete-emptydir-data`，尊重 PDB（§7.2） |
| 修复/替换 | 平均节拍 ~15 分钟/台 | 云主机：API 重建；裸机：报修；kubeadm 手动扩容：`kubeadm reset`（§3.7）+ `kubeadm join`（§3.3） |

> ❗ 自愈不是「见 condition 就弹」——**哪些 condition 直接联动 draino、哪些只会告警**，要写成显式矩阵（如 `ReadonlyFilesystem`/`KernelDeadlock` 直塞 draino、`MetricsServerDown`/`PrometheusDown` 只告警）。**尤其控制面节点绝不允许自动 drain**——draino label 过滤里把 control-plane 显式排除（§3.1 的故障耦合逻辑：丢一台 CP 对 etcd quorum 的影响）。

---

## 八、租户治理生产配置（PriorityClass / NetworkPolicy / PSA 引用第 2、3、5 章）

### 8.1 ResourceQuota：namespace 边界的总量天花板

ResourceQuota 是 admission 阶段的总量围栏——「算力 + 存储 + 对象数量 + scope 过滤」四类面板都能绑。生产长相示例：

```yaml
apiVersion: v1
kind: ResourceQuota
metadata: { name: prod-quota, namespace: prod-team-a }
spec:
  hard:
    requests.cpu: "40"
    requests.memory: "64Gi"
    limits.cpu: "80"
    limits.memory: "128Gi"
    persistentvolumeclaims: "20"
    requests.storage: "2Ti"
    gold.storageclass.storage.k8s.io/requests.storage: "500Gi"
    count/pods: "200"
    count/services: "20"
    count/secrets: "100"
    count/configmaps: "100"
    count/deployments.apps: "30"
    services.loadbalancers: "2"
    services.nodeports: "5"
  scopeSelector:                     # 只对 scope 匹配的 Pod 计入
    matchExpressions:
      - scopeName: PriorityClass
        operator: NotIn
        values: ["system-cluster-critical", "system-node-critical"]
```

**生产要点**：

- **requests 与 limits 成对配**——只写 `limits.cpu` 会导致「无 request 的 Pod 的 request 被 LimitRange 默认填成 limit 值」，配额立刻被装成「它surface 等于它实际上限」；两者都写才是「请求额与上限分层管理」。
- **`scopeSelector` 把系统 Pod 从团队配额里摘出去**——否则某天 DaemonSet 加个 agent 会让整个 namespace 建不出新业务 Pod（生产高频事故款）。
- **配额违例是 admission 时直接 403 Forbidden**，不是 Pending spinlock——告警链直接打 API 错误量，别只盯 Pending。
- 同 ns 多份 quota 并存时**取交集**（每类资源按最严的那份计）。

### 8.2 LimitRange：单 Pod / 容器级的默认与上下界

LimitRange 是 admission 阶段的「单容器函数」：

```yaml
apiVersion: v1
kind: LimitRange
metadata: { name: prod-limits, namespace: prod-team-a }
spec:
  limits:
    - type: Container
      default:                        # 没写 spec.resources.limits 的容器认领（limit）
        cpu: "1"
        memory: "1Gi"
      defaultRequest:                 # 没写 spec.resources.requests 的容器认领（request）
        cpu: "200m"
        memory: "256Mi"
      min: { memory: "128Mi" }
      max: { cpu: "4", memory: "8Gi" }
      maxLimitRequestRatio:
        cpu: "4"                      # limit/request 比值上限 = 4（超售节制闸）
    - type: Pod
      max: { cpu: "8", memory: "16Gi" }
    - type: PersistentVolumeClaim
      min: { storage: "1Gi" }
      max: { storage: "500Gi" }
```

**为什么这么设计**：

- `defaultRequest` 与 `default` **成对**——防止「裸 Pod 没 resources」被 quota 以默认 limit 填进来就能把配额撑满（请求额会被默认推成 limit 值等于事实上默认了 request=limit 的假象）；
- `maxLimitRequestRatio` 是**超售反制**——不做这个闸的话，request=100m + limit=100 的 Pod 可以直接「表面占一点，实际顶半天」；加上它，「我能 promise 多少」与「我可能抢多少」之间的比率被硬约束；
- 多份 LimitRange 并存，**每份都对目标资源实例生效**——不是因为「挑了一个」，而是每一个容器都要过**所有**相关声明才算挂牌。

### 8.3 requests / limits 生产纪律表（为什么 CPU limit 有争议）

| 纪律 | 边界 | 直接用一次就能听懂的事故模型 |
|------|------|------------------------------|
| **memory request == memory limit** | 内存 limit 对应的 cgroup 上限越过即 OOMKill；request=limit 才能进 Guaranteed 级（§6.4：oom_score_adj=-997，eviction 序列靠后） | limit > request 的 Burstable Pod 在节点内存压力时**优先**进 evict 候选 |
| **CPU 只配 request 不配 limit** | CPU limit 走 CFS throttle——**只在「超售必须硬封顶」的场景下写**；request 决定调度权重（cpu shares），limit 会造成延迟尖峰（burst 阶段超 quota 即断） | CPU limit=4 + 高峰期 Java GC/Go STW 折线超过 4 core·100ms → `container_cpu_cfs_throttled_periods_total` 冲上去 + P99 延迟放大 |
| **裸 Pod 不许上生产**（requests 必填纪律） | LimitRange 的 defaultRequest 救急；quota 必校验 requests | 业务没写 request → 调度器与 quota 的口径全面失真 → 节点「表面还能塞，实际早撑死」 |
| **高价值 Pod 用 PriorityClass**（第 2 章 §6） | 集群自带 `system-cluster-critical=2000000000`、`system-node-critical=2000001000` 两个保留级 | 业务 Pod 与 CoreDNS/metrics-agent 同 default Priority → 节点压力来时，基础设施与业务同顺位被 evict |

> ❗ **CPU limit 争议一句话**：CPU 是可压缩（compressible）资源——超发在统计学上有效；写死 limit 就把「统计收益」换成了「确定性节流」。生产的常见组合是「**memory 照写 limit（必写）＋CPU 只在强多租户隔离场景写 limit**」，同时**必须有 `container_cpu_cfs_throttled_periods_total` 的告警**——你不写 limit 不代表 burst 被偷光，而是显式采用「靠 statistics + Priority 的预算治理」。

### 8.4 配套基线（引用不重讲）

- **PriorityClass** 生态与 preemption 细节引用第 2 章 §6.2（`preemptionPolicy: Never` 适合不想抢占别人但想插队的批任务）
- **NetworkPolicy 基线**（default-deny + 白名单放行）引用第 3 章 NetworkPolicy 节；Cilium 体系的 `CiliumNetworkPolicy` 差序已在该章覆盖
- **PSA**（`pod-security.kubernetes.io/enforce: restricted`）引用第 5 章 §1~§2——系统命名空间用 label 豁免（第 5 章讲了 exemptions 三类）

---

## 九、灾备与恢复编排（备份铁三角 → L3 演练计划）

### 9.1 备份铁三角（etcd 与 Velero 篇已详解，这里只给动作与频率）

| 面 | 负责什么 | 最小频率建议 |
|----|---------|-------------|
| **etcd 快照** | 控制面真源；单文件带回整个集群 state | **每小时**（CronJob）＋ 每次升级前手动一份 |
| **基建层（IaC）** | 网络/安全组/LB/证书签发/VM 拓扑——「我能重新画出这台机器」 | 每次变更都走 IaC（Terraform/Ansible）并留存 apply 产物 |
| **Velero** | 对象面 + PV 快照 | **每日** ＋ 升级前增量；备份位置与集群故障域分离（详 `Velero-Kubernetes备份恢复与迁移指南.md`） |

> ❗ 三者不可替代关系：**etcd 快照恢复不了 PV 里的业务数据**（那是数据盘的事）；**Velero 恢复不了「你的 etcd 被格式化」**（要先 restore 快照，再 Velero restore 对象）；**IaC 不能恢复数据**。混在一起代替，等于在某一类事故里裸奔。

### 9.2 恢复优先级表（灾难时刻按序逐个上来）

```
P0（根） → 控制面静态清单（/etc/kubernetes/manifests）+ pki 目录在场
             └── 没有它们 apiserver 起不来 → 一切都是白做
P1        → etcd 数据（stacked 在 /var/lib/etcd；用 etcdctl snapshot restore 从快照恢复）
             └── 恢复前必须先停所有 apiserver（官方 configure-upgrade-etcd 页原话）
P2        → apiserver / scheduler / controller-manager 起来 + 证书有效
             └── （整机重建路径：IaC 起 VM → kubeadm init/join 重建静态清单 → §P1 恢复数据）
P3        → RBAC / webhook（聚合层 apiserver、PSA、自建 validating/mutating）
             └── 它们挂了：apiserver 能起、但所有写请求被 500/403 拒——查的头一个子域
P4        → CNI / CoreDNS / kube-proxy / CSI（数据面与末梢平面）
             └── CoreDNS Running 是「集群可操作」的标志（create-cluster 页验证步）
P5        → 业务（按 PriorityClass 从高到低恢复）
```

### 9.3 「node down 5 分钟自愈」检查表

| 检查项 | 对 5 分钟窗口的意义 | 落地规则 |
|--------|--------------------|---------|
| **控制器/PDB 完整** | 漂移速度取决于「控制器多快能抱出新副本」 | 关键业务 PDB：`minAvailable`≥1 或 `maxUnavailable`=25% 对应 |
| **节点标签/拓扑可行** | scheduler 得有替代落点 | `topology.kubernetes.io/zone` 规划好；nodeSelector 别绑死在一台 |
| **镜像 registry 冗余** | 新节点拉镜像不能卡在源站 | registry 高可用/镜像预热；日常别在无备用下手工清节点 image cache |
| **存储可漂** | PV 能不能跟着 Pod 飘到新节点 | RWO 云盘漂要熬 6 分钟 attach 时间窗；要么 RWX/NFS，要么接受 replacement 节奏 |
| **NPD→draino 链路（§7 闭合）** | node condition 到 cordon 自动打通 | 新集群先让 draino 跑 dry-run 观察期，验证了再切实战 label |

### 9.4 整机恢复演练计划（实验 L3 主体）

《总纲》规定的 7 个破坏场景，逐个演练并各写一篇 runbook（归档进第 8 章 `K8s-故障排查方法论.md`）：

| # | 破坏脚本一句话 | 破损后的信号 | 恢复动作（导引） |
|---|---------------|-------------|-----------------|
| 1 | 删 etcd 数据目录（单 CP 才演） | apiserver crashloop，`kubectl get` 全部 etcd timeout | 停 apiserver → 最新快照 restore → 起 apiserver（§9.2 P1） |
| 2 | 换一张错误 CA 签的 apiserver.crt | `x509: certificate signed by unknown authority` | `kubeadm certs renew apiserver` + 静态 Pod 重启（§5.2） |
| 3 | 反复杀 Cilium DaemonSet Pod | Node NotReady、业务 Pending 大涨 | 先 `systemctl restart kubelet`、后重启 Cilium  operator，不行则删出重建（§3.4） |
| 4 | `kill -STOP` 挂起 kubelet | 约 40s（node lease）后 NotReady、随后 node-lifecycle taint 生效 | `systemctl restart kubelet`；校正 §6.2 里 40s lease 与 50s grace period 的关系 |
| 5 | `fallocate` 塞根盘到 95%+ | DiskPressure → eviction 连环 → kubelet 死 | 清盘 + 校验 eviction 默认表被谁改了（§6.4 + §6.4 mergeDefault） |
| 6 | 放一张过期的 Ingress TLS 证书 | TLS 握手 `certificate has expired` | 证书 renew 流程 + Ingress TLS Secret 替换（§5.2 通法） |
| 7 | 删 CoreDNS / 拦安全组 6443 | cluster.local 全面解析失败 / API 不可达 | 第 3 章 DNS 排障链 + 放开安全组（§2.6 端口表） |

> ❗ 每场必备三行：「破坏前我看了什么快照/备份」「破坏中 `kubectl get --raw=/readyz?verbose` 与 `kubectl get events -A` 各显示什么」「恢复中哪个对象是最大因果」——三行齐备，你的 runbook 才算真成型。

---

## 十、实验（实验 L2、L3 的操作本体）

以下 4 个实验都在 **Multipass VM**（参照 `云服务/Multipass-使用指南.md`）上完成——macOS 本机不直接跑 kubeadm。

### 实验 7.1 Multipass 三节点搭建记录（L2 上篇：v1.37 三节点 kubeadm 集群）

**step 0**：宿主机（macOS）上 `multipass version` 能动就成。

```bash
# step 1：三台 VM（1 CP + 2 worker），Ubuntu 24.04 LTS（noble）
multipass launch 24.04 --name k8s-cp1  --cpus 2 --memory 4G --disk 20G
multipass launch 24.04 --name k8s-w1   --cpus 2 --memory 4G --disk 20G
multipass launch 24.04 --name k8s-w2   --cpus 2 --memory 4G --disk 20G
multipass list            # 记下三台 IP：Multipass 为它们分配私网 IPv4
```

**step 2**：每台 VM 依次跑 §2 前置 8 件事（用 `multipass shell k8s-cp1` 进，或写成脚本后用 `multipass transfer` 上传 + `multipass exec` 执行）：

```bash
# 2A swap + 内核/sysctl（§2.1 + §2.2 合并）
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

# 2C chrony + kubeadm/kubelet/kubectl（§2.5 + §2.8）
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

**step 3**：k8s-cp1 上 init（使用 §1.4 v1beta4 完整样例；`controlPlaneEndpoint` 写 `k8s-cp1:6443`，advertiseAddress 写 Multipass 私网 IP）：

```bash
sudo kubeadm init --config kubeadm-config.yaml --upload-certs 2>&1 | tee /tmp/kubeadm-init.log
mkdir -p $HOME/.kube && sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config && \
sudo chown $(id -u):$(id -g) $HOME/.kube/config
kubeadm token create --print-join-command     # 复制 worker join 命令（token + hash）
```

**step 4**：CNI（§3.4 的 Cilium 安装命令；任何一台有 kubectl 的节点执行即可）：

```bash
helm repo add cilium https://helm.cilium.io/ && helm repo update
helm install cilium cilium/cilium --version 1.20.2 -n kube-system \
  --set image.pullPolicy=IfNotPresent --set ipam.mode=kubernetes
cilium status --wait
```

**step 5**：`multipass shell k8s-w1`、`k8s-w2` 分别粘 join 命令（§3.3；w1/w2 的 §2 前置已先做）。

**step 6**：验收三行：

```bash
kubectl get nodes -o wide
kubectl -n kube-system get pods -o wide | grep -E 'cilium|coredns|kube-proxy'
kubectl get --raw='/readyz?verbose' | tail -6
```

> ❗ 本实验故障排查的两个文件先记：**`/tmp/kubeadm-init.log`** 与 **`journalctl -u kubelet -f`**——ImagePullBackOff、containerd cri-disabled、kubelet crashloop 的首发信号都在这里，别从 stdout 猜。

**实验收获**：能从 blank VM 走到 `kubectl get nodes` 全 Ready 的每一步出处都记了；后三章所有演练都以这个集群为主场。

### 实验 7.2 升级演练模板（L2 下篇：**v1.38 发布后执行**；占位的 `1.38.x-*` `/v1.38` 到时用 `apt-cache madison kubeadm` 查询替换）

```bash
# ========== k8s-cp1（首台控制面） ==========
# ① （可选但推荐）etcd 手动快照——独立于 kubeadm 备份路径的离线证据链
sudo ETCDCTL_API=3 etcdctl snapshot save /tmp/snapshot-pre-upgrade.db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# ② 换 Minor 源 + kubeadm
sudo sed -i 's|core:/stable:/v1.37|core:/stable:/v1.38|' /etc/apt/sources.list.d/kubernetes.list
sudo apt-mark unhold kubeadm
sudo apt-get update && sudo apt-get install -y kubeadm='1.38.x-*'
sudo apt-mark hold kubeadm
kubeadm version -o short

# ③ plan + diff + apply
sudo kubeadm upgrade plan
sudo kubeadm upgrade diff v1.38.x
sudo kubeadm upgrade apply v1.38.x

# ④ drain → kubelet/kubectl → uncordon
kubectl drain k8s-cp1 --ignore-daemonsets
sudo apt-mark unhold kubelet kubectl && \
sudo apt-get install -y kubelet='1.38.x-*' kubectl='1.38.x-*' && \
sudo apt-mark hold kubelet kubectl
sudo systemctl daemon-reload && sudo systemctl restart kubelet
kubectl uncordon k8s-cp1

# ========== k8s-w1 / k8s-w2（逐台；同序） ==========
multipass exec k8s-w1 -- sudo bash -c "apt-mark unhold kubeadm && apt-get update && apt-get install -y kubeadm='1.38.x-*' && apt-mark hold kubeadm"
multipass exec k8s-w1 -- sudo kubeadm upgrade node
kubectl drain k8s-w1 --ignore-daemonsets
multipass exec k8s-w1 -- sudo bash -c "apt-mark unhold kubelet kubectl && apt-get install -y kubelet='1.38.x-*' kubectl='1.38.x-*' && apt-mark hold kubelet kubectl && systemctl daemon-reload && systemctl restart kubelet"
kubectl uncordon k8s-w1
# 同一流程跑 k8s-w2

# ========== 收尾验证 ==========
kubectl get nodes -o wide                # 三行均 v1.38.x Ready
kubeadm certs check-expiration           # 已被 upgrade 自动 renew（剩余 ~364d）
kubectl get --raw='/readyz?verbose' | tail -3
```

> 想做 patch 级演练（v1.37.0 → v1.37.x），把目标版本号换成最新 patch、全序重跑——**顺序不变**。另外，演练前可以做 VM 级快照；但**VM 快照 ≠ etcd 快照**——「物理恢复 VM」与「恢复 etcd 数据」是两层、不可互相替代。

### 实验 7.3 证书实验（L3 中篇）

```bash
# ① 现状
sudo kubeadm certs check-expiration

# ② 单点 renew
sudo kubeadm certs renew apiserver

# ③ 静态 Pod 重启（四大件依次移走-等 20-移回）
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/ && sleep 20 && \
  sudo mv /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/

# ④ 验证新证书 SAN
openssl s_client -connect 127.0.0.1:6443 -servername k8s-cp1 </dev/null 2>/dev/null | \
  openssl x509 -noout -subject -ext subjectAltName -dates

# ⑤ kubelet serving 证书自签验证（10 的证据）
openssl s_client -connect 127.0.0.1:10250 </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates

# ⑥ 轮转开关
kubectl get cm kubelet-config -n kube-system -o=jsonpath='{.data.kubelet}' | grep -E 'rotateCertificates|serverTLSBootstrap'
```

> ❗ 期望在第 ⑤ 步看到 `subject=CN=k8s-cp1@<ts>` 且 `issuer=CN=k8s-cp1-ca@<ts>` 的自签形态——这是 kubeadm 默认下 metrics-server/`kubectl logs` 报 `x509: certificate signed by unknown authority` 的根源；要切签发形态，见 §5.3（`serverTLSBootstrap: true` + 配套 approver）。

### 实验 7.4 eviction 实验：上一个内存炸弹 Pod 看 kubelet evict（观察 QoS 顺序）

```bash
# ① 压worker（示例用 k8s-w1）上一个 stress Pod（requests 小、limit 大于节点可用）
kubectl apply -f - <<'YAML'
apiVersion: v1
kind: Pod
metadata: { name: mem-bomb }
spec:
  nodeSelector: { kubernetes.io/hostname: k8s-w1 }
  containers:
  - name: bomb
    image: polinux/stress
    args: ["--vm", "1", "--vm-bytes", "3G", "--vm-hang", "120"]
    resources:
      requests: { memory: "128Mi", cpu: "100m" }     # Burstable
      limits:   { memory: "6Gi" }                    # limit 超过节点可用内存 → 不会触发 cgroup OOM，才能看到 kubelet eviction
YAML

# ② 确认它是 Burstable
kubectl get pod mem-bomb -o jsonpath='{.status.qosClass}{"\n"}'

# ③ 同时观察：node condition、evict 事件与 QoS
kubectl describe node k8s-w1 | grep -A8 Conditions
kubectl get events -A --sort-by='.lastTimestamp' | grep -iE 'evict|memory'
```

**观察要点**（对照 §6.4 排序规则）：

- mem-bomb 的 **usage(3G) > requests(128Mi)**——evict 候选第一顺位；QoS 可用来**估算**排序，但真正决定的是「usage 是否超 requests」；
- 同时跑一个 BestEffort Pod（完全不写 resources）——它**先于** Burstable 被 evict（usage 恒超 request）；
- 给 mem-bomb 改挂 `priorityClassName: system-node-critical` 再跑——kubelet 给它的 oom_score_adj 拉到 -997；高优 Pod 在 usage 不超 requests 时会被留到最后；Guaranteed + usage≤requests 是最后的堡垒；
- 静态 Pod（/etc/kubernetes/manifests/，v1.37 里控制面四大件就是）即使 evict 也会被 kubelet 按「本节点必须跑的 intent」**重启拉回**（node-pressure-eviction 页原话）——这就是为什么 apiserver 不会被你真的「杀死」；

**清理**：

```bash
kubectl delete pod mem-bomb --force --grace-period=0
kubectl describe node k8s-w1 | grep -iE 'MemoryPressure|eviction manager'
```

> 实验收获：「usage vs requests → Priority → QoS 只是估算量」的 eviction 排序亲手看到了——这是在生产「MemoryPressure 连环驱逐」告警里你马上就认的格局。

---

## 十一、速查表 + 背诵要点 + 参考链接

### 11.1 一页速查

| 主题 | 命令 / 字段 / 默认值 |
|------|---------------------|
| kubeadm 六大族 | `init / join / reset / token / certs / upgrade`；`kubeadm config print init-defaults` |
| 配置 API | 现行唯一 `kubeadm.k8s.io/v1beta4`；v1beta3 在 **v1.37 移除**（release-1.37 源码确认）；v1.31 起 kubeadm 可做 v1beta3→v1beta4 迁移 |
| 证书有效期 | 叶证 8760h（1 年）/ CA 87600h（10 年）——v1beta4 字段 `certificateValidityPeriod` / `caCertificateValidityPeriod`；源码常量同名 |
| swap / cgroup / sysctl | `failSwapOn=true` 默认；`cgroupDriver: systemd` 与 containerd `SystemdCgroup: true` 配对；sysctl 三件 `bridge-nf-call-iptables / bridge-nf-call-ip6tables / ip_forward` |
| 端口表（v1.37 官方） | 控：6443 / 2379-2380 / 10250 / 10257 / 10259；worker：10250 / 10256 / 30000-32767（TCP+UDP）；kubeadm 源码附加：etcd metrics 2381、kubelet healthz 10248 |
| 静态 Pod 心智 | `/etc/kubernetes/manifests/*.yaml` → kubelet 每 20s 扫（fileCheckFrequency）→ spec hash 变即重启；delete API 镜像对象无效 |
| join 防 MITM | token + `--discovery-token-ca-cert-hash sha256:<hash>`；hash = CA SPKI SHA-256（§3.3 命令重算） |
| 版本偏差（v1.37 官方） | apiserver HA ±1；kubelet 同或至多老 3 minor；CM/scheduler 同或至多老 1；kubectl ±1；kubeadm vs 控制面 同/+1；etcd 3.7.1-0（1.35/36/37 同） |
| 升级序列 | 快照 → plan/diff → 首 CP `apply` → 后续 CP `node` → drain → 升 kubelet/kubectl + hold → uncordon → worker 重复 |
| upgrade 边界 | 不重写业务 workload；重写控制面静态清单（手工 extraArgs 会丢）；自动 renew 证书（`--certificate-renewal=false` 关）；`/etc/kubernetes/tmp/kubeadm-backup-*` 用后手工清 |
| 证书家谱 | 3 把 CA（kubernetes / etcd / front-proxy）+ SA 密钥对；admin.conf 绑 `kubeadm:cluster-admins`、super-admin.conf 为 system:masters（勿分享） |
| kubelet 证 | client：`rotateCertificates: true`（kubeadm 默认）+ csrapproving selfnodeclient 自动批；serving：默认自签（生产要 `serverTLSBootstrap: true` + 第三方 approver：kubernetes.io/kubelet-serving 不自动批） |
| CA 根换新 | 11 步手册（§5.4）：新 CA → bundle（CM root/apiserver client/kubelet CA）→ SA token 全量重发 → apiserver/kubelet 换证重启 → Pod roll → 清旧 CA |
| apiserver flag 默认 | inflight 400/200（APF 总 600）；watch-cache true；etcd-compaction-interval 5m；min-request-timeout 1800；goaway-chance 0~0.02（建议 0.001 起）；EtcdRangeStream Beta 默认开（etcd≥3.7） |
| QPS 默认 | CM **20/30**；scheduler **50/100**；kube-proxy **5/10**；kubelet **50/100**；image pull **5/10** |
| CM 并发默认 | deployment/rs 5、gc 20、endpoint 5、namespace 10、cronjob 5 |
| kubelet 调优点 | maxPods=110（与 §6.5 110/节点 同源）；imageGCHigh/Low=85/80；containerLogMaxSize=10Mi×5；evictionHard 5 条默认 + mergeDefaultEvictionSettings；serializeImagePulls=true |
| etcd 大集群 | 静态 5-member 推荐；events 拆独立 etcd；生产最低 3.4.29+/3.5.11+；quota 默认 2GiB；defrag 程序化 |
| 大规模数字（官方 v1.37） | ≤5000 nodes / ≤150000 pods / ≤300000 containers / **≤110 pods per node** |
| 节点自运维 | NPD 4 daemon（SystemLog/Stats/CustomPlugin/HealthChecker）+ 3 exporter（k8s/prometheus/stackdriver）；draino 联动：condition→label→cordon+drain（守 PDB）+leader elect；原仓 cloudflare/draino 已 404，自选活跃 fork |
| 租户治理 | ResourceQuota（requests+limits+storage+count+scopeSelector）+ LimitRange（defaultRequest/default/min/max/maxLimitRequestRatio）+ 纪律：memory limit 照写 / CPU limit 视超售约束 / 系统 Pod 用 PriorityClass 保护 |
| 灾备铁三角 | etcd 快照（每小时+升级前）+ IaC + Velero（每日）；恢复顺序：静态清单→etcd→组件+证书→RBAC/webhook→CNI/DNS/proxy/CSI→业务 |

### 11.2 关键要点（背诵版）

1. **kubeadm 只做 cluster lifecycle 的 subset**（init/join/upgrade/certs/token/reset + phase 拼装）；CNI/Ingress/LB/监控/etcd 备份全是你的运维边界。配置 API **现行唯一 v1beta4**（v1beta3 在 v1.37 移除——release-1.37 源码核实）。
2. **前置 8 件套**：swap、sysctl 三件、containerd `SystemdCgroup=true` 与 kubelet `cgroupDriver: systemd` 对齐、sandbox_image 国内加速、chrony、端口放行、`pkgs.k8s.io` 三件套 + `apt-mark hold`。**cgroup driver 不一致是「两套记账」类事故的祸首**（§2.3）。
3. **`controlPlaneEndpoint` 在 init 就写**——单 CP 将来上 HA 的唯一门票；`certSANs` 决定 apiserver 证书 SAN 覆盖；改 SAN 走 renew + 重启静态 Pod。
4. **join 的防 MITM 双保险**：bootstrap token = 低权限入场券；`--discovery-token-ca-cert-hash` = 钉住 CA 公钥防篡改——用 §3.3 一条 `openssl` 命令现场重算对峙。token 重发=`kubeadm token create --print-join-command`。
5. **升级序固定**：快照 → plan/diff → apiserver（首 CP `apply`、后续 CP `node`）→ CM/scheduler → kubelet（drain→升包→uncordon）→ kube-proxy；**etcd 快照是第一步而不是事后**；**升级会重写静态清单=你手工塞的 extraArgs 必丢**——所有定制必须进 ClusterConfiguration.extraArgs/volumes。
6. **1 年叶证、10 年 CA**（源码）：kubeadm upgrade 自动 renew（`--certificate-renewal=false` 关）；renew 以旧证书为准读 CN/O/SAN——**与 kubeadm-config ConfigMap 无关**；renew 后必重启四静态 Pod（文件移走-等 20s-移回）。
7. **kubelet 两族证**：client 自动轮转 + selfnodeclient 自动批（默认路径）；serving 默认自签（`x509 unknown authority` 之根源）→ 生产开 `serverTLSBootstrap: true` **必配第三方 approver**（`kubernetes.io/kubelet-serving` 不自动批）；`RotateKubeletServerCertificate` v1.37 Beta 默认开。
8. **CA 根换新 11 步**：bundle 先行（CM root-ca-file + apiserver/scheduler client-ca-file + kubelet CA）→ 全 Pod SA token 重读 → apiserver/kubelet 换证 → 全 Pod roll → 清旧 CA 与 cluster-info CM；常态不轮，泄漏/合规/算法更换才触发；总窗口按 2~4h/人 + 全量 rollout 观察估。
9. **生产资源纪律**：memory limit 照写（必写）＋ CPU limit 视「强超售约束」场景写 + PriorityClass 保护系统件（`system-cluster-critical=2e9`/`system-node-critical=2000001000`）+ quota/LimitRange 双闸。eviction 真序：**usage 超 requests → Priority →（同级）usage/requests 比值**——QoS 只是估算量（§6.4/实验 7.4）。
10. **大集群数字是「支持上限」不是推荐**：5000 nodes / 150000 pods / 300000 containers / **110 per node**（官方 large cluster 页）——它们的背后是 etcd 写速 × watch 扇出 × 每 apiserver watch-cache 内存的乘积约束（§6.5）；超规模只走「events 拆独立 etcd + 多集群」。

### 11.3 参考链接

| 主题 | 链接 |
|------|------|
| kubeadm config API v1beta4（逐字段与各版本增量） | https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta4/ |
| kubeadm config API v1beta3（deprecation 声明） | https://kubernetes.io/docs/reference/config-api/kubeadm-config.v1beta3/ |
| kubeadm 证书管理（check-expiration / renew / serverTLSBootstrap / super-admin.conf） | https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/ |
| kubeadm 集群升级（v1.37 页） | https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/ |
| 用 kubeadm 搭集群（controlPlaneEndpoint/join/admin.conf 警告/cleanup） | https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm/ |
| HA topology（stacked vs external etcd 官方对比） | https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/ha-topology/ |
| 版本偏差政策（component skew 与升级顺序） | https://kubernetes.io/releases/version-skew-policy/ |
| 端口与协议（required-ports 官方表） | https://kubernetes.io/docs/reference/networking/ports-and-protocols/ |
| kube-apiserver flags（400/200、goaway、shutdown-delay-duration、EtcdRangeStream） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-apiserver/ |
| kube-controller-manager flags（20/30、concurrent-*、leader、signing-duration） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-controller-manager/ |
| kube-scheduler flags | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-scheduler/ |
| kube-proxy flags（5/10、iptables mode、healthz 10256） | https://kubernetes.io/docs/reference/command-line-tools-reference/kube-proxy/ |
| KubeletConfiguration v1beta1（maxPods/imageGC/log/eviction/failSwapOn/failCgroupV1/separateDiskGC） | https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/ |
| Node-pressure eviction（5 条默认硬阈值、驱逐排序、OOM scores、static pod 自拉起） | https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/ |
| Manual CA rotation（11 步 + issue 1350 bundle 坑 + cluster-info CM 替换命令） | https://kubernetes.io/docs/tasks/tls/manual-rotation-of-ca-certificates/ |
| TLS bootstrapping（CSR/csrapproving/serving 不自动批/kubelet-csr-approver 审核要点） | https://kubernetes.io/docs/reference/access-authn-authz/kubelet-tls-bootstrapping/ |
| PKI 证书需求表（3 把 CA + 逐证书 CN/O/usages） | https://kubernetes.io/docs/setup/best-practices/certificates/ |
| 大集群设计（5000/150000/110/事件拆 etcd/PriorityClass 建议） | https://kubernetes.io/docs/setup/best-practices/cluster-large/ |
| K8s 上的 etcd 运维（5-member 建议/etcdutl/restore 须停 apiserver/EtcdRangeStream） | https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/ |
| Monitor Node Health（NPD 本体/4 daemon/3 exporter） | https://kubernetes.io/docs/tasks/debug/debug-cluster/monitor-node-health/ |
| NPD Helm chart（deliveryhero repo） | https://artifacthub.io/packages/helm/deliveryhero/node-problem-detector |
| Container runtimes（containerd 1.x/2.x SystemdCgroup 位置、CRI autodetect、pause、cgroup v1 弃用） | https://kubernetes.io/docs/setup/production-environment/container-runtimes/ |
| kubeadm 常量（release-1.37 源码：etcd 3.7.1-0 / CoreDNS v1.14.7 / Pause 3.10.2 / 证书效期 / timeout 默认值 / 端口常量） | https://raw.githubusercontent.com/kubernetes/kubernetes/release-1.37/cmd/kubeadm/app/constants/constants.go |
| kubeadm API 目录（release-1.37 只剩 v1+v1beta4） | https://github.com/kubernetes/kubernetes/tree/release-1.37/cmd/kubeadm/app/apis/kubeadm |
| ComponentStatus deprecated 来源（v1.19 changelog） | https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-1.19.md |
| draino 现状（原仓 404 与活跃 fork 搜索点） | https://github.com/search?q=draino&type=repositories |

---

> 下一章预告：`K8s-故障排查方法论.md`（第 8 章）——本手册里出现的各类「破坏场景」（init fail、证书过期、eviction storm、etcd 满、CNI 断、节点失联）都将汇成**症状→工具→修复**的分域排障树，实验 L3 的 runbook 本体也要归档到那。
