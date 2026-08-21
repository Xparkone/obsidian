# Velero：Kubernetes 备份、恢复与迁移指南

> 验证基线：Velero `v1.18.2`、Velero AWS Plugin `v1.14.2`  
> 资料截止日期：2026-08-21  
> 适用范围：自建 Kubernetes、K3s、托管 Kubernetes，以及使用 S3/MinIO、CSI 存储的集群

---

## 1. 文档概述

### 1.1 先讲结论

Velero 是 Kubernetes 应用级的备份、恢复和迁移工具。它主要处理两类内容：

1. Kubernetes API 中的资源对象，例如 Namespace、Deployment、Service、Secret、RBAC、CRD、PV 和 PVC；
2. 持久卷中的数据，通过 CSI 快照、云厂商快照、CSI Snapshot Data Mover 或 File System Backup 完成。

生产使用时应记住以下原则：

1. Velero 不是节点操作系统备份，也不是 Kubernetes 安装目录备份。
2. Velero 不能完全代替 etcd 快照；两者解决的问题不同。
3. 卷快照成功不等于数据库事务一致，数据库仍需要原生备份或一致性 Hook。
4. 备份对象存储必须位于独立故障域；把 MinIO 和备份数据只放在被保护集群内，无法覆盖整集群故障。
5. 备份是否可用必须通过恢复演练证明，不能只看 `Completed` 状态。
6. 应明确 RPO、RTO、保留周期、备份范围、恢复顺序和责任人。
7. Kubernetes Secret 会进入资源备份，备份桶应视为敏感数据存储并严格控制访问。
8. 不要默认启用对象锁或不可变策略；Velero 备份过程中会更新对象，必须按所用版本验证兼容性。

### 1.2 适用读者

本文适合：

- Kubernetes 管理员；
- DevOps、平台工程师和 SRE；
- 需要建设 Kubernetes 灾难恢复方案的团队；
- 需要迁移 Namespace、应用或整个集群的人员。

阅读完成后，应能够：

- 解释 Velero 的组件和工作流程；
- 判断 CSI 快照、数据搬迁和文件系统备份的适用范围；
- 使用 S3 或 MinIO 部署 Velero；
- 创建按需备份和定时备份；
- 恢复 Namespace、PVC 和应用资源；
- 设计数据库一致性方案；
- 执行跨集群迁移和灾难恢复演练；
- 排查常见备份、快照和恢复故障。

### 1.3 版本基线

本文以以下版本为示例：

| 组件 | 版本 | 说明 |
|---|---:|---|
| Velero | `v1.18.2` | 2026-06-26 发布的稳定补丁版本 |
| Velero AWS Plugin | `v1.14.2` | 用于 AWS S3、EBS 及 S3 兼容对象存储 |
| Kubernetes | 以实际兼容矩阵为准 | 升级前必须检查 Velero 与 Kubernetes 的兼容性 |

Velero、Provider Plugin、Kubernetes、CSI Driver 和对象存储之间存在兼容关系。生产环境不要使用 `latest` 镜像，应固定版本并在测试集群验证升级。

---

## 2. Velero 是什么

Velero 原名 Heptio Ark，是运行在 Kubernetes 中的备份控制器和本地命令行工具。它提供三类核心能力：

- **备份**：导出 Kubernetes 资源，并按配置保护持久卷数据；
- **恢复**：把备份资源和卷数据恢复到原集群或新集群；
- **迁移**：把应用从一个 Kubernetes 集群迁移到另一个集群。

典型使用场景：

- 误删 Namespace 后恢复；
- 集群升级、存储升级或大规模变更前备份；
- 从旧集群迁移到新集群；
- 从自建 Kubernetes 迁移到托管 Kubernetes；
- 将生产应用复制到隔离测试环境；
- 区域级或集群级灾难恢复；
- 为重要应用建立按小时、按日或按周的恢复点。

Velero 由以下两部分组成：

- `velero` CLI：运行在管理员工作站或运维节点；
- Velero Server：运行在集群内，一般位于 `velero` Namespace。

CLI 创建 `Backup`、`Restore`、`Schedule` 等自定义资源，集群内控制器负责真正执行任务。

---

## 3. 能备份什么，不能备份什么

### 3.1 Kubernetes 资源对象

Velero 可以备份通过 Kubernetes API 访问的资源，例如：

- Namespace；
- Deployment、StatefulSet、DaemonSet、Job、CronJob；
- Service、Ingress、EndpointSlice；
- ConfigMap、Secret；
- ServiceAccount、Role、ClusterRole 及其绑定；
- CRD 和自定义资源；
- StorageClass、PV、PVC；
- Operator 管理的资源对象。

资源备份本质上是逻辑备份。Velero读取 Kubernetes API 对象并生成备份内容，不是直接复制 etcd 数据文件。

### 3.2 持久卷数据

持久卷数据需要选择适当方式：

| 方式 | 数据来源 | 典型适用场景 | 主要限制 |
|---|---|---|---|
| 云厂商卷快照 | EBS、Azure Disk、GCE Disk 等 | 同云、同区域快速恢复 | 通常受云厂商、区域和账号限制 |
| CSI Snapshot | CSI Driver 创建的 VolumeSnapshot | 支持 CSI 快照的块存储 | 快照可能仍在原存储故障域 |
| CSI Snapshot Data Mover | 从 CSI 快照搬迁到对象存储 | 需要脱离原存储保存副本 | 需要 Node Agent 和额外临时资源 |
| File System Backup | 从 Pod 已挂载文件系统读取 | NFS、文件存储、无快照能力的卷 | 非严格时间点一致，速度受文件数影响 |
| 数据库原生备份 | 数据库自身逻辑或物理备份 | MongoDB、MySQL、PostgreSQL 等 | 需单独设计、调度和恢复流程 |

### 3.3 Velero 不负责的内容

Velero 通常不备份：

- Kubernetes 节点操作系统；
- `/etc/kubernetes`、`/etc/rancher`、containerd 配置等主机文件；
- kubelet、containerd、内核参数和防火墙规则；
- 云平台 IAM、VPC、负载均衡器等所有外部资源；
- 没有通过卷备份捕获的数据；
- 数据库内存中尚未落盘的事务；
- 外部 DNS、证书平台、消息系统和第三方 SaaS 配置；
- GitOps 仓库、镜像仓库和外部 Secret 管理平台自身的数据。

因此，完整灾备通常还需要：

- etcd 或 K3s datastore 备份；
- Terraform 等基础设施代码；
- Ansible 或节点配置管理；
- 数据库原生备份；
- 镜像仓库备份或跨区域复制；
- Git 仓库备份；
- 对象存储版本控制或跨区域复制；
- DNS、证书和密钥恢复流程。

---

## 4. Velero、etcd 快照和数据库备份的区别

