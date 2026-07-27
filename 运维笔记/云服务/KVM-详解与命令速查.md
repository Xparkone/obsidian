# KVM（Kernel-based Virtual Machine）详解与命令速查

> 文档版本：v1.0 | 更新日期：2026-06-24

---

## 一、KVM 是什么

**KVM（Kernel-based Virtual Machine）** 是 Linux 内核原生支持的虚拟化技术，将 Linux 内核变成一个 **Hypervisor（虚拟机监视器）**。

### 核心原理

```
┌──────────────────────────────────────────────────────────┐
│                     Linux 宿主机（Host）                    │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │  VM 1    │  │  VM 2    │  │  VM 3    │  普通进程      │
│  │ (Guest)  │  │ (Guest)  │  │ (Guest)  │               │
│  │  QEMU    │  │  QEMU    │  │  QEMU    │               │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘               │
│       │             │             │                      │
│       ▼             ▼             ▼                      │
│  ┌─────────────────────────────────────┐                │
│  │         /dev/kvm（KVM 内核模块）      │                │
│  │    ┌───────────────────────────┐    │                │
│  │    │  VMX (Intel VT-x) 或       │    │                │
│  │    │  SVM (AMD-V) 硬件扩展      │    │                │
│  │    └───────────────────────────┘    │                │
│  └─────────────────────────────────────┘                │
│                         │                                │
│                         ▼                                │
│              ┌──────────────────┐                       │
│              │  物理 CPU / 内存  │                       │
│              └──────────────────┘                       │
└──────────────────────────────────────────────────────────┘
```

### 关键特性

| 特性 | 说明 |
|------|------|
| **内核模块** | `kvm.ko`（通用）+ `kvm-intel.ko` 或 `kvm-amd.ko`（平台） |
| **硬件辅助** | 依赖 Intel VT-x 或 AMD-V 硬件虚拟化扩展 |
| **类型** | Type-1 Hypervisor（裸金属级），但寄生于 Linux 内核 |
| **QEMU 配合** | KVM 负责 CPU/内存虚拟化，QEMU 负责 I/O 设备模拟 |
| **许可证** | GPL v2 |
| **支持架构** | x86_64、ARM64、PowerPC、s390x |

---

## 二、核心组件

### 1. KVM 内核模块

```
kvm.ko          → 核心虚拟化框架
kvm-intel.ko    → Intel VT-x 支持（vmx）
kvm-amd.ko      → AMD-V 支持（svm）
```

### 2. QEMU（Quick Emulator）

| 角色 | 说明 |
|------|------|
| **用户态模拟** | 模拟网卡、磁盘控制器、USB、VGA 等 I/O 设备 |
| **加速模式** | `/dev/kvm` 接管 CPU 和内存，大幅提升性能 |
| **进程模型** | 每个 VM 对应一个 QEMU 进程，受 Linux 调度器管理 |

### 3. libvirt（虚拟化管理 API）

| 组件 | 说明 |
|------|------|
| **libvirtd** | 守护进程，统一管理 KVM/QEMU/ Xen / LXC 等 |
| **virsh** | 命令行管理工具（最常用） |
| **virt-manager** | 图形化 GUI 管理工具 |
| **virt-install** | 命令行创建虚拟机 |
| **virt-viewer** | 虚拟机 VNC/SPICE 控制台 |

### 4. 存储与网络

| 组件 | 说明 |
|------|------|
| **qemu-img** | 磁盘镜像管理（创建、转换、快照） |
| **virtio** | 半虚拟化驱动，高性能 I/O（virtio-blk、virtio-net） |
| **virbr0** | libvirt 默认 NAT 网桥（192.168.122.0/24） |
| **brctl / bridge** | Linux 桥接网络，实现 VM 直连物理网络 |

---

## 三、环境检查与安装

### 检查 CPU 是否支持虚拟化

```bash
# Intel CPU
grep -E '(vmx|svm)' /proc/cpuinfo

# 或使用 lscpu
lscpu | grep Virtualization

# 检查 KVM 模块是否加载
lsmod | grep kvm
```

### 安装 KVM + libvirt（Ubuntu/Debian）

```bash
sudo apt update
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients \
  bridge-utils virt-manager virtinst virt-viewer

# 启用并启动 libvirtd
sudo systemctl enable --now libvirtd

# 将用户加入 libvirt 组（免 sudo）
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER
# 重新登录生效
```

### 安装 KVM + libvirt（CentOS/RHEL）

```bash
sudo dnf install -y qemu-kvm libvirt virt-install virt-manager virt-viewer

sudo systemctl enable --now libvirtd
sudo usermod -aG libvirt $USER
```

---

## 四、virsh 命令大全（虚拟机管理）

### 4.1 连接与信息

