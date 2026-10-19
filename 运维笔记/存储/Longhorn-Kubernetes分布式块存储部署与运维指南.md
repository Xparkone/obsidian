# Longhorn Kubernetes 分布式块存储部署与运维指南

> 资料基线：Longhorn v1.13.0 官方文档，核对日期：2026-10-19。本文命令固定到 v1.13.0；实际执行前按目标 Kubernetes、Linux、Rancher、CRI、CNI、内核和 Longhorn 版本重新核对兼容矩阵。
>
> 适用范围：Rancher 管理的 RKE2/K3s 集群、普通 Kubernetes 集群，以及需要给数据库、消息队列和其他有状态应用提供持久块存储的场景。
>
> 验证边界：本文没有连接或修改真实集群。部署成功必须以组件、CSI、PVC、卷挂载、真实读写和恢复结果为证据，不能只看 Helm 返回 deployed。

## 1. 结论和使用边界

Longhorn 运行在 Kubernetes 节点上，通过 CSI 驱动提供 PV/PVC。一个 Longhorn Volume 由 Engine 和多个 Replica 组成，数据同步复制到多个节点或磁盘；用户通过标准 StorageClass 使用它。

推荐顺序：

1. 准备至少 3 个可承载副本的 Linux 节点，生产环境使用独立 SSD/NVMe 数据盘。
2. 每个节点检查 open-iscsi/iscsid、NFSv4 客户端、mount propagation、内核模块和磁盘。
3. 选择一种安装方式：Rancher Apps、Helm、RKE2/K3s HelmChart 或 GitOps。
4. 验证 longhorn-system、CSIDriver 和 Engine Image，再创建测试 PVC/Pod 做真实读写。
5. 使用自定义 StorageClass 定义副本数、回收策略、节点/磁盘标签和扩容能力。
6. 配置 S3 兼容对象存储或 NFS 作为 Backup Target，完成恢复演练。

Longhorn 解决 Kubernetes 内的持久块存储和副本高可用，不等于备份系统，也不是任意网络文件系统。副本主要处理节点/磁盘故障；备份用于误删除、逻辑损坏、勒索和集群级事故。

适合自建 Kubernetes、RKE2、K3s、边缘机房和中小规模有状态应用。不应把单节点 Longhorn 宣称为高可用；已有高性能 SAN、NVMe-oF 或 Ceph 的核心数据库应先做性能和运维对比。

## 2. 架构

Longhorn 最初由 Rancher Labs 开发，目前是 CNCF Incubating Project。它把存储控制器拆成按卷运行的微服务：每个卷拥有自己的 Engine，Engine 将数据同步写入多个 Replica。Kubernetes 通过 CSI 与 Longhorn 交互，应用只使用 PV、PVC 和 StorageClass。

~~~mermaid
sequenceDiagram
    participant App as 应用 Pod
    participant K as API Server / kubelet
    participant CSI as Longhorn CSI
    participant M as Longhorn Manager
    participant E as Volume Engine
    participant R1 as Replica A
    participant R2 as Replica B
    participant B as S3/NFS Backup Target
    App->>K: 挂载 PVC
    K->>CSI: CreateVolume / Publish / Stage
    CSI->>M: 创建或挂载 Volume
    M->>E: 启动 Engine
    E->>R1: 同步写入
    E->>R2: 同步写入
    App->>E: 读写块设备
    M->>B: Snapshot/RecurringJob 上传 Backup
~~~

| 组件 | 作用 |
|---|---|
| longhorn-manager DaemonSet | 管理节点、磁盘、Volume、Replica、Engine 和 Longhorn CR |
| longhorn-global-manager Deployment | v1.13.0 起承载集群范围控制器，默认 3 副本 |
| Volume Engine | 每个卷一个数据面控制器，暴露块设备并同步 Replica |
| Replica | 一份卷数据和快照链，分布在不同节点或磁盘 |
| Instance Manager | 托管每节点的 Engine 和 Replica 进程 |
| longhorn-csi-plugin | 处理 NodeStage、NodePublish、挂载和卸载 |
| CSI sidecar | provision、attach、resize、snapshot |
| Share Manager | 为 RWX 卷提供 NFS |
| longhorn-ui | UI 管理卷、节点、磁盘、快照和备份 |

