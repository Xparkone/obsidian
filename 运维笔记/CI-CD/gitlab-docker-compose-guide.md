# 用 Docker Compose 部署 GitLab CE

## 1. 文档概述

本文说明如何在 Linux 宿主机上，用 **Docker Compose** 部署 **GitLab Community Edition（CE）官方 Omnibus 镜像**（`gitlab/gitlab-ce`），完成可持久化、可升级的单机自建 GitLab。

**适合读者**：已熟悉 Docker 基本概念（镜像、容器、卷、端口映射）的运维或平台工程师。

**阅读后你能**：

- 写出一份可直接使用的 `docker-compose.yml` 并完成首次启动与登录改密；
- 正确配置 `external_url`、HTTP/HTTPS、SSH 端口与数据卷；
- 完成日常启停、备份恢复思路、升级注意点与常见故障排查。

**核心结论（先看这个）**：

1. 官方推荐用 **单一 Omnibus 容器** 跑 GitLab CE，数据落在三个宿主机目录：`config` / `logs` / `data`。
2. 务必设置正确的 **`external_url`**（协议 + 域名 + 端口），否则克隆地址、回调 URL、OAuth、HTTPS 跳转都会错。
3. 首次启动较慢（常需数分钟），出现 **502** 多半是「还在初始化」，不是配置一定错了。
4. Compose 以现代写法 **`docker compose`**（Compose V2 插件）为准；旧版独立二进制 `docker-compose` 多数场景仍可用，但本文命令以 `docker compose` 为例。

