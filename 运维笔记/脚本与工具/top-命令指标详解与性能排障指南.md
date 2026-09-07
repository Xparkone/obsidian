# `top` 命令指标详解与性能排障指南

## 1. 先记住怎么看

`top` 适合回答三个问题：

1. **机器是否有总体压力**：看 `load average`、CPU 各状态和内存/Swap。
2. **压力由谁造成**：看进程表中的 `%CPU`、`%MEM`、`S`、`TIME+` 和进程数量。
3. **压力属于哪一种资源**：CPU 忙、磁盘 I/O 等待、内存不足、虚拟机被宿主机抢占，还是线程/进程状态异常。

不要只盯着一个百分比。一个比较稳妥的阅读顺序是：

```text
load average → CPU 状态 → 内存与 Swap → 进程排序 → 单进程线程/文件/网络证据
```

`top` 是实时快照工具，默认只反映最近一个采样周期和当前状态。要判断趋势，应连续观察，或配合 `vmstat`、`pidstat`、`iostat`、Prometheus/Grafana 等历史数据。

## 2. 启动方式与常用参数

### 2.1 交互式查看

```bash
top
```

常用参数（Linux `procps-ng` 版本）：

| 命令 | 作用 |
|---|---|
| `top -d 1` | 每 1 秒刷新一次 |
| `top -p 1234` | 只看 PID 1234；多个 PID 可写成 `-p 1234,5678` |
| `top -u app` | 只看用户 `app` 的进程 |
| `top -H` | 显示线程，而不是只显示进程 |
| `top -c` | 在进程名和完整命令行之间切换 |
| `top -b -n 1` | 批处理模式输出一次，适合脚本采集 |
| `top -b -d 2 -n 5` | 每 2 秒采集一次，共 5 次 |
| `top -o %CPU` | 启动时按 CPU 使用率排序（不同发行版支持情况可能不同） |

批处理输出示例：

```bash
LC_ALL=C top -b -d 2 -n 5 > /tmp/top-$(date +%Y%m%d%H%M%S).log
```

`/tmp` 中的采集文件可能包含命令行参数、用户名和进程信息。共享前先确认没有密码、Token 或其他敏感参数。

### 2.2 运行中的快捷键

在 `top` 窗口中按键后通常立即生效：

| 按键 | 作用 |
|---|---|
| `P` | 按 `%CPU` 降序排列 |
| `M` | 按 `%MEM` 降序排列 |
| `T` | 按累计运行时间 `TIME+` 排列 |
| `1` | 展开/收起每个逻辑 CPU 的统计 |
| `H` | 切换进程/线程视图 |
| `c` | 切换显示完整命令行 |
| `f` | 选择或隐藏列 |
| `E` | 循环切换内存显示单位 |
| `e` | 循环切换进程内存单位 |
| `r` | 调整进程 nice 值（需要权限，谨慎使用） |
| `k` | 发送信号结束进程（需要权限，谨慎使用） |
| `q` | 退出 |
| `?` 或 `h` | 查看帮助 |

`r` 和 `k` 会改变运行中进程，排障采集时只读查看即可，不要因为误触发而修改优先级或终止进程。

### 2.3 macOS 的差异

macOS 自带的 `top` 与 Linux `procps-ng` 不是同一个实现，参数和列名不同。例如：

```bash
top -l 1 -s 2
top -o cpu -l 1
```

macOS 顶部通常显示 `Load Avg`、`PhysMem`、`VM`、`Networks`、`Disks`，进程列也可能包含 `%CPU`、`MEM`、`#TH`、`STATE`、`FAULTS`、`CMPRS` 等。本文优先解释 Linux 常见输出；在 macOS 上应以 `man top` 和本机实际列名为准，不能直接套用 Linux 的 `buff/cache`、`wa`、`st` 解释。

## 3. 顶部摘要区：逐项解释

Linux `top` 常见输出如下（不同版本可能略有增减）：

