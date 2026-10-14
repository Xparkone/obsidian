# K8s 故障排查方法论

> 精通路线第 8 章（排障篇收官；总收官见第 10 章《多集群与进阶生态》）：排障总原则与工具箱、总入口决策树、七大域（控制面/节点/调度/Pod 与容器/网络 DNS/存储/证书 TLS）分域判读链、`kubectl debug` 四形态与 nsenter 节点级绝招、事故复盘文化与三个完整 mini 案例、实验 L3（破坏-恢复演练）的作战地图
> 创建时间：2026-10-14
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37），文中标注「v1.xx 起 Beta/GA」「默认值」均对照官方 docs（kubernetes.io）、自动生成的 kubectl 命令参考、KEP 或上游源码核实；落地前仍以你本地集群版本与现场输出为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，RequestPath/list-watch/finalizer/APF/审计/健康端点判读）、`K8s-调度器深入.md`（第 2 章，§7.3 四步排查链直接引用不重讲）、`K8s-网络原理详解.md`（第 3 章，CNI/CoreDNS 三板斧/NetworkPolicy 静默放行）、`K8s-存储深入.md`（第 4 章，存储面问题清单与 PV 生命周期）、`K8s-安全加固详解.md`（第 5 章，准入/PSA/RBAC 问题清单）、`K8s-Operator开发实战.md`（第 6 章，Operator 视角问题清单）、`K8s-生产集群运维手册.md`（第 7 章，证书轮转/eviction/NPD/灾备恢复、§9.4 七大破坏场景）。**本文同时是实验 L3（破坏-恢复演练）的主场与 runbook 总入口**（总纲：`学习/K8s-精通路线-总纲.md`）。

---

## 零、本文定位与边界

### 0.1 本文的总纲：顺着 reconcile 链反查

K8s 是声明式系统。你在 YAML 里写下「期望状态」，集群里几百个控制循环（scheduler、kubelet、各 controller、CNI agent、external-provisioner、admission webhook……）轮番把「实际状态」往那里掰。**所以每一个症状，背后都是「某个控制循环没 reconcile 成功」**——Pod Pending 是 scheduler 没绑上，CrashLoopBackOff 是 kubelet 反复拉起反复失败，PVC Pending 是 provisioner 没供给，`kubectl get` 转圈是 apiserver→etcd 这条链的某环慢。

排障方法论只有一句话：**先定位症状落在哪一段控制循环上，再顺着 reconcile 链往上游反查，每一跳只信一手证据**。

```
期望状态（你的 YAML）──► 控制循环们逐环 reconcile ──► 实际状态
       ▲                        │
       │                        ▼ 比对不一致 → 事件/Condition/status 里的「证词」
       └──────── 症状 = 你在这里看到的「比对结果」

反查方向（本章的全部章节都长这个形状）：
  症状对象 → 谁该为它负责（哪台控制循环）→ 它卡在哪一环 → 那一环的输入/依赖怎么了
```

例：「Deployment 改了镜像但 Pod 没滚」——reconcile 链是 `deploy controller → RS → scheduler → kubelet → CRI`。答案是哪一环，命令就是哪一环的：`kubectl rollout status`（control loop 视角）→ `kubectl get rs`（产物视角）→ `kubectl describe pod`（调度与 kubelet 证词）→ 节点上 `crictl ps`（运行时真相）。

### 0.2 与前 7 章的关系地图（每域排障 = 机制章的实战落地）

前 7 章把机制讲透了，本章只做一件事：**把机制变成「出故障时的肌肉记忆」**。引用不重复——凡是机制章已经给过命令清单的，本文只给入口与判读法：

| 本章域 | 机制章出处 | 本文补上什么 |
|--------|-----------|-------------|
| 域一·控制面（§三） | 第 1 章 §9 生产问题清单（etcd 满/重启风暴/429/慢）；第 7 章 §5 证书、§6.1 调优 | 把「kubectl 全卡/慢/429/对象不生效」归一成判读链（readyz→静态 Pod→etcd→webhook/聚合层） |
| 域二·节点（§四） | 第 7 章 §6.4 eviction 底线与驱逐排序/QoS、§7 NPD + draino | NotReady 决策链、kubelet 日志 grep 模板、**两种 OOM 的区分**、crictl 排障速查 |
| 域三·调度 Pending（§五） | 第 2 章 §7.3 四步排查链（完整引用）、§1.5 QueueingHints、§11.1 SchedulingGates | 两个边缘 CASE：「调度系统本身病了」「明明有空闲节点但不调」 |
| 域四·Pod 与容器（§六） | 第 1 章 §4.3 finalizer；`K8s-Pod生命周期详解.md` | 全生命周期症状词典、exit code 词典、**kubectl debug 四形态**、**nsenter 绝招**、优雅退出时序 |
| 域五·网络与 DNS（§七） | 第 3 章 §5.5 CoreDNS 三板斧、§6.3-6.5 NetworkPolicy 静默放行、§4.6 conntrack、§3.5 MTU | 逐跳定位法（每跳给工具与判定标准）、ndots 两个 mini 案例、MTU 黑洞症状表 |
| 域六·存储（§八） | 第 4 章 §7 生产问题清单（主表）、§2.8 HonorPVReclaimPolicy；第 2 章 §5 VolumeBinding | PVC Pending→挂载失败→multi-attach 决策链、mount 残留与 NFS 僵死处置 |
| 域七·证书与 TLS（§九） | 第 7 章 §5 证书家谱与轮转三件套 | x509 症状词典（报错→首查→根因排序）、openssl 速查命令组 |
| Operator/CR 域外的「应用侧」 | 第 6 章 §8（reconcile 卡住/finalizer 泄漏/leader election） | 不重复——本章给的「顺着 reconcile 链反查」就是它的排查通则 |

### 0.3 与仓库 4 篇散落笔记的边界（本章是排障一本通 hub）

仓库里有 4 篇「kubectl 速查/小众命令」笔记，各有保留价值；本文给它们各自在**分域判读链里的位置**，不再重复展开：

| 已有笔记 | 保留什么（继续在那篇看） | 本章接管什么 |
|---------|------------------------|-------------|
| `K8s-排障进阶-5个冷门kubectl命令详解.md` | 5 个命令的完整语法与坑点：events 跨 ns、debug 三模式、logs --previous、top+describe node、explain/api-resources | 这些命令「放在哪一步用」：events 进 §1.3/§二总入口；debug 进 §6.3 四形态全解（补 profile 档与官方勘误）；--previous 进 §6.6 现场留证；top/QoS 进 §4.3/§4.4（资源与 OOM 判读） |
| `Docker-K8s-快捷批量操作手册.md` | jsonpath/jq/cordon-drain 批量操作与危险操作安全清单（§八「先列出再执行」仍是排障期的高压线） | 批量操作在排障场景的落点：批量删 Evicted（§4.3 eviction 后清场）、「某节点上有哪些 Pod」（域二盘点）等只在对应域给一行引用 |
| `k8s-常用操作手册.md` | kubectl 通用速查、label/亲和/Ingress/PV 资源模板 | 排障视角的命令序（describe→logs→debug→节点件），资源语法不再重复 |
| `K8s-组件详解.md` | 各组件功能详解与 §8 大速查（8.1-8.5 命令索引） | 「组件出故障时怎么判读」：静态 Pod 卡死（§3.2）、etcd alarm（§3.3）、kubelet 日志（§4.2）、CoreDNS（§7.3）——症状→判读→修复，命令清单不重复 |

> 一句话：**这 4 篇是「命令词典」，本章是「什么时候用哪本词典哪一页」**。

### 0.4 本文也是实验 L3 的作战地图

第 7 章 §9.4 列了 7 个破坏场景（错证书/删 etcd 数据/杀 CNI/停 kubelet/堵磁盘/过期 Ingress 证书/CoreDNS 黑洞），本文 §11（实验 8.1）把它们扩成**带破坏命令、预期症状、标准排查路径、恢复动作、自评耗时目标**的完整 runbook 表——每个场景演完，把实录写成一篇复盘（按 §10 模板）归档，你的「肌肉记忆」才算成型。

❗ 心智前十条（先背这十条再看正文）：①症状=没 reconcile 成功，先找负责的控制循环；②先摸「面」再钻「点」；③events 是证词但有 1h TTL；④API 层状态 ≠ 节点真相；⑤一次只改一个变量；⑥先止血后根治；⑦生产上默认只读优先于写；⑧任何「删」字命令先 `kubectl get` 同选择器列一遍；⑨复盘不写=没修好；⑩runbook 不演练=没有 runbook。

---

## 一、方法论框架：五个动作与工具箱全景

### 1.1 五个动作（顺序不要乱）

| # | 动作 | 关键问题 | 典型产出 |
|---|------|---------|---------|
| 1 | **界定域** | 谁在抱怨？影响面多大（单 Pod/单节点/单 ns/全集群）？ | 一句话症状陈述 + 影响面边界（决定进哪个域 §三~§九） |
| 2 | **收集证据** | 哪些一手信源还没看？（对象 events、组件日志、节点子系统、指标） | 只读、可复现的证据列表；时间线第一版 |
| 3 | **假设-验证** | 哪个假设能用一条命令证伪？ | 每次只证一个假设，验证记录进时间线 |
| 4 | **修复** | 先止血（不追根因也要让业务回来）还是直接根治？ | 止血动作（cordon/降级/failurePolicy 临时放宽）+ 根治动作分开记账 |
| 5 | **复盘** | 为什么监控没先报？为什么人没先发现？ | §10 的 timeline 复盘文 + 可复现 runbook |

三条贯穿全程的纪律：

- **先读再看再动**：证据收集期坚持「只读命令」——`get/describe/logs/top/diff/get --raw` 全家都是只读；写操作（delete/patch/scale/cordon）进修复期再动，且一次一个。
- **API 层状态 ≠ 节点真相**：apiserver 里 Pod 是 Running，节点上容器可能早挂了（kubelet 状态上报有自己的节奏，NodeLease 续约窗口默认约 40s，超窗即被判失联）。两边对不上时，**节点侧（crictl/journalctl/dmesg）是更接近物理的真相**——参考第 7 章 §3.5「get cs 已废」的教训：任何「替你代报」的状态都要怀疑一层。
- **变更同时段审计**：「故障开始前 30 分钟，谁动了什么」是 60% 事故的第一问题。K8s 审计日志（第 1 章 §8，策略粒度与后端形态）、GitOps 仓库 commit（Argo CD 场景）、云厂商操作审计三线对表。

### 1.2 工具箱全景（按「离故障多近」分层）

| 层 | 工具 | 什么时候是它 |
|----|------|-------------|
| **kubectl 内置件** | `get/describe/logs/exec/--previous/top/wait/diff/get --raw/api-resources/explain/rollout status/history/debug/apply --dry-run=server` | 覆盖 80% 日常排障；`kubectl wait --for=condition=ready pod/x --timeout=60s` 在演练里当「预期症状探针」用 |
| **集群内件** | Event 对象（默认 TTL **1h**，apiserver `--event-ttl`）、ephemeral containers（v1.25 GA）、apiserver 审计日志（第 1 章 §8）、metrics.k8s.io 聚合层 | 事件过了 TTL 就没了——事故正在发生时先把 events 捞一遍存文件（§1.3 ③）；kubeadm 集群的审计开关在 kube-apiserver extraArgs（`--audit-log-path` 一族，配置方式与第 7 章 §1.4 样例同源） |
| **节点件** | `crictl`（CRI 直连）、`journalctl -u kubelet/-k`、`systemctl status kubelet/containerd`、`dmesg -T`、`ss/ip/conntrack/tcpdump/nsenter`、`findmnt/lsblk/df -i`、`iostat -x` | kubelet/CRI/内核三层真相；本章 §四、§六大量使用 |
| **外部件** | metrics-server 之上的 Prometheus/Grafana 告警（本仓 `监控/` 目录）、pprof（apiserver `--profiling` 默认开：`kubectl get --raw=/debug/pprof/goroutine?debug=1`）、云厂商监控 | 「面」层信息：时延水位、429 率、etcd slow 曲线——判断「是个例还是系统性」的第一手 |

❗ 两套容易混的「看状态」入口：① `kubectl describe node/pod` 是**对象视角**（apiserver 记录的最后上报）；② `crictl ps` / `systemctl status` / `dmesg` 是**本机视角**。判 NotReady、Terminating、CrashLoop 三件套时，两视角对账是基本动作。

### 1.3 事件（Event）的正确姿势

Event 是排障的「第一证词」，但它有三条物理性质常被忘记（官方 debug-pods 页原话「events are namespaced」+ 本仓排障进阶笔记）：

```bash
# ① 全集群按时间排（Node/PV 等集群级对象的事件落在 default 等 ns，必须 -A 才看得到）
kubectl get events -A --sort-by='.lastTimestamp' | tail -30
# ② 只捞 Warning（生产排障第一板斧）
kubectl get events -A --field-selector type=Warning --sort-by='.lastTimestamp' | tail -30
# ③ ★事故正在发生时：先把证据存盘（TTL 默认 1h，复盘时多半已过期）
kubectl get events -A --sort-by='.lastTimestamp' > /tmp/events-$(date +%H%M).txt
kubectl get events -A -o json > /tmp/events-$(date +%H%M).json      # 留 JSON 便于事后 jq 关联
# ④ 围着单个对象看
kubectl get events -n <ns> --field-selector involvedObject.name=<pod> --sort-by='.lastTimestamp'
```

- `--field-selector` 只支持 `type/reason/involvedObject.*` 少数键；要按任意条件筛，用 `-o json | jq`（引排障进阶笔记 §一坑点）。
- Event 量大本身可能是病因（探针风暴/镜像回退刷屏推高 etcd，第 1 章 §9.1）——`kubectl get events -A -o json | jq -r '.items[].reason' | sort | uniq -c | sort -rn | head` 看看谁是刷屏主力。

---

