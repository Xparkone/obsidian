# UFW 使用指南（Ubuntu / Debian）

## 1. 文档概述

### 解决什么问题

本指南说明如何用 **UFW**（Uncomplicated Firewall，简易防火墙）在 Linux 主机上配置主机防火墙：放行必要端口、拒绝未授权访问、查看规则与日志，并避免「启用防火墙后把自己锁在 SSH 之外」这类常见事故。

### 适合哪些读者

- 有一定 Linux 基础（会用 `apt`、`systemctl`、SSH 登录）
- 负责 Ubuntu / Debian 云主机或本地服务器的基础安全加固
- 需要一份可检索、可照着敲的实操手册（非概念科普）

### 阅读后能获得什么

- 理解 UFW 与 iptables / nftables 的关系、适用场景与局限
- 能安全地安装、启用、查看与关闭 UFW（**启用前先放行 SSH**）
- 会配置默认策略、端口/来源规则、Application Profile、删除与限速
- 能完成「只开 SSH + Web」「仅内网访问」「限制 SSH 爆破」等常见场景
- 知道如何看日志、排障，以及主机 UFW 与云安全组如何配合

### 版本与范围说明

- 本文以 **Ubuntu 20.04 / 22.04 / 24.04** 及同类 **Debian** 为主（`ufw` 包来自官方源）
- 命令以 root 或带 `sudo` 的普通用户执行为准
- RHEL / CentOS / AlmaLinux 等发行版通常默认用 `firewalld`，本文不覆盖；若在这些系统上强行装 UFW，行为与包名可能不同，请以发行版文档为准并标注为 **【需要确认】**
- UFW 管理的是**本机入站/出站过滤**；它不能替代云厂商安全组、VPC 网络 ACL，也不能替代应用层鉴权

---

## 2. 前置条件

### 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu / Debian（推荐） |
| 权限 | 能使用 `sudo` 执行特权命令，或直接以 root 登录 |
| 网络 | 若通过 SSH 远程操作，务必确认当前 SSH 端口与来源 IP |
| 包管理 | `apt` 可用，能访问发行版软件源 |

### 软件及版本

- `ufw` 包（Ubuntu 桌面版常预装；服务器版可能需手动安装）
- 依赖：底层通常由 **iptables** 或 **nftables**（经 iptables 兼容层）实际执行过滤
- 可选：`netfilter-persistent` / `iptables-persistent`（一般不必与 UFW 混用手工规则，见进阶节）

### 必备基础知识

- 会用 SSH 登录远程主机
- 了解 TCP/UDP 端口的基本含义（如 22、80、443）
- 知道「入站（incoming）」与「出站（outgoing）」的区别

### 动手前必须确认的信息

开始改防火墙前，请自行确认：

- **【需要确认】** 当前 SSH 监听端口（默认 22，还是非标准端口如 2222）
- **【需要确认】** 你是否通过公网 SSH、还是仅内网/跳板机访问
- **【需要确认】** 云主机是否另有安全组 / 防火墙规则（阿里云、AWS、GCP 等）
- **【需要确认】** 是否需要允许 IPv6（默认 UFW 通常同时管 IPv4/IPv6，见进阶节）

> **核心风险：** 在远程 SSH 会话中执行 `ufw enable`，若未先放行 SSH 端口，连接可能立刻断开且无法再登录。下文会反复强调这一点。

---

## 3. 核心概念

**先记住结论：** UFW 是面向主机的防火墙前端；你写简单的 allow/deny 规则，它负责生成并维护底层 netfilter 规则。默认思路是「**默认拒绝入站，只放行明确需要的服务**」。

### 3.1 UFW 是什么

**UFW**（Uncomplicated Firewall）是 Canonical 为 Ubuntu 设计的防火墙管理工具，目标是用少量命令完成常见主机防火墙配置，降低直接写 iptables/nftables 的复杂度。

典型能力：

- 设置默认入站/出站策略
- 按端口、协议、来源 IP/网段允许或拒绝流量
- 按应用配置文件（Application Profile）一键放行服务
- 对 SSH 等端口做简单限速（`limit`），缓解暴力破解
- 启用后规则持久化，重启后仍生效

### 3.2 与 iptables / nftables 的关系

