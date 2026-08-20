# iptables 从入门到生产实践

## 1. 文档概述

### 解决什么问题

本文说明如何在 Linux 上使用 **iptables** 管理 IPv4 包过滤与 NAT，包括：

- 理解 Netfilter、表、链、规则和连接跟踪之间的关系
- 查看、添加、插入、删除和验证规则
- 配置 SSH、Web、数据库白名单等主机防火墙策略
- 配置 SNAT、MASQUERADE、DNAT 和端口转发
- 使用自定义链、日志、限速和计数器组织生产规则
- 安全地在远程服务器修改规则，并在失败时自动回滚
- 保存、恢复和迁移规则
- 排查“端口不通”“规则不生效”“重启后规则消失”等问题

### 适合哪些读者

- Linux 运维、SRE、网络管理员和后端开发
- 已了解 IP、TCP/UDP、端口、网卡和路由的基本概念
- 需要维护旧有 iptables 规则，或排查由 Docker、Kubernetes、UFW、firewalld 生成的底层规则

### 阅读前先记住

1. **iptables 主要处理 IPv4；IPv6 需要使用 `ip6tables`，或改用 nftables 的 `inet` family。**
2. **规则按顺序匹配。** 前面的规则可能让后面的规则永远无法命中。
3. **远程变更必须先备份、先放行管理连接、再收紧默认策略，并准备自动回滚。**
4. **不要同时让多个工具管理同一套规则。** UFW、firewalld、Docker、Kubernetes 和安全软件都可能修改底层规则。
5. **新部署优先评估 nftables。** iptables 仍可使用，但不少新系统中的 `iptables` 命令实际通过 `iptables-nft` 操作 nftables 内核框架。

### 范围说明

- 示例以 Linux IPv4 为主，命令默认由具备 `sudo` 权限的用户执行。
- 本文讲解 iptables 用户态命令，不展开 Netfilter 内核模块开发。
- 云安全组、VPC ACL、WAF 与主机防火墙处于不同位置，不能互相完全替代。
- 不同发行版的持久化方式不同，执行前应确认系统版本和当前防火墙管理方式。

---

## 2. iptables、Netfilter 与 nftables 的关系

### 2.1 Netfilter 是什么

**Netfilter** 是 Linux 内核中的网络包处理框架。它在数据包进入、转发和发出主机的关键位置提供 hook，防火墙、NAT、连接跟踪等功能都建立在这些 hook 上。

### 2.2 iptables 是什么

iptables 是配置 Netfilter 规则的用户态工具。管理员通过命令定义：

- 什么数据包需要匹配
- 数据包在哪个处理阶段匹配
- 匹配后执行什么动作

iptables 规则通常由以下部分组成：

```text
表（table） → 链（chain） → 规则（rule） → 匹配条件（match） → 动作（target）
```

例如：

```bash
sudo iptables -t filter -A INPUT -p tcp --dport 443 -j ACCEPT
```

含义：

- `-t filter`：操作 `filter` 表；省略时也是该表
- `-A INPUT`：把规则追加到 `INPUT` 链
- `-p tcp --dport 443`：匹配目标 TCP 443 端口
- `-j ACCEPT`：允许数据包通过

### 2.3 iptables-legacy 与 iptables-nft

iptables 1.8 系列常见两种后端：

| 后端 | 说明 |
|------|------|
| `iptables-legacy` | 使用旧的 x_tables 内核接口 |
| `iptables-nft` | 保留 iptables 命令语法，但把规则写入 nftables 基础设施 |

检查当前版本和后端：

```bash
sudo iptables -V
sudo ip6tables -V
```

可能看到：

```text
iptables v1.8.x (nf_tables)
```

或：

```text
iptables v1.8.x (legacy)
```

Debian/Ubuntu 还可以查看 alternatives：

```bash
update-alternatives --display iptables
```

> 不要混用 `iptables-legacy` 与 `iptables-nft` 写规则。两套后端看到的规则可能不同，容易出现“明明添加了规则，另一个命令却看不到”的现象。

### 2.4 什么时候继续使用 iptables

适合继续使用：

- 现有系统已经稳定运行大量 iptables 规则
- 第三方程序只提供 iptables 集成
- 临时排查或维护旧系统
- Docker、Kubernetes 等组件仍通过 iptables 兼容接口生成规则

新系统从零设计复杂防火墙时，通常更适合直接使用 nftables。nftables 支持统一处理 IPv4/IPv6、集合、映射和原子规则加载，规则组织能力更强。

---

## 3. 数据包经过哪些链

理解数据包方向比背命令更重要。

### 3.1 发往本机

```text
外部数据包
    │
    ▼
PREROUTING
    │
    ▼
路由判断：目标是本机
    │
    ▼
INPUT
    │
    ▼
本机进程
```

例如别人访问本机 SSH、Nginx、MySQL，主要检查 `INPUT` 链。

### 3.2 由本机发出

```text
本机进程
    │
    ▼
OUTPUT
    │
    ▼
POSTROUTING
    │
    ▼
外部网络
```

例如本机访问软件源、DNS、数据库，主要检查 `OUTPUT` 链。