## 二、总入口决策树：先摸「面」，再钻进域

### 2.1 三条止损命令（30 秒内把「面」摸清）

```bash
# ① 控制面本体健康（含 etcd、informer-sync、poststart hook 链；判读法引第 1 章 §9.6.1）
#    readyz verbose 输出正常项形如 [+]ping ok；故障项形如 [-]etcd failed——只捞故障项：
kubectl get --raw='/readyz?verbose' | grep '^\[-\]' || echo "all ok"
# ② 节点面：READY 列 + 版本偏差（混版也可能是新病）
kubectl get nodes -o wide
# ③ 全集群最近事件（Warning 优先；这 30 行基本能圈定域）
kubectl get events -A --sort-by='.lastTimestamp' | tail -30
```

加一条业务视角（三选一并行不冲突）：`kubectl get pods -A -o wide --field-selector=status.phase!=Running | head -20`（非 Running 全景）；`kubectl top node`（资源面）；`kubectl get ns | grep -v Active`（卡在 Terminating 的 ns）。

### 2.2 ASCII 决策树

```
                       ┌─────────────────────────────┐
                       │ 报障/告警进来：症状一句话    │
                       └──────────────┬──────────────┘
                                      ▼
              kubectl 完全卡住/超时/连不上？ ─── 是 ──► 域一（§三 控制面）
                                      │否              （顺带：先看是不是自己 kubeconfig/
                                      ▼                 网络/LB 探针的问题）
              节点面：大面积 NotReady ─── 是 ──► 域一/域二（先 §3.3 判断是不是
                                      │否              级联：CNI 挂了全站 NotReady）
                                      ▼
              单个/少数节点 NotReady ─── 是 ──► 域二（§四 节点）
                                      │否
                                      ▼
              Pod 面异常？按 phase/status 分流：
                Pending ────────────────────────► 域三（§五 调度）
                ImagePull*/CreateContainer*/CrashLoop/
                Init:* / Running 但探针不过 / ───► 域四（§六 Pod 与容器，最大篇幅）
                Terminating 卡死
                Running 但不通/慢 ──────────────► 域五（§七 网络与 DNS）
                Pending/挂载类事件带 volume/PVC ─► 域六（§八 存储）
                x509/TLS 握手/证书过期报错 ──────► 域七（§九 证书与 TLS）
                                      │
                                      ▼
              都看不出？回到 §1.2 工具箱上探一层：
              Prometheus 曲线定「面」→ pprof/审计定「谁」→ 节点件定「真相」
```

❗ 两条使用说明：**多域并发是常态**（etcd 慢→API 慢→Pending 增加，三个「域」的症状都是同一条根因链的叶子；按域一→四的顺序收敛，别在每个叶子各修一次）；**域五之前先过域四**（「不通」里有三成是容器根本没跑起来/探针不过，先确认进程活着再抓包）。

---

## 三、域一：控制面故障

### 3.1 症状表（先对号入座）

| 症状 | 更深一层的现象 | 首查 |
|------|---------------|------|
| kubectl 全卡：任何命令超时/`connection refused` | LB/跳板网络 vs apiserver 进程 vs etcd 三层分不清 | 本机 `curl -sk --connect-timeout 3 https://<endpoint>:6443/readyz` + 控制面节点上 `journalctl -u kubelet` |
| kubectl 能用但慢：get/list 都要几秒 | 所有请求一起慢（etcd 传导）vs 只有 LIST 大集合慢（watch cache/大对象） | `kubectl get --raw='/metrics'` 里 `apiserver_request_duration_seconds` 与 `etcd_request_duration_seconds`（第 1 章 §9.5） |
| 客户端报 429 带 `Retry-After` | APF 拒绝/inflight 到顶/watch cache 未就绪三类（第 1 章 §9.3） | `kubectl get --raw='/metrics' \| grep apiserver_flowcontrol_rejected_requests_total` 看 reason 分布 |
| 对象创建了但「没生效」 | admission 链塌（webhook failurePolicy=Fail）vs 控制器没在跑 | events + `kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations` |
| 聚合层 500：`kubectl top` 报 `Metrics API not available` | APIService 后端挂了（metrics-server/cert-manager 等） | `kubectl get apiservices \| grep -v Local`（第 1 章 §6.3 FailedDiscoveryCheck 判读） |

### 3.2 判读链（按序执行，每步给「看向哪里」）

**step 1 readyz verbose：给依赖链点名**

```bash
kubectl get --raw='/readyz?verbose' | grep '^\[-\]' || echo all-ok
# 常见失败项含义（对照第 1 章 §9.6.1）：
#   [-]etcd failed                → etcd 连接超时/ALARM（step 3）
#   [-]etcd-readiness failed      → etcd 能接受连接但 quorum 没了
#   [-]informer-sync failed       → watch cache 没灌满（此时 LIST/WATCH 会 429——保护行为，不是故障）
#   [-]poststarthook/* failed     → admission/聚合层初始化没跑完
```

**step 2 静态 Pod 真相：API 视角与节点视角对账**

```bash
# API 视角（mirror Pod，可能滞后）
kubectl -n kube-system get pods -o wide | grep -E 'kube-apiserver|kube-controller-manager|kube-scheduler|etcd'
# 节点真相（控制面节点上执行；静态 Pod 归 kubelet 直管，不经过 apiserver）
sudo crictl ps | grep -E 'kube-apiserver|controller-manager|scheduler|etcd'
sudo journalctl -u kubelet --since '30m ago' | grep -Ei 'apiserver|etcd|scheduler' | tail -30
# 清单本体（手改清单拼错字符 = 连环 crashloop；第 7 章 §3.6 大坑）
ls -la /etc/kubernetes/manifests/
```

**step 3 etcd 磁盘/碎片/quota（v1.37 kubeadm 默认 etcd 3.7.1-0，stacked 形态）**

```bash
sudo ETCDCTL_API=3 etcdctl endpoint status -w=table \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key
# 看 DB SIZE（quota 默认 2 GiB）与 ALARM。NOSPACE 告警处置链（compact→defrag→disarm）
# 完整 step-by-step 在 `K8s-etcd详解.md` §5.4 与第 7 章 §6.3，这里只给「是不是满」的一眼判断。
```

**step 4 审计与调用方（「谁在打 apiserver」）**：apiserver 慢或 429 而 etcd 正常时，查流量来源——`kubectl get --raw='/metrics' | grep apiserver_request_total | sort` 按 verb/resource/client 看；更细的「谁、何时、改了什么」走审计日志（第 1 章 §8；实验 1.4 里分析过 exec/logs 足迹的同一条链）。多副本 HA 场景记得逐台取样（LB 后各实例水位可能不均）。

### 3.3 常见根因表（按生产出现率排）

| 根因 | 判据 | 处置要点 |
|------|------|---------|
| **etcd 磁盘满 / NOSPACE** | readyz `[-]etcd`；`endpoint status` ALARM 列 `NOSPACE`；`mvcc: database space exceeded` | compact+defrag+disarm 三连（`K8s-etcd详解.md` §5.4）；查元凶（event 洪峰/大对象，第 1 章 §9.1）；升 quota 只是权宜 |
| **控制面证书过期/签错** | kubectl/x509 报错（域七词典 §九）；`kubeadm certs check-expiration` | `kubeadm certs renew <name>` + 静态 Pod 重启三件套（第 7 章 §5.2） |
| **webhook 自锁**（failurePolicy=Fail + 后端挂/超时） | 写 API 大面积失败，报错里带 `failed calling webhook "xxx": ...`；读正常 | 急救：把 offending webhook `failurePolicy` 临时改 `Ignore` 或给 `namespaceSelector/objectSelector` 加排除 → 后端修好后收紧；根治：timeoutSeconds 刻意收窄（默认 10——admission 链的咽喉参数，「救火水位」场景 1~3s 才不至于排队堵死 APF 泳道）、kube-system 类系统 ns 显式排除、后端多副本 + PDB（设计面见第 5 章 §3） |
| **CNI/CSI 未就绪 → 节点 NotReady → 级联成「控制面病」假象** | `kubectl get nodes` 全 NotReady 但 readyz 全绿；kubelet 日志 `plugin is not initialized: cni config uninitialized` | 这不是控制面故障——修 CNI（域二/域五）；鉴假法：readyz 绿 + 静态 Pod Running + etcd 状态正常 = 控制面没病 |
| **聚合层后端挂** | `kubectl get apiservices` 非 Local 行 `False`；describe 看 `FailedDiscoveryCheck` 的 message | 修后端：Pod 挂了/selector 漂移/证书/NetworkPolicy（第 1 章 §6.3 的表照用） |
| **watch 重连风暴 / informer 大并发重启** | apiserver CPU/内存尖刺 + LIST 时延涨 + `apiserver_registered_watchers` 陡增 | 错峰启动控制器副本；selector 收窄；只 watch metadata（第 1 章 §9.2/§3.8） |
| **手改清单/证书路径拼错** | 静态 Pod 连环 crashloop，`journalctl -u kubelet` 有 `unknown flag`/`no such file` | 回滚 `/etc/kubernetes/manifests/*.yaml`（第 7 章 §3.6：把清单当生产配置对待，先备份再改） |

> ❗ 「控制面死了」与「控制面活着但大家都以为它死了」是两件事。后者的高频形态：kubectl 选对 context 了吗（`kubectl config current-context`）、跳板/LB 健康探针打在 TCP 443 而不是 `/readyz`（第 7 章 §4.4 经典翻车）、admin.conf 证书过期（域七）。排障第一条：**先在自己这端自证清白，再怀疑集群**。

---

## 四、域二：节点故障

### 4.1 NotReady 决策链（先分四类，别混搭着查）

```
Node NotReady（describe 里 Conditions Ready=Unknown/False；node lifecycle
controller 自动打上 not-ready/unreachable 污点，默认 300s tolerationSeconds
后 Pod 开始被驱逐）
   │
   ├─① 网络分区？     节点能 ping 通吗；kubelet 10250 能连吗
   │      curl -sk --connect-timeout 3 https://<node-ip>:10250/healthz
   │
   ├─② kubelet 挂了？  systemctl status kubelet （/ 看是不是实验 8.1 场景 4 的 kill -STOP 形态）
   │      journalctl -u kubelet --since '1h ago' | grep -Ei 'error|failed|fatal' | tail -30
   │
   ├─③ containerd 卡死？sudo crictl ps  超时/转圈 → systemctl restart containerd
   │      （重启 runtime 不重启业务容器——containerd shim 兜底；但要观察 shim 残留 → §6.1 Terminating）
   │
   ├─④ 证书/授权坏了？ journalctl -u kubelet | grep -E 'x509|Unauthorized|forbidden'
   │      openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -dates -subject
   │      （kubelet client 证默认自轮转，第 7 章 §5.3；轮转出幺蛾子→这里）
   │
   └─⑤ 资源拒活？     PIDPressure/DiskPressure/MemoryPressure=True；处置见 §4.3；
                       NetworkUnavailable=True → CNI 死了（域五；级联见 §3.3）
```

### 4.2 kubelet 日志高频 grep 模板（背下来就是肌肉记忆）

```bash
# 一屏看全：错类→类名归类（按出现率给对照）
sudo journalctl -u kubelet --since '1h ago' \
  | grep -EiE 'evict|oom|garbage collection|cni|PLEG|image|PullBackOff|FailedCreatePodSandBox|certificate|Unauthorized' \
  | tail -60
```

| 日志关键词 | 指向 |
|-----------|------|
| `eviction manager: attempting to reclaim` / `evicted` | node-pressure eviction 已启动 → §4.3 资源面 |
| `Memory cgroup out of memory` / `oom-kill`（也在 `dmesg`、`journalctl -k`） | OOM 相关 → §4.4 两种 OOM 的区分 |
| `PLEG is not healthy` | Pod Lifecycle Event Generator 卡——runtime 半死的经典前兆（crictl ps 大概率也卡） |
| `FailedCreatePodSandBox: ... cni` | CNI 插件挂了/配置文件坏了 → 域五先在节点这层查 |
| `image garbage collection` 刷屏 + `DiskPressure` | 磁盘见底（§4.3 + 第 7 章 §6.4 imageGC 默认 85/80） |
| `x509` / `Unauthorized`（续 lease 或注册 node 时） | 证书/NodeRestriction → 上面 ④ + §九 |

### 4.3 压力条件与 eviction（引用第 7 章，不重复）

eviction 默认五硬阈值、自定义必须挂 `mergeDefaultEvictionSettings: true` 的坑、驱逐排序「usage 超 requests → Priority → usage/requests 比（QoS 只是估算量）」——第 7 章 §6.4 与实验 7.4 已给完，本文只留三条排障期肌肉记忆：

```bash
# ① 现在是不是在驱逐边缘
kubectl describe node <node> | sed -n '/Conditions/,/Addresses/p'
kubectl describe node <node> | grep -iE 'eviction|pressure' 

# ② 谁被赶下来了（Evicted Pod 有 status.reason=Evicted；event 里有 The node had condition）
kubectl get pods -A --field-selector=status.phase=Failed -o json \
  | jq -r '.items[] | select(.status.reason=="Evicted") | "\(.metadata.namespace)/\(.metadata.name) \(.status.message)"' | head

# ③ DiskPressure 时三秒找大户（imagefs/nodefs；第 7 章 §6.4「未分盘经典事故」）
sudo du -sh /var/lib/containerd /var/lib/kubelet /var/log/* 2>/dev/null | sort -rh | head
df -h / /var/lib/containerd 2>/dev/null; df -i / /var/lib/containerd 2>/dev/null | tail -2   # 容量 + inode 各看一眼
```

### 4.4 两种 OOM：生产最常见的误认

「容器被 OOM 杀了」其实有两种完全不同的凶手，处置方向相反：

