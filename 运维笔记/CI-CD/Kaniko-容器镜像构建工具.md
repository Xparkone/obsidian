# Kaniko：无 Docker Daemon 的容器镜像构建指南

> 维护状态基线：原 `GoogleContainerTools/kaniko` 已于 2025-06 归档；本文同时说明社区维护分支 `osscontainertools/kaniko`<br>
> 社区分支验证基线：`v1.28.3`<br>
> 资料截止日期：2026-08-21<br>
> 适用范围：Kubernetes、GitLab CI、Jenkins、Harbor、私有 Registry、离线和受限构建环境

---

## 1. 先讲结论

Kaniko 是一个在容器或 Kubernetes Pod 内，根据 Dockerfile 构建并推送 OCI/Docker 镜像的工具。它不依赖 Docker Daemon，也不需要挂载 `docker.sock`，因此曾广泛用于 Kubernetes CI Runner。

但新项目不能再简单地把 Google Kaniko 当成默认方案：

1. 原官方仓库 `GoogleContainerTools/kaniko` 已于 2025 年 6 月归档，最后版本为 `v1.24.0`，不会继续获得上游修复。
2. GitLab 已删除原 Kaniko 使用指南，并建议改用 Docker、Buildah 或 Podman。
3. 社区项目 `osscontainertools/kaniko` 接续维护，提供新的镜像和安全修复；它与原 Google 项目不是同一个发布主体。
4. 新系统应优先评估 BuildKit、Buildah 或 Podman；存量系统可以测试社区分支，或者制定迁移计划。
5. 不挂载 `docker.sock` 只消除了一个高风险入口，不代表可以安全执行任意不受信任的 Dockerfile。
6. Kaniko 不保证始终能以非 root 用户运行；实际权限取决于基础镜像解包和 Dockerfile 指令。
7. 构建器镜像应固定版本，生产环境最好固定 Digest，不能长期使用 `latest`。
8. Registry 凭据应通过 Secret、短期 Token 或工作负载身份注入。
9. 私有 CA 应正确挂载，不能把 `--skip-tls-verify` 当作生产配置。
10. 发布应记录镜像 Digest，并让后续扫描、签名、晋级和部署都引用该 Digest。

本文既是使用手册，也是存量 Kaniko 系统的维护和迁移指南。

---

## 2. 项目维护状态

### 2.1 原 Google 项目

原地址：

```text
https://github.com/GoogleContainerTools/kaniko
```

当前状态：

- GitHub 仓库已经归档；
- 最后发布版本为 `v1.24.0`；
- 历史镜像位于 `gcr.io/kaniko-project/executor`；
- 归档版本不会继续获得新的漏洞、兼容性和依赖更新。

旧 Pipeline 仍能拉取镜像，不代表它仍适合作为长期生产基线。

### 2.2 社区维护分支

社区维护地址：

```text
https://github.com/osscontainertools/kaniko
```

公开镜像：

```text
ghcr.io/osscontainertools/kaniko
```

该分支声明继续更新依赖、修复安全问题和 Bug，并改进性能。截至本文资料日期，最新 Release 为 `v1.28.3`。

采用社区分支前，团队应评估：

- 维护者和发布流程；
- 镜像签名和来源；
- CVE 响应速度；
- 与 Google `v1.24.0` 的兼容性；
- Feature Flag 的稳定性；
- 企业支持和合规要求。

### 2.3 选型建议

| 场景 | 建议 |
|---|---|
| 新建 GitLab CI 构建平台 | 优先评估 BuildKit、Buildah 或 Podman |
| 已有大量 Kaniko Pipeline | 先盘点旧版本，再测试社区分支或迁移 |
| 禁止 Docker Socket 和特权容器 | 对比 Rootless BuildKit、Buildah 与社区 Kaniko |
| 只构建 Java 或 Go 应用 | 同时评估 Jib、ko |
| 必须获得厂商支持 | 选择有明确支持合同的方案 |
| 继续使用归档 Google 镜像 | 仅限明确接受风险的存量场景 |

---

## 3. Kaniko 解决什么问题

### 3.1 Docker Socket 构建风险

一些早期 Kubernetes Runner 会挂载：

```yaml
volumeMounts:
  - name: docker-sock
    mountPath: /var/run/docker.sock
```

拥有 Docker Socket 访问权限通常等价于能控制宿主机 Docker Daemon，构建任务可能：

- 挂载宿主机目录；
- 启动特权容器；
- 读取其他容器信息；
- 影响同一节点上的工作负载；
- 获得接近宿主机 root 的能力。

Kaniko 不需要该 Socket。

### 3.2 典型流程

