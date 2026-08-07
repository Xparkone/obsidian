# tcpdump 使用与排障指南（Linux）

## 1. 文档概述

### 解决什么问题

本指南说明如何用 **tcpdump** 在 Linux 上抓取网络报文、写 BPF（Berkeley Packet Filter，伯克利包过滤）表达式，以及如何把抓包结果用于排障：端口不通、三次握手失败、DNS 异常、丢包/重传粗判、HTTP/HTTPS 边界判断等。目标是让你能独立完成「选对网卡 → 写准过滤器 → 抓到文件 → 对照现象下结论」。

### 适合哪些读者

- 有 Linux 与基础网络知识（IP、端口、TCP/UDP、路由）的运维、SRE、后端开发
- 需要在服务器上快速验证「包有没有到、握手有没有成、DNS 有没有答」
- 需要一份可检索、可照着敲的实操手册（非工具科普文）

### 阅读后能获得什么

- 理解 tcpdump 与 Wireshark / tshark 的分工，以及适用/不适用场景
- 能在 Debian/Ubuntu、RHEL 系安装并正确处理权限（root / `CAP_NET_RAW`）
- 掌握常用选项（`-i`、`-n`/`-nn`、`-c`、`-w`/`-r`、`-v`、`-tttt` 等）与 BPF 过滤写法
- 能按方法论排查：本机监听与路由 → 抓包验证到达 → 区分客户端 / 服务端 / 防火墙
- 知道常见坑（抓错网卡、容器网桥、混杂模式、缓冲丢包、文件过大）与安全边界

### 版本与范围说明

- 本文以 **Linux 上的 tcpdump + libpcap** 为主；命令在 Ubuntu / Debian、RHEL / AlmaLinux / Rocky 等发行版上通用，包名略有差异
- 过滤器语法遵循 **pcap-filter(7)**（与 Wireshark 显示过滤器不同，勿混用）
- 图形分析以 **Wireshark** 打开 `.pcap` / `.pcapng` 为主；CLI 深度解析可选用 **tshark**
- macOS 也有 tcpdump，但网卡命名与权限模型不同，本文示例以 Linux 为准
- **【需要确认】** 你环境中的 tcpdump / libpcap 具体小版本（`tcpdump --version`）；个别选项（如 `--immediate-mode`）依赖较新版本

> **核心结论先记住：** tcpdump 回答的是「**链路上有没有这包、长什么样**」，不直接回答「应用为什么报错」。排障时先确认监听与路由，再用最小过滤器抓包，把问题切成：包没到 / 到了没回 / 回了但握手失败 / 应用层协议异常。

---

## 2. 前置条件

### 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Linux（推荐 Ubuntu / Debian 或 RHEL 系） |
| 权限 | 能 `sudo`，或具备抓包所需 capability（见 3.4） |
| 网络 | 知道业务走哪块网卡、目标 IP 与端口 |
| 磁盘 | 写文件抓包时，目标分区有足够空间（大流量下 `.pcap` 增长极快） |

### 软件及版本

- `tcpdump`（依赖 **libpcap**）
- 可选：`wireshark` / `tshark`（离线分析）、`ss` / `ip`（排障配合）、`dig`（DNS 场景）

### 必备基础知识

- 知道 IP、端口、TCP 与 UDP 的基本区别
- 会看本机监听：`ss -lntup` 或 `netstat -lntup`
- 会看路由：`ip route` / `ip addr`
- 理解「本机防火墙（如 UFW）」「云安全组」「容器网桥」是不同层次的过滤点

### 动手前建议确认

- **【需要确认】** 业务流量走哪块网卡（`eth0`、`ens*`、`bond0`、`docker0`、CNI 网桥等）
- **【需要确认】** 抓包是在客户端、服务端，还是中间机（跳板 / 网关）
- **【需要确认】** 是否有云安全组、UFW、iptables/nftables、WAF 等额外过滤
- **【需要确认】** 是否允许在该环境抓包（合规、是否含敏感明文）

---

## 3. 核心概念

**先记住结论：** tcpdump 通过 libpcap 从网卡（或隧道接口）复制报文，用 BPF 在内核侧尽早过滤，再打印摘要或写入 pcap 文件。它擅长「证明包在不在」；协议细节、会话重组、TLS 解密更适合 Wireshark。

### 3.1 tcpdump 是什么

**tcpdump** 是命令行抓包工具：在指定接口上捕获匹配过滤表达式的报文，输出一行摘要，或用 `-w` 写成二进制捕获文件。

典型能力：

- 按接口实时抓包、限制包数、写文件 / 读文件
- 用 BPF 表达式精确缩小范围（主机、端口、协议、方向）
- 输出 TCP 标志、序号粗信息、DNS 等常见协议摘要（加 `-v` 更详细）
- 与 Wireshark 互通：`-w` 的文件可直接用 GUI 打开

