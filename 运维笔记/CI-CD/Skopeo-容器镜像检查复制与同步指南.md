# Skopeo：容器镜像检查、复制与同步指南

> 验证基线：Skopeo `v1.23.0`  
> 资料截止日期：2026-08-21  
> 适用范围：Docker Registry HTTP API V2、OCI 镜像、Harbor、Docker Hub、Quay、GitLab Container Registry、云厂商镜像仓库和离线环境

---

## 1. 文档概述

### 1.1 先讲结论

Skopeo 是一个面向容器镜像和镜像仓库的命令行工具。它最有价值的能力是：**不启动 Docker Daemon，也不先把镜像拉到本地，就能检查、复制、同步和删除远程镜像**。

生产使用时应记住以下原则：

1. Skopeo 负责操作已有镜像，不负责读取 Dockerfile 构建镜像。
2. Registry 镜像引用必须带 `docker://` Transport，例如 `docker://registry.example.com/team/app:v1`。
3. 多架构镜像迁移通常必须使用 `--all`，否则默认可能只复制当前机器匹配的平台镜像。
4. Tag 可以移动，Digest 才能标识确定的 Manifest；发布和迁移应记录并校验 Digest。
5. 登录优先使用 `--password-stdin` 或独立 Authfile，不要把密码写在命令参数、脚本和流水线日志中。
6. 私有 CA 应正确安装到信任目录，不要长期使用 `--tls-verify=false`。
7. `skopeo delete` 可能删除由多个 Tag 共同引用的 Manifest，必须先检查 Digest 和 Registry 行为。
8. `docker-archive`、`oci-archive`、`dir` 和 `oci` 不是同一种格式，离线迁移前要确认目标运行时支持什么格式。
9. Registry 之间复制后应比较源、目标 Digest，并验证多架构 Manifest 是否完整。
10. 大规模同步先执行 `--dry-run`，再使用固定镜像清单、重试、审计和失败报告。

### 1.2 适用读者

本文适合：

- DevOps、平台工程师和 SRE；
- 负责 Harbor、GitLab Registry、Docker Hub 或云厂商 Registry 的管理员；
- 需要构建离线镜像仓库的人；
- 需要在国内外 Registry、开发和生产 Registry 之间同步镜像的团队；
- 需要在 CI/CD 中执行镜像晋级、校验和复制的人员。

阅读完成后，应能够：

- 理解 Skopeo 的无 Daemon 工作方式；
- 正确使用不同 Transport；
- 检查远程镜像配置、Manifest、Digest 和 Tag；
- 安全登录多个 Registry；
- 复制单架构和多架构镜像；
- 制作 Docker Archive、OCI Archive 和离线镜像目录；
- 批量同步镜像；
- 在 CI/CD 中完成镜像晋级；
- 排查认证、TLS、Manifest、Digest 和存储问题。

### 1.3 版本基线

本文以 Skopeo `v1.23.0` 为功能基线。该版本于 2026-05-26 发布，包含：

- `--require-signed` 全局选项；
- `--tls-details`；
- `copy --multi-arch`；
- 更完善的重试和同步行为；
- 容器配置文件查找行为调整。

Linux 发行版的软件仓库可能提供更旧版本。使用本文中的新参数前，应检查：

```bash
skopeo --version
skopeo copy --help
skopeo sync --help
```

生产环境不要假设不同发行版中的 Skopeo 功能完全一致。

---

## 2. Skopeo 是什么

Skopeo 基于 `containers/image` 库，可以直接与远程 Registry 或本地镜像存储交互。

它可以：

- 检查远程镜像，不下载完整镜像层；
- 查看镜像 Digest、架构、创建时间、标签和环境变量；
- 获取原始 Manifest 或镜像配置；
- 列出 Repository 中的所有 Tag；
- 在两个 Registry 之间直接复制镜像；
- 在 Docker Schema 与 OCI 格式之间按目标能力转换；
- 复制完整多架构镜像；
- 将镜像保存为目录、OCI Layout 或 Archive；
- 从离线目录恢复到内部 Registry；
- 批量同步 Repository 或 YAML 清单；
- 删除远程 Registry 中的镜像 Manifest；
- 配合 `policy.json`、Sigstore 或 Simple Signing 执行信任检查。

Skopeo 大多数操作：

- 不需要 Docker Daemon；
- 不需要 containerd；
- 不需要把镜像导入本地主机镜像缓存；
- 不需要 root。

例外：访问 `docker-daemon:` 或某些 `containers-storage:` 后端时，仍可能需要本地运行时、Socket 或相应权限。

---

## 3. Skopeo 不是什么

### 3.1 不是镜像构建工具

Skopeo 不解析 Dockerfile，也不执行：

```bash
RUN apt-get update
COPY . /app
```

构建镜像应使用：

- Docker BuildKit；
- Buildah；
- BuildKit/`buildctl`；
- Kaniko；
- Buildpacks；
- 云厂商构建服务。

### 3.2 不是容器运行时

Skopeo 不启动容器，也不替代：

- Docker Engine；
- containerd；
- CRI-O；
- Podman；
- Kubernetes。

### 3.3 不是通用 OCI Artifact 工具

Skopeo 的重点是容器镜像。对于 Helm Chart、SBOM、签名附件和任意 OCI Artifact，还应评估：

- ORAS；
- Cosign；
- Registry 自带复制能力；
- `crane`；
- `regctl`。

Skopeo 的签名能力基于 containers/image 的信任与签名体系，不能简单等同于所有 Cosign/OCI Referrers 工作流。

---

## 4. 工作原理

### 4.1 Registry 到 Registry

```text
┌──────────────────────┐
│ Source Registry      │
│ Manifest + Blobs     │
└──────────┬───────────┘
           │ Registry HTTP API V2
           ▼
┌──────────────────────┐
│ Skopeo               │
│ 读取 Manifest         │
│ 流式读取和写入 Layer   │
│ 必要时转换格式         │
└──────────┬───────────┘
           │ Registry HTTP API V2
           ▼
┌──────────────────────┐
│ Destination Registry │
│ Manifest + Blobs     │
└──────────────────────┘
```

复制过程中不需要先执行：

```bash
docker pull
docker tag
docker push
```

### 4.2 远程检查

```text
skopeo inspect
      │
      ├── 请求 Manifest
      ├── 请求 Image Config
      └── 返回 JSON
```

相比 `docker inspect`：

- `docker inspect` 通常检查本地 Docker Daemon 中已经存在的镜像；
- `skopeo inspect` 可以直接检查远程 Registry 中的镜像。