```text
构建上下文 + Dockerfile
          │
          ▼
  Kaniko Executor 容器
          │
          ├── 拉取并解包基础镜像
          ├── 执行 Dockerfile 指令
          ├── 对文件系统进行快照
          ├── 生成镜像层和 Manifest
          └── 推送 Registry 或输出 Tar/OCI Layout
```

### 3.3 适用场景

- Kubernetes 原生 CI Runner；
- 不允许挂载 Docker Socket 的环境；
- 需要直接把结果推送到 Registry；
- 需要兼容 Dockerfile 和多阶段构建；
- 短期内无法迁移的稳定 Kaniko 流水线。

### 3.4 不适合的场景

- 大量依赖 BuildKit `RUN --mount` 等高级语法；
- 希望一次构建原生输出完整多平台 Manifest List；
- 执行不可信 Dockerfile，但没有额外沙箱；
- 依赖 Docker Daemon 的本地镜像缓存或插件；
- 组织不接受社区分支的支持模型。

---

## 4. 工作原理

### 4.1 基础镜像解包

Kaniko 根据 `FROM` 拉取基础镜像，并把镜像层解包到自身容器的文件系统视图中。它不是启动嵌套容器执行每条 `RUN`。

因此：

- Executor 文件系统会参与构建执行环境；
- 不建议把 Executor 二进制随意复制进自制镜像运行；
- 基础镜像的文件权限会影响 Kaniko 所需权限。

### 4.2 Dockerfile 指令

```text
FROM          拉取并解包基础镜像
ARG / ENV     更新构建参数和环境
WORKDIR       切换工作目录
COPY / ADD    把上下文文件加入文件系统
RUN           在当前文件系统执行命令
USER          改变后续命令的用户
CMD           写入镜像配置
ENTRYPOINT    写入镜像配置
```

### 4.3 文件系统快照

Kaniko 检测指令执行后的文件系统变化并生成镜像层：

| 模式 | 比较内容 | 特点 |
|---|---|---|
| `full` | 文件内容和元数据 | 最稳健，通常最慢 |
| `redo` | mtime、大小、权限、UID、GID 等 | 较快，准确性低于 full |
| `time` | 主要依赖 mtime | 最快，但最容易漏变化 |

生产默认优先 `full`。只有验证镜像内容正确后才考虑 `redo`；`time` 需要充分理解 mtime 限制。

### 4.4 推送

构建完成后 Kaniko 会：

1. 生成 Layer Blob；
2. 生成 Image Config；
3. 生成 Manifest；
4. 向 Registry 上传缺失 Blob；
5. 推送目标 Tag；
6. 可选地将 Digest 写入文件。

---

## 5. 安全边界与运行权限

### 5.1 无 Daemon 不等于无风险

Dockerfile 中的 `RUN` 会执行项目提供的命令。恶意构建仍可能：

- 读取 Pod 中挂载的 Registry 凭据；
- 访问云元数据服务；
- 扫描集群网络；
- 消耗 CPU、内存和临时磁盘；
- 向外部地址发送源码或秘密；
- 利用运行时或内核漏洞。

Kaniko 依赖容器运行时和 Kubernetes 提供隔离，本身不是完整安全沙箱。

### 5.2 是否需要 root

准确说法是：Kaniko 不要求 Docker Daemon，也通常不要求特权容器，但不保证所有构建都能以非 root 用户完成。

最低权限取决于：

- 解包基础镜像需要创建的文件、UID 和 GID；
- Dockerfile 是否以 root 运行包管理器；
- 是否需要 `chown`、修改权限或写系统目录；
- 目标基础镜像的用户设计。

只有基础镜像和 Dockerfile 都允许时，才能稳定使用非 root Executor。

### 5.3 Kubernetes 隔离建议

- 使用独立 Namespace、ServiceAccount 和节点池；
- 不需要访问 Kubernetes API 时设置 `automountServiceAccountToken: false`；
- 使用 NetworkPolicy 限制代码源、依赖源和 Registry；
- 不挂载宿主机目录和运行时 Socket；
- 禁止 `privileged: true`；
- 设置 CPU、内存和 Ephemeral Storage 限额；
- 对不可信构建使用 gVisor、Kata Containers 或独立集群；
- Registry 凭据仅允许推送指定 Repository；
- 构建结束删除 Pod 和临时凭据。

---

## 6. 镜像版本选择

### 6.1 社区分支

普通 Executor：

```text
ghcr.io/osscontainertools/kaniko:v1.28.3
```

带 BusyBox Shell 的调试镜像：

```text
ghcr.io/osscontainertools/kaniko:debug
```

生产应从 Release 页面确认标签，并固定 Digest：

```yaml
image: ghcr.io/osscontainertools/kaniko:v1.28.3@sha256:<经过验证的摘要>
```

尖括号内容是占位符，不能原样执行。

### 6.2 原 Google 镜像

```text
gcr.io/kaniko-project/executor:v1.24.0
gcr.io/kaniko-project/executor:v1.24.0-debug
```

