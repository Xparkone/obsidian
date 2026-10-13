# K8s 存储深入

> 精通路线第 4 章：in-tree→CSI 大迁徙、PV/PVC/SC 生命周期、CSI 三大 service 与全链路 RPC、VolumeSnapshot API、扩容与克隆、本地存储与拓扑
> 创建时间：2026-10-13
> 学习基线：**Kubernetes v1.37**（官方维护 1.35 / 1.36 / 1.37），文中标注「v1.xx 起 Beta/GA」均取自官方文档、KEP 或上游源码，执行时仍以你本地集群版本为准
>
> 📎 前置阅读：`K8s-API机制深入.md`（第 1 章，finalizer/ownerReference 概念直接引用不重讲）、`K8s-调度器深入.md`（第 2 章，§5 VolumeBinding/WFFC 的调度视角直接引用不重讲）。

---

## 零、本文定位与边界

「存储」在 K8s 里是把三件事拆给三拨人做：

1. **卷怎么供给出来** —— PV / PVC / StorageClass / provisioner（谁来造盘、造多大、什么规格、拓扑在哪）；
2. **怎么挂进容器** —— CSI attach/mount 链（云盘先「attach 到 VM」再「mount 到节点/Pod」，两层都被独立抽象）；
3. **数据生命怎么管理** —— reclaim（保留还是销毁）、快照（点到点恢复）、扩容/克隆（变更现有盘）。

这三件事横跨 5 个以上控制器（kube-controller-manager 的 PV-controller、A/D controller、集群级 snapshot-controller、external-provisioner/attacher/resizer/snapshotter、kubelet volume manager），全是「watch 对象 → 调外部系统 → 写状态/finalizer」的循环——和第 1 章讲的控制器模型一脉相承。学存储的机制，本质是把**每个对象归谁改、改成什么样、什么时候摘 finalizer**问清楚。

```
你的存储问题，最终都会变成这几类：
  "PVC 一直 Pending 为什么？"      → provisioner/SC/拓扑/配额四选一        §2.7 §7.1
  "Pod 起不来，报 FailedAttachVolume" → attach 链（云 API 或 VolumeAttachment）断了  §3.2 §3.5 §7.3
  "删了 Pod 怎么盘还在？"           → finalizer 保护 + reclaim 语义        §2.4 §2.5
  "扩容改了 PVC 怎么没变？"         → 两级扩容状态机 + Recover 语义        §5
  "快照恢复了怎么是空的？"          → dataSource 语义 + 快照拓扑/类不匹配    §4
  "local 盘的 Pod 漂到别的节点起不来" → local PV + nodeAffinity + WFFC       §6
```

### 与已有笔记的边界（不重复内容）

| 已有笔记 | 讲了什么 | 本文不重复 |
|---------|---------|-----------|
| `K8s-资源全览.md`（四、Config & Storage） | PV/PVC/StorageClass 的 **YAML 使用层**写法 | 只讲这些对象背后的控制器、状态机与回收语义 |
| `K8s-调度器深入.md`（第 2 章 §5） | WFFC 的调度链路（PreFilter/Filter/Reserve、selected-node 注解、CSIStorageCapacity 的调度消费） | 本文从「数据侧」讲供给器产出容量、PV nodeAffinity 落盘 |
| `Velero-Kubernetes备份恢复与迁移指南.md`（§15） | VolumeSnapshot 的**备份运维视角**（Data Mover、BSL/VSL、演练） | 本文讲 VolumeSnapshot 的 **API 机制视角**（三件套、snapshot-controller/csi-snapshotter 分工、dataSource 恢复语义） |
| `K8s-API机制深入.md`（第 1 章 §4.3） | finalizer 通用机制与「先修清理失败、再摘 finalizer」纪律 | 只列存储域的 finalizer 清单与保护场景表 |
| `K8s-Pod生命周期详解.md` | Pod 起停时间线 | 只讲其中「卷 attach/mount」那一段的内部拆解 |

> ❗ **版本标注约定**：文中形如「v1.34 起 GA」「v1.37 起默认开」的说法均已对照官方 docs、KEP（kubernetes/enhancements 对应目录）或 k/kubernetes master `pkg/features/kube_features.go` 中的版本注释核实；
> 个别字段（feature gate 默认值）可能随 minor 漂移，落地前用
> `kubectl get --raw /api/v1/nodes/<node>/proxy/configz | grep -i featuregate` 和 `kubectl get csidriver <driver> -o yaml` 再确认一次。

---

## 一、卷全景与 in-tree → CSI 大迁徙

### 1.1 两族卷：临时卷 vs 持久卷

K8s 对象模型里「卷」分成两族，判定标准一句话：**有没有独立的 API 对象（PV/PVC）来承载它的生命周期**。

**临时卷一族（生命周期 = Pod）**：

| 卷类型 | 机制一句话 | 关键版本事实（已核对官方 docs） |
|--------|-----------|-------------------------------|
| `emptyDir` | kubelet 在自己的 rootDir（通常 `/var/lib/kubelet`）下创建目录；Pod 被移出节点即删；`medium: Memory` 改挂 tmpfs（容器内存限额计费）；`sizeLimit` 计入 ephemeral-storage | v1.37 起 Alpha：`emptyDir.mode`（门控 `EmptyDirVolumeMode`，默认关）允许自定义目录权限位 |
| `configMap` / `secret` / `downwardAPI` / `projected` | 把 API 对象/字段投影成只读文件；**secret 落 tmpfs 不落盘**；定时同步更新，但 **subPath 挂载的拿不到后续更新**（官方死规则） | `subPathExpr` v1.17 起 Stable（用 downwardAPI 变量拼路径） |
| `image` | 把 OCI 镜像/artifact 当卷，只读挂载；`pullPolicy` 决定解析时机，拉取失败直接 Pod Failed | v1.31 首发、**v1.36 起 Stable 默认开**；subPath 支持 v1.33+ |
| `csi`（内联，CSI ephemeral） | Pod spec 直写 `csi:` 驱名+volumeAttributes；只有 CSIDriver 对象 `spec.volumeLifecycleModes` 声明了 `Ephemeral` 的驱动能被这么用；**不做容量感知调度、不参与 CSIStorageCapacity**（官方：此类卷只在特定节点本地生成，失败代价大所以设计上不许复杂化） | v1.25 起 Stable |
| `ephemeral`（generic ephemeral，内嵌 volumeClaimTemplate） | **任何支持动态供给的驱动都能供**：kubelet 之外的 ephemeral-volume-controller 替 Pod 建一个普通 PVC（名字确定：`"<pod名>-<卷名>"`），Pod 是 PVC 的 owner，Pod 删除被 GC 级联清掉 | **v1.23 起 Stable**（注意：常被误记成 v1.25） |

**persistent 一族（有自己的对象，活得比任何 Pod 都久）**：`csi` / `fc` / `iscsi` / `local` / `nfs` / `hostPath`（官方 1.37 PV 插件全集），外加排**deprecated 但源码还在、调用被重定向到 CSI** 的：`azureDisk` / `azureFile` / `cinder` / `vsphereVolume` / `portworxVolume`（见 §1.3 迁移表）。

### 1.2 为什么 in-tree 必须死掉

早年的 K8s 把几十种卷插件（EBS/GCE-PD/Azure/Ceph/GlusterFS/Portworx/vSphere…）**编译进 kube-controller-manager / kubelet 主干**。这个形态的代价是真实的：

- vendor 的任何 bug、权限改动、云 API 变化都要等 K8s 发版；K8s 发版又不敢快动存储代码——互相拖死（e.g. Ceph 侧大改被堵一个 release cycle）。
- 控制面进程里挂着各家 SDK 和凭据，一个插件 panic 波及全集群；供给逻辑编进主干二进制，不可灰度、不可热升级。
- 新存储厂商无法入场：要给主干提 PR 让一个三流阵列出现在 `kubectl explain pvc` 里。

CSI（Container Storage Interface，跨编排系统的统一 RPC 规范）把「发现/供给/attach/mount/快照/扩容」全变成**gRPC 接口**。K8s 只管对象世界，调用统一走 unix socket——厂商的 driver 以普通 Deployment/DaemonSet 形式部署、独立发版。CSIMigration（官方 Feature state：v1.25 起 Stable）是一层兼容重定向：**老 YAML 里的 in-tree 字段原样可读，但所有操作被透明转向对应 CSI 驱动**，于是老 cluster 升级不需要批量改 PV。

### 1.3 大迁徙时间线（每行都核对过）

| in-tree 插件 | CSIMigration 默认转发 | 重定向目标 CSI 驱动 | in-tree 代码处置 |
|-------------|----------------------|--------------------|-----------------|
| `cinder`（OpenStack） | v1.21 起默认开 | `cinder.csi.openstack.org` | v1.37 仍在（deprecated）|
| `awsElasticBlockStore` | v1.23 起默认开 | `ebs.csi.aws.com` | deprecated v1.19，**源码 v1.27 移除** |
| `azureDisk` | v1.23 起默认开 | `disk.csi.azure.com` | deprecated v1.19，**源码 v1.27 移除** |
| `gcePersistentDisk` | v1.23 起默认开 | `pd.csi.storage.gke.io` | deprecated v1.17，**源码 v1.28 移除** |
| `azureFile` | v1.24 起默认开 | `file.csi.azure.com` | v1.37 仍在（deprecated） |
| `vsphereVolume` | v1.25 起默认开 | `csi.vsphere.vmware.com` | v1.37 仍在（deprecated） |
| `portworxVolume` | v1.31 起默认开，v1.33 起 Stable（gate 已移除） | `pxd.portworx.com` | v1.37 仍在（deprecated，v1.37 中默认全部重定向到 pxd） |
| `cephfs` / `rbd` | —（官方明确没有迁移计划，直接死亡） | 换 `rbd.csi.ceph.com` / `cephfs.csi.ceph.com` | deprecated v1.28，**源码 v1.31 移除** |
| `storageos` / `flocker` / `quobyte` | — | — | **v1.25 移除** |
| `glusterfs` | — | — | **v1.26 移除** |
| `scaleIO` / `photonPersistentDisk` | — | — | **v1.21 / v1.15 移除** |
| `gitRepo`（非 PV，内联卷） | — | — | deprecated v1.11；**v1.37 已不存在**（最后提供于 v1.35） |

**为什么这么设计的琐事**：

- 迁移是「重定向」不是「转换」：老 in-tree PV 今天、明天、升级后都能正常挂载，不需要动对象——**前提是集群装上了对应 CSI 驱动**（K8s 不替你装）。这也是升级 checklist 里最容易漏的一项（官方 docs 原话：core of Kubernetes does not install that software for you）。
- 不迁移的（cephfs/rbd）选择直接源码移除：釜底抽薪比假装兼容更诚实，逼所有 Ceph 用户上 CSI 驱动（它们其实早就有）。
- `flexVolume` 是折中产物（exec 式 out-of-tree），deprecated v1.23，官方说「没有迁移计划（无法自动化成 CSI）、也没有移除计划」——它历史包袱太轻了，不值得迁移成代码，直接等死。

### 1.4 generic ephemeral volume：为什么值得用（v1.23 起 Stable）

`ephemeral` 内联模板解决了「emptyDir 太弱、PVC 太重」的中间地带：