默认安装使用 V1 Data Engine，数据保存在文件系统类型磁盘上，默认路径通常是 /var/lib/longhorn。V2 Data Engine 基于 SPDK，需要 IOMMU、HugePages、特定内核模块和块类型磁盘，不建议第一次部署就启用。

## 3. 部署前置条件

### 3.1 版本、节点和工具

Longhorn v1.13.0 安装页面当前写明 Kubernetes >= v1.34；Best Practices 页面列出 v1.33～v1.36 为测试版本，并说明升级到 v1.13.0 的最低版本为 v1.21。这是不同页面的语境差异，落地时按目标版本的 Installation Requirements 和发布说明为准。

~~~bash
kubectl version
kubectl config current-context
kubectl get nodes -o wide
kubectl get storageclass
command -v bash curl findmnt grep awk blkid lsblk
findmnt -o TARGET,FSTYPE,OPTIONS /
uname -a
~~~

Longhorn 组件需要 root 和 privileged 权限，并访问 /dev、/proc、/sys、/lib/modules、/var/lib/kubelet 和数据目录。禁止特权容器或禁止挂载传播的集群不能直接安装。

### 3.2 open-iscsi 和 NFSv4

V1 Data Engine 的每个承载节点都要安装 open-iscsi、运行 iscsid、加载 iscsi_tcp，并使用支持 file extents 的 ext4 或 XFS。

~~~bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y open-iscsi nfs-common
sudo modprobe iscsi_tcp
sudo systemctl enable --now iscsid

# RHEL/Rocky/Oracle Linux
sudo yum install -y iscsi-initiator-utils nfs-utils
sudo modprobe iscsi_tcp
sudo systemctl enable --now iscsid

# SUSE/openSUSE
sudo zypper install -y open-iscsi nfs-client
sudo modprobe iscsi_tcp
sudo systemctl enable --now iscsid

systemctl is-active iscsid
lsmod | grep '^iscsi_tcp'
command -v mount.nfs4
~~~

官方文档提示不要使用 open-iscsi 2.1.12，该版本存在导致卷附加失败的配置变化。执行前检查发行版仓库的实际版本。

### 3.3 磁盘、容量和故障域

生产环境优先使用独立 SSD/NVMe，并稳定挂载到例如 /var/lib/longhorn-data。容量粗略估算：

~~~text
物理空间需求 ≈ 业务实际写入量 × 副本数 + 快照空间 + 重建余量 + 系统预留
~~~

3 个或更多存储节点通常使用副本数 3；2 个节点使用 2；单节点测试使用 1 且没有节点级高可用。根盘至少保留默认 25% 的可用空间；独立数据盘再结合监控调整。不要只根据 PVC 请求量提高 over-provisioning。

### 3.4 网络、标签和预检

确认节点互通、Pod 网络、DNS、时间同步和 MTU 正常，NetworkPolicy 没有阻断 Longhorn 组件；跨可用区时优先规划独立存储网络。

~~~bash
# 以下是变更命令，先评审再执行
kubectl label node <storage-node-1> longhorn-storage=ssd
kubectl taint node <storage-node-1> dedicated=longhorn:NoSchedule
~~~

~~~bash
curl -sSfL -o longhornctl \
  https://github.com/longhorn/cli/releases/download/v1.13.0/longhornctl-linux-amd64
chmod +x longhornctl
./longhornctl --kubeconfig ~/.kube/config check preflight
~~~

若允许工具安装依赖：

~~~bash
./longhornctl --kubeconfig ~/.kube/config \
  --image longhornio/longhorn-cli:v1.13.0 \
  install preflight