它们属于归档项目，不应因为旧 Pipeline 仍能拉取就忽略安全和兼容风险。

### 6.3 普通与 Debug 镜像

| 镜像 | Shell | 适用场景 |
|---|---:|---|
| 普通 Executor | 无 | Kubernetes Job、直接使用 Args |
| Debug | `/busybox/sh` | GitLab CI Shell、临时诊断 |

普通 Executor 基于极简镜像，不能假设存在 `sh`、`bash`、`cat` 或 `cp`。

---

## 7. 快速使用

### 7.1 在 Docker 中运行

Docker 只负责启动 Kaniko 容器，Kaniko 不连接 Docker Socket：

```bash
docker run --rm \
  -v "$PWD:/workspace:ro" \
  -v "$HOME/.docker/config.json:/kaniko/.docker/config.json:ro" \
  ghcr.io/osscontainertools/kaniko:v1.28.3 \
  --context=dir:///workspace \
  --dockerfile=/workspace/Dockerfile \
  --destination=registry.example.com/team/app:v1.0.0
```

不要挂载：

```text
/var/run/docker.sock
```

### 7.2 推荐参数

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --dockerfile=/workspace/Dockerfile \
  --destination=registry.example.com/team/app:v1.0.0 \
  --cache=true \
  --cache-repo=registry.example.com/team/app-cache \
  --cache-copy-layers=true \
  --digest-file=/workspace/image-digest.txt \
  --push-retry=3 \
  --log-format=json \
  --log-timestamp=true
```

### 7.3 多个 Tag

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --destination=registry.example.com/team/app:1.4.2 \
  --destination=registry.example.com/team/app:git-abc1234
```

不要让多个并发任务无控制地覆盖同一个可变 Tag。

---

## 8. 构建上下文

### 8.1 常见来源

| 来源 | 示例 |
|---|---|
| 容器内目录 | `dir:///workspace` |
| 本地压缩 Tar | `tar:///workspace/context.tar.gz` |
| 标准输入 | `tar://stdin` |
| Git | `git://github.com/org/repo.git#refs/heads/main#<commit>` |
| GCS | `gs://bucket/context.tar.gz` |
| S3 | `s3://bucket/context.tar.gz` |
| Azure Blob | `https://account.blob.core.windows.net/container/context.tar.gz` |

实际支持范围以所选分支当前文档为准。

### 8.2 Kubernetes 中提供 Context

- CI Runner 挂载工作目录；
- Init Container 克隆代码到 `emptyDir`；
- 使用 PVC；
- 从对象存储下载固定 Tarball；
- 通过标准输入传入 `tar.gz`。

### 8.3 Git Context

```bash
--context='git://github.com/example/app.git#refs/heads/main#<commit-id>'
```

生产应固定 Commit。私有仓库 Token 不要写进 URL，因为 URL 可能进入日志。通常让 CI 先检出代码，再使用 `dir://` 更易审计。

### 8.4 Monorepo

```bash
--context=git://github.com/example/monorepo.git
--context-sub-path=services/api
```

如果 Dockerfile 需要仓库其他目录，Context 不能缩得过小。

### 8.5 `.dockerignore`

```dockerignore
.git
.gitlab-ci.yml
.github
node_modules
dist
tmp
*.log
.env
*.key
*.pem
terraform.tfstate*
```

缩小 Context 可以降低扫描时间、临时磁盘和秘密误入镜像的风险。

---

## 9. Registry 认证

### 9.1 Docker Config Secret

Kaniko 默认读取：

```text
/kaniko/.docker/config.json
```

创建 Kubernetes Secret 的示意命令：

```bash
kubectl -n image-build create secret docker-registry registry-push \
  --docker-server=registry.example.com \
  --docker-username='<registry-user>' \
  --docker-password='<从安全输入提供>'
```

命令参数可能进入 Shell 历史，生产更推荐 External Secrets、工作负载身份或受控 Secret 管理。

挂载：

```yaml
volumes:
  - name: registry-auth
    secret:
      secretName: registry-push
      items:
        - key: .dockerconfigjson
          path: config.json

volumeMounts:
  - name: registry-auth
    mountPath: /kaniko/.docker
    readOnly: true
```

### 9.2 最小权限

构建凭据只应拥有：

- 拉取允许的基础镜像；
- 查询目标 Repository；
- 上传 Blob 和推送指定 Manifest；
- 使用远程缓存时访问缓存 Repository。

不应授予 Registry 全局管理员或任意删除权限。

### 9.3 短期身份

云 Registry 优先使用：

- Kubernetes Workload Identity；
- OIDC 联邦；
- IAM Role for Service Account；
- 临时 Token；
- Registry Credential Helper。

### 9.4 Build Arg 不是秘密通道