```yaml
spec:
  volumes:
  - name: scratch                                    # PVC 名字将是 my-app-scratch
    ephemeral:
      volumeClaimTemplate:
        spec:
          accessModes: [ "ReadWriteOnce" ]
          storageClassName: "your-fast-csi-sc"       # 用上了驱动全部能力
          resources: { requests: { storage: 1Gi } }
```

相对于 emptyDir：

- 可以用**任意支持动态供给的存储后端**（网络盘、LVM、本地 NVMe），拿到**固定容量配额**、**快照/克隆/扩容三件套**和 **CSIStorageCapacity 调度**——emptyDir 只能跟着节点根盘漂。
- PVC 由 ephemeral-volume-controller 建在本 ns，**Pod 是它的 owner**：Pod 死了，GC 级联删 PVC，默认 `reclaimPolicy: Delete` 的盘跟着回收，整条链不需要人工干预。
- PVC 命名是确定性的 `<pod名>-<卷名>`（官方例子 `my-app-scratch-volume`），便于 `kubectl debug`、扩缩容手动对接和跨窗口排查；命名撞车会被 owner 校验拦下（不会让别人的 PVC 被强制借用），但不会自愈——官方要求「同 ns 里 Pod 名+卷名组合别撞到别人」。
- SC 推荐 WFFC：Immediate 模式下 PVC 供给后调度器只能选能访问该卷的节点，WFFC 下调度器先选节点再让 provisioner 就近供给——事实上「按 Pod 而生的盘最该按 Pod 落点供给」。
- 安全提醒（官方原文级别）：generic ephemeral 让「能建 Pod 但没 PVC 权限」的用户间接造出 PVC——与集群自己的权限模型冲突时，需要准入策略显式拦截这类 Pod；ns 级 PVC 配额依旧是兜底。

---

## 二、PV / PVC / StorageClass 生命周期（本章核心之一）

### 2.1 状态机：一张图读完

```
PVC（用户侧）                      PV（集群侧）                     后端盘
───────────                       ─────────                       ──────
[Create PVC] ── 供给分流 ──► 静态：选既有 Available 的 PV
                     └──────► 动态：provisioner 造 PV + 造盘
                              （SC 指定；WFFC 时等首个消费者 Pod）
        │                                                            │
        ▼                                                            ▼
 Pending ──匹配成功──► Bound ◄──────── claimRef 双向锁定 ─────►  盘就绪（被 attach/mount）
                            │
        用户 kubectl delete pvc
                            ▼
                     PVC 消失 → PV → Released
                            │
              .persistentVolumeReclaimPolicy 分流：
   ┌───────────┬───────────────────────┬───────────────────┐
 Retain      Delete                 Recycle(已废弃)
   │           │                       │
 PV 停     provisioner/plugin       rm -rf 擦洗后回 Available
 Released   先删后端盘、再摘        （1.37 仅 nfs/hostPath 支持）
 手工四步   finalizer、后删 PV 对象
 手工回收   （见 §2.4 / §2.5）
                            │
                        Failed：自动回收出错（驱动删盘失败等），
                        模型上不自动复活，需管理员接管
```

**就是这么设计的**：PVC/PV 是一组「需求域 ↔ 资源域」的双单向指针对象。用户需求域（PVC）是 ns 级，资源域（PV）是集群级——这个 ns 隔离是后来的「RWX 多 Pod 共享只能发生在同 ns 内」「PV 跨 ns 传需管理员手工」等硬边界的根源。`Released` 状态的存在避免了一个经典事故：**上一份数据还没确认处置，下一家就先把盘绑走了**——官方明确「Released 的 PV 不承认任何新 PVC 绑它」。

### 2.2 绑定算法：control-plane 的逐字段筛选

kube-controller-manager 里的 PV controller（`pkg/controller/volume/persistentvolume`）拿到一个未绑 PVC，对它**过滤候选 PV，再择优**。

1. **phase 可绑**：`Available`，或 `claimRef` 已经指向本 PVC（重复提交幂等）；
2. **storageClassName 双方严格相等**：PVC 写 `""` 只能绑 `""` 的 PV，写到动态类则等供给器（动态项不参与静态挑选）；
3. **PVC.spec.selector 匹配**：PV 标签满足 matchLabels/matchExpressions 子集；
4. **volumeMode 一致**：`Filesystem`（默认）或 `Block`——两列组合官方给了绑定矩阵（缺省视为 Filesystem，混搭即 NO BIND）；
5. **accessModes 覆盖**：PV 列出的模式必须包含 PVC 要的那个（RWO/ROX/RWX/RWOP）；
6. **capacity ≥ request**；此时**候选里挑容量最小者**（剩下的留给大需求）；nodeAffinity 在此阶段不判（预绑例外，见 §2.3）。

匹配完成即双向写入：PV 的 `spec.claimRef` 指向 PVC，PVC 的 `spec.volumeName` + `status.phase: Bound` 由控制器落库——官方定义这双向绑定叫 bi-directional ClaimRef 绑定。动态供给时 provisioner 出的 PV **预先把 claimRef 写好**（annotation `pv.kubernetes.io/bound-by-controller: yes` 通常伴随），故 PVC 一出现就一定绑到给它的那盘。

**为什么这么设计**：

- 整张算法是「扫全局、挑最小」，及其朴素——因为 provisioner 才是懂拓扑和配额的人，绑定器只做信纸配对（尺寸、形态、独家身份）的事，不做资源调度。任何「按 zone/负载/价格挑 PV」的念头都必须绕去 WFFC 或静态 + nodeAffinity 组合。
- accessMode 是**声明而不是执行体**：官方 docs 黑体字写着「RWO/ROX/RWX 不会在挂载层实施任何写保护」——RWO 的意思只是「同一时刻一台节点」，同节点的多 Pod 照样能同挂它；只有 `ReadWriteOncePod`（v1.29 起 Stable）在集群维度做单 Pod 独占。

### 2.3 「预留」与「预绑」：两个加速手法（都核对官方）

- **预绑（用户侧点名）**：PVC 写 `spec.volumeName: foo-pv`，直接绑定。**控制面不查 nodeAffinity**，但**仍会校验 storageClass、accessModes、请求尺寸**。官方原话：“The control plane still checks that storage class, access modes, and requested storage size are valid.”——点名绑定绕不过 class/模式/尺寸这三道校验。
- **预留（资源侧锁定）**：PV 先写 `spec.claimRef` 指名它只服务某 ns 的某 PVC，则别的 PVC 即使字段全匹配也绑不进它。常见用法：手工 Retain 回收后，想让「下一个重建的 PVC」精准接住这份带数据的 PV。

两句配合的常见约束：两边都不写 storageClass（或都显式 `""`），否则会被 DefaultStorageClass 准入器/retroactive 默认类（Stable v1.28，「晚创建的默认类会追填没写 storageClassName 的存量 PVC」）横插一脚。

### 2.4 reclaim 语义：Retain / Delete / 废弃的 Recycle

| 策略 | 行为 | 典型用途 | 深坑 |
|------|------|---------|------|
| `Retain` | PVC 删除 → PV 变 `Released`，**盘和对象都不动** | 数据要人审后处置（数据库、审计数据） | Released 不会被任何新 PVC 自动接走，必须手工四步：删 PV 对象 → 后端按需清数据（或保留）→ 建新 PV（可写 claimRef/预绑）→ 建新 PVC |
| `Delete`（动态供给默认） | 后端盘被真删，PV 对象随后消失 | 日常块存储、临时分析盘 | 回收顺序由 finalizer 守护（§2.5）；误删 PVC 等于删盘——**备份先行** |
| `Recycle` | `rm -rf /thevolume/*` 后回 `Available` | 历史包袱 | **已废弃**（官方建议用动态供给）；v1.37 只剩 `nfs`、`hostPath` 还支持——擦洗式回收对多 tenant 数据继承不安全、对块盘无意义 |

**为什么 Recycle 死了**：它承诺「洗掉即复用」，但共享存储场景里最经典的事故正是这个——`rm -rf` 受权限、挂载点布局、`..?*` 类通配兜底的影响，谁也不能形式化论证「洗完干净了」；前租户的数据残影会被下一家看到。动态供给（Delete + 新盘）用一点点供给时间，换掉了整张正确性论证。

三条策略之外，Delete 还有一条「删除顺序」带来的泄漏尾巴——先删 PV 再删 PVC 时老逻辑会漏掉 reclaim——§2.8 讲 v1.31+（GA 于 v1.33）修掉它的那套机制。

### 2.5 存储域 finalizer 清单（第 1 章 §4.3 概念的直接应用）

存储是「对象删除 ≠ 后端资源释放」最密集的领域，finalizer 全是「什么时候可以真删」的承诺：

| finalizer | 挂在 | 保护场景（谁在什么时刻摘） |
|-----------|------|---------------------------|
| `kubernetes.io/pvc-protection` | PVC | StorageObjectInUseProtection 自动挂；有 Pod 引用 PVC 时 PVC 删除被压到 Terminating，无人用了才摘 |
| `kubernetes.io/pv-protection` | PV | Bound 住 PVC 期间 PV 抗删；PVC 已删、PV 变 Released 后摘 |
| `external-provisioner.volume.kubernetes.io/finalizer` | PV（**CSI 驱动**，静态/动态都加，v1.31 起） | 保证 reclaim=Delete 的 PV **先把后端盘删掉**，ext-provisioner 才摘——包住「先删 PV 对象再删 PVC」那类顺序（§2.8） |
| `kubernetes.io/pv-controller` | PV（**in-tree 动态供给**；静态 in-tree 不加，v1.31 起） | 上者 in-tree 版；in-tree → CSI 迁移开启时会被前者替换 |
| `snapshot.storage.kubernetes.io/volumesnapshotcontent-bound-protection` | VolumeSnapshotContent | 有 VolumeSnapshot 绑定期间的 Content 抗删（外部：防止快照实体先死） |
| `snapshot.storage.kubernetes.io/volumesnapshot-bound-protection` | VolumeSnapshot | 有 PVC dataSource 恢复进行中时防删 |
| `snapshot.storage.kubernetes.io/pvc-as-source-protection` | PVC | 被快照引用为源、且快照未 readyToUse 期间，PVC 删除被压住（官方 docs：快照源保护） |

> ❗ 回到第 1 章的纪律：这些 finalizer 的存在表示「存储后端还有以我为凭据的货」，**强摘就等于云盘泄漏/盘上数据先死**。正确的修复永远是先查「为什么后端删不掉」——驱动挂掉、凭据失效、出口网络、后端配额，一个个排。

### 2.6 静态供给 vs 动态供给：决策树

```
 我需要一块盘
   │
   ├─ 已经有现成的物理盘/目录/LVG 吗？
   │     ├─ 是 → 静态供给：管理员建 PV（写清后端细节 + claimRef/标签/亲和）
   │     │        用户建 PVC 匹配 → Bound
   │     │        （local 盘必选这条，官方：local 卷只支持静态供给）
   │     └─ 否 → 动态供给：建 StorageClass（指明 provisioner + 参数 + reclaim）
   │              用户建 PVC 引 SC → provisioner 造盘后 PV 自动出现 → Bound
   │
   ├─ 需求方要不要在意盘造在哪个 zone/拓扑段？（多数有状态负载要）
   │     └─ 是 → SC 用 volumeBindingMode: WaitForFirstConsumer
   │              （不先供给；等第一个消费者 Pod 被调度，再按 Pod 落点供给）
   │
   └─ 盘上的是一次性的、跨 ns 的长命数据，还是可再生的？
        └─ 长命/要复用 → Retain + 手工回收流程（§2.4）
           可再生/日常     → Delete（默认）
```