| 能力 | Velero | etcd 快照 | CSI/云盘快照 | 数据库原生备份 |
|---|---|---|---|---|
| 备份 Kubernetes API 对象 | 是 | 是，原始集群状态 | 否 | 否 |
| 按 Namespace 恢复 | 是 | 不适合 | 否 | 否 |
| 跨集群迁移 | 较适合 | 通常不适合 | 受存储限制 | 取决于数据库 |
| 恢复 PVC 数据 | 可编排 | 不包含卷实际数据 | 是 | 只恢复数据库数据 |
| 数据库事务一致性 | 默认不保证 | 不保证卷数据一致 | 通常只保证存储层时间点 | 最适合 |
| 恢复整个控制平面 | 否 | 是 | 否 | 否 |
| 典型粒度 | 集群、Namespace、资源 | 整个 etcd | 卷 | 库、表、日志或实例 |

建议组合：

```text
Terraform / Ansible    恢复基础设施与节点
        +
etcd 快照              恢复控制平面原始状态
        +
Velero                 恢复 Kubernetes 应用资源
        +
CSI / FSB              恢复普通持久卷数据
        +
数据库原生备份          恢复数据库并保证业务一致性
```

### 4.1 什么时候优先使用 etcd 快照

- 原集群控制平面损坏；
- 需要恢复整个集群在某一时刻的 Kubernetes 状态；
- 集群拓扑、版本和证书环境仍与原环境匹配；
- 目标是原地灾难恢复，而不是选择性迁移应用。

### 4.2 什么时候优先使用 Velero

- 只恢复一个 Namespace 或应用；
- 跨集群迁移；
- 需要对资源进行筛选；
- 需要重映射 Namespace；
- 需要同时编排资源对象和卷数据恢复；
- 需要定期保存应用级恢复点。

---

## 5. 架构与工作流程

### 5.1 核心组件

```text
管理员工作站
┌──────────────────────┐
│ velero CLI           │
└──────────┬───────────┘
           │ 创建 Backup / Restore / Schedule CR
           ▼
Kubernetes API Server
┌──────────────────────────────────────────────┐
│ Velero Namespace                             │
│                                              │
│  ┌────────────────────┐                      │
│  │ Velero Server      │                      │
│  │ Backup/Restore 控制器│                     │
│  └──────┬─────────────┘                      │
│         │                                    │
│  ┌──────▼─────────────┐  每个节点可运行       │
│  │ Provider Plugin    │  ┌────────────────┐  │
│  │ S3/EBS/Azure/GCP   │  │ Node Agent     │  │
│  └──────┬─────────────┘  │ FSB/Data Mover │  │
│         │                └────────┬───────┘  │
└─────────┼─────────────────────────┼──────────┘
          │                         │
          ▼                         ▼
┌──────────────────┐     ┌──────────────────────┐
│ S3 / MinIO / OSS │     │ CSI Snapshot / PVC  │
│ 资源与备份数据    │     │ 卷快照和数据搬迁     │
└──────────────────┘     └──────────────────────┘
```

### 5.2 主要自定义资源

| 资源 | 作用 |
|---|---|
| `Backup` | 一次备份请求及其执行状态 |
| `Restore` | 一次恢复请求及其执行状态 |
| `Schedule` | 基于 Cron 的周期备份模板 |
| `BackupStorageLocation` | 资源备份和 FSB/Data Mover 数据的对象存储位置 |
| `VolumeSnapshotLocation` | 云厂商卷快照位置和参数 |
| `PodVolumeBackup` | 一次 Pod 卷文件系统备份任务 |
| `PodVolumeRestore` | 一次 Pod 卷文件系统恢复任务 |
| `DataUpload` | CSI Snapshot Data Mover 上传任务 |
| `DataDownload` | CSI Snapshot Data Mover 下载任务 |
| `BackupRepository` | FSB 或 Data Mover 使用的备份仓库状态 |

查看资源：

```bash
kubectl api-resources | grep velero
kubectl -n velero get backup,restore,schedule
kubectl -n velero get backupstoragelocation,volumesnapshotlocation
kubectl -n velero get podvolumebackup,podvolumerestore
kubectl -n velero get dataupload,datadownload
kubectl -n velero get backuprepository
```

### 5.3 备份流程

简化流程如下：

1. 用户通过 CLI 或 YAML 创建 `Backup`；
2. Velero Server 读取备份范围；
3. 可选执行备份前 Hook；
4. 从 Kubernetes API 读取目标资源；
5. 通过 Provider Plugin 写入对象存储；
6. 根据配置创建 CSI/云盘快照，或触发 FSB/Data Mover；
7. 等待异步数据操作完成；
8. 可选执行备份后 Hook；
9. 更新 `Backup` 状态。

Kubernetes 对象在备份过程中仍可能发生变化，因此一次集群备份不是严格原子操作。对强一致应用，需要暂停写入、使用 Hook 或使用应用原生备份。

### 5.4 恢复流程

简化流程如下：

1. 用户创建 `Restore`；
2. Velero 从对象存储读取备份；
3. 按资源优先级恢复 CRD、Namespace、StorageClass、PVC、工作负载等对象；
4. 通过快照、FSB 或 Data Mover 恢复卷；
5. 可选执行恢复 Hook；
6. 记录恢复状态、警告和错误。

如果目标资源已经存在，默认恢复行为通常是跳过，而不是强制覆盖。使用更新策略前必须在测试环境验证，避免覆盖新配置。

---

## 6. 备份位置与故障域设计

### 6.1 BackupStorageLocation

`BackupStorageLocation`，简称 BSL，指向一个对象存储 Bucket 或 Bucket 中的 Prefix，用于保存：

- Kubernetes 资源备份；
- 备份元数据和日志；
- File System Backup 数据；
- CSI Snapshot Data Mover 搬迁的数据。

Velero 假设自己能够管理指定 Bucket 或 Prefix。建议为 Velero 使用独立 Bucket 或独立 Prefix，不要与无关业务文件混用。

### 6.2 VolumeSnapshotLocation

`VolumeSnapshotLocation`，简称 VSL，描述云厂商卷快照所需的区域、资源组等参数。

需要注意：

- 一个备份只选择一个 BSL；
- 每种卷 Provider 可以选择一个 VSL；
- 单个备份不能同时写入两个 BSL；
- 需要双份备份时，应建立两个 Schedule，分别写入不同位置；
- AWS 和 Azure 等平台通常不允许直接把卷快照创建到另一个区域；
- 跨 Provider 快照通常不可用。

### 6.3 推荐故障域

不推荐：

```text
Kubernetes 集群
├── 应用
├── MinIO Pod
└── MinIO 数据只保存在同一集群 local-path PVC
```

如果集群、节点或底层磁盘整体损坏，应用和备份会一起丢失。

推荐：

```text
生产 Kubernetes 集群
        │
        ├── 资源备份 ──────► 独立账号/独立区域对象存储
        │
        ├── 卷快照 ────────► 存储平台快照域
        │
        └── 数据搬迁 ──────► 独立对象存储
```

至少满足一项：

