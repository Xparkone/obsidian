# Multipass 使用指南

> 最后更新：2026-07-15 · 当前版本：1.16.3

---

## 一、什么是 Multipass

Multipass 是 **Canonical 官方** 推出的轻量级 VM 管理器，跨平台（Linux / macOS / Windows）。一句话概括：**一条命令启动 Ubuntu 虚拟机，像用云主机一样在本地干活。**

### 核心特点

| 特点 | 说明 |
|------|------|
| **一条命令启动** | `multipass launch` 几秒内出一台 Ubuntu VM |
| **原生 Hypervisor** | Linux 用 KVM，macOS 用 QEMU，Windows 用 Hyper-V，也可切换 VirtualBox |
| **cloud-init 支持** | 像 AWS/Azure 一样用 cloud-init 初始化实例，模拟云端部署 |
| **镜像管理** | 自动拉取 Ubuntu 镜像，保持最新，还有 Debian、Fedora 等可选 |
| **文件共享** | 宿主机目录直接 mount 进 VM |
| **快照/克隆** | 支持 snapshot 和 clone，实验不怕搞坏 |
| **轻量** | 默认 1 CPU + 1G RAM + 5G 磁盘，按需调整 |

### 典型使用场景

- **学习 Linux/Ubuntu** — 在 Mac/Windows 上快速获得 Ubuntu 命令行环境
- **本地开发环境** — 隔离的开发环境，不污染宿主机
- **云部署预演** — 用 cloud-init 模拟云上部署流程
- **K8s/Docker 实验** — 快速起多台 VM 组集群
- **安全沙箱** — 测试脚本、软件，不影响宿主机

---

## 二、安装

### macOS（你当前的环境）

```bash
# 方式一：Homebrew（推荐）
brew install --cask multipass

# 方式二：手动下载安装包
# https://github.com/canonical/multipass/releases
```

### Linux

```bash
sudo snap install multipass
```

### Windows

```bash
# 下载安装包
# https://github.com/canonical/multipass/releases
# 需要启用 Hyper-V（Windows Pro/Enterprise）或安装 VirtualBox
```

---

## 三、核心概念

| 概念 | 说明 |
|------|------|
| **Instance** | 一台 Ubuntu VM，有唯一名称和 IP |
| **Image** | 预制的 Ubuntu 镜像，如 `22.04`、`24.04`、`lts` |
| **Primary Instance** | 名为 `primary` 的特殊实例，自动挂载宿主机 Home 目录 |
| **Snapshot** | 实例快照，可恢复 |
| **Blueprint** | （已废弃）预装特定软件的实例模板，如 Docker、Jellyfin |

---

## 四、常用命令速查

### 4.1 镜像管理

```bash
# 查看可用镜像
multipass find

# 输出示例：
# Image    Aliases           Version    Description
# 22.04    jammy             20260705   Ubuntu 22.04 LTS
# 24.04    noble             20260705   Ubuntu 24.04 LTS
# 26.04    resolute,lts      20260713   Ubuntu 26.04 LTS
```

### 4.2 实例生命周期

```bash
# 启动默认 LTS 实例（随机名称）
multipass launch

# 启动指定版本 + 自定义名称
multipass launch 24.04 --name dev-vm

# 启动指定资源配置
multipass launch lts --name k8s-node \
  --cpus 2 --memory 4G --disk 20G

# 查看所有实例
multipass list

# 查看实例详情
multipass info dev-vm

# 停止/启动/重启
multipass stop dev-vm
yuyu dev-vm
multipass restart dev-vm

# 暂停/恢复（类似休眠，内存状态保留）
multipass suspend dev-vm
multipass start dev-vm    # 恢复

# 删除实例
multipass delete dev-vm   # 标记删除，可恢复
multipass recover dev-vm  # 恢复已删除的实例
multipass purge           # 彻底清除所有已删除实例
```

### 4.3 进入实例

```bash
# 打开 shell（最常用）
multipass shell dev-vm

# 在实例中执行单条命令
multipass exec dev-vm -- lsb_release -a
multipass exec dev-vm -- sudo apt update
```

### 4.4 文件操作

```bash
# 宿主机 → 实例
multipass transfer myfile.txt dev-vm:/home/ubuntu/

# 实例 → 宿主机
multipass transfer dev-vm:/home/ubuntu/output.log .

# 递归复制目录
multipass transfer -r ./project dev-vm:/home/ubuntu/

# 挂载宿主机目录到实例（实时同步）
multipass mount ~/code dev-vm:/home/ubuntu/code

# 查看挂载
multipass info dev-vm    # 看 Mounts 字段

# 卸载
multipass umount dev-vm
```

### 4.5 快照与克隆

```bash
# 创建快照（需先停止实例）
multipass stop dev-vm
multipass snapshot dev-vm --name before-experiment

# 查看快照
multipass list --snapshots

# 恢复快照
multipass restore dev-vm.before-experiment

# 克隆实例（需先停止）
multipass stop dev-vm
multipass clone dev-vm --name dev-vm-clone
```

### 4.6 网络

