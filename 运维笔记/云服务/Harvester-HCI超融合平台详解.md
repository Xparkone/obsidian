# Harvester：HCI 超融合平台详解

> 文档版本：v1.0 | 更新日期：2026-09-29
> 说明：具体版本号、硬件要求和功能边界以 [官方文档](https://docs.harvesterhci.io/) 对应版本为准。

---

## 一、Harvester 是什么

**一句话定义：Harvester 是 SUSE / Rancher 出品的开源 HCI（超融合基础设施）平台，把 KVM 虚拟机当作 Kubernetes 资源来管理。**

传统虚拟化平台（VMware、Proxmox）是"宿主机上跑 VM"；Harvester 的思路是"K8s 集群上跑 VM"——每个虚拟机本质上是 K8s 里的一个 CRD 对象，用 `kubectl` 和 YAML 就能创建、迁移、删除虚拟机。

| 基本信息 | 说明 |
|------|------|
| **出品方** | Rancher Labs（后并入 SUSE） |
| **许可证** | Apache License 2.0，完全开源 |
| **首次 GA** | v1.0 于 2021 年底发布，此后保持小版本持续演进 |
| **安装形态** | 裸金属 ISO 直接安装（自带操作系统，无需先装 Linux） |
| **上游项目** | [github.com/harvester/harvester](https://github.com/harvester/harvester) |
| **对标产品** | VMware vSphere、Proxmox VE、Nutanix、OpenStack |

---

## 二、HCI 超融合是什么

HCI（Hyper-Converged Infrastructure，超融合基础设施）把以前分开的三样东西**融合进同一组通用 x86 服务器**：

```
传统三层架构                          超融合架构
┌──────────────┐                   ┌─────────────┐
│  计算服务器    │                   │ 通用 x86 节点 │──┐
└──────┬───────┘                   │ 计算+存储    │  │
       │ FC/iSCSI                  └─────────────┘  │ 集群内
┌──────▼───────┐                   ┌─────────────┐  │ 互联储存副本
│  SAN 存储阵列  │                   │ 通用 x86 节点 │──┤
└──────────────┘                   │ 计算+存储    │  │
┌──────────────┐                   └─────────────┘  │
│  光纤交换机    │                   ┌─────────────┐  │
└──────────────┘                   │ 通用 x86 节点 │──┘
                                   │ 计算+存储    │
每个节点既出算力，也出磁盘，           └─────────────┘
用软件把各节点的盘组成一个分布式存储池（Harvester 用 Longhorn）。
```

好处：扩容就是加节点（算力存储一起扩）、没有单独存储阵列的采购和运维成本、故障域简单。代价：网络和磁盘 I/O 要求更高，节点数太少时性价比不明显。

---

## 三、Harvester 架构

Harvester 节点 = 自带操作系统 + 内嵌 K8s + 虚拟化组件 + 分布式存储，开箱即用：

```
┌─────────────────── Harvester 节点（裸金属服务器）───────────────────┐
│                                                                    │
│   你的虚拟机             VM 本质上是一个 K8s CR 对象                  │
│   ┌────────┐ ┌────────┐        （apiVersion: kubevirt.io/v1）       │
│   │  VM 1   │ │  VM 2  │                                            │
│   └───┬────┘ └───┬────┘                                            │
│       │ virt-launcher Pod（KubeVirt 为每个 VM 拉起）                 │
│  ┌────▼───────────▼─────────────────────────────────────────┐      │
│  │  KubeVirt：在 K8s 中管理 KVM 虚拟机（VM CRD + virt-* 组件）│      │
│  │  Longhorn：把各节点本地盘聚合成分布式块存储                  │      │
│  │  Multus + Whereabouts：多网卡 / VLAN 网络                 │      │
│  ├───────────────────────────────────────────────────────────┤     │
│  │  内嵌 Kubernetes（早期版本 K3s，新版本为 RKE2）+ Dashboard   │      │
│  ├───────────────────────────────────────────────────────────┤     │
│  │  自带操作系统（SUSE SLE Micro 系，Elemental 工具链构建）      │     │
│  └───────────────────────────────────────────────────────────┘     │
│                          │                                         │
│                    KVM / 硬件虚拟化                                  │
└──────────────────────────┼─────────────────────────────────────────┘
                           ▼
                    物理 CPU / 内存 / 磁盘 / 网卡
```

多个节点组成一个集群：管理面有一个 **VIP**（虚拟 IP），任一节点的 UI/API 都可通过 VIP 访问；VM 数据通过 Longhorn 在节点间保留多副本，节点故障后 VM 可在其他节点重新拉起。

### 核心组件职责

| 组件 | 作用 | 备注 |
|------|------|------|
| **KubeVirt** | 把 VM 定义为 K8s CRD，用控制器管理 VM 生命周期 | 详见“用 YAML 创建 VM”一节 |
| **Longhorn** | 分布式块存储：VM 磁盘跨节点多副本，支持快照/备份 | 即 [[K3s-部署指南]] 场景常用的那个 Longhorn |
| **Multus / Whereabouts** | CNI 插件，给 VM 提供 VLAN、多网卡等 L2 网络能力 | 区别于容器默认网络 |
| **Harvester Dashboard** | 内置 Web 管理界面（基于 Rancher UI 框架） | 日常操作主要入口 |
| **Elemental / cOS** | 不可变操作系统层，节点像容器镜像一样整体升级 | 升级 ISO 引导切换 |
| **内置 K8s** | 集群底座：早期版本为 K3s，新版本为 RKE2 | 不面向用户跑业务负载 |

---

## 四、核心功能

### 4.1 虚拟机生命周期

- 创建 / 启动 / 停止 / 重启 / 暂停 / 删除，UI 和 `kubectl` 均可。
- **在线热迁移（Live Migration）**：把运行中的 VM 迁移到其他节点，维护宿主机时业务不中断。
- **节点维护模式**：节点进维护前自动疏散 VM。
- **模板（Template）**：把配好的 VM 存成模板，批量克隆。

### 4.2 镜像管理

- 支持 QCOW2 / RAW / ISO 镜像：本地文件上传，或从 HTTP(S) URL 直接导入。
- 镜像进入集群后端存储（默认 Longhorn）后可被多个 VM 复用。

### 4.3 网络

| 类型 | 用途 |
|------|------|
| **Management 网络** | 节点安装时自带的集群管理网络，VM 也可挂（NAT 出站） |
| **VLAN 网络（L2VlanNetwork）** | 把 VM 直接桥接到上游物理网络 / VLAN，获得真实 IP |
| **负载均衡** | Harvester 内置 LB 及面向下游集群的 Cloud Provider 模式 |
| **IP 池（IPPool）** | 给 VM / LB 分配固定网段的地址 |

### 4.4 存储、快照与备份

- VM 磁盘默认落在 Longhorn，可配置副本数（生产建议 ≥ 2，需节点数 ≥ 3）。
- 支持卷快照；**备份目标**可以是外部 NFS 或 S3 兼容对象存储，用于异地/异集群恢复。
- 细分成 **VM Backup**（整机）与 **Volume 快照** 两个层面。

### 4.5 高级能力

- **PCIe / GPU 直通**：把宿主机 PCI 设备直接分配给 VM（适用于 GPU 计算、专用网卡等场景）。
- **cloud-init / NoCloud**：创建 VM 时注入用户数据（初始化密码、SSH key、网络配置）。
- **热插拔**：部分资源（磁盘、网卡）支持运行中添加，CPU/内存热插拔能力随版本演进，需查当版文档。

---

## 五、管理面：三种用法

### 5.1 Web UI（最常用）

安装完成后浏览器访问 VIP（默认 `https://<vip>`），首次登录设置 admin 密码。UI 覆盖 VM、镜像、网络、存储、备份、节点、设置的日常操作。

### 5.2 kubectl + YAML（云原生方式）

从 UI 可下载 kubeconfig，然后像管 K8s 资源一样管 VM：

```yaml
# my-vm.yaml：声明一台 Ubuntu 虚拟机
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: my-vm
  namespace: default
  labels:
    harvesterhci.io/creator: harvester
spec:
  running: true
  template:
    metadata:
      labels:
        harvesterhci.io/vmName: my-vm
    spec:
      domain:
        cpu:
          cores: 2
        memory:
          guest: 4Gi
        resources:
          limits:
            cpu: "2"
            memory: 4Gi
        devices:
          disks:
            - name: rootdisk
              disk:
                bus: virtio
          interfaces:
            - name: default
              bridge: {}
      networks:
        - name: default
          pod: {}          # 用集群管理网络
      volumes:
        - name: rootdisk
          persistentVolumeClaim:
            claimName: my-vm-rootdisk
```

```bash
kubectl apply -f my-vm.yaml
kubectl get vm                       # 查看虚拟机
kubectl get vmi                      # 查看运行实例
virtctl console my-vm                # 进入控制台（需 virtctl 插件）
```

> KubeVirt 的 VM 资源模型细节：Kind 原理参照 [[KVM-详解与命令速查]]（底层就是 KVM/QEMU）。

### 5.3 Terraform Provider

存在官方维护的 `harvester/harvester` Terraform Provider，可把 VM、网络、镜像纳入 IaC 管理，思路见 [[Terraform-入门到实战]]。

---

## 六、与 Rancher 的集成

这是 Harvester 区别于一般虚拟化平台的关键卖点：

```
Rancher Manager
   │  启用 Virtualization Management
   ▼
纳管 Harvester 集群 ──┬──► 统一管 VM（在 Rancher UI 里操作 Harvester 的 VM）
                      └──► 在 VM 上自动部署下游 RKE2 / K3s 业务集群
                                  │
                                  ▼
                    Harvester 自动为下游集群创建 VM、分配网络，
                    并提供 Harvester CSI Driver / Cloud Provider
```

即“一套底座”同时交付**虚拟机**和**Kubernetes 集群**两种资源，VM 和容器在同一团队的同一条流水线里管理。

---

## 七、安装与硬件要求

### 安装方式

| 方式 | 场景 |
|------|------|
| **ISO 裸机安装**（官方镜像 U 盘引导） | 标准方式，全部节点逐一安装，首节点选 Create Harvester Cluster，其余选 Join |
| **PXE 网络安装** | 批量装机，配合 iPXE 脚本自动应答 |
| **嵌套虚拟化**（VMware/KVM 里装 Harvester） | 仅适合评估学习，需开启 CPU 虚拟化透传；性能受限，勿用于生产 |

### 硬件要求（量级参考，以当版官方文档为准）

| 场景 | CPU | 内存 | 磁盘 | 网络 |
|------|-----|------|------|------|
| 评估 | ≥ 8 核 | ≥ 32 GB | ≥ 250 GB SSD | 1 GbE 即可 |
| 生产 | ≥ 16 核 | ≥ 64 GB | ≥ 500 GB SSD/NVMe（系统盘与数据盘分开更好） | 建议 10 GbE，管理/存储流量可分离 |

其他硬性前提：

- x86_64，BIOS 开启 Intel VT-x / AMD-V；嵌套环境需 vHV 透传。
- 生产集群 **≥ 3 节点**（Longhorn 副本 + etcd 仲裁需要）。
- 节点间二层可达，管理 VIP 地址需与节点同网段且未被占用。
- 时间同步（NTP）正常；上游 DNS 可解析。

> 与 [[私有云部署指南]] 中“最小 3 台”的经验一致：单节点 Harvester 能装但没有副本与迁移能力。

---

## 八、对比与选型

| 方案 | 本质 | 学习成本 | 适合场景 | 短板 |
|------|------|:--:|------|------|
| **Harvester** | K8s + KubeVirt 的开箱 HCI | 中（要懂 K8s 更好） | K8s/Rancher 团队、VM+容器混合、边缘 | 生态较年轻、企业特性少于 vSphere |
| **Proxmox VE** | Debian + KVM/LXC 虚拟化管理 | 低 | 中小团队快速上手、单机也可用 | 非 K8s 原生、大规模编排弱 |
| **VMware vSphere** | 商业虚拟化标准 | 中 | 大企业、重 SLA、要成熟生态 | 授权贵、绑定厂商 |
| **OpenStack** | 开源全栈 IaaS | 高 | 大规模多租户私有云 | 组件多、部署升级复杂 |
| **Nutanix** | 商业 HCI 一体机 | 中 | 预算充足的超融合需求 | 闭源、硬件绑定 |
| **自建 K8s + KubeVirt** | 自己组装 | 高 | 已有成熟 K8s 平台和平台团队 | 组装与运维成本自担 |

### 典型使用场景

| 场景 | 为什么选 Harvester |
|------|------|
| **VMware 替代（成本敏感）** | 开源无按 CPU/核心授权费；中小规模虚拟化池可直接迁入，支持主流 VM 镜像格式 |
| **VM 与容器混跑** | 老系统（Windows Server、商业软件、数据库）继续跑 VM，新应用上 K8s，同一底座同一套 kubectl/CI 流程 |
| **私有云自助交付 VM** | 用 YAML / Terraform / API 声明式开 VM，纳入 GitOps，审计与回滚天然具备 |
| **边缘机房 / 分支站点** | ISO 一体化安装、组件少、不可变 OS，适合无人值守的小机房统一纳管（SUSE Edge 场景） |
| **GPU / AI 算力平台** | PCIe/GPU 直通给 VM 跑推理训练，同集群又能跑容器化数据处理任务 |
| **开发测试 / CI 环境** | API 驱动批量创建销毁 VM，配合模板+cloud-init 快速出干净环境 |
| **Rancher 用户扩展** | 已用 Rancher 管容器集群，加上 Harvester 后 VM 与下游 K8s 集群在一个界面统一管 |

**选 Harvester 的典型信号**：团队已在用 K8s/Rancher；要同时交付 VM 和容器集群；想要开源、无按 CPU 授权的 VMware 替代；边缘机房需要轻量一体化底座。

**不太合适的信号**：只有 1~2 台物理机、想用最少命令跑起来（选 Proxmox）；需要 vSphere 的 DRS/vSAN 企业特性；没有任何 K8s 概念且短期内不打算学。

---

## 九、落地检查清单与常见排障方向

### 部署前只读检查

- [ ] 确认 CPU 支持并开启虚拟化（`lscpu | grep Virtualization` 在引导介质环境或 BIOS 核对）。
- [ ] 规划管理网段、VIP、NTP、DNS、（可选）VLAN 与上游交换机 trunk 配置。
- [ ] 规划备份目标（NFS / S3 桶名、权限、网络可达性）。
- [ ] 记录节点数 ≥ 3、磁盘清洁度（旧分区表可能干扰安装）。

### 常见问题方向

| 现象 | 优先怀疑 |
|------|----------|
| VIP / UI 打不开 | VIP 与节点网段、上游防火墙 443、证书有效期 |
| 节点 NotReady | NTP 漂移、磁盘压力、管理网络 MTU |
| VM 卡在 Starting | 镜像未就绪、PVC 未绑定、virt-launcher Pod 事件 |
| 迁移失败 | Longhorn 卷健康、节点资源余量、selinux/内核限制 |
| 存储降级 | Longhorn UI 看副本副本数与节点磁盘水位 |
| 备份失败 | 备份目标连通性、S3 凭证与 region、NFS 挂载权限 |

排障入口（只读优先）：UI 的 Support Bundle → 节点 `kubectl get pods -A`、`kubectl describe vm <name>`、Longhorn UI、节点系统日志。K8s 通用排障思路见 [[Kubernetes-从入门到生产实践：组件资源与常用操作指南]]。

---

## 十、延伸阅读

### 本笔记库

- [[私有云部署指南]] — Harvester 在整体私有云选型中的位置
- [[KVM-详解与命令速查]] — Harvester 底层虚拟化原理
- [[K3s-部署指南]] — 早期 Harvester 内嵌的轻量 K8s 形态
- [[Kubernetes-从入门到生产实践：组件资源与常用操作指南]] — kubectl / CRD 通用操作
- [[Helm-3-从入门到生产实践]] — 下游集群应用交付
- [[Terraform-入门到实战]] — 用 IaC 管理 Harvester 资源

### 官方与社区

- 官方文档：https://docs.harvesterhci.io/
- GitHub：https://github.com/harvester/harvester
- KubeVirt：https://kubevirt.io/
- Longhorn：https://longhorn.io/

---

*文末提示：本文档基于公开资料整理，未在真实集群逐条验证；落实前请按目标版本官方文档复核功能与参数。*