- 对象存储不依赖被保护集群；
- 跨账号保存；
- 跨区域复制；
- 独立存储系统；
- Bucket 开启版本控制并配置受控保留策略。

---

## 7. 备份策略设计

### 7.1 先定义 RPO 和 RTO

- **RPO**：允许丢失多少时间的数据；
- **RTO**：从故障发生到服务恢复允许多长时间。

示例：

| 应用等级 | 示例 RPO | 示例 RTO | 建议策略 |
|---|---:|---:|---|
| 核心数据库 | 5 分钟 | 30 分钟 | 数据库持续日志 + 定期全量 + Velero 资源备份 |
| 核心无状态服务 | 1 小时 | 30 分钟 | GitOps + 每小时 Velero 资源备份 |
| 一般有状态应用 | 4 小时 | 4 小时 | CSI 快照或 FSB + 每日恢复验证 |
| 测试环境 | 24 小时 | 1 天 | 每日或每周备份 |

表中只是示例，真实目标必须由业务、成本和恢复能力共同决定。

### 7.2 备份分层

建议至少分为：

1. **资源层**：Kubernetes API 对象；
2. **卷数据层**：CSI 快照、Data Mover 或 FSB；
3. **应用层**：数据库和中间件原生备份；
4. **控制平面层**：etcd 或 K3s datastore；
5. **基础设施层**：Terraform、网络、IAM、证书和 DNS；
6. **供应链层**：Git、镜像仓库、Helm Chart 和制品。

### 7.3 保留策略示例

```text
每小时备份：保留 24 份
每日备份：保留 30 份
每周备份：保留 12 份
每月备份：保留 12 份
```

生产环境应显式设置 TTL，不依赖默认值，并评估：

- 对象数量；
- 文件数量和总容量；
- 快照费用；
- API 请求费用；
- 跨区域流量；
- Repository Maintenance 时间；
- 恢复所需网络带宽。

### 7.4 恢复演练频率

建议：

- 每周：自动验证最近备份状态；
- 每月：在隔离 Namespace 恢复一个应用；
- 每季度：恢复到独立集群；
- 每半年：执行完整灾难恢复演练；
- 大版本升级前：进行专项恢复验证。

---

## 8. 安装前检查

### 8.1 集群和权限

```bash
kubectl version
kubectl cluster-info
kubectl get nodes -o wide
kubectl auth can-i create customresourcedefinitions.apiextensions.k8s.io
kubectl auth can-i create clusterroles.rbac.authorization.k8s.io
kubectl auth can-i create namespaces
```

安装 Velero 通常需要集群级权限，因为它会创建 CRD、ClusterRole 和相关资源。

### 8.2 确认存储类型

```bash
kubectl get storageclass
kubectl get pv
kubectl get pvc -A
kubectl get volumesnapshotclass
kubectl get csidriver
```

需要回答：

- 当前 PVC 使用什么 StorageClass？
- CSI Driver 是否支持快照？
- 集群是否安装 Snapshot Controller 和 VolumeSnapshot CRD？
- 快照是否能跨区域、跨账号或跨集群恢复？
- 如果不支持快照，是否使用 FSB？
- 卷中是否包含数据库？需要什么一致性措施？

### 8.3 对象存储检查

确认：

- Bucket 已创建；
- Velero 能通过 DNS 和网络访问 Endpoint；
- 凭据具有所需 Bucket/Prefix 权限；
- 使用 HTTPS 或受控的内网链路；
- Bucket 不依赖被保护集群；
- 生命周期规则不会早于 Velero TTL 删除数据；
- 对象锁、版本控制和复制策略已经过兼容性验证。

---

## 9. 安装 Velero CLI

### 9.1 Linux AMD64

```bash
VELERO_VERSION=v1.18.2

curl -fLO \
  "https://github.com/vmware-tanzu/velero/releases/download/${VELERO_VERSION}/velero-${VELERO_VERSION}-linux-amd64.tar.gz"

tar -xzf "velero-${VELERO_VERSION}-linux-amd64.tar.gz"

install -m 0755 \
  "velero-${VELERO_VERSION}-linux-amd64/velero" \
  /usr/local/bin/velero

velero version --client-only
```

ARM64 将文件名中的 `linux-amd64` 改为 `linux-arm64`。生产环境应从 Release 页面获取校验值并验证下载文件。

### 9.2 macOS

```bash
brew install velero
velero version --client-only
```

### 9.3 命令补全

Bash：

```bash
velero completion bash > /etc/bash_completion.d/velero
```

Zsh：

```bash
mkdir -p "${HOME}/.zfunc"
velero completion zsh > "${HOME}/.zfunc/_velero"
```

---

## 10. 使用 S3 或 MinIO 安装

本节使用 AWS Plugin。它既能访问 AWS S3，也能访问部分 S3 兼容对象存储，例如 MinIO。第三方 S3 兼容实现并非全部由 Velero 团队持续测试，升级前必须验证。

### 10.1 准备凭据文件

创建临时凭据文件：

```bash
install -m 0600 /dev/null credentials-velero
```

写入以下内容，使用真实值替换占位符：

```ini
[default]
aws_access_key_id=<ACCESS_KEY>
aws_secret_access_key=<SECRET_KEY>
```

不要把凭据文件提交到 Git，也不要把真实凭据写入本文档或交接文档。

### 10.2 AWS S3 安装示例

仅使用 S3 保存资源备份，并启用 Node Agent：

```bash
velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.14.2 \
  --bucket <BUCKET_NAME> \
  --secret-file ./credentials-velero \
  --backup-location-config region=<AWS_REGION> \
  --snapshot-location-config region=<AWS_REGION> \
  --use-node-agent
```

如果使用云工作负载身份，应优先评估 IRSA、Workload Identity 等短期身份机制，避免长期静态密钥，并按 Provider 文档使用 `--no-secret` 等对应配置。

### 10.3 MinIO 安装示例

假设：

- Bucket：`velero-backups`；
- MinIO Endpoint：`https://minio-backup.example.com`；
- 不使用云厂商卷快照；
- 使用 FSB 保护卷数据。

```bash
velero install \
  --provider aws \
  --plugins velero/velero-plugin-for-aws:v1.14.2 \
  --bucket velero-backups \
  --secret-file ./credentials-velero \
  --backup-location-config \
region=minio,s3ForcePathStyle=true,s3Url=https://minio-backup.example.com \
  --use-volume-snapshots=false \
  --use-node-agent \
  --default-volumes-to-fs-backup
```

说明：

- `s3ForcePathStyle=true`：使用 Path Style 访问 S3；
- `s3Url`：MinIO API Endpoint，不是 Console 地址；
- `--use-volume-snapshots=false`：不创建无用的 VSL；
- `--use-node-agent`：部署 Node Agent DaemonSet；
- `--default-volumes-to-fs-backup`：默认对符合条件的 Pod 卷启用 FSB。

如果只想对显式标记的卷使用 FSB，删除 `--default-volumes-to-fs-backup`，改用 Pod Annotation 或备份参数。

