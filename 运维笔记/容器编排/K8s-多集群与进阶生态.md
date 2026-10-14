# K8s 多集群与进阶生态

> 精通路线第 10 章（收官）：多集群的真实动因与反模式、一致性三难与五类拓扑、管理平面横向对比（Rancher+Fleet / OCM / Karmada / Federation 退役史）、多集群 Service 与流量方案谱、Cluster API 声明式造集群、设备管理与 GPU（TimeSlicing/MIG/MPS/DRA）、边缘与 Wasm/Serverless、虚拟集群与多租户谱系、四个实验（Karmada / vCluster / CAPI / GPU）、全路线索引与十项验收能力对照
> 创建时间：2026-10-14
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37）；外部生态组件基线（2026-10-14 逐一对照官方文档与 GitHub releases 核实，来源见 §十一）：**Karmada v1.19.0**（CNCF 毕业）、**OCM v1.4.0**、**Cluster API v1.14.3**（capi-operator v0.29.0）、**vCluster v0.37.3**、**Cilium 1.20.x**、**Submariner v0.24.2**、**KubeEdge v1.23.1**（CNCF 毕业）、**OpenYurt v1.7.0**、**NVIDIA k8s-device-plugin v0.20.1 / gpu-operator v26.7.x**、**Knative Serving v1.23.0**、**spin-operator v0.6.1**、**Fleet 0.16.x**、**Rancher v2.15.2**（本机已部署实例）。当时尚在预发布的：Karmada v1.20、Cilium 1.21、vCluster 0.38、Submariner 0.25/0.26、Fleet 0.17。落地前仍以你本地组件版本与现场输出为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，list-watch/聚合层/审计）、`K8s-调度器深入.md`（第 2 章，**§11.2 DRA**——本章设备管理直接接力不重讲）、`K8s-网络原理详解.md`（第 3 章，CNI/Gateway API——多集群入口方案在此处引一句）、`K8s-Operator开发实战.md`（第 6 章，CRD 多版本与 Conversion——Cluster API 跨版本升级的机制底座）、`K8s-生产集群运维手册.md`（第 7 章，§6.5 大集群约束与 §8 租户治理）、`K8s-自动伸缩深入.md`（第 9 章，Karpenter/CA/KEDA/HPA——伸缩与多集群的边界划分）。总纲：`学习/K8s-精通路线-总纲.md`。**本文是精通十章的收官篇：第 10 节是全系列索引 + 总纲十项验收能力对照表**。

---

## 零、本文定位与边界

### 0.1 收官定位：把「多个集群」当成一件事来设计

前 9 章解决的是一个集群内部的精通：API、调度、网络、存储、安全、扩展开发、生产运维、排障、伸缩。本章解决最后一块拼图——**当集群不止一个时，怎么把它们当成「一件事」而不是「N 件事」来设计**。

先立一条贯穿本章的心智：**多集群不是一个组件，是一组取舍**。没有「上了某工具就有了多集群」这回事——Karmada 管的是「工作负载怎么铺」，Cilium Cluster Mesh 管的是「Pod 网怎么通」，Rancher 管的是「几十个控制面怎么运维」，Cluster API 管的是「集群本身怎么批量造」，vCluster 管的是「怎么不造集群也能多租户」。它们解决同一难题的不同切片，可以叠加，不能互相替代。

### 0.2 多集群的真实动因清单（含反模式）

| 动因 | 它真实的样子 | 判定问题 |
|------|-------------|---------|
| **灾备/可用区/可用域隔离** | 一个集群的影响面按「控制面 + etcd + 数据面 CIDR」整体计算；多集群把爆炸半径收到集群粒度 | 「集群级故障（控制面失联、CIDR 冲突、etcd 坏）时，业务还能跑吗？」答不出 → 需要第二个集群 |
| **合规与数据驻留** | 数据必须在某国/某区域/某行业专区内落地；跨区流量受法规限制 | 「这批数据能不能物理上离开该区域？」不能 → 拆 |
| **就近接入（延迟）** | 用户/设备在多个地域，跨洲 RTT 不可接受 | 「100ms+ 的 RTT 对这个业务是体验问题还是契约问题？」契约问题 → 拆 |
| **云商/供应商风险分散** | 双云或「云 + 自建」防止单云故障、砍价筹码、采购合规 | 「这个集群从云上消失 24 小时，公司的应急剧本是什么？」没剧本 → 至少演练过异构第二集群 |
| **弹性外溢（burst）** | 常态容量在自建/主云，峰值溢到公云第二集群 | 「峰值期间是新加节点还是新开集群？」边缘/合规型负载适合后者 |
| **团队自治边界** | 大组织里平台组管集群，业务组要「自己的集群」自助又不会互相炸 | 「多租户隔离需求超出了 namespace + RBAC + Quota + PSA 的组合吗？」超出 → vCluster 或物理集群（§七） |

**反模式（最重要的一张表）**：

| 伪动因 | 真相 | 正确做法 |
|--------|------|---------|
| 「集群太多了所以要多集群管理」 | 集群数量本身不是问题；没有动因的集群才是 | 先审「这个集群为什么存在」，能合则合 |
| 「为了学 Karmada/多集群而上多集群」 | 学习用 kind + 实验 10.1 就够，生产别陪葬 | 本章实验全在沙箱完成 |
| 「namespace 隔离不够，上多集群」 | namespace + RBAC + ResourceQuota + LimitRange + PSA + NetworkPolicy 的「软多租」组合能覆盖 80% 场景（第 7 章 §8 已有全套） | 先软多租，不够再 vCluster，**单集群能解决的绝不拆多集群** |
| 「为了高 QPS 拆集群」 | 单集群官方上限 5000 节点/15 万 Pod（§1.2），绝大多数团队到不了 | 先复核容量模型（第 7 章 §6.5） |

### 0.3 与已有笔记的边界表（引用不重讲）

| 主题 | 已有笔记 | 本章的关系 |
|------|---------|-----------|
| 单集群规模上限（5000 节点等）与 etcd/apiserver 预算推导 | 第 7 章 §6.5 | §1.2 只引结论与「什么时候仍要拆」 |
| Gateway API 跨集群入口（MCI/Global Gateway 类云实现） | 第 3 章 §七；`Kubernetes-Ingress-部署与使用详解.md` | §3.1 一句引，多集群入口层归云方案 |
| ApplicationSet 多集群 GitOps（clusters 生成器） | `CI-CD/Argo-CD-部署与使用详解.md` §12 | §8.1 把 GitOps 定位为「多集群的 glue」一句引 |
| CRD 多版本转换（Conversion webhook） | 第 6 章 §3 | CAPI/Karmada 的 CR 跨版本升级、把同一份 YAML 分发到异构版本集群时，靠的就是这套机制——§4.4/§2.3 点一句不展开 |
| Istio 多集群（sidecar 成熟 / Ambient 多网络多集群 Beta） | `容器编排/Istio详细入门与实践指南.md`（Ambient 状态段与选型表） | §3.1 最贴应用层方案一句引 |
| Rancher 平台部署与纳管实操（含 Cilium kube-proxy 替换模式的 NodePort 坑） | `脚本与工具/Rancher部署文档.md` | §2.1 衔接一段，不重复安装文档 |
| GPU 硬件形态（DGX/HGX/SXM/NVLink） | `云服务/DGX-HGX-SXM-详解.md` | §5 只讲 K8s 视角的设备使用与共享，硬件选型不重讲 |
| DRA 对调度链路的影响 | 第 2 章 §11.2 | §5.4 直接接力：版本口径以第 2 章为准 |
| 伸缩（HPA/VPA/KEDA/Karpenter） | 第 9 章全文 | §6.3 Knative 一句引；多集群伸缩留给 §8.2 的落地节奏 |

### 0.4 研究与落地心法（先背这十条）

❗ ①一致性是多集群的第一成本，不是工具选择；②单集群能解决的绝不拆多；③多集群方案 = 管理面 × 数据面 × GitOps 三层各选一件，不选全；④hub-spoke 里 hub 单点，pull 模式是命脉；⑤跨集群流量的保质期看「故障摘除」而不是「能通」；⑥Pod CIDR 重叠是 CNI 级多集群的第一拦路虎（Globalnet/非重叠规划二选一）；⑦vCluster 解决的是「控制面多租户」，不是「集群廉价化」；⑧GPU 上 K8s 的第一课永远是「卡在驱动与 toolkit」——不是调度；⑨边缘的真问题是「断网后谁说了算」，不是「怎么下发」；⑩每加一个集群，问问自己「拆掉它需要几步」——可逆性决定架构健康度。

### 0.5 生态版本基线速览（2026-10-14 现场核实）

| 组件 | 本文落笔版本 | 成熟度形态 | 核实来源（§11.3 全表） |
|------|-------------|-----------|------------------------|
| Karmada | v1.19.0（v1.20 alpha 中） | CNCF Graduated；K8s 兼容表当前列到 1.36 | GitHub releases + README 兼容表 |
| OCM | v1.4.0 | active；ACM 的上游 | open-cluster-management-io/ocm releases、官方架构页 |
| kubefed（Federation v2） | **已于 2023 年归档退役** | kubernetes-retired 组织 | GitHub 仓库 archived + 最后 push 2023-03 |
| Rancher（你已部署）/ Fleet | Rancher v2.15.2（实战）/ Fleet stable 0.16.x（0.17 alpha） | 管理面 + 内建 GitOps | `脚本与工具/Rancher部署文档.md`、rancher/fleet releases |
| Cilium Cluster Mesh | Cilium 1.20.x（1.21 pre） | 官方稳定文档线；MCS-API 实现另册 | docs.cilium.io clustermesh 章节 |
| Submariner | v0.24.2（0.25/0.26 预发布） | CNCF（云厂商联营） | submariner-io/submariner releases |
| Cluster API | v1.14.3；capi-operator v0.29.0（pin CAPI v1.13.5） | core API 已 v1beta2；v1beta1 计划 v1.16 停 serve | kubernetes-sigs/cluster-api(+operator) releases |
| vCluster | v0.37.3（v0.38 alpha） | CNCF Certified K8s Distribution | loft-sh/vcluster releases + README |
| KubeEdge / OpenYurt | v1.23.1 / v1.7.0 | **Graduated（2024-09-11）** / Incubating | 两仓 releases + CNCF 项目页 |
| NVIDIA 设备栈 | k8s-device-plugin v0.20.1；gpu-operator v26.7.x | GA 常用；DRA 驱动收编进行中 | 两仓 releases + gpu-operator README Roadmap |
| Knative / SpinKube | Serving v1.23.0 / spin-operator v0.6.1 | 常态使用 / **仍 0.x 谨慎** | knative/serving、spinframework/spin-operator releases |
| KWasm | **已退役（repo archived）** | 接力 `spinframework/runtime-class-manager` | KWasm/kwasm-operator 归档 README |

### 0.6 本章怎么用（阅读路径）

- **赶时间（30 min）**：§0.4 十条心法 → §1.4 组合形态 → §2.5 决策表 → §8.1 铁律 → §11 速查/背诵——拿到「开会够用的多集群选型地图」。
- **认真学（一个周末）**：全文顺序读 + 实验 10.1/10.2 各跑一遍 → §10.2 对照表自查十项验收，勾掉精通路线最后一格。
- **动手前（生产上会）**：§0.2 动因表 + §8.2 路径表逐条过你的现状 → 每选中一条产品线，回到对应小节把「版本核实/限制条件/局限段」重读一遍（本章所有「❗」都值这个价）。

---

## 一、多集群的现实动因与主矛盾

### 1.1 一致性三难：config / workload identity / traffic

多集群的所有复杂度，最终落进三个「怎么也难两全」的一致性命题：

```
                   ┌────────────────────────────────────────────┐
                   │            多集群一致性三难                  │
                   └───────┬────────────┬────────────┬──────────┘
                           ▼            ▼            ▼
                     config 一致性  identity 一致性  traffic 一致性
                  （同一份 YAML/秘  （同一个工作负载  （同一笔流量在 A
                    钥/策略在 N 个   在 N 个集群里是  集群和 B 集群里
                    集群里语义相同）  不是同一个身份）  的待遇相同）
                           │            │            │
                  Karmada/OCM/    SPIFFE/SPIRE、    Submariner/
                  GitOps/Policy   服务网格 mTLS、   Cilium Mesh/
                  框架的战场       云 IAM 映射       MCS/云 LB
```

