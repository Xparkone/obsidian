# Rundeck：Runbook 自动化与运维自助平台详解

> 名称说明：用户口语中的 “runduck” 通常指 **Rundeck**  
> 验证基线：Rundeck OSS `6.1.0-20260803`、API v58  
> 资料截止日期：2026-08-21  
> 适用范围：Rundeck Open Source、Linux、Docker、PostgreSQL、SSH、Ansible、Kubernetes 和运维自助服务

---

## 1. 先讲结论

Rundeck 是一个 Runbook 自动化平台。它把现有 Shell、Python、Ansible、API、Kubernetes 和其他运维工具编排成可审计的 Job，并通过 Web UI、计划任务、Webhook、CLI 或 API 执行。

可以把它理解为：

~~~text
脚本和自动化工具
      +
目标主机清单
      +
参数表单
      +
权限控制
      +
审批、日志、计划任务
      =
可委派的运维自助平台
~~~

生产使用时应记住：

1. Rundeck 主要负责组织、授权和执行现有自动化，不替代 Ansible、Terraform、Argo CD 或监控系统。
2. Job 是核心执行单元，Project 是资源、Job、Key Storage 和权限的管理边界。
3. Node 不一定是物理服务器，也可以代表虚拟机、容器、数据库、网络设备或逻辑目标。
4. Rundeck 能执行高权限操作，因此自身属于关键控制面，必须启用 HTTPS、SSO、最小权限和审计。
5. 默认 H2 数据库仅适合体验；生产应使用 PostgreSQL、MySQL/MariaDB 等受支持的外部数据库。
6. 默认本地管理员账号和示例密码不能用于生产。
7. 凭据应放入 Key Storage 或外部秘密系统，不能写在 Job、脚本、Git 或日志中。
8. ACL 同时存在 Application Context 和 Project Context；只写其中一层经常导致“能看到但不能执行”或“完全看不到项目”。
9. Job 成功只表示步骤返回成功，不代表业务恢复；必须增加健康检查和结果验证。
10. 开源版与 PagerDuty Runbook Automation 商业版功能不同，HA、Runner、商业插件等能力需要单独确认授权。

---

## 2. Rundeck 是什么

Rundeck Open Source 是 Apache License 2.0 的开源 Runbook 自动化软件，现由 PagerDuty 团队和社区维护。

它提供：

- Web 管理界面；
- Job 和 Workflow；
- 计划任务；
- Node Inventory；
- SSH、WinRM 和插件执行；
- Job 参数和输入校验；
- Key Storage；
- RBAC/ACL；
- 执行历史和日志；
- REST API；
- `rd` 命令行工具；
- Webhook 和通知；
- Ansible、Kubernetes、云平台等插件集成。

典型目标是把依赖少数专家手工完成的操作，变成：

~~~text
有参数约束
有权限边界
有执行日志
有失败处理
有结果验证
可由授权用户自助执行
~~~

---

## 3. Rundeck 不是什么

### 3.1 不等于 Ansible

Ansible 擅长声明目标状态、批量配置服务器和编写 Playbook；Rundeck 擅长把 Ansible Playbook、脚本和 API 编排成可调度、可授权的自助 Job。

常见组合：

~~~text
用户 / 告警 / API
        ↓
     Rundeck Job
        ↓
  ansible-playbook
        ↓
     目标主机
~~~

### 3.2 不等于 Terraform

Terraform 管理基础设施资源生命周期和 State；Rundeck 可以触发经过审查的 Terraform 流程，但不应绕过 Plan、审批和 State Lock。

### 3.3 不等于 Jenkins

Jenkins 主要面向软件构建和交付流水线；Rundeck 更偏向生产运维操作、自助服务、计划任务和跨工具 Runbook。

### 3.4 不等于 Argo CD

Argo CD 持续协调 Kubernetes GitOps 状态；Rundeck 适合触发诊断、扩缩容、故障处理和跨系统流程。不要让二者同时修改同一资源字段。

### 3.5 不等于监控系统

Prometheus、Grafana 和告警平台发现问题；Rundeck执行诊断或修复。自动修复前必须避免告警抖动、重复触发和错误扩大。

---

## 4. 适用场景

### 4.1 运维自助

- 重启指定服务；
- 清理应用缓存；
- 查询日志和进程；
- 扩缩容；
- 开关维护模式；
- 刷新 CDN；
- 执行数据库只读检查；
- 获取诊断包。

开发或客服人员只看到授权的 Job 和受约束的参数，不直接获得服务器登录权限。

### 4.2 事件响应

~~~text
告警
  ↓
收集节点、应用和依赖状态
  ↓
判断故障类型
  ↓
执行有限修复
  ↓
健康检查
  ↓
通知和审计
~~~

### 4.3 计划任务

- 定期巡检；
- 日志或临时文件清理；
- 证书到期检查；
- 数据同步；
- 报表生成；
- 非高峰期维护。

### 4.4 跨工具编排

一个 Job 可以依次调用：

1. ServiceNow 或工单 API；
2. Terraform；
3. Ansible；
4. Kubernetes；
5. HTTP 健康检查；
6. Slack、飞书或邮件通知。

### 4.5 不适合直接自动化

- 没有可靠检测条件的破坏性操作；
- 无法幂等且没有补偿措施的长事务；
- 必须进行复杂人工判断的事故；
- 直接在生产执行未审查用户输入；
- 把任意 Shell 控制台开放给普通用户。

---

## 5. 产品版本与发行边界

### 5.1 Rundeck Open Source

Rundeck OSS 提供核心 Job、Workflow、Node、ACL、Key Storage、API、计划任务和插件能力。

当前官方 GitHub 最新 Release：

~~~text
v6.1.0-20260803
~~~

### 5.2 PagerDuty Runbook Automation

商业产品通常增加：

- 官方技术支持；
- 高可用和集群能力；
- Enterprise Runner / Distributed Automation；
- 部分商业插件；
- 更完整的企业身份、审计或管理能力；
- 商业版专属调度和条件逻辑功能。

功能名称和授权会变化，应以当前产品比较页和 License 为准。

### 5.3 版本约束

Rundeck 6.0 起生产运行最低要求 Java 17。官方系统要求页面建议：

- Rundeck OSS 最低约 2 CPU、8 GB RAM、4 GB JVM Heap；
- 生产使用外部数据库；
- HTTP 默认 4440；
- HTTPS 常用 4443；
- Linux SSH 默认 22；
- Windows WinRM 常用 5985/5986。

实际容量取决于并发 Job、Node 数、日志量、插件和数据库性能。

---

## 6. 核心概念

| 概念 | 说明 |
|---|---|
| Project | Job、Node、配置、ACL 和 Key Storage 的组织边界 |
| Job | 可重复执行的自动化定义 |
| Workflow | Job 内按策略执行的步骤集合 |
| Step | 命令、脚本、插件或其他 Job |
| Node | 可被选择和执行操作的目标资源 |
| Resource Model Source | Node Inventory 来源 |
| Node Filter | 按名称、标签、属性筛选 Node |
| Option | Job 执行时的输入参数 |
| Execution | 一次 Job 或命令的具体运行记录 |
| Key Storage | SSH Key、密码等秘密的存储接口 |
| ACL Policy | 决定用户和角色能看什么、做什么 |
| Plugin | 扩展 Workflow、Node、通知、存储等能力 |
| Runner | 商业版分布式执行组件 |

---

## 7. 架构与请求流程

### 7.1 单实例架构

~~~text
Browser / API / rd CLI
          │ HTTPS
          ▼
