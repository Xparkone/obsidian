# Kaniko — 无需 Docker Daemon 的容器镜像构建工具

## 概述

Kaniko 是 Google 开源的容器镜像构建工具，最大的特点是 **不需要 Docker Daemon（守护进程）**，也不需要 root 权限。它可以在容器内、Kubernetes 集群中、CI/CD 流水线里直接构建镜像，完全不需要挂载 `docker.sock`。

---

## 一、为什么需要 Kaniko

### Docker 构建的痛点

```
传统 Docker 构建：
  需要 Docker Daemon 运行
      │
      ▼
  挂载 docker.sock 到容器 → 安全风险（相当于 root 权限）
      │
      ▼
  需要 root 权限 → CI/CD 环境的噩梦
```

### Kaniko 的解决方案

```
Kaniko 构建：
  不需要 Docker Daemon
      │
      ▼
  在用户空间执行，不需要 root 权限
      │
      ▼
  完全在容器内运行 → 安全、干净
```

### 典型场景

| 场景 | 说明 |
|------|------|
| **Kubernetes 中构建镜像** | 不用挂载 docker.sock，Pod 里直接跑 |
| **CI/CD 流水线** | GitLab CI / GitHub Actions / Jenkins 中安全构建 |
| **无特权容器环境** | 不允许 root、不允许 Docker 的环境 |
| **Google Cloud Build** | 底层就是 Kaniko 在跑 |

---

## 二、工作原理

Kaniko 不依赖 Docker Daemon，而是**自己实现了 Dockerfile 的解析和执行**：

```
Dockerfile
    │
    ▼
Kaniko 逐行解析每条指令
    │
    ├── FROM           → 拉取基础镜像层到本地
    ├── RUN            → 在用户空间执行命令，对比文件系统快照，生成新层
    ├── COPY / ADD     → 复制文件，生成新层
    ├── ENV / WORKDIR  → 修改镜像元数据
    └── CMD / ENTRYPOINT
    │
    ▼
推送镜像到 Registry（支持 Docker Hub / GCR / ECR / Harbor 等）
```

### 关键实现

- **文件系统快照**：执行每条 `RUN` 指令前后，对比文件系统的变化，只把变化打包成新层
- **不依赖 Daemon**：完全在用户空间执行，不需要 Docker socket
- **分层构建**：和 Docker 一样，利用镜像层缓存加速构建

---

## 三、快速上手

### 3.1 最简单的用法

```bash
# 拉取 Kaniko 执行器镜像
docker run \
  -v $(pwd):/workspace \
  -v ~/.docker/config.json:/kaniko/.docker/config.json:ro \
  gcr.io/kaniko-project/executor:latest \
  --context=/workspace \
  --dockerfile=/workspace/Dockerfile \
  --destination=myregistry.com/myimage:latest
```

### 3.2 参数说明

| 参数 | 必需 | 说明 |
|------|:--:|------|
| `--context` | ✅ | 构建上下文路径（Dockerfile 所在目录） |
| `--dockerfile` | ❌ | Dockerfile 路径，默认 `{context}/Dockerfile` |
| `--destination` | ✅ | 推送目标镜像（可多次指定，推多个） |
| `--no-push` | ❌ | 只构建不推送，用于本地测试 |
| `--cache` | ❌ | 开启缓存（`--cache=true`） |
| `--cache-repo` | ❌ | 缓存存放的镜像仓库 |
| `--build-arg` | ❌ | 构建参数（可多次使用） |
| `--target` | ❌ | 多阶段构建的目标阶段 |
| `--skip-tls-verify` | ❌ | 跳过 TLS 验证（自签名 Registry 用） |
| `--verbosity` | ❌ | 日志级别：panic/fatal/error/warn/info/debug/trace |

---

## 四、典型用法

### 4.1 推送到 Docker Hub

```bash
# 1. 创建认证文件
echo '{"auths":{"https://index.docker.io/v1/":{"auth":"'$(echo -n "username:password" | base64)'"}}}' \
  > /kaniko/.docker/config.json

# 2. 构建并推送
/kaniko/executor \
  --context=/workspace \
  --destination=myusername/myapp:latest
```

### 4.2 推送到私有 Harbor

```bash
# 跳过 TLS 验证（自签名证书）
/kaniko/executor \
  --context=/workspace \
  --destination=harbor.example.com/project/myapp:v1.0 \
  --skip-tls-verify
```

### 4.3 推送到阿里云 ACR

```bash
# 用 --build-arg 传递参数
/kaniko/executor \
  --context=/workspace \
  --build-arg=ENV=production \
  --build-arg=VERSION=1.0.0 \
  --destination=registry.cn-hangzhou.aliyuncs.com/ns/myapp:latest
```

### 4.4 多阶段构建

```dockerfile
# Dockerfile（多阶段）
FROM golang:1.21 AS builder
WORKDIR /app
COPY . .
RUN go build -o myapp .

FROM alpine:3.19
COPY --from=builder /app/myapp /usr/local/bin/myapp
CMD ["myapp"]
```

```bash
# Kaniko 自动支持多阶段构建，无需额外配置
/kaniko/executor \
  --context=/workspace \
  --destination=myregistry.com/myapp:latest
```

### 4.5 使用缓存加速

```bash
# 将缓存层推送到 Registry，下次构建复用
/kaniko/executor \
  --context=/workspace \
  --destination=myregistry.com/myapp:latest \
  --cache=true \
  --cache-repo=myregistry.com/myapp-cache
```

---

## 五、在 Kubernetes 中构建

