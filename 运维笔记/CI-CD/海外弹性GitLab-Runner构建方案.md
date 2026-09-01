# 海外弹性 GitLab Runner 构建方案

> 安全与版本提示（2026-09-01）：本文保留的是阿里云 ASK、ECI、NAS 与旧 Kaniko 方案的专项设计。新部署应使用 GitLab Runner authentication token（通常以 `glrt-` 开头）和 Helm Chart 的 `runnerToken`/外部 Secret，不再使用已不推荐的 `runnerRegistrationToken`。通用部署流程见：[GitLab、GitLab Runner 与 Argo CD 的 GitOps 完整部署流程](GitLab-ArgoCD-GitLab-Runner-GitOps完整部署流程.md)。Kaniko 构建示例应优先评估迁移到 BuildKit rootless。

## 概述

在海外构建公共镜像时，需要同时开启大量构建机并行执行以提高效率，对弹性资源需求极强。本方案基于**阿里云 ASK（Serverless Kubernetes）+ ECI（弹性容器实例）**，使用 Helm 部署 GitLab Runner，配合 Kaniko 实现无 Docker Daemon 的安全镜像构建。

---

## 架构全景

```
┌──────────────────────────────────────────────────────────────────┐
│                        GitLab (git.dp.tech)                       │
│                         触发 CI Pipeline                          │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              阿里云 ASK 集群 (us-east-1 海外)                      │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │              GitLab Runner (Helm 部署)                     │    │
│  │  concurrent: 10 · 每 30s 轮询 · tags: k8s-runner          │    │
│  └──────────────────────────┬───────────────────────────────┘    │
│                             │ 创建 Job Pod                        │
│                             ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │              ECI Job Pod (弹性容器实例)                     │    │
│  │  ┌────────────────────────────────────────────────────┐   │    │
│  │  │  Kaniko Executor (debug)                            │   │    │
│  │  │  · 解析 Dockerfile · 执行 RUN/COPY · 生成镜像层     │   │    │
│  │  │  · 拉取基础镜像 · 推送最终镜像                        │   │    │
│  │  └────────────────────────────────────────────────────┘   │    │
│  │  资源: 16C / 32Gi · 缓存: NAS /cache                       │    │
│  └──────────────────────────────────────────────────────────┘    │
│                             │                                     │
│              ┌──────────────┼──────────────┐                      │
│              ▼              ▼              ▼                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  NAS 存储     │  │  海外 Registry │  │  国内 Registry│           │
│  │  (缓存层)     │  │  (us-east-1)  │  │  (registry    │           │
│  │  /cache       │  │               │  │   .dp.tech)   │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────────────────────────────────────────────┘
```

---

## 一、组件说明

| 组件 | 作用 | 选型原因 |
|------|------|----------|
| **阿里云 ASK** | Serverless K8s 集群 | 无需管理节点，按量付费，弹性伸缩 |
| **ECI** | 弹性容器实例 | Job Pod 直接跑在 ECI 上，秒级启动 |
| **GitLab Runner** | CI 任务执行器 | Helm 一键部署，K8s Executor 原生支持 |
| **Kaniko** | 镜像构建 | 不需要 Docker Daemon，不需要特权模式 |
| **Kaniko Warmer** | 基础镜像预缓存 | 提前拉取基础镜像到 NAS，加速构建 |
| **NAS** | 共享缓存存储 | ReadWriteMany，多 Job Pod 共享缓存层 |

---

## 二、部署步骤

### 2.1 创建海外 ASK 集群

在阿里云控制台创建 ASK 集群，选择 `us-east-1` 区域，开启 ECI 支持。

### 2.2 创建 NAS 缓存存储

**PV（PersistentVolume）**：

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  labels:
    alicloud-pvname: gitlab-runner-cache-pv
  name: gitlab-runner-cache-pv
  namespace: gitlab