./longhornctl --kubeconfig ~/.kube/config check preflight
~~~

不可变发行版可能需要重启后再次运行 install preflight。预检通过不代表网络、磁盘性能、备份和恢复已经成功。

## 4. 部署方式

一个集群只选一种管理方式，不要先用 Rancher App、再用 Helm CLI 接管同一个 release。

### 4.1 Helm CLI（通用推荐）

~~~bash
helm version
helm repo add longhorn https://charts.longhorn.io
helm repo update
helm search repo longhorn/longhorn --versions | head -20
~~~

示例 values：

~~~yaml
defaultSettings:
  defaultReplicaCount: "3"
  storageMinimalAvailablePercentage: "25"
  storageOverProvisioningPercentage: "100"
  replicaAutoBalance: "least-effort"
persistence:
  defaultClass: true
  defaultClassReplicaCount: 3
  defaultFsType: "ext4"
  reclaimPolicy: "Delete"
~~~

~~~bash
helm upgrade --install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --create-namespace \
  --version 1.13.0 \
  --values longhorn-values.yaml \
  --wait --timeout 15m

helm -n longhorn-system status longhorn
helm -n longhorn-system get values longhorn
kubectl -n longhorn-system get pod -o wide
~~~

官方最小命令：

~~~bash
helm install longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --create-namespace \
  --version 1.13.0
~~~

### 4.2 Rancher Apps/Marketplace

1. 进入目标集群的 Apps 或 Apps & Marketplace。
2. 搜索 Longhorn，选择与目标版本对应的 Chart。
3. 使用 longhorn-system Namespace，确认没有重复 release。
4. 在 Values/YAML 中配置副本数、StorageClass、节点选择器、污点容忍和 Ingress。
5. 安装后在 Rancher Shell 执行 kubectl -n longhorn-system get pod。
6. 组件稳定后再创建测试 PVC。

Rancher Catalog App 可能自动创建 rancher-proxy。Helm 或 kubectl 安装的 UI 默认没有认证，不能直接暴露公网，必须使用 Rancher 代理、Ingress 或 Gateway API 配置认证和 TLS。

### 4.3 RKE2/K3s Helm Controller

~~~yaml
apiVersion: helm.cattle.io/v1
kind: HelmChart
metadata:
  name: longhorn-install
  namespace: default
  annotations:
    helmcharts.cattle.io/managed-by: helm-controller
spec:
  chart: longhorn
  repo: https://charts.longhorn.io
  version: v1.13.0
  targetNamespace: longhorn-system
  createNamespace: true
  failurePolicy: abort
~~~

~~~bash
kubectl apply -f longhorn-helmchart.yaml
kubectl get helmchart -A
kubectl get job -A | grep longhorn
kubectl -n longhorn-system get pod -w
~~~

failurePolicy 使用 abort，让失败安装保留现场并重试；删除 HelmChart CR 会触发卸载，生产环境不要未经审批直接删除。

### 4.4 kubectl 官方清单

~~~bash
kubectl apply -f \
  https://raw.githubusercontent.com/longhorn/longhorn/v1.13.0/deploy/longhorn.yaml
kubectl -n longhorn-system get pod -w
~~~

清单方式需要自行管理版本、初始设置、Ingress、Backup Target 和卸载步骤，生产更适合 Helm 或 GitOps。

### 4.5 安装成功的证据

~~~bash
kubectl -n longhorn-system get pod -o wide
kubectl -n longhorn-system get ds,deploy,sts,svc
kubectl get crd | grep longhorn.io
kubectl get csidriver driver.longhorn.io -o yaml
kubectl get storageclass
~~~

检查 manager、CSI plugin、Engine Image、Global Manager、CSI sidecar 均 Ready，且没有持续 ImagePullBackOff、CrashLoopBackOff、挂载失败或 webhook 错误。

## 5. 访问 UI

临时访问：

~~~bash
kubectl -n longhorn-system port-forward svc/longhorn-frontend 8080:80
~~~