### 10.4 自签名证书

如果 MinIO 使用自签名 CA，不要直接关闭 TLS 校验。应将 CA 文件传给安装命令，并依据当前 Velero/Provider 文档验证参数：

```bash
velero install \
  ... \
  --cacert ./minio-ca.crt
```

生产环境不建议使用 HTTP；如果实验环境暂时使用 HTTP，应明确记录风险并限制网络访问。

### 10.5 删除本地临时凭据

确认集群中的 Secret 已创建且 Velero 正常启动后，安全删除本地临时文件：

```bash
shred -u credentials-velero
```

如果文件系统或平台不保证 `shred` 有效，应使用组织批准的凭据处理方式。

---

## 11. 安装验证

### 11.1 检查组件

```bash
kubectl -n velero get deployment
kubectl -n velero get daemonset
kubectl -n velero get pods -o wide
kubectl get crd | grep velero
```

预期：

- Velero Server Pod 为 `Running`；
- 使用 Node Agent 时，每个符合调度条件的节点上有一个 Node Agent Pod；
- 相关 CRD 已创建。

### 11.2 检查版本

```bash
velero version
```

输出应同时包含 Client 和 Server 版本。CLI 与 Server 不应长期使用未经验证的跨版本组合。

### 11.3 检查 BSL

```bash
velero backup-location get
kubectl -n velero get backupstoragelocation -o wide
kubectl -n velero describe backupstoragelocation default
```

预期 BSL Phase 为 `Available`。如果为 `Unavailable`，不要继续创建正式备份，应先处理 Endpoint、DNS、TLS、凭据和权限问题。

### 11.4 查看日志

```bash
kubectl -n velero logs deployment/velero --tail=200
kubectl -n velero logs daemonset/node-agent --all-containers --tail=100
```

### 11.5 创建最小测试备份

```bash
kubectl create namespace velero-test
kubectl -n velero-test create configmap smoke-test \
  --from-literal=message=hello

velero backup create velero-smoke-test \
  --include-namespaces velero-test \
  --wait

velero backup describe velero-smoke-test --details
velero backup logs velero-smoke-test
```

只有在状态为 `Completed` 且没有未解释的警告、错误后，才继续配置正式备份。

---

## 12. 按需备份

### 12.1 备份整个集群

```bash
velero backup create full-cluster-20260821 \
  --wait
```

整集群备份会包含大量集群级和 Namespace 级资源。生产使用前应明确排除不需要或无法安全恢复的资源。

### 12.2 备份指定 Namespace

```bash
velero backup create production-20260821 \
  --include-namespaces production \
  --ttl 720h0m0s \
  --wait
```

### 12.3 备份多个 Namespace

```bash
velero backup create business-apps-20260821 \
  --include-namespaces production,payments \
  --ttl 720h0m0s \
  --wait
```

### 12.4 按标签筛选

```bash
velero backup create tier-critical-20260821 \
  --selector 'backup-tier=critical' \
  --wait
```

使用前应统一资源标签规范。不要临时依靠模糊标签决定生产备份范围。

### 12.5 排除 Namespace 或资源类型

```bash
velero backup create selected-cluster-20260821 \
  --exclude-namespaces kube-system,velero \
  --exclude-resources events,events.events.k8s.io \
  --wait
```

具体排除项应在测试环境验证。排除 CRD、Webhook、RBAC 或 StorageClass 可能导致应用无法恢复。

### 12.6 排除单个对象

为资源添加标签：

```bash
kubectl -n production label configmap temporary-cache \
  velero.io/exclude-from-backup=true
```

### 12.7 指定并行文件上传

FSB 或 CSI Snapshot Data Mover 可以设置文件并行度：

```bash
velero backup create production-fast-20260821 \
  --include-namespaces production \
  --parallel-files-upload 4 \
  --wait
```

并行度越高，CPU、内存、磁盘 I/O 和网络消耗越大。应根据节点和对象存储性能压测，不要直接在生产大幅提高。

### 12.8 查看备份

```bash
velero backup get
velero backup describe production-20260821 --details
velero backup logs production-20260821

kubectl -n velero get backup production-20260821 -o yaml
```

常见状态：

- `New`：刚创建；
- `InProgress`：正在执行；
- `Finalizing`：等待异步数据操作完成；
- `Completed`：完成；
- `PartiallyFailed`：部分资源或卷失败；
- `Failed`：备份失败。

`PartiallyFailed` 不能视为成功，必须确认失败项是否影响恢复。

### 12.9 删除备份

使用 Velero 命令删除：

```bash
velero backup delete production-20260821 --confirm
```

不要只执行：

```bash
kubectl -n velero delete backup production-20260821
```

只删除 CR 可能不会按预期清理对象存储内容、快照或关联数据。正式删除前应确认保留和审计要求。

---

## 13. 定时备份

### 13.1 每天凌晨 03:00 备份

明确指定时区：

```bash
velero schedule create production-daily \
  --schedule="CRON_TZ=Asia/Shanghai 0 3 * * *" \
  --include-namespaces production \
  --ttl 720h0m0s
```

说明：

- Cron 使用五段格式；
- 指定 `CRON_TZ=Asia/Shanghai` 可减少时区误解；
- `720h` 等于 30 天；
- Schedule 创建后通常在下一个计划时间触发。

### 13.2 每小时备份

```bash
velero schedule create production-hourly \
  --schedule="CRON_TZ=Asia/Shanghai 0 * * * *" \
  --include-namespaces production \
  --ttl 48h0m0s
```

### 13.3 手动触发 Schedule

```bash
velero backup create --from-schedule production-daily
```

手动触发不会改变后续计划。

### 13.4 查看 Schedule

```bash
velero schedule get
velero schedule describe production-daily
kubectl -n velero get schedule production-daily -o yaml
```

### 13.5 暂停和恢复

可以编辑 Schedule 的 `spec.paused` 字段：

```bash
kubectl -n velero patch schedule production-daily \
  --type merge \
  -p '{"spec":{"paused":true}}'
```

恢复：

```bash
kubectl -n velero patch schedule production-daily \
  --type merge \
  -p '{"spec":{"paused":false}}'
```

### 13.6 GitOps 注意事项

`Backup` 和 `Restore` 是运行时生成资源。ArgoCD 等 GitOps 工具不应把这些资源误判为需要删除的漂移对象。

同时谨慎使用 Schedule 对 Backup 的 OwnerReference：删除 Schedule 可能触发 Kubernetes 垃圾回收删除 Backup CR，并与 Velero 从对象存储同步元数据的行为冲突。采用 GitOps 管理 Schedule 时应单独验证 Prune 策略。

---

## 14. File System Backup

### 14.1 工作原理

File System Backup，简称 FSB，会从 Pod 在节点上挂载的卷文件系统读取数据，并通过 Node Agent 将数据上传到对象存储。

Velero 1.18 的 Node Agent 以 DaemonSet 形式运行，负责 FSB 和数据搬迁相关任务。