**为什么这么设计**：静态/动态不是两个功能、是**谁的意图更先发生**。管理员先发（静态）= 资源池治理思路；用户先发（动态）= 服务自助思路。两者公用一个绑定状态机（§2.2），所以你可以混用——一个 PV 既可以被 provisioner 造、也可以被管理员造，状态机无差别对待。

### 2.7 StorageClass 逐字段

| 字段 | 语义（官方已核对） | 机制影响 |
|------|-------------------|---------|
| `provisioner` | **必填**；谁供给。CSI 写驱动名（`hostpath.csi.k8s.io`）；in-tree 重定向类写老名；特殊值 `kubernetes.io/no-provisioner` 表示「本类不做供给，仅配合 local + WFFC 用」 | 决定看哪个外部系统 |
| `parameters` | driver 私有键值对（**最多 512 项，键值总长 ≤256 KiB**，官方 SC 文档明写）；如 EBS 的 `type/iopsPerGB/encrypted`、vSphere 的 `storagePolicyName` | 原样透传 `CreateVolume` 的参数域 |
| `reclaimPolicy` | 该类动态供给的 PV 的回收策略，**不写默认 Delete** | 由 provisioner 写进 PV；静态供给的 PV 不受影响 |
| `mountOptions` | 挂盘附加选项（如 `discard` 开 TRIM/UNMAP） | 写进动态 PV 的 mountOptions；**不校验**，非法则 mount 失败才爆 |
| `allowVolumeExpansion` | bool；**只有 true 时**，PVC 改大请求才被放行 | 详见 §5 |
| `volumeBindingMode` | `Immediate`（默认：创建 PVC 立即供给/绑定）/ `WaitForFirstConsumer`（等第一个消费者 Pod 被调度才供给） | §1.2 调度器章 §5 对应；官方明确：WFFC 动态供给**只支持 CSI**（要驱动会做拓扑）；预先建的 PV 延迟绑定支持 CSI + `local`；**Pod 直写 `spec.nodeName` 旁路调度器时 WFFC 死等**——用 `nodeSelector: {kubernetes.io/hostname: ...}` 代替 |
| `allowedTopologies` | 给供给划线（SC 例：只允许两个 zone） | WFFC 下通常**不必再写**：落点由 Pod 自己决定；官方把它定位为老 `zone/zones` 参数的替代 |
| annotations `storageclass.kubernetes.io/is-default-class` | 默认类（未写 storageClassName 的 PVC 走它） | 多个默认类取**最近创建的那个**（允许共存只是为了平滑迁移）；retroactive 追填（Stable v1.28，见 §2.3） |

**为什么这么设计**：SC 全部字段=「供给决策点」，而不是「卷的运行时」。参数表公开是自由的，可一旦供给完成，盘活多久、被多少 Pod 用、要不要挪动，跟 SC 半毛钱关系没有——这就是为什么「改 SC 参数」从来不会改既有 PV 的行为（§2.9 讲的 VolumeAttributesClass 就是为解这层而出现的）。

### 2.8 HonorPVReclaimPolicy（v1.26 α → v1.31 β → v1.33 GA → v1.36 gate 移除）：一条历史泄漏尾巴

KEP-2644 揭了一个经典坑（官方 KEP 源码注释佐证）：

> `Bound` 的 PV-PVC 对上，**谁先删决定 reclaim 是否生效**。
> - 先删 PVC，后删 PV：reclaim 按 Delete 正常执行。
> - **先删 PV（比如运维手贱 `kubectl delete pv pvc-xxx`），后删 PVC**：老逻辑看到 PV 已带 `deletionTimestamp`，PV controller 在 `deleteVolumeOperation` 里把「对象已删除」当成了「删除已被处理」，直接 return——**reclaim 根本没跑，后端盘直接泄漏**（云账单默默增长）。

KEP-2644 的修法：

- CSI 卷：复用 `external-provisioner.volume.kubernetes.io/finalizer`（§2.5），external-provisioner 把它「**不管是动态还是静态供给，统统加上**」，PV 对象在它的看守下，只有后端真删了它才摘——于是顺序收敛为「先删后端，再释放对象」。
- in-tree 卷：补一个 `kubernetes.io/pv-controller` finalizer，处理逻辑对称（只加在动态供给的 in-tree PV 上）。
- `deleteVolumeOperation` 的调整：开了门控之后**忽略旧 `DeletionTimestamp` 判断**，以「PV 是否 Released」为触发点执行任务。

版本历程（KEP-2644 头注释）：**v1.26 Alpha、v1.31 Beta、v1.33 GA、v1.36 门控移除**——**v1.37 里这条行为已经是默认事实，不可再退回**。这也就是说：现在你在 v1.37 里删了一个 Bound 的 PV，即使 PVC 等下才删，**盘是真得没的**——这是一个「升级行为变了」的生产注意点（过去在很多集群是老误操作也无所谓，现在必须当正式操作对待）。

### 2.9 VolumeAttributesClass（v1.29 α → v1.31 β → v1.34 GA；v1.36 gate 锁定）：不停机换卷规格

SC 参数建完即冻（§2.7），现实中 iops/吞吐按跑流量调整很常见。**VolumeAttributesClass（VAC）** 定义一组「可变的属性类」：

```yaml
apiVersion: storage.k8s.io/v1
kind: VolumeAttributesClass
metadata:
  name: silver
driverName: csi.storage.example.com     # 必填；与 SC.provisioner 同源
parameters:                              # ≤512 项 / ≤256 KiB，driver 私有
  iops: "3000"
  throughput: "50Mi"
```

机制：

- PVC 上写 `spec.volumeAttributesClassName: silver`——**这个名字是可变字段**（改它不需要删 PVC）；VAC 对象自己的 parameters 内置不可变（换个类从新类，而不是就地改类）；
- 供给路径由 **external-provisioner** 所在侧把参数带进 `CreateVolume`；变更路径由 **external-resizer** 侧通过 CSI `ModifyVolume` RPC 下发（注意这条链与 resizer 的 size 语义无关——管的是 attributes，不是容量）；
- **限制**：仅 CSI、且驱动实现 `ModifyVolume`——一个驱动不支持时改动会在事件里报错但 PVC 旧属性照旧可用；
- 定位一句话：它解决的是「**不停机改卷的运行档位**」（iops/吞吐这类 QoS）——StorageClass 是供给模板（造盘时刻），VAC 是运行中的可调档（第 §5.1 的扩容量管大小，本节管规格）。

### 2.10 v1.35–1.37 顺手新增的两个新信号

- **`Unused` condition（v1.37 起 Beta 默认开）**：PVC Protection controller 给每个 PVC 加一个 condition——`Unused=True`（reason `NoPodsUsingPVC`）/ `False`（reason `PodUsingPVC`）。PVC 找僵尸盘（挂了 30 天没人用的）就有了一手官方信号，不必外挂控制器去 join Pod 表。Pending 的 Pod 仍算「用」。处于删除中的 PVC 不更新。
- **`MutablePVNodeAffinity`（v1.35 起 Alpha 默认关）**：允许 PV 的 `nodeAffinity` 处于可改状态，给「数据被迁走、PV 亲和要跟」的场景留出口。官方注意事项：新亲和必须仍覆盖当前在跑 Pod——官方明确在跑的违规 Pod 不会被强杀、但该形态不受支持（应尽早换掉）；缓存差异期间新 Pod 也可能按旧亲和调度一小会。

---

## 三、CSI 架构深拆（本章核心之二）

### 3.1 三个 gRPC service 是谁

CSI 规范把一个驱动拆成三个能力面，每个面对着 K8s 里不同的「老板」：

| Service | 对外的关键 RPC | K8s 里谁调它（以何种方式） |
|---------|---------------|---------------------------|
| **Identity** | `GetPluginInfo`（报驱动名）、`GetPluginCapabilities`、`Probe`（健康） | 启动期 bootstrap 端、livenessprobe sidecar |
| **Controller** | `CreateVolume`/`DeleteVolume`（供给）、`ControllerPublishVolume`/`ControllerUnpublishVolume`（attach/detach）、`ControllerExpandVolume`、`CreateSnapshot`/`DeleteSnapshot`、`ModifyVolume`（VAC） | external-provisioner / external-attacher / external-resizer / external-snapshotter sidecar（与 controller plugin 同 Pod，经同 unix socket 调它） |
| **Node** | `NodeGetInfo`（registrar 问）、`NodeStageVolume`/`NodeUnstageVolume`（节点级挂载）、`NodePublishVolume`/`NodeUnpublishVolume`（Pod 级 bind）、`NodeExpandVolume`、`NodeGetVolumeStats`、`NodeGetCapabilities` | **kubelet 直接调**（通过 unix socket；socket 位置由注册机制发现）；node-driver-registrar 启动期问一遍 |

### 3.2 一次「动态供给 + Pod 挂载」的完整链路

```
阶段 1：供给（control plane 侧）
┌──────────┐    ① PVC 创建(SC 指向 hostpath.csi.k8s.io)
│  用户    │ ─────────────────────────────────────────────────► apiserver
└──────────┘                                                     │ watch
                                                                 ▼
                                          external-provisioner（sidecar，watch PVC）
                                          ② Controller.CreateVolume(secrets,
                                                    name, capacity, params, topology?)
                                          ─► driver Controller service
                                          ③ 返回 volume_id；provisioner 写 PV 对象
                                             （+ external-provisioner.../finalizer，§2.5）
                                                                 │ watch
                                          PV controller（kube-controller-manager）
                                          ④ claimRef 双向锁 → PVC/PV 双双 Bound
阶段 2：attach（决策在 control plane、执行在驱动）
┌──────────┐
│ kubelet  │ ⑤ Pod 调度到 node-3（k8s 负责调度；PVC 此时已 Bound）
└──────────┘
   A/D controller（kube-controller-manager）发现：
     「这个 PV 的 CSIDriver.attachRequired=true 且 Pod 用了它」
   ⑥ 创建 VolumeAttachment{attacher, nodeName: node-3, source.persistentVolumeName: pv-1}
                                                                 │ watch
                                          external-attacher
                                          ⑦ ControllerPublishVolume(node_id=node-3,
                                                    volume_id, volume_context, readonly)
                                          ─► driver ─► 云 API/平台层「把盘挂到 node-3 VM」
                                          ⑧ VA.status.attached = true
阶段 3：mount（节点本地）
kubelet volume manager（§3.4）
   ⑨ 等 attach 完（attachRequired 时）→ Node service：
      NodeStageVolume(staging_target_path:
        /var/lib/kubelet/plugins/kubernetes.io/csi/pv/<pv-1>/globalmount,
        volume_capability: fstype/ext4, secrets?)   ← format+mount，节点级一次
   ⑩ NodePublishVolume(target_path:
        /var/lib/kubelet/pods/<podUID>/volumes/kubernetes.io~csi/<vol名>/mount,
        staging_path, readonly?)                   ← 从 globalmount bind 到 Pod 目录
   ⑪ 容器启动看见卷
（卸载逆过程）
   Pod 删 → NodeUnpublishVolume → 本节点再无 Pod 用 → NodeUnstageVolume
   A/D controller 清理 VolumeAttachment → external-attacher
     → ControllerUnpublishVolume → VA 对象消失
   PVC 删（reclaim=Delete）→ provisioner → DeleteVolume → 摘 finalizer → PV 对象消失
```

