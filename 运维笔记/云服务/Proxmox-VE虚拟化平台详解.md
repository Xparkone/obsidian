# Proxmox VE：虚拟化平台详解

> 文档版本：v1.0 | 更新日期：2026-09-29
> 说明：具体版本特性与硬件要求以 [官方文档](https://pve.proxmox.com/pve-docs/) 对应版本为准。

---

## 一、Proxmox VE 是什么

**一句话定义：Proxmox VE（Proxmox Virtual Environment，简称 PVE）是一个基于 Debian 的开源虚拟化管理平台，用 Web 界面统一管理 KVM 虚拟机和 LXC 容器。**

如果说 [[Harvester-HCI超融合平台详解]] 是"把 VM 变成 K8s 资源"，那 Proxmox 就是传统虚拟化路线里最容易上手的开源选手：**单机就能装、装完就有 UI、不依赖任何 K8s 概念**。

| 基本信息 | 说明 |
|------|------|
| **出品方** | Proxmox Server Solutions GmbH（奥地利） |
| **许可证** | AGPLv3 完全开源；付费订阅只买"企业仓库 + 官方支持"，不锁功能 |
| **首次发布** | 2008 年，持续维护至今（7.x 基于 Debian 11，8.x 基于 Debian 12，9.x 基于 Debian 13） |
| **虚拟化** | KVM/QEMU（全虚拟化 VM）+ LXC（系统容器） |
| **管理入口** | Web UI（`https://<ip>:8006`）+ REST API + CLI |
| **配套产品** | Proxmox Backup Server（PBS，备份）、Proxmox Mail Gateway |
| **对标** | VMware vSphere（ESXi + vCenter）、Hyper-V、oVirt、[[Harvester-HCI超融合平台详解]] |

---

## 二、架构

```
┌─────────────────────── PVE 节点（物理机）───────────────────────┐
│                                                              │
│   虚拟机(VM)                 容器(CT)                           │
│   ┌──────┐ ┌──────┐         ┌──────┐ ┌──────┐                │
│   │Win/  │ │Linux │         │Debian│ │Ubuntu│ ← 共享宿主内核   │
│   │Linux │ │ BSD  │  任意OS │ LXC  │ │ LXC  │   只能 Linux    │
│   └──┬───┘ └──┬───┘         └──┬───┘ └──┬───┘                │
│      │ QEMU/KVM                │ LXC（namespaces/cgroups）     │
│  ┌───┴──────────────────────────┴──────────────────────┐      │
│  │  pvedaemon / pveproxy（Web UI:8006、REST API）         │      │
│  │  pve-cluster（集群）、pve-firewall、SDN、HA Manager    │      │
│  ├───────────────────────────────────────────────────────┤     │
│  │  存储：local-lvm / ZFS / NFS / iSCSI / Ceph(RBD)       │      │
│  ├───────────────────────────────────────────────────────┤     │
│  │  Debian Linux（PVE 自带定制内核）                       │      │
│  └───────────────────────────────────────────────────────┘     │
│                          │                                     │
│                    KVM / 硬件虚拟化                              │
└──────────────────────────┼─────────────────────────────────────┘
                           ▼
                    物理 CPU / 内存 / 磁盘 / 网卡
```

集群模式（可选，非必需）：

```
节点1 ──────────┐
节点2 ───Corosync 心跳─── pmxcfs 同步集群配置（/etc/pve）
节点3 ──────────┘        一起构成仲裁（Quorum），支持 HA + 在线迁移

两节点集群可挂 QDevice（第三方小设备投票）解决分裂仲裁。
```

| 组件 | 作用 |
|------|------|
| **QEMU/KVM** | 全虚拟化，跑任意操作系统的 VM（原理见 [[KVM-详解与命令速查]]） |
| **LXC** | 系统容器，跑 Linux，密度高、开销小、秒级启动 |
| **pmxcfs + Corosync** | 集群配置同步与心跳仲裁 |
| **pveproxy/pvedaemon** | Web UI 与 API 服务 |
| **pve-firewall / SDN** | 集群级防火墙、虚拟网络（VLAN/VXLAN/EVPN） |
| **HA Manager** | 节点故障时自动在其他节点重启 VM/CT |

---

## 三、VM（KVM）还是 CT（LXC）？

| 维度 | VM（KVM 虚拟机） | CT（LXC 容器） |
|------|------------------|----------------|
| 操作系统 | 任意（Windows、BSD…） | 仅 Linux 发行版 |
| 内核 | 独立内核 | 共享宿主内核 |
| 开销 | 较高（独占内存） | 极低，接近裸机 |
| 隔离强度 | 强（硬件虚拟化边界） | 较弱（可能有特权需求） |
| 适用 | Windows、需要独立内核、强隔离 | 跑 Linux 服务（Nginx、数据库、工具箱），追求密度 |

经验：**能 CT 就 CT**（省资源），涉及 Windows、特殊内核模块或强隔离需求才上 VM。

---

## 四、存储体系

PVE 把存储抽象成"存储池（Storage）"，按位置分两类：

| 类型 | 选项 | 说明 |
|------|------|------|
| **本地存储** | Directory / LVM / LVM-thin / **ZFS** | ZFS 是一等公民：装系统时可选 ZFS on root，自带快照、压缩、校验和 |
| **共享存储** | NFS / iSCSI / **Ceph RBD** / CIFS | 在线迁移和 HA 的前提；Ceph 可直接在 UI 里一体化部署（≥3 节点、建议独立高速网） |
| **备份目标** | **PBS** / NFS / Directory | Proxmox Backup Server：去重、增量、校验任务、客户端加密 |

要点提示：

- ZFS 默认吃内存做 ARC 缓存，生产建议 ECC 内存并适当限制 ARC 上限。
- 本地目录（Directory）存 qcow2 才能用快照；raw 格式不支持快照（ZFS/LVM-thin 底层另说）。
- **备份务必接 PBS 或异地目标**，VM 快照不是备份。

---

## 五、核心功能

- **模板与克隆**：完整克隆 / 链接克隆（qcow2/ZFS）；模板一键批量出机。
- **快照**：磁盘快照 + 内存状态快照（qcow2），秒级回滚。
- **备份**：`vzdump` 支持 stop/suspend/snapshot 三种模式；接 PBS 后增量 + 去重。
- **在线迁移与 HA**：共享存储下 VM 不停机搬家；配 HA 后节点宕机自动接管。
- **存储复制（pvesr）**：无共享存储时，ZFS 增量把卷定时复制到对端节点做"准 HA"。
- **SDN 与防火墙**：VLAN / VXLAN / EVPN 虚拟网络；数据中心→主机→VM 三级防火墙规则。
- **cloud-init**：Ubuntu/Debian cloud 镜像开箱即用，自动注入用户、SSH key、网络配置。
- **PCI(e)/GPU 直通**：开 IOMMU 后把显卡/网卡直挂 VM（玩 AI、软路由必备）。
- **VMware 导入**：较新版本内置从 ESXi 拉 VM 的导入向导（具体版本以官方文档为准）。
- **权限与审计**：PAM/PVE realm、LDAP/AD 集成、双因素认证、细粒度角色。

---

## 六、管理面：四种用法

### 6.1 Web UI

日常操作主入口：`https://<节点IP>:8006`。VM/CT、存储、网络、备份、集群、权限全在里面，**不碰命令行也能用完整功能**。

### 6.2 命令行速查

```bash
# 虚拟机（VM）
qm list                    # 列出所有 VM
qm start 100               # 启动 VMID=100
qm shutdown 100            # 优雅关机
qm snapshot 100 before-up  # 打快照
qm rollback 100 before-up  # 回滚
qm clone 100 101 --name vm-clone   # 克隆

# 容器（CT）
pct list                   # 列出所有 LXC
pct create 200 local:vztmpl/debian-12-standard_12.7_amd64.tar.zst \
    --hostname ct-demo --memory 1024 --net0 name=eth0,bridge=vmbr0,ip=dhcp
pct enter 200              # 进容器

# 存储与集群
pvesm status               # 存储池状态
pvesm free local-lvm
pvecm status               # 集群/仲裁状态
pve-ha-manager status      # HA 状态

# 通用 API 外壳（等价于 REST）
pvesh get /cluster/resources --type vm
```

### 6.3 REST API

每个 UI 操作都对应 REST 端点，自带 API Viewer，适合做自动化和与自研系统对接（思路对照 [[Skill-Tool-MCP-概念关系与使用指南]] 中 Tool 层的设计）。

### 6.4 Terraform / Ansible

- 社区主流 Provider：`bpg/proxmox`（老的 Telmate Provider 多见存量项目），用法见 [[Terraform-入门到实战]]。
- Ansible 有 `community.general.proxmox_*` 系列模块，见 [[ansible-usage-guide]]。

---

## 七、安装与硬件要求

### 7.1 安装方式

| 方式 | 说明 |
|------|------|
| **ISO 直装（推荐）** | 官网下载 ISO → U 盘引导 → 图形化几步装完，装完即有 UI；根盘可选 ext4 / XFS / ZFS |
| **Debian 上加装** | 已有 Debian 时添加 PVE 软件源安装（适合先在虚拟机上练手） |
| **嵌套虚拟化** | 在 VMware/Parallels/KVM 里装来评估，需开启 CPU 虚拟化透传 |

### 7.2 硬件要求（量级参考）

| 组件 | 最低（评估） | 生产建议 |
|------|------------|----------|
| CPU | x86_64 + VT-x/AMD-V | 8 核以上，核越多越好 |
| 内存 | 2 GB（能装） | 32 GB+，用 ZFS 建议 ECC |
| 系统盘 | 10 GB | 128 GB SSD 起步 |
| 数据盘 | — | 按容量规划，SSD/NVMe |
| 网卡 | 1 张 | 2 张起（管理/业务或 Ceph 分离），Ceph 建议 10 GbE |

**与 [[Harvester-HCI超融合平台详解]] 的关键差异：Proxmox 单机就是完整形态**，集群是加分项；Harvester 生产必须 ≥3 节点（那是 HCI 架构决定的）。

### 7.3 装完第一件事：换免费源

未购买订阅时，企业源会报 401，应将 `pve-enterprise` 仓库换为 `pve-no-subscription`（8.x 用 `.list` 文件，9.x 起为 deb822 `.sources` 格式，按官方 wiki 当版指引操作），并知晓 UI 登录时的一次性订阅提示弹窗属正常、不影响功能。

```bash
# PVE 8.x 示例（9.x 请按官方 wiki 的 .sources 格式操作）
sed -i 's/^deb/#deb/' /etc/apt/sources.list.d/pve-enterprise.list
echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" \
  > /etc/apt/sources.list.d/pve-no-subscription.list
apt update && apt full-upgrade -y
```

---

## 八、对比与选型

| 方案 | 一句话 | 选它的信号 |
|------|--------|-----------|
| **Proxmox VE** | 开源虚拟化里最好上手 | 单机可用、要 VM+CT 两种形态、无 K8s 诉求 |
| [[Harvester-HCI超融合平台详解]] | K8s 原生 HCI | 团队懂 K8s/Rancher、要 VM+容器混跑、API/GitOps 交付 |
| **VMware vSphere** | 商业标准 | 大企业预算足、重 SLA 与成熟生态 |
| **Hyper-V** | Windows 生态自带 | 全 Windows 环境、Windows Server 授权赠送 |
| **OpenStack/oVirt** | 全栈/企业开源 | 大规模多租户云（OpenStack）、Red Hat 系（oVirt） |

### 典型使用场景

| 场景 | 为什么选 PVE |
|------|-------------|
| **家庭实验室 / Homelab** | 免费、硬件要求低、软路由/NAS/影音一台机全收 |
| **中小企业服务器整合** | 几台物理机顶替一堆老旧服务器，HA + PBS 备份低预算闭环 |
| **VMware 低成本替代（中小规模）** | 无订阅强制费，ESXi 导入向导降低迁移成本 |
| **私有云学习第一站** | 概念直通（VM/存储/网络/HA），是理解 [[私有云部署指南]] 的最短路径 |
| **边缘单机/双节点** | 单机完整可用，双节点 + QDevice 也能做 HA |
| **开发测试环境** | 模板 + cloud-init 分钟级出机，PBS 快照兜底 |

### 不太合适的信号

- 一切都要走 Kubernetes/GitOps，VM 想当成 CR 管 → 用 Harvester。
- 需要 vSphere 独有的企业特性（深度 DRS、FT、庞大生态绑定）→ 留在 VMware。
- 纯公有云式多租户编排（计费、VPC 自服务）→ Proxmox 是虚拟化平台不是全栈云管，应选 OpenStack 或自研云管 + PVE API。

### 快速决策

```
要在物理机上跑虚拟机吗？
│
├── 只有 1~2 台机器、想最快上手 ──────────────► Proxmox VE（单机即完整形态）
│
├── ≥3 台且团队懂 K8s，要 VM+容器统一编排 ──────► Harvester（K8s 原生 HCI）
│
├── 大规模多租户、计费/VPC 自服务 ──────────────► OpenStack（全栈云管）
│
└── 预算充足、重 SLA 的核心生产 ───────────────► vSphere（商业标准）

已经在用 PVE 了，要不要上 K8s？
└── 不必二选一：PVE 专职跑 VM，K8s 单独建集群跑容器很常见；
   只有当"VM 也要用 kubectl/GitOps 管"才值得迁 Harvester。
```

---

## 九、落地检查清单与常见排障方向

### 部署前只读检查

- [ ] CPU 虚拟化已开启（`lscpu | grep Virtualization`），要用直通再确认 IOMMU。
- [ ] 规划管理网段、主机名（**PVE 靠主机名解析通信，装前定好**）、NTP、DNS。
- [ ] 规划存储：系统盘格式（ZFS on root？）、数据盘归属、备份目标（PBS？）。
- [ ] 集群要 3 节点，或 2 节点 + QDevice；节点间延迟低、时钟同步。

### 常见问题方向

| 现象 | 优先怀疑 |
|------|----------|
| 集群只读/无法改配置 | Quorum 丢失（存活节点未过半），`pvecm status` 确认 |
| VM 迁移失败 | 目标节点存储是否同名同类型、本地盘绑定、网络带宽 |
| CT 起不来 | 特权/非特权容器 flag、镜像损坏、存储剩余 |
| 快照失败 | qcow2/raw 格式、Dir 存储限制、LVM 剩余空间 |
| ZFS 性能/内存高 | ARC 占用、recordsize/压缩设置、磁盘健康 `zpool status` |
| Web UI 打不开 | `pveproxy` 状态、8006 端口与防火墙、证书 |
| apt 401/更新失败 | 企业源未换 no-subscription（见 7.3） |

底层排查与 Linux 通用方法一致：参照 [[Ubuntu-日志查看详解]] 与 [[top-命令指标详解与性能排障指南]]。

---

## 十、延伸阅读

### 本笔记库

- [[私有云部署指南]] — Proxmox 在整体私有云选型中的位置（第三章入门推荐）
- [[Harvester-HCI超融合平台详解]] — K8s 原生路线对照
- [[KVM-详解与命令速查]] — 底层虚拟化原理
- [[Ubuntu-日志查看详解]] — Debian 系日志排查通用方法
- [[Terraform-入门到实战]] / [[ansible-usage-guide]] — 用 IaC 管理 PVE

### 官方与社区

- 官方文档/管理手册：https://pve.proxmox.com/pve-docs/
- 官方 wiki（no-subscription 源、直通、集群等）：https://pve.proxmox.com/wiki/
- Proxmox Backup Server：https://www.proxmox.com/en/proxmox-backup-server

---

*文末提示：本文档基于公开资料整理，未在真实环境逐条验证；命令与仓库配置请以目标版本官方文档为准。*