### 3.3 经过本机转发

```text
外部或内网数据包
    │
    ▼
PREROUTING
    │
    ▼
路由判断：目标不是本机
    │
    ▼
FORWARD
    │
    ▼
POSTROUTING
    │
    ▼
另一块网卡或下一跳
```

网关、路由器、容器宿主机和 DNAT 端口转发主要涉及 `FORWARD` 链。

### 3.4 最常见的方向判断错误

- 访问本机服务却修改 `FORWARD`
- 做 DNAT 后只写 `nat` 规则，没有放行 `FORWARD`
- 本机访问外部失败却只检查 `INPUT`
- 误以为云安全组放行后，本机 `INPUT` 一定会放行

---

## 4. 表与内置链

### 4.1 filter 表

默认表，用于允许或阻止数据包。

| 链 | 用途 |
|----|------|
| `INPUT` | 进入本机的数据包 |
| `OUTPUT` | 本机发出的数据包 |
| `FORWARD` | 经本机转发的数据包 |

不指定 `-t` 时默认操作 `filter`：

```bash
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
```

等价于：

```bash
sudo iptables -t filter -A INPUT -p tcp --dport 22 -j ACCEPT
```

### 4.2 nat 表

用于网络地址转换。常见链：

| 链 | 常见用途 |
|----|----------|
| `PREROUTING` | 路由判断前修改目标地址，常用于 DNAT |
| `OUTPUT` | 修改本机产生流量的目标地址 |
| `POSTROUTING` | 数据包离开前修改源地址，常用于 SNAT/MASQUERADE |

`nat` 表通常只处理连接的首个数据包，后续数据包由连接跟踪应用相同转换。因此不要把它当成逐包过滤表。

### 4.3 mangle 表

用于修改数据包相关属性，例如：

- 设置 `MARK`
- 修改 DSCP/TOS
- 配合策略路由
- 调整部分 TCP 属性

没有明确需求时不要使用。

### 4.4 raw 表

在连接跟踪之前处理数据包，常用于：

- 使用 `NOTRACK` 绕过连接跟踪
- 特殊高性能或故障排查场景

绕过连接跟踪会影响状态防火墙和 NAT，生产环境慎用。

### 4.5 security 表

可用于强制访问控制系统的安全标记处理，例如 SELinux。普通主机防火墙很少直接修改。

---

## 5. 命令结构与常用操作

### 5.1 通用结构

```bash
iptables [-t 表] 操作 链 [匹配条件] [-j 动作]
```

### 5.2 常用操作

| 操作 | 长选项 | 说明 |
|------|--------|------|
| `-A` | `--append` | 追加规则到链末尾 |
| `-I` | `--insert` | 插入规则，默认插到第一条 |
| `-R` | `--replace` | 替换指定编号规则 |
| `-D` | `--delete` | 按规则内容或编号删除 |
| `-C` | `--check` | 检查规则是否存在，不修改 |
| `-L` | `--list` | 以列表形式查看 |
| `-S` | `--list-rules` | 以接近命令的形式查看 |
| `-N` | `--new-chain` | 创建自定义链 |
| `-X` | `--delete-chain` | 删除空且未被引用的自定义链 |
| `-F` | `--flush` | 清空链中的规则 |
| `-P` | `--policy` | 设置内置链默认策略 |
| `-Z` | `--zero` | 清零包和字节计数器 |

### 5.3 查看规则

推荐日常查看：

```bash
sudo iptables -L -n -v --line-numbers
```

参数含义：

- `-L`：列出规则
- `-n`：不解析主机名和服务名，直接显示数字
- `-v`：显示接口、计数器等详细信息
- `--line-numbers`：显示规则编号

只看某条链：

```bash
sudo iptables -L INPUT -n -v --line-numbers
```

查看 NAT：

```bash
sudo iptables -t nat -L -n -v --line-numbers
```

查看可复用的规则语法：

```bash
sudo iptables -S
sudo iptables -t nat -S
```

查看完整规则集：

```bash
sudo iptables-save
```

### 5.4 添加和插入

追加到末尾：

```bash
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
```

插到第一条：

```bash
sudo iptables -I INPUT 1 -p tcp --dport 22 -j ACCEPT
```

追加适合规则顺序已经规划好的场景；紧急放行时常使用插入，但事后要整理，避免规则越来越混乱。

### 5.5 检查规则是否存在

```bash
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT
echo $?
```

- 返回 `0`：规则存在
- 非 `0`：不存在或检查失败

脚本中可以避免重复添加：

```bash
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null ||
  sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
```

### 5.6 删除规则

按完整内容删除：

```bash
sudo iptables -D INPUT -p tcp --dport 443 -j ACCEPT
```

按编号删除：

```bash
sudo iptables -L INPUT -n --line-numbers
sudo iptables -D INPUT 3
```

> 删除一条规则后，后续编号会立即变化。连续删除多条规则时，应每次重新查看编号，或从最大编号向前删除。

### 5.7 清空规则与自定义链

清空 `filter` 表中的规则：

```bash
sudo iptables -F
```