```bash
# 连接本地 hypervisor
virsh list                    # 列出运行中的 VM
virsh list --all              # 列出所有 VM（含关机）
virsh list --autostart        # 列出开机自启的 VM

# 查看信息
virsh nodeinfo                # 宿主机信息
virsh dominfo <vm>            # VM 详细信息
virsh domstate <vm>           # VM 运行状态
virsh domstats <vm>           # VM 统计信息
virsh vcpucount <vm>          # 查看 vCPU 数量
virsh dommemstat <vm>         # 查看内存统计
virsh domiflist <vm>          # 查看网络接口
virsh domblklist <vm>         # 查看磁盘设备
virsh domfsinfo <vm>          # 查看文件系统信息
```

### 4.2 生命周期管理

```bash
virsh start <vm>              # 启动 VM
virsh shutdown <vm>           # 优雅关机（发送 ACPI 信号）
virsh destroy <vm>            # 强制关机（拔电源）
virsh reboot <vm>             # 重启
virsh reset <vm>              # 强制重置
virsh suspend <vm>            # 挂起（暂停）
virsh resume <vm>             # 恢复
virsh save <vm> <file>        # 保存状态到文件
virsh restore <file>          # 从文件恢复状态
virsh managedsave <vm>        # 托管保存（libvirt 自动管理）
virsh autostart <vm>          # 设置开机自启
virsh autostart --disable <vm> # 取消开机自启
```

### 4.3 虚拟机定义管理

```bash
virsh define <xml>            # 从 XML 定义 VM（不启动）
virsh undefine <vm>           # 删除 VM 定义（不删除磁盘）
virsh undefine <vm> --remove-all-storage  # 删除 VM + 磁盘
virsh dumpxml <vm>            # 导出 VM XML 配置
virsh dumpxml <vm> > vm.xml   # 备份 XML 到文件
virsh edit <vm>               # 编辑 XML 配置（生效需重启）
virsh define /path/to/vm.xml  # 从 XML 文件重新定义
```

### 4.4 资源调整

```bash
# CPU 调整
virsh setvcpus <vm> 4 --maximum   # 设置最大 vCPU
virsh setvcpus <vm> 4 --current   # 调整当前 vCPU（需重启）
virsh setvcpus <vm> 4 --config    # 持久化配置
virsh vcpupin <vm> <vcpu> <pcpu>  # 绑定 vCPU 到物理 CPU

# 内存调整
virsh setmaxmem <vm> 8G --config  # 设置最大内存（持久化）
virsh setmem <vm> 4G --current    # 调整当前内存（热生效）
virsh setmem <vm> 4G --config     # 持久化配置

# 磁盘热插拔
virsh attach-disk <vm> /path/disk.qcow2 vdb --targetbus virtio
virsh detach-disk <vm> vdb
virsh attach-disk <vm> /path/disk.qcow2 vdb --config --live  # 持久+热插

# 网卡热插拔
virsh attach-interface <vm> --type bridge --source br0 --model virtio
virsh detach-interface <vm> --type bridge --mac 52:54:00:xx:xx:xx
```

### 4.5 快照管理

```bash
virsh snapshot-create-as <vm> --name snap1           # 创建快照
virsh snapshot-create-as <vm> --name snap1 --description "更新前"  
virsh snapshot-list <vm>                             # 列出快照
virsh snapshot-info <vm> --snapshotname snap1        # 快照详情
virsh snapshot-revert <vm> --snapshotname snap1      # 恢复快照
virsh snapshot-delete <vm> --snapshotname snap1      # 删除快照
virsh snapshot-current <vm>                          # 查看当前快照
virsh snapshot-parent <vm> --snapshotname snap1      # 查看父快照
```

### 4.6 控制台与认证

```bash
virsh console <vm>              # 串口控制台（Ctrl+] 退出）
virsh vncdisplay <vm>           # 查看 VNC 端口
virt-viewer <vm>                # 图形化控制台
```

### 4.7 存储池管理

```bash
virsh pool-list                         # 列出存储池
virsh pool-list --all                   # 所有存储池（含未激活）
virsh pool-info <pool>                  # 存储池详情
virsh pool-start <pool>                 # 激活存储池
virsh pool-autostart <pool>             # 设置自动启动
virsh pool-destroy <pool>               # 停止存储池
virsh pool-delete <pool>                # 删除存储池
virsh pool-define-as <name> dir --target /path  # 定义目录存储池
virsh pool-build <pool>                 # 构建存储池
virsh vol-list <pool>                   # 列出卷
virsh vol-info <vol> --pool <pool>      # 卷详情
virsh vol-delete <vol> --pool <pool>    # 删除卷
virsh vol-create-as <pool> <name> 10G   # 创建卷
virsh vol-clone <vol> <new> --pool <pool>  # 克隆卷
```

### 4.8 网络管理

```bash
virsh net-list                    # 列出网络
virsh net-info <network>          # 网络详情
virsh net-dumpxml <network>       # 导出网络 XML
virsh net-start <network>         # 启动网络
virsh net-autostart <network>     # 设置自动启动
virsh net-destroy <network>       # 停止网络
virsh net-undefine <network>      # 删除网络定义
virsh net-define <xml>            # 从 XML 定义网络
virsh net-dhcp-leases <network>   # 查看 DHCP 租约
```

---

## 五、virt-install 命令大全（创建虚拟机）

### 5.1 基本语法