浏览器访问 http://127.0.0.1:8080。它只适合临时排障，不适合作为生产入口。

生产入口应具备 TLS、认证、管理员访问控制、审计日志和网络策略。新部署优先使用 Rancher 代理、Traefik、HAProxy 或 Gateway API；Longhorn 官方已提示 ingress-nginx 进入退休流程。

~~~yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: longhorn-ui
  namespace: longhorn-system
spec:
  ingressClassName: <your-ingress-class>
  tls:
  - hosts:
    - longhorn.<example-domain>
    secretName: longhorn-ui-tls
  rules:
  - host: longhorn.<example-domain>
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: longhorn-frontend
            port:
              number: 80
~~~

## 6. 使用 PVC

### 6.1 StorageClass

生产建议复制默认 longhorn 类为业务专用类，不要直接修改默认类。示例：

~~~yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: longhorn-replicated
provisioner: driver.longhorn.io
allowVolumeExpansion: true
reclaimPolicy: Retain
volumeBindingMode: Immediate
parameters:
  numberOfReplicas: "3"
  staleReplicaTimeout: "2880"
  fsType: ext4
  dataLocality: disabled
  replicaAutoBalance: ignored
~~~

关键参数：numberOfReplicas 控制副本数；nodeSelector/diskSelector 限定故障域和盘型；reclaimPolicy 决定 PVC 删除后的行为；allowVolumeExpansion 控制在线扩容；recurringJobSelector 可给新卷自动绑定任务。

~~~bash
kubectl apply -f longhorn-storageclass.yaml
kubectl get storageclass longhorn-replicated -o yaml
~~~

### 6.2 PVC 和测试 Pod

~~~yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: demo-data
  namespace: demo
spec:
  accessModes:
  - ReadWriteOnce
  storageClassName: longhorn-replicated
  resources:
    requests:
      storage: 20Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: volume-test
  namespace: demo
spec:
  containers:
  - name: shell
    image: busybox:1.36
    command: ["sh", "-c", "echo ready; sleep 3600"]
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: demo-data
~~~

~~~bash
kubectl create namespace demo
kubectl apply -f demo-pvc-pod.yaml
kubectl -n demo get pvc demo-data -w
kubectl -n demo wait --for=condition=Ready pod/volume-test --timeout=180s
kubectl -n demo exec volume-test -- sh -c \
  'date -u > /data/probe.txt && sync && cat /data/probe.txt'
kubectl -n longhorn-system get volumes.longhorn.io -o wide
~~~

重启 Pod 再读回文件：

~~~bash
kubectl -n demo delete pod volume-test
kubectl apply -f demo-pvc-pod.yaml
kubectl -n demo wait --for=condition=Ready pod/volume-test --timeout=180s
kubectl -n demo exec volume-test -- cat /data/probe.txt
~~~

PVC Bound 只代表 PV 已绑定，不代表卷有足够健康副本、已附加、已挂载或应用完成真实写入。

### 6.3 RWO、RWOP、RWX

- RWO：一个节点以读写方式挂载，同节点多个 Pod 仍可能共享。
- RWOP：单个 Pod 独占，需要确认 Kubernetes/CSI 版本支持。
- RWX：通过 Share Manager/NFS 提供，每个目标节点需要 NFSv4 客户端。

~~~yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: shared-data
  namespace: demo
spec:
  accessModes: [ReadWriteMany]
  storageClassName: longhorn-replicated
  resources:
    requests:
      storage: 10Gi
~~~

~~~bash
kubectl -n longhorn-system get pod -l longhorn.io/component=share-manager -o wide
kubectl -n demo describe pvc shared-data
~~~

### 6.4 在线扩容

~~~bash
kubectl -n demo patch pvc demo-data --type merge \
  -p '{"spec":{"resources":{"requests":{"storage":"40Gi"}}}}'
kubectl -n demo get pvc demo-data -w
kubectl get pv
kubectl -n demo exec volume-test -- df -h /data
~~~