清空指定链：

```bash
sudo iptables -F INPUT
```

清空 NAT：

```bash
sudo iptables -t nat -F
```

删除未使用的自定义链：

```bash
sudo iptables -X
```

这些命令风险很高：

- `-F` 只清规则，不会自动把默认策略改回 `ACCEPT`
- 如果默认策略已经是 `DROP`，清空放行规则可能立即断网
- Docker、Kubernetes、UFW、firewalld 创建的规则也可能被破坏

生产服务器上不要把 `iptables -F` 当作“恢复默认”的通用命令。

---

## 6. 规则如何匹配

### 6.1 协议

```bash
sudo iptables -A INPUT -p tcp -j ACCEPT
sudo iptables -A INPUT -p udp -j ACCEPT
sudo iptables -A INPUT -p icmp -j ACCEPT
```

端口匹配通常需要先指定 TCP 或 UDP：

```bash
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
```

### 6.2 源和目标地址

允许单个源地址：

```bash
sudo iptables -A INPUT -s 192.0.2.10/32 -j ACCEPT
```

允许整个网段：

```bash
sudo iptables -A INPUT -s 10.20.0.0/16 -j ACCEPT
```

匹配目标地址：

```bash
sudo iptables -A OUTPUT -d 198.51.100.20/32 -j ACCEPT
```

示例中的 `192.0.2.0/24`、`198.51.100.0/24`、`203.0.113.0/24` 是文档保留地址，使用时必须替换成实际地址。

### 6.3 源端口与目标端口

```bash
# 访问本机 HTTPS：目标端口为 443
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT

# 匹配来自某源端口的数据包
sudo iptables -A INPUT -p tcp --sport 443 -j ACCEPT
```

现代状态防火墙通常用 `ESTABLISHED,RELATED` 放行返回流量，不建议单纯依赖 `--sport 443` 判断它是可信响应。

### 6.4 多端口匹配

```bash
sudo iptables -A INPUT \
  -p tcp -m multiport --dports 80,443,8443 \
  -j ACCEPT
```

端口范围：

```bash
sudo iptables -A INPUT -p tcp --dport 8000:8100 -j ACCEPT
```

### 6.5 网卡

匹配进入接口：

```bash
sudo iptables -A INPUT -i eth0 -p tcp --dport 443 -j ACCEPT
```

匹配离开接口：

```bash
sudo iptables -A OUTPUT -o eth0 -p tcp --dport 443 -j ACCEPT
```

`FORWARD` 链可以同时匹配：

```bash
sudo iptables -A FORWARD \
  -i eth1 -o eth0 \
  -s 10.20.0.0/16 \
  -j ACCEPT
```

查看实际网卡名：

```bash
ip -br link
ip -br addr
```

### 6.6 取反匹配

`!` 表示“不匹配该条件”：

```bash
sudo iptables -A INPUT ! -s 10.20.0.0/16 -p tcp --dport 3306 -j DROP
```

取反规则不直观，复杂规则中应优先使用明确的白名单链，降低误读风险。

### 6.7 TCP 标志

只匹配新发起连接的 SYN：

```bash
sudo iptables -A INPUT \
  -p tcp --syn --dport 22 \
  -j ACCEPT
```

更常见的生产写法是配合连接跟踪：

```bash
sudo iptables -A INPUT \
  -p tcp --dport 22 \
  -m conntrack --ctstate NEW \
  -j ACCEPT
```

### 6.8 MAC 地址

```bash
sudo iptables -A INPUT \
  -m mac --mac-source 00:11:22:33:44:55 \
  -j ACCEPT
```

MAC 地址只在同一二层网络内有意义，流量经过路由器后看到的是相邻设备的 MAC，不能作为跨网段身份认证手段。

---

## 7. 连接跟踪与状态防火墙

### 7.1 为什么需要连接跟踪

TCP 请求和响应方向相反，UDP 虽然无连接，内核也会为其维护临时状态。连接跟踪让防火墙知道一个数据包属于：

- 新连接
- 已建立连接
- 与现有连接相关的辅助连接
- 无法识别的异常状态

### 7.2 常见状态

| 状态 | 含义 |
|------|------|
| `NEW` | 新连接的首批数据包 |
| `ESTABLISHED` | 已建立连接中的数据包 |
| `RELATED` | 与已有连接相关的新流量 |
| `INVALID` | 无法归入正常连接状态 |

典型规则：

```bash
sudo iptables -A INPUT \
  -m conntrack --ctstate ESTABLISHED,RELATED \
  -j ACCEPT

sudo iptables -A INPUT \
  -m conntrack --ctstate INVALID \
  -j DROP
```

放行 SSH 新连接：

```bash
sudo iptables -A INPUT \
  -p tcp --dport 22 \
  -m conntrack --ctstate NEW \
  -j ACCEPT
```

### 7.3 推荐的基础顺序

主机 `INPUT` 链通常按以下顺序组织：

1. 允许回环接口
2. 丢弃 `INVALID`
3. 允许 `ESTABLISHED,RELATED`
4. 允许明确的新连接
5. 对未匹配流量限速记录日志
6. 拒绝或依靠默认 `DROP`