- **config 一致性**：Deployment/Service 好对齐（Karmada/GitOps），难的是 Secret、RBAC、NetworkPolicy、PSA 标签、甚至 CRD 版本这种「地基配置」聚齐一致——v1.37 的 workload 拿到 v1.35 的集群落不下去（缺 API 版本）是最常见翻车。
- **workload identity 一致性**：Pod 在集群 A 里的 ServiceAccount token 由集群 A 的 CA 签发，集群 B 的 API 与外系统天然不认。跨集群的 OIDC federation/服务网格 mTLS/云 IAM 是三条主流出路——**选哪条决定了你多集群的身份天花板**（SPIFFE/SPIRE 是云中立的那条，Istio 笔记里有成熟的 sidecar 实现）。
- **traffic 一致性**：服务名、ClusterIP、CIDR 在每个集群都是本地性的；「同名 Service 跨集群可达且语义一致」要靠专门产品补（§三的全部内容）。

### 1.2 单集群上限回顾：什么时候「真的到顶了」

第 7 章 §6.5 已给官方数字与推导（官方 large cluster 页：**≤5000 节点 / ≤150000 Pod / ≤300000 容器 / ≤110 Pod 每节点**；背后是 etcd 写速 × watch 扇出 × apiserver watch-cache 内存的乘积约束）。本章只补两句接力台词：

- **到不了 5000 也要拆**：合规、爆炸半径、就近——到顶不是拆集群的唯一理由，甚至不是主理由（§0.2 的真动因里没有一个与「节点数登顶」直接相关）。
- **过了 5000 只有一条路**：第 7 章已写「超规模只走『events 拆独立 etcd + 多集群』」——多集群不是单大集群的可选替代，而是官方唯一答案。

### 1.3 五类拓扑速览（先把形态说成一个词）

| 拓扑 | 一句话 | 典型动因 | 关键产品 | 本章落点 |
|------|--------|---------|---------|---------|
| **hub-spoke（治理平面）** | 一个中心控制面发布/审计到 N 个执行集群 | 多集群运维治理 | OCM、Karmada、Rancher/Fleet | §二（管理平面） |
| **主备（active-standby）** | 流量常驻主集群，备集群热备或冷备，RTO/RPO 由数据层决定 | 灾备 | GitOps + 外部 DNS/GSLB + 数据层复制 | §3.2、§8.2 |
| **就近多活** | 多地域各自独立 service 全量，入口按地理位置分流 | 延迟 | 云 GSLB/多集群 ingress（§3.1） | §3.2 |
| **虚拟集群（nested）** | 在宿主集群里跑「逻辑集群」给租户/CI | 团队自治、CI | vCluster | §七 |
| **边缘扇出** | 中心控制面 + 成千上万边缘节点/微集群 | 边缘 | KubeEdge / OpenYurt / K3s 路线（§6.1） | §6.1 |

> ★ 心智：**拓扑决定产品面，而不是反过来**。先回答「我的多集群长哪种形状」（五选一或组合），再开选型会。一个冷事实：很多团队的「多集群」其实只有「hub-spoke 治理」一层皮——工作负载本身根本不用跨集群跑，那 §三（流量）就可以整章只做了解。

### 1.4 三种最常见的组合形态（生产实际长这样）

```
形态甲「主备 + GitOps」（灾备驱动，80% 团队的第一个多集群）：
  外部 DNS/GSLB ──┬── 主集群（流量 100%）
                  └── 备集群（热备，副本全量、入口常闭）
  治理：一份 git repo × ApplicationSet 双 destination —— 无 hub 控制面

形态乙「hub-spoke 治理」（≥3 集群后的必然叠加）：
        Hub（OCM/Karmada/Rancher）
        ┌────┼─────┬─────┐
     集群A  集群B  集群C   …（workload 各跑各的，hub 只发策略/负载清单）
  治理：Placement/PropagationPolicy；流量：仍是本地入口，不跨集群

形态丙「mesh 内联」（同城/同 VPC 双活，Cilium 一体的扁平直连）：
   集群A ◄──── Cluster Mesh（flat Pod IP）────► 集群B
     Global Service「rebel-base」在两边同名 → eBPF 层 LB
  治理：仍叠形态乙的 hub 或 GitOps；流量：mesh 自管
```

❗ 选型要落地到「SLA 数字」：一致性三难各给一个可测量的预算再开工——config 漂移容忍（例：政策类 ≤5min、业务类 ≤1min）、身份覆盖（例：跨集群服务调用 100% mTLS 或 0%——抵制中间态）、故障摘除时延（例：整簇失联到流量全走 ≤90s，配 §3.2 的域名 TTL/cacheTTL）。**没有数字的「跨集群同步」四个字，最终都是运维的黄金时段（和血压）去补。**

---

## 二、管理平面横向对比（本章重点）

「管理平面」= 谁负责把工作负载/策略发布到 N 个集群。它**不管网络连通**（那是 §三）、**不管集群的生死**（那是 §四 CAPI）。三个主要玩家 + 一段历史：

### 2.1 Rancher + Fleet：「管理面 + agent 回连」的平台路线

Rancher 的模式（对应你 `脚本与工具/Rancher部署文档.md` 已落地的实例 v2.15.2）：宿主集群跑 rancher（cattle-system）+ UI + 认证 + fleet；被管集群只需装 **cattle-cluster-agent，由它主动回连** Rancher server-url 建立隧道——方向是「集群 → Rancher」，被管集群不必开放入站（Rancher 文档 §1 架构图与 §6 Import 步骤）。这个「agent pull」方向与后面 Karmada/OCM 的 Pull 模式是同一个心智：**可纳管性只依赖被管集群能出网**。

```bash
# 在你已部署的 rancher 上确认协议形态（引用 Rancher 部署文档，不重复安装）
kubectl get settings.management.cattle.io server-url -o jsonpath='{.value}{"\n"}'
kubectl -n cattle-system get pods                                 # rancher + fleet 工作件
kubectl get clusters.management.cattle.io                         # 纳管清单（集群级 CR，不在 ns 里）
```

- Rancher 自身是多集群**管理面**：UI（视图/监控/RBAC/目录） + provision（RKE2/K3s/托管集群接入） + 策略。它**不是一个负载调度器**（没有 PropagationPolicy 那类「把这个 Deployment 铺过去」的 API）。
- Fleet 是 Rancher 自带的 GitOps 引擎（下游 agent 形态，GitRepo/Bundle 对象；版本随 Rancher 配套，当前 stable 0.16.x 线、0.17 在预发布）——与 Argo CD 的另一个差异：Fleet 原生按「一组集群」为投放目标设计，而 Argo CD 的批量化靠 ApplicationSet（`CI-CD/Argo-CD-部署与使用详解.md` §12）。
- ❗ 实战备注（引用 Rancher 文档 §8 FAQ，不重复）：在 **Cilium kube-proxy 替换模式**下，NodePort 由 eBPF 实现，`ss`/`iptables` 看不到监听与规则、`curl 127.0.0.1:<NodePort>` 一定不通——测接入一律用节点内网 IP 或公网 IP。这个坑在任何「Cilium + NodePort 暴露管理面」的组合里都适用（含 §3.1 的 Cluster Mesh apiserver NodePort 形态）。

### 2.2 OCM（Open Cluster Management）：hub-spoke 的「hub-kubelet」镜像

OCM 是开源的 hub-spoke 多集群控制面（Red Hat 的商业版 **ACM（Advanced Cluster Management for Kubernetes）** 是其下游发行，概念一一对应），当前版本 **v1.4.0**。官方架构页原话点题：它吸取 kubefed v2「中心、指令式」的失败教训，**复刻 K8s 自己的 hub-kubelet 模式**——hub 类比 apiserver，每集群一个 **klusterlet** 类比 kubelet，hub 只「持久化处方」，klusterlet 主动拉取处方并 reconcile 本集群。

概念链（背下来就是 OCM 的全部入门）：

```
Hub 集群（轻量，跑 cluster-manager / registration / placement / work）
   │
   │  ManagedCluster 对象：一个对象 = 一个被管集群（double opt-in 注册，
   │    hub 侧要「批 CSR + 接受集群」两权合一，防未受邀注册）
   │  cluster namespace：Hub 上每个被管集群一个命名空间，既是它的
   │    「处方收件箱」（写 ManifestWork 进来就是下发），也是它的上报区
   │  Placement → PlacementDecision：用 label/clusterClaim 选出目标集群清单
   │    （纯「决策」，与执行解耦；后续的 ManifestWork/ManifestWorkReplicaSet
   │     消费这份清单）
   │  ManifestWork：写进 cluster namespace 的「一批 K8s 资源」，
   │    work agent 在目标集群 apply（SSA 语义下发）
   ▼
Klusterlet（跑在被管集群里的 agent：registration + work 两大件）
   └─ add-on（cluster-proxy 反向隧道（基于 konnectivity）、policy 框架、应用生命周期…
             全部走 ClusterManagementAddOn / ManagedClusterAddOn 两个 API 注册）
```

上手形态（官方 quickstart，2026-10-14 核实）：`clusteradm` CLI + 官方脚本一键起 kind 三集群环境：

```bash
curl -L https://raw.githubusercontent.com/open-cluster-management-io/clusteradm/main/install.sh | bash   # 装 clusteradm
curl -L https://raw.githubusercontent.com/open-cluster-management-io/OCM/main/solutions/setup-dev-environment/local-up.sh | bash
```

- **生态定位一句话**：OCM 的 API 面比 Karmada 更「平台工程向」——ManifestWork 偏「下发就不怎么管调度」，Placement 与 policy/addon 框架才是撒手锏；**做「合规/策略分发 + 多云集群运维」的 hub 首选**，做「把 Deployment 按 HA 拓扑智能铺开」的编排则 Karmada 更对味（§2.3）。
- 扩展阅读：`OCM 官方架构页`（§十一）对「为什么不直连被管集群、为什么双向认证、为什么 cluster namespace」的论证，本身就是一份多集群设计的优秀文献——读它等于上一节设计课。

### 2.3 Karmada：K8s 原生 API 风格的多集群编排（本章重点）

Karmada 自述定位（README 原话）：**延续 Kubernetes Federation v1/v2 的概念，做成「K8s 原生 API + 自带调度器」的多集群编排系统**，CNCF **毕业项目**。当前 stable **v1.19.0**（v1.20 在 alpha）。

**控制面形态**（官方 installation 页核实）：控制面组件装在一个叫 host cluster 的普通 K8s 集群（kind 都行）里，组件清单：`karmada-apiserver`（独立 apiserver，**不是** host 的）+ `karmada-etcd`（StatefulSet）+ `karmada-controller-manager` + `karmada-scheduler` + `karmada-aggregated-apiserver` + `karmada-webhook`（另外带一份 `kube-controller-manager` 用于命名空间/回收等基础控制循环）。**它给每个租户一个「很像 K8s 的 API 面」**——你 kubectl 直接用 `Deployment/Service/Secret` 这些**原生类型**写进 karmada-apiserver，不需要 federated 模板 CRD——这是 Karmada 相对 kubefed 最核心的设计分野（官方 README 首页就是「K8s Native API Compatible / Zero change upgrade」）。

**对象链**（记三层）：

```
你的 Deployment（写进 karmada-apiserver，原生 apps/v1）
   │
   ├── PropagationPolicy / ClusterPropagationPolicy（ns 级 / 集群级）
   │     placement.clusterAffinity 选集群；replicaScheduling 决定
   │     Duplicated（每集群全量）还是 Divided（拆分+权重）
   │     ──► ResourceBinding（policy controller 生成，1 工作负载 : 1 binding）
   │            ──► karmada-scheduler 给 binding 打分选集群（多集群调度器）
   │            ──► Work（binding controller 生成，每目标集群一个，
   │                  落在该集群的 execution space：karmada-es-<cluster>）
   │                     ──► execution controller 按 Push/Pull 下发
   │
   └── OverridePolicy / ClusterOverridePolicy
         按集群改差异位（镜像仓库前缀、时区、Region 参数、StorageClass…）
```