不要这样传密码：

```bash
--build-arg=PASSWORD=<secret>
```

Build Arg 可能进入日志、镜像配置或缓存。需要 Secret Mount 时，应确认所选社区版本确实支持，或者改用 BuildKit。

---

## 10. TLS、私有 CA 与 mTLS

### 10.1 私有 CA

```bash
--registry-certificate=registry.example.com=/kaniko/certs/registry-ca.crt
```

也可以根据镜像约定把 CA 挂到 Kaniko 信任目录。不同分支的目录可能变化，部署前应验证。

### 10.2 mTLS

```bash
--registry-client-cert=registry.example.com=/kaniko/mtls/client.crt,/kaniko/mtls/client.key
```

私钥必须来自只读 Secret，并限制 Pod 可见范围。

### 10.3 不安全参数

```text
--skip-tls-verify
--skip-tls-verify-pull
--skip-tls-verify-registry
--insecure
--insecure-pull
--insecure-registry
```

这些参数只适合隔离测试。生产应修复 CA、证书域名、证书链和 Registry 配置。

---

## 11. 缓存机制

### 11.1 远程缓存

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --destination=registry.example.com/team/app:v1.0.0 \
  --cache=true \
  --cache-repo=registry.example.com/team/app-cache \
  --cache-run-layers=true \
  --cache-copy-layers=true \
  --cache-ttl=168h
```

生产中显式指定 Cache Repository，更容易授权、审计和清理。

### 11.2 缓存 Miss

原 Google 实现中，一个 Stage 出现缓存 Miss 后，后续层可能不再继续查询远程缓存，而是本地构建。社区分支可能通过 Feature Flag 改善此行为，但不能把新分支参数套到归档版本。

### 11.3 Base Image 缓存

```bash
docker run --rm \
  -v "$PWD/cache:/cache" \
  ghcr.io/osscontainertools/kaniko:warmer \
  --cache-dir=/cache \
  --image=alpine:3.22
```

构建时：

```bash
--cache=true
--cache-dir=/cache
```

本地 Base Image 缓存通常是预热后只读使用。共享 PVC 要考虑并发、污染和清理。

### 11.4 内存不足

```bash
--compressed-caching=false
```

它可能降低压缩缓存的内存占用，但会增加时间和 I/O。先确认确实是 OOM：

```bash
kubectl -n image-build describe pod <pod-name>
kubectl -n image-build get pod <pod-name> \
  -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
```

### 11.5 缓存安全

- 不把秘密写入 Layer 后再删除；
- 不同信任域不共享缓存；
- 设置缓存生命周期和容量限制；
- 升级构建器后评估缓存兼容性；
- 缓存命中仍要执行扫描。

---

## 12. Dockerfile 编写建议

### 12.1 多阶段构建

```dockerfile
FROM golang:1.25-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/app ./cmd/app

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=builder /out/app /app
USER nonroot:nonroot
ENTRYPOINT ["/app"]
```

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --dockerfile=/workspace/Dockerfile \
  --destination=registry.example.com/team/app:v1.0.0 \
  --skip-unused-stages=true
```

### 12.2 缓存友好顺序

```dockerfile
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build
```

普通源码变化不会让依赖安装层必然失效。

### 12.3 固定基础镜像

```dockerfile
FROM alpine:3.22@sha256:<已验证的摘要>
```

固定后还需要自动升级和漏洞修复，不能永久不更新。

### 12.4 可重复构建

```bash
--reproducible
```

它会移除部分时间戳信息，但不保证所有构建得到相同 Digest。包仓库、下载内容、随机性、编译器、基础镜像和缓存都会影响结果。

### 12.5 BuildKit 语法

不同 Kaniko 分支对 `RUN --mount` 的支持不同。如果 Dockerfile 大量依赖：

```dockerfile
RUN --mount=type=cache ...
RUN --mount=type=secret ...
RUN --mount=type=ssh ...
```

优先评估 BuildKit，避免维护两套语义不同的 Dockerfile。

---

## 13. Kubernetes Job 完整示例