```text
top - 10:21:33 up 12 days,  3:14,  2 users,  load average: 1.20, 0.85, 0.60
Tasks: 245 total,   2 running, 242 sleeping,   0 stopped,   1 zombie
%Cpu(s): 18.2 us,  4.1 sy,  0.0 ni, 76.5 id,  0.8 wa,  0.0 hi,  0.4 si,  0.0 st
MiB Mem :  15884.0 total,   1024.0 free,   8200.0 used,   6660.0 buff/cache
MiB Swap:   4096.0 total,   3584.0 free,    512.0 used.   6900.0 avail Mem
```

### 3.1 第一行：时间、运行时长、用户、负载

| 字段 | 含义 | 怎么看 |
|---|---|---|
| `10:21:33` | 当前系统时间 | 用于和日志、监控事件对齐 |
| `up 12 days, 3:14` | 系统已运行时间 | 只能说明本次启动持续时间，不代表服务持续健康 |
| `2 users` | 当前登录会话数量 | 不是进程数，也不等于活跃业务用户 |
| `load average: 1.20, 0.85, 0.60` | 最近 1、5、15 分钟的平均负载 | 需要结合逻辑 CPU 数量和任务状态判断 |

#### `load average` 到底表示什么

Linux 的 load average 统计一段时间内处于可运行状态（通常是 `R`）或不可中断睡眠状态（通常是 `D`，多与 I/O 有关）的任务数量的指数平均值。它**不只是 CPU 使用率**：磁盘、NFS、块设备等 I/O 卡住时，即使 CPU 很空，负载也可能很高。

判断步骤：

```bash
nproc                 # 逻辑 CPU 数量
uptime                # 快速查看 load average
cat /proc/loadavg     # 原始负载数据，前 3 个值为 1/5/15 分钟
```

- 单核机器长期 `load average` 接近 1，说明可运行/等待任务大致占满一个执行位。
- 8 逻辑 CPU 的机器，负载 4 通常不等于“100% 满载”；负载 8 左右才接近每个执行位都有任务，仍需看 CPU 和 `D` 状态。
- `1 分钟 > 5 分钟 > 15 分钟` 通常表示压力正在上升；反过来通常表示压力在缓解。
- 负载高且 `%Cpu` 的 `wa`、进程 `D` 状态明显，优先查 I/O；负载高且 `us/sy` 高、`R` 任务多，优先查 CPU/并发。

### 3.2 第二行：Tasks（任务统计）

| 字段 | 含义 | 风险提示 |
|---|---|---|
| `total` | 当前可见任务总数，通常指进程 | 进程数持续增长可能是泄漏、重试风暴或 fork 异常 |
| `running` | 当前处于运行队列或正在运行的任务 | 持续接近 CPU 数量且 CPU 很高，说明 CPU 竞争明显 |
| `sleeping` | 睡眠等待事件的任务 | 普通服务有大量 sleeping 很常见，不等于故障 |
| `stopped` | 被暂停（如收到 `SIGSTOP`）的任务 | 持续增加需检查调试操作或信号处理 |
| `zombie` | 已退出但父进程尚未回收的僵尸进程 | 少量短暂出现可接受；持续增加说明父进程未处理 `wait()` |

僵尸进程不再消耗用户态 CPU 和常规内存，但会占用进程表项。定位方式：

```bash
ps -eo pid,ppid,stat,etime,cmd | awk '$3 ~ /Z/ {print}'
ps -p <PPID> -o pid,ppid,stat,cmd
```

不要直接杀僵尸本身；应修复或重启其父进程，并先确认服务治理方式。

### 3.3 第三行：CPU 状态

Linux 常见字段：

| 字段 | 全称 | 含义 |
|---|---|---|
| `us` | user | 用户态程序消耗的 CPU 时间，如应用计算、脚本、JVM 用户代码 |
| `sy` | system | 内核态消耗的 CPU 时间，如系统调用、网络协议栈、文件系统 |
| `ni` | nice | 以调整过 nice 值运行的用户态任务消耗的时间 |
| `id` | idle | CPU 空闲时间 |
| `wa` | I/O wait | CPU 空闲但等待块设备等 I/O 完成的时间 |
| `hi` | hardware interrupt | 处理硬件中断的时间 |
| `si` | software interrupt | 处理软件中断的时间 |
| `st` | steal | 虚拟机被宿主机“偷走”的时间；常见于超卖严重的虚拟化环境 |