| 对比 | A：容器 cgroup OOMKilled | B：宿主机 OOM killer |
|------|--------------------------|----------------------|
| 触发 | 该容器 usage 越过 memory **limit** | 整机内存耗尽，内核按 oom_score 选人杀 |
| 现场 | `Reason: OOMKilled`、`Exit Code: 137`（128+9）  | **没有 OOMKilled reason**；容器/系统进程被随机杀（可能杀到 kubelet/containerd 一侧），containerd 重启后 exitCode 常显示非 137 或干脆无 lastState |
| 判据 | jsonpath（下） | `journalctl -k \| grep -iE 'out of memory\|oom-kill' \| tail`——`Memory cgroup out of memory: Killed process` = A 层；`Out of memory: Killed process ... (oom_score_adj ...)` 不带 cgroup 定语 = B 层 |
| 处置 | 提 limit / 降应用内存 / 找泄漏 | 找整机谁在涨（`ps aux --sort=-%mem`）；系统性杀进程还会牵连 kubelet → 更像「节点失联」；oom_score_adj 视角：Guaranteed -997/BestEffort 1000（第 7 章 §6.4） |

```bash
# A 的确诊三连（--previous 拿到上一轮日志是现场的最小集）
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'
kubectl logs <pod> -c <container> --previous --tail=50
# B 的确诊：节点上
sudo journalctl -k --since '1h ago' | grep -iE 'out of memory|oom-kill|oom_reaper' | tail -20
```

> ❗ 反直觉点：**A 是「好」的 OOM**（它保护了节点和同机同胞），B 是失控的前兆。生产原则「memory request == memory limit」（第 7 章 §8.3）的深层价值就在这里：让 OOM 只在容器自己的 cgroup 里发生。

### 4.5 crictl 排障速查（节点上的 docker ps 等价物）

crictl 是 CRI 直连调试器（官方 debug-cluster/crictl 页，v1.11 起稳定）。endpoint 默认自动发现并连本地常见 socket；写死可用 `/etc/crictl.yaml`（`runtime-endpoint: unix:///var/run/containerd/containerd.sock`）。

| 场景 | 命令 |
|------|------|
| 本机所有容器（含已退出） | `sudo crictl ps -a` |
| 按 Pod 维度看沙箱 | `sudo crictl pods`（`--name` 过滤） |
| 日志/执行 | `sudo crictl logs --tail=100 <cid>` / `sudo crictl exec -it <cid> sh`（容器得有 sh） |
| 看容器详情（拿 PID，§6.4 的桥） | `sudo crictl inspect <cid> \| jq '.info.pid'` |
| 镜像与磁盘 | `sudo crictl images` / `sudo crictl rmi --prune`（清未用镜像快照，对应 imageGC 不灵时） |
| 清理僵尸 | `sudo crictl rmp <pod-sandbox-id>`（Terminating 残留沙箱，配合 §6.1 Terminating 段） |
| 静态 Pod 起没起 | `sudo crictl ps \| grep kube-apiserver`（§3.2 已用） |

### 4.6 拿不准时：NPD 可能早就替你报过一遍

节点的内核/磁盘/运行时慢病，NPD 会以 NodeCondition/Event 形式先报上来（SystemLog/Stats/CustomPlugin/HealthChecker 四 daemon，第 7 章 §7.1）。排障期先问一遍 NPD：

```bash
kubectl get events -A --field-selector involvedObject.kind=Node,involvedObject.name=<node> --sort-by='.lastTimestamp' | tail
kubectl describe node <node> | grep -iE 'KernelDeadlock|ReadonlyFilesystem|KubeletReady'
```

之后的行动节奏（观察 5min → 决策 → drain → 修复/替换）直接沿用第 7 章 §7.3 自愈矩阵——尤其**控制面节点绝不自动 drain**。

---

## 五、域三：调度 Pending

### 5.1 四步排查链（完整引用第 2 章 §7.3，不重讲）

`kubectl describe pod` 读 FailedScheduling 聚合 → 调度器指标（:10259，**不在 apiserver /metrics**）看 pending 四档 → `--v=5` 日志逐插件对齐 → 插件级确认 `scheduler_unschedulable_pods`——第 2 章 §7.3 已给照抄命令，本章不再抄。读 events 的「每类插件失败聚合一次、数字是被判负的节点数」口诀也在那里。

本章只补第 2 章的两个**边缘 CASE**——生产里真正让人怀疑人生的两类 Pending。

### 5.2 边缘 CASE 1：调度系统本身病了（Pod 大面积 Pending，但 events 安静）

特征：**`FailedScheduling` 事件干净得不正常**（Pod 连「被拒绝」都没有）。判读链：

```bash
# ① scheduler 本体现状（kubeadm 形态：静态 Pod；托管形态找对应组件）
kubectl -n kube-system get pods | grep kube-scheduler
sudo crictl ps | grep scheduler        # 控制面节点上，确认进程真的在
sudo journalctl -u kubelet --since '30m ago' | grep -i scheduler | tail -20

# ② 谁在当 leader、lease 是不是在陈化（多 scheduler 副本/升级卡住场景）
kubectl -n kube-system get lease | grep -E 'kube-scheduler|NAME'
kubectl -n kube-system get lease kube-scheduler -o jsonpath='{.spec.renewTime}{"\n"}'

# ③ 调度器自己在不在做决定（指标；切记走 :10259）
kubectl -n kube-system port-forward <kube-scheduler-pod> 10259:10259 &
curl -sk https://127.0.0.1:10259/metrics | grep -E 'scheduler_schedule_attempts_total|scheduler_pending_pods'
# schedule_attempts_total 长时间不涨 = 调度循环停摆（QueueingHints 失联 / leader 僵尸 / stuck watch）
```

QueueingHints（v1.34 GA；第 2 章 §1.5）把「任意集群事件都唤醒 Pod」收严成「插件声明的事件才唤醒」——代价是极端场景下**上游插件声明不全/事件丢失时 Pod 可能长期滞留 unschedulableQ**。生产识别点：这个 Pod 本来「理论上调得动」，但 `FailedScheduling` 与指标都不动；处置的最低成本动作是**把 kube-scheduler 静态 Pod 重启一次**（清单文件移走-等 20s-移回，第 7 章 §5.2 同款三件套；让它清空队列重新 list），其次 `kubectl delete pod <pending-pod>` 让控制器重建新对象重新入队（注意：annotate 改标签不是移队信号，别指望它）。

### 5.3 边缘 CASE 2：明明有空闲节点但不调（单 Pod 无动静）

三个真实存在、却完全不出事件的「静默绕路」：

```bash
# a) .spec.nodeName 已被写死 → 调度器整个跳过（直绑/系统移植/故障演练产生的残留）
kubectl get pod <pod> -o jsonpath='{.spec.nodeName}{"\n"}'
#    非空 = 这就是 kubelet 的活而不是 scheduler 的活——看那台节点为什么拒绝（域二/域四）

# b) .spec.schedulerName 不是 default-scheduler，而那个调度器不存在/挂了
kubectl get pod <pod> -o jsonpath='{.spec.schedulerName}{"\n"}'
kubectl -n kube-system get pods | grep <that-name>   # 找不到 = 静默 Pending 的根因

# c) schedulingGates 没解（v1.30 GA；批调度/Kueue/自研控制器场景）
kubectl get pods   # STATUS 列直接显示 SchedulingGated
kubectl get pod <pod> -o jsonpath='{.spec.schedulingGates}{"\n"}'
#    门由写入方负责摘——看是哪个控制器打的 gate、它的 reconcile 为什么没跑完（第 6 章 Operator 视角）
```

另外两例「有空闲≠可用」的经典（有 event、算常规 Pending，但特别容易看错）：requests 算的是 allocatable 而不是物理空闲（`kubectl describe node` 看 Allocated resources 账本，不是 free）；`hostPort` 把每个节点变成单副本坑位（官方 debug-pods 页点名的 Pending 根因之一）；cordon/新加的 NoSchedule 污点没进 pod toleration（事件里的 `had untolerated taint` 行逐台对）。

> ❗ 调度域的通用弱点是「**以为有空闲物理资源就该调得动**」——K8s 只认 allocatable − requests（账本），不看 top 曲线（实况）。一句口诀：**Pending 看账本，慢才看实况**。

---

## 六、域四：Pod 与容器（最大篇幅）

### 6.1 生命周期症状词典（每个症状：首查命令 + 高频根因排序）

| 症状（STATUS 列） | 首查命令 | 高频根因排序（从上往下查） |
|------------------|---------|---------------------------|
| **ImagePullBackOff / ErrImagePull** | `kubectl describe pod <pod> \| sed -n '/Events/,$p'`；`kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].state.waiting.message}'` | ① tag/镜像名拼错或忘了 push（官方 debug-pods 三板斧：名字对？push 了？本机 `docker pull` 试）② registry 认证失败（imagePullSecrets 缺失/过期/namespace 放错）③ 仓限流（docker.io 匿名限额 429）④ 节点 egress 断/代理错（带代理集群）⑤ 国内 registry.k8s.io 可达性（mirror 配置，第 7 章 §2.4） |
| **CreateContainerConfigError** | `kubectl describe pod` 的 Events 会点名 | ① 引用的 ConfigMap/Secret 不存在（或 key 错，env 的 `valueFrom.*KeyRef`）② volumeMounts 名字与 volumes 对不上 ③ 引用的 ServiceAccount 不存在（SA 被误删后 Pod 照旧引用它）④ `resourceFieldRef`/`fieldRef` 路径写错 |
| **CreateContainerError** | `kubectl logs <pod> -c <c>`（大概率没日志）→ 节点上 `sudo crictl ps -a \| grep <name>` + `sudo crictl logs <cid>` + `sudo journalctl -u containerd --since '30m ago' \| grep <pod-name>` | ① OCI spec 层失败（镜像层损坏、`ImageVerify` 失败）② seccomp/apparmor profile 不存在或语法错 ③ mount 目标冲突/只读文件系统期望写挂载 ④ cgroups 层面异常（cgroup driver 不一致的余波，第 7 章 §2.3）⑤ 节点磁盘满拉不动层 |
| **CrashLoopBackOff** | 三连：`kubectl logs <pod> -c <c> --previous --tail=50` + `.lastState.terminated.reason` + `.exitCode`（exit code 词典见 6.2） | ① 应用自身崩溃（exit 1：配置错/依赖连不上/未捕获异常）② OOMKilled（exit 137，§4.4 A 类）③ liveness 探针过于激进（slow start 被当死，§6.5）④ 启动命令本身执行完就退（exit 0 的「假 CrashLoop」：主进程不是常驻）⑤ entrypoint 里 segfault（139）/命令不存在（127） |
| **Init 卡死：`Init:N/M` / `Init:Error` / `Init:CrashLoopBackOff`** | `kubectl logs <pod> -c <init-container-name>`（init 容器要 `-c` 指定）；`kubectl describe pod`（状态表引用官方 debug-init-containers 页：Init:N/M=完成 N 个共 M 个） | ① init 依赖的外部服务/DNS 没就绪（init 早于业务容器，探针也不跑）② init 里等 PVC/Secret 还没挂载好（卷在 init 前挂载，但内容源可能没供给完）③ init 脚本自身逻辑死循环 ④ native sidecar（`restartPolicy: Always` 的 init 容器，v1.29 β/v1.33 GA）的容器健康定义错——sidecar 不 Ready 业务容器永不启动 |
| **Running 但 READY 0/1（探针不过）** | `kubectl describe pod` 看 `Unhealthy` Warning；节点上 `curl -sS http://<podIP>:<port>/<path>`（从该 Pod 所在节点探测，把 kubelet 视角重演一遍）；`kubectl get endpointslice -l kubernetes.io/service-name=<svc>` 看在不在 ready 列表 | ① 探针 path/port 配错（改了应用没改探针）② 启动慢但没配 startupProbe，liveness 先杀人（§6.5）③ 应用 listen 在 127.0.0.1 而不是 0.0.0.0（容器内回环通、节点探测不通）④ readiness 依赖外部依赖拖慢（timeoutSeconds 默认 1s 极短）⑤ 容器端口与 Service targetPort 不匹配（表现为「探针过、Service 不通」——反而去 §七） |
| **Terminating 卡死** | `kubectl get pod <pod> -o jsonpath='{.metadata.deletionTimestamp}{"\n"}{.metadata.finalizers}{"\n"}'`；`kubectl describe pod` 看 Killing/事件 | ① finalizer 没人摘（控制器挂了/被删——第 1 章 §4.3 与第 6 章 §8）② webhook 挡 finalizer 摘除（官方 debug-pods 页：validating/mutating webhook 拦 UPDATE，则 finalizer 永远摘不掉，先查所有 webhook 配）③ 优雅退出被卡（preStop 阻塞/应用无视 SIGTERM，§6.5）④ 卸载卡死（NFS 僵死/挂载点 busy，§八）⑤ containerd shim 残留（节点 `ps aux \| grep containerd-shim \| grep <pod>`；`crictl rmp` 清沙箱或直接 kill shim）⑥ 节点本身失联（kubelet 停止上报时 Terminating 常挂） |

> ❗ 排障期保命诀：**`kubectl delete pod --force --grace-period=0` 只删 API 对象，不杀进程**——节点上容器可能还在跑。之后新 Pod 起不来往往是「老进程还吃着端口/文件锁/卷」；拿 PID 到节点上确认（`crictl ps -a`/`ss -tlnp`）才算完。

### 6.2 exit code 词典