### 5.1 Pod 定义

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: kaniko-build
spec:
  containers:
  - name: kaniko
    image: gcr.io/kaniko-project/executor:latest
    args:
    - "--context=git://github.com/myorg/myapp.git"
    - "--destination=myregistry.com/myapp:latest"
    volumeMounts:
    - name: kaniko-secret
      mountPath: /kaniko/.docker
  restartPolicy: Never
  volumes:
  - name: kaniko-secret
    secret:
      secretName: registry-credentials
      items:
      - key: .dockerconfigjson
        path: config.json
```

### 5.2 创建 Registry 凭据

```bash
kubectl create secret docker-registry registry-credentials \
  --docker-server=myregistry.com \
  --docker-username=admin \
  --docker-password=***bash
```

### 5.3 从 Git 仓库直接构建

```yaml
args:
  - "--context=git://github.com/myorg/myapp.git"
  - "--destination=myregistry.com/myapp:latest"
```

Kaniko 会自动 `git clone` 仓库，然后用里面的 Dockerfile 构建。

---

## 六、在 CI/CD 中使用

### 6.1 GitLab CI

```yaml
# .gitlab-ci.yml
build:
  stage: build
  image:
    name: gcr.io/kaniko-project/executor:debug
    entrypoint: [""]
  script:
    - echo "{\"auths\":{\"$CI_REGISTRY\":{\"auth\":\"$(printf %s:$CI_REGISTRY_PASSWORD | base64)\"}}}" > /kaniko/.docker/config.json
    - /kaniko/executor
        --context $CI_PROJECT_DIR
        --dockerfile $CI_PROJECT_DIR/Dockerfile
        --destination $CI_REGISTRY_IMAGE:$CI_COMMIT_TAG
```

### 6.2 GitHub Actions

```yaml
# .github/workflows/build.yml
name: Build and Push
on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4

    - name: Build with Kaniko
      uses: aevea/action-kaniko@master
      with:
        image: myusername/myapp
        tag: ${{ github.sha }}
        registry: docker.io
        username: ${{ secrets.DOCKER_USERNAME }}
        password: ${{ secrets.DOCKER_PASSWORD }}
```

### 6.3 Jenkins

```groovy
pipeline {
  agent any
  stages {
    stage('Build Image') {
      agent {
        kubernetes {
          yaml '''
            apiVersion: v1
            kind: Pod
            spec:
              containers:
              - name: kaniko
                image: gcr.io/kaniko-project/executor:debug
                command: ["sleep"]
                args: ["infinity"]
                volumeMounts:
                - name: docker-config
                  mountPath: /kaniko/.docker
              volumes:
              - name: docker-config
                secret:
                  secretName: docker-credentials
          '''
        }
      }
      steps {
        container('kaniko') {
          sh '''
            /kaniko/executor \
              --context=git://github.com/myorg/myapp.git \
              --destination=myregistry.com/myapp:latest
          '''
        }
      }
    }
  }
}
```

---

## 七、调试模式

```bash
# 使用 debug 镜像（内置 busybox shell）
docker run -it --entrypoint /busybox/sh gcr.io/kaniko-project/execator:debug

# 开启 trace 级别日志
/kaniko/executor \
  --context=/workspace \
  --destination=myimage:latest \
  --verbosity=trace

# 只构建不推送，用于本地测试
/kaniko/executor \
  --context=/workspace \
  --no-push \
  --tar-path=/workspace/image.tar

# 构建后保存为 tar 文件
docker load < image.tar   # 用 Docker 加载
```

---

## 八、Kaniko vs 其他方案

| 方案 | 是否需要 Docker Daemon | 是否需要 root | 适用场景 |
|------|:--:|:--:|------|
| **Docker CLI** | ✅ 需要 | ✅ 需要 | 本地开发、有 Docker 的环境 |
| **Kaniko** | ❌ 不需要 | ❌ 不需要 | CI/CD、K8s、无特权环境 |
| **Buildah** | ❌ 不需要 | ❌ 不需要 | 本地开发、rootless 构建 |
| **BuildKit** | ✅ 需要 Daemon | ❌ 可 rootless | 本地加速构建 |
| **Jib** | ❌ 不需要 | ❌ 不需要 | Java 项目专用 |
| **ko** | ❌ 不需要 | ❌ 不需要 | Go 项目专用 |

---

## 九、常见问题

**Q: Kaniko 构建速度比 Docker 慢吗？**
> 首次构建差不多。Kaniko 支持缓存（`--cache` + `--cache-repo`），命中缓存后速度接近 Docker。

**Q: 支持 `docker build --build-arg` 吗？**
> 支持。`/kaniko/executor --build-arg=KEY=VALUE`，可多次使用。

**Q: 支持 `.dockerignore` 吗？**
> 支持。构建上下文中的 `.dockerignore` 自动生效。

**Q: 支持多架构镜像吗？**
> 不直接支持。需要分别构建不同架构，再用 `docker manifest` 合并。或用 `--custom-platform` 参数。

**Q: 镜像名称能用环境变量吗？**
> 不能直接在参数中展开。需要先赋值给 shell 变量再传入。

**Q: 能在 Docker 容器中跑 Kaniko 吗？**
> 可以，这就是最常见的用法：`docker run gcr.io/kaniko-project/executor ...`

---

## 十、总结

```
Kaniko 的核心价值：
  ✅ 不需要 Docker Daemon
  ✅ 不需要 root 权限
  ✅ 完全在容器内运行
  ✅ 支持标准 Dockerfile
  ✅ 支持多阶段构建
  ✅ 支持缓存加速

适用场景：
  CI/CD 流水线 · Kubernetes 集群 · 无特权环境 · 安全受限环境
```

---

*文档创建时间：2026-07-02*