顺序不是强制标准，需要结合业务、性能和审计要求调整。

---

## 8. target：匹配后执行什么

### 8.1 ACCEPT、DROP 与 REJECT

```bash
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 23 -j DROP
sudo iptables -A INPUT -p tcp --dport 25 -j REJECT --reject-with tcp-reset
```

区别：

| target | 行为 | 常见用途 |
|--------|------|----------|
| `ACCEPT` | 允许通过 | 放行业务 |
| `DROP` | 静默丢弃 | 不向扫描者返回信息；客户端等待超时 |
| `REJECT` | 明确拒绝 | 内网策略、快速失败、便于排障 |

### 8.2 LOG

记录未匹配入站流量：

```bash
sudo iptables -A INPUT \
  -m limit --limit 5/min --limit-burst 10 \
  -j LOG --log-prefix "iptables-input-drop: " --log-level 6
```

`LOG` 通常不会终止规则遍历，因此后面仍需 `DROP`：

```bash
sudo iptables -A INPUT -j DROP
```

查看日志：

```bash
sudo journalctl -k
sudo journalctl -k -g 'iptables-input-drop'
sudo dmesg --color=always | less -R
```

具体日志文件取决于 journald、rsyslog 和发行版配置，可能出现在 `/var/log/kern.log` 或 `/var/log/messages`。

> 日志规则必须限速。直接记录所有被丢弃的数据包可能造成日志洪水、磁盘写满或影响性能。

### 8.3 自定义链与 RETURN

创建业务链：

```bash
sudo iptables -N WEB_IN
sudo iptables -A WEB_IN -p tcp -m multiport --dports 80,443 -j ACCEPT
sudo iptables -A WEB_IN -j RETURN
sudo iptables -A INPUT -j WEB_IN
```

`RETURN` 表示返回调用它的上一条链，继续处理调用点之后的规则。

自定义链适合：

- 按业务拆分规则
- 复用相同匹配逻辑
- 避免单条内置链过长
- 给 Docker、监控、数据库等规则划分清晰边界

---

## 9. 常见主机防火墙场景

### 9.1 允许回环接口

```bash
sudo iptables -A INPUT -i lo -j ACCEPT
sudo iptables -A OUTPUT -o lo -j ACCEPT
```

许多本机服务通过 `127.0.0.1` 通信，错误阻止回环流量可能导致 DNS 缓存、数据库代理、监控代理或应用异常。

### 9.2 只允许指定地址访问 SSH

```bash
sudo iptables -A INPUT \
  -p tcp -s 203.0.113.10/32 --dport 22 \
  -m conntrack --ctstate NEW \
  -j ACCEPT
```

使用前确认：

- SSH 实际监听端口
- 管理员出口地址是否固定
- 是否经过 VPN、跳板机或 NAT
- 云安全组是否也允许该来源

### 9.3 放行 HTTP 和 HTTPS

```bash
sudo iptables -A INPUT \
  -p tcp -m multiport --dports 80,443 \
  -m conntrack --ctstate NEW \
  -j ACCEPT
```

### 9.4 只允许内网访问数据库

MySQL：

```bash
sudo iptables -A INPUT \
  -p tcp -s 10.20.0.0/16 --dport 3306 \
  -m conntrack --ctstate NEW \
  -j ACCEPT
```

PostgreSQL：

```bash
sudo iptables -A INPUT \
  -p tcp -s 10.20.0.0/16 --dport 5432 \
  -m conntrack --ctstate NEW \
  -j ACCEPT
```

防火墙放行不等于数据库可以安全暴露。仍需配置数据库监听地址、账号权限、TLS 和应用鉴权。

### 9.5 放行 ICMP

允许 ping：

```bash
sudo iptables -A INPUT \
  -p icmp --icmp-type echo-request \
  -m limit --limit 10/second --limit-burst 20 \
  -j ACCEPT
```

不要简单认为“禁用所有 ICMP 更安全”。ICMP 还承担错误通知和路径 MTU 发现等功能。是否限制应结合网络环境设计。

### 9.6 简单限制连接速率

限制 SSH 新连接速率：

```bash
sudo iptables -A INPUT \
  -p tcp --dport 22 \
  -m conntrack --ctstate NEW \
  -m limit --limit 6/min --limit-burst 10 \
  -j ACCEPT
```

这只是粗粒度限速，不替代：

- SSH 密钥认证
- 禁止 root 密码登录
- fail2ban
- VPN 或堡垒机
- 云侧访问控制

---

## 10. 默认策略与完整主机规则

### 10.1 查看默认策略

```bash
sudo iptables -S | grep '^-P'
```

可能看到：

```text
-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
```

### 10.2 设置默认策略

```bash
sudo iptables -P INPUT DROP
sudo iptables -P FORWARD DROP
sudo iptables -P OUTPUT ACCEPT
```

> 远程服务器不要直接先执行 `iptables -P INPUT DROP`。必须先确认当前 SSH 已被明确放行，并准备控制台或自动回滚。

### 10.3 一份可审查的规则文件