┌──────────────────────────────┐
│ Rundeck Server               │
│ Web UI / API / Scheduler     │
│ Job Engine / ACL / Plugins   │
└───────┬───────────┬──────────┘
        │           │
        │           ├── PostgreSQL
        │           ├── Key Storage
        │           └── Execution Logs
        │
        ├── SSH ───── Linux Nodes
        ├── WinRM ─── Windows Nodes
        ├── API ───── Cloud / SaaS
        └── kubectl / Plugin ─ Kubernetes
~~~

### 7.2 Job 执行流程

1. 用户、计划任务或 API 触发 Job；
2. Rundeck 验证身份；
3. ACL 判断是否允许查看和执行；
4. 校验 Job Option；
5. Resource Model 提供 Node；
6. Node Filter 选择目标；
7. Workflow Strategy 组织步骤和 Node 顺序；
8. 执行插件连接目标；
9. 收集日志、状态和上下文；
10. 执行错误处理、通知和结果验证；
11. 保存 Execution History。

### 7.3 分布式执行

商业版 Runner 可以在远端网络内主动连接中心平台，减少中心直接打开 SSH/WinRM 入站路径的需求。

这不是 OSS 默认能力。开源版跨网络执行通常仍需要：

- Rundeck Server 直接访问目标；
- 跳板机；
- SSH Proxy；
- 自定义插件；
- 在各网络部署独立 Rundeck。

---

## 8. 安装前规划

在部署前确定：

- OSS 还是商业版；
- 单实例还是高可用；
- 域名和 HTTPS 终止位置；
- PostgreSQL/MySQL/MariaDB；
- Execution Log 存储；
- SSO/LDAP；
- Project 和权限边界；
- Node Inventory 来源；
- SSH/WinRM 网络路径；
- Key Storage 加密和外部秘密系统；
- 插件来源和升级策略；
- 备份、恢复和升级窗口。

生产拓扑建议：

~~~text
用户
 ↓
WAF / Load Balancer / Reverse Proxy
 ↓ HTTPS
Rundeck
 ├── External PostgreSQL
 ├── Object Storage / Shared Log Store
 ├── SSO / LDAP
 ├── Secret Backend
 └── Target Networks
~~~

---

## 9. Docker 快速体验

### 9.1 启动

~~~bash
docker run --rm -it \
  --name rundeck-lab \
  -p 4440:4440 \
  -e RUNDECK_GRAILS_URL=http://127.0.0.1:4440 \
  rundeck/rundeck:6.1.0
~~~

访问：

~~~text
http://127.0.0.1:4440
~~~

默认体验账号通常是：

~~~text
username: admin
password: admin
~~~

这只适合本机实验。不得把默认密码暴露到可访问网络。

### 9.2 查看日志

~~~bash
docker logs -f rundeck-lab
~~~

### 9.3 体验环境限制

快速启动默认使用 H2：

- 不适合多实例；
- 不适合高并发；
- 容器删除后数据可能丢失；
- 不应作为生产数据库；
- 不能替代正式备份。

---

## 10. Docker Compose 与 PostgreSQL

以下是结构示例，密码必须由部署环境安全注入，不能提交到 Git：

~~~yaml
services:
  postgres:
    image: postgres:17
    restart: unless-stopped
    environment:
      POSTGRES_DB: rundeck
      POSTGRES_USER: rundeck
      POSTGRES_PASSWORD: "${POSTGRES_PASSWORD:?required}"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rundeck -d rundeck"]
      interval: 10s
      timeout: 5s
      retries: 10

  rundeck:
    image: rundeck/rundeck:6.1.0
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      RUNDECK_GRAILS_URL: "https://rundeck.example.com"
      RUNDECK_SERVER_FORWARDED: "true"
      RUNDECK_DATABASE_DRIVER: "org.postgresql.Driver"
      RUNDECK_DATABASE_URL: "jdbc:postgresql://postgres:5432/rundeck"
      RUNDECK_DATABASE_USERNAME: "rundeck"
      RUNDECK_DATABASE_PASSWORD: "${POSTGRES_PASSWORD:?required}"
      JVM_MAX_RAM_PERCENTAGE: "75"
      RUNDECK_LOGGING_STRATEGY: "CONSOLE"
    ports:
      - "127.0.0.1:4440:4440"
    volumes:
      - rundeck_data:/home/rundeck/server/data
      - ./realm.properties:/home/rundeck/server/config/realm.properties:ro

volumes:
  postgres_data:
  rundeck_data:
~~~

启动前在当前 Shell 安全提供密码：

~~~bash
read -rsp 'PostgreSQL password: ' POSTGRES_PASSWORD
export POSTGRES_PASSWORD
docker compose config
docker compose up -d
unset POSTGRES_PASSWORD
~~~

注意：

- 环境变量仍可能被容器管理接口读取；
-更严格环境应使用编排平台 Secret、外部秘密系统或自定义配置模板；
- `docker compose config` 可能展开秘密，不要把输出上传到日志；
- `realm.properties` 必须使用安全密码或改为 SSO/LDAP；
-生产应固定镜像 Digest。

---

## 11. RPM/DEB 安装布局

常见路径：

~~~text
/etc/rundeck/
/etc/rundeck/rundeck-config.properties
/etc/rundeck/framework.properties
/etc/rundeck/realm.properties
/var/lib/rundeck/
/var/log/rundeck/
~~~

Java 检查：

~~~bash
java -version
~~~

Rundeck 6 生产至少使用 Java 17。

服务管理：

~~~bash
sudo systemctl enable --now rundeckd
sudo systemctl status rundeckd
sudo journalctl -u rundeckd -f
~~~

安装仓库脚本和包名可能变化，应从官方 Installation 页面获取当前命令，不能复制多年以前的 apt-key 示例。

---

## 12. 反向代理与 HTTPS

### 12.1 Grails URL

外部地址必须正确：

~~~text
RUNDECK_GRAILS_URL=https://rundeck.example.com
~~~

否则可能出现：

- 登录后跳转到 localhost；
- Webhook URL 错误；
- 邮件链接错误；
- API Client 重定向异常；
- 静态资源路径错误。

### 12.2 Forwarded Header

反向代理终止 TLS 时：

~~~text
RUNDECK_SERVER_FORWARDED=true
~~~

代理必须正确设置：

~~~text
X-Forwarded-Proto
X-Forwarded-Host
X-Forwarded-Port
X-Forwarded-For
~~~

只信任受控代理提供的 Header，避免客户端伪造。

### 12.3 Nginx 示例

~~~nginx
server {
    listen 443 ssl http2;
    server_name rundeck.example.com;

    ssl_certificate     /etc/nginx/tls/tls.crt;
    ssl_certificate_key /etc/nginx/tls/tls.key;

    location / {
        proxy_pass http://127.0.0.1:4440;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Port 443;
        proxy_read_timeout 3600s;
    }
}
~~~

长任务日志跟随需要合理的代理超时。不要关闭 TLS 校验解决证书问题。

---

## 13. 从零开始使用 Rundeck

这一节给出一条可以照着操作的主线：

~~~text
登录 Rundeck
  → 创建 Project
  → 导入 Linux Node
  → 配置 SSH Key 和执行器
  → 测试远程命令
  → 创建参数化 Job
  → 执行并查看日志
  → 配置定时、通知和权限
  → 通过 API 或 rd 调用
~~~

下面以一个实验环境为例：