| code | 含义 | 在 K8s 里的高频根因 |
|------|------|---------------------|
| 0 | 正常退出 | Job 完成是正常；Deployment 里的 Pod exit 0 = 主进程写错了（不是常驻服务） |
| 1 | 应用报错退出 | 配置/依赖/未捕获异常（看 --previous 日志最后一屏） |
| 126 | 命令不可执行 | entrypoint 文件没有可执行位（chmod +x 缺失）/Windows 脚本拷进 Linux 镜像（CRLF 行尾 + shebang 失效） |
| 127 | 命令不存在 | entrypoint/cmd 路径拼错、distroless 镜像被当 full 镜像用、shell 脚本 shebang 里命令没有 |
| 128+n | 死于信号 n | 137=128+9 SIGKILL；139=128+11 SIGSEGV；143=128+15 SIGTERM |
| **137** | SIGKILL 打死 | ① OOMKilled（lastState.reason 点名，§4.4 A 类）② liveness 杀（describe 事件 `Liveness probe failed`）③ 节点驱逐/管理员删 Pod（事件里 `Killing`，Reason `Evicted`） |
| 139 | 段错误 | 应用 bug/原生库问题（典型: JVM crash、C 扩展；看 logs --previous 与 core dump 设置） |
| 143 | SIGTERM 被打死 | 滚动更新/缩容/drain 的**正常**落幕——频繁出现且不该发生时，查探针触发重启策略或外部控制器在删 Pod |

配套：`.status.containerStatuses[].lastState.terminated.reason` 的常用值——`OOMKilled`（§4.4）/`Error`（非 0 退出的通名）/`Completed`（exit 0）/`ContainerCannotRun`（runtime 拒绝起，常与 6.1 CreateContainerError 同根）/`Evicted`（§4.3）/`DeadlineExceeded`（activeDeadlineSeconds 到期）。

### 6.3 kubectl debug 四形态全解（官方 debug-running-pod 页 + 命令参考页核实）

`kubectl debug` 的三种动作（官方 kubectl-debug 参考页原话）：workload 上「**复制一个改了属性的 Pod**」「**往运行中的 Pod 加 ephemeral 容器**」、node 上「**起一个跑在主机命名空间的新 Pod**」。再叠加 profile 档就成了「四形态」。

**形态 A：ephemeral 容器（原 Pod 不动，现场注入）**——Feature 自 **v1.25 Stable**（官方 ephemeral-containers 页）：

```bash
# 经典形态：给没工具的容器挂一个全家桶
kubectl debug <pod> -it --image=nicolaka/netshoot --target=<container-name>
# --target 指定共享哪个容器的进程命名空间（临时容器总在 Pod netns 里；
#   想 ps 看到业务进程就得 --target 或 Pod 开 shareProcessNamespace）
# 一次性命令版（排网络直接抓包，不用 -it 长驻）
kubectl debug <pod> --image=nicolaka/netshoot --target=<container-name> --profile=netadmin -- tcpdump -i any -nn 'port 53'
```

硬约束（官方 ephemeral-containers 页核实，背下来）：ephemeral 容器**不能有 ports、livenessProbe、readinessProbe、resources**（Pod 资源分配不可变）；**不能 kubectl edit 添加**（走特殊的 ephemeralcontainers 子资源处理器）；**加进去后不能改、不能单独删**（只能连 Pod 一起没）；**静态 Pod 不支持**（控制面四大件用不了这招——所以 §3.2 要走节点上 crictl）；**从不自动重启**（应当一次性工具用）；**--target 需要容器运行时支持**（官方注明：不支持时 ephemeral 容器可能起不来，或以独立进程命名空间起来——ps 看不到业务进程）。

**形态 B：copy Pod（改配置再造一个，不动原物）**：

```bash
# ① 最常用：把命令换成 sh，现场留着慢慢查（官方示例原样）
kubectl debug <pod> -it --copy-to=<pod>-debug --container=<container-name> -- sh
#    ★ 不带 --container 时，debug 是「往副本里新加 --image 的那个容器跑 sh」；
#    带 --container 才是「把那个已存在容器的命令换掉」——两个完全不同的对象，最容易混
# ② 换镜像（语法同 kubectl set image）：全部容器换 busybox
kubectl debug <pod> --copy-to=<pod>-debug --set-image=*=busybox
# ③ 换镜像 + 加调试容器组合（官方示例）
kubectl debug <pod> -it --copy-to=<pod>-debug --image=debian --set-image=app=app:debug
# ④ 进程共享（当前默认 true，可显式关）、探针削减（默认都剥掉 liveness/readiness/startup，显式 --keep-* 保留）、
#    删原 Pod（--replace，慎用）、钉回原节点（--same-node）、init 容器默认保留（--keep-init-containers，默认 true）
kubectl debug <pod> -it --copy-to=<pod>-debug --image=busybox --share-processes=false
kubectl delete pod <pod>-debug     # ★ 用完必删；副本不影响原 Pod（spec 快照）
```

**形态 C：node 调试（不用 SSH 上节点）**：

```bash
kubectl debug node/<node> -it --image=ubuntu
# 三事实（官方核实）：主机根文件系统挂 /host；容器跑在 host IPC/Network/PID namespaces；
# 但默认非 privileged——chroot /host 可能失败、部分进程信息看不了
chroot /host           # 失败就开 sysadmin 档重来
kubectl debug node/<node> -it --image=ubuntu --profile=sysadmin
# 生成的 Pod 名形如 node-debugger-<node>-<rand>，落在当前 namespace，用完记得删
```

**形态 D：profile 档（权限/sc 的预置包）**——命令参考页（v1.37 生成）核实：选项 `general / baseline / restricted / netadmin / sysadmin`，**默认 `general`**（教程页写的 `legacy` 是早期默认、计划弃用，docs 两边措辞不一致以命令参考页为准；`--custom=<file>` 自定义部分容器 spec，自 **v1.32 Stable**，不许改 name/image/command/lifecycle/volumeDevices，不支持改 Pod spec）：

| profile | 给什么 | 场景 |
|---------|--------|------|
| `general` | 一组通用安全默认 | 日常（默认） |
| `baseline` / `restricted` | 对齐 PSS baseline/restricted | 高合规集群里 Debug 仍会被 PSA 放行 |
| `netadmin` | 加 NET_ADMIN 能力 | 抓包（tcpdump/iptables 读写） |
| `sysadmin` | privileged（全能力） | 节点调试根因层（strace/挂载/chroot） |

```bash
# 抓包经典组合：netadmin 档 + netshoot，目标 Pod 的 netns 里直接 tcpdump
kubectl debug <pod> --image=nicolaka/netshoot --profile=netadmin --target=<c> -- tcpdump -nn udp port 53
# sysadmin 档验证（官方示例的两步）：
kubectl get pod <pod> -o jsonpath='{.spec.ephemeralContainers[0].securityContext}'
#   {"privileged":true}
# （注：目标 Pod 整体配了非 root runAsUser 时，profile 给的部分能力可能不起效——命令参考页原话）
```

**推荐调试镜像与一句话场景**：

| 镜像 | 场景 |
|------|------|
| `busybox`（或 `busybox:1.28`） | 极简 shell、nslookup/nc/wget；「我只需要进去看一眼」首选 |
| `nicolaka/netshoot` | 网络全家桶（dig/tcpdump/iperf/mtr/conntrack/nmap/curl/jq 都有）——域五默认 |
| `registry.k8s.io/e2e-test-images/dnsutils:1.3` | 官方 DNS 排障镜像（glibc；**而 alpine/musl 的 nslookup 不会 TCP 回放、search 行为不一致**——第 3 章 §5.5 点名的坑，排 DNS 别用 alpine 系） |
| `curlimages/curl`、`ghcr.io/jqlang/jq` 等单工具镜像 | 供应链管控严的集群：单功能镜像好过全家桶 |

> ❗ **易错点四连**（本章点名的）：① **命令对象是不同形态**：`kubectl debug <name>` 猜 pod；`kubectl debug node/<name>` 是集群级对象——node 形态不吃 `-n`，生成的调试 Pod 落当前 ns（稍不留神就以为「我看错了 namespace」）。② **崩溃的容器与 ephemeral 容器是两个对象**：业务容器 CrashLoopBackOff 照样能挂 ephemeral 容器（它站 Pod 沙箱层）；但 **Pending Pod 连沙箱都没有，ephemeral 挂不上**——此时别硬挂，用 `--copy-to` 造副本验证（调度之事先回域三）。③ **已退出/超时的容器不能 `kubectl exec`、也轮不到 ephemeral 去「救」它**——`exec` 只打 Running 容器；要看「死掉那一刻」靠 `logs --previous`（容器重启过才有内容）或 `--copy-to` 改命令复现。④ **events 是 namespaced 对象**（官方 debug-pods 页原话）：Node 这种集群级对象的事件落在 default 等 ns——`kubectl get events` 不加 `-A` 默认看不到，排节点故障时这是最常见「明明有事件却搜不到」的原因。

### 6.4 nsenter 节点级绝招（容器里什么都没有也能排）

ephemeral 容器能解决「没工具」的 90%，但三种场景它进不去：镜像仓挂拉不动调试镜像、ephemeral 被 admission 策略挡、**需要宿主机视角与容器视角对照**。nsenter 是不依赖 K8s 的底层手段（util-linux 自带）：

```bash
# ① 到节点（三种形态）
#    L2 实验节点（multipass）：  multipass shell k8s-w1
#    kind 沙箱节点：           docker exec -it <kind-node-name> bash
#    生产：                   ssh / 或通过形态 C 的 kubectl debug node
# ② 拿目标容器 PID（crictl inspect 的 info.pid）
cid=$(sudo crictl ps | grep <pod-name> | awk '{print $1}')
pid=$(sudo crictl inspect $cid | jq -r '.info.pid')
# ③ 在那个容器的网络命名空间里，跑【宿主机的】工具——容器里没带任何工具照样排
sudo nsenter -t $pid -n ip addr          # 容器视角的网卡
sudo nsenter -t $pid -n ip route         # 容器视角的路由（默认网关应指向 CNI 桥/隧道端）
sudo nsenter -t $pid -n ss -tlnp         # 容器里到底在监听什么
sudo nsenter -t $pid -n curl -sS -m 3 http://127.0.0.1:8080/healthz   # 以容器 TCP 栈看服务
sudo nsenter -t $pid -n tcpdump -nn -i any udp port 53                # 容器视角抓包（节点事先装好 tcpdump）
# ④ 其他 namespace 变体：-m 挂载命名空间（看容器看到的挂载表）；不切换 ns 时
#    /proc/<pid>/root/ 直接就是该容器根文件系统（读配置/日志零成本）
sudo nsenter -t $pid -m mount | head
sudo ls /proc/$pid/root/etc/ | head
```

> ★ 心智模型一句话：**nsenter 是「把宿主机的工具借到容器的世界里跑」**——所以容器再 distroless 也不怕；坏处是完全绕过 K8s 层的审计（操作只留在 shell history，入 runbook 时要主动记账）。
>
> ❗ 别混：`nsenter -t $pid -n <cmd>` 是**切换 netns 后跑宿主机二进制**（所以宿主机得有 tcpdump/curl），而不是「进容器里跑容器里的工具」。想用容器里的工具且容器有 shell，直接 `kubectl exec` 才是正道。

### 6.5 探针与优雅退出时序排障

Pod 删除时刻的真实时序（官方 pods 生命周期 + 第 1 章 list-watch 链合起来的结论——两条线**并行**启动，不是串行）：

```
DELETE /pods/<pod>（或 rollout 触发的新版替换）
  ├─A 线（endpoint 摘除）：deletionTimestamp 打上 → endpoint controller 把 IP 从
  │   Endpoints/EndpointSlice 移入未就绪/移除 → kube-proxy/ingress 更新数据面 → 流量摘除
  │   （这走得是 API→kube-proxy 的链，有秒级传播延迟）
  └─B 线（容器终止）：kubelet 看到删除意图 → 执行 preStop（如有，同步阻塞）→
      SIGTERM → 等 terminationGracePeriodSeconds（默认 30s）→ SIGKILL 兜底
        （A 与 B 几乎同时起步；B 内任一环节超窗都会被 SIGKILL 一刀切）
```

三类生产高发「删 Pod 引发的事」：

| 现象 | 根因链 | 排查与处置 |
|------|--------|-----------|
| 优雅退出期间还在丢流量 | B 线 SIGTERM 发得比 A 线摘 endpoint 快——Pod 已开始关连接，Ingress/kube-proxy 还在派新单 | 主张加 `preStop: exec: {command: ["sh","-c","sleep 5"]}`（给 endpoint 传播留窗）或入口侧 drain 配置；查法：`kubectl get pod -o yaml \| grep -A3 preStop` + 对照 Ingress 后端摘除时间线 |
| Terminating 挂死好几小时 | preStop 脚本阻塞 / 应用装了 SIGTERM handler 但不退出 / terminationGracePeriodSeconds 被写成 3600 | `kubectl get pod -o yaml \| grep -A4 terminationGracePeriodSeconds`；审计查 delete 调用方（第 1 章 §8）；软的不行上节点：`crictl stop <cid>` 或 `kill -9 <主进程PID>`，kubelet 观察到进程退出后会自己走完删除收尾 |
| 「改了配置没生效」慢慢排查 | rollout 后被新版替换中；但 preStop 阻塞卡住旧 Pod——新旧各跑一半，看似改一半 | `kubectl rollout status` 明确定位卡在哪个 revision；`kubectl get rs` 看新旧并行期；§6.1 Terminating 表前五项逐条排 |

探针参数默认值（kubelet 默认，官方 configure-liveness-readiness-startup-probes 口径）：`initialDelaySeconds=0`、`periodSeconds=10`、`timeoutSeconds=1`、`successThreshold=1`、`failureThreshold=3`。排「Running 但探针不过」时**timeoutSeconds=1 是最大暗坑**（响应超过 1s 就算失败——延迟敏感的应用必须显式调大；startup probe 的存在价值正是保护慢启动期，别让 liveness 在预热时杀人）。更深的设计权衡（三种探针怎么组合、sidecar 配合）见 `K8s-Pod生命周期详解.md` §五/§七，这里不重复。

### 6.6 「挂了重启无人知」：重启现场的留证链

容器重启后现场刷新：stdout 被打断、`--previous` 只在「重启过」时有内容、节点重启/镜像 GC 后 `--previous` 也可能被收走（排障进阶笔记 §三坑点）。现场三件套：

