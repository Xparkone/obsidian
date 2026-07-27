# SSH 反向隧道（Remote Port Forwarding）配置详解

> 反向隧道允许外部主机通过 SSH 访问内网机器的服务，是内网穿透的核心手段。

---

## 一、原理

```
内网机器 A (无法公网访问)           公网机器 B (有公网 IP)
┌─────────────────────┐              ┌─────────────────────┐
│  localhost:8080     │──SSH 隧道──▶│  B:9000              │
│  (Web 服务)          │  A → B      │  (监听 9000)         │
└─────────────────────┘              └─────────────────────┘
                                              ▲
                                         外部用户访问 B:9000
                                         流量自动转发到 A:8080
```

**一句话**：A 主动连 B，B 上开一个端口，外部访问 B 的那个端口相当于访问 A 的本地服务。

---

## 二、基本命令

```bash
# 在 内网机器 A 上执行
ssh -R [B的监听地址:]B的端口:目标地址:目标端口 username@B的IP

# 最简写法：在 B 上监听 9000，转发到 A 本地的 8080
ssh -R 9000:localhost:8080 user@公网机器B

# 指定 B 监听在 0.0.0.0（允许外部访问）
ssh -R 0.0.0.0:9000:localhost:8080 user@公网机器B

# 转发到另一台机器
ssh -R 9000:192.168.1.50:3306 user@公网机器B
```

### 参数说明

| 参数 | 含义 |
|------|------|
| `-R` | 远程端口转发（Remote） |
| `B的端口` | 在公网机器 B 上监听的端口 |
| `目标地址` | 流量最终转发到的地址（通常是 localhost 或内网 IP） |
| `目标端口` | 最终目标服务的端口 |

---

## 三、场景一：暴露内网 Web 服务

**需求**：内网开发机 `192.168.1.10` 上跑着 `localhost:3000` 的前端项目，想让外部同事访问。

```bash
# 在内网机器上执行
ssh -R 0.0.0.0:9000:localhost:3000 root@公网服务器IP

# 同事访问 http://公网服务器IP:9000 即可
```

**注意**：默认情况下 SSH 只监听 `127.0.0.1`，需要 `0.0.0.0` 才能让外部访问，还需要在 B 上修改 SSH 配置（见第五节）。

---

## 四、场景二：暴露内网数据库

**需求**：本地 `localhost:3306` 的 MySQL，让公网服务器上的应用能通过 `localhost:3307` 访问。

```bash
# 在内网机器上执行，公网机器上监听 3307
ssh -R 3307:localhost:3306 root@公网服务器IP

# 公网服务器上的应用连接
mysql -h 127.0.0.1 -P 3307 -u root -p
```

---

## 五、公网机器 B 的必备配置

默认情况下，SSH 反向隧道只监听 `127.0.0.1`，外部无法访问。需要在 **B 机器** 上修改 `/etc/ssh/sshd_config`：

```bash
# 编辑配置
sudo vim /etc/ssh/sshd_config
```

添加或修改：

```
# 允许远程端口转发绑定到 0.0.0.0
GatewayPorts yes

# 或者改为 clientspecified，由客户端自己决定
# GatewayPorts clientspecified
```

```bash
# 重启 SSH 服务
sudo systemctl restart sshd
```

`GatewayPorts` 的三个选项：

| 值 | 效果 |
|----|------|
| `no` | 强制只监听 127.0.0.1（默认） |
| `yes` | 强制监听 0.0.0.0（`-R` 不写地址也生效） |
| `clientspecified` | 由客户端 `-R` 参数决定（推荐） |

---

## 六、保持隧道稳定（防断开）

SSH 连接长时间无数据交互会被断开，需要加保活参数：

```bash
ssh -R 0.0.0.0:9000:localhost:8080 \
    -o ServerAliveInterval=60 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    root@公网服务器IP
```

| 参数 | 说明 |
|------|------|
| `ServerAliveInterval=60` | 每 60 秒发送心跳包 |
| `ServerAliveCountMax=3` | 连续 3 次心跳失败则断开 |
| `ExitOnForwardFailure=yes` | 端口转发失败立即退出（防止静默失败） |
| `-N` | 不执行远程命令，仅转发 |
| `-f` | SSH 后台运行 |

---

## 七、使用 autossh 自动重连

`autossh` 在隧道断开后自动重建连接。