| 层次 | 说明 |
|------|------|
| 应用层工具 | UFW：提供易用命令与配置文件 |
| 规则翻译 | UFW 把你的规则翻译成底层防火墙规则 |
| 内核过滤框架 | **netfilter**（Linux 内核包过滤框架） |
| 用户态工具 | 历史上常用 **iptables**；较新系统常用 **nftables**。许多发行版通过兼容层让 `iptables` 命令实际操作 nftables |

要点：

1. **日常运维优先只用 UFW**，不要一边用 UFW、一边手工大幅改 iptables/nftables，否则容易互相覆盖、难排查。
2. UFW 启用后，会在底层插入自己的规则链；`ufw status` 看到的是「UFW 视角」的规则摘要，完整底层规则可用 `iptables -L` / `nft list ruleset` 查看（进阶排查时再用）。
3. UFW **不是** iptables 的完整替代品：复杂 NAT、精细匹配、多接口策略路由等，往往仍需直接写底层规则或改 `before.rules` / `after.rules`。

### 3.3 适用场景与局限

**适合：**

- 单机 / 少量服务器的主机防火墙
- Web、SSH、数据库等「开放少数端口」的常见需求
- 需要快速落地「默认拒绝 + 白名单」策略

**不适合或不够用：**

- 复杂多网卡、策略路由、大规模 NAT 网关
- 需要细粒度连接跟踪状态机调优、自定义匹配扩展
- 替代 WAF、应用鉴权、零信任网关
- 替代云安全组（UFW 只保护「到这台机器网卡」的流量；云边界过滤在安全组）

### 3.4 关键术语

| 术语 | 一句话解释 |
|------|------------|
| Incoming / Outgoing | 入站（进入本机）/ 出站（本机发出） |
| Policy（默认策略） | 没有匹配到具体规则时的默认动作：allow 或 deny |
| Allow / Deny / Reject | 允许；静默丢弃；拒绝并通知对端（通常发 ICMP/TCP RST） |
| Limit | 允许访问，但对短时间内过多连接尝试做限速（常用于 SSH） |
| Application Profile | 软件包提供的端口/协议描述文件，可用服务名放行 |
| Numbered rules | 带序号的规则列表，便于按编号删除 |

---

## 4. 安装与启用

按顺序操作。远程主机请严格按「先放行 SSH → 再 enable」执行。

### 4.1 安装

**做什么：** 安装 `ufw` 软件包。  
**为什么：** 部分最小化镜像未预装。  
**预期结果：** `ufw version` 能输出版本信息。

```bash
sudo apt update
sudo apt install -y ufw
ufw version
```

### 4.2 查看当前状态

```bash
sudo ufw status
# 或更详细：
sudo ufw status verbose
# 带规则编号（删除规则时常用）：
sudo ufw status numbered
```

未启用时通常显示 `Status: inactive`。

### 4.3 启用前必须先放行 SSH（醒目提醒）

> ## ⚠️ 启用 UFW 前必须先放行 SSH
>
> 若你正通过 SSH 远程操作，**先执行 allow，再 enable**。  
> 顺序反了可能导致：当前会话断开、无法再次 SSH 登录，只能走云控制台 VNC / 救援模式 / 物理控制台恢复。
>
> 推荐最小安全步骤：
>
> ```bash
> # 1）先放行 SSH（默认 22；若改过端口请改成实际端口）
> sudo ufw allow OpenSSH
> # 或：
> sudo ufw allow 22/tcp
>
> # 2）确认规则已在列表中
> sudo ufw status
>
> # 3）再启用
> sudo ufw enable
> ```
>
> 非标准 SSH 端口示例（假设为 2222）：
>
> ```bash
> sudo ufw allow 2222/tcp
> sudo ufw enable
> ```

### 4.4 启用 / 关闭

**启用：**

```bash
sudo ufw enable
```

系统通常会提示：启用后可能中断现有 SSH 连接。确认已放行 SSH 后输入 `y`。

**预期结果：** `sudo ufw status` 显示 `Status: active`，且 SSH 相关规则为 `ALLOW`。

**关闭（临时排查时可用；生产勿长期关闭）：**

```bash
sudo ufw disable
```

关闭后规则仍保存在配置里，再次 `enable` 会重新加载。

### 4.5 开机自启

UFW 启用后一般会通过 systemd 在开机时加载规则。可用下列命令确认服务状态（具体单元名因版本略有差异）：

```bash
systemctl status ufw
# 或
systemctl is-enabled ufw
```