**为什么这么设计（三层分工的哲学）**：

- Identity/Controller/Node 分别对应「**我是谁 / 盘在云侧怎么活 / 盘在节点上怎么挂**」。前两个跨网络沟通平台，后一个在节点本地做权限密集操作——所以驱动部署形态天然二分：**controller 插件 + sidecar 像 Deployment 一样起一份（带 leader election）；node 插件 + registrar 像 DaemonSet 每节点一份**。
- Publish/NodePublish 一拆为二后，K8s 可以在 attach 完成之前先做别的（镜像拉取），volume manager 拿到「attach ok + stage ok」两票才算准备好。
- 所有不幂等的副作用（云 API 调用、格式化）都收进**独立于 kubelet 的 sidecar**——kubelet 只做本节点文件系统的事，重启不会把供给链摇散。

### 3.3 侧车容器矩阵（external-* 各管一摊）

| sidecar | watch 什么对象 | 调什么 RPC | 部署面 | 一句话 |
|---------|---------------|-----------|--------|--------|
| **external-provisioner** | PVC（未绑，SC 是自己的）+ StorageClass | `CreateVolume` / `DeleteVolume` | controller 插件同 Pod（leader election） | 唯一会造/删 PV 对象的；也负责写 `external-provisioner.../finalizer`（§2.5） |
| **external-attacher** | VolumeAttachment | `ControllerPublishVolume` / `ControllerUnpublishVolume` | controller 同 Pod | A/D controller 只造 VA 模型，attach 执行全外包 |
| **external-resizer** | PVC.spec.resources / volumeAttributesClassName 变化 | `ControllerExpandVolume` / `ModifyVolume` | controller 同 Pod | 还会维护 PVC status 的两个 allocated* 字段（§5） |
| **external-snapshotter** | VolumeSnapshotContent（**注意不是 VolumeSnapshot**） | `CreateSnapshot` / `DeleteSnapshot` | controller 同 Pod | 与集群级 snapshot-controller 分工（§4.3） |
| **node-driver-registrar** | —（启动期） | `NodeGetInfo` | node 插件同 Pod（DaemonSet） | 把 driver 的 socket 注册进 kubelet 的插件目录 `/var/lib/kubelet/plugins_registry`，并创建/更新 **CSINode 对象**（驱动 nodeID、topologyKeys、attach 可分配数） |
| **livenessprobe** | — | `Probe` | 双方都有 | 把 CSI endpoint 包装成 HTTP `/healthz` 给 K8s 用 |

看一眼真实部署长什么样（csi-driver-host-path 在 1.35/1.34 模板里把 8 个容器装一个 StatefulSet，输出 `csi-hostpathplugin-0 8/8 Running`）：`hostpathplugin`（一体 driver）+ attacher + provisioner + resizer + snapshotter + node-driver-registrar + livenessprobe + external-health-monitor。RBAC 也不玄学——deploy.sh 从对应 sidecar 仓库 tag 上各拉一份官方 rbac.yaml。

### 3.4 kubelet 侧：volume manager 的两个世界

kubelet 不面向 RPC 直接管卷，而是维护一对镜像：

- **Desired State of World（DSW）**：本节点哪些卷「应该」处于什么状态（由 populator 周期从本地 Pod 清单+对应 PVC/PV 计算，~30s 一轮全量）；
- **Actual State of World（ASW）**：哪些卷「现在」已 attach/stage/publish 成功（来自上次操作结果+节点落盘标记）。

reconciler 每 ~100ms 逐条比对两个世界，把差异打包成操作丢进 OperationExecutor 的队列：需要挂→走 §3.2 的 ⑨⑩；需要摘→逆过程。操作失败**指数退避重试**（数秒级起步、上限 10 分钟），连续失败就会产出 `FailedMount` 事件（「Unable to attach or mount volumes … timed out waiting for the condition」）。

**CSINode 对象**（registrar 维护）给的是**节点侧事实**：本节点有哪些驱动、nodeID 是啥、可 attach 多少（`allocatable.count`——第 2 章 NodeVolumeLimits 的判定材料）、topologyKeys（调度器 WFFC 拓扑对照的原料）。kubelet 的对象发现入口是 `plugins_registry` 里的注册文件（注册的内容只有指向 driver socket 的路径）。

### 3.5 attach ≠ mount：为什么一定要分两次

把「云盘接到一台宿主 VM」和「在宿主的哪里能看到它」切到完全不同的层面，是 CSI 对云时代的原生翻译：

| 层 | 物理动作 | 谁执行 | 慢/失败的典型原因 |
|----|---------|--------|------------------|
| attach（publish） | 调云平台 API，把卷对象挂到某 VM（产生 /dev/xxx 级设备出现的前提） | external-attacher → 云 API | API 限流/超时；卷还在别的节点没摘；attach 上限（见 CSINode.allocatable.count） |
| mount（stage+publish） | 节点本地 format + mount + bind 到 Pod 目录 | kubelet → Node 服务 | fstype 不支持、设备未出现、目录占用 |

对应的防护行为也就不同：attach 出问题 → VolumeAttachment 卡住 / FailedAttachVolume 事件 / 调度端 NodeVolumeLimits 提前截胡（这就是「attach 上限要被 scheduler 先考虑」的原因）；mount 出问题 → kubelet 退避重挂 + FailedMount 事件。

纯本地驱动（盘上根本没有「挂到 VM」这一步）**可以直接在 CSIDriver 对象里写 `spec.attachRequired: false`**，A/D controller 就不造 VolumeAttachment，跳过整个 attach 环节。（实验 4.1 的 hostpath 默认部署没这么写，所以你能完整看到 attach 事件链——虽然它的「云 API」只是个 mock。）

### 3.6 fsGroup 与 SELinux 的两次进化（都核对官方 security-context 页 + 源码 gate 表）

**fsGroup 侧**——chmod/chown 风暴的压制：

- 旧默认：挂卷时 kubelet **递归**给整卷 chown/chmod 到 fsGroup。10 万文件的卷上，Pod 启动能卡到分钟级。
- 一级缓解：`fsGroupChangePolicy: OnRootMismatch`（v1.23 起 Stable）——只有卷根目录 UID/GID 不匹配期望时才全量执行。
- 二级缓解（v1.26 起 Stable）：驱动声明 `VOLUME_MOUNT_GROUP` NodeServiceCapability 后，挂载时就地处理 fsGroup（`mount -o context/gid` 式），kubelet 不再递归改属主，此时 `fsGroupChangePolicy` 自然失效（k8s 已不管这事）。

**SELinux 侧**——三个 gate 的三步收敛（里程碑来自 k/kubernetes master 源码注释）：

| gate | 版本轨迹 | 效果 |
|------|---------|------|
| `SELinuxMountReadWriteOncePod` | v1.25 α → v1.28 β 默认开 → **v1.36 GA 锁定** | 只作用于 `ReadWriteOncePod` 卷——天然单 Pod 独占，用 `-o context=<label>` 挂载重打标最安全（不存在两 Pod 抢同一个卷的歧义） |
| `SELinuxChangePolicy` | v1.32 α → v1.33 β 默认开 → **v1.36 GA 锁定** | Pod 加 `spec.securityContext.seLinuxChangePolicy`：`MountOption`（默认：用挂载提速）/ `Recursive`（退出优化，回旧的递归重打标）。配套 SELinuxWarningController（kcm，默认关，`--controllers=*,selinux-warning-controller` 可开）侦测标签冲突 Pod 并发指标 |
| `SELinuxMount` | v1.30 α → v1.33 β 默认关 → **v1.37 GA 默认开** | 把 context 挂载推广到**全部符合条件的卷**：Pod 走 PVC、seLinuxChangePolicy 为 nil/MountOption、有 seLinuxOptions、且 PV 是 in-tree iscsi/rbd/fc 或 CSIDriver 声明了 `spec.seLinuxMount: true` 的 CSI 卷 |

生效后的两条硬规则（security-context 页原文）：

1. 挂载提速生效的卷，在同一节点上**所有使用它的 Pod 必须同 label**；不同意 label 的 Pod 会被 `ContainerCreating` 卡住直到另一拨退出——要混跑不同 label 的 Pod，必须给 Pod 显式写 `seLinuxChangePolicy: Recursive` 退回去。
2. 不满足条件的卷（emptyDir/secret/configMap 这类临时卷，或驱动未声明的 CSI 卷）依旧走老路：容器运行时整卷递归重打标。

❗ 官方升级建议原话：用 SELinux 的集群在升级到 v1.37（`SELinuxMount` GA 默认开）之前，先开启 `SELinuxChangePolicy` + SELinuxWarningController，盯住指标 `selinux_warning_controller_selinux_volume_conflict`，先把违规 Pod 显式打回 Recursive。

---

## 四、VolumeSnapshot API（机制视角）

### 4.1 对象三件套：与 PV/PVC/SC 是对称的

官方把这套对象直接做成了 PV/PVC 的影子结构：

| 卷的一头 | 快照的一头 | 角色 |
|---------|-----------|------|
| PV | **VolumeSnapshotContent** | 集群级，描述「后端那个真实快照实体」（`snapshotHandle`） |
| PVC | **VolumeSnapshot** | ns 级，用户的「给 PVC `xxx` 打个快照」的请求 |
| StorageClass | **VolumeSnapshotClass** | 供给策略：`driver` + `deletionPolicy` + `parameters` |

这样设计的理由与 PV/PVC 完全同构：资源域与应用域分离（管理员能预供给 Content；应用只管发 Snapshot 请求）。**三件套都是 CRD（`snapshot.storage.k8s.io/v1`），不在核心 API 里**——官方明确「CRD/snapshot-controller 的安装由发行版负责」，集群里没有 CRD 就是没有这个能力（Velero 文档 §15 的「先查 CRD」是同一句话的运营版）。

字段要点（官方核对）：

- **VolumeSnapshot.spec.source**：`persistentVolumeClaimName`（动态；必写）或 `volumeSnapshotContentName`（预供给；必写）。
- **VolumeSnapshotContent.spec.source**：动态时是 `volumeHandle`（指向源 PV 的后端 id）；预供给时是 `snapshotHandle`（指向后端已有的真快照）。
- **VolumeSnapshotClass.deletionPolicy**：`Delete`（Snapshot 删 → Content 和后端快照一并删）/ `Retain`（留着）。
- **默认类**：注解 `snapshot.storage.kubernetes.io/is-default-class: "true"`；**每个 driver 最多一个默认类**——同 driver 撞两个会让请求失败（官方原文）。
- **sourceVolumeMode**（Content 级，Filesystem/Block）：防止有人从 Filesystem 快照恢复出 Block 卷从而偷看裸数据；要允许转换需在 Content 上加注解 `snapshot.storage.kubernetes.io/allow-volume-mode-change: "true"`（官方核对）。

### 4.2 dynamic vs pre-provisioned

- **Dynamic**：用户给 PVC 名 → snapshot-controller 建 Content → csi-snapshotter 调 `CreateSnapshot` → readyToUse=true。日常备份演练都长这样。
- **Pre-provisioned**：管理员在存储侧已有快照 → 手工建 Content（填 `snapshotHandle` + `volumeSnapshotRef`）→ 用户建 VolumeSnapshot 点名 Content 绑上。用于接管「平台层早就在打的快照」、或跨集群搬迁时挂接既有快照实体。