FSB 的优点：

- 不强依赖存储平台的快照能力；
- 适合部分 NFS、文件存储和本地卷；
- 备份数据可保存到与原存储不同的对象存储；
- 跨集群和跨存储恢复通常比原生快照更灵活。

FSB 的限制：

- 从在线文件系统读取，不是天然的原子时间点快照；
- 大量小文件会显著降低速度；
- 首次备份可能消耗大量网络和 CPU；
- Node Agent 需要访问节点上的 Pod 卷路径，涉及较高权限；
- 未挂载到 Pod 的 PVC 无法直接按同样方式读取；
- 数据库仍需一致性控制。

### 14.2 默认启用 FSB

安装时使用：

```bash
velero install \
  ... \
  --use-node-agent \
  --default-volumes-to-fs-backup
```

或者调整 Velero Server 配置。变更前先使用当前版本文档核对参数。

### 14.3 按 Pod 指定卷

假设 Pod 中卷名为 `data`：

```bash
kubectl -n production annotate pod <POD_NAME> \
  backup.velero.io/backup-volumes=data
```

排除指定卷：

```bash
kubectl -n production annotate pod <POD_NAME> \
  backup.velero.io/backup-volumes-excludes=cache
```

对于 Deployment 或 StatefulSet，应把 Annotation 写入 Pod Template，避免 Pod 重建后丢失：

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: example
spec:
  template:
    metadata:
      annotations:
        backup.velero.io/backup-volumes: data
```

### 14.4 创建 FSB 备份

如果未设置全局默认，可在命令中启用：

```bash
velero backup create production-fsb-20260821 \
  --include-namespaces production \
  --default-volumes-to-fs-backup \
  --wait
```

### 14.5 检查 FSB 状态

```bash
kubectl -n velero get podvolumebackup
kubectl -n velero get podvolumebackup \
  -l velero.io/backup-name=production-fsb-20260821 \
  -o yaml

kubectl -n velero get backuprepository
kubectl -n velero logs daemonset/node-agent --all-containers --tail=200
```

### 14.6 Repository 密码

Velero 会创建备份仓库凭据 Secret。生产环境应在第一次 FSB 或 Data Mover 备份前按官方文档设置受控密码，并保存到组织批准的密钥管理系统。

已经创建仓库后随意修改密码可能导致旧备份无法访问。修改前必须验证版本行为和恢复方案。

---

## 15. CSI 快照与 Snapshot Data Mover

### 15.1 CSI Snapshot 前提

必须满足：

- 集群安装 VolumeSnapshot CRD；
- 运行 Snapshot Controller；
- CSI Driver 实现快照能力；
- 存在匹配的 `VolumeSnapshotClass`；
- Velero 有创建和读取快照资源的权限。

检查：

```bash
kubectl api-resources | grep -i volumesnapshot
kubectl get volumesnapshotclass
kubectl get csidriver
```

### 15.2 标记 VolumeSnapshotClass

在需要 Velero 选择的 `VolumeSnapshotClass` 上添加标签：

```bash
kubectl label volumesnapshotclass <CLASS_NAME> \
  velero.io/csi-volumesnapshot-class=true
```

同一 CSI Driver 不应存在多个相互冲突的默认选择。变更前检查生产环境已有备份工具的标签和策略。

### 15.3 仅使用 CSI Snapshot

```bash
velero backup create production-csi-20260821 \
  --include-namespaces production \
  --wait
```

检查：

```bash
kubectl get volumesnapshot -A
kubectl get volumesnapshotcontent
velero backup describe production-csi-20260821 --details
```

### 15.4 CSI 快照的故障域问题

CSI Snapshot 可能只是原存储系统中的一个快照引用。如果原存储系统、账号或区域整体丢失，快照也可能不可用。

因此需要确认：

- 快照数据实际存在哪里；
- 是否独立于原卷；
- 是否跨区域复制；
- 删除 PVC、PV、VolumeSnapshot 或 VolumeSnapshotContent 时会发生什么；
- 存储平台的 Retain/Delete 策略；
- 新集群能否访问原快照。

### 15.5 CSI Snapshot Data Mover

Data Mover 的目标是把 CSI 快照中的数据搬到对象存储，以降低快照与原存储处于同一故障域的风险。

前提：

- 安装 Node Agent；
- BSL 可用；
- CSI 快照可创建；
- 节点有足够临时资源；
- 对象存储容量和带宽充足。

创建备份：

```bash
velero backup create production-csi-moved-20260821 \
  --include-namespaces production \
  --snapshot-move-data \
  --wait
```

检查：

```bash
kubectl -n velero get dataupload
kubectl -n velero get backuprepository
kubectl -n velero logs daemonset/node-agent --all-containers --tail=200
```

Data Mover 会增加临时 PVC、节点 I/O、对象存储容量和恢复时间，应先进行容量与性能测试。

---

## 16. 数据库一致性

### 16.1 为什么卷快照不一定一致

数据库可能同时存在：

- 内存中的未落盘数据；
- WAL、Redo Log、Journal；
- 数据文件和日志文件的写入顺序要求；
- 多个卷之间的一致性要求；
- 副本集、主从或分片状态。

直接备份在线文件系统通常只能提供 crash-consistent 或更弱的一致性，不能自动保证 application-consistent。

### 16.2 推荐策略

| 数据库 | 首选保护方式 | Velero 的角色 |
|---|---|---|
| PostgreSQL | pgBackRest、WAL 归档、逻辑备份或受控快照 | 备份 K8s 资源和辅助卷 |
| MySQL | XtraBackup、binlog、逻辑备份或受控快照 | 备份 K8s 资源和辅助卷 |
| MongoDB | 副本集一致性备份、`mongodump` 或专业备份系统 | 备份 K8s 资源和备份产物 |
| Redis | RDB/AOF 结合业务 RPO | 备份 K8s 资源和持久化文件 |
| Elasticsearch | Snapshot Repository | 备份 K8s 资源，不直接替代 ES Snapshot |

### 16.3 Backup Hook

Velero 可以在备份前后执行容器内命令：

- Pre Hook：刷新缓存、暂停写入、执行 `fsfreeze` 等；
- Post Hook：解除冻结、恢复写入。

Pod Annotation 示例：

```yaml
metadata:
  annotations:
    pre.hook.backup.velero.io/container: app
    pre.hook.backup.velero.io/command: '["/bin/sh", "-c", "<PRE_BACKUP_COMMAND>"]'
    pre.hook.backup.velero.io/on-error: Fail
    pre.hook.backup.velero.io/timeout: 2m
    post.hook.backup.velero.io/container: app
    post.hook.backup.velero.io/command: '["/bin/sh", "-c", "<POST_BACKUP_COMMAND>"]'
    post.hook.backup.velero.io/on-error: Continue
    post.hook.backup.velero.io/timeout: 2m