验收 PVC spec、PVC status.capacity、Longhorn Volume size 和 Pod 内文件系统容量。Longhorn 不支持安全缩小卷，误扩大后要新建较小卷并迁移数据。

## 7. 快照、备份和恢复

### 7.1 快照和备份的区别

| 功能 | 保存位置 | 用途 |
|---|---|---|
| Longhorn Snapshot | 本地 Replica 快照链 | 快速回滚，集群全损时不可用 |
| CSI VolumeSnapshot | Kubernetes 对象 + Longhorn Snapshot | 标准 API、克隆、恢复 |
| Longhorn Backup | S3/NFS/SMB/Azure Blob | 异地和跨集群恢复 |
| System Backup | Backup Target 中的 Longhorn 系统资源 | 恢复 Longhorn 控制面状态，不是全量集群备份 |

### 7.2 Longhorn Snapshot 和 CSI Snapshot

~~~yaml
apiVersion: longhorn.io/v1beta2
kind: Snapshot
metadata:
  name: demo-data-before-change
  namespace: longhorn-system
spec:
  volume: <longhorn-volume-name>
  createSnapshot: true
~~~

~~~bash
kubectl apply -f longhorn-snapshot.yaml
kubectl -n longhorn-system get snapshots.longhorn.io
kubectl get crd volumesnapshots.snapshot.storage.k8s.io
kubectl get crd volumesnapshotcontents.snapshot.storage.k8s.io
kubectl get deploy -A | grep snapshot-controller
~~~

如果发行版没有 CSI Snapshot CRD/controller，按目标 Longhorn 版本兼容的 external-snapshotter 安装，不要直接使用旧 YAML。

~~~yaml
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: longhorn-snapshot-vsc
driver: driver.longhorn.io
deletionPolicy: Delete
parameters:
  type: snap
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: demo-data-snapshot
  namespace: demo
spec:
  volumeSnapshotClassName: longhorn-snapshot-vsc
  source:
    persistentVolumeClaimName: demo-data
~~~

~~~bash
kubectl apply -f demo-volume-snapshot.yaml
kubectl -n demo get volumesnapshot demo-data-snapshot -w
kubectl -n demo describe volumesnapshot demo-data-snapshot
~~~

用快照恢复的新 PVC，dataSource 指向 VolumeSnapshot，容量不能小于源卷。恢复后必须检查新 PV、Longhorn Volume 和 Pod 真实读写。

### 7.3 Backup Target

Longhorn 支持 NFS、SMB/CIFS、S3 兼容存储、AWS S3 和 Azure Blob。生产优先选择权限隔离、版本保护和跨故障域的对象存储。备份生命周期由 Longhorn 管理，不要在 Backup Target 侧配置冲突的删除策略。

~~~yaml
apiVersion: v1
kind: Secret
metadata:
  name: longhorn-backup-credentials
  namespace: longhorn-system
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "<redacted-access-key>"
  AWS_SECRET_ACCESS_KEY: "<redacted-secret-key>"
  AWS_ENDPOINTS: "https://s3.<example-domain>"
~~~

Backup Target URL 示例：

~~~text
s3://<bucket-name>@<region>/longhorn/
~~~

URL 末尾的 / 不要省略；MinIO 还要确认 endpoint、路径风格、TLS 和 bucket 权限。配置 UI 的 Backup and Restore → Backup Targets 后，执行：

~~~bash
kubectl -n longhorn-system get backupstores.longhorn.io
kubectl -n longhorn-system get backups.longhorn.io
kubectl -n longhorn-system describe backup.longhorn.io <backup-name>
~~~

验收必须包括 Backup 成功、外部对象存在、从 Backup 恢复新卷并读回业务文件。

### 7.4 Recurring Job

~~~yaml
apiVersion: longhorn.io/v1beta2
kind: RecurringJob
metadata:
  name: daily-backup
  namespace: longhorn-system
