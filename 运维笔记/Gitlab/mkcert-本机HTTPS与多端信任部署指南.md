# mkcert 本机 HTTPS 与多端信任部署指南（Linux / macOS / Windows）

## 1. 文档概述

### 解决什么问题

个人或内网要把 Harbor、GitLab、开发站点跑在 HTTPS 上，又不想买域名、做备案、走 Let’s Encrypt 时，常见结果是：服务器上 `curl` 已经 200，笔记本浏览器却显示「不安全」。

本文说明这一整套在干什么，以及如何在 **Linux 服务端签发、在 Linux / macOS / Windows 客户端分别信任**，做到「只有装过你根证书的设备」访问时是绿锁。

### 适合哪些读者

- 有 Linux 命令行基础、需要给自建服务配 HTTPS 的运维 / 开发
- 已经会 `docker compose`，但不清楚证书、信任库、`hosts` 各自管什么
- 需要一份可检索、可照着敲的跨系统手册（不是厂商营销文）

### 阅读后能获得什么

- 分清「公开 CA（Let’s Encrypt）」和「私人 CA（mkcert）」两条路，知道自己该走哪条
- 能在 Ubuntu 上安装 mkcert、签发叶子证书，并接到 Harbor（或普通 nginx）
- 能在 macOS / Windows / 另一台 Linux 上导入同一张根证书，消除浏览器警告
- 能排查 `Connection refused`、`wrong version number`、本机绿锁但另一台电脑红锁

### 版本与范围

| 项目 | 本文依据 |
|------|----------|
| 服务端 | Ubuntu 22.04、Harbor v2.11.0（`~/harbor` + Docker Compose） |
| 证书工具 | mkcert 1.4.4 |
| 客户端 | macOS（钥匙串）、Windows（受信任的根证书颁发机构）、Linux（`update-ca-certificates` / `update-ca-trust`） |
| 示例主机名 | `harbor.local`（推荐）；文中也会说明用 `hosts` 写 `spark.com` 这类公网名的限制 |

**不替代：** 公网站点、给不认识的人用的 HTTPS。那种场景必须用你拥有的域名 + Let’s Encrypt / 商业证书，见同目录外的 [`domain-name-guide.md`](../网络/domain-name-guide.md)。

### 先讲结论

1. **mkcert 不是给全世界签发的。** 它在你的机器上开一家私人证书局（CA）；谁把根证书装进系统信任库，谁的浏览器才绿锁。
2. **证书名字必须等于地址栏里的名字。** 签的是 `harbor.local`，就只能打开 `https://harbor.local`，不能用裸 IP 凑合。
3. **服务端要真正说 TLS。** 只把宿主机 `443` 转到容器明文 `8080`，curl 会报 `wrong version number`，那不是证书坏了，是对面在说 HTTP。
4. **每台要访问的电脑都要单独信任。** Linux 上 `mkcert -install` 救不了 Mac / Windows。

```text
签发机（通常是 Linux 服务器）
  mkcert -install          → 生成根证书 rootCA.pem + 根私钥
  mkcert harbor.local      → 用根私钥签发站点证书
  nginx / Harbor 挂站点证书

每台客户端（Linux / Mac / Windows）
  hosts:  名字 → 服务器 IP
  信任库: 装入同一份 rootCA.pem
  浏览器: https://harbor.local  → 绿锁
```

---

## 2. 前置条件

### 环境要求

| 角色 | 要求 |
|------|------|
| Linux 服务端 | root 或 sudo；Docker / Docker Compose；80、443 可被本机或客户端打到 |
| 客户端 | 能改 `hosts`；能往系统信任库加证书（管理员 / 钥匙串密码） |
| 网络 | 客户端到服务端 IP 的 443 通；不必有公网域名 |

### 软件版本