```bash
# 安装
sudo apt install autossh    # Debian/Ubuntu
brew install autossh        # macOS
sudo yum install autossh    # CentOS/RHEL

# 使用
autossh -M 0 \
    -o "ServerAliveInterval=60" \
    -o "ServerAliveCountMax=3" \
    -o "ExitOnForwardFailure=yes" \
    -NR 0.0.0.0:9000:localhost:8080 \
    root@公网服务器IP
```

| 参数 | 说明 |
|------|------|
| `-M 0` | 关闭 autossh 自带监控端口（用 ServerAlive 替代） |
| `-N` | 不执行远程命令 |
| `-R` | 反向隧道 |

---

## 八、写成 systemd 服务（开机自启）

```bash
sudo vim /etc/systemd/system/autossh-tunnel.service
```

```ini
[Unit]
Description=AutoSSH Reverse Tunnel
After=network.target

[Service]
User=yourusername
ExecStart=/usr/bin/autossh -M 0 \
    -o "ServerAliveInterval=60" \
    -o "ServerAliveCountMax=3" \
    -o "ExitOnForwardFailure=yes" \
    -o "StrictHostKeyChecking=no" \
    -o "UserKnownHostsFile=/dev/null" \
    -NR 0.0.0.0:9000:localhost:8080 \
    root@公网服务器IP
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable autossh-tunnel
sudo systemctl start autossh-tunnel
sudo systemctl status autossh-tunnel
```

**注意**：如果使用密码认证，需要配合 `sshpass`，否则建议用密钥认证。

---

## 九、配置免密登录（推荐）

在内网机器 A 上生成密钥并复制到公网 B：

```bash
# 在 A 上生成密钥（如果还没有）
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""

# 复制公钥到 B
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@公网服务器IP
```

---

## 十、多隧道转发

```bash
# 同时转发多个端口
ssh -R 9000:localhost:8080 \
    -R 9001:localhost:3306 \
    -R 9002:localhost:6379 \
    root@公网服务器IP

# 或写进 ~/.ssh/config
Host tunnel
    HostName 公网服务器IP
    User root
    RemoteForward 9000 localhost:8080
    RemoteForward 9001 localhost:3306
    RemoteForward 9002 localhost:6379
    ServerAliveInterval 60
    ServerAliveCountMax 3
    ExitOnForwardFailure yes
```

然后只需：

```bash
ssh -N tunnel
```

---

## 十一、管理隧道

```bash
# 在公网机器 B 上查看隧道的监听端口
ss -tlnp | grep 9000
netstat -tlnp | grep 9000

# 查看 SSH 隧道进程
ps aux | grep ssh

# 在公网机器 B 上测试隧道是否通
curl http://localhost:9000

# 杀掉隧道
# 在 A 上 Ctrl+C，或 kill 对应的 autossh 进程
sudo systemctl stop autossh-tunnel
```

---

## 十二、反向隧道 vs 正向隧道 vs 动态隧道

| 类型 | 参数 | 方向 | 典型场景 |
|------|------|------|----------|
| **反向隧道** | `-R` | 内网 → 公网 | 内网穿透，暴露内网服务 |
| **正向隧道** | `-L` | 本地 → 远程 | 访问远程内网服务 |
| **动态隧道** | `-D` | 本地 SOCKS | 代理上网 |

```bash
# 反向（本文重点）：公网访问内网
ssh -R 9000:localhost:8080 user@公网IP

# 正向：本地访问远程内网
ssh -L 8080:内网IP:80 user@跳板机

# 动态：SOCKS5 代理
ssh -D 1080 user@远程主机
```

---

## 十三、常见问题排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 外部访问不了 B:9000 | GatewayPorts 没开 | 在 B 上设 `GatewayPorts yes` 并重启 sshd |
| 端口被占用 | 已有进程监听该端口 | `lsof -i :9000` 查看，换端口 |
| 隧道经常断开 | 网络不稳定 / 无心跳 | 加 `ServerAliveInterval` 或用 autossh |
| `Permission denied` | 没做免密登录 | `ssh-copy-id` 复制公钥 |
| 隧道建立但访问不通 | 目标服务没监听在 localhost | 检查目标地址是否正确 |
| 防火墙拦截 | 云服务器安全组/iptables | 在 B 上开放对应端口 |

### 检查清单

```bash
# 1. 在 B 上确认端口在监听
ss -tlnp | grep 9000

# 2. 在 B 上本地测试
curl http://localhost:9000

# 3. 检查防火墙
sudo iptables -L -n | grep 9000
# 云服务器还需检查安全组规则

# 4. 在 A 上确认隧道进程
ps aux | grep "ssh.*-R"
```