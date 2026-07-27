# AWS EC2 实例清理脚本解析（AMI 制作前准备）

> 该脚本是 AWS ParallelCluster 等官方 AMI 构建流程中使用的清理脚本，在制作 AMI 镜像之前执行，用于清除实例特有的运行时数据，确保从该 AMI 启动的新实例拥有干净的初始状态。

---

## 一、脚本概述

### 1.1 用途

将一个正在运行的 EC2 实例 **"重置"到出厂状态**，使其可以被打包为 AMI（Amazon Machine Image）。新实例从该 AMI 启动时，cloud-init 会重新初始化网络、SSH 密钥、主机名等，就像全新安装一样。

### 1.2 调用方式

```bash
./cleanup.sh            # 普通清理（非官方 AMI 发布）
./cleanup.sh true       # 官方 AMI 构建，额外清理 DNS 配置
```

---

## 二、逐行解析

### 2.1 参数定义

```bash
IS_OFFICIAL_AMI_BUILD=${1:-"false"}
```

- 接收第一个参数，默认为 `"false"`
- 用于区分「官方 AMI 发布」和「普通内部构建」
- 官方 AMI 发布时会额外清理 DNS 解析器配置

---

### 2.2 清理 cloud-init 状态

```bash
cloud-init clean -s
```

| 作用 | 清除所有 cloud-init 的运行时状态 |
|------|------|
| 清除内容 | 实例 ID、数据源缓存、日志、网络配置记录 |
| `-s` 参数 | 同时清除 `/var/lib/cloud/seed` 中的 seed 数据 |

**为什么需要**：cloud-init 在首次启动时会记录"我已经初始化过了"的标记。如果不清除，从 AMI 启动的新实例会认为自己是旧实例，跳过网络配置、SSH key 注入等初始化步骤，导致新实例无法正常启动。

---

### 2.3 清理临时文件

```bash
rm -rf /var/tmp/* /tmp/*
```

| 路径 | 内容 |
|------|------|
| `/tmp/` | 系统临时文件（重启后通常已清空，此处双重保险） |
| `/var/tmp/` | 持久化临时文件（重启后保留，必须手动清理） |

**为什么需要**：打包到 AMI 中的临时文件不仅浪费空间，还可能包含敏感信息（如安装脚本、临时密钥）。

---

### 2.4 清理 SSH 主机密钥

```bash
rm -rf /etc/ssh/ssh_host_*
```

| 删除的文件 | 说明 |
|-----------|------|
| `ssh_host_rsa_key` | RSA 主机私钥 |
| `ssh_host_ecdsa_key` | ECDSA 主机私钥 |
| `ssh_host_ed25519_key` | Ed25519 主机私钥 |
| `ssh_host_*_key.pub` | 对应的公钥文件 |

**为什么需要**：→ **这是最关键的步骤之一。**

SSH 主机密钥是每台机器的"身份证"。如果多个实例共享同一份主机密钥：

1. **安全风险**：中间人攻击保护失效，无法区分不同实例
2. **SSH 警告**：客户端会报 `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED`

新实例启动时，cloud-init 或 sshd 会自动重新生成密钥对。

---

### 2.5 清理网络设备持久化规则

```bash
rm -f /etc/udev/rules.d/70-persistent-net.rules
```

| 文件作用 | 将网卡 MAC 地址绑定到固定设备名（如 eth0） |
|----------|------|

**为什么需要**：EC2 实例的虚拟网卡 MAC 地址每次启动都不同。如果保留旧规则，新实例的网卡会被命名为 `eth1` 而不是 `eth0`，导致网络配置失效。

---

### 2.6 清理 cloud-init 自动生成的网络配置

```bash
grep -l "Created by cloud-init on instance boot automatically" /etc/sysconfig/network-scripts/ifcfg-* | xargs rm -f
```

| 操作 | 找到 cloud-init 自动生成的网卡配置文件并删除 |
|------|------|
| 适用系统 | RHEL/CentOS/Amazon Linux 2 |

**为什么需要**：cloud-init 在首次启动时会根据实例的 MAC 地址生成网卡配置。这些配置绑定到旧实例的 MAC 地址，新实例的 MAC 地址不同，保留会导致网络不通。

---

### 2.7 清理内核崩溃转储

```bash
rm -rf /var/crash/*
```

删除 `/var/crash/` 下的内核崩溃转储文件（vmcore dump），这些文件体积巨大且对镜像无意义。

---

### 2.8 ParallelCluster 特殊处理

```bash
if [ -f /opt/parallelcluster/pin_releasesever ]; then
    rm -f /opt/parallelcluster/pin_releasesever
    rm -f /etc/yum/vars/releasever
fi
```

| 文件 | 作用 |
|------|------|
| `pin_releasesever` | ParallelCluster 用来锁定 yum 仓库版本的标记文件 |
| `releasever` | yum 变量，指定使用哪个系统版本的仓库 |