| 项目 | 示例值 |
|---|---|
| Rundeck 地址 | `http://rundeck.example.com:4440` |
| Project | `linux-operations` |
| 目标主机 | `192.168.1.20` |
| SSH 用户 | `ops` |
| Node 名称 | `web-01` |
| Rundeck Key Storage 路径 | `keys/linux-operations/ssh` |

页面入口会随 Rundeck 版本和语言设置略有变化。文中同时给出功能名称；找不到完全相同的文字时，进入对应 Project 后，从 `Project Settings`、`Nodes`、`Jobs` 或 `Commands` 中查找。

### 13.1 使用前检查

Rundeck 服务器需要能够连接目标主机：

~~~bash
nc -vz 192.168.1.20 22
~~~

目标 Linux 主机需要准备一个专用账号。不要直接使用 root 作为默认执行用户：

~~~bash
sudo useradd --create-home --shell /bin/bash ops
sudo install -d -m 700 -o ops -g ops /home/ops/.ssh
~~~

如果 Job 需要执行少量特权命令，应配置精确的 `sudoers` 白名单。例如只允许重启和查看 nginx：

~~~sudoers
ops ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx
ops ALL=(root) NOPASSWD: /usr/bin/systemctl status nginx
ops ALL=(root) NOPASSWD: /usr/bin/systemctl is-active nginx
~~~

修改后验证语法：

~~~bash
sudo visudo -c
~~~

生产环境还应提前确认：

- Rundeck 到目标端口的防火墙和安全组是否放行；
- 目标主机的 `sshd` 是否允许公钥认证；
- Rundeck 的外部 URL、时区和数据库是否正确；
- 执行账号是否只拥有实际需要的权限；
- 任务输出中是否可能出现密码、Token 或个人信息。

### 13.2 登录与修改初始账号

打开 Rundeck 地址并登录。实验安装可能存在默认账号：

~~~text
用户名：admin
密码：admin
~~~

该默认值只适合本地实验。对外提供服务前必须更换密码，生产环境应接入 LDAP、OIDC 或其他统一身份认证，并限制管理后台的访问来源。

登录后通常会看到 Project 列表。Rundeck 的日常操作几乎都在某个 Project 内完成。

### 13.3 创建第一个 Project

操作路径通常为：

~~~text
Projects / Project Menu
  → New Project / Create a New Project
~~~

填写：

| 字段 | 示例 | 说明 |
|---|---|---|
| Project Name | `linux-operations` | 建议使用稳定的英文标识 |
| Label | `Linux 运维` | 可读名称，部分版本提供 |
| Description | `Linux 主机巡检和服务操作` | 说明用途和责任团队 |

创建后进入 Project。先不要急着创建大量 Job，应先把 Node、凭据和执行器配置正确。

### 13.4 生成并分发 SSH 公钥

建议为 Rundeck 单独生成密钥，不要复用员工个人 SSH 私钥：

~~~bash
ssh-keygen -t ed25519 -f rundeck_ops_ed25519 -C 'rundeck-linux-operations'
~~~

生产环境可以为私钥设置密码，但需要同时配置 Rundeck 对应的密码凭据。公钥写入目标主机：

~~~bash
ssh-copy-id -i rundeck_ops_ed25519.pub ops@192.168.1.20
~~~

或者把公钥内容加入：

~~~text
/home/ops/.ssh/authorized_keys
~~~

在把私钥上传 Rundeck 前，先直接验证：

~~~bash
ssh -i rundeck_ops_ed25519 ops@192.168.1.20 'hostname; id'
~~~

预期结果应显示目标主机名和 `ops` 用户。验证失败时先解决 SSH 问题，不要在 Rundeck 中反复重试。

### 13.5 把私钥保存到 Key Storage

进入：

~~~text
System Menu（右上角齿轮）
  → Key Storage
  → Add or Upload Key
~~~

部分欢迎项目或定制界面也会在 `Project Settings` 中显示 Key Storage 入口，最终进入的是同一类凭据存储功能。

选择私钥类型并上传 `rundeck_ops_ed25519`，保存到：

~~~text
keys/linux-operations/ssh
~~~

注意：

- 上传的是私钥，不是 `.pub` 公钥；
- 文档、Git 仓库和 Job 参数中都不要保存私钥内容；
- Key Storage 路径本身不是秘密，但读取权限仍应通过 ACL 限制；
- 定期轮换密钥，旧公钥应从目标主机移除；
- 不要在命令步骤中使用 `cat` 输出私钥。

### 13.6 添加 Linux Node

进入：

~~~text
Project Settings
  → Edit Nodes / Node Sources
  → Add a Source
~~~

实验环境可选择文件型 Resource Model Source，创建 `resources.yaml`：

~~~yaml
web-01:
  nodename: web-01
  hostname: 192.168.1.20
  username: ops
  osFamily: unix
  osName: Linux
  description: Test web server
  tags: web,test
  ssh-key-storage-path: keys/linux-operations/ssh
~~~

不同 SSH 插件对密钥属性名的支持可能不同。更稳妥的做法是在 Project 的 SSH Node Executor 中设置默认 Key Storage Path，只在个别 Node 需要不同密钥时覆盖。

RPM/DEB 安装中可使用 Rundeck 服务账号可读写的路径，例如：

~~~text
/var/lib/rundeck/resources/linux-operations.yaml
~~~

如果 Rundeck 运行在容器中，Node 文件必须位于持久化卷内，并且容器内路径要与 Node Source 配置一致。不要只在宿主机创建文件却忘记挂载进容器。

主机数量较多时，不建议手工维护 YAML，可改用：

- Ansible Inventory；
- CMDB API；
- 云厂商实例插件；
- Kubernetes Node 或工作负载插件；
- 返回 Rundeck Resource Model 格式的内部服务。

### 13.7 配置 SSH Node Executor

进入：

~~~text
Project Settings
  → Edit Configuration
  → Default Node Executor
~~~

选择 SSH 类执行器，常见配置为：

| 配置 | 示例 |
|---|---|
| SSH User | `${node.username}` 或 `ops` |
| Authentication | Private Key |
| SSH Key Storage Path | `keys/linux-operations/ssh` |
| SSH Port | `22` |
| Connection Timeout | `10000` 毫秒 |
| Command Timeout | 按任务类型设置 |

如果 Workflow 中包含脚本上传，还要配置 `File Copier`，通常使用与 Node Executor 相匹配的 SCP 或 SFTP 插件。

不要为了省事全局关闭 SSH Host Key 校验。生产环境应维护可信 `known_hosts`，防止 Rundeck 把命令发给被冒充的主机。

### 13.8 验证 Node 和远程执行

打开 `Nodes` 页面，搜索：

~~~text
name: web-01
~~~

或按标签筛选：

~~~text
tags: test+web
~~~

确认页面能看到：

- Node 名称；
- IP 或主机名；
- SSH 用户；
- 标签；
- 操作系统属性。

实验阶段可进入 `Commands`，选择 `web-01` 后依次执行只读命令：

~~~bash
hostname
id
uptime
df -h
~~~

`Commands` 允许临时输入任意命令，权限很大。生产环境中通常只向管理员开放，普通使用者通过受控 Job 执行固定流程。

如果失败，按顺序检查：

1. Node Filter 是否选中了 Node；
2. Rundeck 到目标主机的 22 端口是否连通；
3. `hostname` 和 `username` 是否正确；
4. Key Storage 路径是否存在且 ACL 允许读取；
5. 公钥是否在目标用户的 `authorized_keys`；
6. 私钥格式和权限是否被 SSH 插件支持；
7. SSH Host Key 是否发生变化；
8. Rundeck 服务日志中是否有更具体的认证错误。