**【需要确认】** 个别定制镜像可能禁用了 ufw 服务单元；若 `enable` 成功但重启后规则未加载，检查 `systemctl` 与 `/etc/ufw/ufw.conf` 中 `ENABLED=yes`。

---

## 5. 默认策略

**结论：** 生产主机推荐：

- 入站：`deny`（默认拒绝）
- 出站：`allow`（默认允许，避免本机更新、DNS、对外 API 被误伤）

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
```

查看：

```bash
sudo ufw status verbose
```

输出中会包含类似：

```text
Default: deny (incoming), allow (outgoing), disabled (routed)
```

### 何时改出站策略

若你需要「默认拒绝出站、只白名单特定目标」，可：

```bash
sudo ufw default deny outgoing
sudo ufw allow out 53          # DNS 示例（按实际需求调整）
sudo ufw allow out 80/tcp
sudo ufw allow out 443/tcp
```

出站白名单维护成本高，容易弄坏 `apt update`、时间同步、监控上报等，**除非有明确合规要求，否则不要轻易默认拒绝出站**。

### 转发（routed）默认策略

`Default: ... (routed)` 与机器是否作为路由器/网关有关。单机服务默认保持 disabled/deny 即可；需要转发时见第 10 节。

---

## 6. 常用规则

### 6.1 基本语法思路

```text
ufw [allow|deny|reject|limit] [in|out] [from 来源] [to 目的] [port 端口] [proto 协议]
```

也支持更短的写法：

```bash
sudo ufw allow 80/tcp
sudo ufw deny 23/tcp
sudo ufw reject 25/tcp
sudo ufw limit 22/tcp
```

| 动作 | 行为 | 常见用途 |
|------|------|----------|
| `allow` | 允许匹配流量 | 开放服务端口 |
| `deny` | 丢弃，通常不通知对端 | 静默屏蔽 |
| `reject` | 拒绝并通知对端 | 明确告知不可达 |
| `limit` | 允许，但对过快连接尝试限速 | 缓解 SSH 暴力破解 |

### 6.2 按端口与协议

```bash
# TCP 80
sudo ufw allow 80/tcp

# UDP 53
sudo ufw allow 53/udp

# 端口范围（例如被动 FTP 或自定义业务端口段）
sudo ufw allow 60000:61000/tcp
```

不写协议时，UFW 可能对 TCP 与 UDP 都生效（具体以 `status` 为准）。**服务端口建议显式写 `/tcp` 或 `/udp`。**

### 6.3 按来源 IP / 网段

```bash
# 仅允许某公网 IP 访问 SSH
sudo ufw allow from 203.0.113.10 to any port 22 proto tcp

# 仅允许内网网段访问数据库端口
sudo ufw allow from 10.0.0.0/8 to any port 5432 proto tcp

# 拒绝某地址访问
sudo ufw deny from 198.51.100.20
```

### 6.4 按服务名（/etc/services）

```bash
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https
```

服务名依赖系统的 `/etc/services` 映射。更推荐使用 **Application Profile**（下一节）或显式端口，避免同名歧义。

### 6.5 删除规则

**方法一：按规则内容删除（需与添加时写法一致）**

```bash
sudo ufw delete allow 80/tcp
sudo ufw delete allow from 10.0.0.0/8 to any port 5432 proto tcp
```

**方法二：按编号删除（更稳妥）**

```bash
sudo ufw status numbered
# 示例输出中规则前有 [ 1 ] [ 2 ] ...
sudo ufw delete 3
```

删除时会要求确认。编号在每次增删后可能变化，**删多条时每次删除后重新 `status numbered`**，避免删错。

### 6.6 规则顺序（简述）

UFW 按规则**从上到下**匹配，**先匹配先生效**。因此：

- 更具体的规则应放在更靠前的位置（例如「允许某 IP」应先于「拒绝所有人访问该端口」这类宽规则——具体插入位置可用 `insert`）
- 用 `ufw insert N RULE` 可插入到指定序号：

```bash
# 把规则插到第 1 条位置
sudo ufw insert 1 allow from 10.0.0.0/8 to any port 22 proto tcp
```

查看顺序：

```bash
sudo ufw status numbered
```

日常「只有 allow 白名单 + 默认 deny」时，顺序问题较少；一旦混用 allow/deny 到同一端口，就要仔细看编号顺序。

### 6.7 重置（慎用）

清除所有规则并禁用 UFW：

```bash
sudo ufw reset
```

远程操作前同样要想到：重置后若再 enable，必须重新放行 SSH。

---

## 7. Application Profiles

部分软件包会安装 UFW 应用配置文件（通常在 `/etc/ufw/applications.d/`），描述该服务需要的端口。

### 7.1 查看可用应用

```bash
sudo ufw app list
```

查看某个应用详情：

```bash
sudo ufw app info OpenSSH
sudo ufw app info 'Nginx Full'
```

### 7.2 按应用放行

```bash
# OpenSSH（通常为 22/tcp）
sudo ufw allow OpenSSH