```bash
# 查看可用网络接口
multipass networks

# 启动时指定网络
multipass launch --network en0 --name net-vm

# 启动时指定桥接网络
multipass launch --bridged --name bridged-vm
```

---

## 五、进阶用法

### 5.1 cloud-init 初始化

```bash
# 创建 cloud-init 配置文件
cat > cloud-init.yaml << 'EOF'
#cloud-config
packages:
  - docker.io
  - curl
  - vim
runcmd:
  - sudo usermod -aG docker ubuntu
  - echo "Hello from cloud-init!" > /home/ubuntu/welcome.txt
EOF

# 用 cloud-init 启动实例
multipass launch 24.04 --name auto-vm --cloud-init cloud-init.yaml

# 验证
multipass exec auto-vm -- docker --version
multipass exec auto-vm -- cat /home/ubuntu/welcome.txt
```

### 5.2 Primary Instance（特殊待遇）

```bash
# 创建名为 primary 的实例
multipass launch lts --name primary

# Primary 实例的特权：
# 1. 自动挂载宿主机 Home 目录到 /home/ubuntu/Home/
# 2. 可用 multipass shell（不加实例名）直接进入
multipass shell    # 等同于 multipass shell primary

# 修改默认 primary 名称
multipass set client.primary-name=my-primary
```

### 5.3 配置调整

```bash
# 查看所有配置项
multipass get --keys

# 输出：
# client.primary-name
# local.bridged-network
# local.driver
# local.image.mirror
# local.passphrase
# local.privileged-mounts

# 修改配置
multipass set local.driver=virtualbox
multipass set local.privileged-mounts=true
```

### 5.4 多实例组网实验

```bash
# 启动 3 台 VM 模拟集群
multipass launch 24.04 --name node1 --cpus 2 --memory 2G
multipass launch 24.04 --name node2 --cpus 2 --memory 2G
multipass launch 24.04 --name node3 --cpus 2 --memory 2G

# 它们默认在同一 NAT 网络下，可以互相 ping 通
multipass exec node1 -- ping -c 2 node2
```

---

## 六、与其他方案对比

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| **Multipass** | 一条命令、cloud-init、跨平台 | 仅限 Ubuntu 系、底层是 VM | 快速起 Ubuntu 环境 |
| **Docker** | 秒级启动、镜像生态丰富 | 共享宿主机内核、隔离性弱 | 应用容器化 |
| **UTM** (macOS) | GUI 管理、支持多种 OS | 手动配置多、较重量 | 需要 GUI 或非 Linux 系统 |
| **Vagrant** | 多 Provider、IaC 方式 | 需要额外装 VirtualBox/VMware | 复杂多机环境 |
| **Lima** (macOS) | 轻量、文件共享好 | 仅 macOS、配置稍复杂 | Mac 上 Linux 开发环境 |
| **Parallels Desktop** | 性能好、融合模式 | 收费 | 专业 macOS 虚拟化 |

---

## 七、常见问题

### Q: 启动报错 "multipassd daemon not running"
```bash
# 手动启动守护进程
sudo launchctl load /Library/LaunchDaemons/com.canonical.multipassd.plist
```

### Q: 磁盘空间不够
```bash
# 只能创建时指定，或者用 snapshot 迁移
multipass launch 24.04 --name bigger-vm --disk 50G
```

### Q: 如何切换 Hypervisor
```bash
# macOS 默认 QEMU，可切换 VirtualBox
multipass set local.driver=virtualbox

# Linux 默认 KVM，可切换 QEMU
multipass set local.driver=qemu
```

### Q: 实例之间怎么通信
默认所有实例在同一 NAT 虚拟网络中，直接用实例名称即可互相访问：
```bash
multipass exec node1 -- ping node2
```

### Q: 如何完全卸载
```bash
# 先清除所有实例
multipass delete --all
multipass purge

# macOS 卸载
brew uninstall --zap multipass  # 或 sudo rm -rf /var/root/Library/Application\ Support/multipassd
```

---

## 八、快速参考卡片

```
┌─ 启动 ──────────────────────────────────────┐
│ multipass launch lts --name demo             │
│ multipass launch 24.04 --cpus 2 -m 4G -d 20G │
├─ 查看 ──────────────────────────────────────┤
│ multipass list          # 列表               │
│ multipass info demo     # 详情               │
│ multipass find          # 可用镜像            │
├─ 操作 ──────────────────────────────────────┤
│ multipass shell demo    # 进入 shell          │
│ multipass exec demo -- cmd  # 执行命令        │
│ multipass stop/start/restart demo             │
│ multipass delete demo && multipass purge      │
├─ 文件 ──────────────────────────────────────┤
│ multipass mount ~/code demo                  │
│ multipass transfer file.txt demo:/home/ubuntu/│
├─ 快照 ──────────────────────────────────────┤
│ multipass snapshot demo -n snap1             │
│ multipass restore demo.snap1                 │
│ multipass clone demo -n demo2                │
└──────────────────────────────────────────────┘
```

---

## 参考资料

- [Multipass 官方文档](https://canonical.com/multipass/docs)
- [GitHub 仓库](https://github.com/canonical/multipass)
- [Discourse 社区](https://discourse.ubuntu.com/c/multipass/21)