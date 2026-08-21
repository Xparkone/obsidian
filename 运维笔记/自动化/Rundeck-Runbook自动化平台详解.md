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

## 13. Project

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

## 14. Node 与 Resource Model

### 14.1 Node 是什么

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

### 14.2 Resource Model Source

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

### 14.3 Node Filter

示例：

~~~text
name: web-01
tags: prod+web
tags: prod,!maintenance
hostname: 10.20.*
~~~

执行前应在 UI 预览实际匹配的 Node。涉及删除、重启、扩容等操作时，应设置最大匹配数量或额外确认。

### 14.4 Node Executor 与 File Copier

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

## 15. Job 与 Workflow

### 15.1 Job 组成

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

### 15.2 Workflow Step

常见 Step：

- Command；
- Inline Script；
- Script File；
- Job Reference；
- HTTP Request；
- Ansible Playbook；
- Kubernetes Step；
- 插件 Step。

### 15.3 Node Step 与 Workflow Step

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

### 15.4 Workflow Strategy

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

### 15.5 Keep Going

`keepgoing=false` 遇到失败停止后续处理；`true` 允许继续其他 Node 或步骤。

选择取决于业务：

- 批量只读巡检可继续；
- 数据迁移或高风险发布通常应停止；
- 清理操作需要记录失败目标再补偿。

---

## 16. Job Option

Option 将 Job 变成受约束的自助表单。

示例参数：

~~~text
environment: dev / test / prod
service: api / worker / scheduler
replicas: 1-20
change_ticket: CHG-123456
reason: required text
~~~

### 16.1 输入约束

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

### 16.2 Secure Option

Secure Option 可隐藏显示，但仍需理解：

- 是否暴露给脚本；
- 是否写入日志；
- 插件是否安全处理；
- 是否从 Key Storage 获取；
- 是否能在子 Job 传递。

秘密优先从 Key Storage 获取，不应让普通用户每次复制生产密码。

### 16.3 运行上下文变量

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

## 17. 一个安全的服务重启 Runbook

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

## 18. Schedule、Webhook 与触发方式

### 18.1 触发来源

- Web UI；
- Schedule；
- REST API；
- `rd` CLI；
- Webhook；
- 其他 Job；
- 告警系统；
- ITSM。

### 18.2 Schedule

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

### 18.3 Webhook

Webhook 入口必须：

- 验证身份；
- 限制来源；
- 校验 Payload；
- 防重放；
- 设置速率限制；
- 映射固定 Job；
- 不允许外部直接提供任意命令。

### 18.4 告警自动修复

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

## 19. Key Storage

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

## 20. 身份认证

可选方式包括：

- 本地 `realm.properties`；
- LDAP；
- Active Directory；
- PAM；
- SSO/OIDC/SAML，具体取决于版本和产品；
- 反向代理预认证；
- API Token。

### 20.1 本地账号

适合实验或紧急 Break-glass，不适合作为大规模人员生命周期管理方案。

生产至少应：

- 删除或修改默认密码；
- 使用强哈希；
- 限制管理员数量；
- 不共享账号；
- 定期验证 Break-glass；
- 记录登录和操作。

### 20.2 SSO/LDAP

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

## 21. ACL 权限模型

Rundeck 权限经常需要同时配置两个 Context。

### 21.1 Application Context

控制：

- 用户能否看到 Project；
- 系统级资源；
-创建 Project；
- API Token；
- System ACL；
- Key Storage；
-执行开关。

### 21.2 Project Context

控制 Project 内：

- 查看和执行 Job；
- 编辑和删除 Job；
- 查看 Node；
-执行 Ad-hoc Command；
- 查看 Activity；
-删除 Execution；
- Project 资源权限。

### 21.3 只读用户示例

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

### 21.4 只能执行特定 Job

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

### 21.5 权限设计原则

- 拒绝默认；
- Group 授权，不直接按个人；
-开发、测试、生产分开；
-查看、执行、编辑、管理分开；
- Ad-hoc Command 权限比运行固定 Job 更危险；
- Key Storage 单独授权；
- ACL 文件纳入 Git Review；
- 使用测试账号验证正向和反向权限。

---

## 22. Job as Code 与 SCM

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

### 22.1 Job 设计准则

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

## 23. REST API

Rundeck 6.1 当前文档 API 版本为 58。

### 23.1 基础变量