```

注意：

- Hook 命令默认不是在 Shell 中执行，需要 Shell 时显式调用 `/bin/sh -c`；
- Pre Hook 失败时应优先让备份失败，不要产生看似成功但不一致的恢复点；
- Post Hook 必须考虑超时或 Velero 异常，避免应用长时间保持冻结；
- `fsfreeze` 只处理文件系统层面，不自动保证数据库事务语义；
- 多副本、多卷或分片数据库需要数据库级协调。

### 16.4 更稳妥的模式

推荐模式：

```text
数据库原生备份任务
        │
        ▼
把备份文件写入专用 PVC 或对象存储
        │
        ▼
验证备份文件完整性
        │
        ▼
Velero 备份 Kubernetes 资源和必要的备份产物
```

恢复时先恢复基础资源，再按数据库原生流程恢复数据。

---

## 17. 恢复操作

### 17.1 恢复前检查

恢复前确认：

- 目标集群 Kubernetes 版本兼容；
- 所需 CRD 和 Operator 已安装或可由备份恢复；
- Admission Webhook 可用；
- 目标 StorageClass 存在；
- CSI Driver 和 VolumeSnapshotClass 匹配；
- 镜像仓库可访问；
- Secret 和外部身份仍有效；
- DNS、Ingress、LoadBalancer 不会误接生产流量；
- 恢复目标 Namespace 已隔离；
- 备份状态和卷数据状态已确认。

### 17.2 查看可用备份

```bash
velero backup get
velero backup describe production-20260821 --details
```

### 17.3 原 Namespace 恢复

```bash
velero restore create production-restore-20260821 \
  --from-backup production-20260821 \
  --wait
```

### 17.4 恢复到隔离 Namespace

```bash
velero restore create production-restore-test-20260821 \
  --from-backup production-20260821 \
  --namespace-mappings production:production-restore-test \
  --wait
```

这是日常恢复演练的推荐方式。恢复前应阻止测试环境连接生产数据库、生产消息队列和真实支付接口。

### 17.5 查看恢复结果

```bash
velero restore get
velero restore describe production-restore-test-20260821 --details
velero restore logs production-restore-test-20260821

kubectl -n velero get restore production-restore-test-20260821 -o yaml
kubectl -n production-restore-test get all
kubectl -n production-restore-test get pvc
```

### 17.6 已存在资源策略

默认情况下，目标集群已经存在的多数资源会被跳过。不要假设恢复会覆盖现有对象。

如确实需要尝试更新已存在资源，可使用当前版本支持的更新策略：

```bash
velero restore create production-update-20260821 \
  --from-backup production-20260821 \
  --existing-resource-policy update \
  --wait
```

该策略可能覆盖或合并现有配置，必须先在隔离环境验证。

### 17.7 恢复 PVC 的三种路径

Velero 根据备份方式采用不同路径：

1. **云厂商快照**：通过 Provider Plugin 从快照创建卷并恢复 PV/PVC；
2. **FSB**：先动态创建目标卷，再由 Node Agent 写回文件；
3. **CSI Snapshot**：恢复 VolumeSnapshot，并让 CSI Driver 从快照创建目标卷。

如果目标集群没有同名 StorageClass，需要提前创建映射或使用 Restore Resource Modifier 调整资源。不要直接修改原备份文件。

---

## 18. 跨集群迁移

### 18.1 基本流程

```text
源集群
  1. 检查应用一致性
  2. 创建最终备份
  3. 确认资源和卷数据完成
  4. 暂停或限制写入
          │
          ▼
独立对象存储 / 可访问快照
          │
          ▼
目标集群
  5. 安装兼容的 CSI Driver、CRD、Operator
  6. 安装相同或兼容的 Velero/Plugin
  7. 配置同一个 BSL
  8. 等待备份同步
  9. 恢复到隔离 Namespace
 10. 验证后切换 DNS 或流量
```

### 18.2 目标集群连接原 BSL

目标集群的 Velero 使用相同 Bucket、Prefix 和兼容凭据。为了避免两个集群同时写入同一位置，迁移或灾备待命集群可先将 BSL 设为 `ReadOnly`。

检查：

```bash
velero backup-location get
velero backup get
```

Velero 会根据对象存储中的备份元数据重新同步 Backup 资源。若看不到备份，检查：

- Bucket 和 Prefix 是否一致；
- Endpoint、Region 和 Path Style 是否一致；
- 凭据是否有读取权限；
- Velero 和 Plugin 是否兼容；
- BSL 是否 `Available`；
- 服务端日志是否有反序列化或权限错误。

### 18.3 迁移前兼容性清单

- [ ] Kubernetes API 版本在目标集群仍然存在；
- [ ] CRD 版本兼容；
- [ ] Operator 已安装并兼容；
- [ ] StorageClass 可替换；
- [ ] CSI Driver 支持原快照或使用 Data Mover/FSB；
- [ ] LoadBalancer、IngressClass、GatewayClass 已调整；
- [ ] NodeSelector、Affinity、Taint/Toleration 适配新节点；
- [ ] 镜像仓库和拉取凭据可用；
- [ ] ExternalSecret、Vault、KMS 等外部依赖可用；
- [ ] DNS TTL 和切换回滚方案已准备；
- [ ] 数据库最终同步和写入冻结方案已验证。

---

## 19. 灾难恢复运行手册

### 19.1 触发条件

示例：

- 控制平面不可恢复；
- 存储系统发生大范围损坏；
- 集群误删；
- 区域不可用；
- 安全事件要求重建集群；
- 升级失败且原地回滚不可行。

### 19.2 恢复步骤

1. 宣布灾难恢复事件并停止无序操作；
2. 确认故障范围和最后可用恢复点；
3. 冻结源集群写入，避免产生两个活跃集群；
4. 使用 Terraform/Ansible 创建目标基础设施；
5. 安装 Kubernetes、CNI、CSI、Ingress 和证书组件；
6. 安装 Velero 和所需 Provider Plugin；
7. 以只读方式连接备份位置；
8. 确认目标备份的资源和卷数据完整；
9. 恢复 CRD、Operator 和平台依赖；
10. 恢复应用 Namespace；
11. 按数据库原生流程恢复数据库；
12. 验证工作负载、PVC、Service、Ingress 和监控；
13. 执行业务验收；
14. 切换 DNS、负载均衡或流量；
15. 持续观察错误率、延迟和数据一致性；
16. 记录实际 RPO、RTO 和异常；
17. 完成复盘并修订运行手册。

### 19.3 恢复验收

至少验证：

- Pod 不是仅仅 `Running`，而是 Ready 且通过业务健康检查；
- PVC 已绑定，数据量和关键文件符合预期；
- 数据库能读写，复制和时间线正常；
- Service Endpoint 正常；
- Ingress、TLS 和 DNS 正常；
- Secret、证书和外部身份仍有效；
- 队列消费、定时任务和异步任务没有重复执行；
- 告警、日志和 Trace 正常；
- 核心业务用例通过；
- 回滚路径仍可用。

---

## 20. 安全设计

### 20.1 备份桶是敏感资产

资源备份可能包含：

- Kubernetes Secret；
- ServiceAccount 信息；
- ConfigMap 中的连接信息；
- RBAC 和集群拓扑；
- 内部域名、镜像地址和服务配置；
- 应用数据。

因此应：

- 使用独立账号或项目；
- 使用最小权限；
- 启用 TLS；
- 启用存储端加密和 KMS；
- 限制 Bucket Policy；
- 记录和审计访问；
- 定期轮换凭据；
- 优先使用工作负载身份；
- 阻止公共访问；
- 对下载备份内容的操作进行审批或审计。

### 20.2 不要假设备份天然端到端加密

不要假设 Velero 会对所有 Kubernetes 资源备份内容自动提供统一的端到端加密。应依靠：

- HTTPS 传输；
- 对象存储服务端加密；
- KMS 管理密钥；
- 严格 Bucket 权限；
- FSB/Data Mover Repository 的受控密码；
- 必要时的额外客户端加密方案。

### 20.3 对象锁和不可变存储

Velero 在备份过程中可能先写入中间状态，再更新为最终状态。某些 WORM、Object Lock 或不可变策略会阻止更新，导致备份不能正常完成。

推荐：

1. 在独立测试 Bucket 验证；
2. 检查当前 Velero 版本的已知限制；
3. 评估版本控制、跨账号复制和受限删除权限；
4. 不要直接在现有生产 Bucket 上启用未经验证的不可变策略。

### 20.4 Node Agent 权限

FSB 和 Data Mover 需要 Node Agent 访问节点上的卷路径，部分环境需要 root 或特权能力。

应评估：

- Pod Security Admission；
- 节点选择和污点容忍；
- SELinux/AppArmor；
- HostPath 挂载；
- NetworkPolicy；
- 镜像来源和签名；
- Node Agent 可访问的数据范围。

---

## 21. 监控、告警与日常维护

### 21.1 每日检查

```bash
velero backup get
velero schedule get
velero backup-location get
kubectl -n velero get pods
kubectl -n velero get backuprepository
```

### 21.2 建议告警

- 最近一次计划备份未按时完成；
- `Backup` 为 `Failed` 或 `PartiallyFailed`；
- BSL 为 `Unavailable`；
- `PodVolumeBackup`、`DataUpload` 长时间未完成；
- Node Agent 未覆盖所有目标节点；
- 备份 Bucket 容量或配额不足；
- Repository Maintenance 连续失败；
- 快照数量或费用异常；
- 恢复演练超过目标 RTO；
- 备份数量异常下降或突然为零。

### 21.3 日志入口

```bash
kubectl -n velero logs deployment/velero --since=1h
kubectl -n velero logs daemonset/node-agent \
  --all-containers --since=1h