### 4.3 层复用

目标 Registry 如果已经存在相同 Digest 的 Blob，通常不需要重复上传全部内容。实际是否复用由 Registry 实现、Repository 挂载能力、权限和 Skopeo 参数共同决定。

---

## 5. 镜像、Tag、Digest 与多架构 Manifest

### 5.1 Tag

Tag 是可读名称，例如：

```text
registry.example.com/team/api:v1.4.2
registry.example.com/team/api:latest
```

Tag 可以被重新指向其他 Manifest。因此：

```text
api:latest 今天的内容 ≠ api:latest 明天的内容
```

### 5.2 Digest

Digest 是内容寻址标识，例如：

```text
registry.example.com/team/api@sha256:<DIGEST>
```

Digest 可用于：

- 锁定部署内容；
- 校验复制前后是否一致；
- 生成审计记录；
- 避免 Tag 漂移；
- 配合镜像签名和准入策略。

### 5.3 单架构镜像

单架构镜像通常包含：

```text
Manifest
├── Image Config
└── Layers
```

### 5.4 多架构镜像

多架构镜像通常包含 Manifest List 或 OCI Image Index：

```text
Image Index / Manifest List
├── linux/amd64 Manifest
├── linux/arm64 Manifest
└── linux/arm/v7 Manifest
```

不使用 `--all` 时，Skopeo 可能只选择与当前主机 OS/架构匹配的实例。

对于 Kubernetes 混合架构集群，遗漏 ARM64 或其他平台会导致：

```text
no matching manifest for linux/arm64
```

---

## 6. Transport：Skopeo 最关键的语法

Skopeo 使用以下通用格式引用镜像：

```text
transport:details
```

常用 Transport：

| Transport | 示例 | 用途 |
|---|---|---|
| `docker://` | `docker://registry.example.com/team/app:v1` | Docker Registry HTTP API V2 |
| `dir:` | `dir:/data/app` | 非标准展开目录，适合检查和调试 |
| `oci:` | `oci:/data/app:v1` | OCI Image Layout 目录 |
| `oci-archive:` | `oci-archive:/data/app.tar:v1` | OCI Layout Tar Archive |
| `docker-archive:` | `docker-archive:/data/app.tar:app:v1` | `docker save` 兼容 Archive |
| `docker-daemon:` | `docker-daemon:app:v1` | 本地 Docker Daemon 镜像存储 |
| `containers-storage:` | `containers-storage:app:v1` | Podman、Buildah、CRI-O 使用的存储 |

### 6.1 Registry 引用必须写 `docker://`

正确：

```bash
skopeo inspect docker://docker.io/library/alpine:3.20
```

错误：

```bash
skopeo inspect docker.io/library/alpine:3.20
```

### 6.2 总是写完整镜像名

推荐：

```text
docker.io/library/nginx:1.27
```

不要在自动化流程中依赖短名称：

```text
nginx:1.27
```

完整名称可以避免不同主机的 `registries.conf` 搜索顺序导致拉取不同 Registry。

### 6.3 Archive 格式不能混用

```text
docker-archive  通常用于 docker load
oci-archive     符合 OCI Image Layout Archive
dir             Skopeo 调试目录，不是 OCI Layout
oci             标准 OCI Image Layout 目录
```

保存前先确认离线环境的 Docker、Podman、containerd、CRI-O 或 Registry 支持哪种导入方式。

---

## 7. 与相关工具对比

| 工具 | 主要用途 | 是否需要 Daemon | 是否构建镜像 |
|---|---|:---:|:---:|
| Skopeo | 检查、复制、同步、删除镜像 | 否 | 否 |
| Docker CLI | 构建、运行、推拉和管理镜像 | 通常需要 Docker Daemon | 是 |
| Podman | 构建、运行和管理容器 | 否 | 是 |
| Buildah | 构建 OCI/Docker 镜像 | 否 | 是 |
| Kaniko | 在容器/CI 中构建并推送镜像 | 否 | 是 |
| Crane | Registry 镜像操作 | 否 | 否 |
| ORAS | 通用 OCI Artifact 推拉 | 否 | 否 |
| Cosign | 镜像和 Artifact 签名验证 | 否 | 否 |

典型流水线：

```text
BuildKit / Buildah / Kaniko 构建镜像
                │
                ▼
Trivy 等扫描镜像
                │
                ▼
Cosign 或签名系统签名
                │
                ▼
Skopeo 按 Digest 晋级到生产 Registry
                │
                ▼
Kubernetes 按 Digest 部署
```

---

## 8. 安装

### 8.1 Ubuntu 20.10 及更新版本

```bash
sudo apt-get update
sudo apt-get install -y skopeo
```

验证：

```bash
skopeo --version
```

发行版仓库中的版本可能落后于上游 `v1.23.0`。如果命令不支持本文参数，以本机 `--help` 为准。

### 8.2 Debian

```bash
sudo apt-get update
sudo apt-get install -y skopeo
```

### 8.3 RHEL、CentOS Stream、Fedora

```bash
sudo dnf install -y skopeo
```

### 8.4 Alpine

```bash
sudo apk add skopeo
```

### 8.5 macOS

```bash
brew install skopeo
```

### 8.6 使用容器镜像

官方提供：

```text
quay.io/skopeo/stable
```

示例：

```bash
podman run --rm \
  quay.io/skopeo/stable:latest \
  copy --help
```

生产流水线应将容器镜像固定到经过验证的 Tag 或 Digest，不要长期依赖 `latest`。

---

## 9. 快速开始

### 9.1 检查远程镜像

```bash
skopeo inspect \
  docker://docker.io/library/alpine:3.20
```

### 9.2 查看 Digest

```bash
skopeo inspect \
  --format '{{.Digest}}' \
  docker://docker.io/library/alpine:3.20
```

### 9.3 复制镜像到私有仓库

```bash
skopeo copy \
  docker://docker.io/library/alpine:3.20 \
  docker://registry.example.com/base/alpine:3.20
```

### 9.4 复制完整多架构镜像

```bash
skopeo copy --all \
  docker://docker.io/library/alpine:3.20 \
  docker://registry.example.com/base/alpine:3.20
```

### 9.5 保存为 Docker Archive

```bash
skopeo copy \
  docker://docker.io/library/alpine:3.20 \
  docker-archive:/tmp/alpine-3.20.tar:alpine:3.20

docker load -i /tmp/alpine-3.20.tar
```

---

## 10. 检查镜像：`skopeo inspect`

### 10.1 默认输出