通常可以近似认为：

```text
us + sy + ni + id + wa + hi + si + st ≈ 100%
```

解释重点：

- `us` 高：应用本身计算密集，按 `%CPU` 找进程，再看线程、请求和算法。
- `sy` 高：系统调用、网络、文件系统、中断或内核路径压力，继续看 `pidstat -w`、`sar -n DEV`、`iostat`、软中断和连接数。
- `wa` 高：不能简单说“CPU 不够”，应确认磁盘延迟、队列、NFS、云盘限速或容器存储。
- `hi/si` 高：可能是网卡/磁盘中断、网络包量、软中断处理压力。
- `st` 高：应用未必有问题，可能被云主机宿主机或同物理机其他租户抢占；需要查看实例级监控或更换规格验证。

按 `1` 可展开每个逻辑 CPU。单个核心 100% 而总体只有 12.5%，仍可能是单线程程序的瓶颈。

### 3.4 第四、五行：内存与 Swap

#### `MiB Mem` 字段

| 字段 | 含义 |
|---|---|
| `total` | 操作系统可管理的物理内存总量（可能已扣除保留区域） |
| `free` | 当前完全未使用的内存 |
| `used` | 版本相关的“已使用”统计；不要单独用它判断内存不足 |
| `buff/cache` | 内核块设备缓冲和文件页缓存等可回收内存 |
| `avail Mem` | 估算在不触发严重 Swap 的情况下，应用还可使用的内存；Linux 判断余量优先看它 |

不同 `procps` 版本对 `used` 的计算方式可能不同。更稳妥的核对命令：

```bash
free -h
grep -E 'MemTotal|MemFree|MemAvailable|Buffers|Cached|SReclaimable|Shmem|SwapTotal|SwapFree' /proc/meminfo
```

经验判断（仅作排障起点，不是通用告警阈值）：

- `avail Mem` 持续低于总内存的 10%～15%，同时发生回收、Swap 或 OOM，才更像内存压力。
- `buff/cache` 很高本身通常不是故障，缓存可在需要时回收。
- `free` 很低但 `avail Mem` 充足，通常是正常的缓存利用。

#### `MiB Swap` 字段

| 字段 | 含义 |
|---|---|
| `total` | Swap 总量 |
| `free` | 尚未使用的 Swap |
| `used` | 已使用的 Swap |

Swap 已使用不一定代表当前正在发生严重换页；要看换入换出速率和应用延迟：

```bash
vmstat 1 5
# 重点看 si（swap in）、so（swap out）是否持续非零
```

持续 `si/so`、`wa` 升高并伴随业务变慢，优先检查内存工作集、容器 limit、缓存和进程泄漏，而不是盲目扩大 Swap。Linux 还可检查：

```bash
cat /proc/sys/vm/swappiness
swapon --show
```

## 4. 进程表：每一个常见列是什么意思

Linux 常见进程表：

```text
  PID USER      PR  NI    VIRT    RES    SHR S  %CPU %MEM     TIME+ COMMAND
 1234 app       20   0  4120m  820m  120m R  185.0  5.2   12:31.44 java
```

### 4.1 身份、调度与地址空间

| 列 | 含义 | 如何使用 |
|---|---|---|
| `PID` | 进程 ID | 后续用 `ps`、`strace`、`lsof`、`jstack` 等定位目标 |
| `USER` | 进程所属用户 | 判断权限边界、服务归属和异常账号 |
| `PR` | 内核调度优先级显示值 | 普通进程常见为 20；实时任务会不同 |
| `NI` | nice 值，范围通常为 -20～19 | 越小通常优先级越高；修改需要权限且可能影响其他任务 |
| `VIRT` | 虚拟地址空间总量 | 包含代码、共享库、映射文件、保留地址和可能未驻留页面；不等于实际占用内存 |
| `RES` | 当前驻留在物理内存的非 Swap 部分 | 估算单进程实际物理内存占用时比 `VIRT` 有用，但共享页会重复计数 |
| `SHR` | `RES` 中可能与其他进程共享的部分 | 不能简单从 `RES` 减去 `SHR` 得到精确私有内存 |