绑定关系同样 1:1（Snapshot ↔ Content，双向 ref）。整个对象链不如PV/PVC那样有「Available/Released」完整状态机——快照的非工作状态主要靠 `status.readyToUse` / 绑定是否成立表达。

### 4.3 snapshot-controller（集群级）与 csi-snapshotter（driver 侧）：分工为什么这样切

```
VolumeSnapshot（ns 级，用户对象）
     │ ① watch，负责建/删 VolumeSnapshotContent、做绑定、
     │    管 volumesnapshot-bound-protection / content 侧 finalizer
     ▼
snapshot-controller（集群级单例 Deployment，发行版装，独立于 driver）
     │ ② watch VolumeSnapshotContent
     ▼
csi-snapshotter（driver 同 Pod sidecar）
     ③ CreateSnapshot/DeleteSnapshot → driver Controller service → 后端
```

切分哲学与 provisioner/attacher 是同一手：**控制面能有个单例控制器讲统一对象语义**（binding/finalizer/webhook 校验），还能省得每家 driver 重复实现同一套状态机；**真正的后端调用留进驱动的进程域**（幂等、重试、厂商差异）。两个组件任一缺失：有 CRD 没 controller → Snapshot 会一直未绑；有 controller 没 snapshotter sidecar → Content 存在 readyToUse 永远 false。官方还点名了一个**校验 webhook**（应对快照对象的语义约束，发行版应随车安装）。

### 4.4 从快照恢复一条新卷：dataSource 语义

```yaml
spec:
  storageClassName: csi-hostpath-sc       # 目标新卷怎样供给（与快照同 driver/域）
  dataSource:
    name: new-snapshot-demo
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

机制层行为（官方核对过）：

- provisioner 看到 dataSource 是 VolumeSnapshot → 调驱动 `CreateVolume` 时携带 snapshot 作 source → 后端**以快照为底创建新卷（新建一个真实卷，而非挂载快照）**。
- `dataSource` **仅在创建时生效**：PVC Bound 后改 dataSource 没任何作用；快照本身的后续删除/变更不影响已恢复的卷。
- 同样的机制服务于**克隆**：`dataSource` 换 `kind: PersistentVolumeClaim`，要求**源 PVC 同 ns**，驱动声明能力——底层通常是后端的 copy-on-write 或完整复制（见 §5.5）。

### 4.5 拓扑在哪：VolumeSnapshotTopology（sidecar 级 alpha）

多 zone 集群里「A zone 的卷快照」往往只能在 A zone 用。三个组件连锁解决（官方核对）：

1. 管理员在 VolumeSnapshotClass 上写 `allowedTopologies`（约束动态快照要落在哪些拓扑段可用）；
2. CSI 驱动在 `CreateSnapshot` 应答里上报快照可用范围 → **csi-snapshotter sidecar 把它记录在 `VolumeSnapshotContent.spec.nodeAffinity`**；
3. external-provisioner 从这个 Content 的 nodeAffinity 出发恢复卷——新 PV 自带正确的拓扑，调度器和 §6 的链路正常运转。

该特性以 `VolumeSnapshotTopology` gate 挂在 csi-snapshotter/external-provisioner 两个 sidecar 上（alpha，配套于 KEP 外部 CSI docs）——看到 nodeAffinity 出现在 Content 里，就明白它是快照把拓扑一路传到调度端的通道。

### 4.6 VolumeGroupSnapshot（KEP-3476：v1.27 α → v1.32 β → v1.36 GA）

数据库 data 目录 + WAL 两块盘需要**同一点**的一致性快照——逐张打做不到写序一致。群快照用与单快照对称的一套 CRD（API 组 `groupsnapshot.storage.k8s.io/v1beta1`）解决：

- `VolumeGroupSnapshot`（ns 级）：`source.selector.matchLabels` 圈住一组 PVC（host-path 仓库示例就是按 `app.kubernetes.io/name: postgresql` 圈）+ `volumeGroupSnapshotClassName`；
- `VolumeGroupSnapshotContent` / `VolumeGroupSnapshotClass` 对应外层两个角色，`deletionPolicy` 语义同单快照；
- 恢复面也以组为单位：从组快照恢复多张 PVC（每成员一个 VolumeSnapshot/Content 的影子结构，便于按卷恢复）。

之所以拖了八年才稳定：快照的一致性语义在各后端差异很大（崩溃一致 vs 应用静默），sig-storage 选择把「静默/通知」留给备份栈做（Velero hook），K8s 层只保证「后端一次 atomic 动作产生一组点」。

### 4.7 限制与坑 + 与 Velero 的分工

- **快照不是备份**：快照与源卷在同一存储域/故障域（云里「EBS 快照在 S3」是个例外，它的 S3 是同 region 受管存储），同存储阵列/同 zone 团灭时快照跟着没了——快照的工单用途是**本地快速恢复/克隆/预变更保护**，备份要用会跨走的（Velero + Data Mover 或对象存储）。
- **跨 StorageClass/driver 恢复不支持**：`dataSource` 恢复要求目标 SC 的 provisioner 能消化这份源——driver 不一样直接失败（事件里报）；同 driver 不同 SC 的实践上也应指向同一后端家族（改了 `parameters` 指的是别的存储域，恢复必然失败）。
- **跨 zone 恢复要过拓扑**：靠 §4.5 的 nodeAffinity+SC 的 allowedTopologies/标签，落到实处仍取决于后端是否真把快照放在多 zone 可读处。
- **加密**：快照的加密属性由后端自己的密钥策略决定（KMS 托管/自管各自一套），K8s 不参与密钥生命周期——从加密卷快照恢复出的卷是否加密/用哪把 key，验收时实测，别靠直觉。

> 📎 与 Velero 衔接一句：`Velero-Kubernetes备份恢复与迁移指南.md` §15 讲了 CSI 快照在备份运维里的用法（BSL/VSL、Data Mover 把快照内容搬进对象存储）；本章只负责三件套的对象机制、分组件职责与 dataSource 恢复语义，两边的交集 object 是同一份。

---

## 五、扩容与克隆

### 5.1 扩容的两级模型：控制面 vs 节点

前置条件：**SC.allowVolumeExpansion: true**（没有就是 apiserver 直接拒绝 patch）。能扩不能缩——PVC 永远改不小（§5.3 专门讲失败重试通道，那不是缩）。

```
用户 patch spec.resources.requests.storage 1Gi→2Gi
  │
  ├─ 控制面扩容：external-resizer（watch 到变化）
  │     → Controller.ControllerExpandVolume(volume_id, required_bytes)
  │     → 云盘/阵列把盘做大；驱动回 NodeExpansionRequired=true/false
  │
  └─ 节点扩容（需要时）：kubelet（等本节点真有 Pod 用这卷）
        → Node.NodeExpandVolume(volume_path, required_bytes, fstype)
        → 在线把文件系统扩到满盘（仅支持 XFS/ext3/ext4，官方核对）
```

- 两级拆开的原因：云盘上「改元数据」与「节点上 resize2fs」耗时、幂等性质完全不同；同一卷被 RWX 多节点共用时还要对 driver 的 `NodeExpansionRequired=false` 特判。较新版本的 external-resizer 针对「RWX 且控制面扩完即完事」的卷会给 PVC 打 `volume.kubernetes.io/node-expansion-not-required` 注解，kubelet 见到它就跳过 Node 扩容、只把新大小记进 ASW（KEP-1790 实现细节有写）。
- 文件系统扩容时刻（官方原文）：「要么在 Pod 启动时做，要么在 Pod 运行中且底层文件系统支持在线扩容时做」。**没有任何 Pod 用这 PVC 时，Node 扩容没人做**——起个 Pod 让它跑一段（这就是「In-use PVC 扩容 v1.24 起 Stable」的语义边界）。
- in-tree 类型里 CSI 迁移过的 EBS/PD 等都支持扩（v1.24 起 CSI 扩容 Stable）。
- RWX 且 driver 明示不需要节点扩的场景（网络 FS 只有控制面增长是常态），带前述注解后 kubelet 不会傻等 Node 扩容。

### 5.2 PVC status 的读法（KEP-1790 定形的字段族）

```yaml
status:
  capacity:                      # 已生效大小（最终事实）
    storage: 2Gi
  allocatedResources:            # 最后一次 resizer 已认领去做的目标（扩容途中会>capacity）
    storage: 5Gi
  allocatedResourceStatuses:     # 按资源 key 记录当前任务形态
    storage: NodeResizePending   # 五态之一
  conditions:
  - type: Resizing / FileSystemResizePending
```

`allocatedResourceStatuses[storage]` 五态（KEP-1790 定文字）：`ControllerResizeInProgress`（控制面在做）→ 失败为 `ControllerResizeFailed`；控制面完 → `NodeResizePending`（等节点）→ `NodeResizeInProgress` → 失败为 `NodeResizeFailed`，成功则置空串、并把 capacity 补上。

为什么会多一道「allocatedResources」而不是看 spec：**因为要防 quota 滥用**。配额按 `max(spec.resources, status.allocatedResources)` 计——你申请 500G 失败又改回 20G，只要控制器没确认失败回收，quota 账面就一直按已认领过的算（直指 §5.3 场景）。

### 5.3 RecoverVolumeExpansionFailure：扩容失败的官方救援通道（α v1.23 → β v1.32 默认开 → GA v1.34，锁定默认开；组件：apiserver/kcm/external-resizer/kubelet）

故事：叫了 500G，后端撑不出——在老逻辑里 resizer 会**无限重试**，PVC 卡死在中间态，你也**不许把申请改回去**（API 校验拒绝变瘦，只能眼睁睁挂着）。

KEP-1790 的通道：

1. resizer/kubelet 把「终极失败」以 gRPC 错误码 `INVALID_ARGUMENT` / `OUT_OF_RANGE` / `NOT_FOUND` 认定（infeasible 一类），把 allocated* 字段钉进失败态、发事件、降速重试；
2. **API 校验放行**：允许把 `spec.resources.requests.storage` 改小，但**仍必须 > status.capacity**（到底能不能缩仍是不行）；
3. resizer 观察到 spec 变小 + 上一轮 allocated* 已经是失败态 → **重置 allocatedResources 为新值，重新走一遍扩容**——这就是「改小再来」的正确姿势；
4. 成功则 capacity 追上来，quota 也自然回落——账面闭环。

❗ 实务两条：

- 「重置后还是失败」最常见的两个根因是 SC 不接受这么大块、或后端配额——读事件 + `csi_sidecar_operations_seconds{method_name="/csi.v1.Controller/ControllerExpandVolume"}`（resizer 侧）/ `storage_operation_duration_seconds{operation_name=volume_fs_resize}`（kubelet 侧）定位。
- KEP 也兜了一句极端形态：扩容**控制面已成功、仅是节点侧失败**（NodeResizePending/NodeResizeFailed 卡住）时，**出于 quota 保护不许你往小改**（盘在控制面已经变大了）——这时老老实实修节点侧（文件系统错误、驱动 fs 支持），或者 kubelet 的 `storage_operation_duration_seconds{operation_name="volume_fs_resize"}` 指标走一波。

### 5.4 在线扩容的现状边界

v1.24 起「正在使用的 PVC」就能扩，不用重建 Pod；但**全部完成需要节点侧有人在线跑这个 Pod**——也就是：长期闲置的 PVC，先起个引用它的 Pod（Pod spec 挂载/引用即可，应用不写数据也行），Node 扩容推一把后 capacity 正式生效。offline-only 的扩容该用得更像运维仪式（`describe pvc` 的 conditions 告诉你差哪一步）。

另一个边界：文件系统支持面官方只认 XFS/ext3/ext4，**裸 Block 卷模式下没有 FS 扩容这一说**——底层块变大后怎么消化（LVM 通知、应用层重做）是应用的事。

### 5.5 克隆：dataSource 指 PVC

```yaml
dataSource:
  name: existing-src-pvc
  kind: PersistentVolumeClaim         # 源必须同 ns