它**不是**：

- 完整的协议分析 IDE（那是 Wireshark）
- 应用层 APM / 链路追踪工具
- 可以「解密任意 HTTPS」的银弹（无会话密钥或明文旁路时，HTTPS 载荷不可读）

### 3.2 与 Wireshark / tshark 的关系

| 工具 | 定位 | 常见用法 |
|------|------|----------|
| **tcpdump** | 服务器上轻量抓包、写 pcap、快速确认包是否到达 | `tcpdump -i eth0 -nn -w /tmp/a.pcap 'port 443'` |
| **Wireshark** | 桌面 GUI：解码、过滤、跟踪流、统计、导出对象 | 打开 `.pcap`，Follow TCP Stream，看 Expert Info |
| **tshark** | Wireshark 的 CLI 版，适合脚本化解码与统计 | 服务器上对已有 pcap 做字段提取 |

分工建议：

1. **在出问题的机器上**用 tcpdump（权限、网卡、路径都对）抓最小集合
2. **拷到本机**用 Wireshark 看握手、重传、HTTP 明文、DNS 应答
3. 需要批量统计时用 tshark，不必在生产机装完整 GUI

> 注意：Wireshark 的 **display filter**（如 `tcp.flags.syn==1`）与 tcpdump 的 **BPF capture filter**（如 `tcp[tcpflags] & tcp-syn != 0`）语法不同。抓包阶段用 BPF；打开文件后再用 display filter。

### 3.3 适用场景与局限

**适合：**

- 验证某 IP/端口的包是否到达本机某网卡
- 判断 TCP 三次握手是否完成、是否被 RST、是否只有 SYN 无 SYN-ACK
- 排查 DNS 请求发没发出、应答有没有回来
- 对 HTTP 明文看请求行 / 状态码（在可接受合规前提下）
- 保存证据：`-w` 文件给同事或厂商分析

**不适合或不够用：**

- 从加密 HTTPS 中直接读业务 JSON（只能看 TCP/TLS 握手与外层元数据，除非有密钥）
- 超高 PPS 下不做缓冲调优时的无损全量抓取（易丢，见第 10 节）
- 跨多跳路径的端到端可视化（需多点抓包或专门网络探针）
- 替代 `ss`、应用日志、追踪系统做根因分析——抓包是证据链的一环

### 3.4 权限：root 与 CAP_NET_RAW

抓包需要访问网络接口的原始套接字，通常需要：

- **root / sudo**（最常见、最省事），或
- **capability**：至少 `CAP_NET_RAW`（常还配合 `CAP_NET_ADMIN`，取决于发行版与 libpcap 行为）

查看当前是否有相关 capability（示例）：

```bash
# 查看 tcpdump 二进制是否带 capability
getcap $(command -v tcpdump)

# 临时用 root 抓（推荐排查时用这个，简单明确）
sudo tcpdump -i any -nn -c 1
```

非 root 授予示例（**按需、最小权限；生产慎用**）：

```bash
# 【需要确认】你的发行版是否允许、安全策略是否禁止 setcap
sudo setcap 'cap_net_raw,cap_net_admin=eip' $(command -v tcpdump)

# 用完建议收回
sudo setcap -r $(command -v tcpdump)
```

无权限时的典型报错类似：`You don't have permission to capture on that device` 或 `socket: Operation not permitted`。

### 3.5 关键术语

| 术语 | 一句话解释 |
|------|------------|
| 网卡 / 接口（interface） | 抓包附着点，如 `eth0`、`ens192`；`any` 表示伪接口汇总（行为见后文） |
| BPF / capture filter | 内核侧过滤表达式，决定哪些包进入用户态 |
| snaplen（`-s`） | 每个包最多拷贝的字节数；过小会截断载荷 |
| 混杂模式（promiscuous） | 网卡接收非本机 MAC 的帧；默认 tcpdump 常会打开（可用 `-p` 关闭） |
| pcap / pcapng | 捕获文件格式；Wireshark 均可打开 |
| SYN / SYN-ACK / ACK / RST / FIN | TCP 控制标志：建连、确认、复位、关闭 |
| 重传（retransmission） | 发送方认为丢包后重发；Wireshark 会标红提示 |

---

## 4. 安装

### 4.1 Debian / Ubuntu

**要做什么：** 安装 tcpdump 包。  
**为什么：** 发行版源中的包已链接 libpcap，开箱可用。  
**预期结果：** `tcpdump --version` 有输出。

```bash
sudo apt update
sudo apt install -y tcpdump

tcpdump --version
# 预期：tcpdump version x.x.x / libpcap version x.x.x
```