- **Push 模式**：karmada 控制面直连成员集群 apiserver 下发（同机房、网络直通）；`karmadactl join member1 --kubeconfig=<karmada kubeconfig> --cluster-kubeconfig=<member kubeconfig>`（官方 cluster-registration 页逐字核实）。
- **Pull 模式**：成员集群里跑 **karmada-agent**，主动到 karmada-apiserver 拉 `karmada-es-<cluster>` 名下的 Work 再本地 apply——NAT/防火墙后、边缘、大规模集群的推荐模式；用 `karmadactl token create --print-register-command` 在控制面生成引导串，到成员集群执行 `karmadactl register <karmada-apiserver:port> --token ... --discovery-token-ca-cert-hash sha256:...`（官方页例值略改）。`kubectl get clusters` 的 MODE 列会标 `Push`/`Pull`。
- **自带调度器**：`karmada-scheduler` 是多集群层面的 schedule（对 ResourceBinding 选集群、rebalance、failover），与第 2 章的 kube-scheduler 是两层——它不挑节点，挑集群。
- **兼容矩阵**（README 官方表，2026-10-14 核实）：v1.19 兼容到 K8s 1.36（1.37 尚未列入矩阵）——**在 v1.37 成员集群上实验属「未验证组合」**，生产稳一手选 ≤1.36 或等矩阵更新（与 Rancher 文档的版本矩阵提醒同款纪律）。

最小 PropagationPolicy（官方 samples/nginx 逐字，实验 10.1 直用）：

```yaml
apiVersion: policy.karmada.io/v1alpha1
kind: PropagationPolicy
metadata:
  name: nginx-propagation
spec:
  resourceSelectors:                  # 选中哪些「原生」资源（apiVersion+kind+name）
    - apiVersion: apps/v1
      kind: Deployment
      name: nginx
  placement:
    clusterAffinity:
      clusterNames: [member1, member2]        # 目标集群清单
    replicaScheduling:
      replicaDivisionPreference: Weighted     # 多集群调度策略（Divided+权重 拆副本）
      replicaSchedulingType: Divided
      weightPreference:
        staticWeightList:
          - targetCluster: { clusterNames: [member1] }
            weight: 1
          - targetCluster: { clusterNames: [member2] }
            weight: 1
# 常用另一形态：replicaSchedulingType: Duplicated（每个集群全量一份，
#   适合 active-active 基础组件/系统组件下发）
```

**进阶三句话（落地前读一遍）**：

1. **failover 靠集群污点触发**：成员集群失联/不可用被打上污点（`cluster.karmada.io/not-ready` 系），karmada-scheduler 据此对该集群上承载的 ResourceBinding 做 rebalance，把负载「迁移」到健康集群——前提是你的工作负载本身无状态、且 **failover 前的摘除窗口**是可配参数（控制面组件 tolerationSeconds 级）。有状态负载别赌 failover，走「数据层复制 + 主备」方案（§8.1 铁律 7）。
2. **别把「集群级差异」塞进工作负载 YAML**：镜像仓库前缀、Region/zone 拓扑键、StorageClass、Ingress 域名等「每集群一份」的字段，全部走 **OverridePolicy/ClusterOverridePolicy**——它是「按集群 patch」的原生答案。形态：

   ```yaml
   apiVersion: policy.karmada.io/v1alpha1
   kind: OverridePolicy
   metadata:
     name: nginx-override
   spec:
     resourceSelectors:
       - apiVersion: apps/v1
         kind: Deployment
         name: nginx
     overrideRules:
       - targetCluster: { clusterNames: [member1] }
         overriders:                        # 镜像拉取前缀按集群替换（例：离站仓）
           imageOverrider:
             - component: Registry
               operator: replace
               value: registry.cn-hangzhou.aliyuncs.com
   ```

3. **不要一揽子把 K8s 集群级对象下发**：CRD/PSA 标签、ClusterRole、StorageClass、NetworkPolicy 这类「地基配置」先走一遍「它们在每个集群已经一致吗」的审计——Karmada 只管「按 policy 铺」，不加「这个 CRD 在 v1.35 集群有没有对应版本」的智能（config 一致性是 §1.1 的主矛盾；批量地基配置更建议交给 Rancher/Fleet 或 Argo ApplicationSet 分层下发）。

### 2.4 Federation v1/v2 退役史：一段必要的「为什么不再用」

- **Federation v1**（2016 随 K8s 1.x 推出）：一套独立 apiserver + federated 类型，2019 前后终止。
- **Federation v2 / kubefed**：CRD 化的「template + placement + override」三件套，为**每一个** K8s 原生资源生成一份 `FederatedXXX` CRD——初衷是「不改 K8s 就能联邦」，现实是：**生态分裂了**。Helm、kubectl plugin、GitOps、controller 全部只认原生类型，`FederatedDeployment` 是另一个世界；中心控制面 push-only 直连所有集群，可达性与扩展性两难（OCM 架构页把这叫「legacy centric, imperative」）。GitHub 仓库已在 **2023 年归档退役**（迁入 `kubernetes-retired/kubefed`，archived=true，最后代码活动停在 2023-03）。
- 它的**概念遗产**保留在今天的每一件产品里：Karmada 的 PropagationPolicy/OverridePolicy 就是 template+placement+override 的「不离线版」；OCM 的 Placement/ManifestWork 是「决策与执行解耦」的修正版；GitOps 的 cluster 生成器（ApplicationSet）则是「不要在控制面再造 API，把分发交给 git 流水线」这条第三条路。**学这段史的价值：下次再遇到「给所有原生资源造一层 XX 版」的方案，你会秒判死刑。**

### 2.5 对比决策表（按你在意什么选）

| 维度 | Rancher + Fleet | OCM（v1.4.0） | Karmada（v1.19.0） | Argo CD + ApplicationSet |
|------|-----------------|---------------|---------------------|--------------------------|
| 控制面形态 | 宿主集群 + 下游 cattle-cluster-agent pull | Hub 集群 + klusterlet pull（hub-kubelet 镜像） | 独立 karmada-apiserver/etcd + controller-manager + scheduler | 无 hub 形态；控制面在 Argo 实例，集群作 destination |
| API 侵入性 | UI/CR 层（cattle/fleet 体系） | ManagedCluster/Placement/ManifestWork/Addon | **原生 K8s 类型 + policy CRD**（侵入性最低） | 原生 K8s 类型 + Application/ApplicationSet |
| 核心能力 | 多集群生命周期/UI/RBAC/目录/GitOps(Fleet) | 治理/策略/注册/插件式 addon 框架 | 负载编排/副本拆分/failover/原生调度 | 流水线发布到多集群的 GitOps |
| 调度能力 | 无（按组投放） | Placement（选集群纯决策） | **自带 karmada-scheduler（多集群调度）** | 无（生成器按列表/标签） |
| GitOps 贴合 | Fleet 内建 | 建议叠加 Argo/Flux（官方有 integration） | 可叠加；或「git→karmada-apiserver」流水线 | **就是它自己** |
| 生态/社区 | 商业味道浓、量大 | CNCF 项目、Red Hat 背书（ACM 下游） | CNCF **毕业** | CNCF 毕业、事实标准 |
| 供应商绑定 | 绑定 Rancher 体系 | 无 | 无 | 无 |
| 上手成本 | 低（UI 驱动） | 中（概念多；clusteradm 一键可试） | 低-中（init + join + 一条 policy） | 低（你已会 Argo CD） |
| 适合一句话 | 「我要一个统一管几十个集群的门户」 | 「我要合规/策略/注册向的 hub 平台」 | 「我要把 Deployment/Job 智能铺到多集群」 | 「我要发布流水线多环境多集群化」 |

> ★ 常见组合（生产会这样叠）：**Argo CD/Karmada 二选一管「工作负载」+ OCM/Rancher 二选一管「集群治理」+ CAPI 管「集群生命周期」**——三件套正交，不是竞品。选型会吵起来多半是把这三层混为一谈。

### 2.6 你这台 Rancher 的第一步（结合仓库现状的落地路径）

已经有 Rancher v2.15.2 在跑（`脚本与工具/Rancher部署文档.md`，Cilium kube-proxy 替代模式），恭喜——**P3 的治理面你最便宜**：

1. **先把「第二集群」纳管进来**：随便一个 kind/L2 试验集群走 Import Existing（agent 回连，§2.1）——验证「能管两个集群」不依赖任何新组件，只依赖 Rancher 自己；
2. **Fleet 派发一个全局 baseline**：GitRepo 底下把 NetworkPolicy baseline/ResourceQuota 模板/PSA 标签脚本化推到两集群（这就是 §1.1 config 一致性的第一块砖）；
3. **再谈「多集群调度」**：两份集群里同一 Deployment 各放一份，与 Karmada PropagationPolicy Divided 的语义差距，在你的规模（≤3 集群）上 **85% 能被 ApplicationSet/Fleet 覆盖**——把 Karmada 当需要「算副本拆分/failover」时再加的件，不是现在。

> ❗ 反向提醒：Rancher 上「创建集群」（RKE2/K3s provision）与 §四 CAPI 是同类事——**选一个就好**（有 Rancher 就先吃透 Rancher provision，CAPI 读完即可，别并行两套机器生命周期）。

---

## 三、多集群 Service 与流量

### 3.1 方案谱：按「离应用多近」排序

```
离应用近 ────────────────────────────────────────────────► 离网络近
 应用入口层         服务发现层           数据面连通层         网络直连层
┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────┐
│ 云多集群入口  │ K8s MCS-API   │ Submariner    │ Cilium          │
│ (LB/GSLB/   │ (ServiceExport │ (Lighthouse + │ Cluster Mesh    │
│ Global GW/  │  /Import 规范)  │  gateway+VXLAN)│ (扁平 Pod 空间)  │
│ 多集群 GW)  │   厂商各自实现   │   Globalnet 兜底│  +Global Service │
└──────┬──────┘ └──────┬───────┘ └──────┬───────┘ └───────┬────────┘
       ▼ 适合：对外流量 │ 适合：跨集群   │ 适合：异构 CNI/  │ 适合：同 CNI
       主备/就近多活    │ service 语义   │ 跨云 CIDR 可重叠 │ 互信集群全互联
```

- **云多集群入口（最贴应用）**：对外流量先在「GSLB/全局 LB」这一层分流到集群（AWS Global Accelerator/Cloud DNS/阿里全局流量管理…），集群内的入口再用 Gateway API/Ingress（云厂商的 MCI/GKE Multi Cluster Ingress 实现，属第 3 章 §七 Gateway API 的延伸形态，一句引不展开）。这是**主备与就近多活的第一块积木**，对应用零侵入、灰度/摘除粒度粗。
- **K8s MCS-API（SIG-Multicluster，KEP-1645）**：`ServiceExport`/`ServiceImport` 两个 CRD + `clusterset.local` 域的多集群服务发现规范。规范在场多年，但**数据面各干各的**：Cilium 自维护了一份 MCS-API 实现（clustermesh/mcsapi 页），阿里 ACK One/华为 UCS 等云多集群服务也陆续兼容——把它当「协议约定」而不是「开箱产品」。
- **Submariner（v0.24.x stable；0.25/0.26 预发布）**：broker 集群登记各集群 → 每集群选 gateway 节点建直通隧道（默认 WireGuard，可选 Libreswan/IPsec）→ Lighthouse 提供跨集群 DNS（`clusterset.local`）。**杀手锏 Globalnet：专门处理 Pod CIDR 重叠**，把重叠网段 NAT 成全局唯一段——这是「异构 CNI/多云合并存量集群」场景的兜底王；代价是 NAT 贵一层、观测链复杂一层。
- **Cilium Cluster Mesh（Cilium 1.20.x 官方页核实）**：**要求是各集群互信（单一信任域）、Cilium 同 CNI、Pod CIDR 不重叠**。架构：每集群一个 `clustermesh-apiserver`（内含 etcd + apiserver + kvstoremesh 三容器，官方 intro 页逐字核实），经 mTLS 相互 `expose` 本地状态；Pod-to-Pod 直连不经过网关。提供：跨集群 Global Service（注解 `service.cilium.io/global: "true"`，同一同名 Service 在多集群聚合负载均衡）、`service.cilium.io/shared: "false"` 控制「进口不出口」、affinity 控制（prefer local/remote）、cluster-aware NetworkPolicy。官方 Limitations（2026-10-14 核实，两条最容易踩）：**Global NodePort / host-network 访问要 kube-proxy 替换模式才走全集群负载**（否则只本地后端；hostNetwork 可开 SocketLB 补）——Cilium kube-proxy 替换的部署建议见 Rancher 文档同款坑位备注（§2.1）。
- **云方案**：AWS VPC Lattice（service network 抽象，跨 VPC/跨账号）、阿里 ACK One 舰队（多集群服务发现+流量）、华为 UCS（多集群/多云）。共同特征：**产品化完成度最高、绑定也最深**——多云想守住中立性时慎用。
- **Istio multi-cluster**：sidecar 形态成熟度领先、Ambient 多网络多集群目前 Beta 且有拓扑限制——`Istio详细入门与实践指南.md` 里已给出结论，此处一句引不重复（用服务网格做身份/流量策略的群体读本篇那节）。