spec:
  cron: "0 2 * * *"
  task: backup
  retentionPolicy: count-based
  retain: 7
  concurrency: 1
~~~

~~~bash
kubectl apply -f longhorn-recurring-job.yaml
kubectl -n longhorn-system get recurringjob.longhorn.io daily-backup -o yaml
kubectl -n longhorn-system label volume.longhorn.io/<longhorn-volume-name> \
  recurring-job.longhorn.io/daily-backup=enabled
~~~

任务会先创建快照，再上传 Backup。没有 Backup Target、卷 Faulted 或网络/权限异常时，不会得到可恢复备份。v1.13.0 支持 age-based retention，例如 retainAge: 720h，正式使用前确认目标版本支持。

### 7.5 System Backup

~~~bash
kubectl -n longhorn-system get systembackup
kubectl -n longhorn-system get systemrestore
~~~

升级前创建 System Backup 并等待 Ready；跨 major/minor 版本直接恢复通常不受支持。System Backup 不包含完整 Kubernetes 集群、etcd 或应用层数据。

## 8. 节点和副本运维

~~~bash
kubectl -n longhorn-system get nodes.longhorn.io -o wide
kubectl -n longhorn-system get volumes.longhorn.io -o wide
kubectl -n longhorn-system get replicas.longhorn.io -o wide
kubectl -n longhorn-system get engineimages.longhorn.io -o wide
~~~

增加磁盘的推荐流程：主机分区和格式化、写入 /etc/fstab、稳定挂载、确认重启后仍存在、在 Longhorn Node/Disk 中添加、用测试卷验证。

~~~bash
findmnt /var/lib/longhorn-data
df -hT /var/lib/longhorn-data
lsblk -f
~~~

节点维护顺序：查看卷和 Replica → 禁止节点/磁盘调度 → Evict Replica 并等待补齐 → 迁移工作负载并等待 detach → cordon/drain/关机 → 维护后确认 Engine Image、磁盘和副本恢复。

状态含义：

- Healthy：满足副本设置。
- Degraded：仍可服务，但健康副本少于期望值。
- Faulted：所有副本不可用或卷无法服务，有数据丢失风险。
- Detached：未挂载，可能正常也可能异常。
- FilesystemReadOnly：挂载点只读，常见原因是网络中断、磁盘延迟或文件系统保护。

Faulted 卷不要直接删 Replica、清理 /var/lib/longhorn 或强卸载。先保存 Support Bundle、Manager/Engine 日志和卷 YAML。

## 9. 升级和卸载

### 9.1 升级

Longhorn v1.5 起只支持逐 minor 升级，例如 1.12.x → 1.13.x，不支持跳过中间 minor，也不支持降级。

升级前做 System Backup 和业务备份，确认没有 Faulted 卷、失败 Backing Image 或持续重建副本，检查目标版本兼容性，并在测试集群演练。

~~~bash
helm repo update
helm upgrade longhorn longhorn/longhorn \
  --namespace longhorn-system \
  --version 1.13.0 \
  --values longhorn-values.yaml \
  --wait --timeout 20m
helm -n longhorn-system history longhorn
kubectl -n longhorn-system get pod
kubectl get csidriver driver.longhorn.io
kubectl -n longhorn-system get volumes.longhorn.io -o wide
kubectl -n longhorn-system get replicas.longhorn.io -o wide
~~~

Manager 升级完成后还要检查并按需升级 Volume Engine；V2 Instance Manager 有单独的升级前置条件。升级后重启测试 Pod 并读回文件。

### 9.2 卸载

卸载会删除 Longhorn 数据和 CRD。先迁移/删除工作负载、PVC、PV、StorageClass，并确认 Backup Target 有可恢复备份。

~~~bash
helm -n longhorn-system list -a
kubectl get pvc -A | grep -i longhorn || true
kubectl -n longhorn-system get volumes.longhorn.io