# Nginx：仅 Web
sudo ufw allow 'Nginx HTTP'      # 80
sudo ufw allow 'Nginx HTTPS'     # 443
sudo ufw allow 'Nginx Full'      # 80+443

# Apache 示例
sudo ufw allow 'Apache Full'
```

名称含空格时必须加引号。

### 7.3 与端口规则的关系

`allow OpenSSH` 与 `allow 22/tcp` 效果相近，但 Profile 的好处是：

- 端口变更时，更新 Profile 后规则语义更清晰
- `app info` 可自文档化「这个服务开了哪些端口」

同一端口被 Profile 与手工端口规则重复放行通常无问题，但列表会变乱，建议统一风格（团队内约定只用 Profile 或只用端口）。

---

## 8. 完整示例（实战）

以下示例均假设：你在远程 SSH 中操作；系统为 Ubuntu；SSH 为 22/tcp。请按环境替换 IP/端口。

### 8.1 场景 A：只开放 SSH + HTTP/HTTPS

**目标：** 公网 Web 服务器，仅开放 22、80、443。

```bash
# 安装（若未安装）
sudo apt update && sudo apt install -y ufw

# 默认策略
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 先放行 SSH，再放行 Web
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# 检查
sudo ufw status verbose

# 最后启用
sudo ufw enable
sudo ufw status numbered
```

**预期结果：**

- `Status: active`
- `22/tcp`（或 OpenSSH）、`80/tcp`、`443/tcp` 为 ALLOW
- Default incoming = deny

### 8.2 场景 B：SSH 仅内网可访问

**目标：** SSH 不对公网开放，仅办公网 / VPC 网段可连；Web 仍对公网开放。

**【需要确认】** 将 `10.0.0.0/8` 换成你的真实内网 CIDR。

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing

# SSH：仅内网
sudo ufw allow from 10.0.0.0/8 to any port 22 proto tcp

# Web：公网
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

sudo ufw enable
sudo ufw status numbered
```

注意：若你当前正从公网 IP SSH 进来，加完「仅内网」规则并 enable 后，**公网 SSH 会断**。请先通过 VPN / 跳板 / 控制台确保有内网路径，再执行。

### 8.3 场景 C：对 SSH 使用 limit（缓解爆破）

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 用 limit 代替普通 allow（短时间过多尝试会被限制）
sudo ufw limit OpenSSH
# 或：sudo ufw limit 22/tcp

sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