### 13.9 创建第一个巡检 Job

进入：

~~~text
Jobs
  → Create a New Job / New Job
~~~

填写基本信息：

| 字段 | 示例 |
|---|---|
| Job Name | `检查主机状态` |
| Group | `diagnosis/linux` |
| Description | `查看主机名、负载、磁盘和内存，不修改系统` |

在 Workflow 中依次添加 Command Step：

~~~bash
hostname
uptime
df -h
free -m
~~~

在 Nodes 配置中启用“Dispatch to Nodes”，Node Filter 填：

~~~text
tags: test+web
~~~

初次测试建议：

- Thread Count 设为 `1`；
- Keep going 关闭，即某个关键步骤失败后停止；
- 不启用 Schedule；
- 暂不允许并发执行；
- Node Filter 先锁定测试标签，不要直接选择所有生产机。

保存 Job 后，Rundeck 会生成 Job UUID。脚本、API 和依赖关系应使用 UUID，Job 名称主要用于人阅读。

### 13.10 执行 Job 并查看结果

打开 Job，先检查右侧或执行确认页中的目标 Node 列表，确认没有误选主机，再点击 `Run Job Now`。

执行页面通常包含：

- Execution ID；
- 当前状态；
- 各个 Workflow Step；
- 每个 Node 的输出；
- 开始时间、结束时间和执行人；
- 重试、中止或重新执行入口。

常见状态：

| 状态 | 含义 |
|---|---|
| Running | 正在执行 |
| Succeeded | 所有必要步骤成功 |
| Failed | 至少一个必要步骤失败 |
| Aborted | 被用户或系统中止 |
| Timed Out | 超过执行超时 |

查看日志时应同时确认“命令退出码”和“业务结果”。命令返回 `0` 不一定代表服务健康，例如重启命令成功后，服务仍可能启动失败，因此还需要单独的健康检查步骤。

### 13.11 给 Job 增加参数

编辑 Job，在 `Options` 中新增：

| Option | 示例配置 |
|---|---|
| `service` | Allowed Values：`nginx,httpd`；Required：是 |
| `action` | Allowed Values：`status,restart`；默认：`status` |
| `environment` | Allowed Values：`test,prod` |
| `reason` | Required：是，用于审计 |

在命令中引用参数：

~~~bash
sudo /usr/local/sbin/rundeck-service-action \
  "${option.service}" \
  "${option.action}"
~~~

不要直接把自由输入拼入 Shell：

~~~bash
# 危险示例：用户可能注入额外 Shell 语句
sudo systemctl ${option.action} ${option.service}
~~~

更安全的包装脚本：

~~~bash
#!/usr/bin/env bash
set -euo pipefail

service_name="${1:-}"
action_name="${2:-}"

case "$service_name" in
  nginx|httpd) ;;
  *) echo "unsupported service" >&2; exit 2 ;;
esac

case "$action_name" in
  status|restart) ;;
  *) echo "unsupported action" >&2; exit 2 ;;
esac

exec sudo /usr/bin/systemctl "$action_name" "$service_name"
~~~

把脚本部署为 `/usr/local/sbin/rundeck-service-action`，并让 `sudoers` 只允许该入口。Rundeck 的 Allowed Values 是第一层校验，目标主机上的包装脚本是第二层校验。

密码、Token 等值应使用 Secure Option 或 Key Storage。Secure Option 只能减少界面暴露，仍要避免命令回显、`set -x`、进程参数和外部脚本把秘密写入日志。

### 13.12 创建一个安全的服务重启 Job

推荐 Workflow：

~~~text
1. 执行前检查：systemctl is-active <service>
2. 重启服务：调用白名单包装脚本
3. 等待服务启动：最多重试 6 次
4. 健康检查：检查端口或 HTTP 接口
5. 输出最终状态
6. 失败时执行通知或回滚 Handler
~~~

例如 nginx 健康检查步骤：

~~~bash
set -euo pipefail

for attempt in 1 2 3 4 5 6; do
  if curl --fail --silent --show-error \
      --max-time 3 http://127.0.0.1/healthz >/dev/null; then
    echo "health check passed"
    exit 0
  fi
  echo "health check attempt ${attempt} failed"
  sleep 5
done

echo "service did not become healthy" >&2
exit 1
~~~

生产 Job 还应设置：

- Execution Timeout，防止无限挂起；
- 同一 Job 的并发策略；
- Node 级 Thread Count，控制批量并发；
- Error Handler 或失败通知；
- Log Filter，遮蔽敏感输出；
- 执行原因和变更单号；
- 执行前确认或审批入口。

### 13.13 配置定时执行

编辑 Job，打开 `Schedule`：

1. 选择简单时间表或 Cron；
2. 明确时区；
3. 设置小时、分钟、星期等条件；
4. 保存后检查下一次运行时间；
5. 先在测试环境观察一次完整执行。

示例：每天 02:30 执行巡检。若使用 Cron，具体字段格式以当前 Rundeck 页面提示为准，不要直接假设它与 Linux 五字段 Cron 完全相同。

需要避免：

- 上一次还未结束，下一次又开始；
- 多个 Job 同时打满数据库或目标主机；
- 维护窗口和业务高峰重叠；
- Rundeck 与使用者理解的时区不一致；
- Schedule 已禁用但外部系统仍通过 API 调用。

### 13.14 配置通知

在 Job 的 `Notifications` 中，可以按事件配置邮件、Webhook 或插件通知。常见事件：

- Start：任务开始；
- Success：任务成功；
- Failure：任务失败；
- Average Duration Exceeded：超过历史平均时间；
- Retryable Failure 或其他插件事件。

Webhook 接收端应校验来源和认证信息。通知内容中不要包含 Secure Option、完整环境变量、私钥、数据库密码或未经脱敏的任务日志。

### 13.15 通过 API 执行 Job

先在 Rundeck 中创建受限 API Token。Token 应属于专用服务账号，并只授权必要的 Project 和 Job。

不要把 Token 直接写进脚本，使用环境变量：

~~~bash
export RUNDECK_URL='https://rundeck.example.com'
export RUNDECK_TOKEN='从安全凭据系统注入'
export RUNDECK_API_VERSION='58'
export JOB_ID='替换为实际 Job UUID'
~~~

执行 Job：

~~~bash
curl --fail-with-body \
  --request POST \
  --header "X-Rundeck-Auth-Token: ${RUNDECK_TOKEN}" \
  --header 'Content-Type: application/json' \
  --data '{
    "options": {
      "service": "nginx",
      "action": "status",
      "environment": "test",
      "reason": "API connectivity test"
    }
  }' \
  "${RUNDECK_URL}/api/${RUNDECK_API_VERSION}/job/${JOB_ID}/run"
~~~

响应中会返回 Execution ID。查询执行结果：

~~~bash
export EXECUTION_ID='替换为返回的执行 ID'

curl --fail-with-body \
  --header "X-Rundeck-Auth-Token: ${RUNDECK_TOKEN}" \
  "${RUNDECK_URL}/api/${RUNDECK_API_VERSION}/execution/${EXECUTION_ID}"
~~~

API 版本应以当前服务的 `/api` 响应和官方文档为准。文中的 `58` 对应本文核对时的 Rundeck 6.1 文档，升级后需要重新确认。

### 13.16 使用 rd 命令行客户端

配置环境变量：

~~~bash
export RD_URL='https://rundeck.example.com'
export RD_TOKEN='从安全凭据系统注入'
export RD_PROJECT='linux-operations'
~~~

常见命令：