### 3.2 跨集群 Service 的三段式设计点（设计检查单）

| 段 | 关键问题 | 推荐设计点 |
|----|---------|-----------|
| **服务发现** | 消费方怎么知道「这个服务在远程集群也有」？ | 单一权威源：MCS-API `ServiceExport/Import` 或 Cilium Global Service 注解；**禁止「靠人脑记住哪个集群有哪个 Service」**——进入拓扑目录（§8.1） |
| **流量路由** | 本地优先还是全局负载？失败怎么降级？ | 默认 affinity 本地优先（Cilium 的 preferred local），跨集群当「容量延伸」；主动健康检查必须能反映「远端整簇失联」而不是「某后端不答」 |
| **故障摘除** | 一整簇失联时多快剔除？ | Cilium 现提供 `clustermesh.cacheTTL`（失联超时后撤销远端 cached 状态，例 `--set clustermesh.cacheTTL=15m`，官方 global-services 页核实）；主备/入口层靠外部 DNS 健康探针+TTL 设计（秒级）+ failover 演练（§3.3） |

> ❗ 一句话：**跨集群的服务发现是「做一张全局表」，而故障摘除是「给这张表一个保质期」。** 多数多集群流量事故都死在后者——通是通了，半失联的集群还在收流量。

### 3.3 mini 案例：主备 failover 演练 runbook（把「故障摘除」练成肌肉）

场景（形态甲，§1.4）：主集群 A + 备集群 B + 外部 DNS 健康切换 + GitOps 双 destination；目标 SLA「整簇失联 → 100% 流量走 B ≤ 90s」。演练步骤：

```bash
# step 0 基线记录（备集群 B 的热备真的健康吗——这一步每季跑一次，别等出事）
kubectl --context cluster-b get deploy,pod -n prod
curl -s -o /dev/null -w '%{http_code}\n' https://standby.probe.example.com/readyz   # B 侧专用探活域
# step 1 破坏：停掉 A 的入口（kind 形态等效：scale ingress controller 到 0
#   或断开 ingress LB 健康探针指向的目标；生产用 LB/DNS 控制台模拟）
kubectl --context cluster-a -n ingress-nginx scale deploy ingress-nginx-controller --replicas=0
# step 2 外部视角：探针失联 → DNS 切除 A（记录时间戳，手动/自动都行）
date; dig +short api.prod.example.com                # 应切到 B 的 LB IP（TTL 设计值内）
# step 3 业务视角：全套 smoke 走 B
curl -s -o /dev/null -w '%{http_code}\n' https://api.prod.example.com/api/health    # 200，来自 B
kubectl --context cluster-b get pods -n prod                                          # B 承流量，Pod 健康
# step 4 回切（最重要的一步，别漏）：恢复 A → 探针回绿 → DNS 切回 A → 确认全回
kubectl --context cluster-a -n ingress-nginx scale deploy ingress-nginx-controller --replicas=2
dig +short api.prod.example.com                      # 回 A；观察抖窗期有没有 5xx
```

判据与教训（写进复盘）：

- **DNS TTL 与探针间隔的乘积 = 摘除下限**——SLA 90s 就要求 TTL ≤ 60s 且探针 ≤ 30s；TTL 300s 的「运维厚脸」会让最好看的 mesh/ingress 一切归零。
- **B 的热备要在演练前先死一次**：常态下没人看备集群，99% 的 failover 失败发生在「B 早就悄悄地坏了」（PVC 没同步、镜像仓拉不动、PSA 标签漏配——全部是 §1.1 config 一致性的欠债）。
- **切回比切出危险**：峰值流量一刀回到才醒过来的 A，冷缓存/连接池/扩容全部在同一秒发生——用「先 5% 灰度」而不是「一步到位」；第 9 章 HPA 的启动保护在这里同样适用。

---

## 四、Cluster API（CAPI）：「Kubernetes 管 Kubernetes」

### 4.1 一句话与四个 Provider 家族

§二/§三解决的是「现成集群怎么管」，CAPI 解决的是「**集群本身怎么以 YAML 的形式声明、创建、升级、修复**」——它就是「cluster 层级的 Deployment 控制器」。一台「管理集群（management cluster）」上装 CAPI，工作负载集群（workload cluster）作为 CR 被 reconcile 出来。

四个 Provider 家族（控制器 + API 的插件化包）：

| 家族 | 缩写/实例 | 管什么 |
|------|-----------|--------|
| **Core** | capi-controller | `Cluster`/`Machine`/`MachineDeployment`/`MachineSet`/`MachineHealthCheck` 的本体控制循环 |
| **Bootstrap** | CABPK（Kubeadm bootstrap provider） | 生成 kubeadm join 用的 cloud-init（每 Machine 一份 bootstrap config secret） |
| **Control Plane** | KCP（KubeadmControlPlane） | 控制面机器的生命周期：init 第一台/滚动升级/证书随机器更换再生成/etcd 成员健康与修复（含 remediation）/扩缩容 |
| **Infrastructure** | CAPA(AWS)/CAPZ(Azure)/CAPV(vSphere)/CAPO(OpenStack)/CAPG(GCP)/metal³/KubeVirt/Proxmox… CAPD(Docker，仅实验) | 把 `Machine` 翻译成真实的 VM/裸机/容器节点（镜像/网络/负载均衡/安全组的 reconcile） |

> 完整 infra provider 名录：`clusterctl init --list-infrastructure` 现场列；社区表格维护在 CAPI book 的 provider 页（§十一）。

### 4.2 对象继承：Machine ↔ Pod 的隐喻（官方隐喻，背下来）

```
Cluster（一个工作负载集群）
  └─ InfrastructureCluster（AWSCluster 等：VPC/LB/网络）
  ├─ KubeadmControlPlane ──> Machine（×3 控制面副本）
  │                            └─ InfrastructureMachine（AWSMachine 等）
  │                            └─ KubeadmConfig（每个的 cloud-init）
  └─ MachineDeployment（worker 组）      ≈ Deployment
       └─ MachineSet                     ≈ ReplicaSet
            └─ Machine × N               ≈ Pod
                 └─ InfrastructureMachine + KubeadmConfig
```

对上这张表，第 1/2/6 章学到的全部机制（ownerReference/finalizer/reconcile 幂等/滚动策略/健康检查）原样生效——**CAPI 的阅读成本不在于「新学多少概念」，而在于把已知概念投影到「机器」这个领域**。`MachineHealthCheck` 对应于「Pod 健康检查 + remediation」：不健康机器被替换（先 drain 再删，详见第 7 章/第 8 章域二）。

CRD 多版本机制底座：工作集群里的 CAPI 对象跨版本（v1beta1→v1beta2）迁移用的就是第 6 章 §3 的 conversion webhook + storedVersions 演练同一套；**v1.14 官方公告 v1beta1 将在 v1.16 停止 serve**（生产尽早上 v1beta2；CAPD 更激进：Docker* 资源 v1.15 就要移除，转向 Dev*/in-memory 后端——capi v1.14.0 release notes 原文）。这是「机器侧资源也吃 K8s 版本治理」的现成教材。

`MachineHealthCheck`（MHC）就是「机器层的探针 + 自动替换」的声明形态（读 YAML 一次就够，逻辑与 Pod 探针同构）：

```yaml
apiVersion: cluster.x-k8s.io/v1beta2
kind: MachineHealthCheck
metadata:
  name: worker-node-health
spec:
  clusterName: capi-quickstart
  selector:
    matchLabels: { nodepool: workers }
  unhealthyConditions:                  # 哪些 Node 条件算「病」
    - type: Ready
      status: Unknown
      timeout: 300s
    - type: Ready
      status: "False"
      timeout: 300s
  maxUnhealthy: 40%                     # 病号比例闸：超线就暂停自动替换（防雪崩）
  remediationTemplate:                  # 替换动作 = 删掉旧 Machine 让 MD 补新的
    apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
    kind: DockerMachineTemplate
    name: worker-remediation-template
```

### 4.3 KubeadmControlPlane（KCP）到底管什么

KCP 是 CAPI 里最「运维向」的控制器，面试题答这三行就够 80 分：

1. **控制面副本的生命周期**：按 `KubeadmControlPlane` 的 `replicas`/`version` 维护控制面机器组；需要变更时**滚动替换**而不是原地改（immutable infra 哲学的落地）。
2. **etcd 成员健康**：控制面机器与 etcd 成员是「同一台的两个身份」——v1.14 线持续在做 leadership forwarding / 部分失败下的成员清理（v1.14.0 release notes：「improve forward etcd leadership」「cleanup not started etcd members」），确保「半起不来的 etcd 成员」能被安全修复。
3. **证书与 join 一致性**：控制面证书随机器轮换重新签发，新 join 的机器拿到与集群当前 CA 一致的配置（底层仍是 kubeadm，第 7 章 §1 全部约定复用）。

手操 ↔ 自动件对照（读完第 7 章再看 KCP，就是这张表）：

| 第 7 章你的手操 | KCP 里的自动件 |
|-----------------|----------------|
| `kubeadm init` 第一台控制面 + `join --control-plane` 后两台 | `KubeadmControlPlane.replicas` reconcile 出 N 台 Machine |
| `kubeadm upgrade apply/node` + `kubectl drain` 滚动 | 控制面 Machine 滚动替换（新镜像/新版本新机，老机 drain 后退场） |
| `kubeadm certs renew` + 静态 Pod 重启三件套 | 证书随机器更换整体重签（换机即换证，天然轮转） |
| etcd 成员失联时 `member remove/add` | etcd 成员健康检查 + remediation（含未就绪成员清理） |
| Machine 故障人工替换 | `MachineHealthCheck` 标记 + remediation 自动替换 |

> ★ 一句心法：**CAPI 把「第 7 章的 kubeadm 运维手册」自动化了**。你 kubeadm 会做的事（init/join/证书/升级/drain），CAPI 的每个控制器都在自动做同一件事——读懂它的最快方式就是把自己代入「CAPI 在做我平时哪一步手工」。

### 4.4 CAPI × GitOps 为什么是孪生

- CAPI 的所有对象都是 **普通 YAML**。放进 git → Argo/Flux 同步到管理集群 → provider 自动执行——**「集群舰队清单」= 一个 git 目录**，漂移检测、评审、回滚全部复用流水线。
- 没有 GitOps 的 CAPI 是「clusterctl 命令行玩具」；没有 CAPI 的 GitOps 只能管「集群里的东西」，管不了「集群本身」。**ClusterClass**（带参数的集群模板）把「同一形态的集群」进一步模板化，配合 ApplicationSet 的 clusters 生成器（`CI-CD/Argo-CD-部署与使用详解.md` §12）可以写出「按 git 目录文件决定集群存在性」的完整闭环。
- 变量化注入：`Cluster` spec 用 variables + patches（ClusterClass 支持对 metadata.labels/annotations 等动态打补丁，v1.14 更稳），把「一个模板 + N 份 values」这台戏继续标准化。

### 4.5 现状与版本（2026-10-14 核实）

- 当前 GA 线 **v1.14.3**（v1.14.0 系列后热度集中在 etcd leadership/内存瘦身/安全）——管理集群支持 **v1.33.x → v1.37.x**，负载集群支持 **v1.31.x → v1.37.x**（release assets 页连体注记）：也就是说，你的 v1.37 kind 管理集群被官方支持。
- 主线开发 API 已是 **v1beta2**；v1beta1 按计划 v1.16 上线后停 serve（§4.2 已给迁移时间表）。
- **cluster-api-operator v0.29.0**（官方仓库 release）：提供 `CoreProvider`/`InfrastructureProvider`/`BootstrapProvider`/`ControlPlaneProvider` 等 CR 来声明式安装与升级 provider——GitOps 党喜闻乐见；它当前 pin 的核心 CAPI **还停在 v1.13.5**（自己的能力矩阵「慢 core 一拍」是常态，装之前查 README 的对应表）。**结论一句话**：`clusterctl init` 仍是评测/实验主线，operator 是 GitOps 生产化入口但先核版本对应。
- 学习路径建议（实验 10.3 就是它的第一步）：kind 起管理集群 → `clusterctl init --infrastructure docker` → `clusterctl generate cluster` 出一份完整 Cluster YAML——**读 YAML 不真正 apply 也够这章的教学目标**；然后上真 infra provider（你有 Proxmox/云的现成靶场）。CAPD 属**测试 provider**，v1.15 起 Docker* API 要移除，别在生产路径上留依赖，实验照常用（它 deprecation 规则对 CAPD 有豁免条款）。

