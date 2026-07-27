# GitLab CI + ArgoCD 全链路部署流程 (Deploy Recorder)

> **目标**: 将 GitLab CI Pipeline 的每个阶段操作 + ArgoCD 的同步/健康检查事件，全部持久化到数据库，形成完整的部署追溯链。

---

## 一、架构概览

```
┌──────────────┐                ┌──────────────────────┐
│  Developer   │                │   Deploy Recorder    │
│  git push    │                │   (FastAPI + PG)     │
└──────┬───────┘                │                      │
       │                        │  ┌─ pipelines ──────┐│
       ▼                        │  │  stages / builds ││
┌──────────────┐   API 上报     │  ├─ deployments ────┤│
│  GitLab CI   │───────────────▶│  │  syncs / resource││
│  Pipeline    │                │  ├─ audit_logs ─────┤│
└──────┬───────┘                │  └─ projects ───────┘│
       │                        └──────────┬───────────┘
       │ git push                          │ Webhook
       ▼                                   │
┌──────────────┐                ┌──────────▼───────────┐
│  GitOps Repo │                │      ArgoCD          │
│  (k8s.yaml)  │◀──────────────│   Notifications      │
└──────────────┘   sync         └──────────────────────┘
       │
       ▼
┌──────────────┐
│  Kubernetes  │
│  Cluster     │
└──────────────┘
```

**数据流**: Developer `git push` → GitLab CI 构建镜像 → 更新 GitOps 仓库 → ArgoCD 自动同步 → 同步结果 Webhook 回调 Deploy Recorder → 全链路入库。

---

## 二、数据库设计

> 文件: `01-schema.sql`

### 核心表结构

```
projects ──────┐
               ├── pipelines ────── stages
               │       └────── builds
               │
               └── deployments ──── argocd_syncs ──── argocd_resources
                       │
                       └── audit_logs
```

### 表说明

| 表名 | 用途 | 写入方 |
|------|------|--------|
| `projects` | 项目注册 | 手动 / GitLab CI |
| `pipelines` | Pipeline 生命周期 | GitLab CI |
| `pipeline_stages` | 每个 Stage 详情 | GitLab CI |
| `builds` | Docker 镜像构建记录 | GitLab CI |
| `deployments` | 部署记录 (核心) | GitLab CI + ArgoCD |
| `argocd_syncs` | ArgoCD 同步历史 | ArgoCD Webhook |
| `argocd_resources` | 每个 K8s 资源状态 | ArgoCD Webhook |
| `audit_logs` | 操作审计日志 | 所有来源 |
| `env_variables` | 加密环境变量 | 手动 |

### 查询示例

```sql
-- 查看某次部署的完整链路
SELECT 
    d.id AS deploy_id,
    d.environment,
    d.image_tag,
    d.status AS deploy_status,
    pl.ref AS branch,
    pl.commit_sha,
    b.image_sha256,
    s.phase AS sync_phase,
    s.message AS sync_message
FROM deployments d
LEFT JOIN pipelines pl ON pl.id = d.pipeline_id
LEFT JOIN builds b ON b.id = d.build_id
LEFT JOIN argocd_syncs s ON s.deployment_id = d.id
WHERE d.id = 123;

-- 查看最近 30 天 Pipeline 成功率
SELECT * FROM v_pipeline_stats;

-- 查看某环境的部署历史
SELECT * FROM v_recent_deployments
WHERE environment = 'production';
```

---

## 三、GitLab CI Pipeline 配置

> 文件: `02-gitlab-ci.yml`

### Pipeline 阶段

```
validate → build → deploy-staging → approve → deploy-prod
```

### 每阶段自动上报

| 阶段 | 触发时机 | 上报内容 |
|------|---------|---------|
| `validate` | Pipeline 开始 | `pipeline_start` + `stage` |
| `build` | 构建开始/结束 | `build_start` + `build_success` / `build_failed` |
| `deploy-staging` | 部署开始/同步/健康 | `deploy_start` → `argocd_sync` → `deploy_success` |
| `approve` | 人工审批 | `manual_approve_prod` |
| `deploy-prod` | 生产部署 | 同 staging + 超时自动回滚 |

### 关键环境变量

在 GitLab → Settings → CI/CD → Variables 中配置:

```bash
RECORDER_API_URL=https://deploy-recorder.internal/api/v1
RECORDER_API_KEY=<your-api-key>
PROJECT_DB_ID=<project-id-in-recorder>
ARGOCD_SERVER=<argocd-server-url>
ARGOCD_TOKEN=<argocd-api-token>
HARBOR_USER=<registry-username>
HARBOR_PASSWORD=<registry-password>
```

---

## 四、ArgoCD 配置

> 文件: `03-argocd-applications.yaml`

### 两种模式

**模式 1: ApplicationSet (推荐)**

```yaml
# 自动从 GitOps 仓库目录结构发现环境
# apps/<app>/overlays/staging  →  <app>-staging
# apps/<app>/overlays/production → <app>-production
```

**模式 2: 独立 Application**

```yaml
# 每个环境单独定义 Application CR
# 适合需要不同同步策略的场景
```

### ArgoCD Notifications 集成

通过 `argocd-notifications-cm` ConfigMap 配置 Webhook:

- `on-sync-status-unknown` → 同步完成时上报
- `on-healthy` → 健康检查通过时上报
- `on-degraded` → 部署失败时上报