下面假设 CI 已把代码放到名为 `build-context` 的 PVC：

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: kaniko-build-app-v1-0-0
  namespace: image-build
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600
  template:
    metadata:
      labels:
        app.kubernetes.io/name: kaniko-build
    spec:
      restartPolicy: Never
      automountServiceAccountToken: false
      securityContext:
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: kaniko
          image: ghcr.io/osscontainertools/kaniko:v1.28.3
          args:
            - --context=dir:///workspace
            - --dockerfile=/workspace/Dockerfile
            - --destination=registry.example.com/team/app:v1.0.0
            - --destination=registry.example.com/team/app:git-abc1234
            - --cache=true
            - --cache-repo=registry.example.com/team/app-cache
            - --cache-copy-layers=true
            - --digest-file=/dev/termination-log
            - --push-retry=3
            - --log-format=json
            - --log-timestamp=true
            - --registry-certificate=registry.example.com=/kaniko/certs/ca.crt
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          resources:
            requests:
              cpu: "1"
              memory: 2Gi
              ephemeral-storage: 4Gi
            limits:
              cpu: "4"
              memory: 8Gi
              ephemeral-storage: 20Gi
          volumeMounts:
            - name: context
              mountPath: /workspace
              readOnly: true
            - name: registry-auth
              mountPath: /kaniko/.docker
              readOnly: true
            - name: registry-ca
              mountPath: /kaniko/certs
              readOnly: true
      volumes:
        - name: context
          persistentVolumeClaim:
            claimName: build-context
        - name: registry-auth
          secret:
            secretName: registry-push
            items:
              - key: .dockerconfigjson
                path: config.json
        - name: registry-ca
          configMap:
            name: registry-ca
```

### 13.1 关于 `runAsNonRoot`

不要未经验证就设置：

```yaml
runAsNonRoot: true
```

应先检查基础镜像、Dockerfile 的 `USER` 和 `RUN`、文件所有权，再在测试环境固定 UID/GID。

### 13.2 获取 Digest

```bash
kubectl -n image-build get pod <pod-name> \
  -o jsonpath='{.status.containerStatuses[0].state.terminated.message}'
```

后续应使用：

```text
registry.example.com/team/app@sha256:...
```

---

## 14. GitLab CI

GitLab 官方已经移除 Kaniko 指南。下面仅适用于团队明确选择社区分支的场景。

```yaml
stages:
  - build

build-image:
  stage: build
  image:
    name: ghcr.io/osscontainertools/kaniko:debug
    entrypoint: [""]
  variables:
    IMAGE_TAG: "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}"
  script:
    - >-
      /kaniko/executor
      --context=dir://${CI_PROJECT_DIR}
      --dockerfile=${CI_PROJECT_DIR}/Dockerfile
      --destination=${IMAGE_TAG}
      --cache=true
      --cache-repo=${CI_REGISTRY_IMAGE}/cache
      --cache-copy-layers=true
      --digest-file=${CI_PROJECT_DIR}/image-digest.txt
      --push-retry=3
      --log-format=json
      --log-timestamp=true
  artifacts:
    paths:
      - image-digest.txt
    expire_in: 1 day
  rules:
    - if: '$CI_COMMIT_BRANCH'
```

注意：

- 示例使用浮动 `debug` 便于阅读，生产必须改成经过验证的 Digest；
- GitLab Runner 是否自动提供可用 Registry 认证，取决于 Executor 和配置；
- 不要在 YAML 中拼接并打印含密码的 JSON；
- 先构建 Commit Tag，通过扫描和审批后再按 Digest 晋级生产；
- 构建 Job 不应直接持有生产 Registry 写权限。

---

## 15. Jenkins 与 Tekton

### 15.1 Jenkins Kubernetes Agent

概念示例：

```groovy
pipeline {
  agent {
    kubernetes {
      yaml '''
apiVersion: v1
kind: Pod
spec:
  automountServiceAccountToken: false
  containers:
    - name: kaniko
      image: ghcr.io/osscontainertools/kaniko:debug
      command: ["/busybox/sh", "-c"]
      args: ["sleep 3600"]
      volumeMounts:
        - name: registry-auth
          mountPath: /kaniko/.docker
          readOnly: true
  volumes:
    - name: registry-auth
      secret:
        secretName: registry-push
'''
    }
  }
  stages {
    stage('Build') {
      steps {
        container('kaniko') {
          sh '''
            /kaniko/executor \
              --context=dir://${WORKSPACE} \
              --dockerfile=${WORKSPACE}/Dockerfile \
              --destination=registry.example.com/team/app:${GIT_COMMIT} \
              --cache=true \
              --cache-repo=registry.example.com/team/app-cache
          '''
        }
      }
    }
  }
}
```

Jenkins Kubernetes Plugin 的 Command/Args 行为需要在目标版本验证。

### 15.2 Tekton Result

```bash
--digest-file=/tekton/results/IMAGE_DIGEST
```

不同 Tekton 版本对 Result 路径和大小限制不同，应按集群版本核对。

---

## 16. 多架构镜像

### 16.1 `--custom-platform` 不是模拟器

```bash
--custom-platform=linux/arm64
```

它不等于 QEMU 或虚拟机，不能让 amd64 节点任意执行 arm64 二进制。

可靠流程：

```text
amd64 Runner → app:commit-amd64
arm64 Runner → app:commit-arm64
              ↓
       合并 OCI Index
              ↓
          app:commit
```

### 16.2 分架构构建

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --custom-platform=linux/amd64 \
  --destination=registry.example.com/team/app:${GIT_SHA}-amd64
```