`VIRT` 很大并不自动表示内存泄漏。需要结合 `RES`/`PSS`、增长趋势和应用自身堆指标判断：

```bash
grep -E 'VmPeak|VmSize|VmRSS|RssAnon|RssFile|VmSwap' /proc/<PID>/status
cat /proc/<PID>/smaps_rollup 2>/dev/null
```

### 4.2 状态、资源比例和累计时间

| 列 | 含义 | 典型状态/解释 |
|---|---|---|
| `S` | 进程状态 | `R` 运行/就绪，`S` 可中断睡眠，`D` 不可中断睡眠，`T` 停止，`Z` 僵尸，`I` 空闲内核线程（版本相关） |
| `%CPU` | 最近采样周期内的 CPU 使用率 | 多核系统单进程可能超过 100%；通常 100% 约等于占满一个逻辑 CPU |
| `%MEM` | 进程 `RES` 占物理内存的比例 | 受共享页和采样影响，适合排序，不等于精确服务内存 |
| `TIME+` | 进程累计消耗的 CPU 时间 | 不是墙上时间；长期运行服务自然可能很大 |
| `COMMAND` | 进程名或命令行 | 按 `c` 查看完整参数；参数中可能出现敏感信息 |

一些发行版还显示 `CODE`、`DATA`、`nTH`、`P`、`TIME`、`SWAP` 等列。先按 `f` 查看本机定义，不要假设所有列在每个系统都存在。

### 4.3 线程视图

进程总体 `%CPU` 正常，但应用响应变慢时，可能只有一个线程阻塞或打满 CPU：

```bash
top -H -p <PID>
ps -L -p <PID> -o pid,tid,psr,stat,pcpu,pmem,time,comm
```

`TID` 是线程 ID，`psr` 是最近运行所在的 CPU。Java、Go、Python、数据库和代理程序都可能需要线程级定位，不能只看进程总量。

## 5. 一套可复用的阅读流程

### 第一步：确认采样范围和机器规模

```bash
date
hostname
nproc
uptime
top -b -n 1 | sed -n '1,8p'
```

记录主机、时间、逻辑 CPU 数量、运行时长和第一屏摘要。多次采样至少持续 30～60 秒，避免把瞬时尖峰当成持续故障。

### 第二步：先判断是 CPU、I/O 还是内存

| 现象 | 更可能的方向 | 下一步 |
|---|---|---|
| `us`/`sy` 高，`R` 任务多，`wa` 低 | CPU 竞争或计算密集 | 按 `P`，再用 `top -H -p`、`pidstat -u` 定位 |
| `load average` 高，`wa` 高，`D` 任务多 | 存储/NFS/块设备等待 | `vmstat 1`、`iostat -xz 1`、检查磁盘和挂载 |
| `avail Mem` 低，Swap 持续换入换出 | 内存压力 | `free -h`、`vmstat`、`/proc/<PID>/status`、OOM 日志 |
| `st` 高，应用 CPU 并不高 | 虚拟机被宿主机抢占 | 查看云监控、实例规格和同节点资源竞争 |
| 总体 CPU 不高，但单个核心 100% | 单线程瓶颈 | 按 `1` 看每核，`top -H -p` 看线程 |

### 第三步：按资源排序定位候选进程

```bash
top -b -n 1 -o %CPU | sed -n '1,25p'
top -b -n 1 -o %MEM | sed -n '1,25p'
ps -eo pid,ppid,user,stat,pcpu,pmem,rss,vsz,etime,cmd --sort=-pcpu | head -n 20
ps -eo pid,ppid,user,stat,pcpu,pmem,rss,vsz,etime,cmd --sort=-pmem | head -n 20
```