- mkcert 1.4.4（[GitHub Releases](https://github.com/FiloSottile/mkcert/releases)）
- Harbor 2.11：`harbor.yml` + `./prepare` + `docker compose`
- 浏览器：Chromium / Safari 读系统信任库；**Firefox 要单独导入**

### 必备基础知识

- 知道 HTTPS 走 443、HTTP 走 80
- 会改文本文件、会 `curl -I`
- 知道 Docker 端口映射 `宿主机:容器` 的含义

### 动手前确认

- **【需要确认】** 对外主机名用什么：推荐 `harbor.local` / `git.local`，不要占用别人的公网域名
- **【需要确认】** 客户端是只这台 Linux，还是还要 Mac / Windows / 手机访问
- **【需要确认】** 业务是 Harbor、普通 nginx，还是 GitLab Omnibus（GitLab 改 `external_url`，见 [`GitLab 域名配置技术文档（自建 Omnibus）.md`](../CI-CD/GitLab%20域名配置技术文档（自建%20Omnibus）.md)）

---

## 3. 核心概念

**先记住：** 绿锁不是「有个 `.pem` 文件」，而是「浏览器相信签发它的那家 CA，且证书上的名字对得上」。

### 3.1 证书、CA、信任库

| 名词 | 一句话 |
|------|--------|
| **证书（叶子证书）** | 某网站的「身份证」，写明主机名（SAN） |
| **CA（Certificate Authority）** | 签发身份证的机构。Let’s Encrypt 是浏览器出厂就信的；mkcert 是你自己装的 |
| **根证书 `rootCA.pem`** | 私人 CA 的公章，要装进**客户端**信任库 |
| **根私钥 `rootCA-key.pem`** | 能随便签发，只留在签发机，禁止外传、禁止进 Git |
| **站点证书 + 私钥** | 挂在 nginx / Harbor 上，证明「我是 harbor.local」 |
| **信任库** | 操作系统或浏览器里「我信哪些 CA」的名单 |

Let’s Encrypt：全世界的浏览器出厂就信，适合公网。  
mkcert：只有装过你 `rootCA.pem` 的设备才信，适合本机 / 内网 / 个人。

### 3.2 `hosts` 在这套流程里干什么

没有买域名时，用 **hosts**（本机静态「域名 → IP」表）代替公网 DNS。只对**改了这份文件的那一台电脑**生效。

| 在哪改 | 指到哪里 |
|--------|----------|
| 服务端自己测 | `127.0.0.1 harbor.local` |
| Mac / Windows 访问远端 Linux | `服务器公网或内网 IP harbor.local` |

不要在笔记本上写成 `127.0.0.1 harbor.local`，那会打到笔记本自己，而不是服务器。

### 3.3 为什么「服务器 curl 通、Mac 仍不安全」

信任发生在**打开网页的那台机器**。服务端 `mkcert -install` 只更新 Linux 的信任库。Mac / Windows 必须再导入**同一份** `rootCA.pem`。笔记本上 `brew install mkcert` 再 `mkcert -install` 会生成**另一家** CA，和服务器签出来的证对不上。

### 3.4 Harbor 的 HTTPS 和端口

Harbor 官方流程是：改 `harbor.yml` → `./prepare` 重写 nginx 与 compose → 再 `docker compose up -d`。

启用 HTTPS 后，典型映射是：

```text
宿主机 80  → 容器 8080（HTTP，常用于跳到 HTTPS）
宿主机 443 → 容器 8443（nginx listen 8443 ssl）
```

若写成 `443:8080`，而容器里仍是 `listen 8080;`（无 `ssl`），浏览器按 TLS 握手，读到明文 `HTTP/1.1`，报错：

```text
curl: (35) error:0A00010B:SSL routines::wrong version number
```

这是「HTTPS 端口上跑了 HTTP」，不是证书文件坏了。

---

## 4. 实现步骤

下面按「服务端一次签发 → 各系统客户端信任」的顺序。每步写清：做什么 / 为什么 / 预期结果。

### 4.1 Linux 服务端：安装 mkcert

**做什么：** 装二进制和 Firefox 用的 NSS 工具。  
**为什么：** 没有 mkcert 就无法生成受控的本地 CA。  
**预期结果：** `mkcert -version` 打印 `v1.4.4`。

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install -y wget libnss3-tools ca-certificates

# 官方包；国内若 GitHub 慢，换镜像或 ghfast
wget -O mkcert https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-amd64
# wget -O mkcert https://ghfast.top/https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-linux-amd64

chmod +x mkcert
sudo mv mkcert /usr/local/bin/
mkcert -version
```

CentOS / Fedora / RHEL：

```bash
sudo dnf install -y wget nss-tools
# 同样下载 linux-amd64（或 linux-arm64）二进制，移到 /usr/local/bin/
```

### 4.2 Linux 服务端：安装本地 CA（只做一次）

**做什么：** 生成根证书并写入本机信任库。  
**为什么：** 这台 Linux 上的 curl / Chrome 才能信后续签发的站点证书。  
**预期结果：** `mkcert -CAROOT` 有路径；目录里有 `rootCA.pem`、`rootCA-key.pem`。

```bash
mkcert -install
mkcert -CAROOT
# root 执行时一般是 /root/.local/share/mkcert
# 普通用户一般是 ~/.local/share/mkcert
```

Debian / Ubuntu 上这一步会调用 `update-ca-certificates`；Fedora / RHEL 会走 `update-ca-trust`。

### 4.3 签发站点证书

**做什么：** 用根私钥给将要出现在地址栏里的名字办证。  
**为什么：** nginx 只能出示叶子证书；SAN 必须覆盖你所有访问方式。  
**预期结果：** 得到 `local.pem` 与 `local-key.pem`。

```bash
sudo mkdir -p /opt/mkcert
cd /opt/mkcert

# 推荐：本地域名，不占用公网别人的名字
sudo mkcert -cert-file local.pem -key-file local-key.pem \
  harbor.local 127.0.0.1 ::1

sudo chmod 600 /opt/mkcert/local-key.pem

# 核对 SAN
openssl x509 -in /opt/mkcert/local.pem -noout -ext subjectAltName
```

若客户端用 **IP** 访问，签发时必须把该 IP 写进去，例如 `115.191.5.215`。没写 IP、却打开 `https://115.191.5.215`，会报名称不匹配。

Harbor 若要把证书放到官方路径：

```bash
sudo cp /opt/mkcert/local.pem /opt/harbor/certs/server.pem
sudo cp /opt/mkcert/local-key.pem /opt/harbor/certs/server-key.pem
sudo chmod 600 /opt/harbor/certs/server-key.pem
```

### 4.4 服务端 `hosts`（本机自测）

**做什么：** 让这台 Linux 把名字指到自己。  
**为什么：** 没有公网 DNS 时，解析只能靠 hosts。  
**预期结果：** `ping -c 1 harbor.local` 为 `127.0.0.1`。

```bash
echo "127.0.0.1 harbor.local" | sudo tee -a /etc/hosts
getent hosts harbor.local
```

### 4.5 接到 Harbor（推荐完整路径）

**做什么：** 在 `harbor.yml` 写 hostname 与 `https`，执行 `prepare`，再拉起 Compose。  
**为什么：** 只改 yml 或只改端口映射，nginx 仍可能是明文 `8080`。  
**预期结果：** 宿主机 `443 → 8443`，`curl -I https://harbor.local` 返回 200 / 301，且无证书错误。

1. 备份：

```bash
cd ~/harbor   # 或你的 Harbor 安装目录
cp -a harbor.yml harbor.yml.bak.$(date +%Y%m%d%H%M%S)
cp -a docker-compose.yml docker-compose.yml.bak.$(date +%Y%m%d%H%M%S)
```

2. `harbor.yml` 顶部使用官方结构（路径按实际证书改）：

```yaml
hostname: harbor.local

http:
  port: 80

https:
  port: 443
  certificate: /opt/harbor/certs/server.pem
  private_key: /opt/harbor/certs/server-key.pem
```

`hostname` 不要填 `127.0.0.1`。Harbor 文档要求用外部可访问的名字；个人环境用 `harbor.local` 即可。

3. 生成配置并检查：

```bash
./prepare

# nginx 应出现 ssl
grep -nE "listen|ssl_certificate" common/config/nginx/nginx.conf | head

# compose 应类似 80:8080 与 443:8443，不要 443:8080
```

4. Harbor 2.11 的 `prepare` 可能把日志写成 `tcp://localhost:1514`。本机若把 `localhost` 解析成 IPv6 `[::1]`，而 `harbor-log` 只绑 `127.0.0.1:1514`，其它容器会起不来（`dial tcp [::1]:1514: connection refused`）。改成 IPv4：

```bash
sed -i 's|tcp://localhost:1514|tcp://127.0.0.1:1514|g' docker-compose.yml
```

以后每跑一次 `./prepare`，都要再检查这行。

5. 启动（日志容器要先听 1514）：

```bash
docker compose up -d log
sleep 3
docker compose up -d

ss -tulnp | grep -E ':80|:443'
# 预期：0.0.0.0:80、0.0.0.0:443

curl -I https://harbor.local
# 预期：HTTP/1.1 200 或 301，不是 Connection refused / wrong version number
```

### 4.6 接到普通 nginx（非 Harbor）

**做什么：** 在 443 上挂 mkcert 的叶子证书。  
**为什么：** 应用本身只提供 HTTP 时，由 nginx 做 TLS 终止。  
**预期结果：** `curl -I https://harbor.local` 成功。

```nginx
server {
    listen 443 ssl;
    server_name harbor.local;

    ssl_certificate     /opt/mkcert/local.pem;
    ssl_certificate_key /opt/mkcert/local-key.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Real-IP $remote_addr;
    }
}

server {
    listen 80;
    server_name harbor.local;
    return 301 https://$host$request_uri;
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 4.7 客户端总原则（三角必须齐）

任意客户端要绿锁，三件事同时成立：

1. **解析：** hosts 把 `harbor.local` 指到**服务器 IP**
2. **信任：** 系统（或 Firefox）装的是签发机上那份 `rootCA.pem`
3. **名字：** 浏览器打开的 URL 主机名在证书 SAN 里

从签发机拷根证书（只拷公钥，不要拷 `rootCA-key.pem`）：

```bash
# 在客户端执行，按你的 SSH 账号改
scp root@<服务器IP>:/root/.local/share/mkcert/rootCA.pem ./linux-mkcert-rootCA.pem
```

下面 4.8–4.10 是三个系统怎么完成「解析 + 信任」。

### 4.8 macOS 客户端

**做什么：** 改 hosts，把 Linux 的根证书标为「始终信任」。  
**为什么：** Safari / Chrome 读的是钥匙串，不是 Linux 的 `/etc/ssl`。  
**预期结果：** 完全退出浏览器后再打开 `https://harbor.local`，无警告。

hosts（要管理员密码）：

```bash
# 把 <服务器IP> 换成实际地址，例如 115.191.5.215
sudo sh -c 'echo "<服务器IP> harbor.local" >> /etc/hosts'
dscacheutil -q host -a name harbor.local
```

信任根证书：

```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ./linux-mkcert-rootCA.pem
```

或：访达双击 `linux-mkcert-rootCA.pem` → 加到「系统」钥匙串 → 打开该证书 → **始终信任**。

Chrome 必须彻底退出（菜单「Chrome → 退出」，不要只关窗口）。Firefox：设置 → 隐私与安全 → 证书 → 查看证书 → **证书机构** → 导入同一文件。

本机调试（服务就跑在这台 Mac 上）才需要：

```bash
brew install mkcert nss
mkcert -install
mkcert harbor.local 127.0.0.1
```

这与「信任远端 Linux 那张 CA」是两条线，不要混用。

### 4.9 Windows 客户端

**做什么：** 改 `hosts`，把根证书导入「受信任的根证书颁发机构」。  
**为什么：** Edge / Chrome 读 Windows 证书存储。  
**预期结果：** 用管理员重开浏览器后，`https://harbor.local` 绿锁。

1. 用**管理员**记事本打开：

```text
C:\Windows\System32\drivers\etc\hosts
```

加一行（IP 换成服务器）：

```text
115.191.5.215    harbor.local
```

保存后可执行 `ipconfig /flushdns`。

2. 把 `linux-mkcert-rootCA.pem` 拷到本机，**以管理员打开 cmd / PowerShell**：

```text
certutil -addstore -f ROOT C:\path\to\linux-mkcert-rootCA.pem
```

或：双击证书 → 安装证书 → **本地计算机** → 将所有证书放入「受信任的根证书颁发机构」→ 完成。

3. 验证：

```text
certutil -store ROOT | findstr /i mkcert
curl.exe -I https://harbor.local
```

Firefox 同样要在证书机构里单独导入。企业域控环境可能由组策略覆盖本地信任，需找管理员放行。**【需要确认】** 本机是否受域策略管理。

### 4.10 另一台 Linux 客户端

**做什么：** hosts + 把根证写入系统 CA 目录。  
**为什么：** curl、docker pull、Chrome 都读系统信任库。  
**预期结果：** `curl -I https://harbor.local` 无 `SSL certificate problem`。

Debian / Ubuntu：

```bash
echo "<服务器IP> harbor.local" | sudo tee -a /etc/hosts

sudo cp linux-mkcert-rootCA.pem /usr/local/share/ca-certificates/mkcert-rootCA.crt
sudo update-ca-certificates
```

Fedora / RHEL：

```bash
sudo cp linux-mkcert-rootCA.pem /etc/pki/ca-trust/source/anchors/mkcert-rootCA.pem
sudo update-ca-trust extract
```

Docker / containerd 拉私有 HTTPS 仓库时，装完 CA 后常需：

```bash
sudo systemctl restart docker
# 或
sudo systemctl restart containerd
```

容器**镜像内部**默认不带你的 CA；镜像里的进程要访问该 HTTPS，还要在镜像或挂载里再装一次根证。

---

## 5. 完整示例

以「Ubuntu 上 Harbor 2.11 + 一台 Mac + 一台 Windows」为例。把尖括号换成你的值。

### 5.1 服务端一次性脚本（思路）

```bash
# 1) mkcert
mkcert -install
mkdir -p /opt/harbor/certs /opt/mkcert
mkcert -cert-file /opt/harbor/certs/server.pem \
       -key-file  /opt/harbor/certs/server-key.pem \
       harbor.local 127.0.0.1
chmod 600 /opt/harbor/certs/server-key.pem
echo "127.0.0.1 harbor.local" >> /etc/hosts

# 2) 编辑 ~/harbor/harbor.yml：hostname + http + https（见 4.5）
cd ~/harbor
./prepare
sed -i 's|tcp://localhost:1514|tcp://127.0.0.1:1514|g' docker-compose.yml
docker compose up -d log && sleep 3 && docker compose up -d

curl -I https://harbor.local
```

### 5.2 Mac

```text
hosts:   <服务器IP> harbor.local
信任:    sudo security add-trusted-cert ... linux-mkcert-rootCA.pem
访问:    https://harbor.local
```

### 5.3 Windows

```text
hosts:   <服务器IP> harbor.local
信任:    certutil -addstore -f ROOT linux-mkcert-rootCA.pem
访问:    https://harbor.local
```

### 5.4 和「公网域名 + Let’s Encrypt」怎么选

| 目标 | 做法 |
|------|------|
| 只有一台电脑、或少数自己的设备 | 本文：mkcert + hosts |
| 手机、同事、公网任意浏览器 | 买你自己的域名 + Let’s Encrypt / acme.sh |
| 大陆机器对外 80/443 做网站 | 通常还要 ICP 备案；或改用 Cloudflare Tunnel |
| 本机前端 `localhost` 开发 | Mac/Windows 本机 `mkcert localhost 127.0.0.1` 即可，不必上 Harbor |

---

## 6. 常见问题与排查

| 现象 | 可能原因 | 解决方法 |
|------|----------|----------|
| `Failed to connect ... port 443: Connection refused` | 没有进程听 443；或 hosts 指到本机但服务没映射 443 | `ss -tulnp \| grep 443`；检查 compose 端口 |
| `SSL routines::wrong version number` | 443 上是明文 HTTP（常见 `443:8080` + `listen 8080`） | `./prepare` 生成 `listen 8443 ssl`，compose 用 `443:8443` |
| 服务端 curl 200，Mac/Win 显示不安全 | 客户端没装**签发机**的 `rootCA.pem` | 按 4.8 / 4.9 导入；不要用客户端自己 `mkcert -install` 的另一张根 |
| 名称不匹配 / NET::ERR_CERT_COMMON_NAME_INVALID | 地址栏名字不在 SAN 里（例如用了 IP） | 重新 `mkcert` 带上该名字或 IP；或改用证书里的名字访问 |
| Firefox 仍红锁，Chrome 已绿 | Firefox 不用系统信任库 | 在 Firefox「证书机构」里导入 `rootCA.pem` |
| `dial tcp [::1]:1514: connection refused` | compose 日志地址是 `localhost`，走到 IPv6 | 改成 `tcp://127.0.0.1:1514` 再 `up -d` |
| 打开 `https://spark.com` 异常或无法点「继续」 | `spark.com` 是别人的公网站，可能有 HSTS；hosts 劫持后证书不是公共 CA | 改用 `harbor.local`；或清浏览器 HSTS（不推荐继续占用公网名） |
| Docker 容器内 curl 仍报证书错 | 容器有自己的 CA 包 | 把 `rootCA.pem` 拷进镜像并 `update-ca-certificates` |
| 再执行 `./prepare` 后 HTTPS 没了或起不来 | prepare 覆盖 nginx / compose | 再检查端口、ssl、syslog 地址后重启 |

快速自检：

```bash
# 解析到哪
getent hosts harbor.local

# 443 是不是 TLS（应能看到证书主题，而不是 wrong version number）
echo | openssl s_client -connect harbor.local:443 -servername harbor.local 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName

# 证书 SAN
openssl x509 -in /opt/harbor/certs/server.pem -noout -ext subjectAltName
```

---

## 7. 注意事项与最佳实践

- **不要用 mkcert 给公网访客做站。** 他们没有你的根证书，必然不安全。
- **不要占用不属于你的公网域名**（例如真实的 `spark.com`）。hosts 只在本机生效，还可能撞上对方的 HSTS、证书固定，排障更难。个人用 `*.local` 或你自己买的域名。
- **根私钥只留签发机。** 客户端只需要 `rootCA.pem`。私钥泄漏等于任何人能伪造你信任的 HTTPS。
- **Harbor 改证书必须走 `prepare`。** 手工改 compose 端口、不重写 nginx，是 `wrong version number` 的高发原因。
- **每台设备、每种浏览器信任库可能不同。** 系统 Chrome ≠ Firefox；Docker 主机 ≠ 容器内。
- **证书有效期。** mkcert 叶子证大约两年量级，到期后在同一 `CAROOT` 下重新签发并替换 nginx / Harbor 证书即可，不必重装根（根未过期时）。
- **安全不等于保密。** 绿锁只表示加密且名字对；Harbor 仍要强密码、关公开注册、必要时加 VPN / IP 白名单。
- 大陆云主机对公网开 80/443 做网站时，备案要求以当时监管为准。**【需要确认】**

---

## 8. 总结

这套流程只做一件事：在 Linux 上建立私人 CA，给 `harbor.local`（或你选定的名字）签发证书，让 **Harbor / nginx 说 TLS**，再在 **每一台要访问的 Linux / macOS / Windows** 上写入同一张根证书和 hosts。

对照检查：

1. 服务端 `443` 是 `ssl`，不是明文 8080
2. 证书 SAN 包含你在浏览器里输入的主机名
3. 客户端 hosts 指向**服务器 IP**
4. 客户端信任的是签发机的 `rootCA.pem`
5. Firefox 若使用，已单独导入

下一步建议：

- 只给自己、设备很少：保持 mkcert，把本文当 runbook
- 要给手机或他人用：停用公网名 hosts 劫持，改为你拥有的域名 + Let’s Encrypt
- GitLab Omnibus：用同一套信任模型，但域名入口是 `external_url`，不要只改外层 nginx

相关文档：[`domain-name-guide.md`](../网络/domain-name-guide.md)、[`GitLab 域名配置技术文档（自建 Omnibus）.md`](../CI-CD/GitLab%20域名配置技术文档（自建%20Omnibus）.md)。