可选（本机分析）：

```bash
sudo apt install -y tshark
# 或桌面环境再装 wireshark
```

### 4.2 RHEL / AlmaLinux / Rocky / CentOS

```bash
# RHEL 8+ / Alma / Rocky 常见
sudo dnf install -y tcpdump

# 较老的 yum 系
sudo yum install -y tcpdump

tcpdump --version
```

**【需要确认】** 极精简容器镜像可能无 tcpdump；需从对应发行版源安装，或在调试 Pod / sidecar 中带工具镜像，不要默认假设生产镜像已装。

### 4.3 验证抓包能力

```bash
# 列出可用接口（无 root 时可能不全）
ip -br link

# 抓 1 个包即退出（需权限）
sudo tcpdump -i any -nn -c 1
```

预期：打印一条带时间戳的报文摘要，然后退出；若权限不足则报错。

---

## 5. 基本用法

**先记住结论：** 日常排障模板是「指定接口 + 不解析名字 + 限制数量或写文件 + 引号包住 BPF」。

```bash
sudo tcpdump -i eth0 -nn -tttt -c 100 'host 10.0.0.8 and port 443'
```

### 5.1 指定接口：`-i`

```bash
# 列出接口（tcpdump 自带）
sudo tcpdump -D

# 指定物理/虚拟网卡
sudo tcpdump -i eth0 -nn

# any：尽量从所有接口抓（伪接口；部分链路层细节会丢失，见第 10 节）
sudo tcpdump -i any -nn 'port 53'
```

**要做什么：** 先 `ip route get <目标IP>` 看从哪块网卡出去，再 `-i` 对准那块。  
**为什么：** 抓错网卡是「明明业务有流量、tcpdump 却空白」的头号原因。  
**预期结果：** 有匹配流量时持续刷行；无流量则安静等待（不是报错）。

```bash
# 查到某目标应走哪块网卡
ip route get 8.8.8.8
# 示例输出含：dev eth0 src 10.0.0.5 ...
```

### 5.2 不解析主机名与服务名：`-n` / `-nn`

| 选项 | 作用 |
|------|------|
| 默认 | 可能把 IP 反解成主机名、把端口显示成服务名（如 `https`） |
| `-n` | 不解析主机名，IP 原样显示 |
| `-nn` | 既不解析主机名，也不把端口映射成服务名（推荐排障默认） |

```bash
sudo tcpdump -i eth0 -nn 'port 80'
# 预期：看到 10.0.0.5.54321 > 10.0.0.8.80 这类形式，而不是域名和 http
```

排障时优先 `-nn`，避免 DNS 反查拖慢输出、也避免把「解析失败」和「抓包本身」搅在一起。

### 5.3 限制包数：`-c`

```bash
sudo tcpdump -i eth0 -nn -c 20 'tcp port 22'
```

抓到 20 个匹配包后自动退出。适合快速验证「有没有流量」，避免无限刷屏。

### 5.4 写文件与读文件：`-w` / `-r`

```bash
# 写二进制捕获文件（推荐排查时用；终端摘要会丢细节）
sudo tcpdump -i eth0 -nn -w /tmp/web.pcap 'host 10.0.0.8 and port 443'

# 稍后在本机或同机回放摘要
tcpdump -nn -r /tmp/web.pcap
tcpdump -nn -r /tmp/web.pcap 'tcp[tcpflags] & tcp-syn != 0'
```

**要点：**

- `-w` 时默认不再把完整解码打到屏幕（可用 `--print` 边写边打，视版本而定）
- 文件权限通常是 root 所有；分析前注意 `chmod` / `chown` 或拷贝时的权限
- 用 Wireshark 打开：`File → Open` 选择该 `.pcap` 文件

### 5.5 详细程度：`-v` / `-vv` / `-vvv`

```bash
sudo tcpdump -i eth0 -nn -v 'udp port 53'
sudo tcpdump -i eth0 -nn -vv 'icmp'
```

`-v` 增加协议字段细节（TTL、包长、部分选项等）；`-vv` / `-vvv` 更啰嗦。排障初期用 `-nn` 看方向与标志即可；需要看 IP TTL、长度时再加 `-v`。

### 5.6 可读时间戳：`-tttt`

| 选项 | 时间戳样式（概念） |
|------|-------------------|
| 默认 | 自午夜起的时:分:秒.小数 |
| `-tttt` | 年-月-日 时:分:秒.小数（人类可读，推荐写进工单） |
| `-tt` | epoch 秒.微秒（便于脚本） |
| `-ttt` | 与上一包的间隔 |