# 只有变更审批确认后才执行
kubectl -n longhorn-system patch lhs deleting-confirmation-flag \
  --type merge -p '{"value":"true"}'
helm uninstall longhorn -n longhorn-system
~~~

kubectl 清单方式：

~~~bash
kubectl create -f \
  https://raw.githubusercontent.com/longhorn/longhorn/v1.13.0/uninstall/uninstall.yaml
kubectl -n longhorn-system get job/longhorn-uninstall -w
kubectl delete -f \
  https://raw.githubusercontent.com/longhorn/longhorn/v1.13.0/deploy/longhorn.yaml
kubectl delete -f \
  https://raw.githubusercontent.com/longhorn/longhorn/v1.13.0/uninstall/uninstall.yaml
~~~

不要一开始只删除 deploy 清单。卸载卡在 finalizer 或 webhook 时，先看 uninstall Job 和 Manager 日志，不要在没有确认数据去向时强删 CRD finalizer。

## 10. 故障排查 Runbook

证据顺序：应用 Pod → PVC/PV → Longhorn Volume/Replica/Engine → CSI sidecar/node plugin → Manager/Instance Manager/Engine → 节点磁盘、内核、iscsid、NFS、kubelet、网络 → Backup Target。

~~~bash
kubectl -n <namespace> describe pod <pod-name>
kubectl -n <namespace> describe pvc <pvc-name>
kubectl describe pv <pv-name>
kubectl -n longhorn-system get volumes.longhorn.io -o wide
kubectl -n longhorn-system get replicas.longhorn.io -o wide
kubectl -n longhorn-system get events --sort-by=.lastTimestamp
kubectl -n longhorn-system logs daemonset/longhorn-manager --tail=200
kubectl -n longhorn-system logs daemonset/longhorn-csi-plugin --all-containers --tail=200

# 节点侧
sudo systemctl status iscsid
sudo journalctl -u kubelet --since "30 min ago"
sudo dmesg -T | tail -200
~~~

PVC Pending 常见原因：StorageClass/provisioner 错误、CSI provisioner 不健康、磁盘不足、副本数大于存储节点数、nodeSelector/diskSelector 或反亲和没有匹配、Engine Image 未 Ready、taint/NetworkPolicy/特权权限/iscsid 不满足。

FailedAttachVolume 或 MountVolume.SetUp failed 时重点看同节点 CSI plugin、kubelet、Engine 日志，以及旧挂载点、磁盘满、文件系统错误和 iSCSI session。不要删除 Volume CR 或手工删除 /var/lib/longhorn。

RWX 失败时确认 share-manager、mount.nfs4、NFS 网络、NetworkPolicy、防火墙和 nfsOptions。Backup 失败时检查 bucket 权限、URL 末尾 /、Secret 字段、TLS、DNS、出口和时间同步。

卸载 webhook 报错时先确认 deleting-confirmation-flag、卷/PVC/PV/VolumeAttachment 和 uninstall Job；Webhook Service 已删除但配置残留时优先恢复同版本 Longhorn 后按正常流程卸载。

Support Bundle 可收集配置、CR、Pod 状态和日志；节点 dmesg、磁盘 SMART、kubelet 日志需要单独采集。交付前删除 Secret 值、云密钥、Cookie、完整认证 Header 和敏感 URL。

## 11. 监控和上线验收

建议监控 Node Ready、磁盘空间、DiskPressure、Longhorn 节点/磁盘 schedulable、storageAvailable、卷 Degraded/Faulted/FilesystemReadOnly、Replica 重建、CSI 错误、最近备份成功时间和 TooManySnapshots。

生产验收：