---

## 五、设备管理与 GPU

### 5.1 Device Plugin 框架：kubelet 眼里的一切「扩展设备」

只要「CPU/内存之外的可调度资源」，基本走 Device Plugin 框架（官方概念页：`kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/`）：

```
厂商插件 DaemonSet（每个节点一个 Pod）
   │ ① 启动：向 kubelet 的 device-plugin sock 注册自己（gRPC）
   │
   │ ② ListAndWatch（长连接 push）：本节点有哪些设备、健康状态变化
   │      ──► kubelet 上报 node.status.allocatable：nvidia.com/gpu: 8
   │           这就是「extended resource」——与 cpu/memory 并列的调度资源
   │
   │ ③ Allocate（Pod 落节点时）：返回 env（NVIDIA_VISIBLE_DEVICES）+
   │      设备节点挂载 + 运行时注解 → 容器启动拿到设备
   ▼
kubelet 决定 Pod 的 requests/limits 里 nvidia.com/gpu: N 能不能兑现
```

配套两件套（**不要和 device plugin 混淆**）：

- **NFD（Node Feature Discovery）**：按硬件特征规则（PCI ID/内核能力）给 Node 打标签/扩展资源——`NodeFeatureRule` CR 是其规则单元；NVIDIA 的 GFD（GPU Feature Discovery）内置在 device plugin chart 里产出同款 NodeFeature。
- **extended resource**：`kubectl describe node` 里 `Capacity/Allocatable` 里的非 cpu/memory/ephemeral-storage 项。调度器把它当**整数计数**对待（8 块卡就是 8 个 quota）——这就是「为什么 GPU 调度入门第一课看上去跟 CPU 一样」。

### 5.2 NVIDIA 生态一条龙（2026-10-14 核实版本）

| 件 | 版本形态 | 干啥 |
|----|---------|------|
| NVIDIA 驱动 + Container Toolkit | 节点包（gpu-operator 也能代管驱动） | 容器化 CUDA 的运行时底座 |
| **k8s-device-plugin** | **v0.20.1**（helm chart 同号） | 上报 `nvidia.com/gpu`，处理 Allocate，内置 GFD（NodeFeature）、可配 MIG 发现 |
| **gpu-operator** | **v26.7.x**（版本已改日历式 25.x/26.x 系列） | 上面全部 + DCGM 监控 + MIG Manager + driver/toolkit 全包 one-shot helm |

```bash
# 单装 device plugin（驱动/toolkit 节点自带时）
helm repo add nvdp https://nvidia.github.io/k8s-device-plugin && helm repo update
helm upgrade -i nvdp nvdp/nvidia-device-plugin \
  --namespace nvidia-device-plugin --create-namespace --version 0.20.1

# 一把梭 gpu-operator（节点只装标准 OS 时——官方 README Quick Start 逐字：
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
helm install --wait --generate-name \
  -n gpu-operator --create-namespace \
  nvidia/gpu-operator
```

> gpu-operator 官方 Roadmap 原话值得注意两条：**NVIDIADriver CRD 奔 GA**（把驱动也 CRD 化）；**集成 NVIDIA k8s-dra-driver-gpu 为受管组件**（DRA 从选装走入默认路径，见 §5.4）。

### 5.3 GPU 共享的四种姿势（隔离 × 成本 两维对比）

| 方案 | 粒度与隔离 | 代价/硬件门槛 | 适用画像 |
|------|-----------|--------------|---------|
| **TimeSlicing（时间片复用）** | 把 1 块卡暴露成 N 个 extended resource（例 `nvidia.com/gpu: 8` 虚出），N 个 Pod 轮转用 | 显存不隔离/起落互相抢；0 硬件门槛；配置就在 device plugin 一份 ConfigMap | CI/调试/低负载推理开发环境；**生产带 SLA 的推理别用** |
| **MIG（Multi-Instance GPU）** | A100/H100/B200 把一块卡切 ≤7 个硬隔离实例（独立显存/SM/缓存） | 仅高端数据中心卡；切分需要 MIG Manager 或离线切换 | 多租户训练/推理平台；**「密度 + 隔离」唯一正解** |
| **MPS（Multi-Process Service）** | CUDA 层的进程并发：多进程共享一个卡的上下文间并行 | 显存共享、故障域同卡；比 TimeSlicing 更「真并行」、隔离不及 MIG | 批任务密度提升；与 MIG 可叠加（MIG 内再 MPS） |
| **vGPU（NVIDIA vGPU）** | 虚拟化层切分，VM 级隔离 | 需 NVIDIA vGPU 授权（License Server） | 需要 VM 级边界的托管/VDI 场景 |

MIG 在 K8s 侧的呈现细节：device-plugin v0.20+ 把带 `-me`/`+me.all`/`+gfx` 后缀的 profile **拆成独立 extended resource**（v0.20.0 changelog 原话），调度感知更强；`mixed`/`single` 两种 MIG 策略由 gpu-operator 的 MIG Manager 管理（切换要 drain 节点）。

### 5.4 DRA：设备管理的下一个形态（接力第 2 章 §11.2，不重复机制）

Dynamic Resource Allocation：**v1.30 以 Alpha 入场，v1.35 起 Stable/GA 且默认开启（锁定，不可关）**——版本口径以第 2 章为准。第 2 章 §11.2 已给它对**调度链路**的六条影响，本章只补「设备管理员」视角的三句话：

1. **从「数个数」到「挑对象」**：Device Plugin 的 GPU 是 `nvidia.com/gpu: 8` 的计数；DRA 的 `ResourceClaim` 是「给我一块 40GB+ 显存、NVLink 同卡槽的 A100」的**属性选购**（CEL 表达式写在 `DeviceClass` 上；驱动侧发布 `ResourceSlice`）。
2. **NVIDIA 官方 DRA 驱动在场且正在被 gpu-operator 收编**：`NVIDIA/k8s-dra-driver-gpu` 项目由官方 Roadmap 列为「将变为 gpu-operator 受管组件」（§5.2）——结论：**今天装 device-plugin 没问题，design doc 里把 DRA 设为明年路线**。
3. **动态特性记住两条**（第 2 章已给）：**分配是延迟的**（选中节点才真正 allocate，bind 前等 BindingConditions）；**DRA 资源不参与抢占**——高优 Pod 撞上被占 DRA 卡只能等。设计配额与抢占组时把这两条钉在墙上。

### 5.5 配额治理与成本（GPU 集群的「第二块表」）

- **ResourceQuota 直接管 extended resource**：`spec.hard: limits.nvidia.com/gpu: "20"`——租户 GPU 闸就这么配；GPU 必然整卡计数，「核数级拆租」归 MIG 的粒度而不是 Quota。
- **PriorityClass 配套**：GPU 队列前排业务用高 PriorityClass，系统/管理件用 system-cluster-critical/system-node-critical（第 7 章 §8.2 的数字），**别让训练队列把监控挤下线**。
- **GPU 空闲成本提醒（生产第一条）**：A100/H100 云端的时租量级意味着「空闲 10% 的卡 > 一个普通集群整月」——平台侧标配：①每租户配额 + 利用率仪表板（DCGM）；②空闲回收策略（activeDeadlineSeconds/idle reaper）；③TimeSlicing/MIG 的密度规划（**便宜的不是卡，是卡的利用率**）；④配合第 9 章 Karpenter/CA 的 GPU NodeClass 做「用完即还」。
- ❗ 踩坑预告：**Pod 申请 `nvidia.com/gpu` 只允许写在 limits 侧**（K8s docs 与 device plugin 示例一致：requests 要么不写让默认等于 limits，要么显式等于 limits；写成 limits > requests 会被拒）——别踩 Burstable 写法；且 `nvidia.com/gpu` 只能整卡/整 MIG 实例计数，无上小数。

### 5.6 GPU 常见生产问题清单（症状 → 根因 → 处理）

| # | 症状 | 根因（按出现率排） | 定位与处理 |
|---|------|--------------------|-----------|
| 1 | Pod Pending：events `Insufficient nvidia.com/gpu` | ①节点没上报 extended resource（device plugin 没跑/ds 没调度到 GPU 节点）②被占完 ③MIG 切片名写错（`nvidia.com/mig-1g.5gb` ≠ `nvidia.com/gpu`） | `kubectl describe node \| grep nvidia`；`kubectl -n nvidia-device-plugin get pods -o wide`；核对 MIG 资源名 |
| 2 | Pod 起来 `nvidia-smi` 报错 / CUDA driver mismatch | host 驱动与镜像 CUDA 不兼容（驱动太旧） | 驱动 ≥ 镜像 CUDA 要求的最低驱动；gpu-operator 的 driver 容器管理这条路最稳 |
| 3 | `nvidia-container-cli: initialization error` / runtime 找不到 GPU | containerd 没配 nvidia runtime（或 runtimeClass 没指向） | 装 Container Toolkit 并重载 containerd；或直接上 gpu-operator 代管 |
| 4 | 业务 OOM 但报的是「CUDA out of memory」 | 不是容器 OOMKilled——是**显存**爆：batch 过大/共享卡被邻居吃光（TimeSlicing 无隔离） | 看 DCGM 显存曲线；上 MIG 或限流单 Pod 显存预算（应用侧）；别误判为节点内存问题（区分口径同第 8 章 §4.4 两种 OOM） |
| 5 | 队列死锁感：大 job 占全部卡，小 job 排队一周 | 无配额/无优先级分层 | ResourceQuota 硬闸 + PriorityClass（§5.5）；批调度 gang 化见第 2 章 §8（Volcano/Kueue） |
| 6 | GPU 利用率 <20% 但不敢下线 | 无利用率告警、无空闲回收 | DCGM + 仪表板 + idle reaper；一次账单调优往往比一次升学值一个集群预算 |

---

## 六、边缘与 Wasm/Serverless

### 6.1 边缘三条路线（先选「断网自治」边界在哪）

| 路线 | 断网自治 | 形态 | 现状/版本核实 | 适合 |
|------|---------|------|--------------|------|
| **KubeEdge** | 边缘侧 metadata 落盘持久化，断网后边缘自治运行；恢复后增量同步 | CloudCore/EdgeCore 双侧件；tunnel（edgehub/cloudhub）适配私网 | **CNCF Graduated（2024-09-11）**，**v1.23.1**，边缘内存占用官方宣称 ~70MB | 工厂/基站/车载：异构 OS、海量节点、需 IoT 设备面（DeviceTwin） |
| **OpenYurt** | YurtHub 做节点级缓存代理，断网用本地 cache 履约 | **把现成 K8s 集群「转换」成云边形态**（yurtadm join；非侵入），NodePool/YurtAppSet 管多地负载 | **CNCF Incubating**，**v1.7.0**（支持 K8s v1.34；v1.7 引入 K8s-on-K8s） | 已有 K8s 资产不想重造、区域自治 + 多地域负载下发 |
| **K3s 轻量集群** | 每边缘点一个**完整独立**小集群（无外置管面依赖） | 单二进制 + 内置 sqlite；HA 与离线部署见 `容器编排/K3s-部署指南.md` | —（该笔记有 HA/离线专章） | 边缘体量小但要「是真集群」的场景；自治边界最硬，代价是集群数量爆一阶 |

> ★ 选型主问只有一个：**「断网 N 小时后，谁说了算？」** KubeEdge/OpenYurt 的答案是「边缘本地的持久化/缓存层先撑，云回来后 reconcile」；K3s 的答案是「它一直是自己说了算，云只是加了层远程运维」。两派都对——看你的信任边界与运维队伍能吃哪一套。

安全面一句：KubeEdge/OpenYurt 都把「云-边 tunnel」作为默认通道——证书分发/旋转/tunnel 两端的鉴权是边缘方案里的高危面（KubeEdge 用 bootstrap token 换证书，`keadm join` 一套；OpenYurt YurtHub 出向、节点只在私网即可）——与第 5 章/第 7 章 §5 证书体系同标准纳管。

### 6.2 Wasm on K8s 的现状（2026-10-14 严核）

- **KWasm 已退役**：KWasm/kwasm-operator 仓库已 archived（README 原话「KWasm has been retired. This was a fun exploration...」；kwasm.sh 域名只续到 2027-01-20；官方指引的接力项目是 `spinframework/runtime-class-manager`）。**学历史可以，不要在生产上装它。**
- **SpinKube 是当前正路**：`spin-operator` **v0.6.1**（仍 0.x，pre-GA 心态入仓）；形态 = RuntimeClass（containerd shim）+ `SpinApp` CRD + operator；部署形态一句话：**Pod 里是 Wasm 运行时而不是 runc**，冷启动与密度显著优于容器，代价是生态/系统调用/状态的外圈约束——边缘函数、轻量事件处理是它的正位。
- ❗ 心智边界：Wasm-on-K8s 现在是「**特定场景的密度/冷启动优化**」，不是「替代容器」。「Wasm 会不会吃掉 K8s」这类会议标题看看就好，别当真。