```bash
kubectl logs <pod> -c <c> --previous --tail=100 > /tmp/prev.log        # 直接存盘别只看
kubectl get pod <pod> -o json > /tmp/pod-state.json                    # 全量状态（含 lastState/reason/exitCode）
kubectl get events -n <ns> --field-selector involvedObject.name=<pod> --sort-by='.lastTimestamp' > /tmp/pod-events.txt
```

根治永远是把 stdout + 关键日志接入集中式日志（Loki/ES）——本地 stdout 只是应急通道（排障进阶笔记结尾同款告诫）。

---

## 七、域五：网络与 DNS

### 7.1 逐跳定位法（一条命令一跳，每跳给判定标准）

```
客户端 Pod ──①──► 同节点 Pod ──②──► 跨节点 Pod ──③──► Service(ClusterIP)
                 通?              通?              通?
                                                       │
                  ④ EndpointSlice 里它在不在 ◄───────────┘
                  ⑤ 后端 Pod 直接 IP:port 通吗
                  ⑥ 出网（egress）/入网（ingress 入口）两端的网络边界
```

逐跳工具与判定标准（先记两条黄金：**`connection refused` = 三层通到了、四层没人监听；`timeout` = 半路被丢**——这是二分网络故障的最锋利一刀）：

| 跳 | 工具（任选一即可，netshoot ephemeral 默认） | 判定标准 |
|----|------------------------------------------|---------|
| ① 同节点 Pod | `kubectl debug <client-pod> --image=nicolaka/netshoot -- curl -sS -m 3 http://<peerPodIP>:<port>` | 通：本机 veth/桥正常 → 问题在跨节点或 Service 层；不通：本节点 CNI/桥或 peer 容器自身（回域四确认它在监听） |
| ② 跨节点 Pod | 同上换目标 PodIP | 不通 + ①通 ⇒ overlay/路由层：`ip route get <dst-podIP>`（在源节点上跑）看下一跳是否符合 CNI 预期（flannel.1 / cilium_host / cali*） |
| ③ Service ClusterIP | `curl -sS -m 3 http://<clusterIP>:<svcport>` | 拒绝：Service 层规则在（可能是 endpoint 空/端口错）；超时：kube-proxy/数据面规则异常 → 节点上查规则（下） |
| ④ endpoints | `kubectl get endpointslice -l kubernetes.io/service-name=<svc>`（官方 debug-service 页推荐路径） | 期望的 Pod 都在？`ready` 字段是 true？selector 漂移（svc selector vs pod labels 对不上=空 endpoints，高发） |
| ⑤ 后端直达 | 绕过 Service，直接 `curl <podIP>:<containerPort>` | 通：问题 100% 在 Service 面（③④）；不通：回域五②或容器本身没在监听（`nsenter -t $pid -n ss -tlnp`） |
| ⑥ 出网/入网 | egress：`curl -m 5 -sS https://<识别外部端点>`；ingress：从集群外 curl | egress 断：网络出口 SNAT/ELB/代理；ingress 断：LB 探针/Ingress 控制器（第 7 章 §4.4 的「探针必须打 /readyz」同款教训） |

节点侧 Service 规则验证（kube-proxy 系集群；Cilium 换 `cilium service list`/`cilium bpf lb list`）：

```bash
sudo iptables-save | grep -E "KUBE-SVC|<clusterIP>" | head      # iptables 模式：链在不在
sudo ipvsadm -ln | grep -A3 <clusterIP>                          # ipvs 模式：虚拟服务与 real server
kubectl -n kube-system logs ds/kube-proxy --tail=100 | grep -Ei 'error|setting endpoints' | tail
# DNS/Service 都正常但还不通 → 抓包三段论展开（7.2）
```

官方 debug-service 页的清单顺序（svc 存在？→DNS 名？→IP 直连？→endpointSlices？→后端 Pod？→kube-proxy？→hairpin 特例）已覆盖 90%；本章的独特增量是给每一跳绑定「**refused/timeout 二分判定**」与节点侧验证条目。

### 7.2 tcpdump + conntrack 组合技

拆包三段论（两端同时抓）：**客户端是否发出 → 服务端是否收到 → 回复是否返程**。

```bash
# A 端（客户端 Pod 的 netns）：
kubectl debug <client> --image=nicolaka/netshoot --target=<c> --profile=netadmin -- \
  tcpdump -i any -nn "host <dst> and (tcp or udp)"
# B 端（服务端节点）：
sudo tcpdump -i any -nn "host <client-podIP>"
# 判读：发出≠收到 → 中间丢（路由/policy/MTU/overlay）；收到但服务端没回 → 应用/policy 在 B 侧丢；回了但 A 没收到 → 回程路径问题（conntrack/SNAT）
```

conntrack 是 UDP/DNS/短连接时代最大的暗伤（第 3 章 §4.6 已给机制）：

```bash
# 现状一眼
sudo conntrack -C                                   # 当前条目数
cat /proc/sys/net/netfilter/nf_conntrack_max        # 表上限
sudo dmesg -T | grep -i 'nf_conntrack' | tail       # "table full, dropping packet"——满表铁证
sudo conntrack -S | head                            # found/insert/insert_failed/early_drop/drop 各项增速
# 临时缓解：调大表（同时评估内存：每条 ~几百字节）
sudo sysctl -w net.netfilter.nf_conntrack_max=1048576
```

症状画像：间歇性 UDP DNS timeout、短连接 TCP 偶发 SYN 无回、长连接却稳——满表先丢新流，老连接看起来「岁月静好」。实验 8.3 就在 L2 集群上亲手复现它。

### 7.3 CoreDNS 全域超时与 ndots（三板斧引用 + 两个 mini 案例）

三板斧（①明文解析验证与耗时、②CoreDNS 指标/日志/上游、③直查 CoreDNS PodIP 与尾点 dig）完整命令照抄第 3 章 §5.5，这里不重复。补第 3 章没展开的两个 **ndots 特殊故障模式**：

**mini 案例 A：外部域名解析「慢但没死」，高峰期把 CoreDNS 上游压垮**

- 症状：应用调 `api.partner.io`（2 个点 < ndots:5），首次解析 ~100ms+，偶发 SERVFAIL；`coredns_dns_requests_total{type="NXDOMAIN"}` 斜率陡增。
- 机理：`options ndots:5` 默认（官方 debug-service 页 resolv.conf 示例即此）——少于 5 点的名字先去 `default.svc.cluster.local`→`svc.cluster.local`→`cluster.local`→自定义 search 各展开一遍（最多 4~6 次 NXDOMAIN）再原生解析；每 NXDOMAIN 还会吃负缓存。
- 判定：抓 DNS 包看展开序列（`tcpdump -nn udp port 53`；或 CoreDNS 日志 plugin errors/log 级别能看到 qname 序列）。
- 处置三选一：应用侧把外部域名写成**尾点 FQDN**（`api.partner.io.`，直接跳过 search 展开）；Pod `dnsConfig.options: [{name: ndots, value: "2"}]`（改成「两点内就算 FQDN」）；dnsPolicy 局部收窄 `dnsConfig.searches`。

**mini 案例 B：search path 顺序劫持，把短名解析到「幻影主机」**

- 症状：应用连 `redis` 本应进集群，结果连上的是公司内网一台同名主机（`redis.corp.example.com`）——认证错/连上但数据怪，排查绕一大圈才发现连的根本不是集群里的。
- 机理：Pod `dnsConfig.searches` 自定义了公司域、或 kubelet `resolvConf` 带的 search 把 corp 域排在 `cluster.local` 之前 → dns 解析按 search 顺序试，先在 corp 域命中了真主机。
- 判定：`nsenter -t $pid -n cat /etc/resolv.conf` 看 search 顺序；`getent hosts redis`（glibc 视角，比 dig 更接近应用）看解析走了哪条。
- 处置：集群内服务引用一律写短名对应的规范形式（跨 ns 写 `<svc>.<ns>` 或全限定）+ `dnsConfig.searches` 收敛；公司域必须由本集群 DNS 出（CoreDNS 加 `template` 或公司在集群内的 split DNS），别依赖 search 顺序巧合。

### 7.4 NetworkPolicy 静默放行的快速判定

「该断的没断」比「该通的没通」更难发现——NetworkPolicy 对象的样子正常 ≠ 数据面生效（第 3 章 §6.5：不支持的 CNI = 安全负债）。快速判定三连：

```bash
# ① CNI 是什么，enforce 能力有没有
kubectl -n kube-system get ds | grep -E 'cilium|calico|flannel|kube-router'
#    Flannel 原生不 enforce（第 3 章 §6.3 表格）；Cilium/Calico 完整支持
# ② 实弹测试（非生产 ns 先）：一份 default-deny + 一个探测 Pod——探测目标走四层 nc
kubectl apply -n <test-ns> -f - <<'EOF'
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: { name: probe-deny-all }
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
EOF
kubectl run probe -n <test-ns> --rm -it --image=busybox --restart=Never -- \
  nc -zvw2 10.96.0.1 443                                # kubernetes.default 的 ClusterIP
#    结果对照：nc 成功连上 = deny 没被执行（CNI 不支持/未开启）→ 回第 3 章 §6.3 选型与补偿方案；
#             nc 超时/被拒绝 = 策略生效（说明执行面在，去查具体白名单规则）
kubectl delete networkpolicy probe-deny-all -n <test-ns>
# ③ 有观测面的 CNI 直接看判决（Cilium 首选）
cilium monitor -t policy-verdict | head     # DROP/REDIRECT 与 policy 名一行一条；或 hubble observe --verdict DROPPED
```

❗ 探测别用 `ping <ClusterIP>`——kube-proxy 不为 ClusterIP 转发 ICMP，**策略生不生效 ping 都不通**，假阳性。探测一律走四层（nc/curl）。

「该通的被 policy 断了」的反向排查：Pod 描述里 `kubectl describe pod` 不会提示 NetworkPolicy——`--field-selector` 也不支持按 label 查 policy，改用 ns 维度列：`kubectl get netpol -n <ns>` + `kubectl describe netpol` 对照 podSelector/pod labels；NodeLocal DNS/ClusterIP 记得在 egress 白名单里（第 3 章 §6.1 易踩点表）。

### 7.5 MTU 黑洞：「小包通、大包卡」症状表

| 症状 | 为何像 MTU |
|------|-----------|
| ping/ssh 握手通，传大文件卡死 | 小包不分片自由穿，大包撞上 DF=1 + 中间链 PMTUD 断（ICMP 被丢） |
| TCP 三次握手 OK、TLS 握手却卡 | ServerHello(带证书) 是大包，先丢这一发 |
| HTTP 小响应通，大 body 卡半途中断 | 同上：data 段首超 MTU 的包无回音 |
| DNS（UDP 小包多）正常，HTTPS/大 API 全卡 | UDP 短包不过限，长 TLS/HTTP 全靠 TCP 大包 |
| overlay 集群独有，裸机直连正常 | VXLAN/Geneve 头（~50B）未从 MTU 里扣（第 3 章 §3.5 各 CNI 默认表） |

现场二分：

```bash
# 从源节点到目标节点逐步降包，看哪一档开始通（Linux：-M do 禁止分片）
for s in 1400 1420 1440 1460 1472; do ping -M do -s $s -c1 -W1 <dst-node-ip> >/dev/null 2>&1 && echo "size $s OK" || echo "size $s FAIL"; done
# 1472 = 1500 MTU 下 ICMP 载荷的最大值（+20 IP +8 ICMP）；找到可通过的最大值 +28 即有效 MTU
```

修复：CNI mtu 参数对齐「物理链路 MTU − 封装头」（例：物理 1500 + VXLAN → Pod 网 1450）；云主机巨型帧（9001）与隧道混用时尤其要算；改完用同一脚本复测写进 runbook。

---

## 八、域六：存储

### 8.1 PVC Pending → 挂载失败 → IO 慢 决策链

```
症状分四类，先分开再合并：
  A. PVC Pending（卷没造出来）
  B. Pod ContainerCreating 挂（卷造出来了，attach/mount 没完成）
  C. Pod 起来了但 IO 慢/报错（挂载成功但数据面问题）
  D. PVC/PV 对象删不动（回收侧问题）
```

| 类 | 首查 | 高频根因排序 |
|----|------|-------------|
| **A：PVC Pending** | `kubectl describe pvc <pvc>` 的 Events；`kubectl get pvc <pvc> -o jsonpath='{.status.phase}'` | ① StorageClass 不存在/名字拼错 ② provisioner 挂了（CSI controller 组件 Running 吗：`kubectl -n <csi-ns> get pods`） ③ 配额/容量不足 ④ 静态 PV 无匹配（accessModes/size/selector/storageClassName 五要素对照，第 4 章 §2.2） ⑤ WaitForFirstConsumer 设计如此（没 Pod 不来供给——**它不是故障**，第 2 章 §5.1） |
| **B：挂载失败** | `kubectl describe pod` 看 `FailedMount`/`UnableToAttachOrMount`/`MountVolume.SetUp failed`；缺 PVC 时 event 直接报 `persistentvolumeclaim "x" not found` | ① multi-attach（下 8.2） ② CSI node 插件挂了（该节点上 CSI DaemonSet 不健康） ③ NodeStage/NodePublish 报错（格式坏/凭据错/目标目录冲突） ④ Pod 引用的 PVC 不存在/未 Bound（属卷引用错——不是 config 层错误，别和 §6.1 ConfigError 混） ⑤ disk 没在云侧 attach 成功（云 API 配额/zone 不匹配） |
| **C：IO 慢/报错** | Pod 内 `dd`/`fio` 基线 + 节点 `iostat -x 1` + CSI 指标 | ① 卷档位不够（突发额度用完——VolumeAttributesClass 换档，第 4 章 §2.9） ② 节点网络盘丢包（NFS/Ceph：网络域先回 §七） ③ 单盘热点（local PV：iostat 里 `%util` 100） |
| **D：PVC/PV 删不动** | `.metadata.finalizers` | ① `kubernetes.io/pv-protection`/`kubernetes.io/pvc-protection`（使用中保护，正常）② external-provisioner 的 finalizer（HonorPVReclaimPolicy 引入——后端删除没完成它不会摘）③ PV Released 而 reclaim 卡住（provisioner 挂了） |