下面是模板，不应未经修改直接用于生产。将 `203.0.113.10/32` 替换成真实管理地址：

```iptables
*filter

:INPUT DROP [0:0]
:FORWARD DROP [0:0]
:OUTPUT ACCEPT [0:0]

# 回环接口
-A INPUT -i lo -j ACCEPT

# 异常连接状态
-A INPUT -m conntrack --ctstate INVALID -j DROP

# 已建立连接及关联流量
-A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

# 管理员 SSH 白名单
-A INPUT -p tcp -s 203.0.113.10/32 --dport 22 -m conntrack --ctstate NEW -j ACCEPT

# Web 服务
-A INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT

# 有限放行 ping
-A INPUT -p icmp --icmp-type echo-request -m limit --limit 10/second --limit-burst 20 -j ACCEPT

# 对最终丢弃流量进行限速记录
-A INPUT -m limit --limit 5/min --limit-burst 10 -j LOG --log-prefix "iptables-input-drop: " --log-level 6

-A INPUT -j DROP

COMMIT
```

建议保存为：

```text
/etc/iptables/rules.v4
```

为兼容不同版本的 `iptables-restore`，规则文件中的每条 `-A` 规则保持单行。

### 10.4 为什么规则文件优于大量单条命令

- 便于版本管理和评审
- 可以先测试语法
- 规则加载更集中
- 避免脚本执行到一半后留下半套规则
- 可以用 `iptables-apply` 设置超时回滚

---

## 11. 远程服务器安全变更流程

### 11.1 变更前检查

```bash
# 确认当前客户端来源地址
echo "$SSH_CONNECTION"

# 确认 SSH 监听端口
sudo ss -lntp | grep ssh

# 查看当前规则和默认策略
sudo iptables -S
sudo iptables -t nat -S

# 备份完整 IPv4 规则
sudo sh -c 'iptables-save > /tmp/iptables-before-change.v4'

# 同时检查 IPv6
sudo ip6tables -S
```

不要把包含内部网络结构的规则备份随意上传到公开位置。

### 11.2 测试规则文件语法

如果当前版本支持：

```bash
sudo iptables-restore --test /etc/iptables/rules.v4
```

也可以使用标准输入：

```bash
sudo iptables-restore --test < /etc/iptables/rules.v4
```

语法测试只证明格式可解析，不证明业务流量一定能通过。

### 11.3 使用 iptables-apply 自动回滚

如果系统提供 `iptables-apply`：

```bash
sudo iptables-apply -t 60 /etc/iptables/rules.v4
```

它加载规则后要求确认。若新规则切断 SSH，会话无法确认，超时后会尝试恢复之前的规则。

执行前检查命令是否存在：

```bash
command -v iptables-apply
```

### 11.4 应用后的验证

不要只看当前 SSH 没断。应从另一个终端重新建立连接并验证：

```bash
ssh -p 22 user@server
curl -I http://server
curl -Ik https://server
```

服务器上检查：

```bash
sudo iptables -L -n -v --line-numbers
sudo ss -lntup
sudo journalctl -k -g 'iptables'
```

### 11.5 故障回滚

如果仍能使用控制台：

```bash
sudo sh -c 'iptables-restore < /tmp/iptables-before-change.v4'
```

云服务器应提前确认串口控制台、VNC、救援模式或带外管理是否可用。不要等 SSH 失联后才确认。

---

## 12. NAT 与路由转发

### 12.1 开启 IPv4 转发

临时开启：

```bash
sudo sysctl -w net.ipv4.ip_forward=1
```

查看当前值：

```bash
sysctl net.ipv4.ip_forward
```

永久配置可写入专用 sysctl 文件：

```text
/etc/sysctl.d/99-ip-forward.conf
```

内容：

```ini
net.ipv4.ip_forward = 1
```

加载：

```bash
sudo sysctl --system
```

开启转发只是允许内核路由数据包；仍需正确的路由、`FORWARD` 规则和必要的 NAT。

### 12.2 MASQUERADE：动态公网地址

假设：

- 内网网段：`10.20.0.0/16`
- 外网接口：`eth0`
- 内网接口：`eth1`

```bash
sudo iptables -t nat -A POSTROUTING \
  -s 10.20.0.0/16 -o eth0 \
  -j MASQUERADE
```

允许内网访问外网：

```bash
sudo iptables -A FORWARD \
  -i eth1 -o eth0 \
  -s 10.20.0.0/16 \
  -m conntrack --ctstate NEW,ESTABLISHED,RELATED \
  -j ACCEPT

sudo iptables -A FORWARD \
  -i eth0 -o eth1 \
  -d 10.20.0.0/16 \
  -m conntrack --ctstate ESTABLISHED,RELATED \
  -j ACCEPT
```

`MASQUERADE` 适合出口地址可能变化的场景，例如拨号或动态云网卡。

### 12.3 SNAT：固定公网地址

出口地址固定时：

```bash
sudo iptables -t nat -A POSTROUTING \
  -s 10.20.0.0/16 -o eth0 \
  -j SNAT --to-source 198.51.100.10
```