### 6.3 Knative 一句话（Serverless 容器范式）

Knative Serving **v1.23.0**：普通容器 → 按请求量自动伸缩到 0 → 冷启动拉起，activator/queue-proxy 套件 + revision 快照；它是「带 ingress 的自动伸缩引擎」，与第 9 章的关系一句话：**KEDA/HPA 管「指标驱动的副本数」，Knative 自带 KPA（Knative Pod Autoscaler）管「到 0」**——到 0 的冷启动成本与第 9 章 HPA 启动保护一起讨论再用。事件侧（Knative Eventing）本章不展开。

---

## 七、虚拟集群与多租户三档谱系

### 7.1 三档谱系（成本 × 隔离）

| 档位 | 控制面 | 隔离边界 | 每租户成本 | 典型场景 |
|------|--------|---------|-----------|---------|
| **namespace（软多租）** | 共享 | RBAC/Quota/LimitRange/PSA/NetPol | ~0 | 同团队/同信任域 |
| **vCluster（硬多租）** | **每租户一套 v 控制面**（API+数据存储容器化） | 独立 API server/CRD/RBAC/etcd；数据面在宿主节点 | 中（每租户一个控制面 + syncer） | 租户要 cluster-admin 但不该碰宿主；CI 流水线；开发沙箱；operator 交付的隔离环境 |
| **物理多集群** | 每簇一套真实控制面 | 全栈独立 | 最高（控制面 ×N + 节点池） | 合规/灾备/边缘/跨商 |

> ❗ 决策口诀：**信任域边界在哪，控制面就在哪一档**。namespace 解决不了「租户需要装 CRD/webhook」；vCluster 解决不了「etcd/控制面也要物理分家」。反过来物理集群解决一切、也最贵——§八再说怎么收着用。

### 7.2 vCluster 机制（v0.37.x 核实）

- 核心 = **syncer**：vCluster 的控制面（k3s 内核）作为**宿主集群里的一个 StatefulSet**跑在一个 ns 里；用户在 vCluster 里 create 的对象，syncer 把「该落地的」（Pod/Service/PVC/CM/Secret…）同步成宿主 ns 里的等价物（名字经 syncer 映射带后缀），把「不该落地的」（CRD 定义、cluster 级 RBAC、Node）留在 vCluster 自己的 etcd。
- 由此导出两个必然：**租户是 vCluster 的 admin，对宿主只有最小权限**（README 原话「tenants hold admin inside their tenant cluster while holding minimal permissions on the host」）；**CRD/webhook 在租户内随便折腾，不污染宿主**（装 operator 测试/跑同款控制器互不影响）。
- 四个部署形态（README 2026-10 文档的分类，按隔离从松到紧）：**Shared Nodes**（共享宿主节点，密度最高——本章实验用这形态）、**Dedicated Nodes**（标记过的宿主节点独占）、**Private Nodes**（v0.27+，外部节点直接 join 进 vCluster、CNI/CSI 也隔离）、**Standalone**（v0.29+，无宿主集群，二进制自成集群）。`vcluster create` CLI（brew `loft-sh/tap/vcluster`）是官方 README 首选入口；Helm 官方 chart 仓库 `https://charts.loft.sh`（实时可解析）。
- 适合一句话：「**namespace 不够用、物理集群嫌贵的中间态**」——CI 每 PR 一个、客户一租户一套、开发者一人一盒，全是它的战场。

### 7.3 典型场景三例

1. **CI 隔离**：每流水线一个 vCluster，测试 Helm/operator 全套（实验 10.2 就是最小版）；删即散、不残留、与宿主 API 版本解耦。
2. **租户控制面**：平台团队给内部组「像集群一样的东西」自助（quota 在宿主侧仍守），租户侧 100% cluster-admin 体验。
3. **开发沙箱**：学 Operator/CRD 不想污染真集群——第 6 章实验室里你 kind 干的事，换 vCluster 同样成立且更快（免再起 kind）。

### 7.4 局限与成本（用之前读一遍）

- **同步延迟与映射损耗**：syncer 是一把单线程级的翻译器——大规模对象（数千 Pod）同步有可见延迟；**status 回写**（Pod 状态/事件）回租户侧也有跳滞，排查时先在宿主演示真相再回租户侧对表（与第 8 章「API 层状态 ≠ 节点真相」同款纪律）。
- **不是免费的集群**：每租户控制面 StatefulSet（API+etcd/kine）约 0.5C/1G 起 + syncer——10 个租户就是 10 份控制面内存；密度再上就要 sleep mode（平台付费功能）或回头重新评估 namespace 方案。
- **数据面仍共享宿主**：互为邻居的租户 Pod 在同一 kubelet/内核上——逃逸类风险与 namespace 软多租同级（要内核级隔离请 private/standalone 档或上 vNode/Kata 类运行时）；**「硬多租」管的是 API 面，不是内核面**。
- **etcd 在容器里**：备份/恢复走 vCluster 自带 snapshot（v0.33+ 系 S3/OCI/本地），别照搬第 7 章宿主 etcdctl 剧本——管理面数据在 vCluster 自己的存储里。

---

## 八、选型与落地建议

### 8.1 多集群运维铁律(八条，刻进 runbook)

1. **命名/标签先行**：集群命名 `<env>-<region>-<seq>`（`prod-eu-1`），全集群统一 `environment/region/criticality/owner` 四标签——Placement（OCM）/clusterAffinity（Karmada）/clusters 生成器（ApplicationSet）全部靠这口吃饭，事后改名代价巨大。
2. **拓扑目录化**：`clusters/` 一个 git 目录就是事实表——每个集群一条记录（endpoint、CNI、CIDR、版本、用途、入口、联系人）；「这个 Service 在哪些集群有」查目录不查脑。
3. **GitOps 是 glue**：控制面层（CAPI/OCM/Karmada 的 CR）与工作负载层（Application/ApplicationSet/Fleet/PropagationPolicy）**全部先入 git 再进集群**；直改集群 = 事故预定（第 8 章 §10 的变更同期审计同样适用）。
4. **一致性预算提前说**：「config/identity/traffic」三样各定 SLA——允许「主备集群 RBAC 延迟 1 分钟」，就明写；不许发现问题再说「以为同步的」（§1.4 已给模板）。
5. **pull 优先**：能 agent 拉取就不让 hub 直连（防火墙/私网/边缘是常态）——Rancher agent、OCM klusterlet、Karmada Pull、karmada-agent、submariner gateway 全同原则。
6. **CIDR 全局账本**：Pod/Service CIDR 分配表集中维护，多集群**默认不可重叠**；要合并存量重叠集群才考虑 Globalnet/NAT 方案（且明白它的观测成本）。
7. **入口与数据分开想**：「流量怎么过去」（§三）与「数据状态怎么同步/怎么一致」（数据库层/对象存储/消息）是**两件事**——跨集群多活 90% 的难度在后者，K8s 管不了它。
8. **每加一个集群写好「拆除手册」**：workload 迁出、入口摘除、凭证回收、etcd/mesh 解除、记录从拓扑目录移除——可逆性比高可用更值钱。

### 8.2 现实路径（如果你现在只有一个集群）

按「最小有价值动因」排序的升级路径：

| 阶段 | 动因 | 动作 | 成本 |
|------|------|------|------|
| **P0（就现在）** | 单集群够用 | 什么都不拆；把「第二集群」当**演练科目**写进攻防预案：数据备份 + 恢复剧本 + 入口切换剧本（第 7 章 §9 已给备份铁三角） | 0 |
| **P1** | 学习/消费侧扩环境 | kind + 实验 10.1/10.2 把多集群/vCluster 玩熟；Dev/Test 用 vCluster 或 kind 分，不进生产话题 | 一台开发机 |
| **P2** | 第一个真动因出现（八成是「灾备」或「合规」） | **主备拓扑**起第二集群 + GitOps 双 destination（ApplicationSet 已会）+ 外部 DNS 健康切换；数据层复制方案单独设计 | +1 集群 + 1 条 GitOps |
| **P3** | 集群 ≥3 / 团队治理需求 | 上 hub-spoke：**平台治理选 OCM/Rancher**（你已部署 Rancher v2.15.2，先手就是接它，§2.6） + **负载编排要智能再叠 Karmada** | +1 hub 集群 |
| **P4** | 集群造舰规模化 | 上 CAPI：集群清单 Cluster YAML 化 → GitOps → cluster 机器/升级/修复自愈 | 管理集群 ×1 |
| **P5（可选）** | 边缘/GPU/AI | KubeEdge/OpenYurt/K3s 按 §6.1 主问；GPU 按 §5 配额+共享+DRA 路线 | 边缘/GPU 专题投入 |

> ★ 给你自己的具体建议（结合仓库现状）：Rancher 已在，**P3 的治理面你不用再选**——把「加第二个集群」的最小动因先落给「灾备演练自动化」（每月一次脚本化 failover 演练，§3.3 的 runbook 就是模板）；Karmada 的 PropagationPolicy 不如你先把 ApplicationSet clusters 生成器吃透（`CI-CD/Argo-CD-部署与使用详解.md` §12），两者覆盖面在你目前的集群规模上重叠 80%，且免控制面。

---

## 九、实验（沙箱全程可复现，4 个）

> 基线沙箱：kind v0.33+（第 6 章工具链基线，node v1.37.0）或 L2（Multipass 三节点 v1.37，第 7 章实验 7.1），Docker 环境通外网。Karmada 官方兼容矩阵当前列到 K8s 1.36（README 表，2026-10-14）——**实验用 v1.37 kind 属于「未验证组合」**，求稳请用 `kind create cluster --image kindest/node:v1.36.<小版本>` 对照 Karmada 兼容页；要激进就用默认 1.37 顺手做个「踩雷测试」写进心得。

**实验通用小贴士（四个实验共用）**：

```bash
# ① 实验排队前看一眼地面：kind 集群列表与 docker 占用的资源
kind get clusters; docker system df
# ② 拉镜像慢/限流：kind 的 load 旁路（先宿主机拉，再灌进集群）
docker pull nginx:1.27 && kind load docker-image nginx:1.27 --name member1
# ③ 每个实验收摊三步：删工作对象 → 删控制面组件 → kind delete cluster --name <x>
#    跨天继续实验时，直接 kind get kubeconfig --name <x> > ~/.kube/<x>.config 取回入口
# ④ 实验产物（「我已经验证过的」心得）按总纲节奏回写进本仓库——写完才算做完
```

### 实验 10.1 Karmada 最小上手（官方 quickstart 形态）

目标：起一个 Karmada 控制面 + 2~3 成员集群，用 PropagationPolicy 把 nginx Deployment 铺下去，并看懂对象链。

**路径 A（官推 dev 环境，一键 4 集群：host + member1/2/3）** —— 官方 README/Installation 页逐字的形态：

```bash
git clone https://github.com/karmada-io/karmada && cd karmada
hack/local-up-karmada.sh                    # 需要 Go 工具链（源码现编控制面），耐心 10~20 分钟
export KUBECONFIG="$HOME/.kube/karmada.config"
kubectl config get-contexts                 # 应见 karmada-host 与 karmada-apiserver 两个
kubectl --context karmada-apiserver get clusters
#   NAME      VERSION   MODE   READY   AGE  → member1/2/3 全 True（MODE 一列就是 §2.3 的 Push/Pull）
kubectl --context karmada-apiserver get deployment -n karmada-system   # 六大件（§2.3 清单）
```

**路径 B（手动走流程，更接近生产形态：两个 kind 集群 + karmadactl init）**：

```bash
kind create cluster --name karmada-host       # 控制面宿主
kind create cluster --name member1
kind create cluster --name member2
# 装 CLI（官方 install 页的插件/CLI 同形态，偏爱 CLI 用 karmadactl）
curl -s https://raw.githubusercontent.com/karmada-io/karmada/master/hack/install-cli.sh | sudo bash -s karmadactl
kubectl config use-context kind-karmada-host
karmadactl init                             # 默认把配置落 /etc/karmada（需可写权限；--karmada-data 可改）
kubectl --kubeconfig /etc/karmada/karmada-apiserver.config get clusters      # 现在为空
# Push 模式纳管（两个成员是 kind 集群）
karmadactl join member1 --kubeconfig /etc/karmada/karmada-apiserver.config \
  --cluster-kubeconfig $HOME/.kube/config --cluster-context kind-member1
karmadactl join member2 --kubeconfig /etc/karmada/karmada-apiserver.config \
  --cluster-kubeconfig $HOME/.kube/config --cluster-context kind-member2
kubectl --kubeconfig /etc/karmada/karmada-apiserver.config get clusters
#   NAME      VERSION   MODE   READY   AGE → 两个 Push/True
```