sudo ufw enable
```

`limit` 不能替代 fail2ban、密钥登录、禁用密码登录等措施，只是额外一层简单防护。

### 8.4 场景 D：数据库只给应用服务器访问

假设 PostgreSQL 监听 5432，应用服务器 IP 为 `10.0.1.20`：

```bash
sudo ufw allow from 10.0.1.20 to any port 5432 proto tcp
sudo ufw status numbered
```

不要对公网 `allow 5432/tcp`，除非有明确需求且叠加强认证与加密。

---

## 9. 日志与排障

### 9.1 日志级别

```bash
# off | low | medium | high | full
sudo ufw logging on          # 等价于开启低级别日志（常见）
sudo ufw logging medium
sudo ufw logging off
```

日志通常写入系统日志，例如：

```bash
sudo journalctl -u ufw -f
# 或传统路径（视发行版而定）：
sudo tail -f /var/log/ufw.log
sudo grep -i ufw /var/log/syslog
```

被拒绝的入站包会带有 `UFW BLOCK` 等标记，可据此判断「哪类流量被挡」。

### 9.2 常见问题

#### 问题 1：`ufw enable` 后 SSH 连不上

| 项 | 说明 |
|----|------|
| 现象 | 终端卡住 / Connection timed out / Connection refused |
| 可能原因 | 未放行 SSH 端口；放行了错误端口；云安全组未放行；仅允许了错误来源 IP |
| 解决方法 | 用云厂商 VNC/串口控制台登录 → `sudo ufw allow <实际SSH端口>/tcp` 或 `sudo ufw disable` 临时恢复 → 修正规则后再 enable |

#### 问题 2：服务本地正常，外网访问超时

| 项 | 说明 |
|----|------|
| 现象 | `curl 127.0.0.1:80` 正常，外网超时 |
| 可能原因 | UFW 未放行；云安全组未放行；服务只监听 `127.0.0.1`；上游负载均衡健康检查端口不对 |
| 解决方法 | `sudo ufw status verbose` 确认端口；检查云安全组；`ss -lntp` 确认监听地址为 `0.0.0.0` 或正确网卡 IP |

#### 问题 3：加了规则但不生效

| 项 | 说明 |
|----|------|
| 现象 | `allow` 后仍被拒 |
| 可能原因 | UFW 未 active；规则顺序被更靠前的 deny 命中；IPv6 客户端走 v6 而只配了 v4；云安全组仍拦截 |
| 解决方法 | 确认 `Status: active`；`status numbered` 看顺序；检查 `IPV6=yes`；同时查云安全组 |

#### 问题 4：与手工 iptables 规则冲突

| 项 | 说明 |
|----|------|
| 现象 | 规则「有时在、有时丢」或行为怪异 |
| 可能原因 | 同时使用 UFW、firewalld、手工 iptables-restore、Docker 自定义链等 |
| 解决方法 | 选定一个主机防火墙方案；Docker 环境需额外了解 Docker 对 iptables 的介入（**【需要确认】** 你的 Docker/容器网络需求） |

### 9.3 与云安全组的关系

把过滤想成两道门：

```text
互联网 → [云安全组 / 网络 ACL] → 虚拟机网卡 → [UFW / 主机防火墙] → 进程
```

- **云安全组**：云边界控制，未放行则流量到不了虚机
- **UFW**：主机侧控制，即使安全组放行，UFW 仍可拒绝

实操建议：

1. 两边都按最小权限配置（都要放行的端口才放行）
2. 排障时**两处都查**：先看安全组是否放行，再看 `ufw status`
3. 不要假设「只配 UFW 就够」或「只配安全组就够」——对公网主机，两者叠加更稳妥

---

## 10. 进阶简述

### 10.1 before.rules / after.rules

UFW 在应用用户规则前后，会加载：

| 文件 | 作用 |
|------|------|
| `/etc/ufw/before.rules` | 用户规则之前（常含回环、相关连接、部分 ICMPv4 等） |
| `/etc/ufw/after.rules` | 用户规则之后 |
| `/etc/ufw/before6.rules` / `after6.rules` | IPv6 对应文件 |
| `/etc/ufw/ufw.conf` | 总开关、日志级别等 |

适合放：特殊 ICMP、端口重定向、简单 NAT、必须早于普通 allow/deny 的规则。

修改后重载：

```bash
sudo ufw reload
```

直接编辑这些文件属于进阶操作：语法错误可能导致网络异常。改前备份，并确保有控制台兜底。

### 10.2 IPv6

`/etc/ufw/ufw.conf` 中：

```text
IPV6=yes
```

为 `yes` 时，UFW 通常同时为 IPv4/IPv6 生成规则。若你禁用了主机 IPv6 或只想管 IPv4，可改为 `no` 后 `sudo ufw reload`。

排障时注意：客户端若走 IPv6，只开 IPv4 规则会出现「有人能访问、有人不能」的现象。

### 10.3 转发（IP forwarding）与网关场景

若主机需要转发流量（简易路由器、NAT 网关）：

1. 内核开启转发（如 `/etc/sysctl.conf` 中 `net.ipv4.ip_forward=1`）
2. UFW 中允许转发策略，并常在 `before.rules` 写 NAT（`*nat` 的 `POSTROUTING` 等）
3. `ufw` 默认 routed 策略需按文档调整（例如 `DEFAULT_FORWARD_POLICY`）

单机 Web/应用服务器**通常不需要**开转发。网关场景细节因拓扑而异，实施前请对照 Ubuntu 官方 UFW 转发/NAT 文档，并把接口名、内网网段标为 **【需要确认】**。

### 10.4 重载与配置文件位置

```bash
sudo ufw reload
```

用户规则主要体现在 `/etc/ufw/user.rules` 与 `/etc/ufw/user6.rules`（一般不要手改，优先用 `ufw` 命令）。

---

## 11. 注意事项与最佳实践

1. **永远先放行管理通道再 enable**（SSH/控制台）。把这条当成检查清单第一项。
2. **默认拒绝入站，白名单放行**；出站默认允许，除非有强制合规要求。
3. **端口写明协议**（`80/tcp`），避免意外放开 UDP。
4. **管理端口尽量限制来源 IP**（办公出口、VPN、堡垒机网段），不要对全世界 `allow 22`。
5. **SSH 优先密钥登录 + 禁用密码**；`ufw limit` 只是补充。
6. **不要同时用多套主机防火墙框架** 乱改同一台机器。
7. **改规则后用另一终端验证**（保持一个已登录会话，另开窗口测 SSH/HTTP，避免把自己锁死）。
8. **云安全组与 UFW 一起做最小权限**；排障两处都看。
9. **生产变更留回滚步骤**：记录将执行的命令、如何 `delete` / `disable`、控制台入口在哪。
10. **容器主机要额外评估**：Docker 等会插入自己的 iptables 规则，UFW 默认行为可能不符合直觉，上线前在测试机验证。

---

## 12. 总结

- UFW 是 Ubuntu/Debian 上实用的主机防火墙前端，底层落在 netfilter（iptables/nftables）。
- 标准做法：安装 → 设默认策略 → **先放行 SSH** → 放行业务端口 → `enable` → `status` 验证。
- 日常用 `allow` / `deny` / `limit`、来源限制、Application Profile、`status numbered` + `delete` 即可覆盖大多数需求。
- 日志与云安全组是排障的两把钥匙；复杂 NAT/转发再考虑 `before.rules`。

### 下一步建议

1. 在测试机完整走一遍「场景 A」，确认 enable 后 SSH 与 HTTP 均正常。
2. 把生产机的 SSH 改为「仅堡垒机/VPN 网段」并启用 `limit`。
3. 如使用 Docker 或做 NAT 网关，单独验证 UFW 与容器/转发规则的兼容性。
4. 将本机实际规则导出备份：`sudo ufw status verbose > ~/ufw-status-$(date +%F).txt`

---

## 附录 A：命令速查

```bash
# 安装 / 版本
sudo apt install -y ufw
ufw version