在 arm64 原生 Runner：

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --custom-platform=linux/arm64 \
  --destination=registry.example.com/team/app:${GIT_SHA}-arm64
```

### 16.3 合并 Manifest

可使用 `manifest-tool`、`docker buildx imagetools create`、`crane index` 或 `regctl index`。

合并后检查：

```bash
skopeo inspect --raw \
  docker://registry.example.com/team/app:${GIT_SHA}
```

确认所有平台和 Digest 正确。

---

## 17. 不推送、Tar 与 OCI Layout

### 17.1 只构建不推送

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --destination=local/app:test \
  --no-push \
  --no-push-cache
```

只设置 `--no-push` 时，如果启用缓存，仍可能推送缓存层。

### 17.2 输出 Tar

```bash
/kaniko/executor \
  --context=dir:///workspace \
  --destination=local/app:test \
  --no-push \
  --no-push-cache \
  --tar-path=/workspace/app.tar
```

`--tar-path` 仍需要 `--destination`。检查：

```bash
skopeo inspect docker-archive:app.tar
```

### 17.3 OCI Layout

```bash
--oci-layout-path=/workspace/oci-layout
```

实际 Manifest 媒体类型可能是 OCI 或 Docker Schema 2，不能只根据目录名判断。

### 17.4 Digest 输出

```text
--digest-file
--image-name-with-digest-file
--image-name-tag-with-digest-file
```

推荐把 `name@digest` 作为后续扫描、签名和部署的输入。

---

## 18. Registry Mirror 与离线环境

### 18.1 Mirror

```bash
--registry-mirror=mirror.example.com
```

严格离线环境增加：

```bash
--skip-default-registry-fallback
```

防止 Mirror 未命中后访问公网。

### 18.2 Registry Map

```bash
--registry-map=docker.io=harbor.example.com/dockerhub
```

适合把公共基础镜像映射到内部仓库。规则和回退行为必须按目标版本验证。

### 18.3 离线准备

1. 用 Skopeo 同步基础镜像；
2. 同步 Kaniko Executor 和 Warmer；
3. 固定所有镜像 Digest；
4. 配置内部 DNS、CA 和 Registry；
5. 禁止公网 Egress；
6. 预热基础镜像缓存；
7. 验证 Dockerfile 不从公网下载；
8. 为语言包仓库配置内部代理。

仅镜像离线不代表构建离线，`apt-get`、`npm install`、`go mod download` 仍可能访问外网。

---

## 19. 性能优化

### 19.1 优先优化 Dockerfile

- 缩小 Context；
- 使用 `.dockerignore`；
- 先复制依赖清单，再复制源码；
- 合理拆分稳定层和易变层；
- 使用多阶段构建；
- 使用内部依赖代理；
- 避免重复下载不变大文件。

### 19.2 可测试的参数

```text
--cache=true
--cache-copy-layers=true
--cache-ttl=168h
--snapshot-mode=redo
--skip-unused-stages=true
--compressed-caching=false
```

每次只改变一项，并比较构建时间、资源峰值、Registry 流量、镜像内容和缓存命中。

### 19.3 临时磁盘

基础镜像、上下文、展开文件、缓存和 Tar 都占用 Ephemeral Storage：

```bash
kubectl -n image-build describe pod <pod-name>
kubectl describe node <node-name>
```

发生驱逐或 `no space left on device` 时，同时检查 Context 和镜像层是否异常膨胀。

---

## 20. 镜像供应链

Kaniko 只完成构建，不自动完成全部供应链控制：

```text
固定源码 Commit
   ↓
固定构建器和基础镜像
   ↓
Kaniko 构建并输出 Digest
   ↓
漏洞、恶意软件和 Secret 扫描
   ↓
生成 SBOM 和 Provenance
   ↓
签名
   ↓
按 Digest 晋级
   ↓
部署准入验证
```

### 20.1 不可变 Tag

```bash
--push-ignore-immutable-tag-errors=true
```

只有在多个并发构建推送同一不可变 Tag，且任一成功都可接受时才使用。更推荐每个 Commit 使用唯一 Tag。

### 20.2 构建器自身

构建器镜像本身也要：

- 固定 Digest；
- 扫描漏洞；
- 验证签名或来源；
- 控制升级；
- 记录版本。

---

## 21. 日志与观测

### 21.1 日志

```bash
--verbosity=info
--log-format=json
--log-timestamp=true
```

排障时临时使用 `debug`。避免长期使用 `trace`，它会产生大量日志并增加敏感信息暴露风险。

### 21.2 应监控

- 构建成功率；
- P50/P95 时长；
- 排队时间；
- Registry Push 失败率；
- OOM 和磁盘驱逐；
- CPU、内存和流量；
- 构建器版本分布；
- 未固定 Digest 的 Pipeline；
- 缓存命中变化。