spec:
  accessModes:
    - ReadWriteMany
  capacity:
    storage: 20Gi
  claimRef:
    apiVersion: v1
    kind: PersistentVolumeClaim
    name: gitlab-runner-cache-pvc
    namespace: gitlab
  csi:
    driver: nasplugin.csi.alibabacloud.com
    volumeAttributes:
      path: /cache
      server: 1336e24bb4b-ptk46.us-east-1.nas.aliyuncs.com
      vers: '3'
    volumeHandle: gitlab-runner-cache-pv
  persistentVolumeReclaimPolicy: Retain
  storageClassName: nas
  volumeMode: Filesystem
```

**PVC（PersistentVolumeClaim）**：

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: gitlab-runner-cache-pvc
  namespace: gitlab
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 20Gi
  selector:
    matchLabels:
      alicloud-pvname: gitlab-runner-cache-pv
  storageClassName: nas
  volumeMode: Filesystem
  volumeName: gitlab-runner-cache-pv
```

### 2.3 Helm 部署 GitLab Runner

```bash
helm repo add gitlab https://charts.gitlab.io
helm install --namespace gitlab gitlab-runner -f values.yaml gitlab/gitlab-runner
```

**values.yaml 核心配置**（仅关键部分）：

```yaml
# GitLab 地址
gitlabUrl: https://git.example.com/
# 不要把真实 Token 写入 values.yaml；应通过 Kubernetes Secret 注入。
runnerToken: "<RUNNER_AUTHENTICATION_TOKEN>"

# 并发数 & 轮询间隔
concurrent: 10
checkInterval: 30

# Job Pod 配置
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        namespace = "{{.Release.Namespace}}"
        image = "ubuntu:20.04"
        cpu_limit = "16"
        cpu_request = "16"
        memory_limit = "32Gi"
        memory_request = "32Gi"

      # ECI 标识（阿里云 ASK 专用）
      [runners.kubernetes.pod_labels]
        "eci_workload" = "Job"
      # 开启 ECI 镜像缓存加速
      [runners.kubernetes.pod_annotations]
        "k8s.aliyun.com/eci-image-cache" = "true"
      # 挂载 NAS 缓存
      [runners.kubernetes.volumes]
        [[runners.kubernetes.volumes.pvc]]
          name = "gitlab-runner-cache-pvc"
          mount_path = "/cache"
          readonly = false

  tags: "k8s-runner"
```

### 2.4 RBAC 授权

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: gitlab-runner
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: default
  namespace: gitlab
```

### 2.5 基础镜像预缓存（可选，变更时手动执行）

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: kaniko-warmer
spec:
  containers:
  - name: kaniko-warmer
    image: gcr.io/kaniko-project/warmer:latest
    args:
      - '--cache-dir=/cache'
      - '--image=registry.dp.tech/dptech/ubuntu:22.04-py3.10'
      - '--image=registry.dp.tech/dptech/ubuntu:20.04-py3.10'
      - '--image=registry.dp.tech/dptech/ubuntu:22.04-py3.10-intel2022'
      - '--image=registry.dp.tech/dptech/ubuntu:20.04-py3.10-intel2022'
      - '--image=registry.dp.tech/dptech/ubuntu:20.04-py3.10-cuda11.6'
      - '--image=registry.dp.tech/dptech/ubuntu:22.04-py3.10-cuda11.6'
    volumeMounts:
      - mountPath: /cache
        name: cache-volume
      - mountPath: /kaniko/.docker/config.json
        name: docker-config
        subPath: config.json
  restartPolicy: Never
  volumes:
    - name: cache-volume
      persistentVolumeClaim:
        claimName: gitlab-runner-cache-pvc
    - name: docker-config
      configMap:
        name: docker-registry
```

---

## 三、GitLab CI 使用 Kaniko 构建

### 3.1 `.gitlab-ci.yml` 示例

