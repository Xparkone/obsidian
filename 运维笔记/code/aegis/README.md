# Aegis：AI 堡垒机服务

Aegis 是一个面向用户和 AI Agent 的操作入口。身份拿到的密钥只用于识别调用方，调用方能看到哪些服务器、能执行什么动作由显式授权决定；每个命令经过规则引擎后才进入执行适配器，违规动作立即停止并写入审计。它必须通过 Aegis HTTP 服务访问，不能直接双击 `index.html` 当成完整服务使用。

当前交付是一个可直接启动的单实例服务：本地默认使用 SQLite，生产环境可通过 `AEGIS_DATABASE_URL` 切换到 PostgreSQL。生产审计还应配置对象存储的 Object Lock/WORM 归档；仓库内的 JSONL 适配器只提供本地 staging 和 hash-chain 校验，不等于不可变存储。包含：

- 用户/AI 身份与 API Key：数据库只保存 scrypt 哈希，创建接口只返回一次明文密钥。
- 服务器资产与访问授权：`access_grants` 以身份和服务器为联合主键，未授权服务器不可执行。
- 可扩展规则：规则保存为 `id/name/pattern/reason/severity`，当前内置文件系统破坏、服务中断、远程脚本和 fork bomb 规则。
- 审计与告警：允许、阻断、权限拒绝都会落库；命中阻断规则后通过配置的飞书、钉钉、企业微信 webhook 发送通知。
- 执行适配器：默认 `dry-run`，也支持将 `AEGIS_EXECUTOR_MODE=ssh` 切换到受控 SSH 客户端；两种模式都复用同一条身份、权限、规则和审计路径。
- 前端控制台：总览、策略事件、身份、资产和规则指标，视觉 token 参考 Aegis Figma 设计。

## 运行

```bash
cd code/aegis
cp .env.example .env
python3 main.py
```

`main.py` 会自动读取当前目录的 `.env`，已经存在的 shell 环境变量优先；修改 `.env` 后需要重启进程。打开 <http://127.0.0.1:8080/>。本地默认数据库写入项目下的 `data/aegis.db`，不需要 root 权限；Docker Compose 会把数据写入容器 Volume。首次启动默认创建两台演示服务器；生产环境将 `AEGIS_SEED_DEMO=false`。不要使用 `file://.../static/index.html` 打开，因为浏览器不会把它当成 Aegis 服务，也无法请求 `/api/v1/*`。
生产环境设置 `AEGIS_DATABASE_URL=postgresql://...` 后，服务会使用 PostgreSQL backend；镜像已安装 `psycopg[binary]`。当前启动时的 schema 创建只适合 bootstrap，正式环境仍应使用受审查的版本化迁移流程，不要把自动建表当成完整迁移系统。
管理接口（创建身份、服务器、授权和规则）必须带 `X-Aegis-Admin`；未配置 `AEGIS_ADMIN_TOKEN` 时管理写接口默认拒绝，请把 `.env` 里的示例值换成随机值并放入 Secret Manager。
前端右上角可以分别保存管理员令牌和身份密钥。它们只保存在当前浏览器 `localStorage`，保存后会用 `X-Aegis-Admin` / `X-Aegis-Key` 请求对应接口；未提供身份密钥时不会返回服务器资产详情。

容器方式：

```bash
docker compose up --build
```

## API 最小流程

创建身份，密钥只在响应中显示一次：

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/principals \
  -H 'X-Aegis-Admin: change-this-in-a-secret-manager' \
  -H 'Content-Type: application/json' \
  -d '{"name":"ops-agent","kind":"ai"}'
```

创建服务器和授权：

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/servers \
  -H 'X-Aegis-Admin: change-this-in-a-secret-manager' \
  -H 'Content-Type: application/json' \
  -d '{"name":"prod-api-02","address":"10.20.1.12","environment":"production","tags":["api"]}'

curl -sS -X POST http://127.0.0.1:8080/api/v1/access-grants \
  -H 'X-Aegis-Admin: change-this-in-a-secret-manager' \
  -H 'Content-Type: application/json' \
  -d '{"principal_id":1,"server_id":3,"actions":["read"]}'
```

执行请求必须提供 `Authorization: Bearer <密钥>` 或 `X-Aegis-Key`：

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/execute \
  -H 'Authorization: Bearer aegis_...' \
  -H 'Content-Type: application/json' \
  -d '{"server_id":3,"command":"uname -a"}'
```

## AI Agent 接入

AI 接入只需要它自己的身份密钥，不需要管理员令牌，也不需要 SSH 私钥。管理员先创建 AI 身份：

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/principals \
  -H "X-Aegis-Admin: $AEGIS_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"ops-agent","kind":"ai"}'
```

把响应中的 `api_key` 只交给这个 AI，并用管理员令牌授权它访问指定服务器：

```bash
curl -sS -X POST http://127.0.0.1:8080/api/v1/access-grants \
  -H "X-Aegis-Admin: $AEGIS_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"principal_id":1,"server_id":1,"actions":["read","execute"]}'
```

AI 侧只调用两个接口：先 `GET /api/v1/servers` 获取它有权看到的资产，再 `POST /api/v1/execute` 提交命令。每次请求都带 `X-Aegis-Key: aegis_...`。如果返回 403，AI 应把规则或权限阻断作为最终结果记录下来，不能改写命令绕过策略后循环重试。

仓库提供了不依赖第三方包的客户端示例：[examples/ai_agent.py](examples/ai_agent.py)：

```bash
export AEGIS_AGENT_KEY='aegis_...'
export AEGIS_URL='http://127.0.0.1:8080'
python3 examples/ai_agent.py
```