```bash
virt-install \
  --name <vm名> \
  --ram <内存MB> \
  --vcpus <CPU数> \
  --disk path=<磁盘路径>,size=<大小GB>,format=qcow2 \
  --os-variant <系统类型> \
  --network <网络配置> \
  --graphics <图形配置> \
  --cdrom <ISO路径>
```

### 5.2 常用示例

```bash
# 最小化安装（文本模式）
virt-install \
  --name test-vm \
  --ram 2048 \
  --vcpus 2 \
  --disk path=/var/lib/libvirt/images/test.qcow2,size=20 \
  --os-variant ubuntu22.04 \
  --network network=default \
  --graphics none \
  --console pty,target_type=serial \
  --location /path/to/ubuntu.iso \
  --extra-args 'console=ttyS0,115200n8'

# 图形化安装（VNC）
virt-install \
  --name centos-vm \
  --ram 4096 \
  --vcpus 4 \
  --disk path=/var/lib/libvirt/images/centos.qcow2,size=40 \
  --os-variant centos7.0 \
  --network bridge=br0 \
  --graphics vnc,listen=0.0.0.0 \
  --cdrom /path/to/centos.iso

# 使用 virtio 高性能磁盘
virt-install \
  --name perf-vm \
  --ram 8192 \
  --vcpus 8 \
  --disk path=/data/vm/perf.qcow2,size=100,bus=virtio,cache=none,io=native \
  --network bridge=br0,model=virtio \
  --os-variant ubuntu22.04 \
  --cdrom /path/to/ubuntu.iso

# 从已有磁盘导入（不重装系统）
virt-install \
  --name imported-vm \
  --ram 4096 \
  --vcpus 4 \
  --disk path=/data/existing.qcow2,bus=virtio \
  --network bridge=br0 \
  --import

# 通过 PXE 网络启动
virt-install \
  --name pxe-vm \
  --ram 4096 \
  --vcpus 4 \
  --disk size=50 \
  --network bridge=br0 \
  --pxe \
  --os-variant ubuntu22.04
```

### 5.3 常用参数说明

| 参数 | 说明 |
|------|------|
| `--name` | 虚拟机名称 |
| `--ram` | 内存大小（MB） |
| `--vcpus` | CPU 核心数 |
| `--disk path=...,size=...,format=qcow2` | 磁盘配置 |
| `--disk bus=virtio` | 使用 virtio 半虚拟化磁盘（高性能） |
| `--disk cache=none` | 缓存模式（none/writeback/writethrough） |
| `--network bridge=br0` | 桥接网络 |
| `--network network=default` | NAT 网络 |
| `--network model=virtio` | virtio 网卡（高性能） |
| `--graphics vnc` | VNC 图形控制台 |
| `--graphics spice` | SPICE 图形控制台（更好体验） |
| `--graphics none` | 无图形（纯文本串口） |
| `--cdrom` | 挂载 ISO 光盘 |
| `--location` | 安装源（URL/ISO） |
| `--import` | 导入已有磁盘，不安装 |
| `--os-variant` | 操作系统类型（优化默认参数） |
| `--noautoconsole` | 不自动连接控制台 |
| `--autostart` | 创建后自动启动 |
| `--dry-run` | 模拟运行，不实际创建 |

### 5.4 查看支持的 os-variant 列表

```bash
osinfo-query os
# 或
virt-install --os-variant list
```

---

## 六、qemu-img 命令大全（磁盘镜像管理）

### 6.1 创建镜像

```bash
# 创建 qcow2 格式（精简置备，Cow 写时复制）
qemu-img create -f qcow2 disk.qcow2 20G

# 创建 raw 格式（完整分配，性能最优）
qemu-img create -f raw disk.raw 20G

# 预分配 qcow2（提高性能）
qemu-img create -f qcow2 -o preallocation=full disk.qcow2 20G

# 创建带加密的 qcow2
qemu-img create -f qcow2 -o encryption=on disk.qcow2 20G
```

### 6.2 格式转换

```bash
# raw → qcow2
qemu-img convert -f raw -O qcow2 disk.raw disk.qcow2

# qcow2 → raw
qemu-img convert -f qcow2 -O raw disk.qcow2 disk.raw

# vmdk（VMware）→ qcow2
qemu-img convert -f vmdk -O qcow2 vmware.vmdk kvm.qcow2

# vdi（VirtualBox）→ qcow2
qemu-img convert -f vdi -O qcow2 virtualbox.vdi kvm.qcow2

# 压缩转换
qemu-img convert -c -f qcow2 -O qcow2 source.qcow2 compressed.qcow2
```

### 6.3 查看信息

```bash
qemu-img info disk.qcow2           # 查看基本信息
qemu-img info --output=json disk.qcow2  # JSON 格式输出
qemu-img check disk.qcow2          # 检查镜像一致性
qemu-img compare a.qcow2 b.qcow2   # 比较两个镜像
qemu-img measure disk.qcow2        # 测量所需目标大小
```

### 6.4 快照操作