```bash
sudo tcpdump -i eth0 -nn -tttt -c 5 'port 443'
# 预期类似：2026-07-28 18:01:02.123456 IP 10.0.0.5.51234 > 10.0.0.8.443: Flags [S], ...
```

### 5.7 其他高频选项（速览）

| 选项 | 作用 |
|------|------|
| `-p` | **不**把接口置为混杂模式（只收本机相关流量时更「干净」，见第 10 节） |
| `-s0` 或 `-s 65535` | snaplen 尽量大，避免截断应用载荷（老版本常用 `-s0`） |
| `-A` | ASCII 打印载荷（看明文 HTTP 有用） |
| `-X` / `-XX` | hex + ASCII 转储 |
| `-l` | 行缓冲，方便管道给 `grep` |
| `-B 4096` | 增大捕获缓冲（单位 KiB），高流量防丢 |
| `-C 100` | 单文件约 100 MB 后轮转（与 `-w` 联用） |
| `-W 10` | 最多保留 10 个轮转文件（常与 `-C` 联用） |
| `-G 3600` | 按秒轮转（与 `-w` 文件名中的时间格式联用，见 man） |

**【需要确认】** 你机器上的 man 页对 `-C` 单位与 `-G` 文件名格式的精确说明（以 `man tcpdump` 为准）。

### 5.8 过滤器要用引号

```bash
# 正确：整段 BPF 交给 tcpdump
sudo tcpdump -i eth0 -nn 'host 10.0.0.8 and (port 80 or port 443)'

# 错误示范：shell 可能拆词或展开通配
sudo tcpdump -i eth0 -nn host 10.0.0.8 and port 80 or port 443
```

复杂表达式务必单引号包住，括号两边留空格：`( port 80 or port 443 )`。

---

## 6. BPF 过滤精华

**先记住结论：** BPF 由「方向 + 类型 + 协议」等原语用 `and` / `or` / `not` 组合；在抓包阶段尽量写紧，磁盘和 CPU 都会轻松很多。

### 6.1 host / net / port

```bash
# 与某主机相关的双向流量（src 或 dst）
host 10.0.0.8

# 网段（示例）
net 10.0.0.0/24
net 192.168.1.0 mask 255.255.255.0

# 端口（TCP 或 UDP 等，语义见 pcap-filter）
port 53
portrange 8000-8010
```

### 6.2 方向：src / dst

```bash
src host 10.0.0.5
dst host 10.0.0.8
src port 54321
dst port 443

# 组合
src host 10.0.0.5 and dst port 443
```

无 `src`/`dst` 时，`host` / `port` 通常表示「源或目的」。

### 6.3 协议：tcp / udp / icmp / ip

```bash
tcp
udp
icmp
ip          # IPv4
ip6         # IPv6
arp

tcp port 80
udp port 53
icmp and host 10.0.0.8
```

注意：部分「上层协议关键字只作用于 IPv4」的历史限制在文档中有说明；IPv6 场景优先显式写 `ip6` 并实测。**【需要确认】** 你关心的流量是否主要为 IPv6。

### 6.4 逻辑：and / or / not

```bash
host 10.0.0.8 and port 443
host 10.0.0.8 and not port 22
tcp and (port 80 or port 443)
not arp and not port 22
```

等价符号：`&&`、`||`、`!`（更推荐写 `and`/`or`/`not`，可读性更好）。

### 6.5 TCP 标志（握手 / RST 常用）

```bash
# SYN（含纯 SYN 与 SYN-ACK 都可能匹配，需结合方向再看）
'tcp[tcpflags] & tcp-syn != 0'

# 仅看带 SYN 的（排查建连）
'tcp[tcpflags] & (tcp-syn|tcp-ack) == tcp-syn'   # 纯 SYN
'tcp[tcpflags] & (tcp-syn|tcp-ack) == (tcp-syn|tcp-ack)'  # SYN-ACK

# RST
'tcp[tcpflags] & tcp-rst != 0'
```

Wireshark 打开文件后用 display filter `tcp.flags.syn==1 && tcp.flags.ack==0` 往往更直观；线上先抓 `host X and port Y`，线下再细滤。

### 6.6 常用组合速记

```bash
# 某客户端访问某服务端口
'src host 10.0.0.5 and dst host 10.0.0.8 and dst port 8080'

# Web 明文 + TLS 端口
'host 10.0.0.8 and (port 80 or port 443)'

# 仅 DNS
'udp port 53 or tcp port 53'

# 排除 SSH，避免自己操作干扰（仍可能漏看别的）
'host 10.0.0.8 and not port 22'

# ICMP 连通性
'icmp and host 10.0.0.8'
```

---

## 7. 实现步骤：标准抓包流程

按下面顺序做，每步都有「做什么 / 为什么 / 预期结果」。

