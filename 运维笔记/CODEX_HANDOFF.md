# Codex 工作交接

更新时间：2026-09-02
当前主机：本地 macOS
项目路径：`/Users/lijiaxuan/Documents/hermes/运维笔记`
当前分支：`main`

## 当前目标

编写 GitLab 详细日志审计的中文运维文档，说明审计事件、结构化组件日志、外部事件流、集中采集和验收流程。

## 已确认事实

- 现有笔记按主题分类，GitLab 文档归入 `CI-CD/`，根目录索引为 `README.md`。
- 当前仓库没有已有 `CODEX_HANDOFF.md`；本文件为本阶段新增交接文件。
- 官方文档当前说明：Audit Events 的 UI/API 能力按版本和套餐变化；实例级外部审计事件流适用于 Ultimate 的 Self-Managed/Dedicated；`audit_json.log`、`api_json.log`、`production_json.log` 等结构化日志按安装方式有不同路径。

## 基于证据的判断

- “开详细审计”应拆成数据库审计事件、GitLab 组件日志和外部集中留存三层，不能依赖单一 debug 日志级别。
- 长期审计应使用外部采集、事件 `id` 去重、`correlation_id` 关联和不可变归档；页面 CSV 不应作为唯一证据。

## 尚未验证的可能性

- 目标 GitLab 实例的 Edition、版本、许可证、安装方式、实际日志挂载、网络出口和 SIEM 接收端尚未现场确认。
- 文档中的命令和验收动作未在真实 GitLab、SIEM、云存储或 Kubernetes 集群执行。

## 已完成

- 新增 `CI-CD/GitLab审计日志详细配置与运维指南.md`。
- 更新 `README.md`，加入新文档索引。
- 完成围栏、Mermaid、内部链接和差异空白静态检查。

## 修改文件

- `CI-CD/GitLab审计日志详细配置与运维指南.md`
- `README.md`
- `CODEX_HANDOFF.md`

## 验证结果

- Markdown 围栏：20 个，成对。
- Mermaid `sequenceDiagram`：1 个。
- 新文档内部链接：未发现缺失。
- `git diff --check`：通过；新文件单独执行差异检查也通过。

## 未解决问题

- 未针对任何具体 GitLab 实例生成可直接执行的变更命令；必须先确认版本、套餐、安装方式和权限。

## 下一步

- 如需落地，先执行文档第 2.3 节只读预检。
- 按目标套餐选择 UI/API、`audit_json.log` 采集或 Ultimate 外部事件流。
- 使用测试 Group/Project 完成第 9 节事件生成、送达、去重、告警和归档验收。

## 重要命令

- Omnibus：`sudo gitlab-rake gitlab:env:info`、`sudo gitlab-ctl status`。
- Docker：`docker ps`、`docker inspect <gitlab-container>`。
- Helm：`kubectl -n <gitlab-namespace> get pods -o wide`、`helm -n <gitlab-namespace> list`。

## 注意事项

- 不在交接文档中记录密码、Token、Cookie、完整认证 Header、云密钥或完整环境变量。
- 不能把“进程健康、HTTP 200、日志文件存在”当作审计端到端成功；需要验证事件生成、落库/文件、外部送达和归档。

## 本阶段：Status API MVP（2026-09-04）

### 当前目标

开发一个通过 Bearer Token 暴露服务器、Kubernetes、Pod 和中间件状态的只读 HTTP API。

### 已确认事实

- 原仓库只有 `go/todo-api/` 示例，没有现成状态服务；已新增独立工程 `go/status-api/`。
- API 使用 Go 标准库，包含 `/api/v1/status`、`/api/v1/host`、`/api/v1/k8s`、`/api/v1/k8s/pods`、`/api/v1/middlewares`、`/healthz` 和 `/readyz`。
- 受保护接口使用 `Authorization: Bearer <token>`，通过常量时间比较校验 token；未配置 token 时受保护接口全部返回 401。
- Kubernetes 采集使用只读 REST API，读取 `/version`、节点和全命名空间 Pod 摘要；集群内自动读取 ServiceAccount token 和 CA。
- 中间件探针支持 HTTP/HTTPS/TCP，以及以 TCP 方式检查 Redis、MySQL、Kafka；目标来自 `STATUS_MIDDLEWARES` 配置，不接受请求方任意地址。

### 尚未验证的可能性

- 尚未在真实 Kubernetes 集群中验证 ServiceAccount RBAC、API CA、节点和 Pod 数据返回。
- 当前主机采集器读取运行进程所在环境的 `/proc`；API 运行在 Kubernetes Pod 内时不等同于节点级指标。
- 尚未实现 Prometheus/Node Exporter 接入、缓存、JWT/OIDC、历史数据、多集群和完整中间件协议探针。

### 已完成

- 新增 `go/status-api/` 工程、README 和单元测试。
- 实现统一状态模型、主机采集、Kubernetes REST 采集、Pod 汇总、中间件 HTTP/TCP 探针和 Bearer Token 鉴权。

### 验证结果

- `gofmt -w *.go`：通过。
- `GOCACHE=/tmp/status-api-gocache go test ./...`：通过。
- `GOCACHE=/tmp/status-api-gocache go vet ./...`：通过。
- 使用真实监听端口的验证受当前沙箱禁止 bind 端口影响，已使用 `httptest` 覆盖健康检查和鉴权行为。