```bash
qemu-img snapshot -l disk.qcow2             # 列出快照
qemu-img snapshot -c snap1 disk.qcow2       # 创建快照
qemu-img snapshot -a snap1 disk.qcow2       # 应用（恢复）快照
qemu-img snapshot -d snap1 disk.qcow2       # 删除快照
```

### 6.5 镜像扩缩

```bash
qemu-img resize disk.qcow2 +10G            # 增加 10G
qemu-img resize disk.qcow2 50G             # 调整为 50G
qemu-img resize --shrink disk.qcow2 10G    # 缩小到 10G（raw 格式）
```

### 6.6 高级操作

```bash
# 创建 backing file 链（模板镜像）
qemu-img create -f qcow2 -b base.qcow2 -F qcow2 overlay.qcow2

# 提交 backing file 修改
qemu-img commit overlay.qcow2

# 重新指定 backing file
qemu-img rebase -b new-base.qcow2 overlay.qcow2

# 修改 qcow2 选项
qemu-img amend -o cluster_size=2M disk.qcow2
```

---

## 七、网络配置

### 7.1 默认 NAT 网络（virbr0）

```bash
# 默认网段：192.168.122.0/24
# 宿主机 IP：192.168.122.1
# DHCP 范围：192.168.122.2 ~ 192.168.122.254

# 查看 NAT 网络
virsh net-dumpxml default
```

### 7.2 桥接网络（让 VM 直连物理网络）

```bash
# 创建网桥（Netplan 方式，Ubuntu 18.04+）
# /etc/netplan/01-netcfg.yaml
```

```yaml
network:
  version: 2
  ethernets:
    eth0:
      dhcp4: no
  bridges:
    br0:
      interfaces: [eth0]
      dhcp4: yes
```

```bash
sudo netplan apply

# 或使用 nmcli 创建网桥
nmcli con add type bridge ifname br0
nmcli con add type bridge-slave ifname eth0 master br0
nmcli con up br0
```

### 7.3 隔离网络

```bash
# 创建纯隔离网络（VM 间通信，不与宿主机外部通信）
cat > isolated.xml << 'EOF'
<network>
  <name>isolated</name>
  <bridge name='virbr1'/>
</network>
EOF

virsh net-define isolated.xml
virsh net-start isolated
virsh net-autostart isolated
```

---

## 八、存储与性能优化

### 8.1 磁盘格式对比

| 格式 | 精简置备 | 快照 | 加密 | 压缩 | 性能 | 适用场景 |
|------|:--:|:--:|:--:|:--:|:--:|------|
| **raw** | ✗ | ✗ | ✗ | ✗ | ⭐⭐⭐ | 追求极致性能 |
| **qcow2** | ✓ | ✓ | ✓ | ✓ | ⭐⭐ | 通用场景，推荐 |
| **vmdk** | ✓ | ✓ | ✗ | ✗ | ⭐⭐ | VMware 兼容 |

### 8.2 缓存模式

| 模式 | 数据安全 | 性能 | 说明 |
|------|:--:|:--:|------|
| **none** | ✓ | ⭐⭐⭐ | 绕过宿主机页缓存，推荐 |
| **writethrough** | ✓ | ⭐⭐ | 每次写都同步到磁盘 |
| **writeback** | ✗ | ⭐⭐⭐ | 写操作先缓存再落盘 |
| **directsync** | ✓ | ⭐ | 最安全但最慢 |

### 8.3 CPU 优化

```bash
# CPU 模式选择
virsh edit <vm>
```

```xml
<cpu mode='host-passthrough' check='none'>  <!-- 直接暴露宿主机 CPU 特性，性能最佳 -->
  <topology sockets='1' dies='1' cores='4' threads='2'/>  <!-- 1 插槽 × 4 核 × 2 线程 = 8 vCPU -->
</cpu>

<!-- 或使用 host-model（兼容迁移） -->
<cpu mode='host-model' check='partial'/>
```

### 8.4 内存优化

```bash
# 大页内存（减少 TLB miss）
echo 2048 > /proc/sys/vm/nr_hugepages

# VM 使用大页内存
virsh edit <vm>
```

```xml
<memoryBacking>
  <hugepages/>
</memoryBacking>
```

### 8.5 NUMA 绑定

```bash
# 查看 NUMA 拓扑
numactl --hardware

# 绑定 VM 到特定 NUMA 节点
virsh edit <vm>
```

```xml
<numatune>
  <memory mode='strict' nodeset='0'/>
</numatune>
<cpu>
  <numa>
    <cell id='0' cpus='0-3' memory='4' unit='GiB'/>
  </numa>
</cpu>
```

---

## 九、常见问题排查

### 9.1 诊断命令

```bash
# 查看 VM 日志
virsh qemu-monitor-command <vm> --hmp 'info status'

# QEMU 进程日志
tail -f /var/log/libvirt/qemu/<vm>.log

# libvirt 日志
journalctl -u libvirtd -f

# 测试硬件加速
egrep -c '(vmx|svm)' /proc/cpuinfo   # > 0 表示支持

# 验证 KVM 可用
kvm-ok
```

### 9.2 常见错误