# 状态
sudo ufw status
sudo ufw status verbose
sudo ufw status numbered

# 默认策略
sudo ufw default deny incoming
sudo ufw default allow outgoing

# 启用 / 关闭 / 重载 / 重置
sudo ufw enable
sudo ufw disable
sudo ufw reload
sudo ufw reset                 # 危险：清空规则

# 放行 / 拒绝 / 限速
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw deny 23/tcp
sudo ufw reject 25/tcp
sudo ufw limit 22/tcp

# 来源限制
sudo ufw allow from 10.0.0.0/8 to any port 22 proto tcp
sudo ufw allow from 203.0.113.10 to any port 5432 proto tcp

# 插入与删除
sudo ufw insert 1 allow from 10.0.0.0/8 to any port 22 proto tcp
sudo ufw delete allow 80/tcp
sudo ufw delete 3              # 先 status numbered

# 应用 Profile
sudo ufw app list
sudo ufw app info OpenSSH
sudo ufw allow OpenSSH

# 日志
sudo ufw logging on
sudo ufw logging medium
sudo journalctl -u ufw -f
sudo tail -f /var/log/ufw.log
```

## 附录 B：启用前检查清单（远程主机）

- [ ] 已确认 SSH 实际端口
- [ ] 已执行 `ufw allow`（端口或 OpenSSH），且 `ufw status` 能看到
- [ ] 若限制了来源 IP，当前客户端 IP 在允许范围内
- [ ] 云安全组已放行对应端口
- [ ] 另有控制台 / VNC / 救援方式可登录
- [ ] 再执行 `ufw enable`

## 附录 C：参考链接

- Ubuntu Server 文档：UFW（以你所用 Ubuntu 版本的官方文档为准）
- `man ufw`
- `man ufw-framework`（了解 before/after rules 与框架细节）