~~~bash
export RD_BASE_URL='https://rundeck.example.com'
export RD_API_VERSION='58'
read -rsp 'Rundeck token: ' RD_TOKEN
export RD_TOKEN
~~~

Token 不应写入 Shell Profile、脚本或 Git。

### 23.2 系统信息

~~~bash
curl --fail-with-body --silent --show-error \
  -H "Accept: application/json" \
  -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  "$RD_BASE_URL/api/$RD_API_VERSION/system/info"
~~~

### 23.3 Project 列表

~~~bash
curl --fail-with-body --silent --show-error \
  -H "Accept: application/json" \
  -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  "$RD_BASE_URL/api/$RD_API_VERSION/projects"
~~~

### 23.4 执行 Job

~~~bash
curl --fail-with-body --silent --show-error \
  -X POST \
  -H "Accept: application/json" \
  -H "Content-Type: application/json" \
  -H "X-Rundeck-Auth-Token: $RD_TOKEN" \
  --data '{"options":{"environment":"test","service":"api"}}' \
  "$RD_BASE_URL/api/$RD_API_VERSION/job/JOB_UUID/run"
~~~

### 23.5 查询 Execution

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

### 23.6 Token 安全

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

## 24. rd CLI

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

## 25. Ansible 集成

### 25.1 三种方式

1. Rundeck 执行 `ansible-playbook` 命令；
2. 使用 Ansible 插件作为 Workflow Step；
3. 使用 Ansible Inventory 作为 Node Source。

### 25.2 命令方式

~~~bash
ansible-playbook \
  -i /opt/automation/inventory/prod.ini \
  /opt/automation/playbooks/restart-service.yml \
  --limit "$RUNDECK_NODE_NAME" \
  --extra-vars "service_name=$SERVICE_NAME"
~~~

输入必须经过白名单。不要让用户直接输入任意 `--extra-vars`、Inventory 路径或 Playbook 路径。

### 25.3 权限边界

- Rundeck 负责谁能触发、传什么参数和审计；
- Ansible 负责目标状态和主机配置；
- SSH Key 进入 Key Storage；
- sudo 只允许必要命令；
- Inventory 与 Project 对齐；
- Playbook 进入 Git Review；
- Ansible 输出过滤秘密。

---

## 26. Kubernetes 集成

常见方式：

- 执行受控 `kubectl`；
- Kubernetes Plugin；
-调用 Argo CD API；
- 执行 Helm；
- 调用 Kubernetes API。

### 26.1 推荐边界

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

### 26.2 ServiceAccount

为每个用途创建专用 ServiceAccount 和 Role，不共享管理员 Kubeconfig。Token 应短期化，Kubeconfig 不写入 Job 定义。

---

## 27. 通知与事件集成

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

## 28. 日志、历史与审计

### 28.1 三类日志

| 类型 | 内容 |
|---|---|
| Server Log | 启动、插件、数据库、认证等服务日志 |
| Execution Log | Job 每次执行输出 |
| Audit Log | 用户、API 和权限相关操作 |

### 28.2 日志安全

- 脚本使用 `set +x` 处理秘密；
- 不打印环境变量全集；
- 对输出使用 Log Filter；
-限制日志查看 ACL；
-对象存储启用加密和生命周期；
- SIEM 收集审计日志；
-日志 URL 不公开。

### 28.3 日志存储

单实例可以使用文件系统；多实例或长期保留应考虑 S3 兼容对象存储或商业版支持方案。

数据库备份不一定包含所有 Execution Log，恢复计划必须覆盖日志存储。

---

## 29. 数据库、备份与恢复

### 29.1 数据库

生产优先使用受支持版本的 PostgreSQL、MySQL/MariaDB、SQL Server 或 Oracle。具体版本以当前系统要求页为准。

数据库保存的重要内容可能包括：

- Project 和 Job 元数据；
- Execution；
- Schedule；
- Key Storage 数据；
- ACL/API 配置；
-系统状态。

### 29.2 需要备份

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

### 29.3 恢复顺序

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

### 29.4 恢复演练

只备份不演练无法证明可恢复。至少验证：

- RTO/RPO；
-数据库一致性；
-加密 Key 可用；
-Job 可导入；
-Execution Log 可读；
-SSO 故障回退；
-Schedule 不重复执行。

---

## 30. 升级策略

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

## 31. 性能与容量

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