`top -o` 是实现相关参数，若不支持就进入交互界面按 `P`/`M`。命令行中的 `--sort=-pcpu` 也可能因 BSD/GNU `ps` 差异而不同，应先用 `ps --help` 或 `man ps` 确认。

### 第四步：沿 PID 补充证据

```bash
PID=1234
ps -p "$PID" -o pid,ppid,user,stat,pcpu,pmem,rss,vsz,etime,lstart,cmd
readlink /proc/"$PID"/exe
cat /proc/"$PID"/limits
lsof -p "$PID" | sed -n '1,80p'
```

根据方向继续：

```bash
pidstat -p "$PID" -u -r -d -w 1 5   # CPU、缺页、I/O、上下文切换
iostat -xz 1 5                      # 设备利用率、等待和队列
vmstat 1 5                          # 运行队列、内存、换页、I/O、上下文切换
```

这些命令只读采集，但输出中可能包含路径、用户名和命令行，发送前要脱敏。

## 6. 常见场景与判断方法

### 6.1 CPU 使用率高

现象：`us` 或 `sy` 持续高，某些进程 `%CPU` 排在前面。

```bash
top -H -p <PID>
pidstat -p <PID> -t -u 1 5
```

判断要点：

- 先区分用户态计算（`us`）和内核态/系统调用（`sy`）。
- 多核机器单进程 200% 约表示占用两个逻辑 CPU，不是百分之二百的整机容量。
- `TIME+` 大只说明累计消耗多，不能证明当前正在高 CPU；以连续采样 `%CPU` 为准。
- 检查是否在备份、压缩、GC、批处理、加密、正则匹配或重试循环。

### 6.2 Load 高但 CPU 使用率低

常见原因是不可中断 I/O 等待：

```bash
top -H
ps -eo pid,ppid,stat,wchan:32,pcpu,pmem,cmd | awk '$3 ~ /D/ {print}'
iostat -xz 1 5
```

重点关注 `D` 状态数量、`await`、`%util`、设备队列、NFS/网络文件系统和云盘限速。`kill -9` 未必能立即结束处于内核不可中断路径的进程，需先解决底层 I/O 阻塞。

### 6.3 内存看似快满

先看 `avail Mem`，再看 Swap 和进程 RSS：

```bash
free -h
vmstat 1 5
ps -eo pid,user,stat,rss,pmem,cmd --sort=-rss | head -n 20
```

如果 `buff/cache` 大而 `avail Mem` 仍充足，通常是正常缓存；如果 `avail Mem` 低、Swap 活跃或内核日志出现 OOM，才需要沿进程、容器 limit、页缓存和应用堆继续查。

### 6.4 Swap 已使用但业务正常

内核可能把长期不活跃页面换出，Swap 占用不会自动归零。关注的是 `vmstat` 的 `si/so` 是否持续、延迟是否上升、`avail Mem` 是否紧张。不要只因为 `Swap used > 0` 就重启服务或清空 Swap。

### 6.5 `%CPU` 低但服务变慢

可能是锁等待、线程池耗尽、网络延迟、磁盘延迟、GC、外部依赖或连接数耗尽。`top` 只能排除一部分主机资源问题，应继续查看：

```bash
pidstat -p <PID> -w -d 1 5
ss -s
cat /proc/<PID>/status | grep -E 'Threads|State|voluntary_ctxt_switches|nonvoluntary_ctxt_switches'
```

并结合应用日志、请求延迟、数据库慢查询和队列指标，不要把“CPU 不高”当成服务健康证明。

### 6.6 僵尸进程持续增加

```bash
ps -eo pid,ppid,stat,cmd | awk '$3 ~ /Z/ {print}'
```

记录僵尸的父 PID，检查父进程是否正确回收子进程。生产环境不要直接对未知服务执行 `kill -9`；先确认是否由 systemd、容器运行时、Deployment 或其他进程管理器托管。

## 7. 容器和 Kubernetes 中的注意事项