### 21.3 社区分支遥测

社区分支提供 OpenTelemetry 能力。启用前应检查当前 Release 文档，并防止 Dockerfile、凭据或敏感标签进入外部 Collector。

---

## 22. 常见故障排查

### 22.1 `UNAUTHORIZED` / `DENIED`

检查：

- `config.json` 挂载路径；
- Registry Host 是否完全匹配；
- Token 是否过期；
- 是否有目标 Repository Push 权限；
- Cache Repository 是否另需权限；
- Registry 是否要求项目预先存在。

不要输出 Secret 内容。

### 22.2 `x509: certificate signed by unknown authority`

常见原因：

- 企业根 CA 未挂载；
- 中间证书缺失；
- 证书域名不匹配；
- 证书过期；
- Flag 或路径错误。

修复 CA 信任，不要长期跳过 TLS。

### 22.3 Push 权限检查失败

检查 DNS、NetworkPolicy、代理、Registry `/v2/`、Token Scope、Repository 名称和限流。

`--skip-push-permission-check` 只改变检查时机，不能赋予权限。

### 22.4 OOMKilled

```bash
kubectl -n image-build get pod <pod-name> \
  -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
```

可尝试：

- 提高 Memory Limit；
- 缩小 Context；
- 多阶段构建；
- `--compressed-caching=false`；
- 降低编译并行度；
- 使用更小基础镜像。

### 22.5 缓存未命中

可能原因：

- Build Arg 或 Dockerfile 改变；
- `COPY` 输入或 mtime 改变；
- Cache TTL 到期；
- Cache Repository 改变；
- 某层 Miss 后不再查询；
- Kaniko 版本或 Feature Flag 改变缓存 Key。

### 22.6 镜像缺文件

停止发布，重新使用：

```bash
--snapshot-mode=full
--cache=false
```

对比缓存与无缓存构建，重点检查 mtime、忽略路径、挂载点和多阶段 `COPY --from`。

### 22.7 Exec Format Error

通常是节点和执行二进制架构不匹配。`--custom-platform` 不是模拟器，应使用对应架构 Runner 或明确配置的 QEMU/BuildKit。

### 22.8 Debug 镜像找不到 Shell

社区 Debug 镜像 Shell 通常是：

```text
/busybox/sh
```

普通 Executor 没有 Shell，也不要假设存在 `/bin/bash`。

### 22.9 平台错误

```bash
skopeo inspect --raw \
  docker://registry.example.com/team/app:<tag>
```

确认是单平台 Manifest 还是 OCI Index，并核对 Architecture/OS。

---

## 23. 与其他工具对比

| 工具 | Docker Daemon | Rootless/非特权能力 | 主要特点 |
|---|---:|---:|---|
| 社区 Kaniko | 不需要 | 取决于基础镜像和 Dockerfile | 容器内快照构建，适合存量 K8s CI |
| BuildKit | 不要求 Docker Engine，可独立运行 | 支持 Rootless，但有环境要求 | 高级缓存、多平台、Secret/SSH Mount |
| Buildah | 不需要 | 支持 Rootless，但受存储驱动影响 | Dockerfile 和命令式 OCI 构建 |
| Podman | 不需要 Docker Daemon | 支持 Rootless | 运行和构建，兼顾 Docker CLI 习惯 |
| Docker Buildx | 通常连接 BuildKit | 取决于 Builder | 开发体验好，多平台成熟 |
| Jib | 不需要 | 一般不需要特权 | Java 项目，不依赖 Dockerfile |
| ko | 不需要 | 一般不需要特权 | Go 应用构建和发布 |

“是否 Rootless”还要检查内核 User Namespace、运行时、存储驱动、基础镜像、Dockerfile 和 Kubernetes 策略。

---

## 24. 从 Kaniko 迁移

### 24.1 盘点

```text
Kaniko 镜像版本
Runner 和 CPU 架构
Dockerfile 特性
Registry 认证和 CA
远程缓存
Build Arg
多架构流程
Digest 输出
扫描、签名和晋级
```

### 24.2 BuildKit 语义映射

| Kaniko | BuildKit / Buildx |
|---|---|
| `--context` | `docker buildx build <context>` |
| `--dockerfile` | `-f` |
| `--destination` | `--tag` 和 `--push` |
| `--cache-repo` | `--cache-from` / `--cache-to` |
| `--build-arg` | `--build-arg` |
| `--target` | `--target` |
| `--custom-platform` | `--platform` |
| `--digest-file` | Metadata File / Registry Digest |

不是所有参数一一对应。

### 24.3 双轨验证