~~~bash
# 查看系统信息
rd system info

# 列出 Project
rd projects list

# 列出当前 Project 的 Job
rd jobs list

# 按 Job UUID 执行并传入参数
rd run -i "$JOB_ID" \
  -- -service nginx \
     -action status \
     -environment test \
     -reason 'CLI connectivity test'

# 查看执行列表
rd executions list
~~~

不同 `rd` 版本的参数可能略有差异，使用下面的命令确认当前语法：

~~~bash
rd --version
rd help
rd run --help
~~~

### 13.17 导出 Job 并纳入 Git

Job 在页面中验证通过后，应导出 YAML 或 XML 保存到 Git。推荐流程：

~~~text
页面创建和小范围验证
  → 导出 Job 定义
  → 删除环境专属秘密
  → 提交 Git 并评审
  → 测试 Project 导入验证
  → 再发布到生产 Project
~~~

导出的定义可以记录：

- Job UUID 和名称；
- Workflow Step；
- Option；
- Node Filter；
- Schedule；
- Timeout 和并发策略；
- 通知配置。

不要提交：

- API Token；
- SSH 私钥；
- 密码；
- Secure Option 的真实值；
- 仅适用于单台生产主机的临时信息。

### 13.18 一套建议的练习顺序

按以下顺序练习，可以逐步建立对 Rundeck 的完整认识：

1. 创建一个只包含 `localhost` 的实验 Project；
2. 创建输出 `hostname` 和 `date` 的 Job；
3. 接入一台测试 Linux Node；
4. 使用 Node Filter 按标签执行巡检；
5. 添加 Allowed Values Option；
6. 增加超时、错误处理和健康检查；
7. 配置每天一次的测试 Schedule；
8. 用 API Token 调用固定 Job；
9. 创建只允许运行 Job、不能编辑 Job 的测试用户；
10. 导出 Job 到 Git，再导入一个新的测试 Project；
11. 最后才尝试生产变更、审批和批量并发。

完成这一组练习后，至少要能够回答：

- Rundeck 用哪个身份连接目标 Node；
- 私钥保存在什么 Key Storage 路径；
- 哪条 ACL 允许某个用户运行 Job；
- Job 实际会选中哪些 Node；
- 参数如何校验，能否被用于命令注入；
- 失败后如何通知、重试或回滚；
- 如何根据 Execution ID 找到完整审计记录。

---

## 14. Project

Project 是核心隔离和组织单位。常见拆分方式：

- 按业务系统；
- 按团队；
- 按环境；
- 按安全域；
- 按账号或区域。

不建议把所有生产与测试 Job 放在同一个 Project 后仅靠命名区分。

Project 中通常包含：

- Job；
- Node Source；
- Node Executor；
- File Copier；
- Project ACL；
- Project Key Storage；
- SCM 配置；
- Webhook；
- Project 配置和 README。

命名示例：

~~~text
platform-dev
platform-prod
payments-prod
database-operations
~~~

---

## 15. Node 与 Resource Model

### 15.1 Node 是什么

Node 是可被 Job 选择的目标。常用属性：

~~~yaml
web-01:
  hostname: 10.20.10.11
  username: ops
  osFamily: unix
  osName: Linux
  tags: web,prod,cn-hangzhou
  description: Production web node 01
~~~

### 15.2 Resource Model Source

Node 可以来自：

- Project 文件；
- URL；
- Ansible Inventory；
- AWS、Azure、GCP 插件；
- Kubernetes；
- CMDB；
- 自定义脚本或 API。

动态 Inventory 比手工文件更适合频繁变化的云环境，但需要处理：

- API 限流；
- 缓存；
- 属性一致性；
- 已删除 Node；
- 凭据；
-故障时的旧数据。

### 15.3 Node Filter

示例：

~~~text
name: web-01
tags: prod+web
tags: prod,!maintenance
hostname: 10.20.*
~~~

执行前应在 UI 预览实际匹配的 Node。涉及删除、重启、扩容等操作时，应设置最大匹配数量或额外确认。

### 15.4 Node Executor 与 File Copier

Node Executor 决定怎样执行命令：

- SSH；
- WinRM；
-本地执行；
- Ansible；
- Kubernetes；
- 商业 Runner；
- 自定义插件。

File Copier 决定脚本和文件怎样传到远端。SSH Executor 和 Copier 的账号、Key Path、sudo 方式必须一致。

---

## 16. Job 与 Workflow

### 16.1 Job 组成

Job 通常包含：

- 名称和分组；
- 描述；
- Option；
- Workflow Steps；
- Node Filter；
- Dispatch；
- 错误处理；
- 超时和重试；
- 通知；
- Schedule；
-并发策略；
- Log Level。

### 16.2 Workflow Step

常见 Step：

- Command；
- Inline Script；
- Script File；
- Job Reference；
- HTTP Request；
- Ansible Playbook；
- Kubernetes Step；
- 插件 Step。

### 16.3 Node Step 与 Workflow Step

~~~text
Node Step
  对每个匹配 Node 执行

Workflow Step
  整个 Workflow 执行一次
~~~

例如：

- 对每台服务器运行 `systemctl status`：Node Step；
- 调用工单 API：Workflow Step；
- 等待 30 秒：Workflow Step；
- 汇总结果：Workflow Step。

### 16.4 Workflow Strategy

常见策略：

~~~text
node-first:
  Node A 执行所有步骤
  Node B 执行所有步骤

step-first:
  所有 Node 执行步骤 1
  所有 Node 执行步骤 2
~~~

滚动重启通常需要控制并发，避免所有实例同时停止。

### 16.5 Keep Going

`keepgoing=false` 遇到失败停止后续处理；`true` 允许继续其他 Node 或步骤。

选择取决于业务：

- 批量只读巡检可继续；
- 数据迁移或高风险发布通常应停止；
- 清理操作需要记录失败目标再补偿。

---

## 17. Job Option

Option 将 Job 变成受约束的自助表单。

示例参数：

~~~text
environment: dev / test / prod
service: api / worker / scheduler
replicas: 1-20
change_ticket: CHG-123456
reason: required text
~~~

### 17.1 输入约束

应设置：

- Required；
- Allowed Values；
- Enforced Values；
- Regex；
-默认值；
- 多值分隔符；
- 描述和影响说明。

不要把用户输入直接拼入 Shell：

~~~bash
sh -c "systemctl restart @option.service@"
~~~

即使有 Regex，也应在脚本中使用安全参数传递和白名单。

### 17.2 Secure Option

Secure Option 可隐藏显示，但仍需理解：

- 是否暴露给脚本；
- 是否写入日志；
- 插件是否安全处理；
- 是否从 Key Storage 获取；
- 是否能在子 Job 传递。

秘密优先从 Key Storage 获取，不应让普通用户每次复制生产密码。

### 17.3 运行上下文变量

常见引用：

~~~text
@option.environment@
@job.name@
@job.id@
@job.execid@
@node.name@
@node.hostname@
~~~

不同 Step Plugin 使用的语法可能不同，必须按插件文档核对。

---

## 18. 一个安全的服务重启 Runbook

不要只写一条 `systemctl restart`。完整流程应包含：

~~~text
检查变更单
  ↓
确认目标环境和节点数
  ↓
逐台摘除流量
  ↓
停止或重启服务
  ↓
检查进程和端口
  ↓
执行应用健康检查
  ↓
恢复流量
  ↓
下一台
  ↓
总体业务验证和通知
~~~

脚本示例：

~~~bash
#!/usr/bin/env bash
set -euo pipefail

