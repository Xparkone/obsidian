-- ============================================================
-- Deploy Recorder 数据库 Schema
-- 全链路追踪：GitLab CI → ArgoCD → Kubernetes
-- 数据库: PostgreSQL (推荐) 或 MySQL 8.0+
-- ============================================================

-- 1. 项目表
CREATE TABLE IF NOT EXISTS projects (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(255) NOT NULL,                         -- 项目名
    gitlab_project_id INT NOT NULL UNIQUE,                         -- GitLab 项目 ID
    gitlab_url      VARCHAR(512) NOT NULL,                         -- GitLab 仓库地址
    argocd_app      VARCHAR(255),                                  -- 关联的 ArgoCD Application 名
    namespace       VARCHAR(128) NOT NULL DEFAULT 'default',       -- K8s 命名空间
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Pipeline 记录表
CREATE TABLE IF NOT EXISTS pipelines (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT NOT NULL REFERENCES projects(id),
    gitlab_pipeline_id BIGINT NOT NULL,                            -- GitLab Pipeline ID
    gitlab_pipeline_url VARCHAR(512),                              -- GitLab Pipeline 链接
    ref             VARCHAR(255) NOT NULL,                         -- 分支或 tag
    commit_sha      VARCHAR(64) NOT NULL,                          -- 触发 commit
    commit_message  TEXT,                                          -- 提交信息
    triggered_by    VARCHAR(128),                                  -- 触发人
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',        -- pending/running/success/failed/canceled
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_seconds INT,                                          -- 耗时（秒）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_pipelines_project ON pipelines(project_id);
CREATE INDEX idx_pipelines_status  ON pipelines(status);
CREATE INDEX idx_pipelines_ref     ON pipelines(ref);

-- 3. Pipeline Stage 记录表（每个 Stage 的详细操作）
CREATE TABLE IF NOT EXISTS pipeline_stages (
    id              BIGSERIAL PRIMARY KEY,
    pipeline_id     BIGINT NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    stage_name      VARCHAR(128) NOT NULL,                         -- 阶段名: build/test/deploy
    job_name        VARCHAR(255) NOT NULL,                         -- Job 名
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',        -- pending/running/success/failed
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_seconds INT,
    log_snippet     TEXT,                                          -- 失败时保留部分日志
    extra           JSONB DEFAULT '{}',                            -- 扩展字段
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_stages_pipeline ON pipeline_stages(pipeline_id);

-- 4. Docker 镜像构建记录
CREATE TABLE IF NOT EXISTS builds (
    id              BIGSERIAL PRIMARY KEY,
    pipeline_id     BIGINT NOT NULL REFERENCES pipelines(id),
    stage_id        BIGINT REFERENCES pipeline_stages(id),
    image_name      VARCHAR(512) NOT NULL,                         -- 镜像名 (含 registry)
    image_tag       VARCHAR(128) NOT NULL,                         -- 镜像 tag
    image_sha256    VARCHAR(128),                                  -- 镜像 digest
    dockerfile_path VARCHAR(512) DEFAULT 'Dockerfile',             -- Dockerfile 路径
    build_args      JSONB DEFAULT '{}',                            -- 构建参数
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_seconds INT,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_builds_pipeline ON builds(pipeline_id);

-- 5. 部署记录表（核心表）
CREATE TABLE IF NOT EXISTS deployments (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT NOT NULL REFERENCES projects(id),
    pipeline_id     BIGINT REFERENCES pipelines(id),
    build_id        BIGINT REFERENCES builds(id),
    environment     VARCHAR(64) NOT NULL,                          -- dev/staging/prod
    strategy        VARCHAR(32) NOT NULL DEFAULT 'rolling',        -- rolling/blue-green/canary
    image_name      VARCHAR(512) NOT NULL,
    image_tag       VARCHAR(128) NOT NULL,
    git_commit_sha  VARCHAR(64),
    git_ref         VARCHAR(255),
    manifest_path   VARCHAR(512),                                  -- K8s 清单路径
    status          VARCHAR(32) NOT NULL DEFAULT 'pending',        -- pending/syncing/healthy/degraded/failed/rolled_back
    deployed_at     TIMESTAMPTZ,
    synced_at       TIMESTAMPTZ,                                   -- ArgoCD 同步完成时间
    healthy_at      TIMESTAMPTZ,                                   -- 健康检查通过时间
    rollback_from   BIGINT REFERENCES deployments(id),             -- 如果是回滚，记录来源
    extra           JSONB DEFAULT '{}',                            -- 扩展字段
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_deployments_project     ON deployments(project_id);
CREATE INDEX idx_deployments_pipeline    ON deployments(pipeline_id);
CREATE INDEX idx_deployments_environment ON deployments(environment);
CREATE INDEX idx_deployments_status      ON deployments(status);
CREATE INDEX idx_deployments_created     ON deployments(created_at DESC);

-- 6. ArgoCD 同步历史
CREATE TABLE IF NOT EXISTS argocd_syncs (
    id              BIGSERIAL PRIMARY KEY,
    deployment_id   BIGINT NOT NULL REFERENCES deployments(id),
    argocd_app      VARCHAR(255) NOT NULL,                         -- ArgoCD Application 名
    sync_operation_id VARCHAR(255),                                -- ArgoCD 同步操作 ID
    revision        VARCHAR(128) NOT NULL,                         -- 同步的 revision (commit SHA)
    phase           VARCHAR(64) NOT NULL,                          -- Sync/Running/Succeeded/Failed/Error
    message         TEXT,
    sync_started_at TIMESTAMPTZ,
    sync_finished_at TIMESTAMPTZ,
    duration_seconds INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_syncs_deployment ON argocd_syncs(deployment_id);

-- 7. ArgoCD 资源状态（每个 K8s 资源）
CREATE TABLE IF NOT EXISTS argocd_resources (
    id              BIGSERIAL PRIMARY KEY,
    sync_id         BIGINT NOT NULL REFERENCES argocd_syncs(id) ON DELETE CASCADE,
    resource_kind   VARCHAR(64) NOT NULL,                          -- Deployment/Service/ConfigMap/...
    resource_name   VARCHAR(255) NOT NULL,
    resource_namespace VARCHAR(128) NOT NULL,
    status          VARCHAR(32) NOT NULL,                          -- Synced/OutOfSync/Progressing/Healthy/Degraded
    health_status   VARCHAR(32),                                   -- Healthy/Progressing/Degraded/Missing/Unknown
    message         TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_resources_sync ON argocd_resources(sync_id);

-- 8. 操作审计日志（所有操作）
CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT REFERENCES projects(id),
    deployment_id   BIGINT REFERENCES deployments(id),
    pipeline_id     BIGINT REFERENCES pipelines(id),
    action          VARCHAR(64) NOT NULL,                          -- pipeline_start/build_push/argocd_sync/deploy_success/rollback/manual_approve
    actor           VARCHAR(128),                                  -- 操作人
    source          VARCHAR(32) NOT NULL DEFAULT 'gitlab_ci',      -- gitlab_ci/argocd/manual/system
    details         JSONB DEFAULT '{}',                            -- 操作详情
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_project    ON audit_logs(project_id);
CREATE INDEX idx_audit_deployment ON audit_logs(deployment_id);
CREATE INDEX idx_audit_created    ON audit_logs(created_at DESC);

-- 9. 环境变量记录（加密存储敏感信息）
CREATE TABLE IF NOT EXISTS env_variables (
    id              BIGSERIAL PRIMARY KEY,
    project_id      BIGINT NOT NULL REFERENCES projects(id),
    environment     VARCHAR(64) NOT NULL,
    key_name        VARCHAR(128) NOT NULL,
    value_encrypted TEXT NOT NULL,                                 -- AES-256-GCM 加密后的值
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, environment, key_name)
);

-- ============================================================
-- 查询视图（方便运维查询）
-- ============================================================

-- 最近部署概览
CREATE OR REPLACE VIEW v_recent_deployments AS
SELECT
    d.id,
    p.name AS project_name,
    d.environment,
    d.image_tag,
    d.status,
    d.deployed_at,
    pl.gitlab_pipeline_url,
    d.extra->>'version' AS version
FROM deployments d
JOIN projects p ON p.id = d.project_id
LEFT JOIN pipelines pl ON pl.id = d.pipeline_id
ORDER BY d.deployed_at DESC
LIMIT 100;

-- Pipeline 成功率统计
CREATE OR REPLACE VIEW v_pipeline_stats AS
SELECT
    p.name AS project_name,
    COUNT(*) AS total,
    SUM(CASE WHEN pl.status = 'success' THEN 1 ELSE 0 END) AS success_count,
    ROUND(100.0 * SUM(CASE WHEN pl.status = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) AS success_rate,
    AVG(pl.duration_seconds) AS avg_duration_seconds
FROM pipelines pl
JOIN projects p ON p.id = pl.project_id
WHERE pl.created_at > NOW() - INTERVAL '30 days'
GROUP BY p.name;