固定地址场景通常优先使用 SNAT，规则意图更明确。

### 12.4 DNAT：端口转发

把公网接口 TCP 8080 转发到 `10.20.0.50:80`：

```bash
sudo iptables -t nat -A PREROUTING \
  -i eth0 -p tcp --dport 8080 \
  -j DNAT --to-destination 10.20.0.50:80
```

放行转发：

```bash
sudo iptables -A FORWARD \
  -i eth0 -o eth1 \
  -p tcp -d 10.20.0.50 --dport 80 \
  -m conntrack --ctstate NEW,ESTABLISHED,RELATED \
  -j ACCEPT

sudo iptables -A FORWARD \
  -i eth1 -o eth0 \
  -p tcp -s 10.20.0.50 --sport 80 \
  -m conntrack --ctstate ESTABLISHED,RELATED \
  -j ACCEPT
```

如果内网目标的默认网关不是这台 NAT 主机，返回数据包可能绕过 NAT 主机，导致连接失败。解决方法通常是：

- 修正目标主机回程路由；或
- 在确认网络设计后，对转发流量增加 SNAT/MASQUERADE

### 12.5 REDIRECT：重定向到本机端口

把本机收到的 TCP 80 重定向到本机 8080：

```bash
sudo iptables -t nat -A PREROUTING \
  -p tcp --dport 80 \
  -j REDIRECT --to-ports 8080
```

常用于透明代理或本地服务端口转换。应用需要正确处理被重定向的连接。

### 12.6 NAT 排障检查表

```bash
sysctl net.ipv4.ip_forward
ip route
sudo iptables -t nat -L -n -v --line-numbers
sudo iptables -L FORWARD -n -v --line-numbers
sudo conntrack -L 2>/dev/null
sudo tcpdump -i any -nn 'host 10.20.0.50 and tcp port 80'
```

重点确认：

- 包是否到达入口接口
- DNAT 规则计数器是否增加
- `FORWARD` 是否放行
- 目标主机是否监听
- 目标主机是否有回程路由
- 返回流量是否重新经过 NAT 主机

---

## 13. IPv6

iptables 不会自动覆盖 IPv6。查看 IPv6 规则：

```bash
sudo ip6tables -S
sudo ip6tables -L -n -v --line-numbers
```

如果 IPv4 设置为默认拒绝，但 IPv6 仍允许全部入站，服务可能继续通过 IPv6 暴露。

处理方式：

1. 为 `ip6tables` 编写对应规则；或
2. 使用 nftables `inet` family 统一处理 IPv4 和 IPv6；或
3. 确认确实不使用 IPv6后，再按发行版和网络规范正确禁用，而不是仅删除地址。

IPv6 不使用 IPv4 的广播和 ARP，依赖 ICMPv6 完成邻居发现、路径 MTU 等功能。不要照搬“丢弃全部 ICMP”的规则。

---

## 14. 保存、恢复与持久化

### 14.1 导出规则

导出全部 IPv4 规则：

```bash
sudo iptables-save
```

保存到文件：

```bash
sudo sh -c 'iptables-save > /etc/iptables/rules.v4'
```

包含当前包和字节计数器：

```bash
sudo iptables-save -c
```

IPv6：

```bash
sudo sh -c 'ip6tables-save > /etc/iptables/rules.v6'
```

### 14.2 恢复规则

```bash
sudo sh -c 'iptables-restore < /etc/iptables/rules.v4'
sudo sh -c 'ip6tables-restore < /etc/iptables/rules.v6'
```

默认恢复行为和可用参数应以当前系统的手册为准：

```bash
man iptables-restore
```

### 14.3 Debian/Ubuntu

常见方案是安装：

```bash
sudo apt install iptables-persistent
```

保存当前规则：

```bash
sudo netfilter-persistent save
```

查看服务：

```bash
systemctl status netfilter-persistent
```

通常使用：

```text
/etc/iptables/rules.v4
/etc/iptables/rules.v6
```

> 安装过程可能询问是否保存当前规则。执行前先确认当前规则确实是希望持久化的版本。

### 14.4 RHEL、Rocky Linux、AlmaLinux

现代 RHEL 系发行版通常以 firewalld/nftables 为主，不建议默认新建一套独立的 iptables 持久化机制。先确认：

```bash
sudo systemctl status firewalld
sudo nft list ruleset
sudo iptables -V
```

旧版系统可能使用 `iptables-services` 和 `/etc/sysconfig/iptables`，但包可用性、支持状态与启动方式依发行版大版本不同，应查对应版本文档。

### 14.5 不要同时启用多个规则管理器

常见冲突组合：

- UFW + 手工维护完整 iptables 规则
- firewalld + 自定义 `iptables-restore` systemd 服务
- nftables 服务 + iptables-legacy
- 多个启动脚本重复清空和恢复规则

排查重启后规则变化时，检查：

```bash
systemctl list-unit-files | grep -E 'ufw|firewalld|nftables|iptables|netfilter'
systemctl list-timers --all
```

---

## 15. Docker、Kubernetes 与其他管理工具

### 15.1 Docker

Docker 常在 `filter` 和 `nat` 表创建：