> 主表（症状→指标→修复的 10+ 条目）完整引用第 4 章 §7 生产问题清单——本段只做「先分 ABCD 再进哪一项」的路由，不重复表格。

### 8.2 multi-attach 快速判定与处置

经典报错：`Multi-Attach error for volume "<pv>" Volume is already exclusively attached to one node and can't be attached to another`。

```bash
# ① 一眼看 attach 真相（cluster-scoped 对象）
kubectl get volumeattachment | grep <pv-name>
kubectl describe volumeattachment <va-name>     # Attached=true 且 Node 指向旧节点 = 实锤
# ② 旧节点真死了吗（决定处置胆量）
kubectl get node <old-node>
# 旧节点 NotReady/失联 → 等 attach-detach controller 的超时窗（云盘常 6 分钟左右漂，第 7 章 §9.3）
# ③ 紧急处置（确认旧节点真的回不来/盘上无在写 IO 后）：
kubectl delete pod <stuck-pod>          # 先清 Pod 引用
kubectl delete volumeattachment <va-name>   # ★ 触发立即 detach——数据权属必须人工确认后
```

❗ 数据安全三确认再动手：旧节点不是「分区中还在写」（网络分区 vs 宕机，域二判读）、平台没有对这块盘的在途快照/迁移、Pod 侧业务是高可用的。RWO 云盘漂的时间窗是「常态延迟」，别把它当故障修（第 7 章 §9.3）。

### 8.3 mount 残留与 NFS 僵死处置

卸载卡死的形态（Terminating 挂死 §6.1 的存储分支）：

```bash
# ① 节点上看卷挂载真相
sudo findmnt -R /var/lib/kubelet/pods/<pod-uid>/volume-subpaths 2>/dev/null
sudo findmnt | grep <pv-or-pvc-name>
# ② 卸载卡住的硬证据：D 状态进程 + dmesg
ps aux | awk '$8 ~ /^D/ {print}'                        # 僵在 IO 上的进程
sudo dmesg -T | grep -iE 'stale|nfs|timed out|mount' | tail
sudo umount -f -l /var/lib/kubelet/pods/<uid>/volumes/*/<vol>   # 强制+懒卸载（-l 让内核情景卸载，清引用）
#    仍残留 → systemctl restart kubelet 让它重扫挂载树（业务最低损）
```

NFS 特定注意：服务端重启/网络抖 → 客户端默认 `hard` mount 的 IO 无限等（D 状态成片）。挂载参数建议（第 4 章 §1/§2 讨论面）：`soft,timeo=XX,retrans=X` 换取超时返回错误；或者容忍僵死但**runbook 里写明「NFS 服务端不可用期间禁止重启客户端节点」**——重启会让 umount 顺序把它拖进更深的 D 状态。

---

## 九、域七：证书与 TLS

### 9.1 x509 症状词典（报错原文 → 首查 → 高频根因）

| 报错原文（截特征段） | 首查 | 高频根因（排序） |
|---------------------|------|-----------------|
| `certificate has expired or is not yet valid` | `openssl x509 -in <crt> -noout -dates`；`kubeadm certs check-expiration` | ① 真过期（叶证 1 年，第 7 章 §5.2） ② **not yet valid = 时钟漂**（chrony 挂了/VM 恢复快照，第 7 章 §2.5） ③ 用错文件（拿了旧备份） |
| `certificate signed by unknown authority` | `openssl x509 -in <crt> -noout -issuer` vs 信任的 CA 文件是哪个 | ① kubelet serving 自签（kubeadm 默认，第 7 章 §5.3——metrics-server/`kubectl logs` 报这个的经典源） ② 客户端带的 CA 与服务端签发 CA 不是同一把（多套 CA 混） ③ webhook/APIService `caBundle` 缺失或过期 |
| `cannot validate certificate for <IP> because it doesn't contain any IP SANs` / `x509: certificate is valid for A, B, not C` | `openssl x509 -in <crt> -noout -ext subjectAltName` | ① SAN 没覆盖现在访问的形态（新增了 LB FQDN/VIP/hostname alias） ② 用 IP 直连而证只有 DNS SAN ③ SNI 与证书 hostname 不匹配 |
| `tls: bad certificate`（服务端日志；客户端常只见到 EOF） | 服务端组件日志里带 x509 reason；双向看 | ① 客户端证书被服务端 CA 不认 ② 客户端证书过期（自轮转断链，kubelet 侧 → §4.1 ④） ③ 中间链缺 |
| `certificate relies on legacy Common Name field, use SANs or ...` | 同上 `-ext subjectAltName` | 老 CA/手工签的证只有 CN 没有 SAN——现代 Go 客户端直接拒；重签带 SAN 的证 |
| `unknown certificate authority`（出现在组件间调用） | 两端 CA 文件 diff | front-proxy 聚合层证书链（第 7 章 §5.1 家谱第三把 CA）旋转后没同步（metrics-server/custom-metrics 典型） |

### 9.2 速查命令组

```bash
# 看证书本体（本地文件）
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -subject -issuer -dates
openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -ext subjectAltName
# 在线看服务端（SNI 必须带对；</dev/null 防止阻塞）
openssl s_client -connect 10.0.0.11:6443 -servername k8s-cp1 </dev/null 2>/dev/null | \
  openssl x509 -noout -subject -issuer -dates -ext subjectAltName
# web 类（Ingress 域名）同款
openssl s_client -connect <ingress-ip>:443 -servername api.example.com </dev/null 2>/dev/null | openssl x509 -noout -dates -subject
# 看握手全流程与链（调试 unknown authority）
openssl s_client -connect <ip>:<port> -servername <sni> -showcerts </dev/null 2>/dev/null | grep -E 's:|i:'
# kubeadm 集群证书账
sudo kubeadm certs check-expiration
# Ingress TLS Secret 内容（确认 cert/key 一对、未截断）
kubectl get secret <tls-secret> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates -subject
# 集群里还有哪些 CSR 在等
kubectl get csr
```

### 9.3 修复与轮转的衔接（引用不重复）

- **kubeadm 叶证过期/签错**：`kubeadm certs renew <name>` + 静态 Pod 重启三件套（manifests 移走-等 20s-移回）——全套在第 7 章 §5.2；**renew 以旧证书的 CN/O/SAN 为准**，改 SAN 要先改 `ClusterConfiguration.apiServer.certSANs` 再 renew（第 7 章 §1.4 样例）。
- **CA 根轮换**：11 步手册在第 7 章 §5.4（bundle 先行 → 全 Pod SA token 重读 → 换证 → 全 rollout → 清旧 CA）；触发只限「泄漏/合规/算法更换」。
- **Ingress TLS**：换 Secret 即可（`kubectl create secret tls <name> --cert=... --key=... --dry-run=client -o yaml | kubectl apply -f -`），主流 controller 自动热加载；切换前用 9.2 的 s_client 命令验证握手。
- **webhook/聚合层 caBundle 漂移**：`kubectl get validatingwebhookconfigurations <name> -o jsonpath='{.webhooks[0].clientConfig.caBundle}' | base64 -d | openssl x509 -noout -dates`——和证书管理器（cert-manager 的 `caInjector` 或你自研注入器）对账。
- **企业/国密链** 用 kubeadm external CA 时，`EXTERNALLY MANAGED=yes` 的证书 kubeadm 不管（第 7 章 §5.2），企业 PKI 侧的续期窗口要自己纳管进日历告警。

> ❗ 时间前提重申：**所有「not yet valid」与周期漂移类证书问题，先查 chrony**——证书域 80% 的诡异报错是时钟先错的衍生品（第 7 章 §2.5）。

---

## 十、事故复盘文化

### 10.1 SRE 风格 timeline 模板（写完才算事故结束）

复盘的范本就在仓库里：`安全/挖矿木马入侵排查与清除实录.md`——它的四个亮点值得照抄：**时间戳反推**（入侵窗口是靠 `find -newermt` 的时间聚集推出来的）、**IOC 附录**（证据单独成表，横向扫描命令可直接复用）、**检测信号总结**（「下次直接套」的 5 条）、**原则先行**（「手工清杀仅为止血；root 失陷过的机器只有重装才算干净」）。K8s 事故按同一体裁写：

| 项目 | 内容写法 |
|------|---------|
| 触发/发现 | 告警名与触发时间 vs 用户报障时间（差值 = 监测盲区） |
| 影响面 | 域（§三~§九）× 受影响 ns/Pod 数 × 时长 |
| Timeline | 分钟级：变更点→首症状→诊断路径（**含走过的弯路**）→止血→根治→验证 |
| 根因 | 一句话能说清的「哪个控制循环为什么没 reconcile」 |
| 止血 vs 根治 | 分开记（止血动作是否需要回滚要标明） |
| 经验 | 检测信号、runbook 链接（归档实验 8.1 后方或独立 runbook 库）、是否需要补监控/补演练 |

第 7 章 §9.4 给破坏演练定的「三行规则」同样适用真实事故：①事故前最近的一份快照/备份是什么、②事故中 `kubectl get --raw=/readyz?verbose` 与 `kubectl get events -A` 各显示了什么、③恢复中哪个对象是最大因果。三行齐备，runbook 才成立。

### 10.2 mini 案例：apiserver 429 雪崩（capstone：APF × webhook 超时 × client 重试 三方共振）

- **初症状**：周二 10:04，全员 kubectl 开始报 `429 Too Many Requests`（带 Retry-After）；发布系统全线卡 Progressing。
- **时间线**：10:00 集群开始做节点滚动重建（例行补丁）→ 大批 kubelet/控制器同时重启 → 各组件 informer 首次 LIST 洪峰（第 1 章 §9.2）→ apiserver 队列水位冲高 → 同时段全部 admission webhook（failurePolicy=Fail、timeoutSeconds 各 10s）超时占座 → APF 按泳道开始拒绝。
- **走的弯路**：先扩容 apiserver 副本——LIST/WATCH 重连洪峰反而放大（弯路 30 分钟）；又怀疑 etcd 慢，查 `etcd_request_duration_seconds` 正常才回头。
- **根因**：三方共振——重启风暴（输入）× webhook 长超时占座（咽喉）× 自研 Operator 的客户端不尊重 `Retry-After` 硬重试（放大器），把 APF 各泳道打满。
- **止血**：临时把两个非关键 webhook 的 `failurePolicy` 改 `Ignore`（写请求瞬间恢复）；自研 Operator 降副本缩 QPS。
- **根治**：webhook timeoutSeconds 全部从 10s 调 3s 且 kube-system/系统 ns 显式排除；Operator 客户端升级 client-go 并移除自写重试循环；大维护窗口前把节点重建拆批（每批间隔 ≥ informer 同步完成观测）。
- **经验**：①429 在 APF 时代是**保护机制不是故障**（第 1 章 §9.3 watch cache 同理），先找谁在制造洪峰；②webhook 是 admission 链的「咽喉」，超时参数要按「救火时间」而不是「平时的 P99」设计；③任何「修控制面」的动作都会制造控制面输入，变更前先看 `apiserver_flowcontrol_rejected_requests_total` 基线。

### 10.3 mini 案例：CoreDNS 全域超时——conntrack 满表的那一个下午

- **初症状**：14:20 起，全集群报障「cluster.local 偶发解析失败」「出网 API 调用超时」，告警风暴 200+。
- **走的弯路**：先 rollout restart CoreDNS（好 5 分钟又坏——弯路 1）；查 CoreDNS forward 上游 114.114 正常（弯路 2）；差点怀疑 Cilium 数据面（方向错误，Hubble 看到包确实发出了）。
- **根因**：`dmesg -T | grep nf_conntrack` 在 3 台高流量节点上打出 `nf_conntrack: table full, dropping packet`——当天上线的批量 CronJob 每分钟产生数千条外部短连接（TCP + UDP DNS），conntrack 新 UDP 条目默认 30s 才老化（`nf_conntrack_udp_timeout`），表被打满后**新流（尤其 DNS UDP 包）被静默丢弃**。
- **止血**：3 台节点 `sysctl -w net.netfilter.nf_conntrack_max=2097152`（临时从 26 万提到 200 万），丢包即刻停。
- **根治**：① 常态化调大 max + 监控 `conntrack -S` 的 `early_drop/insert_failed` 告警；② CronJob 客户端改连接复用（HTTP keepalive）批量收敛；③ 上 NodeLocal DNSCache（第 3 章 §5.4）把 DNS 从 UDP 短连接的雷区里搬出去。
- **经验**：① **D 类疑难先跑 dmesg**——节点层真相很少出现在 kubectl 视角；② UDP 受害先于 TCP（TCP 长连接是「老流」被保护，UDP 新短流是满表的第一批弃儿）；③ 「间歇性」是 conntrack 类问题的招牌画像（表满只打新流，已有的连接一切正常）。

### 10.4 mini 案例：「PV 删了居然真删了」（HonorPVReclaimPolicy 背景，呼应第 4 章 §2.8）