接入 LangChain、OpenAI function calling 或其他 Agent 框架时，把 `visible_servers()` 和 `execute(server_id, command)` 包装成工具即可。模型只生成工具参数，Aegis 仍是唯一的执行入口；不要把管理员令牌、SSH 私钥或其他服务器凭据放进模型上下文。

### 接入 Codex 类软件：MCP

如果 Agent Host 支持 MCP，直接启动仓库里的 stdio MCP 适配器：

```bash
export AEGIS_URL='http://127.0.0.1:8080'
export AEGIS_AGENT_KEY='aegis_...'
python3 integrations/aegis_mcp_server.py
```

在支持 MCP 的客户端配置中加入同等内容（不同软件的配置文件名称可能不同）：

```json
{
  "mcpServers": {
    "aegis": {
      "command": "python3",
      "args": ["/Users/lijiaxuan/Documents/hermes/运维笔记/code/aegis/integrations/aegis_mcp_server.py"],
      "env": {
        "AEGIS_URL": "http://127.0.0.1:8080",
        "AEGIS_AGENT_KEY": "aegis_..."
      }
    }
  }
}
```

客户端启动后会发现三个工具：`aegis_list_servers`、`aegis_execute`、`aegis_get_audit`。Agent 只能通过这些工具操作，不能获得 Aegis 管理员令牌或底层 SSH 凭据。若目标软件不支持 MCP，则使用前面的 HTTP API 客户端方式；不要把 Aegis 直接包装成无权限限制的本地 shell 工具。

启用 SSH 执行前，在资产登记时填写 `username`、`port` 和受信任的 `known_hosts_path`，然后设置：

```bash
AEGIS_EXECUTOR_MODE=ssh
```

执行命令还必须通过结构化白名单。默认只允许 `uname`、`id`、`whoami`、`hostname`、`uptime`、`pwd`、`ls`、`df`、`free` 和 `date`；可通过 `AEGIS_ALLOWED_COMMANDS` 按命令名显式扩展。命令会先分词并拒绝管道、重定向、命令替换、通配符、引号和换行，不能把任意 Shell 脚本交给 SSH。白名单只控制命令入口，远端账号仍应使用最小权限。

SSH 模式还必须配置一个只读的受控凭据目录：

```bash
AEGIS_SSH_CREDENTIAL_DIR=/run/aegis/credentials
```

资产的 `credential_ref` 只能填写类似 `secret://prod-api-02` 的引用，服务端会从该目录解析私钥文件；没有凭据 Provider、Secret 文件、严格文件权限或 `known_hosts` 文件时会失败关闭。SSH 客户端显式使用解析出的 `-i` 文件，并禁用 SSH Agent、密码和交互式认证，不会回退到启动用户的默认密钥。私钥内容不能通过 API 或 `.env` 传入；当前目录 Provider 只是挂载 Secret 的边界，接入生产环境仍应替换为 KMS/Secret Manager Provider。

## 规则扩展设计

MVP 用正则规则是为了让新增规则不需要改执行流程：新增一条规则记录即可。生产版建议把规则拆成以下稳定接口：

当前新增规则的 `pattern` 使用大小写不敏感正则，并限制为最多 512 个字符；系统会拒绝反向引用、高级回溯构造以及明显可能导致灾难性回溯的重复结构。启用规则最多 256 条。规则配置加载失败时执行路径会失败关闭，`/readyz` 返回 503，避免把无效策略当成“没有命中规则”。

```text
Rule.evaluate(CommandContext) -> Allow | Deny | RequireApproval
CommandContext = principal, server, action, command, labels, time, source_ip
```

规则按 `scope`（全局/身份/资产/标签）、`priority`、`enabled` 和 `version` 管理，组合出“拒绝优先”的确定性决策。规则实现可放在 `app/rules/`，内置 `RegexRule`、`PathRule`、`RateLimitRule`，后续再接 OPA/Rego；每次决策保存规则版本和输入摘要，保证审计可复盘。高风险写操作可以返回 `RequireApproval`，交给人工审批后再恢复同一个 execution id。

## 生产边界

- 需要接入真实 SSH/Kubernetes 时，新增受限的 executor adapter，并以 allowlist 命令、最小权限账号、连接超时和会话录屏为前置条件；不要把用户提交的 host、端口或私钥直接交给 shell。
- API Key 适合 MVP。生产环境应接 OIDC/JWT、密钥轮换、撤销、短期 token 和 KMS/Secret Manager。
- webhook 失败不阻断审计写入；需要告警可靠送达时增加消息队列、重试、签名校验和死信。
- SQLite 只用于本地或单实例验证；生产部署必须配置 `AEGIS_DATABASE_URL` 使用 PostgreSQL，并将审计写入不可变存储。
- `AEGIS_AUDIT_ARCHIVE_PATH` 只启用本地 hash-chain JSONL staging；`AEGIS_AUDIT_ARCHIVE_REQUIRED=true` 时归档写入失败会阻断请求。真正生产归档必须由外部对象存储启用 Object Lock/WORM、保留策略和独立权限，不能把本地文件当作不可变证据。
- 配置 `AEGIS_AUDIT_ARCHIVE_S3_BUCKET` 后，服务会使用 S3 兼容 Object Lock 适配器，以 `COMPLIANCE` 保留模式写入事件对象；目标 bucket 必须事先启用版本控制和 Object Lock，凭据应由云 SDK/工作负载身份提供。
- 目标主机的防火墙或安全组必须只允许 Aegis 服务/受控跳板机访问 SSH 端口；仅在代码中关闭 Agent 和密码认证，不能阻止用户拿着其他凭据绕过 Aegis 直连。

## 验证

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
python3 -m py_compile main.py app/*.py
```

当前测试为本地静态/单元验证，未连接真实服务器、SSH、飞书、钉钉、企业微信或生产数据库。