```bash
skopeo inspect \
  docker://docker.io/library/nginx:1.27
```

常见字段：

| 字段 | 说明 |
|---|---|
| `Name` | 规范化镜像名称 |
| `Digest` | 顶层 Manifest Digest |
| `RepoTags` | Repository 中的 Tag 列表 |
| `Created` | 镜像创建时间 |
| `Architecture` | 当前选择的平台架构 |
| `Os` | 操作系统 |
| `Layers` | 层 Digest |
| `LayersData` | 层类型和大小等信息 |
| `Env` | 镜像环境变量 |
| `Labels` | OCI/Docker Label |

默认输出可能为了获取 `RepoTags` 请求整个 Tag 列表。大型 Repository 可使用：

```bash
skopeo inspect --no-tags \
  docker://registry.example.com/team/app:v1
```

### 10.2 只输出需要的字段

```bash
skopeo inspect \
  --format '{{.Digest}} {{.Architecture}}/{{.Os}}' \
  docker://docker.io/library/alpine:3.20
```

输出环境变量：

```bash
skopeo inspect \
  --format '{{range .Env}}{{println .}}{{end}}' \
  docker://docker.io/library/nginx:1.27
```

### 10.3 获取原始 Manifest

```bash
skopeo inspect --raw \
  docker://docker.io/library/alpine:3.20 \
  | jq .
```

原始 Manifest 用于检查：

- `mediaType`；
- OCI Image Index；
- Docker Manifest List；
- 各平台 Manifest Digest；
- Annotation；
- Layer 和 Config 引用。

### 10.4 获取 Image Config

```bash
skopeo inspect --config \
  docker://docker.io/library/nginx:1.27 \
  | jq .
```

可查看：

- Entrypoint；
- Cmd；
- Env；
- WorkingDir；
- User；
- Label；
- RootFS DiffID；
- History。

### 10.5 检查特定平台

```bash
skopeo \
  --override-os linux \
  --override-arch arm64 \
  inspect \
  docker://docker.io/library/alpine:3.20
```

AMD64：

```bash
skopeo \
  --override-os linux \
  --override-arch amd64 \
  inspect \
  docker://docker.io/library/alpine:3.20
```

### 10.6 检查是否为多架构镜像

```bash
skopeo inspect --raw \
  docker://docker.io/library/alpine:3.20 \
  | jq '{mediaType, manifests}'
```

列出平台：

```bash
skopeo inspect --raw \
  docker://docker.io/library/alpine:3.20 \
  | jq -r '.manifests[]? | [.platform.os, .platform.architecture, (.platform.variant // "-")] | @tsv'
```

---

## 11. 列出 Tag：`skopeo list-tags`

Repository 引用不能带 Tag 或 Digest：

```bash
skopeo list-tags \
  docker://docker.io/library/alpine
```

使用 `jq` 排序：

```bash
skopeo list-tags \
  docker://registry.example.com/team/app \
  | jq -r '.Tags[]' \
  | sort -V
```

错误示例：

```bash
skopeo list-tags \
  docker://docker.io/library/alpine:3.20
```

`list-tags` 的目标是 Repository，而不是具体镜像版本。

需要注意：

- 大型 Repository 的 Tag 列表可能很多；
- Registry 可能限制列举权限；
- Tag 列举接口可能分页；
- 返回 Tag 不代表该 Tag 一定符合当前平台；
- 同步前不能只按字符串排序判断最新版。

---

## 12. Registry 认证

### 12.1 交互式登录

```bash
skopeo login registry.example.com
```

### 12.2 使用标准输入传密码

```bash
printf '%s' "$REGISTRY_PASSWORD" \
  | skopeo login \
      --username "$REGISTRY_USERNAME" \
      --password-stdin \
      registry.example.com
```

优点：密码不会作为命令行参数出现在进程列表中。

### 12.3 使用独立 Authfile

```bash
install -m 0600 /dev/null /tmp/skopeo-auth.json

printf '%s' "$REGISTRY_PASSWORD" \
  | skopeo login \
      --authfile /tmp/skopeo-auth.json \
      --username "$REGISTRY_USERNAME" \
      --password-stdin \
      registry.example.com
```

后续使用：

```bash
skopeo inspect \
  --authfile /tmp/skopeo-auth.json \
  docker://registry.example.com/team/app:v1
```

也可以设置：

```bash
export REGISTRY_AUTH_FILE=/tmp/skopeo-auth.json
```

### 12.4 默认凭据位置

Linux 默认主要使用：

```text
${XDG_RUNTIME_DIR}/containers/auth.json
```

该目录通常随用户会话变化，不适合假设凭据永久存在。自动化任务应显式传递 `--authfile`。

Skopeo 还可能读取 Podman、Buildah 或 Docker 登录产生的兼容凭据，具体顺序以当前 containers/image 文档为准。

### 12.5 源和目标使用不同凭据

```bash
skopeo copy \
  --src-authfile /run/secrets/source-auth.json \
  --dest-authfile /run/secrets/destination-auth.json \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

### 12.6 退出登录

```bash
skopeo logout registry.example.com
```

### 12.7 不推荐的方式

不推荐：

```bash
skopeo copy \
  --src-creds username:plaintext-password \
  ...
```

原因：

- 可能出现在 Shell History；
- 可能出现在进程列表；
- 可能被 CI 日志记录；
- 特殊字符容易产生转义问题。

`--src-creds` 和 `--dest-creds` 适合受控临时场景，生产优先 Authfile 或工作负载身份。

---

## 13. TLS 和私有 CA

### 13.1 推荐方式：安装 CA

对于：

```text
registry.example.com
```

创建：

```text
/etc/containers/certs.d/registry.example.com/ca.crt
```

如果包含端口：

```text
/etc/containers/certs.d/registry.example.com:5000/ca.crt
```

安装示例：

```bash
sudo install -d -m 0755 \
  /etc/containers/certs.d/registry.example.com

sudo install -m 0644 registry-ca.crt \
  /etc/containers/certs.d/registry.example.com/ca.crt
```

验证：

```bash
skopeo inspect \
  docker://registry.example.com/team/app:v1
```

### 13.2 临时指定证书目录

```bash
skopeo inspect \
  --cert-dir /run/registry-certs \
  docker://registry.example.com/team/app:v1
```

复制时区分源和目标：

```bash
skopeo copy \
  --src-cert-dir /run/certs/source \
  --dest-cert-dir /run/certs/destination \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

### 13.3 跳过 TLS 校验

仅限受控实验：