| 错误现象 | 原因 | 解决方法 |
|------|------|------|
| `permission denied` | 用户不在 libvirt 组 | `sudo usermod -aG libvirt $USER` |
| `KVM not available` | 未加载 KVM 模块 | `modprobe kvm && modprobe kvm-intel` |
| `Cannot access storage file` | AppArmor/SELinux 阻止 | 调整路径或关闭 `aa-complain` |
| `No bootable device` | 磁盘未挂载或无系统 | 添加 `--cdrom` 安装系统 |
| 网络不通 | 网桥未配置 | `brctl show` 检查网桥 |
| `Could not get snapshot` | 磁盘格式不支持 | raw 格式不支持快照，转换为 qcow2 |

### 9.3 性能调优检查清单

```bash
# 1. 确认 virtio 驱动已加载
virsh dumpxml <vm> | grep virtio

# 2. 确认 CPU 直通
virsh dumpxml <vm> | grep 'cpu mode'

# 3. 确认磁盘缓存模式
virsh dumpxml <vm> | grep cache

# 4. 确认大页内存
cat /proc/meminfo | grep HugePages

# 5. 确认网卡多队列
virsh dumpxml <vm> | grep queues
```

---

## 十、命令速查卡片

```
┌─── 虚拟机管理 ───────────────────────────────────┐
│ virsh list --all              # 列出所有 VM       │
│ virsh start <vm>              # 启动              │
│ virsh shutdown <vm>           # 优雅关机           │
│ virsh destroy <vm>            # 强制关机           │
│ virsh reboot <vm>             # 重启              │
│ virsh autostart <vm>          # 开机自启           │
│ virsh undefine <vm>           # 删除 VM            │
│ virsh dominfo <vm>            # VM 信息            │
│ virsh dumpxml <vm>            # 导出 XML           │
│ virsh edit <vm>               # 编辑 XML           │
│ virsh console <vm>            # 串口控制台         │
│ virsh vncdisplay <vm>         # 查看 VNC 端口      │
└──────────────────────────────────────────────────┘
┌─── 快照管理 ─────────────────────────────────────┐
│ virsh snapshot-create-as <vm> --name snap1       │
│ virsh snapshot-list <vm>                          │
│ virsh snapshot-revert <vm> --snapshotname snap1   │
│ virsh snapshot-delete <vm> --snapshotname snap1   │
└──────────────────────────────────────────────────┘
┌─── 磁盘管理 ─────────────────────────────────────┐
│ qemu-img create -f qcow2 disk.qcow2 20G          │
│ qemu-img info disk.qcow2                          │
│ qemu-img convert -f raw -O qcow2 a.raw a.qcow2    │
│ qemu-img resize disk.qcow2 +10G                   │
│ qemu-img snapshot -c snap1 disk.qcow2             │
│ virsh pool-list                                   │
│ virsh vol-list <pool>                             │
└──────────────────────────────────────────────────┘
┌─── 创建 VM ──────────────────────────────────────┐
│ virt-install \                                    │
│   --name vm --ram 4096 --vcpus 4 \                │
│   --disk size=40,format=qcow2 \                   │
│   --cdrom /path/to/iso \                          │
│   --network bridge=br0 \                          │
│   --graphics vnc                                  │
└──────────────────────────────────────────────────┘
┌─── 网络管理 ─────────────────────────────────────┐
│ virsh net-list                                    │
│ virsh net-info <net>                              │
│ virsh net-dhcp-leases <net>                       │
│ brctl show                                        │
└──────────────────────────────────────────────────┘
```

---

## 十一、常见与不常见命令总结

> 按使用频率和场景分级，从日常用到高级排查全覆盖。

### 11.1 常见命令（每日必用）

#### 虚拟机生命周期

```bash
virsh list --all                          # 查看所有 VM 状态
virsh start centos7                       # 启动 VM
virsh shutdown centos7                    # 优雅关机
virsh destroy centos7                     # 强制关机（紧急）
virsh reboot centos7                      # 重启
virsh autostart centos7                   # 宿主机开机自动启动 VM
virsh autostart --disable centos7         # 取消自启
```

#### 查看信息

```bash
virsh dominfo centos7                     # VM 基本信息（CPU/内存/状态）
virsh domstate centos7                    # 当前运行状态
virsh vcpucount centos7                   # 查看 vCPU 数量
virsh dommemstat centos7                  # 内存使用统计
virsh domiflist centos7                   # 列出网络接口及 MAC
virsh domblklist centos7                  # 列出磁盘设备
virsh nodeinfo                            # 宿主机 CPU/内存/架构
```

#### 控制台

```bash
virsh console centos7                     # 串口控制台（Ctrl+] 退出）
virsh vncdisplay centos7                  # 查看 VNC 端口号
```

#### XML 配置

```bash
virsh dumpxml centos7 > centos7.xml       # 备份 VM 配置
virsh edit centos7                        # 在线编辑 XML（关机生效）
virsh define centos7.xml                  # 从 XML 文件重新定义 VM
```

#### 快照

