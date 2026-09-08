# Dockerfile 构建镜像详细指南

> 适用范围：使用 Dockerfile 构建应用镜像，并在本地、CI/CD 或镜像仓库中交付。
>
> 文档边界：本文说明构建、检查、推送和交付镜像的方法，不替代 Kubernetes Deployment、Helm 或具体云厂商的发布手册。文中的镜像名、仓库地址、端口和版本均为示例，未在本机或生产环境执行。

## 目录

1. [先看结论](#1-先看结论)
2. [构建前的准备](#2-构建前的准备)
3. [Dockerfile、上下文和镜像的关系](#3-dockerfile上下文和镜像的关系)
4. [一个可维护的最小示例](#4-一个可维护的最小示例)
5. [Dockerfile 指令详解](#5-dockerfile-指令详解)
6. [构建上下文与 .dockerignore](#6-构建上下文与-dockerignore)
7. [docker build 常用命令](#7-docker-build-常用命令)
8. [缓存与构建速度](#8-缓存与构建速度)
9. [多阶段构建](#9-多阶段构建)
10. [BuildKit 的缓存、Secret 和 SSH](#10-buildkit-的缓存secret-和-ssh)
11. [镜像安全与可重复构建](#11-镜像安全与可重复构建)
12. [本地构建和验收](#12-本地构建和验收)
13. [推送到 Registry](#13-推送到-registry)
14. [CI/CD 中的构建](#14-cicd-中的构建)
15. [与 Kubernetes 交付的边界](#15-与-kubernetes-交付的边界)
16. [常见问题排查](#16-常见问题排查)
17. [上线前检查清单](#17-上线前检查清单)
18. [延伸阅读](#18-延伸阅读)

---

## 1. 先看结论

一条完整的镜像交付路径是：

```text
源代码 + Dockerfile + .dockerignore
              │
              ▼
        docker build / buildx
              │
              ▼
      本地镜像（分层、带元数据）
              │
              ├── docker run 验证实际进程和请求
              └── docker push 推送到 Registry
                              │
                              ▼
                    部署系统按 tag 或 digest 拉取
```

写 Dockerfile 时，优先遵守下面几条：

- 用固定的基础镜像版本；生产环境进一步记录并核对 digest。
- 明确构建上下文，使用 `.dockerignore` 排除 `.git`、依赖缓存、构建产物和本地密钥。
- 先复制依赖清单并安装依赖，再复制经常变化的业务代码，以获得稳定缓存。
- 编译工具、源码和测试依赖放在构建阶段，最终运行阶段只保留运行所需文件。
- 使用 exec 形式的 `ENTRYPOINT`/`CMD`，让进程正确接收 `SIGTERM`，便于优雅退出。
- 让应用以非 root 用户运行，并明确监听地址、端口、健康检查和启动命令。
- 不要把密码、Token、私钥放进 `ARG`、`ENV`、`COPY` 或普通 `RUN`；构建时凭据使用 BuildKit secret/SSH mount。
- 生产发布使用不可变标签（例如 Git commit SHA）或 digest，不把可变的 `latest` 当作唯一版本依据。

### 1.1 先区分三个“成功”

| 层次 | 能证明什么 | 不能证明什么 |
|------|------------|--------------|
| `docker build` 返回 0 | Dockerfile 能被当前构建器解析并产出镜像 | 应用启动正常、业务接口可用、目标架构可运行 |
| `docker run` 进程存在 | 容器入口命令能启动 | 外部网络、依赖服务、鉴权和完整业务流程 |
| 实际 HTTP/RPC 请求成功 | 当前容器在当前环境能完成一次真实请求 | 集群调度、滚动升级、扩缩容和故障恢复 |

因此，验收至少要覆盖：构建日志、镜像元数据、容器日志、健康检查和一个真实请求。

---

## 2. 构建前的准备

### 2.1 检查客户端和构建器

```bash
docker version
docker buildx version
docker info
docker buildx ls
```

需要确认：

1. Docker CLI 可以连接到预期的 Docker Engine 或远程 BuildKit builder。
2. `docker buildx` 可用；`--secret`、`--mount=type=cache`、多架构和 `--check` 等能力依赖 BuildKit/Buildx 版本。
3. 当前账号有权访问 Docker socket、私有 Registry 和代理网络（如果使用）。
4. 目标运行环境的 CPU 架构、操作系统、基础镜像来源和出网策略已明确。

### 2.2 建议的项目结构

```text
myapp/
├── Dockerfile
├── .dockerignore
├── go.mod / package.json / pyproject.toml   # 按语言选择
├── src/ 或 app/
├── tests/
├── deploy/                                 # 可选：K8s/Helm/GitOps 文件
└── docs/
```

Dockerfile 不必放在项目根目录，但要明确 `-f` 指定的文件和最后一个位置参数代表的构建上下文。Dockerfile 能通过 `COPY` 访问的范围是上下文，而不是宿主机任意路径。

### 2.3 先确定镜像契约

在写 Dockerfile 前记录以下信息：

| 项目 | 示例 | 需要确认的实际值 |
|------|------|------------------|
| 进程 | `python -m app` | 应用真实启动命令 |
| 监听地址 | `0.0.0.0` | 不能只监听容器内的 `127.0.0.1` |
| 端口 | `8080/tcp` | 容器端口，不等同于宿主机端口 |
| 用户 | `app:app` | UID/GID、文件读写目录 |
| 健康检查 | `GET /healthz` | 是否需要认证、启动耗时、超时 |
| 运行时依赖 | CA 证书、字体、动态库 | 运行阶段必须存在的文件 |
| 目标平台 | `linux/amd64`、`linux/arm64` | 是否需要多架构 manifest |
| 镜像标签 | `registry.example.com/team/app:<git-sha>` | 仓库、权限和保留策略 |

---

## 3. Dockerfile、上下文和镜像的关系

### 3.1 Dockerfile 是构建指令，不是启动脚本

Dockerfile 描述“如何得到镜像”，其中：

- `RUN` 在构建阶段执行并把结果写入镜像层。
- `CMD` 和 `ENTRYPOINT` 通常不在构建时执行，只记录容器启动时的默认进程。
- `COPY` 从构建上下文或其他构建阶段复制文件。
- `ENV` 会成为镜像默认环境变量，容器启动时仍可覆盖。
- `ARG` 主要用于构建阶段，不能作为存放 Secret 的机制。

### 3.2 构建上下文

```bash
# . 代表当前目录作为上下文
docker build -t example/app:dev .

# Dockerfile 在 docker/ 目录，但上下文仍为项目根目录
docker build -f docker/Dockerfile -t example/app:dev .

# 只把 backend 目录作为上下文
docker build -f docker/Dockerfile -t example/app:dev backend/
```

最后一个参数决定了 `COPY` 能看到哪些文件。下面的写法无法复制上下文之外的文件：

```dockerfile
# ❌ 如果 /etc/hosts 不在构建上下文内，构建会失败
COPY /etc/hosts /tmp/hosts
```

### 3.3 镜像层和可写容器层

`FROM`、`RUN`、`COPY` 等指令会形成可复用的只读层；容器运行时在顶部增加可写层。容器删除后，写入可写层的数据通常随容器消失。因此：

- 不要把数据库、上传文件或持久化日志只写到容器可写层。
- 运行时数据应通过卷、对象存储或外部服务保存。
- 删除 Dockerfile 后续层里的文件，并不能抹掉前一层已经写入的 Secret；敏感数据不能先写入再删除。

---

## 4. 一个可维护的最小示例

下面示例使用 Python 标准库，重点展示顺序、用户、健康检查和运行时配置。`app.py` 的实际内容需要由项目提供。

### 4.1 示例 Dockerfile

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm

# 运行时默认值；敏感信息不要写在这里
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOME=/app

WORKDIR ${APP_HOME}

# 先复制低频变化的依赖文件，利于复用缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 创建非 root 用户，并准备应用目录
RUN groupadd --system app && \
    useradd --system --gid app --create-home --home-dir ${APP_HOME} app

# 最后复制高频变化的应用代码
COPY --chown=app:app app.py ./

USER app
EXPOSE 8080

# exec 形式：容器内进程直接作为 PID 1 接收信号
ENTRYPOINT ["python", "app.py"]

# 只有应用确实提供该端点时才添加健康检查
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
```

### 4.2 示例 `.dockerignore`

```dockerignore
.git
.gitignore
.dockerignore
Dockerfile*
**/.DS_Store
**/__pycache__/
**/*.pyc
.venv/
venv/
node_modules/
dist/
build/
coverage/
*.log
*.tmp
.env
.env.*
id_rsa
*.pem
```

`Dockerfile` 和 `.dockerignore` 即使被排除，构建客户端仍会将它们提供给构建器用于完成构建；不要依赖“排除文件”来传递 Secret，也不要在 Dockerfile 中尝试 `COPY` 被排除的凭据。

### 4.3 构建和运行示例

```bash
docker build \
  --pull \
  --tag example/app:dev \
  .

docker run --rm \
  --name example-app \
  --publish 8080:8080 \
  --env APP_ENV=dev \
  example/app:dev
```

上面的 `--env` 是运行时配置；若变量会改变前端静态资源或编译产物，则必须在构建阶段通过 Dockerfile/CI 注入并重新构建，容器启动后再设置环境变量不会修改已经生成的静态文件。

---

## 5. Dockerfile 指令详解

### 5.1 语法指令和注释

```dockerfile
# syntax=docker/dockerfile:1
# check=skip=JSONArgsRecommended
```

- `# syntax=...` 选择 Dockerfile 前端语法；使用 BuildKit 特性时建议显式声明。
- `# check=...` 可配置构建检查；不要为了让构建通过而随意关闭检查，应记录关闭原因并在代码评审中确认。
- 注释必须位于指令行前；不要把普通 shell 注释误认为 Dockerfile parser directive。

### 5.2 `FROM`：选择基础镜像和构建阶段

```dockerfile
FROM node:22-bookworm-slim AS build
FROM nginx:1.27-alpine
```

规则和建议：

- 每个 `FROM` 开始一个新的构建阶段。
- `FROM` 之后的 `ARG` 只能使用在它之前声明的全局参数。
- 生产环境不要使用无约束的 `latest`；至少固定主版本/发行版，关键组件记录 digest。
- `alpine` 不是所有应用的默认最优选择；基于 musl 的兼容性、调试工具和证书/时区需求要实际验证。
- `scratch` 没有 shell、CA 证书、时区和系统用户；只适合明确准备运行时依赖的静态程序。

```dockerfile
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim-bookworm
```

### 5.3 `RUN`：构建阶段执行命令

```dockerfile
# shell 形式：由默认 shell 解释
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# exec 形式：不自动经过 shell，不会做 shell 变量展开
RUN ["python", "-m", "compileall", "-q", "."]
```

注意：

- `RUN` 产生构建结果，不能替代容器启动命令。
- apt 类命令要在同一层完成 `update`、安装和索引清理，避免缓存失配及无用文件进入镜像。
- 使用 `set -eux`、明确工作目录和失败条件，避免脚本吞掉错误。
- shell 形式涉及变量、管道或信号转发时，要确认使用的 shell 行为；长时间运行的应用入口更推荐 exec 形式。

### 5.4 `COPY` 与 `ADD`

```dockerfile
COPY package.json package-lock.json ./
COPY --chown=app:app src/ /app/src/
COPY --from=build /app/dist/ /usr/share/nginx/html/
```

通常优先 `COPY`。`ADD` 还支持自动解压本地 tar 和部分远程来源，但隐式行为会降低可读性和可审计性；需要下载文件时，优先使用固定校验和的下载命令，或者在构建上下文中准备好文件。

`COPY --from=<stage>` 只复制指定构建阶段的产物，不会把构建工具链带入最终镜像。

### 5.5 `WORKDIR`

```dockerfile
WORKDIR /app
```

`WORKDIR` 影响后续 `RUN`、`COPY`、`ADD`、`CMD` 和 `ENTRYPOINT`。建议使用绝对路径并尽早设置，避免依赖基础镜像未知的默认目录。

### 5.6 `ARG` 与 `ENV`

```dockerfile
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION}
RUN echo "building ${APP_VERSION}"
```

| 项目 | `ARG` | `ENV` |
|------|-------|-------|
| 作用阶段 | 构建阶段 | 构建后仍作为镜像默认环境变量 |
| 传入方式 | `docker build --build-arg NAME=value` | `docker run -e NAME=value` 或 Dockerfile |
| 是否适合 Secret | 不适合，可能出现在 history/provenance | 不适合，会进入镜像配置 |
| 常见用途 | 版本、目标平台、构建开关 | 运行模式、默认路径、语言运行时参数 |

不要写：

```dockerfile
# ❌ Token 会进入镜像历史或镜像元数据
ARG NPM_TOKEN
RUN npm config set //registry.example.com/:_authToken=${NPM_TOKEN}
```

需要凭据时见[第 10 节](#10-buildkit-的缓存secret-和-ssh)。

### 5.7 `CMD` 与 `ENTRYPOINT`

```dockerfile
ENTRYPOINT ["/usr/local/bin/app"]
CMD ["--config", "/etc/app/config.yaml"]
```

- `ENTRYPOINT` 定义容器的主要可执行程序。
- `CMD` 提供默认命令或默认参数；`docker run image <args>` 会覆盖/追加默认行为。
- 两者都只有最后一次声明生效。
- 推荐 JSON/exec 形式；shell 形式可能多出 `/bin/sh -c`，并影响信号和参数处理。

快速判断：

| 目标 | 推荐写法 |
|------|----------|
| 固定启动一个服务，可覆盖参数 | `ENTRYPOINT ["app"]` + `CMD ["--port", "8080"]` |
| 基础镜像只是提供运行时，由部署系统传命令 | 只设合理的 `CMD` 或由编排文件明确覆盖 |
| 启动脚本需要做一次初始化 | `ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]`，脚本末尾使用 `exec "$@"` |

### 5.8 `EXPOSE`

```dockerfile
EXPOSE 8080/tcp
```

`EXPOSE` 是镜像元数据和文档声明，不会自动把端口发布到宿主机。实际映射由 `docker run -p`、Compose、Kubernetes Service 或其他编排层决定。

### 5.9 `USER`

```dockerfile
RUN groupadd --system app && \
    useradd --system --gid app --create-home app
USER app
```

安装系统包、创建目录等需要 root 的步骤应放在前面；完成后切换到非 root 用户。确认应用需要写入的路径权限，避免只在容器启动后才暴露 `Permission denied`。

### 5.10 `HEALTHCHECK`

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8080/healthz || exit 1
```

健康检查只应验证“进程是否能提供基本服务”，不要把外部数据库、第三方 API 或高成本业务流程作为唯一存活检查。镜像中没有 `curl` 时，使用应用运行时已有的轻量客户端，或把探针放在编排层。

### 5.11 `LABEL`、`SHELL`、`STOPSIGNAL`、`VOLUME`、`ONBUILD`

```dockerfile
LABEL org.opencontainers.image.source="https://git.example.com/team/app" \
      org.opencontainers.image.revision="unknown"
```

- `LABEL` 可写入源码、构建版本、维护者和许可证等元数据；不要写入 Token。
- `SHELL` 只在需要改变 shell 行为时使用，并明确影响范围。
- `STOPSIGNAL` 适用于应用需要非默认停止信号的场景；先验证应用的信号处理。
- `VOLUME` 声明默认挂载点，但不会自动提供跨主机备份或高可靠持久化。
- `ONBUILD` 会把触发指令埋入基础镜像，容易产生隐式行为；只有维护“供其他项目继承的基础镜像”时才考虑使用。

---

## 6. 构建上下文与 `.dockerignore`

### 6.1 为什么上下文大小重要

构建客户端会将上下文发送给构建器。上下文越大：

- 首次构建越慢，远程 BuildKit/CI 的上传时间越长。
- 文件变化越多，`COPY . .` 的缓存越容易失效。
- 本地密钥、日志、源码副本可能被意外送入构建环境。

检查上下文的简单方法：

```bash
du -sh .
du -sh --exclude=.git . 2>/dev/null || true
```

真正送入构建器的文件还受 `.dockerignore` 影响，应结合构建日志中 `load build context` 的大小判断。

### 6.2 `.dockerignore` 规则

```dockerignore
# 目录和文件
.git/
node_modules/
*.log

# 环境文件和凭据
.env
.env.*
*.key
*.pem

# 如果确实需要某个文件，可用 ! 例外规则恢复
docs/
!docs/README.md
```

规则是按顺序匹配的，最后一个匹配规则决定文件是否保留。多个 Dockerfile 时，可把专用忽略文件放在 Dockerfile 旁边，例如：

```text
docker/build.Dockerfile
docker/build.Dockerfile.dockerignore
```

专用忽略文件优先于上下文根目录的 `.dockerignore`。不要盲目排除运行所需的证书、迁移脚本或前端构建输入；每次调整后都要重新构建并验证。

### 6.3 Named context

需要让 Dockerfile 读取另一组只读文件时，可使用 named context：

```bash
docker build \
  --build-context docs=./docs \
  -t example/app:dev \
  .
```

```dockerfile
# docs 是通过 --build-context 传入的命名上下文
COPY --from=docs . /usr/share/nginx/html/docs/
```

这能避免把多个目录拼成一个临时上下文；使用前要确认团队的 Docker/Buildx 版本支持该能力。

---

## 7. `docker build` 常用命令

### 7.1 基础命令

```bash
# 使用当前目录和默认 Dockerfile
docker build -t example/app:dev .

# 指定 Dockerfile 和上下文
docker build -f docker/Dockerfile -t example/app:dev .

# 拉取更新的 FROM 基础镜像，但不等于完全无缓存构建
docker build --pull -t example/app:dev .

# 忽略已有缓存，适合诊断缓存问题；构建会更慢
docker build --no-cache -t example/app:debug .

# 查看更完整的构建进度
docker build --progress=plain -t example/app:debug .
```

### 7.2 参数、目标阶段和输出

```bash
# 传入非敏感的构建参数
docker build \
  --build-arg APP_VERSION=2026.09.08 \
  -t example/app:2026.09.08 \
  .

# 只构建到指定阶段，用于调试或导出测试产物
docker build --target build -t example/app:build .

# buildx 构建并加载到本地 Docker 镜像库
docker buildx build --load -t example/app:dev .

# buildx 构建后直接推送，不把多架构结果加载到本地
docker buildx build --push -t registry.example.com/team/app:${GIT_SHA} .
```

`docker buildx build` 的结果默认取决于 builder 和输出方式；在 CI 中要明确使用 `--load`、`--push` 或 `--output`，不要假定镜像一定会出现在当前 Docker Engine。

### 7.3 多架构构建

```bash
docker buildx create --name ci-builder --use
docker buildx inspect --bootstrap

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag registry.example.com/team/app:${GIT_SHA} \
  --push \
  .
```

注意：

- 多架构构建会生成 manifest list；`--load` 通常只适合单一平台的本地加载。
- 原生编译、CGO、平台相关依赖和基础镜像必须验证架构兼容性。
- `TARGETOS`、`TARGETARCH` 等自动参数可用于条件构建，但不能替代真实运行测试。

### 7.4 构建检查

```bash
# 只检查 Dockerfile，不真正生成镜像；要求较新的 Buildx
docker build --check .

# 构建时使用 plain 输出，便于保存 CI 证据
docker buildx build --progress=plain -t example/app:ci .
```

构建检查可以发现部分指令风格、变量和可维护性问题，但不会证明应用功能正确、依赖可用或镜像无漏洞。

---

## 8. 缓存与构建速度

### 8.1 缓存失效规律

构建器从前往后处理指令。某一层的指令或依赖文件改变后，通常从该层开始，后续层都需要重新执行。因此下面的顺序会导致代码每次变化都重新安装依赖：

```dockerfile
# ❌ 代码先复制，依赖安装缓存容易失效
COPY . /app
RUN pip install --no-cache-dir -r /app/requirements.txt
```

更合理的顺序：

```dockerfile
# ✅ 依赖清单变化才触发依赖安装
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app/
```

### 8.2 缓存设计原则

1. `FROM`、系统依赖和工具链放前面，应用源码放后面。
2. 按依赖清单复制：`package-lock.json`、`go.sum`、`poetry.lock` 等与代码分开。
3. 缩小 `COPY . .` 的范围，避免把无关文件引入缓存键。
4. 不把时间戳、随机数或当前时间写进 Dockerfile，否则每次都可能破坏可复用性。
5. CI 远程构建时，将缓存导出到 Registry 或 CI 缓存后端，并设置保留策略。

### 8.3 分层与清理

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    make && \
    apt-get purge -y --auto-remove build-essential && \
    rm -rf /var/lib/apt/lists/* /tmp/*
```

单纯在后续层删除文件，不能抹掉前一层的大小；更稳妥的方式是多阶段构建，或者在同一个 `RUN` 中安装、使用和清理构建工具。

### 8.4 如何判断缓存是否真的生效

```bash
docker build --progress=plain -t example/app:cache-test . 2>&1 | tee build.log
rg -n 'CACHED|cache|transferring context' build.log
```

不要只看总耗时。应对比依赖安装步骤是否命中缓存、上下文大小是否异常、是否因基础镜像更新而重新执行。

---

## 9. 多阶段构建

### 9.1 Go 示例

```dockerfile
# syntax=docker/dockerfile:1

FROM golang:1.24-bookworm AS build
WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/app ./cmd/app

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/app /app
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/app"]
```

需要确认：

- `CGO_ENABLED=0` 是否与应用依赖兼容。
- 是否需要 CA 证书、时区、字体或动态链接库；`distroless`/`scratch` 默认不提供这些内容。
- `nonroot` 用户是否能读取配置和写入必要目录。

### 9.2 前端静态资源示例

```dockerfile
FROM node:22-bookworm-slim AS build
WORKDIR /web

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /web/dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
```

前端框架常把变量编译进静态 JS。`ARG`/`ENV` 必须在 `npm run build` 之前生效；部署阶段的 ConfigMap 或 `docker run -e` 不会自动改变已经构建好的 JS 内容。变量中不要放长期 Token、数据库密码或用户级私密信息。

### 9.3 调试构建阶段

```bash
# 构建到 build 阶段，保留编译器和源码，方便检查
docker build --target build -t example/app:build-debug .

docker run --rm -it --entrypoint /bin/sh example/app:build-debug
```

调试阶段镜像不应作为生产镜像发布。生产 tag 应明确来自最终阶段，并在 CI 中检查最终镜像的入口和文件清单。

---

## 10. BuildKit 的缓存、Secret 和 SSH

### 10.1 缓存挂载

缓存挂载用于复用包管理器缓存，但缓存内容不应被当作最终镜像数据依赖：

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```

常见目录：

| 工具 | 缓存目录示例 |
|------|--------------|
| pip | `/root/.cache/pip` |
| npm | `/root/.npm` |
| Go | `/go/pkg/mod`、`/root/.cache/go-build` |
| Maven | `/root/.m2` |

先确认包管理器和构建器支持该 mount，再在 CI 中观察缓存命中率；缓存可能被清理，构建必须在冷缓存下仍然成功。

### 10.2 Secret mount

Docker 官方不建议用 `ARG` 传递密码、API Token 等 Secret，因为它们可能出现在构建历史或 provenance 中。BuildKit secret mount 的文件只在对应的 `RUN` 期间可见：

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./

RUN --mount=type=secret,id=npmrc,target=/root/.npmrc \
    npm ci
```

```bash
docker buildx build \
  --secret id=npmrc,src="$PWD/.npmrc" \
  -t example/app:private-deps \
  .
```

安全边界：

- 命令行、CI 日志和构建输出不要打印 Secret 内容。
- `src` 指向的文件由 CI Secret 管理，不要提交到 Git。
- Secret 不应被 `COPY` 进镜像，也不要把它复制到普通文件后再删除。
- Registry、CI 平台和 BuildKit builder 仍需单独配置权限和审计。

### 10.3 SSH mount

拉取私有 Git 依赖时可转发 SSH agent：

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.21
RUN apk add --no-cache git openssh-client
RUN --mount=type=ssh \
    git clone git@github.com:example/private-module.git /opt/private-module
```

```bash
docker buildx build \
  --ssh default \
  -t example/app:private-source \
  .
```

这不是让镜像携带私钥；仍需配置 known_hosts、最小权限和 CI agent 生命周期。若依赖可以通过带校验和的发布包获取，优先使用可重复的包版本。

### 10.4 缓存和 Secret 的选择

| 需求 | 机制 | 是否进入最终镜像 |
|------|------|------------------|
| 加速下载依赖 | `RUN --mount=type=cache` | 不应进入 |
| 读取包仓库 Token | `RUN --mount=type=secret` | 不进入 |
| 访问私有 Git | `RUN --mount=type=ssh` | 不进入 |
| 运行时数据库密码 | 编排平台 Secret/外部密钥服务 | 不进入 |

---

## 11. 镜像安全与可重复构建

### 11.1 基础镜像和依赖

- 从组织认可的 Registry 或官方镜像来源选择基础镜像。
- 使用版本约束和 digest 记录构建输入；定期更新并重新扫描，而不是永远冻结在有漏洞的旧 digest。
- 构建依赖和运行依赖分离；删除编译器、包管理器缓存、测试数据和调试工具。
- 运行阶段保留 CA 证书、时区数据、动态库等真实依赖，避免为了缩小镜像而破坏 TLS 或本地化功能。

### 11.2 身份和权限

```dockerfile
RUN install -d -o app -g app /var/lib/app
USER app:app
```

- 默认非 root；确需 root 的初始化动作应有明确理由和范围。
- 不要通过 `chmod -R 777` 绕过权限问题；确认目录所有者、UID/GID 和挂载卷的权限。
- 入口脚本使用 `exec "$@"`，否则应用可能收不到停止信号。

### 11.3 Secret、日志和镜像历史

以下内容都可能留下敏感数据：

- `RUN echo "$TOKEN"` 的构建输出。
- `ARG TOKEN=...`、`ENV TOKEN=...`。
- `COPY . .` 把 `.env`、私钥、云凭据复制进镜像。
- 包管理器生成的配置文件和错误日志。
- CI 上传的完整构建日志、镜像 history 或 provenance。

检查镜像元数据时可以使用：

```bash
docker history --no-trunc example/app:dev
docker inspect example/app:dev
```

输出可能包含路径、命令和标签，不要把包含凭据的结果粘贴到工单、聊天或长期文档中。

### 11.4 扫描和签名

扫描工具和参数由组织标准决定，常见流程如下：

```bash
# 示例：使用已批准的扫描器；命令需按实际工具版本调整
trivy image --severity HIGH,CRITICAL example/app:${GIT_SHA}
```

扫描发现漏洞后要区分：基础镜像漏洞、应用依赖漏洞、仅存在于构建阶段的漏洞和实际可达漏洞。不要只看数量；要记录修复版本、误报依据、豁免期限和重新扫描结果。镜像签名、SBOM、provenance 和准入策略应由团队的 Registry/供应链方案统一定义。

### 11.5 可重复构建

建议把以下输入纳入版本控制或构建记录：

- Dockerfile、`.dockerignore`、依赖锁定文件。
- 基础镜像 tag 和 digest。
- 构建器版本、目标平台和 BuildKit 配置。
- Git commit SHA、构建时间和镜像 digest。
- 构建参数（不含 Secret 值）和外部依赖源。

“同一个 tag 能拉到镜像”不等于可重复构建；生产回滚应优先记录并使用镜像 digest。

---

## 12. 本地构建和验收

下面是一套只读观察加临时容器的最小验收流程。示例中的镜像、端口和 URL 需要替换；本仓库未执行这些命令。

### 12.1 静态检查和构建

```bash
docker build --check .
docker build --pull --progress=plain -t example/app:${GIT_SHA:-local} .
```

检查：

- Dockerfile 是否使用了预期的基础镜像和目标阶段。
- `.dockerignore` 是否排除了本地凭据和大目录。
- 依赖安装是否命中缓存，是否有隐藏的下载失败或被忽略的错误。
- 最终镜像是否真的由最终运行阶段产出。

### 12.2 镜像元数据

```bash
docker image inspect example/app:${GIT_SHA:-local}
docker history --no-trunc example/app:${GIT_SHA:-local}
docker image ls example/app
```

重点查看：

- `Entrypoint`、`Cmd`、`WorkingDir`、`User`、`Env`。
- `ExposedPorts` 是否与应用实际监听端口一致。
- 是否意外携带 `.env`、源码、编译器和调试工具。
- 镜像大小和层大小是否异常。

### 12.3 临时启动和容器日志

```bash
docker run -d --rm \
  --name example-app-test \
  --publish 18080:8080 \
  --env APP_ENV=test \
  example/app:${GIT_SHA:-local}

docker ps --filter name=example-app-test
docker logs --tail=200 example-app-test
docker inspect --format '{{json .State}}' example-app-test
```

容器处于 `Up` 只说明主进程尚未退出；还要观察日志中的启动错误、依赖连接失败、端口监听和健康状态。

### 12.4 健康检查和真实请求

```bash
docker inspect --format '{{json .State.Health}}' example-app-test
curl --fail --silent --show-error http://127.0.0.1:18080/healthz
curl --fail --silent --show-error http://127.0.0.1:18080/api/v1/status
```

验证响应状态码之外，还要检查：

- `Content-Type`、响应体结构和错误码。
- 请求是否进入应用日志，是否访问了预期依赖。
- 应用是否以正确用户运行，是否能读配置、写临时目录。
- 停止时是否能在超时前优雅退出。

### 12.5 清理临时容器

```bash
docker rm -f example-app-test
```

只删除本次启动的明确容器名；不要使用无范围的批量删除命令。若需要释放构建缓存，应先确认缓存不会影响其他项目，并按团队保留策略执行。

---

## 13. 推送到 Registry

### 13.1 认证和标记

```bash
docker login registry.example.com

docker tag example/app:dev \
  registry.example.com/team/app:${GIT_SHA}
docker push registry.example.com/team/app:${GIT_SHA}
```

认证信息不要写进 Dockerfile、脚本仓库或命令历史。CI 应使用短期凭据、最小权限和平台 Secret。

### 13.2 使用不可变版本

推荐同时保存：

- 人类可读的发布标签：`v1.8.0`。
- 不可变构建标签：`sha-<完整或短 Git SHA>`。
- Registry 返回的 digest：`repo@sha256:<digest>`。

```bash
docker pull registry.example.com/team/app:${GIT_SHA}
docker image inspect registry.example.com/team/app:${GIT_SHA}
```

拉取成功不等于应用可用；仍需在目标运行环境做启动和真实请求验收。

### 13.3 推送后的核对

```bash
docker buildx imagetools inspect \
  registry.example.com/team/app:${GIT_SHA}
```

多架构镜像要核对 manifest 中是否包含目标平台；单架构镜像要确认运行节点架构匹配。Registry 的保留、复制、签名和扫描状态需在 Registry 侧进一步确认。

---

## 14. CI/CD 中的构建

### 14.1 推荐的流水线顺序

```text
lint / docker build --check
        │
        ▼
构建最终镜像（带 Git SHA）
        │
        ├── 单元测试或容器内测试
        ├── 漏洞扫描 / SBOM / 签名
        └── 推送 Registry
                    │
                    ▼
          更新部署仓库或发布清单
```

CI 只把“构建成功”作为中间结果；推送、扫描、签名、部署和真实请求需要分别记录状态。

### 14.2 GitLab CI 示例（BuildKit/buildx）

下面展示流程结构，Runner、镜像仓库和权限需要按实际环境替换。若采用 Docker-in-Docker，通常需要根据 Runner 配置启用相应权限；也可改用 rootless BuildKit、Kaniko 或组织批准的构建服务。

```yaml
stages:
  - check
  - build
  - scan

variables:
  IMAGE_TAG: "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
  DOCKER_BUILDKIT: "1"

dockerfile-check:
  stage: check
  image: docker:cli
  script:
    - docker build --check .

build-image:
  stage: build
  image: docker:cli
  services:
    - name: docker:dind
  before_script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"
  script:
    - docker build --pull --progress=plain -t "$IMAGE_TAG" .
    - docker push "$IMAGE_TAG"

scan-image:
  stage: scan
  image: aquasec/trivy:latest
  script:
    - trivy image --severity HIGH,CRITICAL "$IMAGE_TAG"
```

生产化时要进一步处理：

- 固定 CI 工具镜像版本，不直接依赖 `latest`。
- 使用 BuildKit Registry cache，减少依赖重新下载。
- 把 `$CI_COMMIT_SHA`、镜像 digest、构建器版本和扫描结果作为制品或流水线证据保存。
- 不在日志中打印 Registry 密码、Secret mount 内容或完整环境变量。
- 对 Docker-in-Docker 的 privileged 权限、宿主机隔离和 Runner 归属做安全评审。

### 14.3 前端构建参数

```yaml
build-frontend:
  stage: build
  script:
    - docker build
        --build-arg VITE_API_BASE_URL="$VITE_API_BASE_URL"
        -t "$IMAGE_TAG" .
    - docker push "$IMAGE_TAG"
```

只有非敏感、确实需要在编译期固化的值才通过 `--build-arg` 传入。前端静态资源中的公开 API 地址与服务端密码要严格区分；公开配置也要经过代码评审，避免把误称为“配置”的 Secret 编译进浏览器可下载的 JS。

### 14.4 无 Docker Daemon 的构建

如果 Runner 不允许访问 Docker socket 或 privileged Docker-in-Docker，可评估：

- BuildKit rootless/buildkitd。
- Kaniko 等用户空间构建器。
- 云端构建服务或组织统一的构建平台。

不同构建器对 Dockerfile 指令、缓存、Secret、平台和输出的支持不完全相同。迁移前至少用同一 Dockerfile 构建、推送并对比镜像 digest、入口、文件清单和运行结果。仓库已有 [Kaniko-容器镜像构建工具](Kaniko-容器镜像构建工具.md) 和 [Docker 镜像构建流程详解](Docker镜像构建流程.md) 可供对照。

---

## 15. 与 Kubernetes 交付的边界

Dockerfile 只负责产出镜像。Kubernetes 或 GitOps 系统还要负责：

- `image` 使用 tag 还是 digest。
- `imagePullSecrets`、Registry 网络和仓库权限。
- 容器端口、Service、Ingress/Gateway 和探针。
- ConfigMap/Secret 的运行时配置。
- 资源请求/限制、滚动策略、PDB、HPA 和回滚。

一个常见误区是：镜像构建成功后，只修改 Deployment 的 ConfigMap 就期待已编译前端变量变化。若变量在 `npm run build`、`vite build` 或其他编译步骤中被固化，必须重新构建并推送镜像，再部署新镜像。

最小交付核对顺序：

```bash
kubectl -n <namespace> get deploy <deployment> -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'
kubectl -n <namespace> get pods -l app=<app> -o wide
kubectl -n <namespace> logs deploy/<deployment> --tail=200
kubectl -n <namespace> describe pod <pod>
```

这些命令只能说明清单、Pod 和日志状态；还要从实际入口发起请求，检查响应体、Content-Type、应用日志和依赖落点。若由 Argo CD 或其他 GitOps 系统管理，生产变更应回到声明仓库，避免手工修改被回滚。

---

## 16. 常见问题排查

### 16.1 `COPY failed` / `file not found`

**已确认方向：** 文件不在构建上下文，或被 `.dockerignore` 排除了。

```bash
docker build -f docker/Dockerfile -t example/app:debug .
sed -n '1,200p' .dockerignore
```

检查 Dockerfile 所在目录与上下文最后一个参数，不要把宿主机路径当作可直接 `COPY` 的来源。确认大小写：Linux 构建环境区分 `App.py` 与 `app.py`。

### 16.2 `no such file or directory` 但文件看起来存在

可能是：

- `WORKDIR` 与预期不同。
- 多阶段 `COPY --from` 的源路径错误。
- 脚本使用了镜像中不存在的解释器、shell 或动态库。
- Windows 换行符导致 shebang 失败。

```bash
docker build --target build -t example/app:debug .
docker run --rm -it --entrypoint /bin/sh example/app:debug
```

### 16.3 `exec format error`

通常表示镜像架构与运行节点不匹配，或二进制是为另一平台编译的。

```bash
docker image inspect example/app:dev \
  --format '{{.Os}}/{{.Architecture}}'
docker buildx imagetools inspect registry.example.com/team/app:${GIT_SHA}
```

确认构建 `--platform`、交叉编译参数、基础镜像平台和运行节点架构。不要只在 Apple Silicon 本机验证后就推送给 amd64 生产节点。

### 16.4 构建很慢或缓存完全失效

检查顺序：

1. 上下文是否包含 `node_modules`、`.git`、构建产物或大压缩包。
2. 是否把 `COPY . .` 放在依赖安装前。
3. 基础镜像是否经常更新，CI 是否每次都使用 `--no-cache`。
4. BuildKit cache 是否导出到可复用的 Registry/CI 后端。
5. 包管理器缓存目录是否正确挂载，且没有把缓存误当作构建必需品。

### 16.5 Secret 出现在 history 或扫描结果

不要尝试通过追加一条 `RUN rm` 来补救；旧层仍可能保留内容。处理步骤：

1. 立即撤销并轮换已暴露凭据。
2. 从 Dockerfile、上下文、CI 日志和镜像标签中移除来源。
3. 用 `RUN --mount=type=secret`/`type=ssh` 重新构建。
4. 删除或隔离受污染的镜像 tag，重新扫描并确认新 digest。
5. 按组织流程记录泄露范围和审计结果。

### 16.6 容器启动后立即退出

```bash
docker ps -a --filter name=example-app-test
docker logs example-app-test
docker inspect example-app-test --format '{{json .State}}'
```

常见原因：

- `CMD`/`ENTRYPOINT` 写错或使用了不存在的路径。
- shell 脚本没有执行权限或 shebang 不存在。
- 应用读取了不存在的配置文件。
- 非 root 用户无权访问配置、证书或写入目录。
- 主进程启动后立即完成，容器没有前台进程。

### 16.7 健康检查失败但进程是 Up

这是正常的“进程存活”和“服务可用”不一致。分别检查：

- 应用实际监听地址是否为 `0.0.0.0:<port>`。
- 健康检查 URL、路径、协议和认证是否正确。
- `start-period` 是否覆盖启动迁移时间。
- 镜像中是否存在 `curl`、Python 或健康检查依赖。
- 容器内访问 `127.0.0.1` 与宿主机映射端口是否被混淆。

### 16.8 推送成功但部署拉取失败

检查：

- Registry 仓库路径和 tag 是否完全一致。
- 运行环境是否配置正确的 `imagePullSecrets`/凭据。
- 节点到 Registry 的 DNS、TLS、代理和防火墙。
- 镜像是否包含目标平台 manifest。
- Registry 是否因保留策略清理了 tag。

不要把 `docker push` 返回成功当作所有节点都能拉取；至少在目标网络和目标架构环境验证一次。

---

## 17. 上线前检查清单

### Dockerfile 和上下文

- [ ] `FROM` 版本、来源和 digest 已记录。
- [ ] `WORKDIR` 是明确的绝对路径。
- [ ] 依赖清单在源码前复制，缓存顺序合理。
- [ ] `.dockerignore` 排除了 `.git`、依赖缓存、构建产物、`.env`、私钥和日志。
- [ ] 没有通过 `ADD` 隐式下载未知远程内容。
- [ ] `ARG`/`ENV`/构建日志中没有密码、Token、私钥。
- [ ] 最终阶段不包含编译器、源码副本和测试工具（确有需要时有说明）。

### 运行时和安全

- [ ] 使用非 root 用户，且读写目录权限已验证。
- [ ] `ENTRYPOINT`/`CMD` 使用 exec 形式，停止信号行为已验证。
- [ ] 应用监听地址、容器端口和 `EXPOSE` 一致。
- [ ] 健康检查路径和启动窗口已验证，避免把外部依赖作为唯一存活检查。
- [ ] 基础镜像和应用依赖已扫描，高危漏洞有处理结论。
- [ ] 构建 Secret 使用 BuildKit mount，不进入镜像层。

### 发布和验收

- [ ] `docker build --check` 通过。
- [ ] 冷缓存构建可以成功，增量构建缓存符合预期。
- [ ] `docker run` 后进程、日志、健康检查和真实请求均通过。
- [ ] 镜像用 Git SHA 或 digest 标识，未只依赖 `latest`。
- [ ] Registry 推送、拉取、平台 manifest 和扫描结果已确认。
- [ ] 部署系统引用的新镜像已在目标环境实际生效。
- [ ] 已保存 Dockerfile、构建器、基础镜像、镜像 digest 和验证证据。

---

## 18. 延伸阅读

- [Dockerfile reference（Docker 官方）](https://docs.docker.com/reference/dockerfile)
- [Build context（Docker 官方）](https://docs.docker.com/build/concepts/context/)
- [Multi-stage builds（Docker 官方）](https://docs.docker.com/build/building/multi-stage/)
- [Optimize cache usage in builds（Docker 官方）](https://docs.docker.com/build/cache/optimize/)
- [Build secrets（Docker 官方）](https://docs.docker.com/build/building/secrets/)
- [Build checks（Docker 官方）](https://docs.docker.com/build/checks/)
- [Docker 镜像构建流程详解](Docker镜像构建流程.md)
- [Docker Build 从入门到高级](../容器编排/Docker-Build从入门到高级.md)
- [Kaniko-容器镜像构建工具](Kaniko-容器镜像构建工具.md)

---

## 文档验证边界

- 已完成：根据 Docker 官方 Dockerfile、Build context、Multi-stage、Cache、Secrets 和 Build checks 文档整理概念与示例，并对本文件做 Markdown 围栏、链接和差异空白检查。
- 未执行：真实 Docker Engine/BuildKit 构建、Registry 登录和推送、漏洞扫描、跨架构构建、Kubernetes 部署及业务请求。
- 落地前：请替换镜像仓库、版本、端口、应用命令、运行用户、Secret 管理方式和目标平台，并在隔离环境完成第 12 节验收。