```

机制：供给时驱动以源卷为底发一个新卷。克隆 vs 「快照 + 恢复」的取舍：

| 维度 | 克隆 | 快照 + 恢复 |
|------|------|------------|
| 步骤 | 一步到位（驱动一次性做完） | 两个对象两步，中途可跨人协作 |
| 源后能不能删 | 克隆完成即彼此独立 | 恢复进行中快照对象不能先死——由 `snapshot.storage.kubernetes.io/volumesnapshot-bound-protection` 撑住（§2.5） |
| 跨版本/演练 | 适合「同集群复制一份试跑」（金丝雀数据库验证） | 适合「找个时间点备份、之后随时回来」 |
| 拓扑 | 同源同域；驱动决定 CoW 或全复制 | 快照的拓扑可用范围经过 Content.nodeAffinity 一路传递 |
| 可用性 | 源卷必须存在、可访问（官方文档：仅 CSI 驱动支持克隆） | 快照可供远端/多层恢复 |

**共通约束**：都是**新 PVC、新卷**——dataSource 不产生共享后端的「链接」，没有写穿；源卷做了加密则按 §4.7 同样的预期去验收恢复品。

---

## 六、本地存储与拓扑感知

### 6.1 local PV：「我的盘就在节点上」的正确打开方式

官方定位（核对过的硬事实）：`local` 卷**只支持静态供给**，**PV 上 nodeAffinity 必填**——这就是它区别于 hostPath 的地方：能不能被调度到对的节点是**写进对象**的，调度器认对象，不认部署文档里的口头约定。

```yaml
apiVersion: v1
kind: PersistentVolume
spec:
  capacity: { storage: 100Gi }
  accessModes: [ "ReadWriteOnce" ]
  persistentVolumeReclaimPolicy: Delete
  storageClassName: local-storage            # 对应 SC：provisioner: kubernetes.io/no-provisioner + volumeBindingMode: WaitForFirstConsumer
  local:
    path: /mnt/disks/ssd1
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - { key: kubernetes.io/hostname, operator: In, values: [worker-1] }
```

机制要点：

- **防漂**：PV nodeAffinity 告诉调度器「这盘只在 worker-1 能读到」；PVC 跟它绑定后 Pod 永远落在 worker-1——这就是「不会漂到没有盘的节点」的机制层保证（第 2 章 §5 VolumeBinding 的 Filter 是入口，数据侧就是这条 affinity）。
- **WFFC 配套**：建议 SC 用 `kubernetes.io/no-provisioner` + `WaitForFirstConsumer`——绑定延迟到消费者 Pod 调度时，「调度器选节点」与「PV 亲和」两约束被一起满足（官方 SC 文档原话；即使 local 卷静态供给只支持预先绑，WFFC 模式作用在「何时绑定」而非「何时供给」）。
- **可用性权衡（官方原话级别）**：节点挂 → 卷不可用、Pod 起不来。local 卷用户必须容忍「对应节点的单点」：raft 类应用靠副本，临时热处理靠重算。换句话：stateful 的关键盘不要裸 local。
- **目录供给的自动发现**（官方推荐的外部静态供给器）：`sig-storage-local-static-provisioner` 按 discovery 目录 DaemonSet 扫，代建 local PV ——注意「它是静态供给器，不做动态供给」。
- MutablePVNodeAffinity（§2.10）是未来「数据搬走了，PV 亲和也要改」的口子，目前还是 alpha。

### 6.2 Storage Capacity Tracking：供给侧另一头的账

§2 章讲了调度器怎么消费容量；这里讲**数据侧**（supply side），官方 conditions（核对过）全以下达标才会被消费：

1. Pod 的卷还没供给（WFFC SC）；
2. SC 指向 **CSI 驱动**；
3. CSIDriver 对象 `spec.storageCapacity: true`（**管理员的门**；没写 true 一切白搭）。

CSI 驱动按「storageClass × topology 段」产出 `CSIStorageCapacity` 对象（该对象承载容量值，API 面 v1.24 起 Stable）。调度器仅做**大小比较**（VolumeBinding Filter），官方反复提醒：数据**可能过期**；选错节点、provisioner 供给失败 → 撤掉 selected-node 注解 → 重新调度（乐观假设 + 失败重试模型的正身）。**多卷组合场景**是死结：第一张已在某段建了，第二张这段装不下——官方说要人工（扩容量或先删前卷）。

容量感知**明确不覆盖** CSI ephemeral 卷（节点本地造，账不是在供给层做的）。

### 6.3 本地供给器选型三句话

| 方案 | 一句话 | 规模姿势 |
|------|--------|---------|
| **local-path-provisioner**（Rancher） | 极简单机目录型动态供给器：只在节点上 mkdir 出目录映射进 PVC，像「可声明的 hostPath」 | 单节点/边缘/开发环境；放弃节点故障数据可用性 |
| **TopoLVM**（Cybozu） | 基于 LVM thin 的本地盘 CSI：容量账、调度器扩展/定制打分、LV 快照/克隆/扩容三件套 | 生产级裸金属/LVM 本地高性能 |
| **OpenEBS**（LocalPV/ZFS/LVM 引擎系） | 模块化的容器附加存储：全 CSI，有 Mayastor（NVMe-oF 复制）、LocalPV 分档 | 要本地性能也要可选复制/跨节点时更全家桶 |

共同底线：都是 Kubernetes 原生 CSI 接入，可被 §3 的所有机制（快照、扩容、拓扑）恰好装上——这就是 CSI 化最大的生态红利。

---

## 七、常见生产问题清单（存储面）

| # | 症状 | 根因链 | 排查动作 | 处置 |
|---|------|--------|---------|------|
| 7.1 | PVC 一直 `Pending` | 四选一：① SC 名写错或不存在（provisioner 没人认领）② provisioner 不见（CSI driver 没装/挂了）③ parameters 或后端配额错（供给返回失败）④ WFFC 在等首个消费者 Pod（「等 Pod 先调度」是有意行为，不是 bug）；另查 ResourceQuota（PVC 数与 `requests.storage` 额度） | `kubectl describe pvc <name>` 读 events：`waiting for a volume to be created` / `failed to provision volume with StorageClass` / `waiting for first consumer`；再 `kubectl get pods -n <driver-ns>` 看 provisioner sidecar | 按 event 说话：SC 名→改 PVC/SC；provisioner 挂→拉起来；参数配额→去后端/云查配额；WFFC→把 Pod 起来再走（§2.7） |
| 7.2 | `Multi-Attach error for volume ... is already used by pod(s) ...` | RWO 卷被 Pod 从旧节点迁到新节点，旧节点的 attach 没清完（Pod 被强删 / 节点 NotReady 未了）——K8s 的 A/D 模型和 CSI 的 publish 都站在「保守防双写」一侧 | `kubectl get volumeattachment` 看旧 VA 还在；`kubectl describe pod` 确认迁移事件；`kubectl get node` 看旧节点状态 | **节点已死**：等默认 toleration 期满（约 6 分钟）系统强摘，或确认节点永不回来再手工清旧 VA（**不要在新旧节点都可能活着时强清，双写就完了**）；节点活着：查旧 Pod 为什么没真退出（kubelet 未响应 drain） |
| 7.3 | attach 超时/`FailedAttachVolume` 反复 | 云 API 限流/超时最常见（provisioner/attacher 到云的链路）；其次是 attach 容量上限（NodeVolumeLimits 调度时没拦住，A/D 还是被拒） | external-attacher 日志 + 云配额看板；`kubectl get csinode <node> -o yaml` 看 `spec.drivers[].allocatable.count` 与已占用 | 限流→云侧调配额/重试窗口；attach 上限→扩容节点或让 Driver 合法抬上限（很多驱动 48/64 上限可调） |
| 7.4 | 扩容 patch 了 PVC，capacity 不涨 | 三级查：SC.allowVolumeExpansion=false（apis 拒绝）；后端不支持或配额不够（ControllerResizeFailed）；节点侧没人用 PVC 或文件系统不支持（NodeResizePending 卡着） | `kubectl get pvc <p> -o jsonpath='{.status.allocatedResourceStatuses}'` + conditions + events 三方读 | 失败→§5.3 的「改到可行值重试」流程；等待 NodeResizePending → 起个 Pod 用它；FS 不支持（非 xfs/ext3/ext4）→ 换设计 |
| 7.5 | Pod 启动极慢，挂载阶段卡几十秒~几分钟，卷文件数很多 | **fsGroup 整卷 chown/chmod**（§3.6）或 **SELinux 递归重打标**在跑——都是「改几十万 inode」需要的时间 | `kubectl describe pod` 看卡在挂载侧；sh 进节点挂卷目录估 inode 数；查驱动是否声明 VOLUME_MOUNT_GROUP / seLinuxMount | 优先级：fsGroupChangePolicy: OnRootMismatch（v1.23 GA）→ 让驱动实现 VOLUME_MOUNT_GROUP（v1.26 GA）→ SELinux 集群按 §3.6 接入 SELinuxMount 系列（v1.37 GA） |
| 7.6 | Pod 删了，PV 却留在 `Released`，盘也不见少 | reclaim=Retain 的预期行为（设计上就不自动）；或 finalizer 卡住（provisioner 删后端失败，§2.5） | `kubectl get pv <pv>` 看 phase/Reclaim Policy/finalizers；`kubectl describe pv` 读 finalizer+events | Retain：按 §2.4 手工四步；finalizer 卡住：按第 1 章纪律先修「后端为什么删不掉」（凭据/驱动挂），别强摘 |
| 7.7 | 「我删了 Bound 的 PV，盘实际被回收了」 | v1.33 起 **HonorPVReclaimPolicy GA** 后的正常行为——先删 PV 也会真删后端盘（§2.8）。很多老集群的脑内模型还停在「这样删会泄漏」 | 查操作审计；`kubectl get pv -o yaml` 看 finalizer；云侧查盘是否存在 | 认知升级优先：生产上把「删 Bound PV」列为正式操作；要救盘：Retain 策略 + 快照先行 |
| 7.8 | VolumeSnapshot 建好 readyToUse 总 false / 恢复出的卷是空 | 三类：① 快照 CRD/snapshot-controller/snapshotter 缺失或撞默认类（同 driver 两个默认 VSC 会失败，官方原文）② 快照还没 readyToUse 就被恢复引用（恢复出的卷=空）③ 跨 driver/zone 不可达（拓扑未跟随） | `kubectl get volumesnapshotclasses,content,snapshots`；`kubectl describe volumesnapshot <name>` 的 message | 先让 readyToUse=true 再恢复；默认类唯一化；跨域恢复走 §4.5/§4.7 拓扑通道与多副本手段 |

---

## 八、实验（kind 沙箱 4 连）

> 环境：`kind`（v0.2x+）、`kubectl`、`git`、`docker`。所有命令均可直接粘贴；基线镜像用当前 kind 默认（或可指定 `kind create cluster --image kindest/node:v1.37.x`）。
> 实验 4.1–4.4 共用同一个 kind 集群，按序执行；每个实验带独立清理步骤，也可最后一把 `kind delete cluster` 全清。

### 实验 4.1 部署 csi-driver-host-path，拆一次动态供给链（对照 §3.2）

**step 1：起集群 + 装快照 CRD 和集群级 snapshot-controller（driver 官方前置）**

```bash
kind create cluster --name csi-exp