> 本文以 [GitLab 官方 CE Docker 镜像与安装文档](https://docs.gitlab.com/install/docker/installation/) 为准。镜像版本号、最低资源建议会随大版本变化，文中带 **【需要确认】** 的项请对照你计划使用的版本与环境再定。

---

## 2. 前置条件

### 2.1 环境与软件

| 项目 | 建议 | 说明 |
|------|------|------|
| 操作系统 | Linux x86_64 / aarch64 | 官方 Docker 部署以 Linux 宿主机为主；macOS/Windows 仅适合试验，不建议生产 |
| Docker Engine | **【需要确认】** 建议 24+ | 执行 `docker version` 查看 |
| Compose | **【需要确认】** Compose V2 插件 | 执行 `docker compose version`；旧命令为 `docker-compose` |
| 磁盘 | 见下节资源建议 | 仓库、CI 产物、备份会持续增长 |
| 权限 | 能执行 Docker 的用户 | 常见为 `root` 或加入 `docker` 组的用户 |

检查命令示例：

```bash
docker version
docker compose version
# 若无环境只有旧二进制：
# docker-compose version
```

### 2.2 必备基础知识

- 会写/改 `docker-compose.yml`，理解 `ports`、`volumes`、`environment`。
- 了解宿主机端口占用（尤其 **22 / 80 / 443**）。
- 知道如何看容器日志与进入容器执行命令。

### 2.3 端口规划（务必提前想清楚）

| 用途 | 容器内端口 | 宿主机常见映射 | 冲突风险 |
|------|------------|----------------|----------|
| HTTP | 80 | `80:80` | 与 Nginx/Caddy/其他 Web 服务冲突 |
| HTTPS | 443 | `443:443` | 同上 |
| Git over SSH | 22 | `22:22` 或 **`8022:22`**【需要确认】 | 与宿主机 `sshd` 的 22 极易冲突 |

**推荐做法（自建机常见）**：

- Web：宿主机 `80/443` 给 GitLab，或前面再挂反向代理，GitLab 只监听内网端口。
- SSH：宿主机映射为 **`8022:22`**（或其他空闲端口），并在 Omnibus 配置里声明 `gitlab_rails['gitlab_shell_ssh_port']`，这样界面里的 SSH 克隆地址会带正确端口。

> 域名、对外协议、宿主机端口一律标为 **【需要确认】**，示例中的 `gitlab.example.com`、`8022` 仅作占位。

---

## 3. 核心概念

### 3.1 Omnibus 镜像是什么

**Omnibus** 是 GitLab 官方打包方式：一个容器里集成 Nginx、Puma、Sidekiq、PostgreSQL、Redis、Gitaly 等组件。对运维来说，日常用 **`gitlab-ctl`** 管理服务状态，用 **`GITLAB_OMNIBUS_CONFIG`** 或容器内 `/etc/gitlab/gitlab.rb` 写配置。

- **CE（Community Edition）**：开源社区版，镜像名为 `gitlab/gitlab-ce`。
- **EE（Enterprise Edition）**：企业版镜像为 `gitlab/gitlab-ee`。本文只讲 CE；官方 Compose 示例常写 EE，把镜像名里的 `ee` 换成 `ce` 即可。

### 3.2 三个数据卷分别存什么

| 宿主机目录（示例） | 容器路径 | 内容 |
|--------------------|----------|------|
| `./config` | `/etc/gitlab` | `gitlab.rb`、密钥、`initial_root_password` 等 |
| `./logs` | `/var/log/gitlab` | 各组件日志 |
| `./data` | `/var/opt/gitlab` | 仓库、数据库、上传文件、CI 产物等业务数据 |

升级或重建容器时，**只要这三个卷还在，数据就还在**。不要只备份容器本身。

### 3.3 `external_url` 为什么重要

`external_url` 是 GitLab 认为「用户浏览器与 Git 客户端从外面访问自己」的根 URL，例如：

```ruby
external_url 'https://gitlab.example.com'
# 或带非标准端口：
# external_url 'http://gitlab.example.com:8929'
```

它影响：生成的 HTTP(S)/SSH 克隆地址、部分回调与 Cookie、是否启用 HTTPS 相关逻辑等。改错了会出现「能打开页面但克隆/钩子地址不对」一类问题。

### 3.4 适用场景与资源建议

**适合 Compose 单机 Omnibus 的场景**：

- 团队规模较小到中等、希望自建源码与 CI（可另挂 Runner）；
- 希望部署简单、运维面相对集中；
- 能接受「一台机 / 一套卷」的容量与高可用边界。

**不太适合的场景**：

- 需要多节点高可用、大规模拆分组件 → 应看官方 Helm / 参考架构，而不是单容器 Compose；
- 宿主机内存过小（见下表）→ 频繁 OOM、启动失败或极慢。

**资源建议（经验值，请以你选用版本的官方 System Requirements 为准【需要确认】）**：

| 规模粗分 | 内存 | CPU | 磁盘 |
|----------|------|-----|------|
| 试验 / 个人 | ≥ 4 GB（很紧） | ≥ 2 核 | ≥ 20 GB 起步 |
| 小团队常用 | **≥ 8 GB 推荐** | ≥ 4 核 | ≥ 50–100 GB，并预留增长 |
| 仓库/产物多 | 16 GB+ | 按负载加 | 按仓库与 CI Artifact 规划，SSD 更佳 |

说明：

- Omnibus 默认还会拉起监控等组件，内存占用不低；小内存机可考虑关闭部分监控（见后文「常用配置」）。
- 磁盘要给 **备份** 留空间：备份体积往往接近或大于当前数据量级。
- 建议设置 `shm_size: '256m'`（官方 Compose 示例同款），避免部分场景下共享内存过小导致问题。

---

## 4. 实现步骤

以下步骤假设工作目录为 **【需要确认】** `/srv/gitlab`（可换成你的路径）。示例域名 `gitlab.example.com`、SSH 宿主机端口 `8022` 均为占位。

### 步骤 1：建目录

**做什么**：创建数据与 Compose 文件所在目录。  
**为什么**：把配置、日志、业务数据放在明确路径，便于备份与权限排查。  
**预期结果**：存在 `config`、`logs`、`data` 三个空目录（或即将被 GitLab 填充）。

```bash
export GITLAB_HOME=/srv/gitlab   # 【需要确认】
sudo mkdir -p "$GITLAB_HOME"/{config,logs,data}
cd "$GITLAB_HOME"
```

> 也可用相对路径：在某目录下建 `./config` `./logs` `./data`，与本文附录示例一致。

### 步骤 2：编写 `docker-compose.yml`

**做什么**：写入 Compose 文件（现代格式，顶层直接写 `services:`，无需旧版 `version:` 字段）。  
**为什么**：声明镜像、端口、卷、`external_url` 等一次性可复现配置。  
**预期结果**：同目录下有一份可 `docker compose config` 通过的 YAML。

完整可复制示例如下（与同目录示例文件一致，可按需修改）：

```yaml
# 参考：https://docs.gitlab.com/install/docker/installation/
services:
  gitlab:
    # 【需要确认】钉死版本，例如 17.11.0-ce.0；勿长期依赖 latest
    image: gitlab/gitlab-ce:17.11.0-ce.0
    container_name: gitlab
    restart: always
    hostname: 'gitlab.example.com'   # 【需要确认】
    environment:
      GITLAB_OMNIBUS_CONFIG: |
        external_url 'http://gitlab.example.com'   # 【需要确认】协议/域名/端口
        gitlab_rails['time_zone'] = 'Asia/Shanghai'
        # 宿主机 SSH 映射为 8022:22 时取消下一行注释：
        # gitlab_rails['gitlab_shell_ssh_port'] = 8022
    ports:
      - '80:80'       # 【需要确认】
      - '443:443'     # 【需要确认】
      - '8022:22'     # 【需要确认】避免与宿主机 sshd:22 冲突
    volumes:
      - './config:/etc/gitlab'
      - './logs:/var/log/gitlab'
      - './data:/var/opt/gitlab'
    shm_size: '256m'
```

校验：

```bash
docker compose config
```

### 步骤 3：启动

**做什么**：后台拉取镜像并启动容器。  
**为什么**：`-d` 后台运行，便于随后看日志判断就绪。  
**预期结果**：容器状态为 `Up`（早期可能仍在内部初始化）。

```bash
docker compose up -d
docker compose ps
```

> 旧写法：`docker-compose up -d`（若系统未安装 Compose 插件）。

首次会下载较大镜像，耗时取决于网络。【需要确认】是否需要镜像加速或代理。

### 步骤 4：看日志，等到就绪

**做什么**：跟踪启动日志，直到主要服务起来。  
**为什么**：Omnibus 首次会跑 reconfigure，可能要 **数分钟**；过早打开浏览器常看到 502。  
**预期结果**：日志中出现 reconfigure 成功、Nginx/Puma 等正常；浏览器能打开登录页。

```bash
docker compose logs -f gitlab
# 另开终端可粗测：
curl -I http://gitlab.example.com/   # 【需要确认】域名或改成 http://<宿主机IP>/
```

就绪经验信号（措辞随版本可能略有差异）：

- `gitlab Reconfigured!` 或类似 reconfigure 完成提示；
- 访问 Web UI 不再持续 502。

可用 `Ctrl+C` 结束 `logs -f`（不会停容器）。

### 步骤 5：取出 initial root 密码并登录改密

**做什么**：从配置卷读取首次自动生成的 root 密码，登录后立即修改。  
**为什么**：文件通常在 **24 小时后自动删除**；默认密码不可长期使用。  
**预期结果**：能用 `root` 登录，并改成强密码。

```bash
docker exec -it gitlab grep 'Password:' /etc/gitlab/initial_root_password
```

1. 浏览器打开 `http://gitlab.example.com/`【需要确认】。
2. 用户名：`root`，密码：上一步输出。
3. 登录后立刻修改密码（用户设置 / 管理员设置，以界面为准）。
4. 确认改密成功后，可删除或妥善保管该初始密码文件（勿提交到 Git）。

---

## 5. 完整示例

### 5.1 推荐目录结构

```text
/srv/gitlab/                 # 【需要确认】GITLAB_HOME
├── docker-compose.yml
├── config/                  # → /etc/gitlab
├── logs/                    # → /var/log/gitlab
└── data/                    # → /var/opt/gitlab
```

同主题可复制文件（若你按本文落盘）：

- 文档：见本文路径（文末「交付说明」）。
- Compose 示例：`examples/gitlab-compose/docker-compose.yml`（相对文档所在知识库目录）。

### 5.2 使用 `$GITLAB_HOME` 的写法（贴近官方）

官方文档常用环境变量展开卷路径。可在 shell 中 export 后启动：

```bash
export GITLAB_HOME=/srv/gitlab   # 【需要确认】
```

`docker-compose.yml` 片段：

```yaml
volumes:
  - '$GITLAB_HOME/config:/etc/gitlab'
  - '$GITLAB_HOME/logs:/var/log/gitlab'
  - '$GITLAB_HOME/data:/var/opt/gitlab'
```

注意：Compose 对 `$VAR` 的插值行为依赖版本与是否使用 `.env`；若路径异常，改回相对路径 `./config` 等更直观。

### 5.3 非标准 HTTP 端口 + 自定义 SSH 端口（官方同款思路）

当 80 已被占用时，可让 GitLab 监听例如 **8929**【需要确认】，SSH 用 **2424**【需要确认】：

```yaml
services:
  gitlab:
    image: gitlab/gitlab-ce:17.11.0-ce.0   # 【需要确认】版本
    container_name: gitlab
    restart: always
    hostname: 'gitlab.example.com'
    environment:
      GITLAB_OMNIBUS_CONFIG: |
        external_url 'http://gitlab.example.com:8929'
        gitlab_rails['gitlab_shell_ssh_port'] = 2424
    ports:
      - '8929:8929'
      - '443:443'
      - '2424:22'
    volumes:
      - './config:/etc/gitlab'
      - './logs:/var/log/gitlab'
      - './data:/var/opt/gitlab'
    shm_size: '256m'
```

要点：`external_url` 里的端口必须与对外访问一致；SSH 的 **宿主机端口** 与 `gitlab_shell_ssh_port` 一致，容器内仍是 `22`。

---

## 6. 常用配置

配置入口有两种（效果等价，选一种为主，避免两边互相覆盖搞混）：

1. Compose 里的 `GITLAB_OMNIBUS_CONFIG`（适合首次声明与简单项）；
2. 容器内 `/etc/gitlab/gitlab.rb`（持久在 `config` 卷），改完后执行 `gitlab-ctl reconfigure`。

### 6.1 修改 `external_url`

改 YAML 中的 `external_url`，或编辑 `gitlab.rb` 后：

```bash
docker exec -it gitlab gitlab-ctl reconfigure
```

改域名/协议后，建议清浏览器缓存并检查「项目 → 克隆地址」是否更新。

### 6.2 HTTP / HTTPS

**纯 HTTP（内网或前面已有 TLS 终结）**：

```ruby
external_url 'http://gitlab.example.com'
```

**GitLab 容器自行提供 HTTPS（Let's Encrypt）**【需要确认】公网可达与 80/443 条件：

```ruby
external_url 'https://gitlab.example.com'
# Omnibus 在 external_url 为 https 时，可按官方说明启用 Let's Encrypt
# letsencrypt['enable'] = true   # 【需要确认】是否满足自动签证书条件
```

**自签证书（简述）**：

1. 在宿主机准备证书与私钥，挂到例如 `/etc/gitlab/ssl/`（文件名通常需与域名匹配，以官方 SSL 文档为准【需要确认】）。
2. 设置：

```ruby
external_url 'https://gitlab.example.com'
letsencrypt['enable'] = false
nginx['ssl_certificate'] = "/etc/gitlab/ssl/gitlab.example.com.crt"
nginx['ssl_certificate_key'] = "/etc/gitlab/ssl/gitlab.example.com.key"
```

3. `gitlab-ctl reconfigure`。

**反代（Nginx/Caddy/Traefik）简述**：

- 反代终止 TLS，后端用 HTTP 指到 GitLab 容器端口；
- `external_url` 仍应写成用户浏览器看到的 **https://域名**；
- 常需配置 `nginx['listen_port']`、`nginx['listen_https'] = false` 等（以官方「反向代理」文档为准【需要确认】），并转发正确的 `X-Forwarded-*` / `Host`。
- 不要同时让「容器内 Let's Encrypt」与「外层反代证书」各管一套且互相冲突。

### 6.3 修改 SSH 端口

Compose：

```yaml
ports:
  - '8022:22'   # 【需要确认】
```

Omnibus：

```ruby
gitlab_rails['gitlab_shell_ssh_port'] = 8022
```

客户端克隆示例：

```bash
git clone ssh://git@gitlab.example.com:8022/group/project.git
```

### 6.4 时区

```ruby
gitlab_rails['time_zone'] = 'Asia/Shanghai'
```

### 6.5 邮件（点到为止）

在 `GITLAB_OMNIBUS_CONFIG` 或 `gitlab.rb` 中配置 SMTP，例如（占位，【需要确认】真实服务器与凭据）：

```ruby
gitlab_rails['smtp_enable'] = true
gitlab_rails['smtp_address'] = "smtp.example.com"
gitlab_rails['smtp_port'] = 587
gitlab_rails['smtp_user_name'] = "gitlab@example.com"
gitlab_rails['smtp_password'] = "********"
gitlab_rails['smtp_domain'] = "example.com"
gitlab_rails['smtp_authentication'] = "login"
gitlab_rails['smtp_enable_starttls_auto'] = true
gitlab_rails['gitlab_email_from'] = 'gitlab@example.com'
```

改完后 `gitlab-ctl reconfigure`，再在 Admin 里发测试邮件。凭据不要写入公开仓库。

### 6.6 小内存机可选优化（按需）

```ruby
prometheus_monitoring['enable'] = false   # 可明显省内存；是否关闭【需要确认】
# puma['worker_processes'] = 2
# sidekiq['concurrency'] = 10
```

以你版本的官方配置项名为准；乱关组件可能影响可观测性或性能。

---

## 7. 运维

### 7.1 启停与重启

```bash
cd /srv/gitlab    # 【需要确认】
docker compose stop
docker compose start
docker compose restart
docker compose down          # 停止并移除容器，默认不删命名卷；绑定挂载目录仍保留
docker compose up -d
```

### 7.2 进入容器与 `gitlab-ctl`

```bash
docker exec -it gitlab bash
gitlab-ctl status
gitlab-ctl restart
gitlab-ctl reconfigure
gitlab-ctl tail              # 跟踪日志
```

常用服务级操作：

```bash
gitlab-ctl restart nginx
gitlab-ctl restart puma
```

### 7.3 备份思路

Omnibus 提供备份 Rake 任务（细节随版本略有差异，以官方 Backup 文档为准【需要确认】）：

```bash
# 在容器内创建应用备份（通常落到 data 卷的 backups 目录）
docker exec -it gitlab gitlab-backup create
```

**完整恢复所需，通常不止这一份备份包**：

| 内容 | 说明 |
|------|------|
| 备份包 | `gitlab-backup create` 产物（仓库、DB 等，视选项而定） |
| `/etc/gitlab`（config 卷） | 含 `gitlab-secrets.json` 等，**丢失则无法正确解密部分数据** |
| 可选 | 对象存储、外部 DB（若你改成了外部化架构） |

建议：把 **整个 `config` + 定期 backup 包 + 恢复演练记录** 一起纳入备份策略；备份文件权限收紧，并复制到另一台机器或对象存储。

### 7.4 恢复思路（概要）

1. 部署 **相同大版本路径可接受的 GitLab 版本**（详见官方 upgrade/backup 文档【需要确认】）。
2. 先恢复 `/etc/gitlab`（含 secrets）。
3. 再按官方步骤放置 backup 包并执行 restore。
4. `gitlab-ctl reconfigure` / `restart`，验证登录、仓库、CI。

不要在未读官方步骤的情况下对生产库直接试错。

### 7.5 升级注意

1. **钉死镜像 tag**（如 `17.11.0-ce.0`），不要用浮动的 `latest` 做生产升级。
2. 升级前：备份 + 读 [官方 Upgrade Path / Docker 升级说明](https://docs.gitlab.com/)【需要确认】当前版到目标版的路径。
3. **禁止跨多个大版本一次跳升**（例如从很旧的 15 直接拉到最新 17/18）；按官方要求的中间版本逐级升。
4. 升级操作本质：改 `image:` → `docker compose pull` → `docker compose up -d`，并观察日志与 `gitlab-ctl status`。
5. 升级窗口要预留 reconfigure 与迁移时间；确认 Runner、Webhook、LDAP 等仍可用。

---

## 8. 常见问题与排查

### 8.1 容器起不来 / 反复重启 — 内存不足

**现象**：`docker compose ps` 显示 Restarting；日志有 OOM、被 kill、或 reconfigure 中断。  
**可能原因**：物理内存或 cgroup 限制 < GitLab 所需。  
**解决**：加内存或关闭非必要组件；用 `dmesg` / `journalctl` 确认 OOM；勿在 2GB 机器上硬跑完整 Omnibus。

### 8.2 端口冲突：22 与 8022

**现象**：`Bind for 0.0.0.0:22 failed` 或 SSH 克隆连到宿主机 sshd 而非 GitLab。  
**可能原因**：宿主机 `sshd` 占用 22；或映射端口与 `gitlab_shell_ssh_port` 不一致。  
**解决**：改用 `8022:22`（或其他空闲端口）【需要确认】；同步配置 `gitlab_shell_ssh_port`；用 `ss -lntp | grep -E '22|8022'` 检查占用。

### 8.3 打开网站一直 502

**现象**：HTTP 502 Bad Gateway。  
**可能原因**：首次启动未完成；Puma/Nginx 未就绪；内存不足导致服务起一半；`external_url`/反代错误。  
**解决**：`docker compose logs -f gitlab` 耐心等待；`docker exec -it gitlab gitlab-ctl status`；确认内存；反代场景检查上游地址与 `external_url`。

### 8.4 权限与卷

**现象**：启动报 permission denied、无法写 `/var/opt/gitlab` 等。  
**可能原因**：宿主机目录权限过严、NFS 根squash、SELinux 标签（RHEL 系常见）。  
**解决**：保证 Docker 可对绑定目录读写；SELinux 环境按官方为卷加 `:Z` 或正确上下文【需要确认】；不要手动乱改容器内用户后却在宿主机用错误 UID 灌文件。

### 8.5 找不到 initial_root_password

**现象**：文件不存在。  
**可能原因**：已超过约 24 小时被删除；或曾手动删过。  
**解决**：用容器内 Rails 任务重置 root 密码（以你版本官方文档命令为准【需要确认】），例如查找 `gitlab-rake` 相关重置说明。

### 8.6 克隆 SSH 地址端口不对

**现象**：UI 显示 `git@host:group/project.git` 无端口，但实际映射在 8022。  
**解决**：设置 `gitlab_rails['gitlab_shell_ssh_port'] = 8022` 并 reconfigure。

---

## 9. 注意事项与最佳实践（含安全）

1. **不要把未防护的 GitLab 直接暴露公网**：至少配合防火墙、强密码/2FA、限制注册、必要时 VPN 或 IP 白名单。
2. **立刻修改默认 root 密码**，启用 2FA（管理员账户强烈建议）。
3. **防火墙 / UFW**：只放行必要端口。例如仅开放 `80/443` 与 SSH 映射口 `8022`【需要确认】；管理机 SSH（22）与 GitLab SSH（8022）分开理解，避免「为了 Git 克隆而误关管理端口」或「误开全世界可写」。
4. **密钥与备份**：`gitlab-secrets.json`、备份包、SMTP 密码均属敏感资产。
5. **版本钉死 + 变更有记录**：镜像 tag、compose 变更、升级窗口记入变更单。
6. **磁盘监控**：`data` 与备份目录告警，防止 CI 产物撑满磁盘导致实例只读或宕机。
7. **Runner 分离**：CI 任务建议用独立 Runner 主机/容器，避免与 GitLab 争抢同一台机的 CPU/内存（本篇不展开 Runner 安装）。

UFW 示例（仅示意，【需要确认】策略）：

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8022/tcp comment 'GitLab SSH'
# 管理用 22 是否对公网开放：单独评估，勿与 GitLab SSH 混为一谈
sudo ufw status
```

---

## 10. 总结

- 用官方 **`gitlab/gitlab-ce`** + Compose，挂载 **config / logs / data** 三卷，设置正确 **`external_url`**，是自建单机 GitLab 的标准路径。
- 首次启动要等就绪；用 **`initial_root_password`** 登录后马上改密。
- 运维围绕：`docker compose` 启停、`gitlab-ctl`、备份（含 secrets）、按官方路径升级。
- 排障优先查：内存、端口（尤其 22）、502 是否过早访问、卷权限。

**下一步建议**：

1. 把文中所有 **【需要确认】** 换成真实域名、端口、版本与目录；
2. 在试验机按第 4 节走通一遍，并做一次「备份 → 恢复」演练；
3. 再按需加 HTTPS/反代、SMTP、独立 Runner，并收紧防火墙与账号策略。

---

## 附录 A. 常用命令速查

```bash
# 校验与启动
docker compose config
docker compose up -d
docker compose ps
docker compose logs -f gitlab
docker compose stop | start | restart | down

# 初始密码
docker exec -it gitlab grep 'Password:' /etc/gitlab/initial_root_password

# 容器内运维
docker exec -it gitlab bash
docker exec -it gitlab gitlab-ctl status
docker exec -it gitlab gitlab-ctl reconfigure
docker exec -it gitlab gitlab-ctl restart
docker exec -it gitlab gitlab-ctl tail
docker exec -it gitlab gitlab-backup create

# 端口与资源排查（宿主机）
ss -lntp | grep -E ':80|:443|:22|:8022'
docker stats gitlab
df -h
free -h
```

旧 Compose 二进制对照：把上文 `docker compose` 换成 `docker-compose` 即可（子命令基本相同）。

## 附录 B. 官方参考

- Docker 安装：<https://docs.gitlab.com/install/docker/installation/>
- 系统要求：以官网 *Installation system requirements* 为准【需要确认】链接随文档站改版可能变化
- 备份与恢复、升级路径：在 docs.gitlab.com 搜索 *backup* / *upgrade paths*

## 附录 C. 示例文件路径

若与本文一同落盘到知识库目录，Compose 示例如下：

- `examples/gitlab-compose/docker-compose.yml`

---

*文档依据 GitLab 官方 CE Docker / Compose 说明整理；示例域名与端口均为占位，实施前请逐项确认。*