## 32. 常见故障排查

### 32.1 登录后跳转到 localhost

检查：

~~~text
RUNDECK_GRAILS_URL
RUNDECK_SERVER_FORWARDED
X-Forwarded-Proto
Host Header
~~~

### 32.2 Project 看不到

确认 Application Context 有对目标 Project 的 `read`，再检查用户 Group 映射。

### 32.3 能看到 Job 但不能执行

检查 Project Context 中 Job `run`、Node `read/run` 和相关 Resource 权限。

### 32.4 SSH 失败

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

### 32.5 Job 一直 Running

检查：

- 远端命令是否等待输入；
-脚本是否启动后台子进程但不关闭输出；
- SSH 超时；
- Workflow Step 超时；
-插件线程；
-数据库；
- Server 日志。

所有生产 Job 应设置合理 Timeout。

### 32.6 Schedule 没执行

检查：

- Job 的 Schedule 是否启用；
-系统 Execution 是否被全局禁用；
-时区；
-Server 时间；
-Quartz/数据库锁；
-多实例配置；
-上次 Execution 是否阻止并发。

### 32.7 API 401

- Token 是否过期；
- Header 是否正确；
-URL 是否为 HTTPS；
-代理是否丢弃 Header；
-API 版本是否支持；
-Token Role 是否正确。

### 32.8 API 403

身份已认证但 ACL 不允许。检查 Token Role、Application Context 和 Project Context。

### 32.9 数据库连接失败

检查：

~~~bash
getent hosts postgres.example.com
nc -vz postgres.example.com 5432
~~~

再确认 JDBC URL、驱动、账号、TLS、`pg_hba.conf` 和数据库连接数。

### 32.10 插件加载失败

检查：

- Rundeck 和 Java 版本；
-插件兼容矩阵；
-JAR 权限；
-重复插件；
-依赖冲突；
- Server 启动日志。

第三方插件升级前必须在测试环境验证。

---

## 33. Rundeck 与其他工具对比

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

## 34. 生产落地路线

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

## 35. 上线检查清单

### 35.1 平台

- [ ] 使用受支持的 Rundeck、Java 和数据库版本；
- [ ] 生产未使用 H2；
- [ ] 配置外部域名和 HTTPS；
- [ ] 数据库、配置和日志有备份；
- [ ] 镜像或软件包固定版本；
- [ ] 插件来源可信。

### 35.2 身份和权限

- [ ] 默认密码已移除；
- [ ] SSO/LDAP Group 映射已验证；
- [ ] Application 和 Project ACL 都已配置；
- [ ] 普通用户不能执行 Ad-hoc 任意命令；
- [ ] API Token 最小权限和短期有效；
- [ ] Break-glass 账号已演练。

### 35.3 Job

- [ ] Option 有白名单和校验；
- [ ] 没有 Shell 注入；
- [ ] Node Filter 不会扩大目标；
- [ ] 有 Timeout 和并发限制；
- [ ] 有错误处理和业务验证；
- [ ] 破坏性操作需要审批；
- [ ] Job 定义进入版本控制。

### 35.4 凭据

- [ ] Secret 不在 Job、Git 和日志；
- [ ] Key Storage 已加密；
- [ ] Project 间秘密隔离；
- [ ] SSH/sudo 最小权限；
- [ ] 密钥可轮换；
- [ ] 外部 Secret Plugin 已测试。

### 35.5 运维

- [ ] 日志和审计已接入；
- [ ] Schedule 时区正确；
- [ ] 升级和回滚已演练；
- [ ] 数据库和 Execution Log 恢复已验证；
- [ ] 自动修复有去重、冷却和 Kill Switch；
- [ ] Rundeck 自身故障不会阻塞唯一人工恢复路径。

---

## 36. 命令与 API 速查

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

## 37. 官方资料

- [Rundeck / Runbook Automation 文档](https://docs.rundeck.com/docs/)
- [Rundeck 官方 GitHub](https://github.com/rundeck/rundeck)
- [Rundeck Releases](https://github.com/rundeck/rundeck/releases)
- [Rundeck Introduction](https://docs.rundeck.com/docs/about/introduction.html)
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
- [Community 与商业版比较](https://www.rundeck.com/community-vs-enterprise)

涉及版本、插件、商业能力和 API 字段时，应以目标 Rundeck 实例对应版本的官方文档和实际导出结果为准。