**为什么需要**：AMI 构建时可能锁定了特定版本，但发布给用户后应该让用户自由选择版本。删除这些文件恢复默认行为。

---

### 2.9 CentOS 7 特殊处理

```bash
source /etc/os-release
if [ "${ID}${VERSION_ID}" == "centos7" ]; then
    rm -f /etc/sysconfig/network-scripts/ifcfg-eth0
fi
```

CentOS 7 有一个已知 bug（[bugs.centos.org #13836](https://bugs.centos.org/view.php?id=13836)）：
- cloud-init 生成的 `ifcfg-eth0` 可能与系统默认配置冲突
- 删除这个文件让系统在启动时使用默认配置生成正确的网络设置

---

### 2.10 清理 DNS 解析器配置（仅官方 AMI）

```bash
if [ "${IS_OFFICIAL_AMI_BUILD}" == "true" ]; then
    echo "Clean resolv.conf for official AMIs"
    echo -n > /etc/resolv.conf
    rm -f /run/systemd/resolve/resolv.conf
fi
```

| 文件 | 作用 |
|------|------|
| `/etc/resolv.conf` | DNS 解析器配置 |
| `/run/systemd/resolve/resolv.conf` | systemd-resolved 运行时配置 |

**为什么需要**：官方 AMI 构建环境中可能配置了内部 DNS 服务器。如果不清除，用户启动实例后会尝试连接内部 DNS，导致域名解析失败。清空后新实例会通过 DHCP 自动获取正确的 DNS 配置。

> ⚠️ 只有 `IS_OFFICIAL_AMI_BUILD=true` 时才执行，因为普通构建可能依赖内部 DNS 进行后续操作。

---

### 2.11 清理所有系统日志

```bash
find /var/log -type f -exec /bin/rm -v {} \;
touch /var/log/lastlog
```

| 操作 | 说明 |
|------|------|
| 删除所有日志文件 | `/var/log/messages`, `/var/log/secure`, `/var/log/cloud-init*` 等 |
| 重建 `lastlog` | `lastlog` 是稀疏文件，记录用户最后登录时间，`touch` 重建空文件即可 |

**为什么需要**：
1. **体积**：日志文件可能累积数 GB
2. **隐私**：日志中可能包含 IP 地址、用户名、执行的命令等敏感信息
3. **清洁**：新实例启动后从头开始记录日志，避免混淆

---

## 三、为什么需要这个脚本

### 3.1 AMI 制作的核心原则

AMI 是「系统盘的快照」，从同一个 AMI 启动的所有实例共享同一份初始磁盘内容。因此：

> **AMI 中不能包含任何"实例特有"的信息。**

这些信息包括：

| 类别 | 示例 | 清理方法 |
|------|------|----------|
| 网络标识 | MAC 地址、IP 地址 | 删除 udev 规则、ifcfg 文件 |
| 安全密钥 | SSH 主机密钥 | 删除 `ssh_host_*` |
| 运行状态 | cloud-init 标记 | `cloud-init clean` |
| 日志 | 系统日志、崩溃转储 | 删除 `/var/log/*` |
| DNS 配置 | 内部 DNS 服务器 | 清空 `resolv.conf` |

### 3.2 执行时机

```
安装软件 → 配置系统 → 执行本脚本 → 关机 → 创建 AMI
                                    ↑
                              这个时机执行清理
```

### 3.3 新实例启动流程

```
从 AMI 启动 → cloud-init 检测到无状态 → 首次初始化
    ├── 生成新 SSH 主机密钥
    ├── 配置网络（DHCP 获取 IP）
    ├── 设置主机名
    ├── 注入用户 SSH 公钥
    └── 执行 user-data 脚本
```

---

## 四、注意事项

| 注意点 | 说明 |
|--------|------|
| **执行后不要重启** | 清理后应立即关机做 AMI，重启会触发 cloud-init 重新初始化 |
| **SSH 密钥丢失** | 清理后原有的 SSH 主机密钥不可恢复，但新实例会自动生成 |
| **日志丢失** | 如有需要，应在清理前将日志备份到外部存储（如 S3） |
| **DNS 配置** | 非官方构建不要清空 `resolv.conf`，否则后续 `yum install` 等操作会失败 |
| **仅限 Linux** | 该脚本只适用于 RHEL/CentOS/Amazon Linux 生态，Windows 有完全不同的 Sysprep 流程 |

---

## 五、与 AWS 官方工具的关系

AWS 提供了 **EC2 Image Builder** 和 **Packer** 等工具自动执行类似清理，但手写脚本的优势在于：

- 完全可控，不需要额外依赖
- 适配特定发行版的 quirks（如 CentOS 7 的 ifcfg bug）
- 适合 CI/CD 流水线中集成

---

> **参考**：cloud-init 文档 (cloudinit.readthedocs.io)、AWS ParallelCluster 源码、CentOS Bug #13836