# Docker Build 从入门到高级

## 目录

1. [基础概念](#1-基础概念)
2. [Dockerfile 指令详解](#2-dockerfile-指令详解)
3. [构建上下文与缓存](#3-构建上下文与缓存)
4. [多阶段构建](#4-多阶段构建)
5. [BuildKit 与高级特性](#5-buildkit-与高级特性)
6. [构建优化实战](#6-构建优化实战)
7. [多架构构建](#7-多架构构建)
8. [CI/CD 中的构建](#8-cicd-中的构建)
9. [常见问题与排查](#9-常见问题与排查)

---

## 1. 基础概念

### 1.1 Docker 镜像是什么

```
镜像 = 只读模板 = 文件系统叠加层

┌──────────────────────┐
│   可写容器层 (Container) │  ← 运行时的修改
├──────────────────────┤
│   层 N: CMD/ENTRYPOINT │
├──────────────────────┤
│   层 3: COPY app.py    │
├──────────────────────┤
│   层 2: RUN pip install│
├──────────────────────┤
│   层 1: FROM ubuntu    │  ← 基础镜像
└──────────────────────┘
```

每一条指令（RUN、COPY、ADD）都会创建一个新的**只读层**，这些层叠加在一起形成最终镜像。层可以共享和缓存，这是 Docker 高效的核心。

### 1.2 `docker build` 基本用法

```bash
# 最基本：在当前目录找 Dockerfile 构建
docker build -t myapp:v1 .

# 指定 Dockerfile
docker build -f Dockerfile.prod -t myapp:prod .

# 指定构建上下文（context）
docker build -t myapp:v1 /path/to/context
```

### 1.3 构建上下文（Build Context）

```
docker build -t myapp .
                      ↑
                  这个 "." 就是构建上下文
```

构建上下文是 `docker build` 发送给 Docker daemon 的**目录内容**（不只是 Dockerfile）。docker daemon 收到上下文后，在其中执行 Dockerfile 指令。

**关键点：**
- `.dockerignore` 排除不需要的文件，减小上下文体积，加速构建
- `COPY . /app` 复制的是上下文中的 `.`，不是宿主机整个文件系统

---

## 2. Dockerfile 指令详解

### 2.1 FROM — 基础镜像

```dockerfile
# 指定镜像和标签
FROM ubuntu:22.04

# 多阶段构建时给阶段命名
FROM golang:1.21 AS builder

# 使用 digest（不可变，比 tag 更安全）
FROM ubuntu@sha256:abc123...
```

### 2.2 RUN — 执行命令

```dockerfile
# Shell 形式（默认 /bin/sh -c）
RUN apt-get update && apt-get install -y curl

# Exec 形式（不经过 shell，没有变量展开）
RUN ["apt-get", "update"]

# 最佳实践：合并多条命令，减少层数
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        vim \
        git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
```

### 2.3 COPY vs ADD

```dockerfile
# COPY：最常用，从构建上下文复制文件
COPY app.py /app/
COPY src/ /app/src/

# ADD：功能更多，但一般用 COPY 就够了
# ADD 额外支持：
#   1. 自动解压 tar 文件
#   2. URL 下载（不推荐，用 RUN curl 更可控）
ADD archive.tar.gz /app/     # 自动解压
ADD https://example.com/file /app/  # 下载（不推荐）
```

**规则：优先用 COPY，除非需要自动解压才用 ADD。**

### 2.4 WORKDIR — 工作目录

```dockerfile
# 设置后续指令的工作目录（不存在会自动创建）
WORKDIR /app
# 之后 RUN、COPY、CMD 都在 /app 下执行

# 推荐用绝对路径，不要这样：
# WORKDIR app        ← 相对路径，容易出错
# WORKDIR /app/sub   ← 绝对路径，清晰明确
```

### 2.5 ENV vs ARG

```dockerfile
# ENV：运行时环境变量（持久存在，影响容器运行）
ENV NODE_ENV=production
ENV APP_HOME=/app

# ARG：构建时变量（只在构建过程中存在，不在最终镜像中）
ARG VERSION=1.0.0
RUN echo "Building version $VERSION"

# ARG 可以在构建时传入
# docker build --build-arg VERSION=2.0.0 -t myapp .
```

### 2.6 CMD vs ENTRYPOINT

```dockerfile
# CMD：默认命令，可以被 docker run 后面的参数覆盖
CMD ["python", "app.py"]

# ENTRYPOINT：入口命令，docker run 后面的参数作为它的参数
ENTRYPOINT ["python"]
CMD ["app.py"]
# 容器启动时默认执行：python app.py
# docker run myimage test.py → 执行：python test.py

# 组合使用（推荐模式）
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["postgres"]
# 默认：docker-entrypoint.sh postgres
# 覆盖：docker run myimage --help → docker-entrypoint.sh --help
```

| | CMD | ENTRYPOINT |
|------|-----|-------------|
| 可否被覆盖 | 可以（`docker run img cmd`） | 需要 `--entrypoint` 才能覆盖 |
| 典型用途 | 默认参数 | 固定入口程序 |
| 组合 | 作为 ENTRYPOINT 的默认参数 | 作为主程序，CMD 提供默认参数 |

### 2.7 EXPOSE — 声明端口

```dockerfile
# 声明容器监听的端口（文档性质，不实际发布端口）
EXPOSE 8080
EXPOSE 8080/udp

# 实际发布端口是在 docker run 时指定
# docker run -p 8080:8080 myapp
```

### 2.8 VOLUME — 声明挂载点

```dockerfile
# 创建匿名卷挂载点
VOLUME /data
VOLUME ["/data", "/logs"]

# 注意：VOLUME 之后对 /data 的任何修改都不会持久化到镜像层
```

### 2.9 USER — 切换用户

```dockerfile
# 创建用户并切换到非 root 运行（安全最佳实践）
RUN useradd --system --no-create-home appuser
USER appuser

# 也可以在命令中临时切换
USER root
RUN apt-get update && apt-get install -y curl
USER appuser
```

### 2.10 HEALTHCHECK — 健康检查

```dockerfile
# 告诉 Docker 如何判断容器是否健康
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# 禁用基础镜像的健康检查
HEALTHCHECK NONE
```

---

## 3. 构建上下文与缓存

### 3.1 .dockerignore

```dockerignore
# 版本控制
.git
.gitignore
.svn

# 依赖
node_modules
__pycache__
*.pyc
.venv
vendor

# 构建产物
dist
build
*.log

# IDE
.vscode
.idea
*.swp

# 文档
README.md
docs/

# Docker 相关
Dockerfile
.dockerignore
docker-compose*.yml

# 临时文件
tmp/
*.tmp
```

### 3.2 构建缓存机制

Docker 逐条执行指令，每执行一条就生成一个层并缓存。下次构建时：

```
1. 从基础镜像开始
2. 逐条比较指令及其上下文
3. 如果指令和上下文都没变 → 使用缓存（Cache hit）
4. 如果有一条变了 → 从这条开始，后续全部重新构建（Cache miss）
```

**缓存失效的常见原因：**

```dockerfile
# ❌ 坏：COPY . 放在前面，每次代码变动都让后续 RUN 失效
COPY . /app
RUN pip install -r requirements.txt

# ✅ 好：先复制依赖文件，再复制代码
COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt
COPY . /app
```

### 3.3 缓存优化策略

```dockerfile
# 策略：按变更频率排序，最不常变的放最前面
FROM python:3.11-slim

# 1. 系统依赖（很少变）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. 依赖文件（偶尔变）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 应用代码（经常变）
COPY . .

# 4. 运行时配置（很少变）
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
```

---

## 4. 多阶段构建（Multi-stage Build）

### 4.1 为什么需要多阶段构建

**问题：** 编译型语言（Go、Rust、Java）需要编译工具链，但运行时不需要，导致镜像臃肿。

```dockerfile
# ❌ 单阶段：镜像包含编译器、源码、中间产物 → 1.2GB
FROM golang:1.21
COPY . .
RUN go build -o app .
CMD ["./app"]
```

**解决：** 多阶段构建，构建和运行分离。

```dockerfile
# ✅ 多阶段：最终镜像只有二进制 → 15MB
# 阶段 1：构建
FROM golang:1.21 AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o app .

# 阶段 2：运行
FROM alpine:3.19
COPY --from=builder /app/app /app
CMD ["/app"]
```

### 4.2 多阶段构建的典型模式

```dockerfile
# 前端构建
FROM node:20 AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
```

```dockerfile
# Java Maven 构建
FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline
COPY src/ src/
RUN mvn package -DskipTests

FROM eclipse-temurin:21-jre
COPY --from=builder /app/target/*.jar app.jar
CMD ["java", "-jar", "app.jar"]
```

### 4.3 从其他阶段或外部镜像复制

```dockerfile
# 从其他阶段复制
COPY --from=builder /app/output /app/

# 从外部镜像复制文件
COPY --from=nginx:alpine /etc/nginx/nginx.conf /etc/nginx/
COPY --from=busybox:latest /bin/wget /usr/local/bin/

# 使用 --chown 改变文件所有者
COPY --chown=appuser:appuser --from=builder /app/build /app
```

---

## 5. BuildKit 与高级特性

### 5.1 BuildKit 简介

BuildKit 是 Docker 的下一代构建引擎 (v18.09+)，默认启用 (v23.0+)。

```bash
# 启用 BuildKit（旧版本需要）
export DOCKER_BUILDKIT=1

# 或者在 /etc/docker/daemon.json 中配置
{
  "features": { "buildkit": true }
}
```

### 5.2 BuildKit 特性一览

| 特性 | 说明 | 传统 Builder |
|------|------|-------------|
| 并行构建 | 独立阶段并行执行 | 串行 |
| 缓存挂载 | 跨构建保留缓存目录 | 不支持 |
| 秘密挂载 | 安全传递密钥，不留在镜像中 | 不支持 |
| SSH 转发 | 构建时使用 SSH 密钥 | 不支持 |
| 输出格式 | 支持多种输出（tar, oci, 本地目录） | 只有镜像 |

### 5.3 缓存挂载（BuildKit）

```dockerfile
# 语法：RUN --mount=type=cache,target=<目录>

# 包管理器缓存：apt 缓存跨构建保留
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y curl

# pip 缓存
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# npm 缓存
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Go 模块缓存
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    go build -o app .
```

### 5.4 秘密挂载（BuildKit）

```dockerfile
# 构建时安全使用密钥，不会留在镜像层中
# 语法：RUN --mount=type=secret,id=secret_name

# 使用私钥
RUN --mount=type=secret,id=ssh_private_key \
    mkdir -p ~/.ssh && \
    cp /run/secrets/ssh_private_key ~/.ssh/id_rsa && \
    chmod 600 ~/.ssh/id_rsa && \
    git clone git@github.com:org/repo.git

# 构建时传入
# docker build --secret id=ssh_private_key,src=$HOME/.ssh/id_rsa -t myapp .
```

```dockerfile
# 使用 API Token
RUN --mount=type=secret,id=npm_token \
    NPM_TOKEN=$(cat /run/secrets/npm_token) \
    npm install --registry=https://private-registry.com

# docker build --secret id=npm_token,src=npm_token.txt -t myapp .
```

### 5.5 SSH 转发（BuildKit）

```dockerfile
# 在构建中使用 SSH 密钥（不留在镜像中）
RUN --mount=type=ssh \
    git clone git@github.com:org/private-repo.git

# 构建时
# docker build --ssh default=$HOME/.ssh/id_rsa -t myapp .
```

### 5.6 BuildKit 输出格式

```bash
# 导出为 tar 文件
docker build --output type=tar,dest=build.tar .

# 导出到本地目录（不创建镜像）
docker build --output type=local,dest=./output .

# 导出为 OCI 格式
docker build --output type=oci,dest=./output.tar .

# 只导出指定阶段
docker build --target builder --output type=local,dest=./output .
```

### 5.7 内联缓存

```bash
# 内联缓存：把缓存元数据嵌入镜像，推送到 registry
docker build --cache-to type=inline --cache-from myapp:latest -t myapp .

# Registry 缓存（推荐）
docker build --cache-to type=registry,ref=myapp:cache \
             --cache-from type=registry,ref=myapp:cache \
             -t myapp .

# 本地缓存
docker build --cache-to type=local,dest=./cache \
             --cache-from type=local,src=./cache \
             -t myapp .
```

---

## 6. 构建优化实战

### 6.1 镜像瘦身十大技巧

```dockerfile
# 1. 选最小基础镜像
FROM alpine:3.19          # 7MB
FROM debian:bookworm-slim # 74MB
FROM scratch              # 0MB（静态二进制）

# 2. 合并 RUN 指令
RUN apt-get update && \
    apt-get install -y curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 3. 清理包管理器缓存
# apt: rm -rf /var/lib/apt/lists/*
# apk: rm -rf /var/cache/apk/*
# yum: yum clean all

# 4. 使用 --no-install-recommends
RUN apt-get install -y --no-install-recommends curl

# 5. 使用 --no-cache-dir（pip）
RUN pip install --no-cache-dir -r requirements.txt

# 6. 多阶段构建
FROM golang:1.21 AS builder
# ... 构建 ...
FROM scratch
COPY --from=builder /app /app

# 7. 删除不必要的文件
RUN rm -rf /usr/share/doc /usr/share/man /tmp/*

# 8. 使用 .dockerignore
# 排除 node_modules, .git, __pycache__ 等

# 9. 压缩层（实验性）
# docker build --squash -t myapp .   # 将多层压成一层（不推荐常规使用）

# 10. 使用 dive 分析镜像
# dive myapp:latest   # 查看每层占用的空间
```

### 6.2 基础镜像选择指南

| 语言 | 运行时镜像 | 大小 | 构建镜像 |
|------|-----------|------|----------|
| Go | `scratch` / `alpine` | 0-7MB | `golang:alpine` |
| Rust | `scratch` / `alpine` | 0-7MB | `rust:alpine` |
| Python | `python:3.11-slim` | 120MB | 同上 |
| Node.js | `node:20-alpine` | 120MB | 同上 |
| Java | `eclipse-temurin:21-jre-alpine` | 200MB | `maven:3.9-eclipse-temurin-21` |
| C/C++ | `alpine` | 7MB | `gcc:13` |

### 6.3 构建速度优化

```dockerfile
# 1. 利用缓存：依赖文件放前面
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o app .

# 2. 并行构建（BuildKit 自动）
# 独立阶段会自动并行执行

# 3. 使用 BuildKit 缓存挂载
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# 4. 精简构建上下文
# .dockerignore 排除大文件

# 5. 使用 docker buildx bake（多镜像并行构建）
# docker buildx bake
```

### 6.4 安全最佳实践

```dockerfile
# 1. 使用非 root 用户
RUN useradd --system --no-create-home appuser
USER appuser

# 2. 固定基础镜像版本（不用 latest）
FROM python:3.11.7-slim   # ✅ 精确版本
FROM python:latest         # ❌ 不可重复构建

# 3. 使用 COPY 而非 ADD
COPY app.py /app/          # ✅
ADD app.py /app/           # ❌ 除非需要解压

# 4. 不要硬编码密钥
ENV API_KEY=sk-xxx         # ❌ 会留在镜像层中
# 使用 BuildKit secret:
# RUN --mount=type=secret,id=api_key ...

# 5. 定期扫描漏洞
# docker scan myapp:latest
# trivy image myapp:latest

# 6. 最小权限原则
# 只安装运行必需的包

# 7. 使用可信基础镜像
FROM python:3.11-slim      # ✅ 官方镜像
FROM python:3.11           # ✅ 官方镜像
FROM randomuser/python     # ❌ 不可信
```

---

## 7. 多架构构建

### 7.1 为什么需要多架构

同一镜像需要支持不同 CPU 架构：

```
linux/amd64  → Intel/AMD 服务器、云服务器
linux/arm64  → Apple Silicon (M1/M2/M3)、树莓派、AWS Graviton
linux/arm/v7 → 树莓派 3B+
linux/s390x  → IBM Z 大型机
```

### 7.2 使用 buildx 构建多架构镜像

```bash
# 1. 创建 buildx builder
docker buildx create --name multiarch --use
docker buildx inspect --bootstrap

# 2. 构建并推送多架构镜像
docker buildx build \
    --platform linux/amd64,linux/arm64 \
    --tag myapp:latest \
    --push \
    .

# 3. 构建并加载到本地（单架构）
docker buildx build \
    --platform linux/arm64 \
    --tag myapp:arm64 \
    --load \
    .

# 4. 查看 builder 状态
docker buildx ls
```

### 7.3 多架构 Dockerfile 注意事项

```dockerfile
# 使用 TARGETARCH 自动变量
FROM alpine:3.19
ARG TARGETARCH
RUN echo "Building for $TARGETARCH"

# 根据架构安装不同包
RUN if [ "$TARGETARCH" = "arm64" ]; then \
        apk add --no-cache some-arm-package; \
    else \
        apk add --no-cache some-amd64-package; \
    fi
```

### 7.4 可用变量

| 变量 | 示例值 | 说明 |
|------|--------|------|
| `TARGETARCH` | `amd64`, `arm64` | 目标架构 |
| `TARGETOS` | `linux`, `windows` | 目标操作系统 |
| `TARGETPLATFORM` | `linux/amd64` | 目标平台 |
| `TARGETVARIANT` | `v7` | 架构变体 |
| `BUILDARCH` | `amd64` | 构建机架构 |
| `BUILDOS` | `linux` | 构建机 OS |

---

## 8. CI/CD 中的构建

### 8.1 GitHub Actions 示例

```yaml
name: Build and Push Docker Image

on:
  push:
    branches: [main]
    tags: ['v*']

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and Push
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          platforms: linux/amd64,linux/arm64
```

### 8.2 GitLab CI 示例

```yaml
build:
  stage: build
  image: docker:24-dind
  services:
    - docker:24-dind
  variables:
    DOCKER_BUILDKIT: 1
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

### 8.3 私有 Registry 推送

```bash
# 登录
docker login registry.example.com

# 标记镜像
docker tag myapp:latest registry.example.com/myapp:latest

# 推送
docker push registry.example.com/myapp:latest

# 在 Dockerfile 中引用私有镜像
# FROM registry.example.com/base:latest
```

---

## 9. 常见问题与排查

### 9.1 构建失败原因速查

| 现象 | 可能原因 | 解决 |
|------|---------|------|
| `COPY failed: file not found` | 路径不在构建上下文中 | 检查 `.dockerignore`，确认路径相对于上下文 |
| `no space left on device` | 磁盘空间不足 | `docker system prune -a` 清理 |
| `Cannot connect to docker daemon` | Docker 没启动 | `systemctl start docker` |
| `exec format error` | 架构不匹配 | 确认 `--platform` 正确 |
| `apt-get update` 失败 | 网络问题 | 检查 DNS、代理 |
| Layer 大小异常 | 未清理缓存 | 合并 RUN 并清理 |

### 9.2 调试技巧

```bash
# 查看构建历史
docker history myapp:latest

# 进入某个中间层
docker run -it --rm <image_id> /bin/sh

# 查看镜像详细信息
docker inspect myapp:latest

# 分析镜像层大小
docker history --no-trunc --human myapp:latest

# 使用 dive 工具深入分析
dive myapp:latest

# BuildKit 详细日志
docker build --progress=plain -t myapp .
```

### 9.3 常见错误示例

```dockerfile
# ❌ 错误 1：COPY 之后 RUN 安装依赖 → 缓存失效
COPY . .
RUN pip install -r requirements.txt

# ✅ 正确：先复制依赖文件
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# ❌ 错误 2：使用 latest 标签
FROM python:latest

# ✅ 正确：使用精确版本
FROM python:3.11.7-slim

# ❌ 错误 3：RUN 中残留敏感信息
RUN curl -H "Authorization: Bearer $TOKEN" https://api.example.com

# ✅ 正确：使用 BuildKit secret
RUN --mount=type=secret,id=api_token \
    TOKEN=$(cat /run/secrets/api_token) \
    curl -H "Authorization: Bearer $TOKEN" https://api.example.com
```

---

## 附录：命令速查

```bash
# 构建
docker build -t name:tag .                    # 基本构建
docker build -f Dockerfile.prod -t name .     # 指定 Dockerfile
docker build --no-cache -t name .             # 不使用缓存
docker build --build-arg KEY=val -t name .    # 传入构建参数
docker build --progress=plain -t name .       # 显示详细输出

# 清理
docker builder prune                           # 清理构建缓存
docker system prune -a                         # 清理所有未使用资源
docker image prune                             # 清理未使用镜像

# 查看
docker images                                  # 列出本地镜像
docker history name:tag                        # 查看镜像层历史
docker inspect name:tag                        # 查看镜像详情
docker buildx ls                               # 查看构建器

# 多架构
docker buildx create --name multiarch --use    # 创建构建器
docker buildx build --platform linux/amd64,linux/arm64 -t name --push .

# 分析
dive name:tag                                  # 分层分析镜像大小
docker scan name:tag                           # 安全漏洞扫描
```