- `DOCKER`
- `DOCKER-USER`
- `DOCKER-FORWARD`
- 与端口映射和网桥相关的规则

查看：

```bash
sudo iptables -S | grep DOCKER
sudo iptables -t nat -S | grep DOCKER
```

一般建议把管理员自定义的容器入口过滤放在 `DOCKER-USER` 链，而不是直接修改 Docker 自动生成的链：

```bash
sudo iptables -I DOCKER-USER 1 \
  -s 203.0.113.10/32 \
  -j ACCEPT
```

具体规则仍需结合容器网段、端口发布方式和默认返回策略设计。

不要在运行 Docker 的主机上随意执行：

```bash
sudo iptables -F
sudo iptables -t nat -F
```

这可能破坏容器网络和端口映射。

### 15.2 Kubernetes

使用 iptables 模式的 kube-proxy 会创建大量 `KUBE-*` 链。CNI 插件也可能维护自己的链。

排查时可以查看：

```bash
sudo iptables-save | grep -E 'KUBE-|CNI-|CALI-|CILIUM'
```

不要手工编辑自动生成链；控制器下一次同步可能覆盖修改。应从 Service、NetworkPolicy、CNI 配置或 kube-proxy 配置解决问题。

### 15.3 UFW 和 firewalld

UFW、firewalld 都是上层防火墙管理器。使用它们时：

- 日常规则优先通过对应工具管理
- `iptables -L` 可用于底层观察
- 不要同时手工清空底层规则
- 复杂 NAT 或例外规则需遵循对应工具的扩展方式

相关笔记：[[ufw-usage-guide]]

---

## 16. 排障方法

### 16.1 先确认是不是防火墙问题

按以下顺序排查：

```bash
# 1. 服务是否监听
sudo ss -lntup

# 2. 地址和路由是否正确
ip -br addr
ip route

# 3. 数据包是否到达
sudo tcpdump -i any -nn 'tcp port 443'

# 4. 防火墙规则和计数器
sudo iptables -L -n -v --line-numbers

# 5. NAT 和转发
sudo iptables -t nat -L -n -v --line-numbers
sysctl net.ipv4.ip_forward
```

相关笔记：[[tcpdump-guide]]

### 16.2 规则计数器不增加

可能原因：

- 包没有到达主机
- 抓错协议、端口、源地址或网卡
- 数据包走 IPv6，而你查看的是 IPv4
- 前面的规则已经接受或丢弃
- 查看了错误的表或后端
- 流量走其他网络 namespace

检查：

```bash
sudo iptables -L INPUT -n -v --line-numbers
sudo ip6tables -L INPUT -n -v --line-numbers
sudo iptables -V
sudo nft list ruleset
```

### 16.3 规则存在但端口仍不通

防火墙只决定包是否通过，不负责启动服务：

```bash
sudo ss -lntp | grep ':443'
curl -vk https://127.0.0.1:443/
```

还需检查：

- 服务是否只监听 `127.0.0.1`
- 云安全组是否放行
- 上游路由或 ACL 是否允许
- SELinux 是否阻止服务访问资源
- 应用是否正常返回

### 16.4 默认策略导致误判

```bash
sudo iptables -S | grep '^-P'
```

链中没有显式 `DROP` 不代表会放行；默认策略可能是 `DROP`。

### 16.5 规则顺序错误

例如：

```bash
-A INPUT -p tcp --dport 22 -j DROP
-A INPUT -p tcp -s 203.0.113.10/32 --dport 22 -j ACCEPT
```

第二条永远无法放行，因为第一条已经丢弃所有 SSH 流量。把精确白名单放在广泛拒绝之前。

### 16.6 NAT 规则命中但连接失败

重点检查：

- `FORWARD` 默认策略
- 回程路由
- 目标服务监听地址
- rp_filter
- conntrack 表是否满
- 云平台是否允许源/目的地址检查外的转发

查看内核消息：

```bash
sudo journalctl -k | grep -iE 'conntrack|nf_conntrack|drop'
```

### 16.7 连接跟踪表

如果安装了 `conntrack-tools`：

```bash
sudo conntrack -L
sudo conntrack -S
```

查看容量：

```bash
sysctl net.netfilter.nf_conntrack_count
sysctl net.netfilter.nf_conntrack_max
```

不要在没有容量评估的情况下随意调大上限；连接跟踪会消耗内存。

### 16.8 网络 namespace

容器流量可能位于其他 namespace：

```bash
ip netns list
sudo nsenter -t PID -n iptables -S
```

其中 `PID` 必须替换成目标进程 PID。宿主机规则、容器 namespace 规则和云侧规则需要分别检查。

---

## 17. 常见错误与风险

### 17.1 先 DROP，后放行 SSH

错误顺序：

```bash
sudo iptables -P INPUT DROP
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
```

第一条执行后当前连接可能立即受影响。正确做法是先确认并放行管理来源，再收紧策略，并使用自动回滚。

### 17.2 把 `-F` 当作关闭防火墙

`iptables -F` 只清空规则。若策略为 `DROP`，清空后反而可能全部阻断。