```bash
virsh snapshot-create-as centos7 --name before-update    # 创建快照
virsh snapshot-list centos7                              # 列出快照
virsh snapshot-revert centos7 --snapshotname before-update  # 回滚快照
virsh snapshot-delete centos7 --snapshotname before-update  # 删除快照
```

#### 网络

```bash
virsh net-list                            # 列出网络
virsh net-dhcp-leases default             # 查看 DHCP 分配记录
```

---

### 11.2 次常见命令（运维常用）

#### 资源热调整

```bash
# 热添加 vCPU（需 guest OS 支持）
virsh setvcpus centos7 4 --current --live

# 热调整内存（balloon 驱动）
virsh setmem centos7 4G --current --live

# 热添加磁盘
virsh attach-disk centos7 /data/new-disk.qcow2 vdb --targetbus virtio --live --config

# 热移除磁盘
virsh detach-disk centos7 vdb --live --config

# 热添加网卡
virsh attach-interface centos7 --type bridge --source br0 --model virtio --live --config

# 热移除网卡
virsh detach-interface centos7 --type bridge --mac 52:54:00:ab:cd:ef --live --config
```

#### 挂起/恢复

```bash
virsh suspend centos7                     # 挂起 VM（暂停 CPU）
virsh resume centos7                      # 恢复运行
virsh save centos7 /data/vm-save.state    # 保存完整状态到文件
virsh restore /data/vm-save.state         # 从文件恢复
virsh managedsave centos7                 # libvirt 托管保存（自动管理路径）
```

#### 存储池管理

```bash
virsh pool-list --all                     # 存储池列表
virsh pool-info default                   # 默认池详情
virsh pool-define-as mypool dir --target /data/vm-images  # 新建目录池
virsh pool-start mypool                   # 激活池
virsh pool-autostart mypool               # 自动启动
virsh vol-list default                    # 列出卷
virsh vol-create-as default new-disk.qcow2 20G --format qcow2  # 创建卷
virsh vol-delete new-disk.qcow2 --pool default                   # 删除卷
virsh vol-clone source.qcow2 clone.qcow2 --pool default          # 克隆卷
```

#### 删除 VM

```bash
virsh destroy centos7                     # 先强制关机
virsh undefine centos7                    # 删除定义（保留磁盘）
virsh undefine centos7 --remove-all-storage  # 删除定义 + 磁盘（危险！）
```

#### 磁盘镜像操作

```bash
qemu-img create -f qcow2 disk.qcow2 20G   # 创建镜像
qemu-img info disk.qcow2                  # 查看信息
qemu-img convert -f raw -O qcow2 a.raw a.qcow2   # 格式转换
qemu-img resize disk.qcow2 +10G           # 扩容
qemu-img snapshot -c snap1 disk.qcow2     # disk 级快照
qemu-img snapshot -l disk.qcow2           # 列出快照
```

---

### 11.3 不常见命令（高级场景）

#### 统计与诊断

```bash
virsh domstats centos7                    # 详细统计（CPU/内存/磁盘/网络）
virsh domstats centos7 --cpu-total        # 仅 CPU 统计
virsh domstats centos7 --balloon          # 内存 balloon 统计
virsh domstats centos7 --block            # 块设备 I/O 统计
virsh domstats centos7 --interface        # 网卡流量统计
virsh domtime centos7                     # 查看 VM 时间
virsh domtime centos7 --now               # 同步 VM 时间到宿主机
virsh domifstat centos7 vnet0             # 网卡实时流量
virsh domblkstat centos7 vda              # 磁盘实时 I/O
virsh domblkerror centos7                 # 磁盘 I/O 错误
virsh domcontrol centos7                  # 控制接口状态
virsh domjobinfo centos7                  # 正在执行的后台任务进度
virsh domjobabort centos7                 # 中止后台任务
```

#### QEMU Monitor 直连（底层调试）

```bash
# 进入 QEMU Monitor（HMP 模式）
virsh qemu-monitor-command centos7 --hmp 'info status'
virsh qemu-monitor-command centos7 --hmp 'info cpus'
virsh qemu-monitor-command centos7 --hmp 'info block'
virsh qemu-monitor-command centos7 --hmp 'info network'
virsh qemu-monitor-command centos7 --hmp 'info pci'
virsh qemu-monitor-command centos7 --hmp 'info usb'
virsh qemu-monitor-command centos7 --hmp 'info memory'
virsh qemu-monitor-command centos7 --hmp 'info tlb'
virsh qemu-monitor-command centos7 --hmp 'info registers'   # 查看 CPU 寄存器
virsh qemu-monitor-command centos7 --hmp 'info snapshots'   # QEMU 快照列表
virsh qemu-monitor-command centos7 --hmp 'info migrate'     # 迁移状态

# 动态修改 QEMU 参数（极其危险，慎用！）
virsh qemu-monitor-command centos7 --hmp 'sendkey ctrl-alt-delete'   # 发送 Ctrl+Alt+Del
virsh qemu-monitor-command centos7 --hmp 'change ide1-cd0 /new.iso'  # 热更换光驱 ISO
virsh qemu-monitor-command centos7 --hmp 'eject ide1-cd0'            # 弹出光驱
virsh qemu-monitor-command centos7 --hmp 'screendump /tmp/vm.ppm'    # 截屏
virsh qemu-monitor-command centos7 --hmp 'balloon 2048'              # 手动调整 balloon
virsh qemu-monitor-command centos7 --hmp 'migrate_set_speed 1G'      # 设置迁移带宽
```