velero backup logs <BACKUP_NAME>
velero restore logs <RESTORE_NAME>
```

### 21.4 维护事项

- 定期升级 Velero 和 Provider Plugin；
- 升级前检查兼容矩阵；
- 定期验证 Bucket 凭据和证书；
- 定期检查 Schedule、TTL 和生命周期规则；
- 定期清理过期快照和孤儿数据；
- 定期进行隔离恢复；
- 记录真实备份耗时、恢复耗时和容量增长；
- 确保旧版本备份在升级后仍能读取；
- 更新数据库、CSI 和 Operator 恢复步骤。

---

## 22. 常见故障排查

### 22.1 BSL 为 Unavailable

检查：

```bash
velero backup-location get
kubectl -n velero describe backupstoragelocation default
kubectl -n velero logs deployment/velero --tail=300
```

常见原因：

- Endpoint 写错；
- 把 MinIO Console 端口当成 S3 API 端口；
- DNS 无法解析；
- 防火墙或 NetworkPolicy 阻断；
- 自签名 CA 未导入；
- Access Key 或 Secret Key 错误；
- Bucket 不存在；
- Region、Prefix 或 Path Style 配置不正确；
- 凭据缺少列举、读取、写入或删除权限。

### 22.2 备份 PartiallyFailed

```bash
velero backup describe <BACKUP_NAME> --details
velero backup logs <BACKUP_NAME>
kubectl -n velero get backup <BACKUP_NAME> -o yaml
```

按以下分类处理：

- 资源读取失败；
- Admission Webhook/APIService 不可用；
- Provider Plugin 错误；
- 卷快照失败；
- FSB 或 DataUpload 失败；
- Hook 失败；
- RBAC 权限不足；
- 对象存储超时。

### 22.3 PodVolumeBackup 长时间 InProgress

```bash
kubectl -n velero get podvolumebackup -o wide
kubectl -n velero describe podvolumebackup <NAME>
kubectl -n velero get pods -o wide
kubectl -n velero logs daemonset/node-agent \
  --all-containers --tail=300
```

检查：

- 对应节点是否有 Node Agent；
- Pod 是否仍存在；
- 卷是否挂载；
- Node Agent 是否被污点或 NodeSelector 阻止；
- 节点磁盘、内存和网络是否不足；
- Repository 是否 Ready；
- 对象存储是否限流；
- 是否存在大量小文件。

### 22.4 CSI 快照没有生成

```bash
kubectl get volumesnapshotclass
kubectl get volumesnapshot -A
kubectl get volumesnapshotcontent
kubectl get csidriver
kubectl -n velero logs deployment/velero --tail=300
```

检查：

- Snapshot CRD 和 Controller；
- CSI Driver 快照能力；
- `VolumeSnapshotClass` Driver 名称；
- Velero 选择标签；
- PVC 是否由该 CSI Driver 提供；
- 快照配额和云平台权限；
- 快照是否在超时时间内变为 `ReadyToUse`。

### 22.5 恢复完成但 Pod 起不来

```bash
velero restore describe <RESTORE_NAME> --details
velero restore logs <RESTORE_NAME>
kubectl -n <NAMESPACE> get pods,pvc,events
kubectl -n <NAMESPACE> describe pod <POD_NAME>
kubectl -n <NAMESPACE> describe pvc <PVC_NAME>
```

常见原因：

- StorageClass 不存在；
- PVC 无法绑定；
- 镜像仓库不可访问；
- Secret 已过期；
- NodeSelector、Affinity 或 Taint 不匹配；
- Admission Webhook 不可用；
- CRD 已恢复但 Operator 未安装；
- LoadBalancer、IngressClass 或证书配置不兼容；
- 恢复资源被现有对象跳过；
- 恢复 Hook 失败。

### 22.6 新集群看不到旧备份

检查：

```bash
velero backup-location get
kubectl -n velero get backupstoragelocation -o yaml
kubectl -n velero logs deployment/velero --tail=300
```

核对：

- Bucket；
- Prefix；
- Endpoint；
- Region；
- 凭据；
- Provider Plugin；
- Velero 版本；
- BSL Access Mode；
- 对象存储内是否实际存在备份目录。

### 22.7 删除备份后对象仍存在

确认使用的是：

```bash
velero backup delete <BACKUP_NAME> --confirm
```

再检查：

- BSL 是否只读；
- 删除权限；
- Object Lock；
- 快照删除策略；
- DataUpload/Kopia 数据；
- Velero Server 日志。

---

## 23. 生产检查清单

### 23.1 上线前

- [ ] 已定义 RPO 和 RTO；
- [ ] 已分类资源备份、卷备份和数据库备份；
- [ ] 备份对象存储位于独立故障域；
- [ ] Bucket 权限遵循最小权限；
- [ ] TLS 和存储端加密已启用；
- [ ] 未把长期密钥提交到 Git；
- [ ] 已固定 Velero 和 Plugin 版本；
- [ ] 已检查 Kubernetes 和 CSI 兼容性；
- [ ] BSL 为 `Available`；
- [ ] Node Agent 覆盖所有目标节点；
- [ ] CSI Snapshot 或 FSB 已单独验证；
- [ ] 数据库一致性方案已验证；
- [ ] 已设置 Schedule 和明确 TTL；
- [ ] 对象存储生命周期不早于 TTL；
- [ ] 已完成隔离恢复测试；
- [ ] 已记录恢复步骤和责任人。

### 23.2 每月

- [ ] 检查所有 Schedule 最近一次执行结果；
- [ ] 检查失败和部分失败备份；
- [ ] 检查 Bucket 容量和费用；
- [ ] 检查孤儿快照；
- [ ] 检查凭据和证书有效期；
- [ ] 恢复一个有状态应用到隔离环境；
- [ ] 验证数据库数据，不只验证 Pod 状态；
- [ ] 记录实际 RPO 和 RTO。

### 23.3 升级前

- [ ] 阅读 Velero 和 Provider Plugin Release Notes；
- [ ] 检查 Kubernetes 兼容矩阵；
- [ ] 备份 Velero 配置和 Schedule；
- [ ] 确认最近恢复演练成功；
- [ ] 在测试集群升级；
- [ ] 验证旧备份恢复；
- [ ] 验证 CSI、FSB、Data Mover 和 Hook；
- [ ] 准备回滚步骤。

---

## 24. 命令速查

```bash
# 版本
velero version