service_name="$1"

case "$service_name" in
  api|worker|scheduler) ;;
  *)
    echo "unsupported service" >&2
    exit 2
    ;;
esac

sudo systemctl restart "$service_name"
sudo systemctl is-active --quiet "$service_name"
~~~

Job 应传递单独参数，而不是拼成一段任意 Shell。

---

## 19. Schedule、Webhook 与触发方式

### 19.1 触发来源

- Web UI；
- Schedule；
- REST API；
- `rd` CLI；
- Webhook；
- 其他 Job；
- 告警系统；
- ITSM。

### 19.2 Schedule

计划任务需要考虑：

- 时区；
- 夏令时；
- 节假日；
- 重复执行；
- 上次未完成；
- Misfire；
- 维护窗口；
-并发策略。

所有 Job 应明确使用的时区，不要默认认为容器时区与业务时区一致。

### 19.3 Webhook

Webhook 入口必须：

- 验证身份；
- 限制来源；
- 校验 Payload；
- 防重放；
- 设置速率限制；
- 映射固定 Job；
- 不允许外部直接提供任意命令。

### 19.4 告警自动修复

至少增加：

- 连续多次异常才触发；
- 同一事件去重；
- 冷却时间；
- 最大重试；
- 修复后验证；
- 失败转人工；
- Kill Switch；
- 完整审计。

---

## 20. Key Storage

Key Storage 用于保存或引用：

- SSH 私钥；
- 密码；
- Token；
-证书；
-插件凭据。

路径示例：

~~~text
keys/platform-prod/ssh
keys/payments/database/password
keys/cloud/api-token
~~~

原则：

- 按 Project 和环境隔离；
- ACL 限制 Read/Create/Update/Delete；
- Job 只引用路径；
-启用存储加密；
- 密钥轮换；
- 不允许 UI 用户下载不需要导出的私钥；
- 审计所有访问。

Docker 镜像默认可以配置 Key Storage 加密转换器。加密配置应从第一次初始化就确定，不能随意开关，否则可能导致已有数据不可读。

更高要求环境可集成 Vault、CyberArk 或云秘密服务；具体插件可能属于商业版。

---

## 21. 身份认证

可选方式包括：

- 本地 `realm.properties`；
- LDAP；
- Active Directory；
- PAM；
- SSO/OIDC/SAML，具体取决于版本和产品；
- 反向代理预认证；
- API Token。

### 21.1 本地账号

适合实验或紧急 Break-glass，不适合作为大规模人员生命周期管理方案。

生产至少应：

- 删除或修改默认密码；
- 使用强哈希；
- 限制管理员数量；
- 不共享账号；
- 定期验证 Break-glass；
- 记录登录和操作。

### 21.2 SSO/LDAP

身份系统提供用户和 Group，Rundeck ACL 把 Group 映射为权限。

上线前测试：

- 登录和退出；
- Group 映射；
- 离职禁用；
- SSO 故障时的管理员入口；
- 大小写；
-嵌套组；
- Session 超时。

---

## 22. ACL 权限模型

Rundeck 权限经常需要同时配置两个 Context。

### 22.1 Application Context

控制：

- 用户能否看到 Project；
- 系统级资源；
-创建 Project；
- API Token；
- System ACL；
- Key Storage；
-执行开关。

### 22.2 Project Context

控制 Project 内：

- 查看和执行 Job；
- 编辑和删除 Job；
- 查看 Node；
-执行 Ad-hoc Command；
- 查看 Activity；
-删除 Execution；
- Project 资源权限。

### 22.3 只读用户示例

~~~yaml
description: Allow project visibility
context:
  application: rundeck
for:
  project:
    - equals:
        name: platform-prod
      allow: [read]
by:
  group: platform_readonly

---

description: Read jobs and nodes
context:
  project: platform-prod
for:
  job:
    - allow: [read, view]
  node:
    - allow: [read]
  resource:
    - equals:
        kind: event
      allow: [read]
by:
  group: platform_readonly
~~~

### 22.4 只能执行特定 Job

~~~yaml
description: Project visibility
context:
  application: rundeck
for:
  project:
    - equals:
        name: platform-prod
      allow: [read]
by:
  group: platform_operators

---

description: Execute approved restart jobs
context:
  project: platform-prod
for:
  job:
    - match:
        group: operations/restart/.*
      allow: [read, run]
  node:
    - allow: [read, run]
by:
  group: platform_operators
~~~

实际 Action 名和 Node 权限组合应使用目标版本 ACL Editor 或官方文档验证。错误 ACL 可能过度授权。

### 22.5 权限设计原则

- 拒绝默认；
- Group 授权，不直接按个人；
-开发、测试、生产分开；
-查看、执行、编辑、管理分开；
- Ad-hoc Command 权限比运行固定 Job 更危险；
- Key Storage 单独授权；
- ACL 文件纳入 Git Review；
- 使用测试账号验证正向和反向权限。

---

## 23. Job as Code 与 SCM

Job 可以导出为 YAML 或 XML，并纳入版本控制。

建议流程：

~~~text
开发 Job
  ↓
导出定义
  ↓
Git Review
  ↓
测试环境导入
  ↓
执行测试
  ↓
生产导入
~~~

Job YAML 的字段随版本和插件变化。最可靠做法是：

1. 在目标版本 UI 创建最小 Job；
2. 导出 YAML；
3. 基于导出文件修改；
4. 通过 API 或 CLI 导入；
5. 再导出做差异检查。

不要手工复制陌生版本的大段 Job YAML 后直接导入生产。

### 23.1 Job 设计准则

- 固定 UUID；
- 清晰的 Group；
- 描述影响和回滚；
- Option 白名单；
- 超时；
- 禁止不必要并发；
-显式 Node Filter；
-错误处理；
-结果验证；
-通知；
- Owner 和 Runbook 链接。

---

## 24. REST API

Rundeck 6.1 当前文档 API 版本为 58。

### 24.1 基础变量

~~~bash
export RD_BASE_URL='https://rundeck.example.com'
export RD_API_VERSION='58'
read -rsp 'Rundeck token: ' RD_TOKEN
export RD_TOKEN
~~~

Token 不应写入 Shell Profile、脚本或 Git。

### 24.2 系统信息

~~~bash
curl --fail-with-body --silent --show-error \
  -H "Accept: application/json" \
  -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  "$RD_BASE_URL/api/$RD_API_VERSION/system/info"
~~~

### 24.3 Project 列表

~~~bash
curl --fail-with-body --silent --show-error \
  -H "Accept: application/json" \
  -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  "$RD_BASE_URL/api/$RD_API_VERSION/projects"
~~~

### 24.4 执行 Job

~~~bash
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  --data '{"options":{"environment":"test","service":"api"}}' \
  "$RD_BASE_URL/api/$RD_API_VERSION/job/JOB_UUID/run"
~~~

### 24.5 查询 Execution

~~~bash
curl --fail-with-body --silent --show-error \
  -H "Accept: application/json" \
  -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  "$RD_BASE_URL/api/$RD_API_VERSION/execution/EXECUTION_ID"
~~~

结束后：

~~~bash
unset RD_TOKEN
~~~

### 24.6 Token 安全

- 使用短过期时间；
- 只授予所需 Role；
- 一个集成一个 Token；
- 不放 URL Query；
- 通过 Header 发送；
-记录 Token ID 和 Owner；
- 定期轮换；
- 禁止打印；
- 撤销不再使用的 Token。

---

## 25. rd CLI

常用环境变量：