如需临时恢复宽松策略，必须完整评估所有表、链、IPv6、容器和管理器状态，不建议在生产机用几条通用命令粗暴处理。

### 17.3 只配置 IPv4

服务监听 `[::]:443` 时可能同时接受 IPv6。必须检查：

```bash
sudo ss -lntup
sudo ip6tables -S
```

### 17.4 重启后规则消失

iptables 内核规则本身通常不会自动持久化。需要使用发行版提供的规则管理服务，或由配置管理系统在启动时恢复。

### 17.5 将主机防火墙当成唯一防线

完整访问控制通常包括：

- 云安全组或上游 ACL
- 主机防火墙
- 服务监听地址
- 应用鉴权与 TLS
- 审计、监控和告警

### 17.6 在生产机直接复制未知脚本

应用前至少检查：

- 是否包含 `-F`、`-X` 或修改默认策略
- 是否覆盖 Docker/Kubernetes 链
- 是否包含本机实际 SSH 端口
- IPv4 与 IPv6 是否一致
- 是否有恢复路径

---

## 18. 脚本编写建议

### 18.1 幂等检查

```bash
if ! sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
  sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
fi
```

规则多时优先生成完整 `iptables-restore` 文件，而不是堆积大量 `-C` 与 `-A`。

### 18.2 等待 xtables 锁

多个程序同时操作规则时可能出现锁竞争。较新版本支持：

```bash
sudo iptables -w 10 -A INPUT -p tcp --dport 443 -j ACCEPT
```

表示最多等待 xtables 锁 10 秒。具体参数以本机 `iptables --help` 和手册为准。

### 18.3 规则注释

```bash
sudo iptables -A INPUT \
  -p tcp --dport 443 \
  -m comment --comment "allow public HTTPS" \
  -j ACCEPT
```

查看：

```bash
sudo iptables -S INPUT
```

注释应说明业务目的、来源或负责人，不要记录密码、令牌等敏感信息。

### 18.4 变更记录

建议记录：

- 变更原因
- 规则文件版本
- 管理来源地址
- 验证结果
- 回滚文件位置
- 与云安全组、Docker、Kubernetes 的关系

---

## 19. 命令速查

### 查看

```bash
sudo iptables -V
sudo iptables -S
sudo iptables -L -n -v --line-numbers
sudo iptables -t nat -L -n -v --line-numbers
sudo iptables-save
sudo ip6tables -S
```

### 添加

```bash
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 1 -p tcp --dport 22 -j ACCEPT
```

### 检查和删除

```bash
sudo iptables -C INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -D INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -D INPUT 3
```

### 默认策略

```bash
sudo iptables -P INPUT DROP
sudo iptables -P FORWARD DROP
sudo iptables -P OUTPUT ACCEPT
```

### 备份和恢复

```bash
sudo sh -c 'iptables-save > /tmp/iptables-backup.v4'
sudo sh -c 'iptables-restore < /tmp/iptables-backup.v4'
sudo iptables-apply -t 60 /etc/iptables/rules.v4
```

### NAT

```bash
sudo sysctl -w net.ipv4.ip_forward=1

sudo iptables -t nat -A POSTROUTING \
  -s 10.20.0.0/16 -o eth0 \
  -j MASQUERADE

sudo iptables -t nat -A PREROUTING \
  -i eth0 -p tcp --dport 8080 \
  -j DNAT --to-destination 10.20.0.50:80
```

---

## 20. 生产变更检查清单

### 变更前

- [ ] 确认当前系统使用 `iptables-legacy` 还是 `iptables-nft`
- [ ] 确认是否由 UFW、firewalld、Docker、Kubernetes 管理规则
- [ ] 确认 SSH 实际端口和当前管理员来源地址
- [ ] 检查 IPv4 与 IPv6
- [ ] 导出当前规则
- [ ] 准备控制台或自动回滚
- [ ] 审查规则顺序和默认策略
- [ ] 测试规则文件语法

### 变更后

- [ ] 从新终端重新建立 SSH
- [ ] 验证业务端口
- [ ] 查看规则计数器
- [ ] 查看内核防火墙日志
- [ ] 验证 NAT 回程
- [ ] 验证 IPv6
- [ ] 确认重启持久化方案
- [ ] 保存最终规则和变更记录

---

## 21. 参考资料

- Netfilter 项目主页：<https://www.netfilter.org/>
- iptables 官方源码与手册：<https://git.netfilter.org/iptables/tree/iptables>
- nftables 官方 Wiki：<https://wiki.nftables.org/>
- nftables 与 iptables 的主要区别：<https://wiki.nftables.org/wiki-nftables/index.php/Main_differences_with_iptables>
- Debian `iptables-apply(8)`：<https://manpages.debian.org/testing/iptables/iptables-apply.8.en.html>
- 本机命令手册：

```bash
man iptables
man iptables-extensions
man iptables-save
man iptables-restore
man iptables-apply
```

文档中的命令是通用示例。涉及生产服务器、远程 SSH、容器平台或云网络时，应以本机版本、现有规则和实际网络拓扑为准。