# 备份位置
velero backup-location get
kubectl -n velero get backupstoragelocation

# 创建备份
velero backup create <NAME> --wait
velero backup create <NAME> --include-namespaces <NS> --wait

# 查看备份
velero backup get
velero backup describe <NAME> --details
velero backup logs <NAME>

# 创建定时备份
velero schedule create <NAME> \
  --schedule="CRON_TZ=Asia/Shanghai 0 3 * * *" \
  --include-namespaces <NS> \
  --ttl 720h0m0s

# 手动触发 Schedule
velero backup create --from-schedule <SCHEDULE_NAME>

# 恢复
velero restore create <RESTORE_NAME> \
  --from-backup <BACKUP_NAME> \
  --wait

# Namespace 重映射
velero restore create <RESTORE_NAME> \
  --from-backup <BACKUP_NAME> \
  --namespace-mappings old-ns:new-ns \
  --wait

# 查看恢复
velero restore get
velero restore describe <NAME> --details
velero restore logs <NAME>

# FSB
kubectl -n velero get podvolumebackup,podvolumerestore
kubectl -n velero get backuprepository

# CSI Data Mover
kubectl -n velero get dataupload,datadownload

# 日志
kubectl -n velero logs deployment/velero --tail=200
kubectl -n velero logs daemonset/node-agent \
  --all-containers --tail=200

# 删除备份
velero backup delete <NAME> --confirm
```

---

## 25. 建议实验

### 实验一：无状态 Namespace 恢复

1. 创建 `velero-test` Namespace；
2. 部署 Nginx 和 ConfigMap；
3. 创建备份；
4. 删除 Namespace；
5. 从备份恢复；
6. 验证 Deployment、Service 和 ConfigMap。

### 实验二：PVC + FSB

1. 创建带 PVC 的应用；
2. 写入带校验值的测试文件；
3. 创建 FSB 备份；
4. 删除应用和 PVC；
5. 恢复；
6. 比对文件 Hash。

示例校验：

```bash
sha256sum /data/test-file
```

### 实验三：CSI Snapshot

1. 确认 CSI Driver 支持快照；
2. 标记 VolumeSnapshotClass；
3. 创建备份；
4. 检查 VolumeSnapshot 和 VolumeSnapshotContent；
5. 恢复到新 Namespace；
6. 验证 PVC 数据。

### 实验四：数据库一致性

1. 部署测试数据库；
2. 持续写入编号数据；
3. 分别执行无 Hook 和有一致性控制的备份；
4. 恢复两份备份；
5. 对比事务、日志和数据完整性；
6. 形成适用于该数据库的正式备份流程。

### 实验五：跨集群迁移

1. 准备两个隔离集群；
2. 两个集群连接同一 BSL，目标端先只读；
3. 源集群创建备份；
4. 目标集群等待备份同步；
5. 恢复到新 Namespace；
6. 替换 StorageClass 和 Ingress 配置；
7. 完成业务验证；
8. 记录实际 RPO、RTO 和阻塞项。

---

## 26. 官方资料

- Velero 1.18 文档：https://velero.io/docs/v1.18/
- 基础安装：https://velero.io/docs/v1.18/basic-install/
- 工作原理：https://velero.io/docs/v1.18/how-velero-works/
- Provider 列表：https://velero.io/docs/v1.18/supported-providers/
- 备份参考：https://velero.io/docs/v1.18/backup-reference/
- 恢复参考：https://velero.io/docs/v1.18/restore-reference/
- 备份 Hook：https://velero.io/docs/v1.18/backup-hooks/
- File System Backup：https://velero.io/docs/v1.18/file-system-backup/
- CSI 支持：https://velero.io/docs/v1.18/csi/
- CSI Snapshot Data Mover：https://velero.io/docs/v1.18/csi-snapshot-data-movement/
- 存储位置：https://velero.io/docs/v1.18/locations/
- 故障排查：https://velero.io/docs/v1.18/troubleshooting/
- Velero v1.18.2 Release：https://github.com/velero-io/velero/releases/tag/v1.18.2
- AWS Plugin Release：https://github.com/velero-io/velero-plugin-for-aws/releases

---

## 27. 总结

Velero 的核心价值不是“导出一份 YAML”，而是把 Kubernetes 资源、持久卷保护、恢复顺序和跨集群迁移组织成一套可操作流程。

生产方案应至少满足：

1. 对象存储与生产集群处于独立故障域；
2. 资源对象、普通卷和数据库分别选择合适的备份方式；
3. Velero、etcd、数据库原生备份和基础设施代码相互补充；
4. 所有备份都有明确 TTL、监控和失败告警；
5. 定期在隔离环境完成真实恢复；
6. 用实际恢复结果衡量 RPO 和 RTO。

只有完成过恢复演练并通过业务验收的备份，才可以认为是有效备份。