### 步骤 1：确认本机监听与进程

**要做什么：**

```bash
ss -lntup | grep -E ':80|:443|:8080'   # 按实际端口改
# 或
ss -lntup
```

**为什么：** 若本机根本没监听，抓到 SYN 却没有 SYN-ACK，根因可能在应用没起来，而不是「网络丢了」。  
**预期结果：** 看到 `LISTEN` 及进程名；没有则先修服务再抓包。

### 步骤 2：确认路由与网卡

```bash
ip addr
ip route
ip route get <客户端或服务端 IP>
```

**为什么：** 决定 `-i` 用哪块网卡，以及地址是否在预期网段。  
**预期结果：** 明确 `dev xxx` 与本机源 IP。

### 步骤 3：确认主机防火墙 / 安全组（概念层）

- 本机：**UFW** / iptables / nftables 是否 drop 该端口
- 云上：安全组入站是否放行源 IP 与端口
- 容器：是否只在 `docker0` / CNI 口上能看到，而物理网卡是另一幅图景

**为什么：** 抓包点之前被丢掉的包，你在错误网卡上永远看不到。  
**预期结果：** 知道「包应该出现在哪一层接口」。

### 步骤 4：用最小过滤器开抓

```bash
sudo tcpdump -i eth0 -nn -tttt -s0 -w /tmp/case1.pcap \
  'host 10.0.0.5 and port 8080'
```

另开终端复现问题（curl、浏览器、压测）。复现后 `Ctrl+C` 结束。

**预期结果：** 文件非空；`tcpdump -nn -r /tmp/case1.pcap | head` 能看到相关包。

### 步骤 5：对照现象下结论

| 观察 | 倾向结论 |
|------|----------|
| 完全无包 | 抓错网卡 / 过滤器过紧 / 流量未到本机 / 安全组已丢 |
| 只有客户端 SYN，无 SYN-ACK | 服务未听、本机防火墙丢、或回程路由问题（需结合服务端抓包） |
| 有 SYN、有 SYN-ACK、有 ACK，随后应用超时 | 更可能是应用层 / TLS / 上层协议问题 |
| 大量重传、乱序 | 链路质量、拥塞、中途设备问题（需 Wireshark 统计辅助） |

### 步骤 6：用 Wireshark 打开

1. 将 `/tmp/case1.pcap` 拷到分析机（`scp` 等）
2. Wireshark 打开 → 用 display filter，如 `tcp.port == 8080`
3. 右键 → Follow → TCP Stream
4. Statistics → Conversations / Expert Information 看重传与异常

---

## 8. 完整示例与实战场景

以下示例中的 IP、端口请换成你的真实值。

### 8.1 看某端口是否「通」：三次握手

**场景：** 客户端 `10.0.0.5` 访问服务 `10.0.0.8:8080`，连接超时。

在**服务端**抓：

```bash
sudo tcpdump -i eth0 -nn -tttt -c 50 \
  'host 10.0.0.5 and port 8080'
```

客户端执行：

```bash
curl -v --connect-timeout 3 http://10.0.0.8:8080/
```

**预期观察点：**

1. **正常握手：**  
   - `Flags [S]`（客户端 → 服务端）  
   - `Flags [S.]`（SYN-ACK，服务端 → 客户端）  
   - `Flags [.]`（ACK）  
   随后才有 HTTP 数据或应用数据
2. **只有 `[S]` 反复出现、无 `[S.]`：** 包到了网卡但服务未应答，或应答在别的路径；先查 `ss -lntup`、本机防火墙
3. **出现 `[R]` / `[R.]`：** 连接被复位（进程不在听该端口、防火墙 reject、或应用主动 RST）
4. **服务端完全看不到 SYN：** 安全组 / 上游防火墙 / 抓错网卡 / 客户端根本没发出

在**客户端**对称抓一份，用于区分「没发出」还是「发出去了没回来」。

### 8.2 HTTP / HTTPS 排查边界

**HTTP（明文，端口常 80）：**

```bash
sudo tcpdump -i eth0 -nn -A -s0 \
  'host 10.0.0.8 and tcp port 80'
```

预期：ASCII 中可能看到 `GET / HTTP/1.1`、`Host:`、`HTTP/1.1 200` 等（前提是未再套加密）。

**HTTPS（TLS，端口常 443）：**

```bash
sudo tcpdump -i eth0 -nn -s0 -w /tmp/https.pcap \
  'host 10.0.0.8 and tcp port 443'
```

预期：