**铺 Deployment（两种路径通用，§2.3 的 policy 原样）**：

```bash
export KUBECONFIG=/etc/karmada/karmada-apiserver.config    # 路径 A 时改 $HOME/.kube/karmada.config 并 use-context karmada-apiserver
kubectl create deployment nginx --image=nginx:1.27 --replicas=2
kubectl apply -f - <<'EOF'
apiVersion: policy.karmada.io/v1alpha1
kind: PropagationPolicy
metadata:
  name: nginx-propagation
spec:
  resourceSelectors:
    - apiVersion: apps/v1
      kind: Deployment
      name: nginx
  placement:
    clusterAffinity:
      clusterNames: [member1, member2]
    replicaScheduling:
      replicaDivisionPreference: Weighted
      replicaSchedulingType: Divided
      weightPreference:
        staticWeightList:
          - targetCluster: { clusterNames: [member1] }
            weight: 1
          - targetCluster: { clusterNames: [member2] }
            weight: 1
EOF
kubectl get resourcebinding,work -A | head
kubectl get deployment nginx                              # karmada 视角 READY 2/2
# 验证真落成员集群（分别进入两个成员看）
kubectl --kubeconfig $HOME/.kube/config --context kind-member1 get deployment,pod
kubectl --kubeconfig $HOME/.kube/config --context kind-member2 get deployment,pod
# 清场（unjoin 会顺带清掉下发资源）
karmadactl unjoin member1 --kubeconfig /etc/karmada/karmada-apiserver.config --cluster-kubeconfig $HOME/.kube/config --cluster-context kind-member1
```

**验收五问（答全算过）**：①karmada-apiserver 与 host 的 apiserver 各管什么？（karmada API 管「期望与编排」，host API 只是装控制面的容器）；②PropagationPolicy→ResourceBinding→Work 的生成顺序是谁干的？（policy controller → scheduler → binding controller）；③`kubectl get clusters` 里 MODE 列什么时候出现 `Pull`？（用 `karmadactl register` 走 pull，§2.3）；④把 policy 的 `replicaSchedulingType` 改 `Duplicated` 再 apply，member 两边副本数怎么变？（每边全量 2 个）；⑤把 member1 打污点/失联后，failover 触发时 Work 怎么动？（污点 → scheduler rebalance → 健康集群接住；推荐同时读官方 failover 文档 + `kubectl describe cluster member1` 看污点）。

### 实验 10.2 vCluster 快速建一个（进进出出验证 sync）

```bash
# 一个宿主 kind 集群就够
kind create cluster --name vhost
# 官方 README 首选：CLI（也可用 helm：helm upgrade --install vc-demo vcluster \
#   --repo https://charts.loft.sh --namespace vc-demo --create-namespace）
brew install loft-sh/tap/vcluster          # 或官方 releases 拿二进制
vcluster create vc-demo --namespace vc-demo   # 完成会自动 connect（kubectl 切到 vCluster context）
# —— 以下在 vCluster 里 ——
kubectl get ns                              # default/kube-system/kube-public/kube-node-lease
kubectl create ns ci
kubectl create cm tc --from-literal=owner=team-a -n ci
kubectl create deployment web --image=nginx:1.27 -n ci
kubectl get pods -n ci -o wide              # Running 但注意：这些 Pod 实际跑在宿主节点
# —— 断开回宿主 ——
vcluster disconnect
kubectl config current-context              # 回到 kind-vhost
kubectl -n vc-demo get pods                 # vc-demo-0 控制面（内嵌 syncer）
kubectl -n vc-demo get deployments,cm | grep -E 'web|tc'   # syncer 同步下来的等价物（名字带映射后缀）
# —— 再入再出，验证双向 ——
vcluster connect vc-demo --namespace vc-demo
kubectl get cm tc -n ci -o yaml | head
vcluster disconnect
kubectl delete ns vc-demo && kind delete cluster --name vhost   # 收摊即散
```

**验收四问**：①vCluster 的控制面跑在哪？（宿主 ns 里的 StatefulSet，README 形态 Shared Nodes）；②vCluster 里装一个 CRD，宿主演示能不能查到？（不能——CRD 只在 vCluster 自留存储，这就是「硬多租」）；③syncer 把「该落地的」和「不该落地的」各举两例（落地：Pod/Service/CM；不落地：CRD 定义/Node）；④`vcluster pause/resume`（Platform 功能）省的是什么？（闲置时控制面+同步停，省宿主资源——README「sleep mode」）。

### 实验 10.3 CAPI 概念上手（阅读性实验：看对象逻辑）

```bash
kind create cluster --name capi-mgmt
brew install clusterctl                       # 或 releases 二进制
clusterctl init --infrastructure docker       # 装 Core + CABPK + KCP + CAPD（实验 provider）
kubectl -n capi-system get pods               # capi-controller-manager
kubectl get crd | grep cluster.x-k8s.io | head
# 生成一份「完整集群」的 YAML 但不 apply：这就是「cluster 即 YAML」
clusterctl generate cluster capi-quickstart \
  --flavor development \
  --kubernetes-version v1.37.0 \
  --control-plane-machine-count=1 --worker-machine-count=1 > capi-quickstart.yaml
grep -E '^kind: ' capi-quickstart.yaml | sort | uniq -c
#   预期对象：Cluster / DockerCluster / KubeadmControlPlane / DockerMachineTemplate
#   / MachineDeployment / KubeadmConfigTemplate / Secret(证书)……对照 §4.2 继承图逐个看
```

**apply 前思考题（答得出就算验收）**：①`KubeadmControlPlane` 与 `DockerCluster` 谁是「逻辑」谁是「物理」？（KCP 管控制面机器逻辑身份，DockerCluster 管网络/负载均衡等底座）；②把 `--control-plane-machine-count` 改 3，YAML 差别出现在哪几个对象？（只改 KubeadmControlPlane.replicas，其他照旧——immutable 模板哲学）；③`MachineDeployment` 里为什么没有镜像字段？（镜像在 `DockerMachineTemplate` 模板里，MachineDeployment 引用它——呼应 Deployment ↔ PodTemplate）；④`clusterctl move`（management 换家）搬的是对象还是机器？（对象 + 迁移动作，保证被管集群不断——官方 pivot 流程）。

（可选真 apply：`kubectl apply -f capi-quickstart.yaml` 后 `clusterctl get cluster capi-quickstart` 看 Ready；Docker Desktop on macOS 要按官方 quickstart 的 Docker provider 提示补 `--loadbalancer` 镜像与端口映射——只需了解，不必跑通。）

### 实验 10.4 GPU 可选（有 NVIDIA 卡环境的 checklist）

- [ ] 节点 `nvidia-smi` 通；`containerd` 已配 nvidia runtime（gpu-operator 会代管）
- [ ] 装 device plugin（§5.2 helm 命令；装了 gpu-operator 则跳过——它已含）
- [ ] `kubectl describe node <gpu-node> | grep nvidia.com/gpu` 在 Capacity/Allocatable 两侧出现（extended resource 上报成功）
- [ ] 最小 Pod 验证（官方 device-plugin 文档同款思路：任意 CUDA base 镜像跑 `nvidia-smi`）：

  ```bash
  kubectl run gpu-smoke --rm -it --restart=Never \
    --image=nvidia/cuda:<近期 base 镜像 tag> \
    --overrides='{"spec":{"containers":[{"name":"gpu-smoke","image":"nvidia/cuda:<同左>","command":["nvidia-smi"],"resources":{"limits":{"nvidia.com/gpu":1}}}]}}'
  # 预期输出一张 nvidia-smi 表；Exit 0 即设备注入成功（GPU 只写 limits，§5.5 ❗）
  ```

- [ ] （有 A100/H100 再进）开 MIG：gpu-operator 的 MIG Manager 把卡切成 mixed；`kubectl get nodes -o json | jq '.items[].status.allocatable | with_entries(select(.key|test("nvidia.com/mig")))'` 见到切片 extended resource
- [ ] 成本题：给该节点打 `gpu=true` 标签 + 建 `ResourceQuota`（`hard: limits.nvidia.com/gpu: "2"`）上限——让后续「超额申请」被拒在 admission（§5.6 #1 的镜像对照）

---

## 十、收官：精通路线全系列索引 + 十项验收能力对照

### 10.1 十章索引（学完闭环表）

| # | 笔记 | 一句话 | 核心交付 | 状态 |
|---|------|--------|---------|------|
| 1 | `K8s-API机制深入.md` | 一切控制循环的地基 | RequestPath/list-watch/finalizer/APF/聚合层/审计 | ✅ |
| 2 | `K8s-调度器深入.md` | 框架 18 扩展点到 DRA | Scheduling Framework、抢占、descheduler、批调度、SchedulingGates、DRA | ✅ |
| 3 | `K8s-网络原理详解.md` | 三原则到排障入口 | CNI/kube-proxy/CoreDNS/NetworkPolicy/Gateway API | ✅ |
| 4 | `K8s-存储深入.md` | PV/PVC 生命全景 | CSI、绑定/回收/扩容/快照/本地存储 | ✅ |
| 5 | `K8s-安全加固详解.md` | 准入到供应链 | PSA、webhook、Gatekeeper/Kyverno、加密、ESO | ✅ |
| 6 | `K8s-Operator开发实战.md` | 从 CRD 到 Operator | CRD 进阶、controller-runtime、kubebuilder、最小 Operator | ✅ |
| 7 | `K8s-生产集群运维手册.md` | 集群生命周期与治理 | kubeadm、升级、证书、调优、NPD、灾备、大集群约束 | ✅ |
| 8 | `K8s-故障排查方法论.md` | 肌肉记忆一本通 | 七大域判读链、debug 四形态、nsenter、复盘、实验 L3 作战图 | ✅ |
| 9 | `K8s-自动伸缩深入.md` | 三轴 + 一扳机 | HPA/VPA/KEDA/CA/Karpenter、PDB 联动、容量规划 | ✅ |
| 10 | `K8s-多集群与进阶生态.md` | 多集群一艘船 | 管理平面、流量、CAPI、GPU、边缘/Wasm、vCluster、选型、收官索引（本文） | ✅ |

配套实验档案：L1=kind 沙箱（各章用）、L2=Multipass 三节点 kubeadm+Cilium v1.37（第 7 章/各章主场）、L3=破坏-恢复 runbook（第 8 章 §11）、L4=killer.sh CKA/CKS 模拟（认证线）。

### 10.2 总纲十项验收能力 ↔ 章节对照表（逐项对账总纲 🧭 原话）

| # | 验收能力（总纲原话） | 主章节/实验 |
|---|----------------------|------------|
| 1 | 「画出任意一次 `kubectl apply` 的完整请求链路（认证→鉴权→准入→etcd→控制器 reconcile）」 | **第 1 章**全文（RequestPath 逐跳 + 审计取证）；第 5 章准入一段 |
| 2 | 「从零用 kubeadm 搭一个三节点集群，并完成一次 minor 版本升级」 | **第 7 章**（L2 实验 7.1 搭建 + 7.2 升级全流程） |
| 3 | 「etcd 快照备份 + 损坏后恢复；证书过期处理与轮转」 | **第 7 章** 证书/灾备恢复段 + 实验 L3（第 8 章 §11 场景 1/2 runbook） |
| 4 | 「讲清 Pod 到外部流量的完整路径（CNI → kube-proxy → 网关），会抓包验证」 | **第 3 章**全文 + 实验 3.x（tcpdump 追包）；第 8 章 §七复用到排障语境 |
| 5 | 「给集群写准入策略：PSA、OPA/Gatekeeper 或 Kyverno 规则各一条」 | **第 5 章**（PSA/webhook/两条框架 + 实验 5.x） |
| 6 | 「用 controller-runtime 从零写一个有 CRD 的最小 Operator 并跑通 reconcile」 | **第 6 章** + 实验 6.x（kubebuilder 全流程） |
| 7 | 「十分钟内定位模拟故障：镜像拉取失败 / CrashLoop / 节点 NotReady / DNS 异常 / 证书报错」 | **第 8 章** 七大域 + 实验 L3（§11 七场景 runbook 自评耗时） |
| 8 | 「配出基于自定义指标的 HPA，并能解释 HPA/VPA/KEDA/Karpenter 各自适用边界」 | **第 9 章** §1-§5 + 实验 9.x（prometheus-adapter/KEDA/Karpenter） |
| 9 | 「给生产集群做容量规划与性能调优设计（apiserver/etcd 瓶颈判断）」 | **第 7 章** §6（调优 + §6.5 大集群约束）+ 第 9 章 §容量规划方法 |
| 10 | 「通过 CKA 模拟考（killer.sh ≥ 80 分），安全方向加考 CKS」 | **实验 L4**（总纲验收线）——十章全部填满后开考 |