ArgoCD 侧的 Application 必须带标注:

```yaml
annotations:
  deploy-recorder.example.com/enabled: "true"
  deploy-recorder.example.com/project-id: "123"
```

---

## 五、Deploy Recorder 服务部署

### 快速启动

```bash
# 1. 进入目录
cd 运维笔记/gitlab-ci-argocd

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，设置 DB_PASSWORD 和 RECORDER_API_KEY

# 3. 启动
docker compose up -d

# 4. 验证
curl http://localhost:8000/health
```

### API 端点

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/v1/projects` | 注册项目 |
| `POST` | `/api/v1/pipelines` | 记录 Pipeline |
| `PATCH` | `/api/v1/pipelines/{id}` | 更新 Pipeline 状态 |
| `POST` | `/api/v1/stages` | 记录 Stage |
| `POST` | `/api/v1/builds` | 记录构建 |
| `PATCH` | `/api/v1/builds/{id}` | 更新构建状态 |
| `POST` | `/api/v1/deployments` | 记录部署 |
| `PATCH` | `/api/v1/deployments/{id}` | 更新部署状态 |
| `POST` | `/api/v1/deployments/rollback` | 记录回滚 |
| `GET` | `/api/v1/deployments/history` | 部署历史 |
| `GET` | `/api/v1/deployments/latest-healthy` | 最近健康部署 |
| `POST` | `/api/v1/argocd/webhook` | ArgoCD Webhook |
| `POST` | `/api/v1/audit` | 记录审计日志 |
| `GET` | `/api/v1/audit` | 查询审计日志 |
| `GET` | `/api/v1/dashboard` | 运维概览 |

### 认证

所有 API 需要 `X-API-Key` Header，值通过环境变量 `RECORDER_API_KEY` 配置。

---

## 六、完整部署流程

### 1. 初始化

```bash
# 注册项目
curl -X POST http://deploy-recorder:8000/api/v1/projects \
  -H "X-API-Key: ${RECO...Y}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "my-app",
    "gitlab_project_id": 42,
    "gitlab_url": "https://gitlab.example.com/team/my-app",
    "argocd_app": "my-app",
    "namespace": "default"
  }'
# → 返回 {"id": 1, "name": "my-app"}

# 记录 PROJECT_DB_ID=1，配置到 GitLab CI Variables
```

### 2. 日常开发流程

```
Developer git push
  │
  ├─ GitLab CI 自动触发
  │   ├─ lint → RECORDER: pipeline_start
  │   ├─ test → RECORDER: stage (validate)
  │   ├─ build → RECORDER: build_start → build_success
  │   ├─ deploy-staging → RECORDER: deploy_start → deploy_success
  │   └─ (等待人工审批)
  │
  ├─ 人工点击 approve-prod
  │   └─ RECORDER: manual_approve_prod
  │
  └─ deploy-prod
      ├─ GitLab CI → 更新 GitOps 仓库
      ├─ ArgoCD → 自动同步
      │   └─ Webhook → RECORDER: argocd_webhook (sync+health)
      └─ RECORDER: deploy_success_prod
```

### 3. 回滚流程

```bash
# 手动触发 GitLab CI 的 rollback-prod Job
# 或直接调用 API:
curl -X POST http://deploy-recorder:8000/api/v1/deployments/rollback \
  -H "X-API-Key: ${RECO...Y}" \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_id": 42,
    "rollback_to_revision": "abc1234",
    "reason": "P99 latency spike after deployment"
  }'
```

### 4. 运维查询

```bash
# 查看项目最近 10 次部署
curl "http://deploy-recorder:8000/api/v1/deployments/history?project_id=1&limit=10" \
  -H "X-API-Key: ${RECO...Y}"

# 查看审计日志
curl "http://deploy-recorder:8000/api/v1/audit?project_id=1&action=rollback" \
  -H "X-API-Key: ${RECO...Y}"

# 运维概览
curl "http://deploy-recorder:8000/api/v1/dashboard" \
  -H "X-API-Key: ${RECO...Y}"
```

---

## 七、文件清单

| 文件 | 用途 |
|------|------|
| `01-schema.sql` | 数据库 Schema + 视图 |
| `02-gitlab-ci.yml` | GitLab CI Pipeline 配置 |
| `03-argocd-applications.yaml` | ArgoCD Application/ApplicationSet + Notifications |
| `04-deploy-recorder.py` | Deploy Recorder 服务 (FastAPI) |
| `05-docker-compose.yml` | Docker Compose 部署配置 |
| `06-Dockerfile.recorder` | Deploy Recorder 容器镜像 |
| `07-requirements.txt` | Python 依赖 |
| `README.md` | 本文档 |

---

## 八、扩展建议

1. **Grafana 可视化**: 通过 PostgreSQL 数据源直接制作 Dashboard
2. **告警集成**: 部署失败/超时 → 钉钉/飞书/企业微信通知
3. **变更审批流**: 集成 GitLab MR Approval + 数据库记录
4. **多集群支持**: `deployments` 表增加 `cluster` 字段
5. **秘钥管理**: 使用 Vault 替代 `env_variables` 表
6. **部署策略**: 支持 Canary 部署的渐进式流量切换记录
7. **SLA 统计**: 基于 `deployments` 表计算变更失败率、平均恢复时间