```yaml
variables:
  RUNNER_US_TAG: k8s-runner
  RUNNER_TAG: shared-cpu

stages:
  - build

build-job:
  stage: build
  image: gcr.io/kaniko-project/executor:debug
  # 国内镜像: dp-harbor-registry-vpc.cn-zhangjiakou.cr.aliyuncs.com/public/kaniko-project/executor:debug-0.0.5
  script:
    - |
      # 从 CI_COMMIT_TAG 解析镜像名和 Dockerfile 路径
      # TAG 格式: {type}_{image}_{version}  如: public_ubuntu_22.04-py3.10
      DOCKER_IMAGE=`echo $CI_COMMIT_TAG | awk -F '_' '{print $2}'`":"`echo $CI_COMMIT_TAG | awk -F '_' '{print $3}'`
      DOCKERFILE_DIR=`echo $CI_COMMIT_TAG | awk -F '_' '{print $1}'`"/"`echo $CI_COMMIT_TAG | awk -F '_' '{print $2}'`"/"`echo $CI_COMMIT_TAG | awk -F '_' '{print $3}'`

      # 配置 Registry 认证
      mkdir -pv /kaniko/.docker
      cat > /kaniko/.docker/config.json <<EOF
      {
        "auths": {
          "$REGISTRY_US_HOST": {
            "auth": "`echo -n $REGISTRY_USERNAME:$REGISTRY_PASSWORD | base64`"
          },
          "registry.dp.tech": {
            "auth": "`echo -n $REGISTRY_USERNAME:$REGISTRY_PASSWORD | base64`"
          }
        }
      }
      EOF

      # 执行 Kaniko 构建
      executor \
        --context "${CI_PROJECT_DIR}" \
        --dockerfile=$DOCKERFILE_DIR/Dockerfile \
        --cache=true \
        --cache-ttl=6h \
        --cache-dir=/cache \
        --destination=$REGISTRY_US_HOST/$SYNC_NAMESPACE/$DOCKER_IMAGE

  only:
    variables:
      - $CI_COMMIT_TAG =~ /^(private|public)_.*_.*$/

  tags:
    - $RUNNER_US_TAG
```

### 3.2 关键参数说明

| 参数 | 说明 |
|------|------|
| `--cache=true` | 开启 Kaniko 缓存 |
| `--cache-ttl=6h` | 缓存有效期 6 小时 |
| `--cache-dir=/cache` | 缓存目录（NAS 挂载点） |
| `--context` | 构建上下文（Git 仓库目录） |
| `--destination` | 推送目标镜像 |

---

## 四、Kaniko Warmer — 基础镜像预热

### 4.1 为什么需要 Warmer

Kaniko 每次构建时，`FROM` 指令需要从 Registry 拉取基础镜像层。如果镜像很大（如 CUDA 基础镜像动辄几 GB），每次拉取耗时很长。

**Kaniko Warmer** 提前将基础镜像的层缓存到 NAS `/cache` 目录，后续构建直接命中缓存，跳过网络拉取。

### 4.2 Warmer 工作原理

```
基础镜像: registry.dp.tech/dptech/ubuntu:22.04-py3.10-cuda11.6
                        │
                        ▼
Kaniko Warmer 拉取所有层 → 缓存到 /cache（NAS）
                        │
                        ▼
Kaniko Executor 构建时 → 检测到 /cache 已有基础镜像层 → 直接使用
```

### 4.3 何时执行 Warmer

- 基础镜像版本更新时
- 新增基础镜像类型时
- 缓存过期后（`--cache-ttl` 到期）

---

## 五、方案亮点

| 特性 | 实现方式 |
|------|----------|
| **弹性伸缩** | ASK + ECI 按需创建 Pod，闲置时不计费 |
| **安全构建** | Kaniko 不需要 Docker Daemon，不需要特权模式 |
| **缓存加速** | NAS 共享 + Kaniko 层缓存 + Warmer 预热 |
| **海外部署** | us-east-1 区域，离海外用户更近 |
| **并发构建** | concurrent=10，最多同时 10 个构建任务 |
| **镜像同步** | 推送到海外 Registry + 国内 registry.dp.tech 双注册中心 |

---

## 六、参考链接

- [阿里云 ASK + GitLab Runner 弹性构建方案](https://developer.aliyun.com/article/773024)
- [Kaniko 官方文档](https://github.com/GoogleContainerTools/kaniko)
- [GitLab Runner Helm Chart](https://docs.gitlab.com/runner/install/kubernetes.html)

---

*文档创建时间：2026-07-02*