- **初症状**：周四演练前清场——`kubectl delete pvc prod-data` 想「删掉让 SC 重新供给一份干净卷」；顺手把 Released 状态的 `kubectl delete pv pvc-9f3` 也删了「看着爽」。周末接告警：该业务数据丢失。
- **走的弯路**：先怀疑 Velero 备份坏（中彩票般的误判）；又怀疑云盘被别的系统回收。
- **根因**：集群刚升到 v1.37——`HonorPVReclaimPolicy`（v1.26 α → v1.31 β → v1.33 GA → v1.36 门控移除）在 v1.37 已是**不可回退的默认行为**（第 4 章 §2.8）：删除 Bound/Released PV 时，external-provisioner 认 PV 自己的 `reclaimPolicy`——这盘是 SC 默认的 `Delete`，provisioner 看门（finalizer）到位，**真把云盘删了**。而在老集群时代同样有 bug：手贱先删 PV 后删 PVC，reclaim 不跑，**盘泄漏**（账单默默涨）——那时「先删 PV」是无痛操作，肌肉记忆恰恰孵化于 bug 年份。
- **止血**：云平台的小时级自动快照找回 → 从快照建新盘 → 静态建 PV 重绑（第 4 章 §2.6 静态供给链）。RPO ≈ 1 小时数据损失。
- **根治**：①删除 PV/PVC 前 routine 动作：`kubectl get pv <pv> -o jsonpath='{.spec.persistentVolumeReclaimPolicy}'` 必查；要保数据先 `kubectl patch pv <pv> -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'` 再动对象。② 升级评审 checklist 增加「行为改变型 GA 特性」一栏（第 4 章 §2.8 这类「老误操作换义」的条目最高危）。③ 数据删除类动作纳入双人复核 + 云侧快照覆盖率告警（第 7 章 §9.1 备份铁三角）。
- **经验**：①「删 K8s 对象」≠「删后端资源」的心智模型在 v1.37 被官方重新定义——**v1.37 起，删 Bound 的 PV 就是删盘**；② 好习惯不是「我记得」，是「delete 前必走一条只读命令」（与危险批量手册 §8.1 两步法同源）。

---

## 十一、实验（实验 L3 的作战地图）

承接第 7 章 §9.4 的 7 个破坏场景；本实验在 **L2 集群（Multipass 三节点 v1.37）** 上执行（搭法见第 7 章实验 7.1）。每场景演练完，按 §10.1 模板写一篇复盘，runbook 归档建议两处：直接追加进本文 §10 的案例区，或收入 `自动化/runbooks/`（自选并全仓库统一）。

### 实验 8.1 七大域破坏演练 runbook

| # | 场景 | 破坏命令（先备份！） | 预期症状 | 标准排查路径（本文引用） | 恢复动作 | 自评耗时目标 |
|---|------|---------------------|---------|--------------------------|---------|------------|
| 1 | 错证书：换一张错误 CA 签的 apiserver.crt | 备份 `cp -a /etc/kubernetes/pki{,.bak}`；`openssl req -x509 -newkey rsa:2048 -nodes -keyout /tmp/bad.key -out /tmp/bad.crt -days 1 -subj /CN=kube-apiserver`；替换 `pki/apiserver.{crt,key}`；mv apiserver.yaml 出进重启 | kubectl 全报 `x509: certificate signed by unknown authority` | §九 9.1 词典（unknown authority 行）+ §3.2 静态 Pod → 第 7 章 §5.1 家谱对比 issuer | 还原 pki 备份或 `kubeadm certs renew apiserver`；静态 Pod 重启三件套（第 7 章 §5.2） | 15 min（首次 30 min） |
| 2 | 删 etcd 数据目录（单 CP 集群上演） | **先快照**：`etcdctl snapshot save /tmp/snap.db ...`（第 7 章实验 7.2 同款）；`mv /etc/kubernetes/manifests/etcd.yaml /tmp/`；`sudo systemctl stop kubelet`；`rm -rf /var/lib/etcd` | apiserver crashloop；readyz `[-]etcd`；kubectl 全超时报 etcd timeout | §3.2 step 1→3（readyz→静态 Pod→etcd）；恢复优先级 P1（第 7 章 §9.2） | 停 apiserver → `etcdctl snapshot restore /tmp/snap.db --data-dir /var/lib/etcd` → 恢复清单 → `systemctl start kubelet` | 30 min |
| 3 | 反复杀 CNI（Cilium agent Pod 连环删） | `watch -n5 'kubectl -n kube-system delete pod -l k8s-app=cilium --wait=false'`（或 cordon 一节点后删该节点的 cilium Pod） | 该节点新 Pod 卡 `FailedCreatePodSandBox`/`NetworkUnavailable`；业务 Pending 涨；严重时 Node NotReady | §4.1 ⑤ NetworkUnavailable + §4.2 `FailedCreatePodSandBox` grep + §七 7.1 | `kubectl -n kube-system rollout restart ds cilium`；节点上 `systemctl restart kubelet`；观察 `cilium status` | 20 min |
| 4 | 停 kubelet | `sudo systemctl stop kubelet`（轻量：`kill -STOP $(pidof kubelet)` 可逆版） | ~40s 后 Node NotReady（Lease 陈化）；nolifecycle 污点；300s 后该节点 Pod 被逐 | §4.1 ② + `kubectl -n kube-node-lease get lease <node> -o yaml` 看 renewTime | `systemctl start kubelet`；NotReady 恢复后确认污点与驱逐按计划消退 | 10 min |
| 5 | fallocate 堵根盘到 eviction 起跳 | 先记 `df -h /`（L2 的 20G 盘、OS+镜像约占 5G）：`avail_g=$(df --output=avail -BG / \| tail -1 \| tr -dc 0-9)`；`sudo fallocate -l $(( avail_g * 92 / 100 ))G /var/bigfile`；盯 `kubectl describe node \| grep DiskPressure`（填满 92% 空闲 → available <10% 过默认硬阈值） | DiskPressure=True → eviction 连环（Evicted Pod 涨）→ imageGC 轰鸣 | §4.3 三条命令（conditions/Evicted 盘点/du 大户）；对照第 7 章 §6.4 默认表与 `mergeDefaultEvictionSettings` 坑 | `sudo rm /var/bigfile`；确认 condition 回 False；清 Evicted（危险手册 §5.6 命令） | 25 min |
| 6 | 过期 Ingress 证书 | 生成过期证：`sudo apt-get install -y faketime && faketime '2 years ago' openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout /tmp/expired.key -out /tmp/expired.crt -subj /CN=api.example.com`（faketime 让 notBefore 落在两年前，-days 365 → notAfter 落在一年前）；`kubectl create secret tls demo-tls --cert=/tmp/expired.crt --key=/tmp/expired.key -n default --dry-run=client -o yaml \| kubectl apply -f -`；Ingress 指它 | 浏览器/`curl` 报 `certificate has expired`；s_client notAfter 在过去 | §九 9.1 首行 + 9.2 命令组（s_client -servername + Secret 解码） | 重新生成新证 → Secret 替换（§9.3 第三条）；`curl -vk https://...` 复测 | 15 min |
| 7 | CoreDNS forward 指向黑洞 | `kubectl -n kube-system edit cm coredns`：把 `forward . /etc/resolv.conf` 改为 `forward . 10.255.255.1`；`kubectl -n kube-system rollout restart deploy coredns` | cluster.local 内解析正常；**所有外部域名超时**；业务报障但集群内互通无恙 | §7.3 三板斧第 ②③：直查 CoreDNS PodIP / 看 Corefile（`kubectl -n kube-system get cm coredns -o yaml`）；对照三板斧命令 | 改回 `forward . /etc/resolv.conf`；再 rollout restart；`nslookup api.github.com 10.96.0.10` 验证 | 15 min |

❗ 通用铁律（第 7 章 §9.4 已立，此处重申并扩成动作）：**每个场景动手前的备份指令本身就是评分项**（场景 1 的 pki 备份、场景 2 的 snapshot、场景 6 的原 Secret `-o yaml > 备份`）；演练中用 §2.1 三条止损命令记录「破坏中 readyz/events 显示什么」；恢复后按 §1.1 动作五填表复盘。演练即复盘，复盘即 runbook。

### 实验 8.2 kubectl debug 三形态一条流水线速通

目标：10 分钟内跑通三形态并各留下一个「证据产物」。

```bash
# step 0：造一个「没工具」的目标（用 pause 镜像模拟 distroless，官方示例同款思路）
kubectl run dbg-victim --image=registry.k8s.io/pause:3.10 --restart=Never
kubectl exec -it dbg-victim -- sh            # 预期失败：executable file not found

# ① ephemeral 容器形态（证据产物：一张 Pod 网络视角的截图/输出）
kubectl debug dbg-victim -it --image=nicolaka/netshoot --target=dbg-victim --profile=general
# 容器内：ip addr; ps aux | head; ss -tlnp
kubectl get pod dbg-victim -o jsonpath='{.spec.ephemeralContainers[0].securityContext}'   # 记录形态

# ② netadmin 形态抓包（证据产物：DNS 包展开序列 3 行）
kubectl debug dbg-victim --image=nicolaka/netshoot --target=dbg-victim --profile=netadmin -- \
  tcpdump -i any -nn -c 10 udp port 53

# ③ copy-pod 形态（证据产物：副本跑起 sh、原 Pod 不受影响）
kubectl debug dbg-victim -it --copy-to=dbg-victim-debug --image=busybox
kubectl get pods dbg-victim dbg-victim-debug -o wide
kubectl delete pod dbg-victim-debug

# ④ node 形态（证据产物：拿到 /host 视图 + crictl ps 能在里面跑）
kubectl debug node/k8s-w1 -it --image=ubuntu --profile=sysadmin
# 容器内：chroot /host crictl ps | head
# 出来后按实际生成的名字清理（kubectl delete 不支持通配 Pod 名）：
kubectl get pods | grep node-debugger        # 找到 node-debugger-k8s-w1-<rand>
kubectl delete pod <node-debugger-k8s-w1-...>
kubectl delete pod dbg-victim
```

验收四问（答得出才算过）：`--target` 管什么？（目标容器的 process namespace）`--copy-to --container=x` 与不带 `--container` 的差别？（改已有容器命令 vs 新加调试容器——6.3 ★）profile general/netadmin/sysadmin 各拿到什么权限？（6.3 表）ephemeral 容器为什么不能用 kubectl edit 加？（走特殊子资源 handler，官方 ephemeral-containers 页）。

### 实验 8.3 nsenter + tcpdump 追「Service 间歇丢包」（conntrack 压力场）

目标：在 L2 集群亲手复现 §7.2 的 conntrack 满表，并把「间歇丢包 → 满表」的链路走通。

```bash
# step 0：搭受害者 Service（随便一个 nginx + ClusterIP）
kubectl create deploy web --image=nginx:1.27 --replicas=2
kubectl expose deploy web --port=80

# step 1：在 k8s-w1 上制造 conntrack 压力（把表上限调小 = 低成本模拟满表，不必真造几万流）
multipass shell k8s-w1
cat /proc/sys/net/netfilter/nf_conntrack_max                       # 记下原值（恢复用）
sudo sysctl -w net.netfilter.nf_conntrack_max=1024

# step 2：压力源 Pod 必须钉在 k8s-w1（conntrack 是「发起侧节点」的表）——overrides 指定 nodeSelector
kubectl run flood --image=nicolaka/netshoot --restart=Never --rm -it \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/hostname":"k8s-w1"}}}' -- sh
# 容器内循环发短连接（每轮回 50 个 SYN + 50 个 UDP DNS 查询，各自占 conntrack 条目）
while true; do
  for i in $(seq 1 50); do nc -z -w1 10.255.0.$((RANDOM % 250+1)) 80 2>/dev/null; dig +time=1 +tries=1 fake-$RANDOM.example.com @10.96.0.10 >/dev/null 2>&1; done
  sleep 0.2
done &
# 之后不断 curl 我们的 Service，观察间歇性失败：
while true; do curl -s -m 2 -o /dev/null -w '%{http_code}\n' http://web.default.svc.cluster.local || echo TIMEOUT; sleep 0.5; done
# 预期：间歇 000/TIMEOUT 与 200 交替（≤30% 丢包观感）

# step 3：三端取证（另外开两路 shell）
#   端点 A（k8s-w1 节点内核，multipass shell k8s-w1）：dmesg 铁证
sudo dmesg -T | grep -i 'nf_conntrack' | tail -5     # nf_conntrack: table full, dropping packet
sudo conntrack -C; sudo conntrack -S | head -6
#   端点 B（到 web Pod 所在节点：multipass shell <那台>；用 nsenter 在后端 Pod 的 netns 抓，不扰流）
cid=$(sudo crictl ps | grep 'web-' | awk 'NR==1{print $1}')
pid=$(sudo crictl inspect $cid | jq -r '.info.pid')
sudo nsenter -t $pid -n tcpdump -i any -nn -c 20 'tcp port 80'
# 判读：SYN 到没到 Pod netns？到了没回（应用/port 问题）vs 没到（中间丢——本实验的剧本）

# step 4：止血与恢复
sudo sysctl -w net.netfilter.nf_conntrack_max=<step 1 记下的原值>
# 观察 curl 循环恢复全 200；kill flood 循环；delete pod flood
```

验收：①能在 30 分钟内从「Service 间歇丢包」定位到 `nf_conntrack: table full`；②写出三端各自「看到了什么」的复盘三行（§10.1 规则）；③调整 max 后 curl 恢复全 200 的证据截图进 runbook。

---

## 十二、速查表 + 背诵要点 + 参考链接

### 12.1 一页速查（排障命令）