1. 同一 Commit 用两种构建器构建；
2. 使用不同临时 Tag；
3. 比较 Config、Manifest 和文件系统；
4. 运行集成测试和扫描；
5. 比较缓存和性能；
6. 验证多架构；
7. 小范围切流；
8. 保留回退窗口；
9. 最后回收旧缓存和凭据。

不同构建器产生不同 Digest 很常见，目标是运行语义和安全属性一致。

---

## 25. 生产流程

### 25.1 构建前

- 固定源码 Commit；
- 固定 Kaniko 镜像和 Digest；
- 固定基础镜像 Digest；
- 验证 Registry CA；
- 获取短期身份；
- 检查 Context 不含秘密；
- 设置资源、超时和网络限制。

### 25.2 构建中

- 使用唯一 Commit Tag；
- 输出 Digest；
- 不打印凭据；
- 不挂 Docker Socket；
- 不使用 Privileged Pod；
- 使用受控缓存；
- 对不可信代码增加沙箱。

### 25.3 构建后

- 按 Digest 检查镜像；
- 执行漏洞、恶意软件和 Secret 扫描；
- 生成 SBOM 和 Provenance；
- 签名；
- 使用 Skopeo 按 Digest 晋级；
- 在目标运行时拉取和启动验证；
- 清理 Pod、临时 Token 和过期缓存。

---

## 26. 参数速查

### 26.1 输入和输出

```text
--context
--context-sub-path
--dockerfile
--destination
--tar-path
--oci-layout-path
--digest-file
--image-name-with-digest-file
--image-name-tag-with-digest-file
```

### 26.2 构建

```text
--build-arg
--target
--custom-platform
--label
--reproducible
--single-snapshot
--snapshot-mode
--skip-unused-stages
--ignore-path
```

### 26.3 缓存

```text
--cache
--cache-repo
--cache-dir
--cache-run-layers
--cache-copy-layers
--cache-ttl
--compressed-caching
--no-push-cache
```

### 26.4 Registry

```text
--push-retry
--registry-certificate
--registry-client-cert
--registry-map
--registry-mirror
--skip-default-registry-fallback
--push-ignore-immutable-tag-errors
```

### 26.5 查看实际 Help

```bash
docker run --rm \
  ghcr.io/osscontainertools/kaniko:v1.28.3 \
  --help
```

原 Google 版和社区分支参数不同，必须以所用镜像的 Help 为准。

---

## 27. 上线检查清单

### 27.1 维护状态

- [ ] 已确认使用归档版还是社区分支；
- [ ] 已完成维护者和许可证评估；
- [ ] 构建器固定版本和 Digest；
- [ ] 已订阅 Release 和安全公告；
- [ ] 已制定迁移方案。

### 27.2 安全

- [ ] 未挂 Docker Socket；
- [ ] Pod 非 Privileged；
- [ ] 禁止权限提升并删除多余 Capability；
- [ ] ServiceAccount Token 非必要不挂载；
- [ ] Registry 凭据最小权限且短期有效；
- [ ] 没有通过 Build Arg 传秘密；
- [ ] 使用可信 CA，没有跳过 TLS；
- [ ] NetworkPolicy 限制 Egress；
- [ ] 不可信构建有额外沙箱。

### 27.3 可追踪

- [ ] 源码固定 Commit；
- [ ] 基础镜像固定 Digest；
- [ ] 保存构建结果 Digest；
- [ ] Release Tag 不可变；
- [ ] 已生成 SBOM 和 Provenance；
- [ ] 已完成扫描和签名；
- [ ] 部署按 Digest 或不可变 Tag。

### 27.4 稳定性

- [ ] CPU、内存和临时磁盘合理；
- [ ] Cache Repository 有生命周期；
- [ ] Push 有有限重试；
- [ ] 构建有超时；
- [ ] 多架构使用合适 Runner 并验证 Manifest；
- [ ] 目标运行时已完成拉取和启动验证。

---

## 28. 官方与主要资料

- [原 Google Kaniko 仓库（已归档）](https://github.com/GoogleContainerTools/kaniko)
- [原 Google Kaniko Releases](https://github.com/GoogleContainerTools/kaniko/releases)
- [osscontainertools Kaniko 社区维护分支](https://github.com/osscontainertools/kaniko)
- [osscontainertools Kaniko Releases](https://github.com/osscontainertools/kaniko/releases)
- [GitLab 已移除的 Kaniko 指南与替代建议](https://docs.gitlab.com/ci/docker/using_kaniko/)
- [OCI Image Specification](https://github.com/opencontainers/image-spec)
- [BuildKit 官方仓库](https://github.com/moby/buildkit)
- [Buildah 官方仓库](https://github.com/containers/buildah)

实际部署时，以选定 Kaniko 分支和具体 Release 的 README、Release Notes、镜像签名及 `--help` 为最终依据，不能混用原 Google 版本和社区分支参数。