```bash
skopeo inspect \
  --tls-verify=false \
  docker://registry.lab.example.com/app:v1
```

复制时：

```bash
skopeo copy \
  --src-tls-verify=false \
  --dest-tls-verify=false \
  docker://source.lab.example.com/app:v1 \
  docker://destination.lab.example.com/app:v1
```

生产环境使用该参数会失去服务器身份验证，存在中间人攻击风险。正确做法是安装 CA、修复证书 SAN 和完整证书链。

### 13.4 `registries.conf`

系统级配置通常位于：

```text
/etc/containers/registries.conf
/etc/containers/registries.conf.d/*.conf
```

用户级配置位于用户配置目录。Skopeo `v1.23.0` 调整了部分配置文件查找行为，升级后如果镜像源、Mirror 或 Insecure 配置表现变化，应优先检查当前 `containers-config(5)` 和 `registries.conf`。

自动化流程仍建议使用完整 Registry 名称，不依赖短名称搜索和隐式 Mirror。

---

## 14. 复制镜像：`skopeo copy`

### 14.1 Registry 到 Registry

```bash
skopeo copy \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2
```

源名称和目标名称完全独立。目标不会自动继承源 Registry、Namespace、Repository 或 Tag。

### 14.2 带认证复制

```bash
skopeo copy \
  --src-authfile /run/secrets/source-auth.json \
  --dest-authfile /run/secrets/destination-auth.json \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2
```

### 14.3 多架构复制

推荐：

```bash
skopeo copy --all \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2
```

Skopeo `v1.23.0` 也支持：

```bash
skopeo copy \
  --multi-arch all \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2
```

两种写法选择一种即可。迁移多架构镜像时还要检查目标 Registry 是否支持 Manifest List/OCI Index。

### 14.4 只复制当前平台

默认行为通常等价于选择运行 Skopeo 主机匹配的平台。也可以显式指定：

```bash
skopeo \
  --override-os linux \
  --override-arch amd64 \
  copy \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2-amd64
```

### 14.5 重试

```bash
skopeo copy \
  --retry-times 5 \
  --retry-delay 5s \
  --all \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2
```

默认不一定执行重试。跨区域、跨境网络和公共 Registry 应显式设置重试，并让流水线保留最终失败状态。

### 14.6 限制并行层复制

```bash
skopeo copy \
  --image-parallel-copies 3 \
  --all \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2
```

并行度过高可能导致：

- Registry 限流；
- 出口带宽占满；
- NAT 连接数过多；
- 临时目录空间压力；
- 代理连接失败。

### 14.7 记录目标 Digest

```bash
skopeo copy \
  --all \
  --digestfile /tmp/destination-digest.txt \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2

cat /tmp/destination-digest.txt
```

### 14.8 保持 Digest

```bash
skopeo copy \
  --all \
  --preserve-digests \
  docker://source.example.com/team/app:v1.4.2 \
  docker://destination.example.com/release/app:v1.4.2
```

如果目标格式转换、层压缩或 Registry 行为导致 Digest 无法保持，命令会失败。

`--preserve-digests` 不会自动改变复制范围，因此多架构镜像通常还需要 `--all`。

### 14.9 指定目标 Manifest 格式

```bash
skopeo copy \
  --format oci \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

可用格式取决于版本，常见值：

- `oci`；
- `v2s2`；
- `v2s1`。

不要为了兼容旧 Registry 随意降级到 Schema 1。应优先升级 Registry，并评估签名、Digest 和安全影响。

### 14.10 压缩格式

Skopeo 支持按目标能力设置：

```bash
skopeo copy \
  --dest-compress-format zstd \
  --dest-compress-level 10 \
  docker://source.example.com/team/app:v1 \
  oci:/tmp/app:v1
```

压缩格式改变会影响 Layer Digest。目标运行时、Registry 和签名流程必须支持所选格式。

---

## 15. Digest 校验和不可变晋级

### 15.1 复制前记录源 Digest

```bash
SOURCE_IMAGE=docker://source.example.com/team/app:v1.4.2

SOURCE_DIGEST=$(skopeo inspect \
  --format '{{.Digest}}' \
  "$SOURCE_IMAGE")

printf 'source=%s\n' "$SOURCE_DIGEST"
```

### 15.2 按 Digest 读取源镜像

```bash
skopeo copy --all \
  "docker://source.example.com/team/app@${SOURCE_DIGEST}" \
  docker://destination.example.com/release/app:v1.4.2
