# ============================================================
# Deploy Recorder — 部署全链路记录服务
# 
# 功能:
#   - 接收 GitLab CI Pipeline 的各个阶段操作
#   - 接收 ArgoCD 同步/健康检查事件
#   - 所有操作持久化到 PostgreSQL
#   - 提供查询 API 用于运维审计和回溯
#
# 技术栈: Python 3.11+ / FastAPI / SQLAlchemy / PostgreSQL
# ============================================================

import os
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import FastAPI, HTTPException, Depends, Header, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import (
    create_engine, Column, BigInteger, Integer, String, Text,
    DateTime, ForeignKey, Index, Boolean, func, text
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import (
    declarative_base, sessionmaker, Session, relationship
)
from sqlalchemy.sql import case
from contextlib import asynccontextmanager

# ============================================================
# Configuration
# ============================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://recorder:password@localhost:5432/deploy_recorder"
)
API_KEY = os.getenv("API_KEY", "your-secret-api-key")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("deploy-recorder")

# ============================================================
# Database Setup
# ============================================================

engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


# ============================================================
# SQLAlchemy Models
# ============================================================

class Project(Base):
    __tablename__ = "projects"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    gitlab_project_id = Column(Integer, nullable=False, unique=True)
    gitlab_url = Column(String(512), nullable=False)
    argocd_app = Column(String(255))
    namespace = Column(String(128), nullable=False, default="default")
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    pipelines = relationship("Pipeline", back_populates="project")
    deployments = relationship("Deployment", back_populates="project")


class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, ForeignKey("projects.id"), nullable=False)
    gitlab_pipeline_id = Column(BigInteger, nullable=False)
    gitlab_pipeline_url = Column(String(512))
    ref = Column(String(255), nullable=False)
    commit_sha = Column(String(64), nullable=False)
    commit_message = Column(Text)
    triggered_by = Column(String(128))
    status = Column(String(32), nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=func.now())

    project = relationship("Project", back_populates="pipelines")
    stages = relationship("PipelineStage", back_populates="pipeline", cascade="all, delete-orphan")
    builds = relationship("Build", back_populates="pipeline")
    deployments = relationship("Deployment", back_populates="pipeline")


class PipelineStage(Base):
    __tablename__ = "pipeline_stages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_id = Column(BigInteger, ForeignKey("pipelines.id"), nullable=False)
    stage_name = Column(String(128), nullable=False)
    job_name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Integer)
    log_snippet = Column(Text)
    extra = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=func.now())

    pipeline = relationship("Pipeline", back_populates="stages")


class Build(Base):
    __tablename__ = "builds"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pipeline_id = Column(BigInteger, ForeignKey("pipelines.id"), nullable=False)
    stage_id = Column(BigInteger, ForeignKey("pipeline_stages.id"))
    image_name = Column(String(512), nullable=False)
    image_tag = Column(String(128), nullable=False)
    image_sha256 = Column(String(128))
    dockerfile_path = Column(String(512), default="Dockerfile")
    build_args = Column(JSONB, default=dict)
    status = Column(String(32), nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Integer)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), default=func.now())

    pipeline = relationship("Pipeline", back_populates="builds")


class Deployment(Base):
    __tablename__ = "deployments"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, ForeignKey("projects.id"), nullable=False)
    pipeline_id = Column(BigInteger, ForeignKey("pipelines.id"))
    build_id = Column(BigInteger, ForeignKey("builds.id"))
    environment = Column(String(64), nullable=False)
    strategy = Column(String(32), nullable=False, default="rolling")
    image_name = Column(String(512), nullable=False)
    image_tag = Column(String(128), nullable=False)
    git_commit_sha = Column(String(64))
    git_ref = Column(String(255))
    manifest_path = Column(String(512))
    status = Column(String(32), nullable=False, default="pending")
    deployed_at = Column(DateTime(timezone=True))
    synced_at = Column(DateTime(timezone=True))
    healthy_at = Column(DateTime(timezone=True))
    rollback_from = Column(BigInteger, ForeignKey("deployments.id"))
    extra = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=func.now())

    project = relationship("Project", back_populates="deployments")
    pipeline = relationship("Pipeline", back_populates="deployments")


class ArgoCDSync(Base):
    __tablename__ = "argocd_syncs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    deployment_id = Column(BigInteger, ForeignKey("deployments.id"), nullable=False)
    argocd_app = Column(String(255), nullable=False)
    sync_operation_id = Column(String(255))
    revision = Column(String(128), nullable=False)
    phase = Column(String(64), nullable=False)
    message = Column(Text)
    sync_started_at = Column(DateTime(timezone=True))
    sync_finished_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=func.now())