~~~bash
export RD_URL='https://rundeck.example.com/api/58'
read -rsp 'Rundeck token: ' RD_TOKEN
export RD_TOKEN
~~~

常用命令：

~~~bash
rd system info
rd projects list
rd jobs list -p platform-prod
rd jobs info -p platform-prod -i JOB_UUID
rd run -i JOB_UUID -F environment=test -F service=api
rd executions query -p platform-prod
~~~

查看帮助：

~~~bash
rd help
rd jobs help
rd run help
~~~

CLI 版本和 Server API 版本需要兼容。自动化脚本应检查退出码，不要只解析人类可读文本。

---

## 26. Ansible 集成

### 26.1 三种方式

1. Rundeck 执行 `ansible-playbook` 命令；
2. 使用 Ansible 插件作为 Workflow Step；
3. 使用 Ansible Inventory 作为 Node Source。

### 26.2 命令方式

~~~bash
ansible-playbook \
  -i /opt/automation/inventory/prod.ini \
  /opt/automation/playbooks/restart-service.yml \
  --limit "$RUNDECK_NODE_NAME" \
  --extra-vars "service_name=$SERVICE_NAME"
~~~

输入必须经过白名单。不要让用户直接输入任意 `--extra-vars`、Inventory 路径或 Playbook 路径。

### 26.3 权限边界

- Rundeck 负责谁能触发、传什么参数和审计；
- Ansible 负责目标状态和主机配置；
- SSH Key 进入 Key Storage；
- sudo 只允许必要命令；
- Inventory 与 Project 对齐；
- Playbook 进入 Git Review；
- Ansible 输出过滤秘密。

---

## 27. Kubernetes 集成

常见方式：

- 执行受控 `kubectl`；
- Kubernetes Plugin；
-调用 Argo CD API；
- 执行 Helm；
- 调用 Kubernetes API。

### 27.1 推荐边界

Rundeck 适合：

- 收集 Pod 和 Event；
-触发受控 Rollout Restart；
-扩缩容；
-切换维护模式；
-执行事故诊断；
-调用 GitOps Sync。

不建议：

- 允许任意 `kubectl exec`；
-让用户任意填写 Namespace 和资源名；
-绕过 GitOps 长期修改对象；
-使用 cluster-admin ServiceAccount。

### 27.2 ServiceAccount

为每个用途创建专用 ServiceAccount 和 Role，不共享管理员 Kubeconfig。Token 应短期化，Kubeconfig 不写入 Job 定义。

---

## 28. 通知与事件集成

通知时机通常包括：

- On Start；
- On Success；
- On Failure；
- On Abort；
-平均耗时或阈值；
-自定义插件事件。

通知内容应包含：

- Project 和 Job；
- Execution ID；
- 发起人；
-目标环境；
-开始和结束时间；
-结果；
-日志链接；
-后续处理。

不要包含：

- 密码；
- Token；
-完整环境变量；
- SSH 私钥；
-敏感业务数据。

告警平台触发 Rundeck 时，应把原始 Incident ID 作为 Option 传入，便于关联审计。

---

## 29. 日志、历史与审计

### 29.1 三类日志

| 类型 | 内容 |
|---|---|
| Server Log | 启动、插件、数据库、认证等服务日志 |
| Execution Log | Job 每次执行输出 |
| Audit Log | 用户、API 和权限相关操作 |

### 29.2 日志安全

- 脚本使用 `set +x` 处理秘密；
- 不打印环境变量全集；
- 对输出使用 Log Filter；
-限制日志查看 ACL；
-对象存储启用加密和生命周期；
- SIEM 收集审计日志；
-日志 URL 不公开。

### 29.3 日志存储

单实例可以使用文件系统；多实例或长期保留应考虑 S3 兼容对象存储或商业版支持方案。

数据库备份不一定包含所有 Execution Log，恢复计划必须覆盖日志存储。

---

## 30. 数据库、备份与恢复

### 30.1 数据库

生产优先使用受支持版本的 PostgreSQL、MySQL/MariaDB、SQL Server 或 Oracle。具体版本以当前系统要求页为准。

数据库保存的重要内容可能包括：

- Project 和 Job 元数据；
- Execution；
- Schedule；
- Key Storage 数据；
- ACL/API 配置；
-系统状态。

### 30.2 需要备份

- 外部数据库；
- `/etc/rundeck` 或容器配置；
- Project 文件；
- Realm/JAAS/SSO 配置；
- ACL Policy；
-插件；
- Key Storage 加密密钥和配置；
- Execution Log；
-自定义脚本；
-反向代理配置；
- License，若使用商业版。

### 30.3 恢复顺序

1. 恢复相同兼容版本；
2. 恢复数据库；
3. 恢复配置和加密材料；
4. 恢复插件；
5. 恢复 Execution Log；
6. 校验登录和 ACL；
7. 校验 Key Storage；
8. 禁用 Schedule；
9. 运行只读测试 Job；
10. 确认后再启用写操作和 Schedule。

不要在恢复环境中意外连接生产 Node 并自动执行到期 Schedule。

### 30.4 恢复演练

只备份不演练无法证明可恢复。至少验证：

- RTO/RPO；
-数据库一致性；
-加密 Key 可用；
-Job 可导入；
-Execution Log 可读；
-SSO 故障回退；
-Schedule 不重复执行。

---

## 31. 升级策略

升级前：

- 阅读当前和目标版本 Release Notes；
-检查 Java 和数据库版本；
-备份数据库、配置、插件和加密 Key；
-导出关键 Project；
-统计第三方插件；
-在副本环境测试；
-暂停 Schedule 和自动触发；
-准备回滚条件。

升级后：

- 检查数据库 Migration；
-确认 Server 健康；
-检查认证和 ACL；
-验证 Project/Node/Key Storage；
-运行只读 Job；
-运行测试环境写 Job；
-检查 API Client 和 rd CLI；
-确认日志和通知；
-再恢复 Schedule。

Rundeck 6 移除了旧 XML API 兼容开关，仍依赖旧 XML API 的集成必须在升级前迁移。

---

## 32. 性能与容量

影响因素：

- 并发 Execution；
- 每个 Job 的 Node 数；
- Dispatch Thread Count；
-执行日志大小；
-数据库延迟；
-插件；
- SSH 握手；
- Node Source 刷新；
- JVM Heap；
-对象存储。

优化顺序：

1. 找到慢在 Queue、连接、脚本、数据库还是日志；
2. 限制单 Job Thread Count；
3. 优化 SSH 连接和网络；
4. 缩减无用日志；
5. 优化数据库；
6. 调整 JVM；
7. 拆分 Project 或执行域；
8. 商业版评估 Runner/HA。

不要仅通过无限增加并发提高速度，否则可能同时压垮目标系统。

---

## 33. 常见故障排查

### 33.1 登录后跳转到 localhost

检查：

~~~text
RUNDECK_GRAILS_URL
RUNDECK_SERVER_FORWARDED
X-Forwarded-Proto
Host Header
~~~

### 33.2 Project 看不到

确认 Application Context 有对目标 Project 的 `read`，再检查用户 Group 映射。

### 33.3 能看到 Job 但不能执行

检查 Project Context 中 Job `run`、Node `read/run` 和相关 Resource 权限。

### 33.4 SSH 失败

在 Rundeck 运行身份下验证：

~~~bash
sudo -u rundeck ssh -vvv ops@target.example.com
~~~

检查：

- DNS 和路由；
- Host Key；
- Key Storage 路径；
-用户名；
-文件权限；
-sudo；
-跳板机；
-算法兼容。