# VolumeSnapshot 三件套 CRD + 单例 snapshot-controller（官方 host-path 文档步骤；
# 版本用与仓库 docs 时间相近的外部 snapshotter 标签，本文以 v8.6.0 验证过下列 URL 有效）
SNAPVER=v8.6.0
for f in volumesnapshotclasses volumesnapshotcontents volumesnapshots; do
  kubectl apply -f "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/${SNAPVER}/client/config/crd/snapshot.storage.k8s.io_${f}.yaml"
done
kubectl apply -f "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/${SNAPVER}/deploy/kubernetes/snapshot-controller/rbac-snapshot-controller.yaml"
kubectl apply -f "https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/${SNAPVER}/deploy/kubernetes/snapshot-controller/setup-snapshot-controller.yaml"
kubectl -n kube-system rollout status deploy/snapshot-controller --timeout=90s
```

**step 2：克隆 driver 仓库并部署（一条脚本拉起 8 容器的 StatefulSet）**

```bash
cd /tmp && git clone --depth 1 https://github.com/kubernetes-csi/csi-driver-host-path.git
cd csi-driver-host-path

# deploy.sh 是符号链接 → ../util/deploy-hostpath.sh；kubernetes-latest → 1.35 → 1.34（真实清单目录）
deploy/kubernetes-latest/deploy.sh

# 等驱动就绪（8/8：hostpathplugin + attacher + provisioner + resizer + snapshotter + registrar + livenessprobe + health-monitor）
kubectl wait pod/csi-hostpathplugin-0 --for=condition=Ready --timeout=180s
kubectl get pods
```

**step 3：创建 SC/PVC/Pod（用仓库自带示例）**

```bash
for i in ./examples/csi-storageclass.yaml ./examples/csi-pvc.yaml ./examples/csi-app.yaml; do
  kubectl apply -f $i
done
kubectl wait pvc csi-pvc --for=jsonpath='{.status.phase}'=Bound --timeout=60s
kubectl wait pod my-csi-app --for=condition=Ready --timeout=120s
```

**step 4：按 §3.2 的四个阶段把事件对号入座**

```bash
kubectl describe pvc csi-pvc | sed -n '/Events/,$p'
kubectl describe pod my-csi-app | sed -n '/Events/,$p'
kubectl get volumeattachment
kubectl get csidriver, csinode
kubectl get pv $(kubectl get pvc csi-pvc -o jsonpath='{.spec.volumeName}') -o yaml | head -40
```

| 事件/对象 | 属于哪一阶段（对照 §3.2） | 谁在写 |
|-----------|--------------------------|--------|
| `Provisioning` → `ProvisioningSucceeded: Successfully provisioned volume pvc-...` | 阶段 1 ②③ CreateVolume → 写 PV | external-provisioner |
| PVC/PV `Bound` | 阶段 1 ④ claimRef 双向锁 | PV controller |
| `Scheduled`（Pod 落点） | 调度结果 | kube-scheduler |
| `SuccessfulAttachVolume: AttachVolume.Attach succeeded for volume "pvc-..."`（from `attachdetach-controller`） | 阶段 2 ⑥⑦⑧ VolumeAttachment+ControllerPublish | A/D controller + external-attacher |
| `-`（无独立事件，但可 `get volumeattachment` 看 status.attached=true） | attach 达成的持久凭据 | external-attacher |
| `Pulling/Pulled/Created/Started`（from `kubelet`） | 阶段 3 ⑨⑩（NodeStage/NodePublish 完成才到这） | kubelet volume manager |

节点侧的物证可选看：

```bash
# hostpath 卷的 Pod 目录形态（对照 §3.2 的路径图）
docker exec -it csi-exp-control-plane sh -c \
  'ls /var/lib/kubelet/pods/*/volumes/kubernetes.io~csi/*/mount 2>/dev/null | head'
```

### 实验 4.2 快照 → dataSource 恢复（对照 §4）

**step 1：先在卷里留一个标记文件，再打快照**

```bash
kubectl exec my-csi-app -- sh -c 'echo "marker:$(date +%s)" > /data/hello.txt && cat /data/hello.txt'

kubectl apply -f ./examples/csi-volumesnapshotclass.yaml    # deletionPolicy: Delete
kubectl apply -f ./examples/csi-snapshot-v1.yaml            # 名为 new-snapshot-demo，源 csi-pvc

kubectl wait volumesnapshot new-snapshot-demo \
  --for=jsonpath='{.status.readyToUse}'=true --timeout=90s
kubectl get volumesnapshot,volumesnapshotcontent
```

**step 2：看一眼 finalizer/绑定状态（对照 §2.5 / §4.1）**

```bash
kubectl get volumesnapshot new-snapshot-demo -o jsonpath='{.metadata.finalizers}'; echo
kubectl get volumesnapshotcontent -o jsonpath='{.items[0].spec.volumeSnapshotRef.name}{"  "}{.items[0].metadata.finalizers}'; echo
# 可再确认 §4.3 的两个保护：kubectl describe pvc csi-pvc | grep -i finalizer
```

**step 3：从快照恢复一个新 PVC，挂载验证数据一致**

```bash
kubectl apply -f ./examples/csi-restore.yaml                # hpvc-restore（dataSource 指 new-snapshot-demo）
kubectl wait pvc hpvc-restore --for=jsonpath='{.status.phase}'=Bound --timeout=60s

cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: { name: restore-check }
spec:
  containers:
  - name: c
    image: busybox
    command: [ "sh", "-c", "sleep 3600" ]
    volumeMounts: [{ name: data, mountPath: /data }]
  volumes:
  - name: data
    persistentVolumeClaim: { claimName: hpvc-restore }
EOF

kubectl wait pod restore-check --for=condition=Ready --timeout=60s
kubectl exec restore-check -- cat /data/hello.txt           # 看得到 snapshot 前写的 marker 即通过
```

**step 4（可选）：验证「快照期间的源 PVC 保护」（§2.5 / §4.3）**

用一块单独的临时 PVC 来做（**不要动 csi-pvc——实验 4.3 还要用它扩容**）：

```bash
kubectl apply -f ./examples/csi-pvc.yaml --dry-run=client -o yaml | \
  sed 's/name: csi-pvc/name: protect-src/' | kubectl apply -f -
kubectl wait pvc protect-src --for=jsonpath='{.status.phase}'=Bound --timeout=60s

# 快照 + 立刻删源：PVC 应被 pvc-as-source-protection 压住直到快照 readyToUse
kubectl apply -f ./examples/csi-snapshot-v1.yaml --dry-run=client -o yaml | \
  sed 's/name: new-snapshot-demo/name: snap-protect-demo/; s/persistentVolumeClaimName: csi-pvc/persistentVolumeClaimName: protect-src/' | kubectl apply -f -

kubectl delete pvc protect-src & sleep 2; kubectl get pvc protect-src
#   期望：STATUS=Terminating，metadata.finalizers 里能看到 snapshot.storage.kubernetes.io/pvc-as-source-protection

kubectl wait volumesnapshot snap-protect-demo --for=jsonpath='{.status.readyToUse}'=true --timeout=90s
sleep 5; kubectl get pvc protect-src 2>/dev/null || echo "保护语义生效：快照就绪后源 PVC 才真正消失"
```

> hostpath 打快照是目录复制，大概率 2 秒内就 readyToUse——竞争窗口一闪而过时（第 5 行已看不到 protect-src）属正常；在云盘类 CSI 驱动上，这段保护窗口能拉到几秒甚至分钟级，行为完全一致。

**清理**：`kubectl delete volumesnapshot new-snapshot-demo snap-protect-demo pvc hpvc-restore protect-src pod restore-check --ignore-not-found`

### 实验 4.3 扩容 + 读状态字段（对照 §5）

csi-hostpath-sc 自带 `allowVolumeExpansion: true`（仓库示例文件原位）。**保持 my-csi-app 在跑**（Node 扩需要有人用这卷）。

```bash
# step 1：1Gi → 2Gi
kubectl patch pvc csi-pvc --type=json -p='[{"op":"replace","path":"/spec/resources/requests/storage","value":"2Gi"}]'

# step 2：连环读状态（对照 §5.2 的字段族）
kubectl get pvc csi-pvc -o jsonpath='{.status.allocatedResourceStatuses}'; echo
kubectl get pvc csi-pvc -o jsonpath='{.status.capacity}{" <- capacity"}{"\n"}'
kubectl describe pvc csi-pvc | sed -n '/Events/,$p'

# step 3：到达终态的标准观察（事件含 External resizer is resizing volume；
#        allocatedResourceStatuses 短暂闪烁后清空，capacity=2Gi）
kubectl wait pvc csi-pvc --for=jsonpath='{.status.capacity.storage}'=2Gi --timeout=120s
```

> ❗ hostpath 驱动扩得快，瞬态字段（`ControllerResizeInProgress`/`NodeResizePending`）可能一闪而过——盯不到位的话，用 `kubectl get pvc csi-pvc -o yaml -w` 从头合跑一遍。
> 拓展练习（不动手）：设计一个必失败的扩容来走 §5.3 的 RecoverVolumeExpansionFailure 全流——hostpath 驱动不模拟容量耗尽，在云/LVM 后端上把请求喊过池子上限，观察 allocatedResourceStatuses 打上 `ControllerResizeFailed`，再把申请改小到「略大于 status.capacity」的值，看 resizer 重置 allocatedResources 重跑。

### 实验 4.4 WFFC：PVC 先 Pending，Pod 来了才供给（对照 §2.7 + 第 2 章 §5）

```bash
# step 1：加一个 WFFC 版本的类（同 provisioner、同参数，只改 binding mode）
cat <<'EOF' | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata: { name: csi-hostpath-wffc }
provisioner: hostpath.csi.k8s.io
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer   # 关键这一行
allowVolumeExpansion: true
EOF

# step 2：建 PVC——它必须 Pending（不是出错，是在等第一个消费者）
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: wffc-pvc }
spec:
  accessModes: [ "ReadWriteOnce" ]
  resources: { requests: { storage: 1Gi } }
  storageClassName: csi-hostpath-wffc
EOF

kubectl get pvc wffc-pvc            # STATUS=Pending；此时 get pv 看不到对应卷
kubectl describe pvc wffc-pvc | sed -n '/Events/,$p'
#   事件里看到 waiting for first consumer / waiting for a volume to be created

# step 3：起一个用它的 Pod
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: { name: wffc-app }
spec:
  containers:
  - name: c
    image: busybox
    command: [ "sh", "-c", "sleep 3600" ]
    volumeMounts: [{ name: data, mountPath: /data }]
  volumes:
  - name: data
    persistentVolumeClaim: { claimName: wffc-pvc }
EOF

