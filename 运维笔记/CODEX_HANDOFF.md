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

## 本阶段：Kubernetes 总览与资源使用指南（2026-09-07）

### 当前目标

新增一篇按日常使用频率组织的 Kubernetes 中文总览文档，说明组件、资源、使用方式、使用后的效果、验证方法和常见排障路径，并同步容器编排索引。

### 已确认事实

- 新增 `容器编排/Kubernetes-从入门到生产实践：组件资源与常用操作指南.md`，覆盖控制平面、节点组件、CNI/CoreDNS/CSI/入口扩展，以及 Namespace、Pod、Deployment、ReplicaSet、Service、ConfigMap、Secret、Job、CronJob、StatefulSet、DaemonSet、EndpointSlice、Ingress/Gateway API、NetworkPolicy、PV/PVC/StorageClass、RBAC、Pod Security、Quota、HPA、PDB、调度、CRD、Node、Lease、APIService、Webhook 和 etcd。
- 文档按“最常用 → 较少用”排序，包含完整发布示例、真实请求验收要求、Pending/ImagePullBackOff/CrashLoopBackOff/Service 不通的排障顺序和命令速查。
- `README.md` 的“容器编排”索引已加入新文档；原工作区中其他文件的未提交变更未在本阶段处理。

### 基于证据的判断

- 现有仓库已经有组件、资源、Pod 生命周期、Ingress、etcd、Velero 等专题，因此新增文档作为入口和使用顺序说明，并通过专题链接避免重复维护。
- Kubernetes 文档当前仍强调对象 `spec`/`status`、API Server、控制器、Namespace 和组件边界；文档明确区分 API 请求成功、对象状态正常和端到端业务请求成功。

### 尚未验证的可能性

- 未连接或修改任何真实 Kubernetes 集群；文档中的命令、镜像、域名、Controller、CNI、CSI、Metrics Server 和存储类均为通用示例。
- 不同 Kubernetes 版本、发行版和扩展实现可能需要调整字段、注解、入口、网络策略和存储参数。

### 已完成

- 新增总览文档并按组件/资源使用频率组织内容。
- 更新根 `README.md` 的容器编排索引。
- 读取官方 Kubernetes 文档页面，核对组件、对象、Namespace、API 访问和版本边界说明。

### 验证结果

- 新文档 728 行；Markdown 围栏 88 个且成对。
- 12 个 YAML 代码块通过 Ruby YAML 解析。
- 新文档相对链接均解析到现有文件；`git diff --check` 通过。
- 未执行集群部署、镜像拉取、HTTP 访问、RBAC、NetworkPolicy、CSI 或 HPA 的 live 验证。

### 下一步

- 若要落地到具体集群，先记录 Kubernetes 版本、发行版、当前 context、权限、CNI、CSI、入口 Controller、Metrics Server、镜像仓库和目标 Namespace。
- 按文档第 11 节在隔离 Namespace 做最小 Deployment/Service 发布和真实请求验收，再按需扩展存储、权限、网络策略、入口和自动伸缩。

## 本阶段：OpenKruise 文档（2026-09-07）

### 当前目标

整理 OpenKruise 的定位、作用、核心资源、使用方式、Helm 部署、升级回滚、卸载和生产排障说明。

### 已确认事实

- 新文档归入 `容器编排/`，根目录 `README.md` 已增加索引。
- 文档按 OpenKruise 官方 v1.9 文档核对，示例 Helm Chart 版本为 `1.9.0`。
- 官方安装方式支持 Helm 3.5+，Chart 仓库为 `https://openkruise.github.io/charts/`；安装参数包含 `featureGates`、`installation.namespace`、manager 副本与资源、daemon 参数等。
- OpenKruise 通过 CRD、Controller Manager、Admission Webhook 和可选 KruiseDaemon 扩展 Kubernetes；主要资源包含 CloneSet、Advanced StatefulSet、Advanced DaemonSet、SidecarSet、BroadcastJob、UnitedDeployment、ContainerRecreateRequest 和 PodUnavailableBudget。
- 官方说明 OpenKruise 1.5 起不再支持 dockershim，较新版本对 Kubernetes 与 CRI 有兼容约束；自 1.7.3 起 Helm 卸载会检查是否仍存在 Kruise CR。

### 尚未验证的可能性

- 未在真实 Kubernetes 集群执行安装、Webhook 注入、原地升级、CRR、HPA/PUB 或卸载演练。
- 目标集群版本、CRI、镜像仓库、网络策略、GitOps 工具和 FeatureGate 尚未确认；文档命令需按实际 CRD schema 和兼容矩阵调整。

### 已完成

- 新增 `容器编排/OpenKruise-原理作用使用与部署指南.md`，涵盖概念、资源选型、Helm 部署、CloneSet/StatefulSet/DaemonSet/SidecarSet/CRR/PUB 示例、GitOps/HPA 配合、升级回滚、卸载、故障排查和生产清单。
- 更新根目录 `README.md` 的容器编排索引。