#### CPU 绑定与亲和性

```bash
# 查看物理 CPU 拓扑
virsh nodeinfo                            # 总览
virsh capabilities                        # 详细 XML 拓扑
virsh vcpupin centos7                     # 查看 vCPU → 物理 CPU 绑定
virsh vcpupin centos7 0 2                 # 绑定 vCPU0 到物理 CPU 2
virsh vcpupin centos7 0 2-3               # 绑定到 CPU 范围
virsh vcpupin centos7 0 2,4,6            # 绑定到多个 CPU
virsh vcpupin centos7 --live 0 2          # 仅当前生效（不持久化）
virsh vcpupin centos7 --config 0 2        # 仅持久化（不立即生效）
virsh emulatorpin centos7                 # 查看 QEMU 进程的 CPU 绑定
virsh emulatorpin centos7 0-1             # 绑定 QEMU 进程到 CPU 0-1
virsh emulatorpin centos7 --live 0-1
```

#### NUMA 调优

```bash
# 查看宿主机 NUMA 拓扑
numactl --hardware
virsh numatune centos7                    # 查看 VM 的 NUMA 绑定
virsh freepages --all                     # 查看大页内存可用量
virsh allocpages 2048 2M --nodeset 0      # 在 NUMA 0 节点预分配 2M 大页
```

#### 迁移

```bash
# 在线迁移（共享存储）
virsh migrate --live centos7 qemu+ssh://dest-host/system

# 在线迁移（非共享存储，同时迁移磁盘）
virsh migrate --live --copy-storage-all centos7 qemu+ssh://dest-host/system

# 在线迁移（增量拷贝）
virsh migrate --live --copy-storage-inc centos7 qemu+ssh://dest-host/system

# 离线迁移
virsh migrate --offline centos7 qemu+ssh://dest-host/system

# 设置迁移带宽上限
virsh migrate-setspeed centos7 500        # 500 MiB/s
virsh migrate-getspeed centos7            # 查看当前带宽

# 迁移后可选操作
virsh migrate-compcache centos7 --size 1G  # 设置压缩缓存
```

#### 密钥与加密

```bash
# 创建 secret（如 Ceph 密钥、iSCSI CHAP 密码等）
virsh secret-define --file secret.xml

# 列出所有 secret
virsh secret-list

# 设置 secret 值
virsh secret-set-value <uuid> --interactive  # 交互式输入
echo -n "mypassword" | virsh secret-set-value <uuid> --base64 $(base64)

# 查看 secret
virsh secret-get-value <uuid>

# 删除 secret
virsh secret-undefine <uuid>
```

#### 事件监控

```bash
# 监听 VM 生命周期事件（阻塞式）
virsh event centos7 --all                 # 监听所有事件
virsh event centos7 --event lifecycle     # 仅生命周期事件
virsh event centos7 --event reboot        # 仅重启事件
virsh event --all --loop                  # 监听所有 VM 的所有事件（循环）

# 事件类型：lifecycle, reboot, rtc-change, watchdog,
#           io-error, graphics, block-job, disk-change,
#           tray-change, device-added, device-removed, migration-iteration
```

#### 高级磁盘操作

```bash
# 块设备复制（block copy）
virsh blockcopy centos7 vda /data/new-disk.qcow2 --wait --finish

# 块设备提交（block commit，合并快照链）
virsh blockcommit centos7 vda --base /base.qcow2 --top /snap1.qcow2

# 块设备拉取（block pull，扁平化）
virsh blockpull centos7 vda --base /base.qcow2

# 块设备重设大小
virsh blockresize centos7 vda 50G

# 重命名镜像
virsh vol-rename old.qcow2 new.qcow2 --pool default

# 上传/下载卷
virsh vol-upload vol.qcow2 /local/file.qcow2 --pool default
virsh vol-download vol.qcow2 /local/file.qcow2 --pool default

# 擦除卷
virsh vol-wipe vol.qcow2 --pool default
```

#### 高级网络操作

```bash
# 查看网桥信息
virsh iface-list --all                    # 所有物理接口
virsh iface-info eth0                      # 接口详情
virsh iface-bridge eth0 br0 --no-stp      # 将 eth0 加入网桥 br0

# 查看 VM 网卡 MAC 与宿主机接口映射
virsh domiflist centos7
virsh domifaddr centos7                   # 查询 VM 内 IP 地址（需 qemu-guest-agent）
virsh domifaddr centos7 --source agent    # 从 agent 获取
virsh domifaddr centos7 --source arp      # 从 ARP 表获取

# 修改网卡 MAC
virsh edit centos7                        # 修改 XML 中 <mac address='...'/>

# 更改网卡 MTU
virsh domiftune centos7 vnet0 --mtu 9000 --live --config
```

