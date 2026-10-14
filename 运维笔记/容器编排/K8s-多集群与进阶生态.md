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
     集群A  集群B  集群C   …（workload 各跑各的，hub 只发政策/负载清单）
  治理：Placement/PropagationPolicy；流量：仍是本地入口，不跨集群

形态丙「mesh 内联」（同城/同 VPC 双活，Ciliun 一体的浮出地带）：
   集群A ◄──── Cluster Mesh（flat Pod IP）────► 集群B
     Global Service「rebel-base」在两边同名 → eBPF 层 LB
  治理：仍叠形态乙的 hub 或 GitOps；流量：mesh 自管
```

❗ 选型要落地到「SLA 数字」：一致性三难各给一个可测量的预算再开工——config 漂移容忍（例：政策类 ≤5min、业务类 ≤1min）、身份覆盖（例：跨集群服务调用 100% mTLS 或 0%——抵制中间态）、故障摘除时延（例：整簇失联到流量全走 ≤90s，配 §3.2 的域名 TTL/cacheTTL）。**没有数字的「跨集群同步」四个字，最终都是运维用黄金日补。**

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