| 主题 | 命令 |
|------|------|
| **总入口三件套** | `kubectl get --raw='/readyz?verbose' \| grep '^\[-\]'`；`kubectl get nodes -o wide`；`kubectl get events -A --sort-by='.lastTimestamp' \| tail -30` |
| 事件铁律 | events 是 namespaced 对象（Node 事件落 default）；TTL 默认 1h（`--event-ttl`）；事故中先把 events 存盘 |
| 证据存盘 | `kubectl get events -A -o json > events.json`；`kubectl get pod x -o json > pod.json`；`kubectl logs x --previous > prev.log` |
| 控制面清单 | 静态 Pod：`crictl ps \| grep -E 'apiserver\|scheduler\|controller\|etcd'`；日志：`journalctl -u kubelet`；etcd：`etcdctl endpoint status -w=table`；webhook：`kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations`；聚合层：`kubectl get apiservices \| grep -v Local` |
| 节点 NotReady | `curl -sk https://<node>:10250/healthz`；`systemctl status kubelet`；`crictl ps` 超时？；`openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -dates` |
| kubelet 日志 | `journalctl -u kubelet --since '1h ago' \| grep -EiE 'evict\|oom\|garbage\|cni\|PLEG\|FailedCreatePodSandBox\|x509' \| tail -60` |
| 压力与驱逐 | describe node 的 Conditions；默认 evictionHard 5 条（mem<100Mi/nodefs<10%/imagefs<15%/inode<5%）引用第 7 章 §6.4；清 Evicted：`kubectl delete pods -A --field-selector=status.phase=Failed` |
| 两种 OOM | A=容器 cgroup：`lastState.terminated.reason=OOMKilled` + exit 137；B=宿主机 OOM killer：`journalctl -k \| grep -i 'out of memory'`（`Memory cgroup out of memory`=A 层，`Out of memory: Killed process`=B 层） |
| crictl | `crictl ps -a` / `pods` / `logs --tail=100 <cid>` / `exec -it <cid> sh` / `inspect <cid> \| jq .info.pid` / `rmp <sandbox>` / `rmi --prune` |
| Pending | 四步链照抄第 2 章 §7.3；静默绕路三查：`.spec.nodeName`、`.spec.schedulerName`、`.spec.schedulingGates` |
| Pod 症状 | describe → Events；`logs -c <c> --previous` → `.exitCode`/`.reason`；exit 137=SIGKILL（OOMKilled/liveness/Evicted 三选一）、139=SIGSEGV、143=SIGTERM 正常落幕 |
| kubectl debug | A：`-it <pod> --image=<img> --target=<c>`（ephemeral，v1.25 Stable）B：`--copy-to=<n> [--container=<c>] [--set-image=*=<img>]`（副本）C：`node/<node> -it --image=ubuntu`（主机命名空间 + /host）D：`--profile={general\|baseline\|restricted\|netadmin\|sysadmin}`（默认 general），`--custom=<file>`（v1.32 Stable） |
| nsenter | `pid=$(sudo crictl inspect $cid \| jq -r .info.pid)`→ `sudo nsenter -t $pid -n <cmd>`（跑宿主机工具：tcpdump/curl/ss/ip）；`-m` 挂载 ns；`/proc/$pid/root` 直接看容器文件系统 |
| 优雅退出 | 摘除（endpoint 控制器→kube-proxy）∥ 终止（preStop→SIGTERM→30s 默认 grace→SIGKILL）**并行**非串行；preStop sleep 可解「退期间丢流量」；探针默认 period 10s/timeout 1s/failureThreshold 3 |
| 网络逐跳 | Pod→同节点→跨节点→ClusterIP→endpointSlice→后端直达→egress/ingress；**timeout=半路丢，refused=四层没人监听** |
| conntrack | `conntrack -C` vs `nf_conntrack_max`；`dmesg \| grep nf_conntrack`（table full = 丢新流）；症状=间歇 UDP/DNS + 短连接丢 |
| DNS ndots | 默认 `options ndots:5` → <5 点多走 search 展开；FQDN 尾点（`name.`）跳过；排 DNS 用 dnsutils/netshoot（glibc），**别用 alpine** |
| NetworkPolicy | 静默放行判定：default-deny 实弹测试（nc 还能连上=没执行）；Cilium 用 `hubble observe --verdict DROPPED`；全程引第 3 章 §6.3-6.5 |
| MTU 黑洞 | 小包通大包卡/TLS 卡握手/image 拉不动；`ping -M do -s <size>` 逐档二分；修复=CNI mtu 对齐「物理-封装头」 |
| 存储 | PVC Pending 看 describe pvc events；挂载失败看 describe pod；multi-attach 看 `kubectl get volumeattachment`；mount 残留 `findmnt` + `umount -f -l` |
| 证书 | `kubeadm certs check-expiration`；`openssl x509 -noout -subject -issuer -dates -ext subjectAltName`；在线 `openssl s_client -connect IP:443 -servername <sni> </dev/null`；not yet valid 先查 chrony |

### 12.2 症状 → 域 速查（一分钟路由）

| 症状一句话 | 先去 |
|-----------|------|
| kubectl 全卡/全超时 | 域一 §3.1（先自证 kubeconfig/网络） |
| kubectl 慢、对象创建没生效、聚合层 500 | 域一 §3.1/§3.3（webhook、APIService） |
| 单个节点 NotReady | 域二 §4.1（四类分流） |
| 大面积 NotReady | 域一 §3.3 级联行 + 域五 CNI |
| Pod Pending | 域三 §5.1 四步链；大面无 events → §5.2 |
| 有节点空闲但不调 | 域三 §5.3（nodeName/schedulerName/gates） |
| ImagePullBackOff | 域四 §6.1（镜像名/认证/限流/egress） |
| CrashLoopBackOff | 域四 §6.1+6.2（--previous/exit code） |
| Running 但不通/READY 0x | 域四 §6.1 Ready 行 → 不通再去域五 |
| Terminating 卡死 | 域四 §6.1（finalizer/webhook/卸载） |
| 「通但慢」「间歇丢包」 | 域五 §7.2 conntrack + §7.5 MTU |
| 解析慢/失败 | 域五 §7.3（三板斧 + ndots 两例） |
| 挂载类/PVC 类 | 域八 §8.1（A/B/C/D 分类路由） |
| x509/TLS 报错 | 域九 §9.1 词典 |

### 12.3 关键要点（背诵版）

1. **总纲一句话**：症状 = 某个控制循环没 reconcile 成功；排障 = 定位到那台循环 → 顺着链反查每一环的输入 → 每一跳只信一手证据（events/status/日志/节点真相）。
2. **五动作顺序**：界定域 → 收集证据（只读） → 假设-验证（一次一个变量） → 修复（先止血后根治，分账记） → 复盘（timeline 模板 §10.1）。**没有复盘的修复等于没修**。
3. **总入口三件套 30 秒**：`/readyz?verbose`（控制面）→ `get nodes`（节点面）→ `get events -A --sort-by='.lastTimestamp`（事件面）。多域并发按域一→四顺序收敛。
4. **控制面判读链**：readyz（`[-]etcd` / informer-sync / poststarthook）→ crictl ps 静态 Pod → etcdctl endpoint status → webhook/聚合层。`get cs` 已废（v1.19 deprecated），代报状态全部要怀疑一层。
5. **NotReady 四类分流**：网络分区（10250 不通）/ kubelet 挂（systemctl）/ runtime 卡（crictl ps 超时）/ 证书（`kubelet-client-current.pem` 过期）+ 压力条件。看 `journalctl -u kubelet` 之前别下结论。
6. **两种 OOM 必区分**：容器 cgroup（OOMKilled reason + exit 137，好 OOM） vs 宿主机杀手（`journalctl -k` 有 `Out of memory: Killed process`，无 OOMKilled reason，失控前兆）。「memory request == limit」让 OOM 永远只在 cgroup 里发生。
7. **Pending 静默绕路三剑客**：`.spec.nodeName` 预绑 / `.spec.schedulerName` 指了不存在的调度器 / `.spec.schedulingGates`（STATUS 显 SchedulingGated）——**全都不出 FailedScheduling 事件**。调度器本体病了看 kube-scheduler Pod + Lease + :10259 指标。口诀：**Pending 看账本（allocatable − requests），慢才看实况**。
8. **kubectl debug 四形态**：ephemeral（v1.25 Stable；--target 共享进程 ns；不能有 ports/probes/resources；加后不可改；静态 Pod 不支持）、copy pod（--copy-to；--container 改已有容器命令、--set-image 换镜像；副本不影响原物）、node 调试（/host 挂载 + host namespaces，默认非特权）、profile 三档（general 默认/netadmin 抓包/sysadmin privileged；--custom v1.32 GA）。**CrashLoop 的 Pod 沙箱还在，ephemeral 照挂；Pending 无沙箱挂不上——转 --copy-to**。
9. **nsenter 是「把宿主机工具借进容器的 namespace 跑」**：`crictl inspect → .info.pid → nsenter -t <pid> -n tcpdump`——容器再 distroless 也能抓包；`/proc/<pid>/root` 零成本看容器文件系统。它绕过 K8s 层，runbook 里要记账。
10. **优雅退出两条线并行**：endpoint 摘除（A）∥ 容器终止（preStop→SIGTERM→30s→SIGKILL，B）——B 快于 A 就丢流量，用 preStop sleep 留窗；Terminating 卡死五查：finalizer → webhook 挡 UPDATE → preStop 阻塞 → 卸载僵死 → shim 残留。
11. **网络排障最锋利一刀**：**timeout = 半路丢，refused = 到了没人监听**；逐跳定位走 Pod→同节点→跨节点→ClusterIP→endpointSlice→后端直达。conntrack 满表的画像 = 间歇 UDP/DNS 失败但长连接稳；MTU 黑洞的画像 = 小包通大包卡（TLS 握手先死）。**alpine/musl 镜像排 DNS 会给假线索——用 dnsutils/netshoot**。
12. **存储四分类**：PVC Pending（供给层）/ 挂载失败（attach/mount 层，`Unable to attach or mount` 字样）/ IO 慢（数据面层）/ 对象删不动（回收侧 finalizer）——各走各的表；multi-attach 先 `kubectl get volumeattachment` 确认旧节点真死再松手删，数据权属永远人工确认。
13. **x509 词典三急**：expired/not yet valid（查日期 + chrony）/ unknown authority（issuer vs 信任链，kubelet serving 自签是 kubeadm 默认）/ SAN mismatch（证书覆盖 FQDN≠访问形态）。kubeadm 叶证续期 = renew + 静态 Pod 重启三件套。
14. **复盘是手段不是文书**：三行铁证——事故前最近快照、事故中 readyz 与 events 各显示什么、恢复中哪个对象是最大因果。L3 七场景演完按 §10.1 写复盘，runbook 才配叫 runbook。

### 12.4 参考链接

| 主题 | 链接 |
|------|------|
| Debug Running Pods（ephemeral/copy/node/profile/--target/--set-image/sysadmin 抓包/sysadmin 权限验证） | https://kubernetes.io/docs/tasks/debug/debug-application/debug-running-pod/ |
| Debug Pods（Pending/Waiting/Terminating/webhook 挡 finalizer 判读、events are namespaced） | https://kubernetes.io/docs/tasks/debug/debug-application/debug-pods/ |
| Debug Services（逐跳清单 svc→DNS→IP→endpointSlices→Pods→kube-proxy；ndots 默认 resolv.conf 示例） | https://kubernetes.io/docs/tasks/debug/debug-application/debug-service/ |
| Debug Init Containers（Init:N/M 状态表、init 日志取法） | https://kubernetes.io/docs/tasks/debug/debug-application/debug-init-containers/ |
| Troubleshooting Clusters（日志位置 /var/log、失败模式与缓解列表） | https://kubernetes.io/docs/tasks/debug/debug-cluster/ |
| Ephemeral Containers 概念页（Stable since v1.25；disallowed 字段；不可改；静态 Pod 不支持） | https://kubernetes.io/docs/concepts/workloads/pods/ephemeral-containers/ |
| kubectl debug 命令参考（--profile 选项与默认 general、--custom/--keep-*/--replace/--same-node，自动生成本） | https://kubernetes.io/docs/reference/kubectl/generated/kubectl_debug/ |
| crictl 节点调试（pods/ps/logs/exec/inspect 示例；endpoint 配置；Stable since v1.11） | https://kubernetes.io/docs/tasks/debug/debug-cluster/crictl/ |
| Node Pressure Eviction（默认 evictionHard、驱逐排序、static Pod 拉起） | https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/ |
| 配置 Liveness/Readiness/Startup 探针（默认参数） | https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/ |
| Pod 生命周期与终止时序 | https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ |
| kubeadm 证书管理（check-expiration/renew/自签 serving 根源） | https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-certs/ |
| Monitor Node Health（NPD 4 daemon 部署） | https://kubernetes.io/docs/tasks/debug/debug-cluster/monitor-node-health/ |
| KEP-2644 HonorPVReclaimPolicy（先删 PV 历史 bug 与 GA 后行为） | https://github.com/kubernetes/enhancements/tree/master/keps/sig-storage/2644-honor-pv-reclaim-policy |
| resolv.conf 与 ndots（glibc resolver 行为） | `man 5 resolv.conf`（Linux man-pages） |
| 本仓前 7 章 | `容器编排/K8s-API机制深入.md`（§8 审计/§9 生产问题清单）、`K8s-调度器深入.md`（§7.3 四步链/§1.5 QHints/§11.1 Gates）、`K8s-网络原理详解.md`（§5.5 三板斧/§6.3-6.5 静默放行）、`K8s-存储深入.md`（§2.8/§7 主表）、`K8s-安全加固详解.md`（§8）、`K8s-Operator开发实战.md`（§8）、`K8s-生产集群运维手册.md`（§5 证书/§6 调优/§7 NPD/§9 灾备） |
| 本仓范本笔记 | `安全/挖矿木马入侵排查与清除实录.md`（事故复盘体裁）、`容器编排/K8s-排障进阶-5个冷门kubectl命令详解.md`、`容器编排/Docker-K8s-快捷批量操作手册.md`、`容器编排/k8s-常用操作手册.md`、`容器编排/K8s-组件详解.md` |

---

> 收官备注：八个章节到此闭环——第 1~7 章给了 K8s 的「零件级机制」，本章给了「出故障时的肌肉记忆」。**方法论没有终点只有演练**：实验 8.1 的七场景每季度重跑一遍（time-box 按表内自评耗时收敛），每跑一次把新踩到的坑回填进症状词典——这就是这张「排障一本通」成为活的文档的方式。