- 在容器内执行 `top`，看到的进程和 CPU/内存视图受 PID namespace、cgroup 及镜像工具影响；不一定等同于宿主机全局视图。
- 宿主机 `top` 能看到容器进程，但要用容器运行时、Pod、Namespace 和 cgroup 信息映射回工作负载。
- 容器 CPU 限额下，进程显示的 100% 常接近一个宿主机逻辑 CPU；如果容器只分配 `500m`，应用在配额内的“满载”与宿主机整体 100% 不是同一概念。
- Kubernetes 资源排障要同时核对 `requests/limits`、cgroup throttling、Pod 重启、节点压力和应用指标。可用：

```bash
kubectl top pod -A
kubectl top node
kubectl describe pod <pod> -n <namespace>
kubectl get pod <pod> -n <namespace> -o wide
```

`kubectl top` 依赖 Metrics Server，数据可能有延迟；它与节点上 `top` 的采样口径不同，不能机械比较数值。

## 8. 建议的阈值与证据边界

下面是排障时的经验起点，不是适用于所有业务的告警规则：

| 指标 | 需要关注的起点 | 不能单独推出的结论 |
|---|---|---|
| `load average / nproc` | 持续接近或超过 1 | 不能单独证明 CPU 满载，可能是 I/O 等待 |
| `us + sy` | 持续超过约 80% | 不能单独证明某个进程是根因 |
| `wa` | 持续超过约 10% | 不能单独确定是哪块设备或哪类存储 |
| `st` | 持续超过约 5% | 不能单独证明云厂商故障 |
| `avail Mem` | 低于总内存约 10%～15% | 不能单独证明已经 OOM |
| Swap `si/so` | 持续非零且伴随延迟/`wa` | `Swap used` 非零本身不等于故障 |
| `zombie` | 数量持续增长 | 单个短暂僵尸不一定影响业务 |

最终结论应包含时间窗口、重复采样、受影响进程、业务现象和至少一项独立证据（日志、I/O 统计、应用指标、内核事件或容器指标）。

## 9. 最小只读命令集

下面的命令适合在没有监控面板时快速留证：

```bash
# 主机规模与总体状态
date; hostname; nproc; uptime
top -b -n 1 | sed -n '1,8p'

# CPU / 进程
top -b -d 2 -n 5 -o %CPU | sed -n '1,35p'
ps -eo pid,ppid,user,stat,pcpu,pmem,rss,vsz,etime,cmd --sort=-pcpu | head -n 20

# 内存 / Swap
free -h
vmstat 1 5
ps -eo pid,user,stat,rss,pmem,cmd --sort=-rss | head -n 20

# I/O（若已安装 sysstat）
iostat -xz 1 5

# 指定 PID
PID=<pid>
ps -p "$PID" -o pid,ppid,user,stat,pcpu,pmem,rss,vsz,etime,cmd
top -H -p "$PID"
```

`<pid>` 只是占位符，执行前替换为已确认的数字 PID。涉及 `kill`、`renice`、清理 Swap、重启服务或修改 cgroup 的命令不属于只读命令集，需要单独评审和授权。

## 10. 记录模板

排障记录至少保留以下信息：

```text
时间窗口：
主机 / 容器 / Pod：
逻辑 CPU 数：
load average（1/5/15）：
CPU（us/sy/ni/id/wa/hi/si/st）：
内存（total/avail/buff-cache）：
Swap（total/used，si/so）：
Top CPU 进程及 PID：
Top 内存进程及 PID：
R/D/Z 状态数量：
独立证据（日志、iostat、应用指标等）：
已确认事实：
基于证据的判断：
尚未验证的可能性：
下一步：
```

## 11. 结论

`top` 的核心不是“找一个最高的百分比”，而是把系统压力拆成：

```text
负载是否变高 → CPU 是否真正执行 → 是否在等待 I/O → 内存是否有余量
→ 哪个进程/线程对应 → 用独立工具确认根因
```

记住三个边界：

1. `load average` 不是 CPU 百分比，可能包含 I/O 等待。
2. `VIRT` 不是实际物理内存，Linux 内存余量优先看 `avail Mem` 和 Swap 活动。
3. 一次 `top` 快照只能提供线索，不能替代趋势、应用指标和业务请求验证。