### 下一步

- 在 Linux 主机或测试集群启动服务，验证真实 HTTP 请求、Kubernetes RBAC 和中间件连通性。
- 接入 Node Exporter/Prometheus 或实现独立 Host Collector DaemonSet，补齐节点级主机状态。
- 根据调用方需求增加 scope 权限、分页、缓存和 OpenAPI 文档。

## 本阶段：Python Status API（2026-09-04）

### 当前目标

提供与 Go 版相同接口契约的 Python 实现，方便在没有 Go 运行环境时部署。

### 已确认事实

- 已新增 `python/status-api/`，使用 Python 标准库 `http.server`、`urllib`、`socket` 和 `/proc`，不依赖 FastAPI、Flask 或 psutil。
- 已实现 Bearer Token 鉴权、主机状态、Kubernetes REST 采集、Pod 汇总、中间件 HTTP/HTTPS/TCP 探针。
- 支持通过 `namespace` 查询参数限制 Kubernetes Pod 范围。

### 尚未验证的可能性

- 尚未在真实 Kubernetes 集群和 Linux 节点验证 Python 版本的 RBAC、ServiceAccount CA 和中间件探针。
- 尚未实现 Prometheus/Node Exporter、缓存、JWT/OIDC、多集群和历史数据。

### 已完成

- 新增 `python/status-api/status_api/`、测试和 README。
- 扩充 `go/status-api/README.md`、`python/status-api/README.md` 的运行、Token、接口、配置、RBAC、安全和限制说明，并在根目录 `README.md` 增加两个工程入口。

### 验证结果

- `PYTHONPATH=. python3 -m unittest discover -s tests -v`：2 项测试通过。
- `python3 -m compileall -q status_api`：通过。
- 两份 Status API README 各有 22 个代码围栏，均为成对围栏；`git diff --check`：通过。

### 下一步

- 在目标 Linux/Kubernetes 环境启动 `python3 -m status_api`，验证真实 HTTP、RBAC 和采集数据。
- 根据生产依赖约束决定是否增加 FastAPI/Uvicorn 适配层。

## 本阶段：Status API 配置文件与服务探针（2026-09-04）

### 当前目标

允许 Go 和 Python 版本从独立环境文件读取 Token、Kubernetes 地址、业务服务地址和中间件地址。

### 已确认事实

- Go 和 Python 均自动读取运行目录的 `.env`，也支持 `STATUS_API_ENV_FILE` 指定其他文件。
- 已实现环境变量优先级：进程环境变量覆盖 `.env` 文件中的同名键。
- 新增 `STATUS_SERVICES` 业务服务探针配置和 `/api/v1/services` 接口；`STATUS_MIDDLEWARES` 继续用于中间件探针。
- 新增 Go/Python 各自的 `.env.example`，不包含真实凭据。

### 尚未验证的可能性

- 尚未在真实 Linux/Kubernetes 环境验证 `.env` 文件权限、ServiceAccount、业务服务 DNS 和中间件地址连通性。
- `.env` 解析器只支持简单 `KEY=VALUE`、单/双引号和注释，不支持 Shell 命令替换或变量展开。

### 已完成

- 完成 Go `env.go` 和 Python `dotenv.py` 配置文件加载。
- 汇总接口同时返回 `services` 和 `middlewares` 两类探针结果。
- 更新两个工程 README，说明 `.env`、自定义配置路径和地址配置格式。

### 验证结果

- Go：`go test ./...`、`go vet ./...` 通过。
- Python：`unittest` 2 项测试通过，`compileall` 通过。
- `git diff --check` 通过。

### 下一步

- 复制 `.env.example` 为 `.env`，填入测试环境的服务和中间件地址后做真实 HTTP 验证。
- 生产部署时将 `.env` 替换为 Kubernetes Secret、Vault 或其他凭据管理方式，并设置 `chmod 600`。

## 本阶段：脚本与工具整理（2026-09-03）

### 当前目标

按用途整理 `脚本与工具/` 下的 kubectl 工具和 Shell 命令审计文档，并补充索引。

### 已确认事实

- kubectl 相关文档已归入 `脚本与工具/kubectl/`。
- Bash/Fish 审计、日志轮转和卸载文档已归入 `脚本与工具/shell-audit/`。
- 原有文档内容未改写；迁移后的 6 个已跟踪文件与迁移前内容 SHA-256 一致。
- `脚本与工具/x.md` 的删除状态在本阶段未处理，仍保留为原有工作区变更。

### 已完成

- 新增 `脚本与工具/README.md` 作为分类索引和使用顺序说明。
- 更新根目录 `README.md` 的分类描述与文档路径。

### 验证结果

- 索引中的 8 个相对链接均能解析到现有文件。
- `脚本与工具/` 下 Markdown 代码围栏均成对。
- `git diff --check` 通过，未发现新增尾随空格。

### 下一步

- 若后续将 Markdown 中的脚本提取为独立 `.sh` 文件，需要另行确认命名、执行权限和发布方式；本阶段未做提取或执行验证。