### 33.5 Job 一直 Running

检查：

- 远端命令是否等待输入；
-脚本是否启动后台子进程但不关闭输出；
- SSH 超时；
- Workflow Step 超时；
-插件线程；
-数据库；
- Server 日志。

所有生产 Job 应设置合理 Timeout。

### 33.6 Schedule 没执行

检查：

- Job 的 Schedule 是否启用；
-系统 Execution 是否被全局禁用；
-时区；
-Server 时间；
-Quartz/数据库锁；
-多实例配置；
-上次 Execution 是否阻止并发。

### 33.7 API 401

- Token 是否过期；
- Header 是否正确；
-URL 是否为 HTTPS；
-代理是否丢弃 Header；
-API 版本是否支持；
-Token Role 是否正确。

### 33.8 API 403

身份已认证但 ACL 不允许。检查 Token Role、Application Context 和 Project Context。

### 33.9 数据库连接失败

检查：

~~~bash
getent hosts postgres.example.com
nc -vz postgres.example.com 5432
~~~

再确认 JDBC URL、驱动、账号、TLS、`pg_hba.conf` 和数据库连接数。

### 33.10 插件加载失败

检查：

- Rundeck 和 Java 版本；
-插件兼容矩阵；
-JAR 权限；
-重复插件；
-依赖冲突；
- Server 启动日志。

第三方插件升级前必须在测试环境验证。

---

## 34. Rundeck 与其他工具对比

| 工具 | 核心定位 | 与 Rundeck 的关系 |
|---|---|---|
| Ansible | 配置管理和批量执行 | Rundeck 编排和授权 Ansible |
| Terraform | IaC 和资源生命周期 | Rundeck 可触发受控 Plan/Apply |
| Jenkins/GitLab CI | CI/CD | Rundeck 更偏生产运维自助 |
| Argo CD | Kubernetes GitOps | Rundeck 可触发诊断或 Sync |
| AWX/AAP | Ansible 控制平面 | 与 Rundeck 部分重叠，Ansible 更原生 |
| StackStorm | 事件驱动自动化 | 更偏规则和事件自动化 |
| Jenkins | 通用流水线 | 可做类似任务，但权限和 Node 模型不同 |
| Cron | 简单计划任务 | Rundeck 提供 UI、ACL、日志和参数 |

如果自动化几乎全部是 Ansible，AWX/AAP 可能更自然；如果需要跨脚本、API、Ansible、云和人工自助，Rundeck 更适合做统一入口。

---

## 35. 生产落地路线

### 阶段一：只读诊断

- 建一个测试 Project；
-接入少量 Node；
-只做 `uptime`、磁盘、进程、健康检查；
-配置 SSO 和只读 ACL；
-验证日志与审计。

### 阶段二：低风险自助

- 缓存清理；
-日志收集；
-只读数据库检查；
-测试环境服务重启；
-参数白名单；
-结果通知。

### 阶段三：生产操作

- 工单号必填；
-审批或双人复核；
-滚动执行；
-健康检查；
-回退；
-限制并发和目标数；
-按环境分权。

### 阶段四：事件自动化

- 告警触发诊断；
-人工确认后修复；
-成熟后才考虑全自动；
-设置 Kill Switch、冷却和最大次数；
-定期复盘误触发。

---

## 36. 上线检查清单

### 36.1 平台

- [ ] 使用受支持的 Rundeck、Java 和数据库版本；
- [ ] 生产未使用 H2；
- [ ] 配置外部域名和 HTTPS；
- [ ] 数据库、配置和日志有备份；
- [ ] 镜像或软件包固定版本；
- [ ] 插件来源可信。

### 36.2 身份和权限

- [ ] 默认密码已移除；
- [ ] SSO/LDAP Group 映射已验证；
- [ ] Application 和 Project ACL 都已配置；
- [ ] 普通用户不能执行 Ad-hoc 任意命令；
- [ ] API Token 最小权限和短期有效；
- [ ] Break-glass 账号已演练。

### 36.3 Job

- [ ] Option 有白名单和校验；
- [ ] 没有 Shell 注入；
- [ ] Node Filter 不会扩大目标；
- [ ] 有 Timeout 和并发限制；
- [ ] 有错误处理和业务验证；
- [ ] 破坏性操作需要审批；
- [ ] Job 定义进入版本控制。

### 36.4 凭据

- [ ] Secret 不在 Job、Git 和日志；
- [ ] Key Storage 已加密；
- [ ] Project 间秘密隔离；
- [ ] SSH/sudo 最小权限；
- [ ] 密钥可轮换；
- [ ] 外部 Secret Plugin 已测试。

### 36.5 运维

- [ ] 日志和审计已接入；
- [ ] Schedule 时区正确；
- [ ] 升级和回滚已演练；
- [ ] 数据库和 Execution Log 恢复已验证；
- [ ] 自动修复有去重、冷却和 Kill Switch；
- [ ] Rundeck 自身故障不会阻塞唯一人工恢复路径。

---

## 37. 命令与 API 速查

### 服务

~~~bash
sudo systemctl status rundeckd
sudo systemctl restart rundeckd
sudo journalctl -u rundeckd -f
~~~

### Docker

~~~bash
docker compose up -d
docker compose ps
docker compose logs -f rundeck
docker compose stop
~~~

### rd CLI

~~~bash
rd system info
rd projects list
rd jobs list -p PROJECT
rd run -i JOB_UUID
rd executions query -p PROJECT
~~~

### API

~~~bash
curl -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  "$RD_BASE_URL/api/58/system/info"
~~~

### SSH 诊断

~~~bash
sudo -u rundeck ssh -vvv user@node.example.com
~~~

---

## 38. 官方资料

- [Rundeck / Runbook Automation 文档](https://docs.rundeck.com/docs/)
- [Rundeck 官方 GitHub](https://github.com/rundeck/rundeck)
- [Rundeck Releases](https://github.com/rundeck/rundeck/releases)
- [Rundeck Introduction](https://docs.rundeck.com/docs/about/introduction.html)
- [新 Project 入门流程](https://docs.rundeck.com/docs/learning/getting-started/projects-overview.html)
- [通过 SSH 接入 Linux/Unix Node](https://docs.rundeck.com/docs/learning/howto/ssh-on-linux-nodes.html)
- [创建 Rundeck Job](https://docs.rundeck.com/docs/learning/getting-started/jobs/creating-a-job.html)
- [Administration Guide](https://docs.rundeck.com/docs/administration/)
- [System Requirements](https://docs.rundeck.com/docs/administration/install/system-requirements.html)
- [User Guide](https://docs.rundeck.com/docs/manual/)
- [Jobs](https://docs.rundeck.com/docs/manual/jobs/)
- [Node Resource YAML](https://docs.rundeck.com/docs/manual/document-format-reference/resource-yaml-v13.html)
- [Key Storage](https://docs.rundeck.com/docs/manual/key-storage/)
- [Authentication](https://docs.rundeck.com/docs/administration/security/authentication.html)
- [ACL Authorization](https://docs.rundeck.com/docs/administration/security/authorization.html)
- [API Reference](https://docs.rundeck.com/docs/api/)
- [rd CLI](https://docs.rundeck.com/docs/rd-cli/)
- [rd CLI 操作示例](https://docs.rundeck.com/docs/learning/howto/learn-rd-cli.html)
- [Community 与商业版比较](https://www.rundeck.com/community-vs-enterprise)

涉及版本、插件、商业能力和 API 字段时，应以目标 Rundeck 实例对应版本的官方文档和实际导出结果为准。