### 10.3 下一步建议（把十章变成战斗力三件事）

1. **killer.sh CKA 计时刷题**：8 套题按「破坏-恢复熟练度 = 答题速度」思路刷，目标分 ≥80；把错的题回填进第 8 章症状词典（活文档原则）。
2. **在 L2 集群拉通一遍「GitOps + Karpenter/CA + 监控」**：Argo CD 把前十章的关键对象（policy/operator/ingress/monitoragent）全部 git 化，配一次「集群重建后 30 分钟自愈」演练——这一遍下来，多集群的地基就齐了（§8.2 P2→P3 的入场券）。
3. **多集群动因审计**：给现有环境写一页 §0.2 动因清单——只为回答一个问题：**「我们第一个真集群动因是什么，预计什么时候到」**。答案决定你该不该翻开本章 §二~§四。
4. 资源接力：`Cilium labs`（cilium.io/labs，mesh/hubble 上手快）、`Karmada samples`（仓库 samples 全套）、`CAPI book`（§十一）、CNCF SIG-Multicluster 双周会（多集群地盘的主战场）。

---

## 十一、速查 + 背诵要点 + 参考链接

### 11.1 一页速查（多集群与进阶生态命令）

| 主题 | 命令 |
|------|------|
| **Rancher 本体** | `kubectl get settings.management.cattle.io server-url -o jsonpath='{.value}'`；`kubectl -n cattle-system get pods`；纳管清单：`kubectl get clusters.management.cattle.io`；Cilium 集群测 NodePort 用节点 IP（`127.0.0.1` 恒不通） |
| **OCM** | `clusteradm init`（hub）、成员侧 `clusteradm join`、hub 侧 `clusteradm accept --clusters <name>`；对象：`kubectl get managedclusters,placements,manifestworks -A`（dev：`local-up.sh` 一键三集群） |
| **Karmada 控制面** | `karmadactl init`（或 kubectl karmada 插件同名）；配置默认 `/etc/karmada/karmada-apiserver.config`（`--karmada-data` 可改） |
| **Karmada 纳管** | Push：`karmadactl join <member> --kubeconfig <karmada> --cluster-kubeconfig <member> [--cluster-context <ctx>]`；Pull：`karmadactl token create --print-register-command` → 成员上 `karmadactl register <karmada-ep> --token ... --discovery-token-ca-cert-hash sha256:...`；退：`karmadactl unjoin`（Push）/ `unregister`（Pull） |
| **Karmada 查询** | `kubectl --kubeconfig /etc/karmada/... get clusters,resourcebinding,work -A`；成员侧对象看 `karmada-es-<cluster>` ns |
| **Cilium mesh** | 打 Global：`kubectl annotate svc <name> service.cilium.io/global=true`；不分享：`service.cilium.io/shared=false`；缓存保质期：`helm upgrade ... --set clustermesh.cacheTTL=15m`；状态：`cilium clustermesh status` |
| **CAPI** | `clusterctl init --infrastructure docker`（实验）；`clusterctl generate cluster <name> --flavor development --kubernetes-version v1.37.0 > out.yaml`；`clusterctl describe cluster <name>`；运维：`clusterctl move`（换管理集群） |
| **vCluster** | `vcluster create <name> --namespace <ns>`（自动 connect）；`vcluster disconnect` / `vcluster connect <name> -n <ns>`；helm：`helm upgrade --install <name> vcluster --repo https://charts.loft.sh --namespace <ns> --create-namespace` |
| **GPU** | 装：`helm upgrade -i nvdp nvdp/nvidia-device-plugin -n nvidia-device-plugin --create-namespace --version 0.20.1`；一把梭：`helm install --wait --generate-name -n gpu-operator --create-namespace nvidia/gpu-operator`；验：`kubectl describe node \| grep nvidia.com/gpu`（只写 limits）；配额：`ResourceQuota hard: limits.nvidia.com/gpu: N` |
| **边缘** | KubeEdge：`keadm init`（云）/ `keadm join --cloudcore-ipport ... --token ...`（边）；OpenYurt：`yurtadm join`（把节点「转换」边缘自治）；K3s 轻量：`K3s-部署指南.md` |
| **Knative/Wasm** | Knative：`kn service create`（serving v1.23.x CLI）；SpinKube：RuntimeClass + `SpinApp` CRD（spin-operator v0.6.x，0.x 谨慎） |
| **版本核对** | 每季重核 sources：各上游 GitHub `/releases` 页（§11.3） |

### 11.2 背诵要点（12 条）

1. **多集群的主矛盾是一致性（config/identity/traffic），不是工具**；方案 = 「管理平面 × 数据面 × GitOps」三层各选一件，hub-spoke 里 pull 模式优先、hub 单点要预案。
2. **单集群上限 5000/150000/110 是「变更率预算」换算的**（第 7 章 §6.5）；拆集群的主因是合规/爆炸半径/就近，不是节点数登顶。
3. **Rancher = 管理门户 + Fleet**（agent pull）；**OCM = hub-kubelet 镜像**（ManagedCluster/cluster-ns/Placement→PlacementDecision/ManifestWork/add-on）；**Karmada = 原生 K8s API + karmada-scheduler + Push/Pull 双模**，PropagationPolicy→ResourceBinding→Work。
4. **kubefed 已 2023 归档**（kubernetes-retired），遗产是「template+placement+override」三段论被 Karmada/OCM/GitOps 三路分别继承——**为原生对象造 FederatedXX 的路已被证伪**。
5. **Cilium Cluster Mesh**：互信单一信任域 + 同 CNI + CIDR 不重叠；`clustermesh-apiserver`（etcd+apiserver+kvstoremesh）；Global Service 用 `service.cilium.io/global`；**NodePort/hostNet 要 kube-proxy 替换模式**；失联摘除配 `clustermesh.cacheTTL`。
6. **Submariner 的 Globalnet 专治 CIDR 重叠**；**MCS-API（KEP-1645）是规范不是产品**，数据面各实现各的；**故障摘除 > 能通**——跨集群服务发现是「全局表」，`cacheTTL`/外部 DNS 健康探针是它的保质期。
7. **CAPI 四 provider**：Core（Cluster/Machine/MD/MS/MHC）、Bootstrap（CABPK/kubeadm cloud-init）、ControlPlane（KCP：控制面生命周期+etcd 修复）、Infrastructure（CAPA/CAPZ/CAPV/…/CAPD 仅实验）。Machine↔Pod、MachineSet↔RS、MachineDeployment↔Deployment。v1beta1 将于 v1.16 停 serve；capi-operator 慢 core 一拍（v0.29.0 pin v1.13.5）。
8. **Device Plugin**：gRPC `ListAndWatch`（上报 allocatable）+ `Allocate`（注入设备与 env）；NVIDIA 栈 = 驱动/toolkit → device-plugin（v0.20.1，`nvidia.com/gpu`）→ gpu-operator（v26.7.x，全包含 MIG Manager/DCGM）。
9. **GPU 共享四式**：TimeSlicing（时间片/零隔离）、MIG（硬切 ≤7 实例/高端卡）、MPS（CUDA 并发/显存共享）、vGPU（VM 级/授权）；**GPU 只写 limits 整卡计数**；**配额直接 `limits.nvidia.com/gpu`**；**GPU 空闲成本是最大事故源**（DCGM 利用率仪表 + idle reaper 是标配）。
10. **DRA 版本口径（与第 2 章 §11.2 一致）**：v1.30 Alpha 入场，**v1.35 GA 默认开启（锁定）**；`ResourceClaim`/`DeviceClass`/`ResourceSlice`；驱动分配延迟、不参与抢占；NVIDIA 官方 DRA 驱动正被 gpu-operator 收编。
11. **vCluster**：syncer 把「该落地的」同步到宿主 ns，「不该落地的」（CRD 等）留在 v 存储；多租户三档 namespace（软）→ vCluster（硬，API 面）→ 物理集群（全栈）按信任域选档——**「硬」管 API 面不管内核面**。
12. **KWasm 已退役**（接力 `spinframework/runtime-class-manager`）；SpinKube v0.6.x 0.x 谨慎；KubeEdge Graduated（2024-09-11）/OpenYurt Incubating/K3s 独立小集群——边缘主问「断网谁说了算」。**多集群铁律一句话：拓扑永远服务于动因**。

### 11.3 参考链接

| 主题 | 链接 |
|------|------|
| Karmada 官方文档（install/cluster-registration/quickstart/兼容矩阵） | https://karmada.io/docs/installation/ 、https://karmada.io/docs/userguide/clustermanager/cluster-registration/ 、https://github.com/karmada-io/karmada/releases |
| OCM 架构与 quickstart | https://open-cluster-management.io/docs/concepts/architecture/ 、https://open-cluster-management.io/docs/getting-started/quick-start/ 、https://github.com/open-cluster-management-io/ocm/releases |
| kubefed 退役仓库 | https://github.com/kubernetes-retired/kubefed |
| Fleet releases | https://github.com/rancher/fleet/releases ；你的部署：`脚本与工具/Rancher部署文档.md` |
| Cilium Cluster Mesh（intro/global-services/mcs-api/limitations） | https://docs.cilium.io/en/stable/network/clustermesh/intro/ 与 https://docs.cilium.io/en/stable/network/clustermesh/global-services/ ；releases：https://github.com/cilium/cilium/releases |
| Submariner | https://github.com/submariner-io/submariner/releases |
| K8s MCS-API（KEP-1645） | https://github.com/kubernetes-sigs/mcs-api |
| Cluster API（book/ releases / operator） | https://cluster-api.sigs.k8s.io/ 、https://github.com/kubernetes-sigs/cluster-api/releases 、https://github.com/kubernetes-sigs/cluster-api-operator/releases |
| vCluster（README/CLI/chart 仓库） | https://github.com/loft-sh/vcluster 、https://github.com/loft-sh/vcluster/releases 、https://charts.loft.sh |
| 边缘三剑客 | https://kubeedge.io/（CNCF Graduated 2024-09-11）与 https://github.com/kubeedge/kubeedge/releases ；https://github.com/openyurtio/openyurt/releases ；本仓 `容器编排/K3s-部署指南.md` |
| NVIDIA on K8s | https://github.com/NVIDIA/k8s-device-plugin 、https://github.com/NVIDIA/gpu-operator （含 quickstart/Roadmap）、Device Plugin 框架概念页 https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/ |
| DRA（口径以第 2 章 §11.2 为准） | `容器编排/K8s-调度器深入.md` §11.2 |
| Wasm | https://github.com/KWasm/kwasm-operator（已退役归档说明）、https://github.com/spinframework/spin-operator/releases（runtime-class-manager 在同 org） |
| Knative | https://github.com/knative/serving/releases |
| 云多集群（各自文档） | AWS VPC Lattice、阿里 ACK One 舰队/MCS、华为 UCS——以各云官方文档为准 |
| 本仓系列联读 | 第 1~9 章（§10.1 索引）、`学习/K8s-精通路线-总纲.md`、`CI-CD/Argo-CD-部署与使用详解.md` §12、`容器编排/Istio详细入门与实践指南.md`、`云服务/DGX-HGX-SXM-详解.md`（GPU 硬件侧）、`容器编排/OpenKruise-原理作用使用与部署指南.md`（扩展工作负载，多集群分发的常客） |

---

> 收官备注：十章到此闭环。第 1~9 章把「一个 K8s」拆到零件又装回生产，本章把「N 个 K8s」装回「一件事」。回到总纲 🧭 的十项验收——**§10.2 的对照表就是你的结业考卷**：全打勾且实验 L1-L3 做完之后，L4 的 killer.sh 只是最后盖个章。多集群没有终点：每加一个集群，重跑一次 §0.2 的动因审计 + §8.2 的现实路径，让拓扑永远服务于动因，而不是反过来。
