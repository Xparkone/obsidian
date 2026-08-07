# GitLab 域名配置技术文档（自建 Omnibus）

## 目录

1. [文档概述](#1-文档概述)
2. [前置条件](#2-前置条件)
3. [核心概念：external_url 如何决定域名](#3-核心概念external_url-如何决定域名)
4. [实现步骤：Omnibus 标准配置](#4-实现步骤omnibus-标准配置)
5. [HTTPS / 证书配置](#5-https--证书配置)
6. [反向代理 / 外部 TLS 终止](#6-反向代理--外部-tls-终止)
7. [改域名后的连带影响](#7-改域名后的连带影响)
8. [Docker / Helm 差异入口](#8-docker--helm-差异入口)
9. [完整示例：最小可复制配置](#9-完整示例最小可复制配置)
10. [常见问题与排查](#10-常见问题与排查)
11. [注意事项与最佳实践](#11-注意事项与最佳实践)
12. [检查清单](#12-检查清单)
13. [总结与下一步](#13-总结与下一步)

---

## 1. 文档概述

### 1.1 解决什么问题

自建 GitLab 上线或搬家时，最常问的是：**「域名怎么配？」** 实际要解决的是：

- 浏览器访问地址、Git 克隆 URL、邮件里的链接、OAuth 回调地址不一致
- HTTPS 证书怎么接（Let’s Encrypt / 自备证书 / 仅 HTTP）
- 前面还有 Nginx / Traefik 时，GitLab 自带 Nginx 该怎么配合，避免无限重定向
- 改完域名后，Registry、Pages、Webhook、已克隆仓库的 remote 还要不要动

本文以 **Omnibus 安装**（Linux 包安装，配置文件 `/etc/gitlab/gitlab.rb`）为主，给出可照做的配置与验证步骤；Docker / Helm 只说明配置入口差异。

> **GitLab.com（SaaS）**：租户无法「改整站域名」。仓库在 `gitlab.com`（或企业自定 Pages/Registry 等产品能力）上，不存在本文所述的 `external_url` 整站改域。功能全景见 [`gitlab-features-guide.md`](GitLab%20功能全景技术文档.md)；迁入数据见 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md)。

### 1.2 适合哪些读者

- 负责自建 GitLab（CE/EE）的运维 / 平台工程师
- 需要把 IP 访问改为正式域名、或从旧域名切到新域名的实施人员
- 已熟悉 Linux 与基础 DNS / TLS，但不熟悉 GitLab Omnibus 配置项的工程师

### 1.3 阅读后能获得什么

- 理解 **`external_url` 是整站对外域名的单一事实来源**
- 能独立完成：DNS → `gitlab.rb` → `reconfigure` → HTTPS → 验证
- 知道反向代理场景下的常见坑（listen_https / listen_port）
- 改域后能系统处理 Registry、Pages、OAuth、已克隆仓库等连带项

### 1.4 先讲结论（核心思路）

1. **改域名 = 改 `external_url`，再 `gitlab-ctl reconfigure`**，不要只改 Nginx 或只改 DNS。
2. **`external_url` 必须写成用户最终在浏览器里看到的协议 + 主机名**（生产建议 `https://...`），即使 TLS 在前面的反向代理上终止。
3. Registry、Pages 若启用，通常还要单独配 **`registry_external_url` / `pages_external_url`**（常为子域名）。
4. 改域后：**DNS、证书、防火墙、集成回调、本地 git remote** 必须一起核对，否则会出现「网页能开、clone 仍是旧地址」或「无限重定向」。

---

## 2. 前置条件

### 2.1 环境与版本

| 项目 | 建议 / 要求 |
|------|-------------|
| 安装方式 | 本文默认 **Omnibus**（官方 Linux 包）；Docker / Helm 见第 8 节 |
| 版本语境 | 配置项以较新的 **16.x / 17.x** 习惯为主；具体键名以你实例版本文档为准 |
| 权限 | 需服务器 **root** 或等价 sudo，能改 `/etc/gitlab/gitlab.rb` 并执行 `gitlab-ctl` |
| 实例状态 | GitLab 已安装并可启动；建议在低峰操作，改域前做好备份（见导入文档中的整站备份说明：[`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md) 场景五） |

### 2.2 DNS

在改 `external_url` 之前（或与之同步）准备好解析：

| 记录类型 | 典型用法 |
|----------|----------|
| **A** | `gitlab.example.com` → 服务器公网 / 内网 IPv4 |
| **AAAA** | 若启用 IPv6，指向 IPv6 地址 |
| **CNAME** | 子域名（如 `registry.example.com`）可 CNAME 到主域名；**apex（裸域）** 是否支持 CNAME 取决于 DNS 厂商 |

验证示例（在你的电脑或服务器上）：

```bash
# 应解析到预期 IP
dig +short gitlab.example.com A
# 或
nslookup gitlab.example.com
```

**预期结果**：解析稳定且指向将承载 GitLab（或反向代理）的主机。DNS 未生效时，Let’s Encrypt 校验与浏览器访问都会失败。

### 2.3 防火墙与端口

| 场景 | 需放行端口 |
|------|------------|
| HTTP 跳转 HTTPS / ACME HTTP-01 | **80/tcp** |
| HTTPS 用户访问 | **443/tcp** |
| 仅内网 HTTP（不推荐生产） | 对应监听端口（常为 80） |
| 自定义 SSH 克隆端口（若改过） | 如 22 或 `gitlab_rails['gitlab_shell_ssh_port']` 对应端口 |

若前面有负载均衡 / 反向代理，**公网 80/443 开在代理上**，GitLab 节点只需对代理网段开放其实际监听端口。

### 2.4 证书准备情况（三选一）

1. **Let’s Encrypt**：域名已公网可解析到本机（或代理能正确转发 ACME），80 可达。
2. **自备证书**：已有 `fullchain.pem`（或等价）与私钥，路径可读。
3. **仅 HTTP**：内网 PoC / 开发；**不推荐生产**。

### 2.5 必备基础知识

- 会编辑文本配置并执行系统命令
- 理解 DNS 记录与 HTTPS 证书的基本关系
- 知道「浏览器访问的 URL」应与「Git 远程 URL 的主机名」一致

---

## 3. 核心概念：external_url 如何决定域名

### 3.1 什么是 external_url

**`external_url`**：Omnibus 中声明的「GitLab 对外权威地址」（协议 + 主机名 + 可选端口）。`gitlab-ctl reconfigure` 会据此生成 Nginx、GitLab Rails、邮件链接、克隆 URL 提示等大量下游配置。

示例：

```ruby
external_url 'https://gitlab.example.com'
```

### 3.2 它影响什么

| 能力 / 场景 | 如何受影响 |
|-------------|------------|
| Web UI | 登录后重定向、绝对链接 |
| Git HTTPS 克隆 | `https://gitlab.example.com/group/project.git` |
| 邮件通知 | 邮件正文中的 Issue / MR 链接 |
| OAuth / OIDC / SAML 回调 | 回调 URL 主机名必须与 IdP 登记一致 |
| Container Registry | 若启用，常另设 `registry_external_url`；镜像引用含该主机名 |
| GitLab Pages | 若启用，常另设 `pages_external_url`（用户站点子域或路径） |
| Webhook / 集成 | 出站请求里的「本实例链接」及部分回调约定 |

一句话：**用户眼里的「GitLab 域名」必须与 `external_url` 一致**；只改 DNS 或只改前端代理而不改 `external_url`，一定会出现链接错乱。

### 3.3 相关配置项（后续章节会展开）

| 配置项 | 作用 |
|--------|------|
| `external_url` | 主站对外 URL（必配） |
| `registry_external_url` | Container Registry 对外 URL |
| `pages_external_url` | Pages 对外 URL |
| `letsencrypt['enable']` | 是否由 Omnibus 申请/续期 Let’s Encrypt 证书 |
| `nginx['ssl_certificate']` / `nginx['ssl_certificate_key']` | 自备证书路径 |
| `nginx['listen_https']` / `nginx['listen_port']` | 反向代理场景下 GitLab 侧监听行为 |
| `nginx['real_ip_trusted_addresses']` 等 | 可信代理 / 真实客户端 IP（点到为止） |

---

## 4. 实现步骤：Omnibus 标准配置

以下以全新域名 `https://gitlab.example.com` 为例。请把示例域名换成你的真实域名。

### 步骤 1：确认 DNS 与连通性

**做什么**：确保 `gitlab.example.com` 已指向 GitLab 服务器（或入口代理），80/443 策略已按第 2 节放行。

**为什么**：`reconfigure` 若启用 Let’s Encrypt，需要域名可达；即使用自备证书，用户也依赖正确解析。

**预期结果**：`dig` / `nslookup` 得到正确 IP；从客户端 `curl -I http://gitlab.example.com` 或 `https://...` 能打到入口（此时可能还是旧站或默认页，属正常）。

### 步骤 2：备份当前配置（强烈建议）

**做什么**：

```bash
sudo cp -a /etc/gitlab/gitlab.rb /etc/gitlab/gitlab.rb.bak.$(date +%Y%m%d%H%M%S)
# 可选：同时备份已有 SSL 目录
sudo cp -a /etc/gitlab/ssl /etc/gitlab/ssl.bak.$(date +%Y%m%d%H%M%S) 2>/dev/null || true
```

**为什么**：改错 `gitlab.rb` 或证书路径时可快速回退。

**预期结果**：备份文件存在且可读。

### 步骤 3：编辑 gitlab.rb，设置 external_url

**做什么**：

```bash
sudo editor /etc/gitlab/gitlab.rb
```

找到或新增（全文件中 **只应有一个生效的** `external_url`）：

```ruby
# 生产环境请使用 https
external_url 'https://gitlab.example.com'
```

常见补充（按需取消注释/修改）：

```ruby
# 若 SSH 克隆不想走 22，可声明展示用端口（并在防火墙/SSH 侧真实开放）
# gitlab_rails['gitlab_shell_ssh_port'] = 2222
```

**为什么**：这是 Omnibus 生成站点配置的源头；协议用 `https` 时，后续证书段才有意义。

**预期结果**：文件已保存；`grep "^external_url" /etc/gitlab/gitlab.rb` 显示新值。

### 步骤 4：配置 HTTPS（先选一种方案）

在执行 `reconfigure` 前，按第 5 节选好证书方案并写好对应配置块：

- Let’s Encrypt → 打开 `letsencrypt['enable']` 等
- 自备证书 → 放置文件并设置 `nginx['ssl_certificate*']`
- 仅 HTTP → `external_url 'http://...'`（仅限非生产）

**预期结果**：证书相关配置与 `external_url` 协议一致，无互相矛盾（例如 `https` 却未提供任何证书来源）。

### 步骤 5：执行 reconfigure

**做什么**：

```bash
sudo gitlab-ctl reconfigure
```

**为什么**：Chef 根据 `gitlab.rb` 渲染 Nginx、GitLab、证书续期任务等；**只改文件不 reconfigure 不会生效**。

**预期结果**：末尾出现成功完成类提示（无致命 Error）；服务保持运行。可用：

```bash
sudo gitlab-ctl status
```

查看各进程为 `run`。

> 首次启用 Let’s Encrypt 时，reconfigure 会尝试申请证书；失败时整次可能报错，见第 10 节。

### 步骤 6：验证

**做什么（建议按序）**：

```bash
# 1) 浏览器打开
# https://gitlab.example.com

# 2) 命令行看跳转与证书（示意）
curl -I https://gitlab.example.com

# 3) GitLab 自检（耗时可能较长）
sudo gitlab-rake gitlab:check

# 4) 可选：查看当前对外 URL 相关配置是否符合预期
sudo gitlab-rake gitlab:env:info
```

在 UI 中打开任意项目 → **Clone**，确认 HTTPS 地址主机名为新域名。

**为什么**：把「配置写对」和「用户可见链接正确」都验证一遍。

**预期结果**：页面可登录；克隆 URL 为新域名；`gitlab:check` 无与 URL/SSL 相关的致命失败（个别可选组件 Warning 可再单独处理）。

---

## 5. HTTPS / 证书配置

### 5.1 Let’s Encrypt（Omnibus 内置）

适用：域名**公网可解析到本机**（或 ACME 能完成校验），希望自动申请与续期。

```ruby
external_url 'https://gitlab.example.com'

letsencrypt['enable'] = true
# 可选：失败通知邮箱
letsencrypt['contact_emails'] = ['admin@example.com']
# 可选：自动续期相关（版本不同默认可能已开启）
# letsencrypt['auto_renew'] = true
```

然后：

```bash
sudo gitlab-ctl reconfigure
```

**说明**：

- 通常需要 **80** 可从公网访问（HTTP-01）。若只能 DNS-01 或证书由外部统一签发，改用自备证书或外部代理终结 TLS。
- 证书落盘路径由 Omnibus 管理；一般**不必**再手写 `nginx['ssl_certificate']`，除非你有意覆盖。

**【需要确认】**：你所在网络是否拦截 80、是否强制仅通过公司统一网关做 ACME；若是，内置 Let’s Encrypt 可能不适用。

### 5.2 自备证书

适用：公司内部 CA、已购买的商业证书、或由外部流水线下发的证书。

1. 准备文件（示例路径，可自定）：

```bash
sudo mkdir -p /etc/gitlab/ssl
sudo cp fullchain.pem /etc/gitlab/ssl/gitlab.example.com.crt
sudo cp privkey.pem   /etc/gitlab/ssl/gitlab.example.com.key
sudo chmod 600 /etc/gitlab/ssl/gitlab.example.com.key
```

2. 在 `gitlab.rb` 中：

```ruby
external_url 'https://gitlab.example.com'

# 关闭内置 LE，避免冲突（若曾开启）
letsencrypt['enable'] = false

nginx['ssl_certificate']     = "/etc/gitlab/ssl/gitlab.example.com.crt"
nginx['ssl_certificate_key'] = "/etc/gitlab/ssl/gitlab.example.com.key"
```

3. `sudo gitlab-ctl reconfigure`

**注意**：证书链需完整（常需包含中间证书）；主机名必须覆盖 `gitlab.example.com`（SAN / CN）。

### 5.3 仅 HTTP（开发 / 内网）

```ruby
external_url 'http://gitlab.example.com'
# 或直接使用 IP（更不推荐长期使用）
# external_url 'http://192.168.1.10'
```

```bash
sudo gitlab-ctl reconfigure
```

**限制**：浏览器与部分客户端对混合内容、OAuth、Cookie `Secure` 等更敏感；**不推荐生产**。若内网也有 TLS 能力，仍建议上 HTTPS。

---

## 6. 反向代理 / 外部 TLS 终止

场景：前面已有 **Nginx / Traefik / 云 LB** 负责 HTTPS，后端 GitLab Omnibus 只提供 HTTP。

### 6.1 核心原则

- **`external_url` 仍然写成用户看到的 HTTPS 地址**，例如 `https://gitlab.example.com`。
- GitLab 内置 Nginx 可改为监听 HTTP，并由代理把 `X-Forwarded-Proto: https` 等头传过来。
- 若代理与 GitLab **双方都做 HTTP→HTTPS 重定向** 且头未传对，极易出现**无限重定向**。

### 6.2 常见 gitlab.rb 写法（示意）

```ruby
external_url 'https://gitlab.example.com'

# 让 GitLab 侧按「对外是 HTTPS」生成链接，但本机只听 HTTP
nginx['listen_port'] = 80
nginx['listen_https'] = false

# 若代理与 GitLab 不同机，确保代理把 Host / X-Forwarded-Proto / X-Forwarded-For 正确传入
# 可信代理（按实际网段修改）
# nginx['real_ip_trusted_addresses'] = ['10.0.0.0/8', '192.168.0.0/16']
# nginx['real_ip_header'] = 'X-Forwarded-For'
# nginx['real_ip_recursive'] = true
```

代理侧需保证：

- 回源到 GitLab 的 `listen_port`（上例为 80）
- 传递 `Host: gitlab.example.com`
- 传递 `X-Forwarded-Proto: https`（以及常用的 `X-Forwarded-Ssl` 等，视代理而定）

### 6.3 证书放在哪

| 模式 | 证书位置 |
|------|----------|
| 外部代理终止 TLS | 证书配在 Nginx/Traefik/LB；GitLab 可关 HTTPS 监听 |
| GitLab 自己终止 TLS | 证书配在 Omnibus（第 5 节）；代理做 TCP 透传或不用代理 |

不要「代理已 HTTPS、GitLab 仍强制 listen_https 且再 301」除非你非常清楚链路。

### 6.4 CORS / 可信代理（点到为止）

- 改域后若有前端、IDE 插件、自定义 Pages 域跨域调用 API，可能需在 Admin 或对应组件中更新 **允许的来源**。
- 日志中的客户端 IP 依赖 **real_ip / 可信代理** 配置；配错会导致限流、审计 IP 不准。细节以官方 Nginx 设置文档为准，本文不展开全部键名。

---

## 7. 改域名后的连带影响

改完主站 `external_url` 并 reconfigure 后，请按表逐项处理。

### 7.1 已克隆仓库的 remote URL

本地仓库不会自动更新：

```bash
cd /path/to/repo
git remote -v
git remote set-url origin https://gitlab.example.com/group/project.git
# SSH 示例
# git remote set-url origin git@gitlab.example.com:group/project.git
```

通知团队统一替换，或提供脚本批量修改。

### 7.2 Container Registry

若启用 Registry，通常需要**独立对外域名**（或明确的主机:端口）：

```ruby
registry_external_url 'https://registry.example.com'

# 证书：可与主站同样用 LE 或自备证书（路径/域名要匹配 registry 主机名）
```

影响：

- `docker login` / 镜像引用 `registry.example.com/group/project:tag`
- CI 中 `CI_REGISTRY` 等变量随配置更新；**已推送到旧域名的引用不会自动改写**，需重新 tag/push 或保留旧解析过渡期

DNS：为 `registry.example.com` 单独做 A/CNAME，并放行 443（或你的 Registry 端口）。

### 7.3 GitLab Pages

```ruby
pages_external_url 'https://pages.example.com'
# 具体是否启用 pages['enable']、通配符证书、二级域名策略依版本与架构而定
```

用户站点 URL、CI 里 Pages 作业产物地址都会变；自定义域名需在项目 Pages 设置与 DNS 侧同步更新。

### 7.4 集成 / Webhook / OAuth

| 类型 | 要做什么 |
|------|----------|
| 系统 OAuth 应用 / 第三方登录（Google、GitHub 等） | 在 IdP 控制台更新 **Authorized redirect URI** 为新域名 |
| 项目 Webhook | 检查 URL 是否写死旧域名；失败队列可在项目 Settings → Webhooks 查看 |
| Slack / Jira / 其他集成 | 更新回调与文档中的链接 |
| Runner | 一般连 `external_url`；确认 `config.toml` 的 `url` 指向新地址并能解析/信任证书 |

### 7.5 对象存储、缓存 CDN 中的绝对 URL（若使用）

若历史上把带绝对域名的链接写入对象存储或对外文档，需评估是否重写或做旧域 301。**【需要确认】**：你是否启用了外部对象存储及是否有硬编码旧域。

---

## 8. Docker / Helm 差异入口

不展开完整部署，只标「域名改哪里」。

| 安装方式 | 配置入口 | 说明 |
|----------|----------|------|
| **Omnibus（本文主体）** | `/etc/gitlab/gitlab.rb` → `gitlab-ctl reconfigure` | 最常见自建方式 |
| **官方 Docker 镜像** | 常通过环境变量 **`GITLAB_OMNIBUS_CONFIG`** 写入与 `gitlab.rb` 相同的 Ruby 片段（含 `external_url`），或挂载自定义 `gitlab.rb` | 改完后重启/重建容器使配置生效 |
| **Kubernetes / Helm** | `values.yaml` 中的 **`global.hosts.domain`**、`https`、ingress TLS 等 | 由 Chart 渲染 Ingress 与工作负载；证书常用 cert-manager |

原则相同：**对外主机名与协议必须在「全局 hosts / external_url」层声明一致**，不要只改 Ingress 注解而忽略 GitLab 应用配置。

---

## 9. 完整示例：最小可复制配置

### 9.1 场景 A：公网域名 + Let’s Encrypt（无外部代理）

`/etc/gitlab/gitlab.rb` 最小片段：

```ruby
external_url 'https://gitlab.example.com'

letsencrypt['enable'] = true
letsencrypt['contact_emails'] = ['admin@example.com']
```

```bash
sudo gitlab-ctl reconfigure
sudo gitlab-ctl status
curl -I https://gitlab.example.com
```

### 9.2 场景 B：自备证书

```ruby
external_url 'https://gitlab.example.com'

letsencrypt['enable'] = false
nginx['ssl_certificate']     = "/etc/gitlab/ssl/gitlab.example.com.crt"
nginx['ssl_certificate_key'] = "/etc/gitlab/ssl/gitlab.example.com.key"
```

### 9.3 场景 C：Traefik/Nginx 终止 TLS + GitLab 仅 HTTP

```ruby
external_url 'https://gitlab.example.com'

nginx['listen_port'] = 80
nginx['listen_https'] = false
letsencrypt['enable'] = false
```

代理示例逻辑（伪配置，按你实际栈改写）：

```nginx
# 示意：对外 443，回源 http://gitlab-backend:80
proxy_set_header Host              $host;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-Ssl   on;
proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
```

### 9.4 场景 D：主站 + Registry 子域（示意）

```ruby
external_url 'https://gitlab.example.com'
registry_external_url 'https://registry.example.com'

letsencrypt['enable'] = true
letsencrypt['contact_emails'] = ['admin@example.com']
```

DNS：`gitlab` 与 `registry` 均指向入口；443 可达。

---

## 10. 常见问题与排查

### 10.1 Let’s Encrypt / 证书申请失败

| 项目 | 说明 |
|------|------|
| **现象** | `reconfigure` 报 ACME 错误；浏览器证书错误 |
| **可能原因** | DNS 未生效；80 被挡；域名指向错误主机；频次限制；公司防火墙拦截 |
| **解决方法** | 先 `dig` 确认解析；临时用自备证书恢复服务；修好 80/域名后再开 LE；查看 `gitlab-ctl tail` 中 nginx/letsencrypt 相关日志 |

### 10.2 浏览器无限重定向

| 项目 | 说明 |
|------|------|
| **现象** | 打开站点不断 301/302 |
| **可能原因** | 外部代理强制 HTTPS，同时 GitLab 也在重定向；**未传 `X-Forwarded-Proto: https`**；`external_url` 为 https 但链路上被当成 http |
| **解决方法** | 按第 6 节设置 `listen_https = false` 与 `listen_port`；修正代理头；避免双层「无条件跳 HTTPS」冲突 |

### 10.3 Clone / UI 仍显示旧域名

| 项目 | 说明 |
|------|------|
| **现象** | 已改 DNS，Clone 按钮仍是旧 host |
| **可能原因** | 未改 `external_url` 或未 `reconfigure`；浏览器/CDN 缓存；看的是本地 `git remote`（本地不会自动变） |
| **解决方法** | 核对 `gitlab.rb` → reconfigure → 无痕窗口验证 UI；本地执行 `git remote set-url` |

### 10.4 DNS 未生效

| 项目 | 说明 |
|------|------|
| **现象** | 部分地区能开、部分不能；LE 失败 |
| **可能原因** | TTL 未过期；本地 hosts 残留；双栈 A/AAAA 不一致 |
| **解决方法** | 查权威 DNS 与多地解析；检查 `/etc/hosts`；IPv6 若不可用可暂不配 AAAA |

### 10.5 reconfigure 报错

| 项目 | 说明 |
|------|------|
| **现象** | Chef 中途失败，服务异常 |
| **可能原因** | `gitlab.rb` 语法错误（缺引号/括号）；证书文件不存在或权限不对；磁盘满；端口被占用 |
| **解决方法** | 读报错末尾首个 Error；`ruby -c` 无法直接检 rb 时用备份回退对比；确认 ssl 文件路径；`gitlab-ctl status` / `lsof -i :443`；修好后再次 `reconfigure` |

### 10.6 SSH 克隆主机名不对

SSH 不走 `external_url` 的 HTTP(S) 主机逻辑时，仍依赖 DNS 中 `gitlab.example.com` 的 A 记录与 SSH 服务端口。若仅改了 Web 域名而 SSH 仍用旧 IP/别名，需同步 DNS 或 `~/.ssh/config`。

---

## 11. 注意事项与最佳实践

1. **先 DNS、再证书、再切 `external_url`**（或维护窗口内一次完成），减少「半新半旧」窗口。
2. **生产始终用 HTTPS**；内网 HTTP 仅作短期 PoC。
3. **改域列入变更**：通知开发者更新 remote；同步 IdP 回调；评估 Registry/Pages。
4. **保留旧域名一段时间**：DNS/Nginx 301 到新域，降低书签与 Webhook 失败面。
5. **改前备份** `gitlab.rb` 与（如需要）`gitlab-backup`；回滚时先恢复配置再 reconfigure。
6. **不要在文档/脚本里写死 IP** 当长期入口；以域名为准。
7. 与功能启用、数据迁入分开规划：域名是基础设施；功能地图与导入流程见同目录另外两篇文档。

---

## 12. 检查清单

实施前后可打印勾选：

**准备**

- [ ] 目标域名已确定（含是否启用 `registry` / `pages` 子域）
- [ ] DNS A/AAAA/CNAME 已提交，解析验证通过
- [ ] 防火墙 / 安全组：80、443（及 Registry 端口）已放行
- [ ] 证书方案已选：Let’s Encrypt / 自备 / 外部代理终止
- [ ] 已备份 `/etc/gitlab/gitlab.rb`（及证书目录）

**配置**

- [ ] `external_url` 为最终对外 URL（协议正确）
- [ ] HTTPS 配置与方案一致，无冲突
- [ ] 若有反向代理：`listen_https` / `listen_port` / 转发头已核对
- [ ] 若有 Registry/Pages：对应 `*_external_url` 与 DNS 已配置
- [ ] 已执行 `sudo gitlab-ctl reconfigure` 且成功

**验证**

- [ ] 浏览器可登录新域名，证书无告警
- [ ] 项目 Clone URL 为主机名为新域
- [ ] `sudo gitlab-rake gitlab:check`（或等价检查）无阻塞性错误
- [ ] OAuth / Webhook / Runner 已指向新 URL
- [ ] 团队已收到更新 `git remote` 的通知
- [ ] （可选）旧域 301 到新域

---

## 13. 总结与下一步

### 13.1 核心要点

- 自建 GitLab 改域名的主开关是 **`external_url`**，必须 **`gitlab-ctl reconfigure`** 才生效。
- HTTPS 用 Let’s Encrypt、自备证书或外部代理终止均可，但 **`external_url` 仍应反映用户真实访问方式**。
- 反向代理场景重点防 **重定向环** 与 **转发头缺失**。
- 改域是「主站 URL + DNS/证书 + Registry/Pages + 集成回调 + 本地 remote」的组合变更，不是改一行配置就结束。

### 13.2 建议的下一步

1. 按第 12 节检查清单在测试环境走通一次，再进生产变更窗口。
2. 需要启用 CI、Registry、权限体系时，参阅 [`gitlab-features-guide.md`](GitLab%20功能全景技术文档.md)。
3. 若改域伴随整站搬家或项目迁入，参阅 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md)。
4. 对照官方文档核对你当前大版本的键名差异：[Configure the external URL](https://docs.gitlab.com/omnibus/settings/configuration.html)（Omnibus Configuration）、NGINX 与 Let’s Encrypt 相关章节。

---

*文档定位：自建 Omnibus 域名与 TLS 实操指南。配置项随 GitLab 小版本可能有增减，实施时以实例版本文档为准；不确定处已标【需要确认】。*