- 能看到 TCP 握手、TLS ClientHello / ServerHello 等**外层**行为（Wireshark 会解码握手消息名）
- **不能**直接读到 HTTPS 里的 JSON、Cookie 明文（除非配置 SSLKEYLOGFILE 等解密条件，超出日常运维默认真范围）
- 超时若发生在 TCP 握手之后、应用读响应之前，重点看 TLS 证书、SNI、防火墙对已建立连接的干扰，而不是「HTTP 状态码」

**边界口诀：** 明文协议可以「看到内容」；加密协议抓包主要「证明连接与握手阶段卡在哪」。

### 8.3 DNS 解析问题

```bash
# 本机解析器常走 127.0.0.53（systemd-resolved）或真上游
sudo tcpdump -i any -nn -tttt 'port 53'

# 同时触发
dig @8.8.8.8 example.com +time=2
```

**预期观察点：**

| 现象 | 含义 |
|------|------|
| 无任何 port 53 包 | 查询未发出，或走了别的路径/接口；检查 `/etc/resolv.conf`、本地 stub |
| 有查询无应答 | 上游不可达、被过滤、或抓错接口 |
| 有应答但应用仍失败 | 应答内容可能是 NXDOMAIN / 错误 IP；用 `dig` 看内容，勿只看「有包」 |
| 仅 UDP 53 失败、TCP 53 有流量 | 大包截断 / 防火墙只放 UDP 等进阶问题 |

配合：

```bash
dig example.com
resolvectl status   # 若使用 systemd-resolved
```

### 8.4 丢包 / 重传粗判（配合 ss）

抓包：

```bash
sudo tcpdump -i eth0 -nn -tttt -w /tmp/retrans.pcap \
  'host 10.0.0.8 and port 443'
```

连接存续时看套接字统计：

```bash
ss -ti dst 10.0.0.8:443
# 关注输出中的 retrans、rtt、cwnd 等字段（内核版本不同显示略有差异）
```

Wireshark：`Statistics → TCP Stream Graphs` 或 Expert 里的 retransmission / duplicate ACK。

**粗判逻辑：**

1. `ss` 显示重传攀升 + 抓包见重复序号段 → 倾向路径丢包或严重拥塞  
2. 握手都完不成 → 先别谈应用重试，先修连通性  
3. 单侧抓包无法证明「中间哪一跳」丢，需要多点或 mtr/traceroute 辅助  

`netstat -s`（若仍可用）也可看协议层累计计数，适合看趋势，不适合单次会话精确定位。

### 8.5 抓到文件后用 Wireshark 打开

```bash
# 服务器
sudo tcpdump -i eth0 -nn -s0 -w /tmp/case.pcap 'host 10.0.0.5 and port 8080'
# Ctrl+C 结束后
sudo chmod 644 /tmp/case.pcap
scp user@server:/tmp/case.pcap .
```

Wireshark 建议动作：

1. 过滤：`ip.addr == 10.0.0.5 && tcp.port == 8080`
2. Follow TCP Stream 看明文会话
3. 看 Info 列是否 `TCP Retransmission`、`RST`、`DUP ACK`
4. 需要给同事时只传该 pcap，并注明抓包点（客户端/服务端）与时间

---

## 9. 排障方法论

把网络问题切成一条证据链，避免一上来无脑全量抓包。

### 9.1 推荐顺序

```text
1) 本机服务是否监听？          → ss -lntup
2) 路由与网卡是否正确？        → ip route get
3) 主机防火墙是否放行？        → ufw status / iptables / nft
4) 云安全组 / ACL 是否放行？   → 控制台核对源 IP、端口、方向
5) 抓包：包是否到达抓包点？    → tcpdump
6) 握手是否完成？              → 看 SYN / SYN-ACK / ACK / RST
7) 应用层是否异常？            → 明文看载荷；加密看 TLS/应用日志
```

### 9.2 如何区分客户端 / 服务端 / 防火墙

| 角色 | 你应看到的证据 | 若缺失则怀疑 |
|------|----------------|--------------|
| 客户端 | 发出 SYN；若超时，可能无 SYN-ACK | 客户端策略、错误目标 IP、本地防火墙出站 |
| 服务端 | 收到 SYN；若正常应回 SYN-ACK | 未监听、本机 UFW/iptables drop、应用崩溃 |
| 防火墙 / 安全组 | 一侧有 SYN，对侧完全无 SYN（或回 RST） | 中间策略丢弃；需在两侧对比抓包 |
| 路径 / NAT | 两边五元组不一致、只单边有流量 | NAT、策略路由、非对称路由 |

**UFW 示例（仅点到为止）：** 若服务端 `ufw status` 未放行 `8080/tcp`，可能出现客户端狂发 SYN、服务端应用无日志；是否在 tcpdump 可见取决于过滤发生在抓包钩子之前还是之后——**务必在「业务网卡」上抓，并结合 `ufw logging` 与两侧对比**。云安全组丢包通常在实例网卡之外，实例内抓包可能完全空白。