### 验证结果

- 新文档 Markdown 代码围栏共 74 个，数量为偶数。
- 新文档内部相对链接未发现缺失目标。
- `git diff --check` 通过（新文件未纳入 diff stat 时仍需以 `git diff --no-index /dev/null <file>` 或暂存后复核）。

### 下一步

- 如需落地，先执行文档第 5 节只读预检，再在测试集群按第 6 节部署并完成第 7 节最小验收。
- 根据目标 Kubernetes/CRI 版本、镜像仓库和 GitOps 归属生成经过评审的 values 与 CR YAML。

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
- 两份 README 已补充集群内运行、VM/物理机外部长期运行、`kubectl proxy` 临时验证和 kubeconfig 暂不支持的差异说明，并移除个人目录路径。
- 两份 README 已增加可复制的长期运行步骤：创建只读 ServiceAccount/RBAC、生成短期 Token、导出 CA、填写 `.env`、验证 `/version` 和调用 Pod 接口；同时保留临时 `kubectl proxy` 流程。

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
- 新增 `KUBERNETES_API_TOKEN` 和 `KUBERNETES_CA_FILE`，支持服务运行在 Kubernetes 集群外时访问指定 API 地址。
- Go/Python Pod 查询现在按 `namespace` 使用 Kubernetes namespaced API 路径；未指定时查询全部 Namespace，并区分 `NAMESPACE_NOT_FOUND`、`PODS_FORBIDDEN` 和一般不可用。
- Go/Python Pod 汇总现在新增 `items`，返回所有已查询 Pod 的 Namespace、名称、Phase、Ready、重启次数和等待原因；`unhealthy` 保留为异常 Pod 子集。
- 修复 Python `collectors.py` 中 `pod_api_path` 插入位置导致 `KubernetesClient.collect` 缩进到错误作用域的问题；该问题会使 `/api/v1/k8s/pods` 触发 `AttributeError` 并让客户端收到 Empty reply。
- 新增 Go/Python 各自的 `.env.example`，不包含真实凭据。

### 尚未验证的可能性

- 尚未在真实 Linux/Kubernetes 环境验证 `.env` 文件权限、ServiceAccount、业务服务 DNS 和中间件地址连通性。
- `.env` 解析器只支持简单 `KEY=VALUE`、单/双引号和注释，不支持 Shell 命令替换或变量展开。
- 尚未支持从 `~/.kube/config` 读取客户端证书；如果 kubectl 使用证书认证，需要后续增加客户端证书配置。

### 已完成

- 完成 Go `env.go` 和 Python `dotenv.py` 配置文件加载。
- 汇总接口同时返回 `services` 和 `middlewares` 两类探针结果。
- 更新两个工程 README，说明 `.env`、自定义配置路径和地址配置格式。

### 验证结果

- Go：`go test ./...`、`go vet ./...` 通过。
- Python：`py_compile`、`unittest` 3 项测试通过，`compileall` 通过。
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

## 本阶段：top 命令指标与性能排障文档（2026-09-07）

### 当前目标

编写 `top` 命令常见指标、阅读方法和主机性能初步排障 Runbook，并补充分类索引。

### 已确认事实

- 文档归入 `脚本与工具/`，文件为 `脚本与工具/top-命令指标详解与性能排障指南.md`。
- 内容覆盖 Linux `procps-ng` 常见摘要行（`load average`、Tasks、CPU、Mem、Swap）、进程列（`PID`、`PR`、`NI`、`VIRT`、`RES`、`SHR`、`S`、`%CPU`、`%MEM`、`TIME+`、`COMMAND`）、线程视图、容器/Kubernetes 差异及 CPU/I/O/内存排障场景。
- 已在 `脚本与工具/README.md` 和根目录 `README.md` 增加入口；同时说明 macOS `top` 与 Linux 版本的参数和列名差异。

### 尚未验证的可能性

- 命令示例未在目标 Linux 主机、容器或 Kubernetes 集群现场执行；`top -o`、`ps --sort` 等参数需按发行版实现确认。
- 文档中的阈值是排障经验起点，不是目标环境的正式告警规则。

### 已完成

- 新增 `top` 指标详解与性能排障文档，包含可复制的只读命令集和记录模板。
- 更新脚本工具索引和根目录索引。

### 验证结果

- 新文档共 484 行，Markdown 代码围栏 54 个，数量为偶数。
- 新文档、脚本工具 README 和根 README 的新增链接目标均存在。
- `git diff --check` 通过；新文件使用 `git diff --no-index --check /dev/null <file>` 检查，无空白错误。

### 下一步

- 如需生产落地，先在目标主机按文档第 9 节执行只读采样，再结合 `vmstat`、`iostat`、`pidstat`、应用日志和业务指标确认根因。
- 若需要监控告警，应根据 CPU 核数、业务延迟、容器 requests/limits 和历史基线单独制定阈值。