- [ ] 版本、CRI、CNI、OS、内核和兼容性已记录。
- [ ] open-iscsi、iscsid、iscsi_tcp 和 NFSv4 已验证。
- [ ] mount propagation、root/privileged 权限和独立数据盘满足要求。
- [ ] Manager、Global Manager、CSI、Engine Image、UI 正常。
- [ ] driver.longhorn.io 存在，StorageClass 参数已确认。
- [ ] PVC Bound，Pod 能挂载、写入，重启后文件仍在。
- [ ] 副本数、健康副本和扩容结果符合预期。
- [ ] UI 只通过认证后的代理、Ingress 或 Gateway API 暴露。
- [ ] 手动 Backup 成功，外部对象可见，恢复新卷并读回文件。
- [ ] Recurring Job、System Backup、RPO/RTO 和责任人已确认。

## 12. 常用命令

~~~bash
kubectl -n longhorn-system get pod -o wide
kubectl -n longhorn-system get ds,deploy,sts,svc
kubectl -n longhorn-system get nodes.longhorn.io -o wide
kubectl -n longhorn-system get volumes.longhorn.io -o wide
kubectl -n longhorn-system get replicas.longhorn.io -o wide
kubectl -n longhorn-system get engineimages.longhorn.io -o wide
kubectl get storageclass
kubectl get pv
kubectl get pvc -A
kubectl get volumeattachment
kubectl get csidriver driver.longhorn.io
kubectl -n longhorn-system get snapshots.longhorn.io
kubectl -n longhorn-system get recurringjob.longhorn.io
kubectl -n longhorn-system get backups.longhorn.io
kubectl -n longhorn-system get systembackup
kubectl -n longhorn-system get systemrestore
helm -n longhorn-system list -a
helm -n longhorn-system status longhorn
helm -n longhorn-system history longhorn
~~~

## 13. 与现有笔记的衔接

- Kubernetes PV/PVC/StorageClass、CSI 生命周期和 VolumeSnapshot：[K8s-存储深入.md](../容器编排/K8s-存储深入.md)。
- Kubernetes 资源和常用操作：[Kubernetes-从入门到生产实践：组件资源与常用操作指南.md](../容器编排/Kubernetes-从入门到生产实践：组件资源与常用操作指南.md)。
- 跨集群备份和 Velero：[Velero-Kubernetes备份恢复与迁移指南.md](../容器编排/Velero-Kubernetes备份恢复与迁移指南.md)。
- Rancher 和 Harvester：[Harvester-HCI超融合平台详解.md](../云服务/Harvester-HCI超融合平台详解.md)。

## 14. 官方资料

- [What is Longhorn](https://longhorn.io/docs/1.13.0/what-is-longhorn/)
- [Architecture and Concepts](https://longhorn.io/docs/1.13.0/concepts/)
- [Installation Requirements](https://longhorn.io/docs/1.13.0/deploy/install/)
- [Install with Helm](https://longhorn.io/docs/1.13.0/deploy/install/install-with-helm/)
- [Install with Helm Controller](https://longhorn.io/docs/1.13.0/deploy/install/install-with-helm-controller/)
- [Accessing the UI](https://longhorn.io/docs/1.13.0/deploy/accessing-the-ui/)
- [Storage Class Parameters](https://longhorn.io/docs/1.13.0/references/storage-class-parameters/)
- [Recurring Snapshots and Backups](https://longhorn.io/docs/1.13.0/snapshots-and-backups/scheduling-backups-and-snapshots/)
- [Setting a Backup Target](https://longhorn.io/docs/1.13.0/snapshots-and-backups/backup-and-restore/set-backup-target/)
- [Upgrade](https://longhorn.io/docs/1.13.0/deploy/upgrade/)
- [Uninstall Longhorn](https://longhorn.io/docs/1.13.0/deploy/uninstall/)
- [Troubleshooting](https://longhorn.io/docs/1.13.0/troubleshoot/troubleshooting/)
- [Support Bundle](https://longhorn.io/docs/1.13.0/troubleshoot/support-bundle/)

> 版本提醒：Longhorn 文档、Helm values、CSI sidecar 和 Kubernetes 版本要求会变化。执行前优先打开目标版本官方文档，重新核对安装要求、StorageClass 参数、Snapshot CRD、升级路径和卸载步骤。