### 9.3 最小复现模板（可直接套）

```bash
# 终端 A：服务端
sudo tcpdump -i eth0 -nn -tttt -s0 -w /tmp/srv.pcap \
  'host <CLIENT_IP> and port <PORT>'

# 终端 B：客户端
curl -v --connect-timeout 5 http://<SERVER_IP>:<PORT>/

# 结束后分别在两端看
tcpdump -nn -tttt -r /tmp/srv.pcap
```

结论写进工单时建议固定四句话：**抓包点、过滤器、是否见到 SYN、是否见到 SYN-ACK**。

---

## 10. 常见问题与排查

### 10.1 抓包结果是空的

| 可能原因 | 解决方法 |
|----------|----------|
| 抓错网卡 | `ip route get` 后改 `-i`；容器场景抓 `docker0` / veth / CNI |
| 过滤器过严 | 先放宽为 `host x.x.x.x`，确认有包再收紧 |
| 流量在 `any` 上看不到预期链路层 | 改抓具体接口 |
| 权限不足 | `sudo` 或检查 capability |
| 流量未到本机 | 查安全组 / 上游防火墙；在客户端再抓一份对比 |

### 10.2 只有出站或只有入站

- 检查是否用了 `src`/`dst` 写反  
- 非对称路由：入站与出站不在同一网卡 → 可能需要两块网卡都抓或改用 `any`  
- 云环境「流量清洗 / LB」导致你看到的源 IP 是健康检查或节点 IP

### 10.3 容器 / Docker / K8s

```bash
# 宿主机上看桥
ip -br link | grep -E 'docker|cni|flannel|cali|veth'

# 进容器命名空间抓（需工具与权限）
# 【需要确认】运行时是 docker / containerd，以及是否允许 nsenter
sudo ls /var/run/docker/netns 2>/dev/null
```

常见坑：

- 在宿主机 `eth0` 上抓，容器间东向流量可能只出现在 veth/桥上  
- Service / ClusterIP 经 kube-proxy / CNI 改写后，五元组与你想的不一致  
- 建议：先确定抓包点（Pod 内 / Node / 入口 LB），再写过滤器

### 10.4 需要 `-p` 的情况

默认 tcpdump 常开启**混杂模式**，在交换机镜像口、桥接环境可能收到「不是发给本机」的帧，干扰判断。

```bash
# 只关心本机收发时，关闭混杂模式
sudo tcpdump -i eth0 -p -nn 'port 8080'
```

**要做什么：** 主机排障优先试 `-p`。  
**为什么：** 减少无关广播/洪泛干扰。  
**预期结果：** 仍能看到本机相关的 TCP/UDP；若你在做镜像口旁路分析，则不要加 `-p`。

### 10.5 高流量丢包：加大 `-B`

内核到用户态之间有环形缓冲；打满后抓包会丢（tcpdump 结束时可能提示 `packets dropped by kernel`）。

```bash
sudo tcpdump -i eth0 -nn -B 8192 -s0 -w /tmp/busy.pcap 'port 443'
```

同时：**收紧 BPF**、避免 `-A` 刷屏、优先 `-w` 写盘。仍丢则考虑端口镜像到专用分析机或降低采样面。

### 10.6 文件过大：轮转

```bash
# 约每 100MB 轮转，最多 20 个文件（具体命名见 man）
sudo tcpdump -i eth0 -nn -C 100 -W 20 -w /tmp/rot.pcap 'port 443'
```

或按时间（`-G`）轮转。抓完尽快删含敏感数据的文件。

### 10.7 snaplen 截断

载荷在 Wireshark 里显示 `[Packet size limited during capture]`：

```bash
sudo tcpdump -i eth0 -nn -s0 -w /tmp/full.pcap 'port 80'
```

老环境若 `-s0` 异常，显式 `-s 65535`。**【需要确认】** 当前 libpcap 对 0 的含义（多数现代版本中 0 表示最大）。

---

## 11. 注意事项与最佳实践

### 11.1 安全与合规

- **不要**在生产随意抓含明文密码、Cookie、Token、个人信息的流量并长期留存
- 抓包范围最小化：能 `host + port` 就不要 `any` 无过滤
- 文件加密传输、用后删除；工单只贴摘要，不贴整包 Base64
- 多租户 / 合规环境先确认是否允许抓包（部分行业有明确审计要求）
- 给二进制 `setcap` 等于扩大攻击面，用毕收回

### 11.2 操作建议