kubectl wait pvc wffc-pvc --for=jsonpath='{.status.phase}'=Bound --timeout=120s

# step 4：验证三件事——调度器打的注（selected-node）、PV 其上的亲和、Pod 起来了
kubectl get pvc wffc-pvc -o jsonpath='{.metadata.annotations}'; echo
kubectl get pv $(kubectl get pvc wffc-pvc -o jsonpath='{.spec.volumeName}') -o jsonpath='{.spec.nodeAffinity}'; echo
kubectl get pod wffc-app
```

> ❗ 注解里的 `volume.kubernetes.io/selected-node: <node>` 是「Pod 落点已选」的合同信号——这比第 2 章 §5 的讲解更直观：先 Pod 后盘。`nodeAffinity` 内容取决于驱动是否开 topology 上报；hostpath 的默认部署主要以「供给瞬间锚定节点」演示 WFFC 的链，没有拓扑键也属正常（部署了 distributed 形态则能看到 topology.hostpath.csi/node 键）。

**清理（全部实验）**

```bash
deploy/kubernetes-latest/destroy.sh
kind delete cluster --name csi-exp
rm -rf /tmp/csi-driver-host-path
```

---

## 九、速查表 + 背诵要点 + 参考链接

### 9.1 一页速查

| 主题 | 命令 / 字段 / 对象 |
|------|-------------------|
| PV/PVC 生命周期 | phase: Pending/Bound/Available/Released/Failed；claimRef 双向绑定；`pv.kubernetes.io/bound-by-controller` 注解 |
| PVC 卡 Pending | `describe pvc` 读 events → 四类根因（SC/provisioner/参数/等消费者，§7.1） |
| 预绑/预留 | `pvc.spec.volumeName` 点名 PV（不查 nodeAffinity，仍校验类/模式/大小）；`pv.spec.claimRef` 定向预留 |
| reclaim | Retain 手工四步 / Delete 默认 / Recycle 已废弃（1.37 仅 nfs+hostPath） |
| finalizer 全景 | 对象保护：`kubernetes.io/pv-protection`、`kubernetes.io/pvc-protection`；后端删除保护（v1.31+）：`external-provisioner.volume.kubernetes.io/finalizer`、`kubernetes.io/pv-controller`；快照域：`snapshot.storage.kubernetes.io/*-protection`（§2.5） |
| 供给分流 | SC.provisioner；`kubernetes.io/no-provisioner` 只绑不供；多默认类取最新 |
| 拓扑联动 | `volumeBindingMode: WaitForFirstConsumer`；`selected-node` 注解；PV.spec.nodeAffinity；CSIDriver.spec.storageCapacity + CSIStorageCapacity |
| attach/mount 链 | VolumeAttachment{attacher,nodeName,source.persistentVolumeName} → status.attached；目录：`plugins/kubernetes.io/csi/pv/<pv>/globalmount` → `pods/<uid>/volumes/kubernetes.io~csi/<vol>/mount`；注册目录 `/var/lib/kubelet/plugins_registry` |
| CSI 对象面 | CSIDriver{attachRequired,storageCapacity,seLinuxMount,volumeLifecycleModes,fsGroupPolicy}；CSINode{drivers[].nodeID,topologyKeys,allocatable.count} |
| 快照三件套 | VolumeSnapshot/Content/Class = CRD（snapshot.storage.k8s.io/v1，GA v1.20）；readyToUse；deletionPolicy；is-default-class 注解 |
| 快照恢复 | `pvc.spec.dataSource: {kind: VolumeSnapshot, apiGroup: snapshot.storage.k8s.io}`；克隆换 `kind: PersistentVolumeClaim`（同 ns） |
| 扩容读表 | spec.resources.requests.storage → status.allocatedResources / allocatedResourceStatuses[storage] 五态 / capacity；quota 按 max(spec, allocated) 计 |
| 失败重试 | RecoverVolumeExpansionFailure（GA v1.34）：改小到 > status.capacity，resizer 重置 allocatedResources；quota 不占便宜 |
| 不停机改档 | PVC.spec.volumeAttributesClassName（GA v1.34；driver 需实现 ModifyVolume） |
| fsGroup 提速 | fsGroupChangePolicy: OnRootMismatch（GA v1.23）；CSI VOLUME_MOUNT_GROUP（GA v1.26） |
| SELinux 提速 | seLinuxChangePolicy=MountOption/Recursive（GA v1.36）；SELinuxMount v1.37 默认开（前提：CSIDriver.spec.seLinuxMount=true 或 in-tree iscsi/rbd/fc） |
| 僵尸 PVC 雷达 | PVC condition `Unused`（v1.37 Beta，reason NoPodsUsingPVC） |
| hostpath demo | `deploy/kubernetes-latest/deploy.sh` → 8 容器 StatefulSet；`examples/` 下 SC/PVC/App/snapshot/restore/cloning 全有 |

### 9.2 关键要点（背诵版）

1. K8s 存储=「**供给（PV/PVC/SC）、挂载（CSI attach/mount）、数据生命（reclaim/快照/扩容/克隆）**」三事；PV/PVC 是资源域↔需求域的 1:1 双向锁定，动态供给不过让 provisioner 替管理员填 PV。
2. 绑定只按**类相等 → 标签 → volumeMode → accessModes → 容量足则取最小**筛，认领后写 claimRef；`volumeName` 预绑绕过匹配但不绕过类/模式/尺寸校验；accessMode 是声明不是执行体——只有 `ReadWriteOncePod`（GA v1.29）真强制单 Pod。
3. Reclaim：Retain=手工四步且不自动再绑；Delete=后端真删；Recycle 已废弃——**v1.37 只见于 nfs/hostPath**。
4. 删除保护三段时间：最早的 in-use 保护（pv/pvc-protection）防「对象先于使用消失」；**v1.31+ 加的 backend 保护 finalizer**（`external-provisioner.../finalizer` 或 `kubernetes.io/pv-controller`）保「后端先于对象死」；**HonorPVReclaimPolicy（GA v1.33，v1.36 移除 gate）**让「先删 PV 再删 PVC」不再泄漏——v1.37 已默认生效，先删 Bound PV 现在一定真删盘。
5. CSIMigration（Stable v1.25）是**重定向**不是转换：老 YAML 照读、操作转发给 CSI；EBS/AzureDisk v1.27、GCE PD v1.28、cephfs/rbd v1.31 源码移除，azureFile/cinder/vSphere/Portworx 在 v1.37 全默认重定向——集群必须装对 CSI 驱动。
6. CSI 三分法：Identity/Controller/Node；挂载完整序=`CreateVolume`→PV Bound→`VolumeAttachment`+`ControllerPublishVolume`（attach，云 API 层）→`NodeStageVolume`（节点级一次）→`NodePublishVolume`（Pod 级 bind）——**attach 与 mount 的分离是云盘时代的根本设计**，也是 multi-attach、attach 超时、NodeVolumeLimits 这些问题的发源地。
7. sidecar 分工一句话：provisioner 守 PVC 造/删 PV（并管 backend finalizer）；attacher 守 VolumeAttachment；resizer 守 spec.resources 与 volumeAttributesClassName 的变化；snapshotter 守 **VolumeSnapshotContent**（VolumeSnapshot 归集群级 snapshot-controller）；registrar 守 kubelet 注册目录 + CSINode。
8. 快照对称 PV 族（GA v1.20）；恢复走 `dataSource`，**快照不是备份**（同存储域、跨 driver/zone 受限）；group snapshot（GA v1.36）用 label selector 圈多盘，让后端以一次原子动作产出一组同一时点的快照。
9. 扩容两级（Controller→Node）、能扩不能缩；`allocatedResources/allocatedResourceStatuses` 是状态机，quota 按 max 计——KEP-1790（GA v1.34）的最终救援语义是「改小到仍 > status.capacity 重试」，quota 从不吃亏。
10. WFFC=「先 Pod 后盘」：SC mode + 调度器 selected-node 注解 + provisioner 按拓扑供给；**Pod 直写 spec.nodeName 会绕过调度器让 WFFC 死等**（用 nodeSelector 代替）；local PV 只静态供给 + nodeAffinity 必填，节点坏则卷不可用——应用必须自承副本或重算能力。

### 9.3 参考链接

| 主题 | 链接 |
|------|------|
| Volumes（卷全谱、CSIMigration、in-tree 移除/迁移时间表、emptyDir/image/bindMountOptions 各字段） | https://kubernetes.io/docs/concepts/storage/volumes/ |
| Persistent Volumes（phase、保护、finalizer、回收五步、pre-bind、扩容、Unused condition、MutablePVNodeAffinity） | https://kubernetes.io/docs/concepts/storage/persistent-volumes/ |
| Storage Classes（逐字段、WFFC 支持矩阵、默认类/retroactive） | https://kubernetes.io/docs/concepts/storage/storage-classes/ |
| Volume Snapshots（CRD 分工、源保护、topology、源模式注解） | https://kubernetes.io/docs/concepts/storage/volume-snapshots/ |
| Volume Snapshot Classes（deletionPolicy、默认类唯一性） | https://kubernetes.io/docs/concepts/storage/volume-snapshot-classes/ |
| Ephemeral Volumes（CSI ephemeral / generic ephemeral GA v1.23） | https://kubernetes.io/docs/concepts/storage/ephemeral-volumes/ |
| Storage Capacity（CSIStorageCapacity、就绪条件、限制） | https://kubernetes.io/docs/concepts/storage/storage-capacity/ |
| VolumeAttributesClass（GA v1.34、driverName/parameters） | https://kubernetes.io/docs/concepts/storage/volume-attributes-classes/ |
| security-context 任务页（fsGroupChangePolicy、VOLUME_MOUNT_GROUP、SELinux 三门控、SELinuxWarningController） | https://kubernetes.io/docs/tasks/configure-pod-container/security-context/ |
| node-driver-registrar 官方文档（注册机制、CSINode） | https://kubernetes-csi.github.io/docs/node-driver-registrar.html |
| csi-driver-host-path（实验本体：部署、示例、各 driver 能力） | https://github.com/kubernetes-csi/csi-driver-host-path |
| external-snapshotter（快照三件套 CRD、snapshot-controller、finalizer 源码） | https://github.com/kubernetes-csi/external-snapshotter |
| KEP-1790 RecoverVolumeExpansionFailure（五态、infeasible 错误码、quota 语义） | https://github.com/kubernetes/enhancements/tree/master/keps/sig-storage/1790-recover-resize-failure |
| KEP-2644 HonorPVReclaimPolicy（泄漏原理与两个 finalizer） | https://github.com/kubernetes/enhancements/tree/master/keps/sig-storage/2644-honor-pv-reclaim-policy |
| KEP-3476 VolumeGroupSnapshot（对象结构、里程碑） | https://github.com/kubernetes/enhancements/tree/master/keps/sig-storage/3476-volume-group-snapshot |
| KEP-3751 VolumeAttributesClass（ModifyVolume、字段面） | https://github.com/kubernetes/enhancements/tree/master/keps/sig-storage/3751-volume-attributes-class |
| KEP-1710 SELinux volume relabeling（三门控机制源头） | https://kep.k8s.io/1710 |
| feature gate 版本注释（SELinux 三件套/RecoverVolumeExpansionFailure/VAC/StorageCapacityScoring） | https://github.com/kubernetes/kubernetes/blob/master/pkg/features/kube_features.go |