#### 元数据与自定义属性

```bash
# 查看/修改 metadata（自定义标签）
virsh metadata centos7 --uri http://myapp.com/ns --current
virsh metadata centos7 --uri http://myapp.com/ns --config --set '<tag>value</tag>'

# 查看/修改 title 和 description
virsh desc centos7                        # 查看描述
virsh desc centos7 --config --new-desc "生产环境 Web 服务器"  # 设置描述
virsh desc centos7 --title                # 查看标题
virsh metadata centos7 --title --live --config   # 查看/设置标题
```

#### 客户机代理（qemu-guest-agent）

```bash
# 前提：VM 内安装了 qemu-guest-agent
virsh qemu-agent-command centos7 '{"execute":"guest-info"}'           # agent 信息
virsh qemu-agent-command centos7 '{"execute":"guest-network-get-interfaces"}'  # 网络信息
virsh qemu-agent-command centos7 '{"execute":"guest-get-osinfo"}'     # 操作系统信息
virsh qemu-agent-command centos7 '{"execute":"guest-get-time"}'       # VM 时间
virsh qemu-agent-command centos7 '{"execute":"guest-get-fsinfo"}'     # 文件系统信息
virsh qemu-agent-command centos7 '{"execute":"guest-exec","arguments":{"path":"/bin/ls","arg":["-la"]}}'  # 执行命令
virsh qemu-agent-command centos7 '{"execute":"guest-exec-status","arguments":{"pid":123}}'  # 查看结果
virsh qemu-agent-command centos7 '{"execute":"guest-shutdown"}'       # 优雅关机
virsh qemu-agent-command centos7 '{"execute":"guest-suspend-disk"}'   # 挂起到磁盘
virsh qemu-agent-command centos7 '{"execute":"guest-suspend-ram"}'    # 挂起到内存
virsh qemu-agent-command centos7 '{"execute":"guest-set-user-password","arguments":{"username":"root","password":"newpass"}}'  # 重置密码
```

#### 其他罕见命令

```bash
# 串口操作
virsh ttyconsole centos7                  # 查看串口设备路径

# SCSI 控制器热插拔
virsh attach-device centos7 scsi.xml --live
virsh detach-device centos7 scsi.xml --live

# 更改启动设备
virsh domblklist centos7
virsh destroy centos7 && virsh edit centos7  # 修改 <boot dev='...'/> 顺序

# 查看 VM 的 cgroup 信息
virsh schedinfo centos7                   # CPU 调度器参数
virsh schedinfo centos7 --set cpu_shares=2048  # 设置 CPU 权重

# 更改 VM 的 blkio 权重
virsh blkiotune centos7 --weight 500 --live

# 发送 NMI（Non-Maskable Interrupt）给 VM（用于内核调试）
virsh inject-nmi centos7

# 发送 ACPI 关机信号
virsh send-key centos7 --codeset linux KEY_POWER

# 重新编号
virsh domrename centos7 centos7-new       # 重命名 VM（需关机）

# 转换 VM 为模板
virsh destroy centos7
virsh dumpxml centos7 > template.xml       # 导出 XML 作为模板
```

---

### 11.4 命令分类速查索引

| 场景 | 常用命令 | 不常用命令 |
|------|----------|------------|
| **启动/关机** | `start`, `shutdown`, `destroy`, `reboot` | `reset`, `inject-nmi`, `send-key` |
| **查看状态** | `list --all`, `dominfo`, `domstate` | `domstats`, `domtime`, `domjobinfo` |
| **控制台** | `console`, `vncdisplay` | `ttyconsole` |
| **配置管理** | `dumpxml`, `edit`, `define` | `metadata`, `desc`, `domrename` |
| **资源调整** | `setvcpus`, `setmem`, `attach-disk` | `vcpupin`, `emulatorpin`, `numatune`, `schedinfo` |
| **快照** | `snapshot-create-as`, `snapshot-list`, `snapshot-revert` | `snapshot-current`, `snapshot-parent` |
| **磁盘** | `qemu-img create/info/convert` | `blockcopy`, `blockcommit`, `blockpull`, `blockresize` |
| **网络** | `net-list`, `net-dhcp-leases` | `domifaddr`, `domiftune`, `iface-bridge` |
| **存储池** | `pool-list`, `vol-list` | `vol-upload`, `vol-download`, `vol-wipe` |
| **迁移** | — | `migrate`, `migrate-setspeed`, `migrate-compcache` |
| **底层调试** | — | `qemu-monitor-command`, `qemu-agent-command` |
| **事件** | — | `virsh event` |
| **密钥** | — | `secret-define`, `secret-set-value` |

---

## 参考资源

- [KVM 官方文档](https://www.linux-kvm.org/page/Documents)
- [libvirt 文档](https://libvirt.org/docs.html)
- [QEMU 文档](https://www.qemu.org/docs/master/)
- [virt-install 手册](https://linux.die.net/man/1/virt-install)
- [Red Hat 虚拟化指南](https://access.redhat.com/documentation/zh-cn/red_hat_enterprise_linux/8/html/configuring_and_managing_virtualization/)