class ArgoCDResource(Base):
    __tablename__ = "argocd_resources"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sync_id = Column(BigInteger, ForeignKey("argocd_syncs.id"), nullable=False)
    resource_kind = Column(String(64), nullable=False)
    resource_name = Column(String(255), nullable=False)
    resource_namespace = Column(String(128), nullable=False)
    status = Column(String(32), nullable=False)
    health_status = Column(String(32))
    message = Column(Text)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    project_id = Column(BigInteger, ForeignKey("projects.id"))
    deployment_id = Column(BigInteger, ForeignKey("deployments.id"))
    pipeline_id = Column(BigInteger, ForeignKey("pipelines.id"))
    action = Column(String(64), nullable=False)
    actor = Column(String(128))
    source = Column(String(32), nullable=False, default="gitlab_ci")
    details = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=func.now())


# ============================================================
# FastAPI App
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时创建表"""
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
    yield

app = FastAPI(
    title="Deploy Recorder",
    description="GitLab CI + ArgoCD 全链路部署记录服务",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Dependencies
# ============================================================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_api_key(x_api_key: str = Header(..., alias="X-API-Key")):
    """验证 API Key"""
    if not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key


# ============================================================
# Pydantic Schemas (Request/Response)
# ============================================================

class PipelineCreate(BaseModel):
    project_id: int
    gitlab_pipeline_id: int
    gitlab_pipeline_url: Optional[str] = None
    ref: str
    commit_sha: str
    commit_message: Optional[str] = None
    triggered_by: Optional[str] = None
    status: str = "pending"

class PipelineUpdate(BaseModel):
    status: Optional[str] = None
    finished_at: Optional[str] = None
    duration_seconds: Optional[int] = None

class StageCreate(BaseModel):
    pipeline_id: int
    stage_name: str
    job_name: str
    status: str = "pending"
    log_snippet: Optional[str] = None
    extra: Dict[str, Any] = {}

class BuildCreate(BaseModel):
    pipeline_id: int
    stage_id: Optional[int] = None
    image_name: str
    image_tag: str
    dockerfile_path: str = "Dockerfile"
    build_args: Dict[str, Any] = {}
    status: str = "pending"

class BuildUpdate(BaseModel):
    status: Optional[str] = None
    image_sha256: Optional[str] = None
    error_message: Optional[str] = None

class DeploymentCreate(BaseModel):
    project_id: int
    pipeline_id: Optional[int] = None
    build_id: Optional[int] = None
    environment: str
    strategy: str = "rolling"
    image_name: str
    image_tag: str
    git_commit_sha: Optional[str] = None
    git_ref: Optional[str] = None
    manifest_path: Optional[str] = None
    status: str = "pending"

class DeploymentUpdate(BaseModel):
    status: Optional[str] = None
    synced_at: Optional[str] = None
    healthy_at: Optional[str] = None

class RollbackRequest(BaseModel):
    deployment_id: int
    rollback_to_revision: str
    reason: Optional[str] = None

class AuditLogCreate(BaseModel):
    project_id: Optional[int] = None
    deployment_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    action: str
    actor: Optional[str] = None
    source: str = "gitlab_ci"
    details: Dict[str, Any] = {}

class ArgoCDWebhookPayload(BaseModel):
    """ArgoCD Notifications Webhook 接收的荷载"""
    event: Optional[str] = None
    app_name: Optional[str] = None
    project_id: Optional[int] = None
    sync_status: Optional[str] = None
    health_status: Optional[str] = None
    revision: Optional[str] = None
    operation_state_phase: Optional[str] = None
    operation_state_message: Optional[str] = None
    timestamp: Optional[str] = None

class ProjectCreate(BaseModel):
    name: str
    gitlab_project_id: int
    gitlab_url: str
    argocd_app: Optional[str] = None
    namespace: str = "default"


# ============================================================
# API Routes — Projects
# ============================================================

@app.post("/api/v1/projects", status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """注册项目"""
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info(f"Project created: {project.name} (id={project.id})")
    return {"id": project.id, "name": project.name}


@app.get("/api/v1/projects")
def list_projects(
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    projects = db.query(Project).all()
    return [
        {"id": p.id, "name": p.name, "namespace": p.namespace}
        for p in projects
    ]


# ============================================================
# API Routes — Pipelines
# ============================================================

@app.post("/api/v1/pipelines", status_code=201)
def create_pipeline(
    payload: PipelineCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """记录 Pipeline 开始"""
    pipeline = Pipeline(
        **payload.model_dump(),
        started_at=datetime.now(timezone.utc)
    )
    db.add(pipeline)
    db.flush()

    # 同时记录审计日志
    audit = AuditLog(
        project_id=payload.project_id,
        pipeline_id=pipeline.id,
        action="pipeline_start",
        actor=payload.triggered_by,
        source="gitlab_ci",
        details={"ref": payload.ref, "commit": payload.commit_sha}
    )
    db.add(audit)
    db.commit()
    db.refresh(pipeline)

    logger.info(f"Pipeline recorded: {pipeline.id} (GitLab: {payload.gitlab_pipeline_id})")
    return {"id": pipeline.id, "status": pipeline.status}


@app.patch("/api/v1/pipelines/{pipeline_id}")
def update_pipeline(
    pipeline_id: int,
    payload: PipelineUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """更新 Pipeline 状态"""
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    update_data = payload.model_dump(exclude_none=True)
    if "finished_at" in update_data and update_data["finished_at"]:
        update_data["finished_at"] = datetime.fromisoformat(
            update_data["finished_at"].replace("Z", "+00:00")
        )

    for key, value in update_data.items():
        setattr(pipeline, key, value)

    # 审计
    audit = AuditLog(
        project_id=pipeline.project_id,
        pipeline_id=pipeline.id,
        action=f"pipeline_{payload.status or 'updated'}",
        source="gitlab_ci",
        details={"status": payload.status}
    )
    db.add(audit)
    db.commit()

    return {"id": pipeline.id, "status": pipeline.status}


@app.get("/api/v1/pipelines/{pipeline_id}")
def get_pipeline(
    pipeline_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """获取 Pipeline 详情"""
    pipeline = db.query(Pipeline).filter(Pipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    stages = db.query(PipelineStage).filter(
        PipelineStage.pipeline_id == pipeline_id
    ).all()

    return {
        "id": pipeline.id,
        "ref": pipeline.ref,
        "commit_sha": pipeline.commit_sha,
        "status": pipeline.status,
        "started_at": pipeline.started_at.isoformat() if pipeline.started_at else None,
        "finished_at": pipeline.finished_at.isoformat() if pipeline.finished_at else None,
        "duration_seconds": pipeline.duration_seconds,
        "stages": [
            {
                "name": s.stage_name,
                "job": s.job_name,
                "status": s.status,
                "duration_seconds": s.duration_seconds
            }
            for s in stages
        ]
    }


# ============================================================
# API Routes — Stages
# ============================================================

@app.post("/api/v1/stages", status_code=201)
def create_stage(
    payload: StageCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """记录 Pipeline Stage"""
    stage = PipelineStage(
        **payload.model_dump(),
        started_at=datetime.now(timezone.utc)
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return {"id": stage.id, "status": stage.status}


# ============================================================
# API Routes — Builds
# ============================================================

@app.post("/api/v1/builds", status_code=201)
def create_build(
    payload: BuildCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """记录镜像构建"""
    build = Build(
        **payload.model_dump(),
        started_at=datetime.now(timezone.utc)
    )
    db.add(build)
    db.commit()
    db.refresh(build)

    # 审计
    pipeline = db.query(Pipeline).filter(Pipeline.id == payload.pipeline_id).first()
    audit = AuditLog(
        project_id=pipeline.project_id if pipeline else None,
        pipeline_id=payload.pipeline_id,
        action="build_start",
        source="gitlab_ci",
        details={"image": payload.image_name, "tag": payload.image_tag}
    )
    db.add(audit)
    db.commit()

    logger.info(f"Build recorded: {build.id} ({payload.image_name}:{payload.image_tag})")
    return {"id": build.id, "status": build.status}


@app.patch("/api/v1/builds/{build_id}")
def update_build(
    build_id: int,
    payload: BuildUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """更新构建状态"""
    build = db.query(Build).filter(Build.id == build_id).first()
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    if payload.status:
        build.status = payload.status
        build.finished_at = datetime.now(timezone.utc)
        if build.started_at:
            build.duration_seconds = int(
                (build.finished_at - build.started_at).total_seconds()
            )
    if payload.image_sha256:
        build.image_sha256 = payload.image_sha256
    if payload.error_message:
        build.error_message = payload.error_message

    db.commit()
    return {"id": build.id, "status": build.status}


# ============================================================
# API Routes — Deployments
# ============================================================

@app.post("/api/v1/deployments", status_code=201)
def create_deployment(
    payload: DeploymentCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """记录部署开始"""
    deployment = Deployment(
        **payload.model_dump(),
        deployed_at=datetime.now(timezone.utc)
    )
    db.add(deployment)
    db.flush()

    # 审计
    audit = AuditLog(
        project_id=payload.project_id,
        deployment_id=deployment.id,
        pipeline_id=payload.pipeline_id,
        action="deploy_start",
        source="gitlab_ci",
        details={
            "environment": payload.environment,
            "image": payload.image_name,
            "tag": payload.image_tag
        }
    )
    db.add(audit)
    db.commit()
    db.refresh(deployment)

    logger.info(f"Deployment recorded: {deployment.id} ({payload.environment})")
    return {"id": deployment.id, "status": deployment.status}


@app.patch("/api/v1/deployments/{deployment_id}")
def update_deployment(
    deployment_id: int,
    payload: DeploymentUpdate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """更新部署状态"""
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    now = datetime.now(timezone.utc)
    if payload.status:
        deployment.status = payload.status
    if payload.synced_at:
        deployment.synced_at = datetime.fromisoformat(
            payload.synced_at.replace("Z", "+00:00")
        )
    if payload.healthy_at:
        deployment.healthy_at = datetime.fromisoformat(
            payload.healthy_at.replace("Z", "+00:00")
        )
    if payload.status == "healthy":
        deployment.healthy_at = now

    db.commit()
    return {"id": deployment.id, "status": deployment.status}


@app.post("/api/v1/deployments/rollback")
def rollback_deployment(
    payload: RollbackRequest,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """记录回滚"""
    deployment = db.query(Deployment).filter(
        Deployment.id == payload.deployment_id
    ).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    # 创建回滚部署记录
    rollback = Deployment(
        project_id=deployment.project_id,
        pipeline_id=deployment.pipeline_id,
        environment=deployment.environment,
        strategy="rollback",
        image_name=deployment.image_name,
        image_tag=payload.rollback_to_revision,
        git_commit_sha=deployment.git_commit_sha,
        git_ref=deployment.git_ref,
        status="rolled_back",
        rollback_from=deployment.id,
        deployed_at=datetime.now(timezone.utc),
        extra={"reason": payload.reason}
    )
    db.add(rollback)

    # 标记原部署为已回滚
    deployment.status = "rolled_back"

    audit = AuditLog(
        project_id=deployment.project_id,
        deployment_id=rollback.id,
        action="rollback",
        source="manual",
        details={
            "from_deployment_id": payload.deployment_id,
            "rollback_to": payload.rollback_to_revision,
            "reason": payload.reason
        }
    )
    db.add(audit)
    db.commit()
    db.refresh(rollback)

    logger.warning(f"Rollback recorded: {rollback.id} -> {payload.rollback_to_revision}")
    return {"id": rollback.id, "status": "rolled_back"}


@app.get("/api/v1/deployments/latest-healthy")
def get_latest_healthy(
    project_id: int = Query(...),
    environment: str = Query(...),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """获取最近一次健康部署（用于回滚）"""
    deployment = (
        db.query(Deployment)
        .filter(
            Deployment.project_id == project_id,
            Deployment.environment == environment,
            Deployment.status == "healthy"
        )
        .order_by(Deployment.deployed_at.desc())
        .first()
    )
    if not deployment:
        raise HTTPException(status_code=404, detail="No healthy deployment found")
    return {
        "id": deployment.id,
        "image_tag": deployment.image_tag,
        "image_name": deployment.image_name,
        "deployed_at": deployment.deployed_at.isoformat() if deployment.deployed_at else None
    }


@app.get("/api/v1/deployments/history")
def get_deployment_history(
    project_id: int = Query(...),
    environment: Optional[str] = None,
    limit: int = Query(20, le=100),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """获取部署历史"""
    query = db.query(Deployment).filter(Deployment.project_id == project_id)
    if environment:
        query = query.filter(Deployment.environment == environment)

    deployments = (
        query.order_by(Deployment.deployed_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "id": d.id,
            "environment": d.environment,
            "image_tag": d.image_tag,
            "status": d.status,
            "strategy": d.strategy,
            "deployed_at": d.deployed_at.isoformat() if d.deployed_at else None,
            "healthy_at": d.healthy_at.isoformat() if d.healthy_at else None,
        }
        for d in deployments
    ]


# ============================================================
# API Routes — ArgoCD Webhook
# ============================================================

@app.post("/api/v1/argocd/webhook")
async def argocd_webhook(
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """
    接收 ArgoCD Notifications 的 Webhook 回调
    自动记录同步状态和健康检查结果
    """
    body = await request.json()
    logger.info(f"ArgoCD webhook received: {json.dumps(body, indent=2)}")

    app_name = body.get("app_name", "")
    sync_status = body.get("sync_status")
    health_status = body.get("health_status")
    revision = body.get("revision")
    phase = body.get("operation_state_phase", sync_status)

    # 找到对应的 project
    project_id = body.get("project_id")
    if project_id:
        project_id = int(project_id)

    # 查找最近的部署
    deployment = None
    if project_id:
        deployment = (
            db.query(Deployment)
            .filter(
                Deployment.project_id == project_id,
                Deployment.status.in_(["pending", "syncing"])
            )
            .order_by(Deployment.deployed_at.desc())
            .first()
        )

    # 记录 ArgoCD 同步
    sync = ArgoCDSync(
        deployment_id=deployment.id if deployment else 0,
        argocd_app=app_name,
        revision=revision or "",
        phase=phase or "Unknown",
        message=body.get("operation_state_message", ""),
        sync_started_at=datetime.now(timezone.utc),
        sync_finished_at=datetime.now(timezone.utc),
    )
    db.add(sync)
    db.flush()

    # 更新部署状态
    if deployment:
        if sync_status == "Synced" and health_status == "Healthy":
            deployment.status = "healthy"
            deployment.healthy_at = datetime.now(timezone.utc)
            deployment.synced_at = datetime.now(timezone.utc)
        elif health_status == "Degraded":
            deployment.status = "degraded"
        elif sync_status == "OutOfSync":
            deployment.status = "syncing"

    # 审计
    audit = AuditLog(
        project_id=project_id,
        deployment_id=deployment.id if deployment else None,
        action="argocd_webhook",
        source="argocd",
        details={
            "app": app_name,
            "sync_status": sync_status,
            "health_status": health_status,
            "phase": phase
        }
    )
    db.add(audit)
    db.commit()

    return {"status": "ok", "sync_id": sync.id}


# ============================================================
# API Routes — Audit Logs
# ============================================================

@app.post("/api/v1/audit", status_code=201)
def create_audit_log(
    payload: AuditLogCreate,
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """记录审计日志"""
    audit = AuditLog(**payload.model_dump())
    db.add(audit)
    db.commit()
    return {"id": audit.id, "action": audit.action}


@app.get("/api/v1/audit")
def get_audit_logs(
    project_id: Optional[int] = None,
    deployment_id: Optional[int] = None,
    action: Optional[str] = None,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """查询审计日志"""
    query = db.query(AuditLog)
    if project_id:
        query = query.filter(AuditLog.project_id == project_id)
    if deployment_id:
        query = query.filter(AuditLog.deployment_id == deployment_id)
    if action:
        query = query.filter(AuditLog.action == action)

    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()

    return [
        {
            "id": l.id,
            "action": l.action,
            "actor": l.actor,
            "source": l.source,
            "details": l.details,
            "created_at": l.created_at.isoformat() if l.created_at else None
        }
        for l in logs
    ]


# ============================================================
# API Routes — Dashboard (运维概览)
# ============================================================

@app.get("/api/v1/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    _: str = Depends(verify_api_key)
):
    """运维概览"""
    total_pipelines = db.query(func.count(Pipeline.id)).scalar()
    total_deployments = db.query(func.count(Deployment.id)).scalar()
    success_rate = db.query(
        func.round(
            100.0 * func.sum(case((Pipeline.status == 'success', 1), else_=0)) /
            func.nullif(func.count(Pipeline.id), 0),
            2
        )
    ).scalar() or 0

    recent_deployments = (
        db.query(Deployment)
        .order_by(Deployment.deployed_at.desc())
        .limit(10)
        .all()
    )

    env_stats = (
        db.query(
            Deployment.environment,
            func.count(Deployment.id).label("total"),
            func.sum(case((Deployment.status == 'healthy', 1), else_=0)).label("healthy")
        )
        .group_by(Deployment.environment)
        .all()
    )

    return {
        "total_pipelines": total_pipelines,
        "total_deployments": total_deployments,
        "success_rate": float(success_rate),
        "recent_deployments": [
            {
                "id": d.id,
                "environment": d.environment,
                "image_tag": d.image_tag,
                "status": d.status,
                "deployed_at": d.deployed_at.isoformat() if d.deployed_at else None
            }
            for d in recent_deployments
        ],
        "environment_stats": [
            {"env": e[0], "total": e[1], "healthy": e[2]}
            for e in env_stats
        ]
    }


# ============================================================
# Health Check
# ============================================================

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "deploy-recorder"}


# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "deploy_recorder:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=LOG_LEVEL.lower()
    )