1. 默认加 `-nn -tttt`，排障写文件用 `-w`，少在生产机开 `-A` 长跑  
2. 先 `ss` / 路由 / 防火墙，再抓包  
3. 两侧对比优于单侧猜测  
4. HTTPS 先判断 TCP/TLS 阶段，再回应用日志  
5. 记录：时间、抓包主机、接口、完整命令行、复现步骤  

### 11.3 与相关工具的边界

| 需求 | 更合适的工具 |
|------|----------------|
| 谁在听端口 | `ss -lntup` |
| 路由下一跳 | `ip route get` |
| 主机防火墙 | UFW / nft / iptables |
| 路径质量 | `mtr` / `ping` / `traceroute` |
| 深度协议分析 | Wireshark / tshark |
| 证明包到达某网卡 | **tcpdump** |

---

## 12. 总结

- **tcpdump** 用 BPF 在 Linux 上高效抓包；与 Wireshark/tshark 是「采集 vs 分析」分工  
- 排障默认命令形态：`sudo tcpdump -i <iface> -nn -tttt -s0 -w file.pcap '<bpf>'`  
- 先确认监听、路由、防火墙/安全组，再抓包；用 SYN/SYN-ACK/RST 判断卡在哪一层  
- HTTP 可看明文载荷；HTTPS 主要看 TCP/TLS 外层；DNS 看请求应答是否完整  
- 避开抓错网卡、容器网桥盲区、缓冲丢包、文件爆炸；遵守最小化与合规  

### 下一步建议

1. 在一台测试机上对已知端口跑通「握手成功」与「只 SYN」两种对照实验  
2. 把一次真实故障的 pcap 用 Wireshark Follow TCP Stream 走一遍  
3. 为团队准备一条标准抓包命令模板（含轮转与目录约定）  
4. 若本环境大量使用容器网络，单独整理「Pod/Node/CNI 该在哪抓」的内部备忘  

---

## 附录 A：命令速查

```bash
# 版本与接口
tcpdump --version
sudo tcpdump -D

# 实时看（限制 30 个包）
sudo tcpdump -i eth0 -nn -tttt -c 30 'port 8080'

# 写文件（推荐）
sudo tcpdump -i eth0 -nn -s0 -w /tmp/a.pcap 'host 10.0.0.5 and port 8080'

# 读文件
tcpdump -nn -tttt -r /tmp/a.pcap
tcpdump -nn -r /tmp/a.pcap 'tcp[tcpflags] & tcp-syn != 0'

# 不混杂
sudo tcpdump -i eth0 -p -nn 'host 10.0.0.5'

# 加大缓冲
sudo tcpdump -i eth0 -nn -B 8192 -w /tmp/b.pcap 'port 443'

# 文件轮转（示例）
sudo tcpdump -i eth0 -nn -C 100 -W 20 -w /tmp/rot.pcap 'port 443'

# 明文 HTTP 瞥一眼
sudo tcpdump -i eth0 -nn -A -s0 -c 20 'tcp port 80'

# DNS
sudo tcpdump -i any -nn -tttt 'port 53'

# 配合复现
curl -v --connect-timeout 3 http://10.0.0.8:8080/
ss -lntup
ip route get 10.0.0.8
```

---

## 附录 B：过滤器速查

```text
host 10.0.0.8
net 10.0.0.0/24
port 53
portrange 8000-8010

src host 10.0.0.5
dst host 10.0.0.8
src port 12345
dst port 443

tcp
udp
icmp
ip / ip6
arp

tcp port 80
udp port 53
host 10.0.0.8 and port 443
host 10.0.0.8 and (port 80 or port 443)
host 10.0.0.8 and not port 22

tcp[tcpflags] & tcp-syn != 0
tcp[tcpflags] & tcp-rst != 0
tcp[tcpflags] & (tcp-syn|tcp-ack) == tcp-syn
tcp[tcpflags] & (tcp-syn|tcp-ack) == (tcp-syn|tcp-ack)

icmp and host 10.0.0.8
udp port 53 or tcp port 53
```

---

## 附录 C：三次握手速查（tcpdump Flags）

| Flags（常见打印） | 含义 |
|-------------------|------|
| `[S]` | SYN |
| `[S.]` | SYN + ACK |
| `[.]` | 纯 ACK（无其他控制位时） |
| `[F]` / `[F.]` | FIN |
| `[R]` / `[R.]` | RST |
| `[P.]` | PSH + ACK（常带数据） |

完整成功建连顺序：`[S]` → `[S.]` → `[.]`，之后才是应用数据。

---

## 参考

- tcpdump 手册：https://www.tcpdump.org/manpages/tcpdump.1.html  
- pcap-filter 手册：https://www.tcpdump.org/manpages/pcap-filter.7.html  
- 本机详细选项以 `man tcpdump`、`man pcap-filter` 为准  