```

这样可以防止复制过程中源 Tag 被重新推送。

### 15.3 检查目标 Digest

```bash
DESTINATION_DIGEST=$(skopeo inspect \
  --format '{{.Digest}}' \
  docker://destination.example.com/release/app:v1.4.2)

printf 'destination=%s\n' "$DESTINATION_DIGEST"
```

比较：

```bash
test "$SOURCE_DIGEST" = "$DESTINATION_DIGEST"
```

如果不一致，不应立即认定镜像内容遭到篡改。还要检查：

- 是否复制了完整 Manifest List；
- 是否发生格式转换；
- 是否重新压缩 Layer；
- 是否只复制了单个平台；
- 目标 Registry 是否改写 Manifest；
- 是否使用了不同媒体类型。

### 15.4 生产晋级建议

```text
测试 Registry 的不可变 Digest
          │
          ├── 安全扫描通过
          ├── 集成测试通过
          ├── 签名验证通过
          ▼
Skopeo 按 Digest 复制到生产 Registry
          │
          ▼
记录目标 Digest
          │
          ▼
Kubernetes 按 Digest 部署
```

不要仅依赖 `latest`、`stable`、`prod` 等可移动 Tag 证明发布内容。

---

## 16. 本地目录与 Archive

### 16.1 保存为 `dir:`

```bash
mkdir -p /tmp/nginx-dir

skopeo copy \
  docker://docker.io/library/nginx:1.27 \
  dir:/tmp/nginx-dir
```

目录中通常能看到 Manifest、Layer Tar 和签名等文件。

`dir:` 是 containers/image 的非标准展开格式，适合调试，不应当作通用 OCI 交换格式。

### 16.2 保存为 OCI Layout

```bash
skopeo copy \
  docker://docker.io/library/nginx:1.27 \
  oci:/tmp/nginx-oci:1.27
```

检查：

```bash
find /tmp/nginx-oci -maxdepth 2 -type f -print
```

### 16.3 保存为 OCI Archive

```bash
skopeo copy \
  docker://docker.io/library/nginx:1.27 \
  oci-archive:/tmp/nginx-1.27-oci.tar:1.27
```

### 16.4 保存为 Docker Archive

```bash
skopeo copy \
  docker://docker.io/library/nginx:1.27 \
  docker-archive:/tmp/nginx-1.27-docker.tar:nginx:1.27
```

导入 Docker：

```bash
docker load -i /tmp/nginx-1.27-docker.tar
```

### 16.5 从 Archive 推送到 Registry

```bash
skopeo copy \
  docker-archive:/tmp/nginx-1.27-docker.tar:nginx:1.27 \
  docker://registry.internal.example.com/base/nginx:1.27
```

OCI Archive：

```bash
skopeo copy \
  oci-archive:/tmp/nginx-1.27-oci.tar:1.27 \
  docker://registry.internal.example.com/base/nginx:1.27
```

### 16.6 与本地 Docker Daemon 交互

从 Docker Daemon 推送到 Registry：

```bash
skopeo copy \
  docker-daemon:local-app:v1 \
  docker://registry.example.com/team/local-app:v1
```

从 Registry 导入 Docker Daemon：

```bash
skopeo copy \
  docker://registry.example.com/team/app:v1 \
  docker-daemon:team-app:v1
```

此时 Skopeo 不再是完全独立于 Docker Daemon，必须能访问 Docker Socket，并具备相应权限。

### 16.7 与 Podman/Buildah 存储交互

```bash
skopeo copy \
  docker://registry.example.com/team/app:v1 \
  containers-storage:team/app:v1
```

访问本地容器存储可能受到 rootless 用户、Storage Driver 和 Store Path 的影响。

---

## 17. 批量同步：`skopeo sync`

### 17.1 同步 Repository 的全部 Tag

```bash
skopeo sync \
  --src docker \
  --dest docker \
  registry.example.com/team/app \
  mirror.example.com/team
```

源 Repository 未指定 Tag 时，通常会同步所有可见 Tag。大型 Repository 可能产生大量流量和存储，执行前应先获取 Tag 数量并使用 `--dry-run`。

### 17.2 先 Dry Run

```bash
skopeo sync \
  --dry-run \
  --src docker \
  --dest docker \
  registry.example.com/team/app \
  mirror.example.com/team
```

### 17.3 同步多架构镜像

```bash
skopeo sync \
  --all \
  --src docker \
  --dest docker \
  registry.example.com/team/app \
  mirror.example.com/team
```

### 17.4 保留源路径

```bash
skopeo sync \
  --scoped \
  --src docker \
  --dest dir \
  registry.example.com/team/app \
  /media/offline-images
```

`--scoped` 会在目标中加入源 Registry 路径，有助于避免来自不同 Registry 的同名镜像冲突。

### 17.5 Tag 添加后缀

```bash
skopeo sync \
  --append-suffix=-mirror \
  --src docker \
  --dest docker \
  registry.example.com/team/app \
  mirror.example.com/team
```

### 17.6 出错后继续其他镜像

```bash
skopeo sync \
  --keep-going \
  --retry-times 5 \
  --src yaml \
  --dest docker \
  images.yaml \
  mirror.example.com
```

`--keep-going` 会继续处理剩余镜像，但命令最终仍应返回失败，以便流水线发现部分同步失败。

### 17.7 YAML 清单

示例 `images.yaml`：

```yaml
docker.io:
  images:
    library/alpine:
      - "3.20"
    library/nginx:
      - "1.27"
    library/redis:
      - "7.4"

quay.io:
  images:
    prometheus/prometheus:
      - "v3.0.0"
```

执行：

```bash
skopeo sync \
  --all \
  --keep-going \
  --retry-times 5 \
  --src yaml \
  --dest docker \
  images.yaml \
  mirror.example.com
```

不要把用户名和密码写入 YAML 并提交到 Git。使用 `--src-authfile`、`--dest-authfile` 或短期凭据。

### 17.8 按 Tag 正则或语义版本筛选

YAML Source 支持 `images-by-tag-regex` 和 `images-by-semver`。适合从公共仓库筛选一部分版本，但生产清单更推荐显式列出 Tag 或 Digest，避免上游新增 Tag 后同步范围突然变化。

---

## 18. 离线环境镜像迁移

### 18.1 在线区导出

准备 `images.yaml`，先 Dry Run：

```bash
skopeo sync \
  --dry-run \
  --all \
  --src yaml \
  --dest dir \
  images.yaml \
  /media/offline-images
```

正式导出：

```bash
skopeo sync \
  --all \
  --keep-going \
  --retry-times 5 \
  --src yaml \
  --dest dir \
  images.yaml \
  /media/offline-images
```

### 18.2 生成校验文件

```bash
find /media/offline-images -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum \
  > /media/offline-images.sha256
```

把清单、Skopeo 版本和执行日志一起保存：

```bash
skopeo --version > /media/skopeo-version.txt
cp images.yaml /media/images.yaml
```

### 18.3 离线区校验

```bash
sha256sum -c /media/offline-images.sha256
```

### 18.4 导入内部 Registry

```bash
skopeo sync \
  --all \
  --keep-going \
  --retry-times 5 \
  --src dir \
  --dest docker \
  /media/offline-images \
  registry.internal.example.com
```

### 18.5 验收

对每个镜像：

- 检查目标 Tag；
- 检查目标 Digest；
- 检查 Manifest List；
- 在 AMD64 和 ARM64 节点分别拉取；
- 运行安全扫描；
- 验证 Kubernetes 能成功创建 Pod；
- 保存最终映射表。

### 18.6 离线方案的常见问题

- 只导出了当前机器架构；
- 使用 Docker Archive 丢失了多架构索引；
- Registry 中存在同名不同来源镜像；
- 缺少 Pause、CNI、CSI、Ingress 等平台镜像；
- 清单使用 `latest`，重复导出内容发生变化；
- 外部 Chart 或 YAML 仍引用原 Registry；
- 签名、SBOM 和其他 OCI Artifact 没有一并迁移；
- 离线介质没有完整校验和和审计记录。

---

## 19. 删除镜像：`skopeo delete`

### 19.1 基本命令

```bash
skopeo delete \
  docker://registry.example.com/team/app:old-tag
```

### 19.2 重要风险

当前行为可能先把 Tag 解析成 Manifest Digest，再删除对应 Manifest。如果多个 Tag 指向同一个 Digest，删除一个 Tag 可能影响其他 Tag。

删除前执行：

```bash
skopeo inspect \
  --format '{{.Digest}}' \
  docker://registry.example.com/team/app:old-tag

skopeo list-tags \
  docker://registry.example.com/team/app
```

还应通过 Registry API 或管理平台确认哪些 Tag 指向相同 Digest。

### 19.3 Registry 必须支持删除

部分 Registry：

- 不支持删除；
- 默认关闭删除；
- 只标记 Manifest 删除；
- 需要后续 Garbage Collection 才释放磁盘；
- 有保留策略或不可变 Tag；
- 由 Harbor/GitLab 等平台自行管理引用和制品关系。

不要绕过 Harbor、GitLab 等平台的保留、复制、审计和制品管理机制直接批量删除。

### 19.4 生产删除流程

```text
生成候选清单
    │
    ├── 排除生产正在使用的 Digest
    ├── 排除保留 Tag
    ├── 检查共享 Manifest
    ├── 审批
    ▼
先删除测试 Repository 中的候选镜像
    │
    ▼
观察 Registry 和部署影响
    │
    ▼
执行正式删除
    │
    ▼
按 Registry 官方流程执行 GC
```

---

## 20. 签名与信任策略

### 20.1 `policy.json`

默认信任策略位置：

```text
$HOME/.config/containers/policy.json
/etc/containers/policy.json
```

也可以显式指定：

```bash
skopeo \
  --policy /etc/containers/production-policy.json \
  copy \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

`policy.json` 可以按 Transport、Registry、Namespace、Repository 或镜像范围定义：

- 拒绝；
- 无条件接受；
- 要求指定密钥签名；
- 要求 Sigstore 签名；
- 校验签名中的镜像身份。

默认使用 `insecureAcceptAnything` 只能满足兼容性，不代表安全验证。生产策略应由安全团队设计并测试。

### 20.2 强制要求签名

Skopeo `v1.23.0` 支持全局参数：

```bash
skopeo \
  --require-signed \
  copy \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

全局参数必须放在子命令 `copy` 之前。

是否能成功验证还依赖：

- 签名类型；
- `policy.json`；
- `registries.d`；
- 公钥；
- 签名存储位置；
- 镜像身份匹配规则。

### 20.3 复制并签名

Skopeo 支持：

- Simple Signing；
- Sigstore 参数文件；
- Sigstore 私钥；
- Sequoia-PGP 指纹。

示意命令：

```bash
skopeo copy \
  --sign-by-sigstore-private-key /run/secrets/signing-private.key \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

签名密钥不应直接存放在普通 Runner 文件系统。生产应使用短期签名身份、KMS、HSM 或组织批准的密钥管理方式。

### 20.4 Skopeo 与 Cosign

如果组织采用 Cosign、Keyless、Fulcio、Rekor 或 OCI Referrers，应继续以该体系为主。Skopeo 可负责复制镜像，但是否自动保留签名、SBOM 和 Attestation 取决于签名存储模型与 Registry。

迁移前必须验证：

- 签名是否为独立 Tag；
- 是否使用 OCI Referrers；
- 目标 Registry 是否支持；
- 复制镜像时附件是否一并复制；
- 准入控制器能否在目标 Registry 验证。

---

## 21. 在 CI/CD 中使用

### 21.1 GitLab CI 镜像晋级

示例把测试 Registry 中已经构建和验证的镜像复制到生产 Registry：

```yaml
promote-image:
  stage: deploy
  image:
    name: quay.io/skopeo/stable:latest
    entrypoint: [""]
  variables:
    SOURCE_IMAGE: "${CI_REGISTRY_IMAGE}:${CI_COMMIT_SHA}"
    DESTINATION_IMAGE: "registry.prod.example.com/team/app:${CI_COMMIT_SHA}"
  script:
    - >-
      printf '%s' "$CI_REGISTRY_PASSWORD"
      | skopeo login
        --username "$CI_REGISTRY_USER"
        --password-stdin
        "$CI_REGISTRY"
    - >-
      printf '%s' "$PROD_REGISTRY_PASSWORD"
      | skopeo login
        --username "$PROD_REGISTRY_USERNAME"
        --password-stdin
        registry.prod.example.com
    - >-
      skopeo copy
      --all
      --retry-times 5
      "docker://${SOURCE_IMAGE}"
      "docker://${DESTINATION_IMAGE}"
    - >-
      skopeo inspect
      --format '{{.Digest}}'
      "docker://${DESTINATION_IMAGE}"
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

生产中应把 `quay.io/skopeo/stable:latest` 固定到经过验证的 Digest。

### 21.2 按 Digest 晋级

流水线应先读取源 Digest：

```bash
SOURCE_DIGEST=$(skopeo inspect \
  --format '{{.Digest}}' \
  "docker://${SOURCE_IMAGE}")

skopeo copy --all \
  "docker://${SOURCE_REPOSITORY}@${SOURCE_DIGEST}" \
  "docker://${DESTINATION_IMAGE}"
```

将以下信息作为流水线制品保存：

- 源镜像；
- 源 Digest；
- 目标镜像；
- 目标 Digest；
- Skopeo 版本；
- 签名验证结果；
- 扫描报告；
- 操作时间和流水线 ID。

### 21.3 GitHub Actions

可以在 Runner 中安装发行版包，或使用固定版本的 Skopeo 容器。核心步骤仍然是：

```bash
printf '%s' "$SOURCE_PASSWORD" \
  | skopeo login \
      --username "$SOURCE_USERNAME" \
      --password-stdin \
      source.example.com

printf '%s' "$DESTINATION_PASSWORD" \
  | skopeo login \
      --username "$DESTINATION_USERNAME" \
      --password-stdin \
      destination.example.com

skopeo copy --all --retry-times 5 \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

凭据应来自 Secret，不应写入 Workflow 文件。

### 21.4 Kubernetes CronJob 同步

可以将 Docker Config 格式的 Registry Secret 以只读文件挂载，并通过 `--authfile` 使用。

示意：

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: image-mirror
  namespace: registry-ops
spec:
  schedule: "0 2 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: Never
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            runAsGroup: 1000
          containers:
            - name: skopeo
              image: quay.io/skopeo/stable:latest
              args:
                - sync
                - --all
                - --retry-times=5
                - --authfile=/auth/config.json
                - --src=docker
                - --dest=docker
                - source.example.com/team/app
                - destination.example.com/team
              volumeMounts:
                - name: registry-auth
                  mountPath: /auth
                  readOnly: true
          volumes:
            - name: registry-auth
              secret:
                secretName: registry-auth
                items:
                  - key: .dockerconfigjson
                    path: config.json
```

生产应固定镜像 Digest，并配置：

- Resource Requests/Limits；
- NetworkPolicy；
- Job 超时；
- 失败告警；
- 最小 Registry 权限；
- 日志留存；
- 避免多个同步 Job 并发。

---

## 22. 性能与可靠性

### 22.1 临时目录

Skopeo 在某些转换、压缩和 Digest 预计算场景会使用临时目录，默认通常是：

```text
/var/tmp
```

指定：

```bash
skopeo \
  --tmpdir /data/skopeo-tmp \
  copy \
  --all \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

大镜像迁移前检查：

```bash
df -h /var/tmp
df -i /var/tmp
```

### 22.2 预计算 Digest

如果目标 Registry 支持层复用但源 Layer Digest 在压缩前未知，可评估：

```bash
skopeo copy \
  --dest-precompute-digests \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

它可能减少重复上传，但需要临时写入完整 Blob，增加本地磁盘和时间消耗。

### 22.3 网络建议

- 为跨区域复制设置重试；
- 避开业务高峰；
- 限制并行度；
- 使用离源和目标 Registry 都较近的 Runner；
- 监控出口流量和 Registry 限流；
- 公共 Registry 注意 Pull Rate Limit；
- 代理环境检查 `HTTP_PROXY`、`HTTPS_PROXY` 和 `NO_PROXY`；
- 内部 Registry 域名应加入正确的 `NO_PROXY`。

### 22.4 幂等性

按同一 Digest 重复复制通常可以复用已有 Blob，但 Tag 最终指向仍可能变化。

自动化流程应：

1. 获取源 Digest；
2. 检查目标是否已有相同 Digest；
3. 按 Digest 复制；
4. 校验目标 Digest；
5. 记录结果；
6. 失败时可安全重试。

---

## 23. 安全建议

### 23.1 凭据

- 使用 `--password-stdin`；
- Authfile 权限设为 `0600`；
- CI 中使用 Masked/Protected Secret；
- 源 Registry 只给 Pull 权限；
- 目标 Registry 只给指定 Repository Push 权限；
- 删除操作使用独立高权限身份；
- 优先短期 Token 或工作负载身份；
- 任务结束后清理临时 Authfile。

### 23.2 TLS

- 安装私有 CA；
- 证书 SAN 必须包含 Registry 域名；
- 不长期使用 `--tls-verify=false`；
- 不使用 HTTP 传输敏感镜像和凭据；
- 定期检查证书过期时间。

### 23.3 镜像内容

- 按 Digest 晋级；
- 复制前后验证签名；
- 运行漏洞扫描；
- 检查基础镜像来源；
- 记录 SBOM 和 Attestation；
- 使用 Registry 不可变 Tag；
- 生产准入控制只允许受信 Registry 和已验证 Digest。

### 23.4 删除权限

Push 权限和 Delete 权限应分离。日常同步账号不应拥有删除整个 Repository 的能力。

---

## 24. 常见故障排查

### 24.1 `unauthorized` 或 `authentication required`

检查：

```bash
skopeo login --get-login registry.example.com
skopeo inspect \
  --authfile /run/secrets/auth.json \
  docker://registry.example.com/team/app:v1
```

常见原因：

- 登录 Registry 域名和镜像域名不一致；
- Token 过期；
- Authfile 路径错误；
- 源有 Pull 权限但目标没有 Push 权限；
- Repository 尚未创建或禁止自动创建；
- Harbor Project、GitLab Project 路径错误；
- 云厂商临时 Token 已失效。

### 24.2 `x509: certificate signed by unknown authority`

检查：

- CA 是否放到正确目录；
- 目录是否包含端口；
- 文件扩展名是否为 `.crt`；
- 证书链是否完整；
- 运行 Skopeo 的容器是否挂载了 CA；
- Registry 证书 SAN 是否正确。

调试时可临时用 `--tls-verify=false` 验证是否确为证书问题，但不能作为正式修复。

### 24.3 `manifest unknown`

检查：

```bash
skopeo list-tags docker://registry.example.com/team/app
```

常见原因：

- Tag 不存在；
- Repository 路径错误；
- 大小写错误；
- Tag 已被清理；
- Registry 返回权限伪装错误；
- 目标只复制了部分架构；
- Manifest 类型不被目标支持。

### 24.4 ARM64 节点拉取失败

检查：

```bash
skopeo inspect --raw \
  docker://registry.example.com/team/app:v1 \
  | jq -r '.manifests[]? | [.platform.os, .platform.architecture] | @tsv'
```

如果只有 AMD64，重新使用：

```bash
skopeo copy --all \
  docker://source.example.com/team/app:v1 \
  docker://registry.example.com/team/app:v1
```

### 24.5 复制后 Digest 不一致

检查：

- 是否使用 `--all`；
- 源和目标是否都是顶层 Manifest List；
- 是否设置 `--format`；
- 是否重新压缩；
- Registry 是否转换 Manifest；
- 目标 Tag 是否被其他流水线覆盖；
- 是否比较了同一平台层级的 Digest。

### 24.6 `no space left on device`

```bash
df -h /var/tmp
df -i /var/tmp
```

处理：

- 指定更大的 `--tmpdir`；
- 降低并行度；
- 避免不必要的格式转换；
- 清理过期临时文件；
- 检查 Runner EmptyDir 或容器临时存储限制。

### 24.7 `429 Too Many Requests`

处理：

- 使用认证账号；
- 降低并行度；
- 增加重试；
- 使用内部 Mirror；
- 避开高峰；
- 检查 Docker Hub 或云 Registry 配额。

### 24.8 删除后磁盘没有释放

原因通常是：

- 删除只移除了 Manifest；
- Blob 仍被其他 Manifest 引用；
- Registry 尚未运行 Garbage Collection；
- Harbor/GitLab 有自己的清理逻辑；
- 对象存储版本控制保留了旧对象。

必须按 Registry 官方流程执行 GC，不要直接删除 Registry 存储目录中的 Blob。

### 24.9 打开调试日志

全局参数放在子命令前：

```bash
skopeo --debug inspect \
  docker://registry.example.com/team/app:v1
```

注意调试日志可能包含内部地址和认证流程信息，分享前应脱敏。

### 24.10 命令超时

```bash
skopeo \
  --command-timeout 30m \
  copy \
  --retry-times 5 \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1
```

不要只增加超时，应同时检查带宽、代理、Registry 日志和对象存储性能。

---

## 25. 生产镜像同步流程

### 25.1 单镜像晋级

```text
1. 检查源镜像存在
2. 获取源 Digest
3. 检查多架构平台清单
4. 验证签名和扫描结果
5. 按 Digest 执行 skopeo copy --all
6. 获取目标 Digest
7. 比较源和目标结构
8. 在目标环境拉取测试
9. 保存审计信息
10. 更新部署引用
```

### 25.2 批量同步

```text
1. 维护受审查的 images.yaml
2. skopeo sync --dry-run
3. 评估镜像数量和容量
4. 准备源/目标最小权限凭据
5. 正式同步并启用 --all、重试和 keep-going
6. 收集失败清单
7. 校验 Digest 和平台
8. 重试失败项
9. 运行安全扫描
10. 生成镜像映射和审计报告
```

### 25.3 上线前检查清单

- [ ] Skopeo 版本已固定；
- [ ] 源和目标 Registry 名称完整；
- [ ] 源 Tag 已解析为 Digest；
- [ ] 已确认是否为多架构镜像；
- [ ] 多架构复制使用 `--all`；
- [ ] 源、目标 Authfile 分离；
- [ ] 密码没有出现在命令行和日志；
- [ ] 私有 CA 已正确安装；
- [ ] 未使用永久 `--tls-verify=false`；
- [ ] 已设置重试和命令超时；
- [ ] 临时目录容量充足；
- [ ] 目标 Registry 支持源 Manifest 类型；
- [ ] 复制后验证目标 Digest；
- [ ] 签名和 SBOM 迁移策略已确认；
- [ ] 流水线保存同步审计记录。

---

## 26. 命令速查

```bash
# 版本
skopeo --version

# 检查远程镜像
skopeo inspect docker://registry.example.com/team/app:v1

# 只看 Digest
skopeo inspect \
  --format '{{.Digest}}' \
  docker://registry.example.com/team/app:v1

# 原始 Manifest
skopeo inspect --raw \
  docker://registry.example.com/team/app:v1 | jq .

# Image Config
skopeo inspect --config \
  docker://registry.example.com/team/app:v1 | jq .

# 列出 Tag
skopeo list-tags \
  docker://registry.example.com/team/app

# 登录
printf '%s' "$REGISTRY_PASSWORD" \
  | skopeo login \
      --username "$REGISTRY_USERNAME" \
      --password-stdin \
      registry.example.com

# 单镜像复制
skopeo copy \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1

# 完整多架构复制
skopeo copy --all --retry-times 5 \
  docker://source.example.com/team/app:v1 \
  docker://destination.example.com/team/app:v1

# 保存 Docker Archive
skopeo copy \
  docker://registry.example.com/team/app:v1 \
  docker-archive:/tmp/app-v1.tar:app:v1

# 保存 OCI Archive
skopeo copy \
  docker://registry.example.com/team/app:v1 \
  oci-archive:/tmp/app-v1-oci.tar:v1

# 同步前预览
skopeo sync --dry-run --all \
  --src yaml --dest docker \
  images.yaml mirror.example.com

# 批量同步
skopeo sync --all --keep-going --retry-times 5 \
  --src yaml --dest docker \
  images.yaml mirror.example.com

# 删除镜像，执行前必须确认共享 Digest
skopeo delete \
  docker://registry.example.com/team/app:old-tag

# 调试
skopeo --debug inspect \
  docker://registry.example.com/team/app:v1
```

---

## 27. 建议实验

### 实验一：远程检查

1. 检查 Alpine 镜像；
2. 获取默认 JSON；
3. 获取 Raw Manifest；
4. 获取 Image Config；
5. 比较 AMD64 和 ARM64；
6. 记录顶层 Digest 和平台 Digest。

### 实验二：Registry 间复制

1. 准备两个测试 Repository；
2. 登录源和目标 Registry；
3. 复制单架构镜像；
4. 比较 Digest；
5. 复制多架构镜像；
6. 验证 ARM64 平台是否存在。

### 实验三：Archive 转换

分别创建：

- `dir:`；
- `oci:`；
- `oci-archive:`；
- `docker-archive:`。

比较目录结构、Manifest 类型、Digest，并分别使用 Docker、Podman 或 Skopeo 导入验证。

### 实验四：离线同步

1. 编写 `images.yaml`；
2. Dry Run；
3. 导出到目录；
4. 生成 SHA-256 清单；
5. 在隔离环境校验；
6. 导入内部 Registry；
7. 启动 Kubernetes Pod 验证。

### 实验五：CI 镜像晋级

1. BuildKit/Kaniko 构建镜像；
2. 安全扫描；
3. 记录源 Digest；
4. Skopeo 按 Digest 复制；
5. 比较目标 Digest；
6. Kubernetes 使用目标 Digest 部署；
7. 保存流水线审计文件。

---

## 28. 官方资料

- Skopeo 项目：https://github.com/podman-container-tools/skopeo
- Skopeo v1.23.0：https://github.com/podman-container-tools/skopeo/releases/tag/v1.23.0
- 安装说明：https://github.com/podman-container-tools/skopeo/blob/main/install.md
- 主命令手册：https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo.1.md
- Copy：https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-copy.1.md
- Inspect：https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-inspect.1.md
- List Tags：https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-list-tags.1.md
- Login：https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-login.1.md
- Sync：https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-sync.1.md
- Delete：https://github.com/podman-container-tools/skopeo/blob/main/docs/skopeo-delete.1.md
- Transport：https://github.com/containers/image/blob/main/docs/containers-transports.5.md
- Authfile：https://github.com/containers/image/blob/main/docs/containers-auth.json.5.md
- Trust Policy：https://github.com/containers/image/blob/main/docs/containers-policy.json.5.md
- Registry 配置：https://github.com/containers/image/blob/main/docs/containers-registries.conf.5.md
- Registry 证书目录：https://github.com/containers/image/blob/main/docs/containers-certs.d.5.md

---

## 29. 总结

Skopeo 最适合放在镜像构建完成之后，负责远程检查、镜像晋级、跨 Registry 复制、离线同步和结果校验。

生产使用的关键点不是“能把镜像复制过去”，而是：

1. 始终使用完整镜像名和正确 Transport；
2. 用 Digest 固定源内容；
3. 使用 `--all` 保留完整多架构镜像；
4. 安全管理源、目标凭据和私有 CA；
5. 复制后验证目标 Digest、平台清单和签名；
6. 批量同步前 Dry Run，并保留完整审计记录；
7. 删除镜像前检查共享 Manifest 和 Registry GC 行为。

如果缺少 Digest 校验、多架构检查和目标环境拉取验证，镜像“同步成功”仍然可能在生产节点上无法运行。
