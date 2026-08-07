# DeepFlow v7.0 部署与使用指南

> 文档版本：1.0  
> 适用产品：DeepFlow Community Edition  
> 目标版本：DeepFlow LTS v7.0 系列  
> 适用读者：平台工程师、运维工程师、SRE、云原生开发人员  
> 更新日期：2026-07-30

## 1. 文档概述

本文介绍 DeepFlow 社区版的架构、部署、接入、基础使用和日常运维，覆盖以下场景：

- 在 Kubernetes 中部署完整的 DeepFlow Server、Agent、ClickHouse、MySQL 和 Grafana。
- 使用 All-in-One 模式快速搭建体验环境。
- 使用 Docker Compose 搭建单机体验环境。
- 在其他 Kubernetes 集群中部署 DeepFlow Agent。
- 在 Linux 传统服务器或云主机中部署 DeepFlow Agent。
- 使用 AutoMetrics、AutoTracing、AutoProfiling 和 Grafana 分析应用。
- 接入 Prometheus 与 OpenTelemetry 数据。
- 执行升级、卸载、故障排查和生产环境优化。

阅读本文后，读者应能够独立完成一个 DeepFlow 社区版环境的部署，并确认采集器、数据链路和查询界面工作正常。

### 1.1 核心结论

DeepFlow 的部署分为两个部分：

1. **DeepFlow Server**：负责 Agent 管理、标签注入、数据接收、存储和查询。生产环境应部署在 Kubernetes 中。
2. **DeepFlow Agent**：部署在被观测的 Kubernetes Node 或 Linux 主机上，使用 eBPF/cBPF 等技术采集应用、系统和网络观测数据。

如果只是学习和验证功能，推荐使用 Kubernetes All-in-One。生产环境应使用持久化存储，并根据数据量规划 MySQL、ClickHouse 和 DeepFlow Server 的高可用方案。Docker Compose 仅适合体验或测试。

## 2. 核心概念与架构

### 2.1 主要组件

| 组件 | 主要职责 |
| --- | --- |
| DeepFlow Agent | 采集应用调用、网络性能、函数性能剖析和资源标签等数据 |
| Controller | 管理 Agent，向 Agent 下发配置，同步资源和标签信息 |
| Ingester | 接收 Agent 上报的数据并写入 ClickHouse |
| Querier | 提供 SQL、PromQL 等查询接口 |
| Labeler | 为观测数据计算并注入统一的资源属性标签 |
| ClickHouse | 存储流日志、指标、追踪和剖析等观测数据 |
| MySQL | 存储 DeepFlow 元数据和配置 |
| Grafana | 展示服务拓扑、指标、追踪和持续性能剖析结果 |
| deepflow-ctl | 管理 Domain、Agent、Agent Group 和采集配置的命令行工具 |

### 2.2 数据处理流程

```text
应用进程 / Pod / Linux 主机
          │
          │ eBPF、cBPF、Prometheus、OTLP
          ▼
   DeepFlow Agent
          │
          ├── 控制面：注册、心跳、拉取配置
          └── 数据面：发送指标、流日志、追踪、剖析数据
                         │
                         ▼
                  DeepFlow Server
                         │
              标签注入、关联、聚合
                         │
                         ▼
                    ClickHouse
                         │
                         ▼
                 Querier / Grafana
```

### 2.3 关键能力

- **AutoMetrics**：无需修改业务代码，自动生成请求量、错误量、时延等 RED 指标，以及吞吐、重传、建连异常等网络指标。
- **AutoTracing**：通过 eBPF 自动生成系统调用和网络调用 Span，并可与 OpenTelemetry 的应用 Span 关联。
- **AutoProfiling**：持续采集 On-CPU 等函数调用栈，用火焰图定位 CPU 热点。
- **AutoTagging**：将 Kubernetes 资源、云资源和自定义 Label 自动注入观测数据。
- **SmartEncoding**：统一编码和关联不同来源的观测信号，降低标签存储和查询成本。

## 3. 前置条件

### 3.1 版本约定

本文示例使用 LTS Chart：

```bash
export DEEPFLOW_CHART_VERSION="7.0.014"
export DEEPFLOW_MAJOR_VERSION="v7.0"
```

部署前应查询仓库中实际可用的 LTS 版本：

```bash
helm search repo deepflow/deepflow --versions
helm search repo deepflow/deepflow-agent --versions
```

Server、Agent 和 `deepflow-ctl` 应尽量保持同一大版本。Agent 版本不能高于 Server 版本，否则可能出现注册或数据上报异常。

### 3.2 Kubernetes 环境要求

建议准备：

- 一个可正常调度工作负载的 Kubernetes 集群。
- Helm 3。
- `kubectl` 已配置，并具有创建 Namespace、DaemonSet、Deployment、Service、ConfigMap、Secret、PVC、ClusterRole 等资源的权限。
- 可用的默认 StorageClass，或明确指定一个 StorageClass。
- 各节点时间已通过 NTP/Chrony 同步。
- 节点可以访问镜像仓库和 Helm Chart 仓库。

体验环境建议至少提供：

```text
CPU：4 Core
内存：8 GiB
磁盘：建议 100 GiB 或以上
```

生产资源无法仅按 Agent 数量估算，还取决于请求量、采集协议、保留周期、是否保存原始流日志和查询并发。上线前必须使用真实流量压测。

### 3.3 Linux 内核与权限要求

DeepFlow 的 eBPF 能力依赖内核版本和内核配置。官方 v7.0 文档给出的典型兼容范围包括：

- CentOS 7.9、Red Hat 7.6：特定的 `3.10.0-940+` 内核。
- 通用发行版：不同 eBPF Hook 能力从 Linux 4.14 起逐步可用。
- 其他主流发行版：建议使用 Linux 5.8 或更高版本。
- ARM 环境需要核对发行版和内核支持情况。

部署前检查：

```bash
uname -a
uname -r
mount | grep debugfs
cat /proc/sys/kernel/kptr_restrict
cat /proc/sys/net/core/bpf_jit_enable 2>/dev/null || true
```

关键要求：

- Agent 需要读取 `/sys/kernel/debug`。
- Linux 5.8 以下通常需要 `SYS_ADMIN`；5.8 及以上可根据环境使用 `BPF`、`PERFMON` 等更细粒度能力。
- `kernel.kptr_restrict=2` 会导致部分持续剖析能力不可用。
- Kubernetes Agent 默认使用 DaemonSet，并需要访问宿主机网络、进程和内核相关目录。

不要为了绕过错误盲目关闭节点安全策略。应先确认所用 DeepFlow Chart 对当前内核、容器运行时、SELinux、AppArmor 和 Pod Security 的要求。

### 3.4 网络要求

默认场景下，Agent 与 Server 的关键通信端口为：

| 场景 | 控制面 | 数据面 |
| --- | ---: | ---: |
| Agent 与 Server 位于同一个 K8s 集群 | 20035 | 20033 |
| Agent 与 Server 位于不同集群或主机 | 30035 | 30033 |

跨集群或传统主机接入时，应确认：

```bash
nc -vz <SERVER_NODE_IP> 30035
nc -vz <SERVER_NODE_IP> 30033
```

若 Server 使用 LoadBalancer，应测试 LoadBalancer VIP。若使用 NodePort，应测试一个实际运行 DeepFlow Server 且网络稳定的 Node IP。

## 4. 部署方式选择

| 方式 | 适用场景 | 优点 | 限制 |
| --- | --- | --- | --- |
| Kubernetes All-in-One | 学习、演示、功能验证 | 部署简单、组件完整 | 单节点本地存储，不适合生产 |
| Kubernetes 标准部署 | 单集群或生产环境 | 支持持久化和多副本 | 需要规划存储与容量 |
| Docker Compose | 无 Kubernetes 的临时体验 | 启动快 | Server 单副本，缺少 K8s 选主，不推荐生产 |
| 独立 K8s Agent | 监控其他 Kubernetes 集群 | DaemonSet 自动覆盖节点 | 需要跨集群网络和集群标识 |
| Linux 主机 Agent | 监控云主机、虚拟机、物理机 | 无需应用插桩 | 需配置 Host Domain、Agent Group 和主机网段 |

## 5. Kubernetes All-in-One 快速部署

### 5.1 添加 Helm 仓库

海外或可直接访问 GitHub、Docker Hub 的环境：

```bash
helm repo add deepflow https://deepflowio.github.io/deepflow
helm repo update deepflow
```

中国大陆网络环境可使用阿里云仓库：

```bash
helm repo add deepflow \
  https://deepflow-ce.oss-cn-beijing.aliyuncs.com/chart/stable
helm repo update deepflow
```

预期结果：`helm search repo deepflow` 能看到 `deepflow` 和 `deepflow-agent` Chart。

### 5.2 创建 All-in-One 配置

创建 `values-all-in-one.yaml`：

```yaml
global:
  # 使用节点本地存储，适用于体验环境。
  allInOneLocalStorage: true
```

使用阿里云镜像时改为：

```yaml
global:
  allInOneLocalStorage: true
  image:
    repository: registry.cn-beijing.aliyuncs.com/deepflow-ce
```

### 5.3 安装

```bash
helm upgrade --install deepflow \
  -n deepflow \
  deepflow/deepflow \
  --version "${DEEPFLOW_CHART_VERSION}" \
  --create-namespace \
  -f values-all-in-one.yaml
```

预期结果：Helm Release 状态为 `deployed`。

```bash
helm list -n deepflow
kubectl get pods -n deepflow -o wide
kubectl get svc -n deepflow
```

等待所有工作负载就绪：

```bash
kubectl wait \
  --for=condition=Ready pod \
  --all \
  -n deepflow \
  --timeout=600s
```

如果超时，不要重复安装。先检查未就绪 Pod：

```bash
kubectl get pods -n deepflow
kubectl describe pod -n deepflow <POD_NAME>
kubectl logs -n deepflow <POD_NAME> --all-containers --prefix
```

## 6. Kubernetes 标准部署

### 6.1 配置持久化存储

生产或长期测试环境应使用 PersistentVolume。查看 StorageClass：

```bash
kubectl get storageclass
```

创建 `values-production.yaml`：

```yaml
global:
  # 替换为集群中真实存在的 StorageClass。
  storageClass: "your-storage-class"

  # 该值用于控制部分核心组件副本数。
  # 最终副本和存储拓扑应结合 Chart values 与容量设计确认。
  replicas: 1
```

如果使用阿里云镜像：

```yaml
global:
  storageClass: "your-storage-class"
  replicas: 1
  image:
    repository: registry.cn-beijing.aliyuncs.com/deepflow-ce

grafana:
  image:
    repository: registry.cn-beijing.aliyuncs.com/deepflow-ce/grafana
```

查看 Chart 的全部可配置项：

```bash
helm show values deepflow/deepflow \
  --version "${DEEPFLOW_CHART_VERSION}" > values-reference.yaml
```

### 6.2 安装并验证

```bash
helm upgrade --install deepflow \
  -n deepflow \
  deepflow/deepflow \
  --version "${DEEPFLOW_CHART_VERSION}" \
  --create-namespace \
  -f values-production.yaml
```

检查 PVC：

```bash
kubectl get pvc -n deepflow
kubectl get pv
```

所有需要持久化的 PVC 应处于 `Bound`。若为 `Pending`：

```bash
kubectl describe pvc -n deepflow <PVC_NAME>
kubectl get storageclass <STORAGE_CLASS> -o yaml
```

### 6.3 生产数据库建议

生产环境可使用托管 MySQL 8.0 或更高版本，并提前创建：

```text
deepflow
grafana
```

示例：

```yaml
global:
  externalMySQL:
    enabled: true
    ip: 10.1.2.3
    port: 3306
    username: deepflow
    password: "REPLACE_WITH_SECRET"

mysql:
  enabled: false
```

不要将真实密码直接提交到 Git。应使用受控的 Helm values、Secret 管理系统或 CI/CD 密钥注入机制。

托管 ClickHouse 应至少满足官方兼容版本要求，并提前创建 DeepFlow 所需数据库。ClickHouse 与 MySQL 的网络、认证、集群名称、存储策略需要按实际环境配置。该部分对数据安全和升级影响较大，生产实施前应单独完成架构评审。

## 7. Docker Compose 体验部署

### 7.1 使用限制

Docker Compose 方式不推荐用于生产，原因包括：

- DeepFlow Server 在 Kubernetes 中依赖 Lease 实现选主和多副本高可用。
- Compose 模式通常只能运行单 Server 副本。
- 配套 ClickHouse 通常为单分片，扩展性和查询性能受限。
- 宿主机故障会同时影响计算和存储。

### 7.2 安装

准备至少 4C8G 的 Linux 主机，并安装 Docker Engine 和 Docker Compose Plugin。

```bash
wget \
  https://deepflow-ce.oss-cn-beijing.aliyuncs.com/pkg/docker-compose/latest/linux/deepflow-docker-compose.tar

tar -zxf deepflow-docker-compose.tar
cd deepflow-docker-compose
```

修改 `.env`：

```dotenv
DEEPFLOW_VERSION=v7.0
NODE_IP_FOR_DEEPFLOW=192.168.101.116
```

`NODE_IP_FOR_DEEPFLOW` 必须是其他主机能够访问的地址，不能误填为仅容器内部可见的 IP。

启动：

```bash
docker compose -f docker-compose.yaml up -d
docker compose -f docker-compose.yaml ps
```

查看日志：

```bash
docker compose -f docker-compose.yaml logs --since=10m
```

Grafana 默认访问地址：

```text
http://<NODE_IP_FOR_DEEPFLOW>:3000
```

默认凭据：

```text
用户名：admin
密码：deepflow
```

首次登录后应立即修改密码。

## 8. 安装 deepflow-ctl

建议将 `deepflow-ctl` 安装在能够访问 DeepFlow Server 的管理节点：

```bash
export DEEPFLOW_MAJOR_VERSION="v7.0"

sudo curl -o /usr/bin/deepflow-ctl \
  "https://deepflow-ce.oss-cn-beijing.aliyuncs.com/bin/ctl/${DEEPFLOW_MAJOR_VERSION}/linux/$(arch | sed 's|x86_64|amd64|' | sed 's|aarch64|arm64|')/deepflow-ctl"

sudo chmod a+x /usr/bin/deepflow-ctl
deepflow-ctl --version
```

常用检查命令：

```bash
deepflow-ctl agent list
deepflow-ctl agent-group list
deepflow-ctl domain list
deepflow-ctl agent-group-config list
```

如果命令无法连接 Server，应检查 `deepflow-ctl` 的连接配置、当前主机到 Server 的网络以及 DeepFlow Server Pod 状态。

## 9. 部署其他 Kubernetes 集群的 Agent

本节假设 DeepFlow Server 已经运行，需要监控另一个 Kubernetes 集群。

### 9.1 确定 Server 地址

如果 Server 使用默认 NodePort，填写一个或多个相对固定的 Server Node IP。如果使用 LoadBalancer，则填写 VIP：

```bash
kubectl get svc -n deepflow
kubectl get nodes -o wide
```

从目标集群节点验证：

```bash
nc -vz 10.1.2.3 30035
nc -vz 10.1.2.3 30033
```

### 9.2 确定集群标识

DeepFlow 默认可以根据 Kubernetes ServiceAccount CA 区分集群。多个集群若复用了同一 CA，或者希望明确指定名称，应先创建 Kubernetes Domain：

创建 `custom-domain.yaml`：

```yaml
name: beijing-prod-k8s
type: kubernetes
config:
  # 使用默认全局 Region 标识。
  region_uuid: ffffffff-ffff-ffff-ffff-ffffffffffff
  controller_ip: 127.0.0.1
  sync_timer: 60
```

执行：

```bash
deepflow-ctl domain create -f custom-domain.yaml
deepflow-ctl domain list beijing-prod-k8s
```

记录输出中的集群 ID。

### 9.3 创建 Agent values

在目标 Kubernetes 集群创建 `values-agent.yaml`：

```yaml
deepflowServerNodeIPS:
  - 10.1.2.3
  - 10.4.5.6

clusterNAME: beijing-prod-k8s

# 如果已手工创建 Domain，在此填写对应 Cluster ID。
deepflowK8sClusterID: "REPLACE_WITH_CLUSTER_ID"
```

中国大陆镜像示例：

```yaml
image:
  repository: registry.cn-beijing.aliyuncs.com/deepflow-ce/deepflow-agent

deepflowServerNodeIPS:
  - 10.1.2.3

clusterNAME: beijing-prod-k8s
deepflowK8sClusterID: "REPLACE_WITH_CLUSTER_ID"
```

### 9.4 安装 Agent

确认 `kubectl` 当前 Context 指向目标集群：

```bash
kubectl config current-context
```

安装：

```bash
helm upgrade --install deepflow-agent \
  -n deepflow \
  deepflow/deepflow-agent \
  --version "${DEEPFLOW_CHART_VERSION}" \
  --create-namespace \
  -f values-agent.yaml
```

验证 DaemonSet：

```bash
kubectl get daemonset -n deepflow
kubectl get pods -n deepflow -o wide
```

DaemonSet 的 `DESIRED`、`CURRENT`、`READY` 应基本一致。被污点、节点选择器或平台架构排除的节点需要单独核对。

在 Server 管理节点确认注册：

```bash
deepflow-ctl agent list
```

## 10. 部署 Linux/云主机 Agent

### 10.1 配置 DeepFlow Server 识别主机网段

默认私网范围通常包括：

```yaml
local_ip_ranges:
  - 10.0.0.0/8
  - 172.16.0.0/12
  - 192.168.0.0/16
  - 169.254.0.0/15
  - 224.0.0.0-240.255.255.255
```

如果被监控主机使用其他地址，例如 `100.42.32.213`，需要将其网段加入 Server values：

```yaml
configmap:
  server.yaml:
    controller:
      genesis:
        local_ip_ranges:
          - 10.0.0.0/8
          - 172.16.0.0/12
          - 192.168.0.0/16
          - 169.254.0.0/15
          - 224.0.0.0-240.255.255.255
          - 100.42.32.0/24
      trisolaris:
        trident-type-for-unkonw-vtap: 3
```

应用配置：

```bash
helm upgrade deepflow \
  -n deepflow \
  deepflow/deepflow \
  --version "${DEEPFLOW_CHART_VERSION}" \
  -f values-production.yaml
```

不要直接覆盖已有 `values-production.yaml`。应把新增配置合并到当前完整 values 中，避免升级时丢失存储、镜像或数据库配置。

### 10.2 创建 Host Domain

```bash
export DOMAIN_NAME="legacy-host"

cat <<EOF | deepflow-ctl domain create -f -
name: ${DOMAIN_NAME}
type: agent_sync
EOF

deepflow-ctl domain list "${DOMAIN_NAME}"
```

Host Domain 用于接收 Agent 自同步的服务器网络和工作负载资源。

### 10.3 创建 Agent Group

```bash
export AGENT_GROUP="legacy-host"

deepflow-ctl agent-group create "${AGENT_GROUP}"
deepflow-ctl agent-group list "${AGENT_GROUP}"
```

记录形如 `g-xxxxxxxxxx` 的 Agent Group ID。

创建 `legacy-host-agent-group-config.yaml`：

```yaml
inputs:
  resources:
    workload_resource_sync_enabled: true
```

创建或更新组配置：

```bash
deepflow-ctl agent-group-config create \
  <AGENT_GROUP_ID> \
  -f legacy-host-agent-group-config.yaml
```

如果配置已存在：

```bash
deepflow-ctl agent-group-config update \
  <AGENT_GROUP_ID> \
  -f legacy-host-agent-group-config.yaml
```

### 10.4 RPM 系统安装

```bash
export AGENT_VERSION="v7.0"
export AGENT_ARCH="$(arch | sed 's|x86_64|amd64|' | sed 's|aarch64|arm64|')"

curl -O \
  "https://deepflow-ce.oss-cn-beijing.aliyuncs.com/rpm/agent/${AGENT_VERSION}/linux/${AGENT_ARCH}/deepflow-agent-rpm.zip"

unzip deepflow-agent-rpm.zip
sudo yum -y localinstall */deepflow-agent-1.0*.rpm
```

通配符会匹配压缩包内实际的 x86_64 或 ARM 架构目录。安装前可先执行 `ls */deepflow-agent*.rpm` 核对文件。

### 10.5 DEB 系统安装

```bash
export AGENT_VERSION="v7.0"
export AGENT_ARCH="$(arch | sed 's|x86_64|amd64|' | sed 's|aarch64|arm64|')"

curl -O \
  "https://deepflow-ce.oss-cn-beijing.aliyuncs.com/deb/agent/${AGENT_VERSION}/linux/${AGENT_ARCH}/deepflow-agent-deb.zip"

unzip deepflow-agent-deb.zip
sudo dpkg -i */deepflow-agent-1.0*.systemd.deb
```

### 10.6 二进制安装

```bash
export AGENT_VERSION="v7.0"
export AGENT_ARCH="$(arch | sed 's|x86_64|amd64|' | sed 's|aarch64|arm64|')"

curl -O \
  "https://deepflow-ce.oss-cn-beijing.aliyuncs.com/bin/agent/${AGENT_VERSION}/linux/${AGENT_ARCH}/deepflow-agent.tar.gz"

sudo tar -zxvf deepflow-agent.tar.gz -C /usr/sbin/
```

创建 `/etc/systemd/system/deepflow-agent.service`：

```ini
[Unit]
Description=DeepFlow Agent
After=syslog.target network-online.target
Wants=network-online.target

[Service]
Environment=GOTRACEBACK=single
LimitCORE=1G
ExecStart=/usr/sbin/deepflow-agent
Restart=always
RestartSec=10
LimitNOFILE=1024:4096

[Install]
WantedBy=multi-user.target
```

重新加载 systemd：

```bash
sudo systemctl daemon-reload
```

### 10.7 配置并启动 Agent

创建 `/etc/deepflow-agent.yaml`：

```yaml
controller-ips:
  - 10.1.2.3

vtap-group-id-request: "g-xxxxxxxxxx"
```

其中：

- `controller-ips`：DeepFlow Server 的 Node IP 或 LoadBalancer VIP。
- `vtap-group-id-request`：前面创建的 Agent Group ID。

启动并设为开机启动：

```bash
sudo systemctl enable deepflow-agent
sudo systemctl restart deepflow-agent
sudo systemctl status deepflow-agent --no-pager
```

查看日志：

```bash
sudo journalctl -u deepflow-agent -n 200 --no-pager
sudo journalctl -u deepflow-agent -f
```

在 Server 管理节点确认：

```bash
deepflow-ctl agent list
```

## 11. 访问 Grafana

### 11.1 获取访问地址

Kubernetes 默认部署可通过以下命令获取 NodePort：

```bash
NODE_PORT=$(kubectl get \
  --namespace deepflow \
  -o jsonpath="{.spec.ports[0].nodePort}" \
  services deepflow-grafana)

NODE_IP=$(kubectl get nodes \
  -o jsonpath="{.items[0].status.addresses[0].address}")

echo "Grafana URL: http://${NODE_IP}:${NODE_PORT}"
echo "Grafana auth: admin / deepflow"
```

如果节点第一个地址不是可访问地址，应从 `kubectl get nodes -o wide` 中选择正确的 InternalIP 或 ExternalIP。

默认登录信息：

```text
用户名：admin
密码：deepflow
```

首次登录后立即修改密码。生产环境应通过 Ingress 或 LoadBalancer 暴露 Grafana，并启用 TLS、认证和网络访问控制。

### 11.2 使用端口转发临时访问

如果不希望开放 NodePort：

```bash
kubectl port-forward \
  -n deepflow \
  service/deepflow-grafana \
  3000:3000
```

访问：

```text
http://127.0.0.1:3000
```

端口转发仅在命令运行期间有效，适合临时管理。

## 12. 基础使用

### 12.1 确认数据已进入系统

依次检查：

1. Agent 是否在线。
2. 被监控应用是否产生实际流量。
3. Grafana 时间范围是否覆盖刚才的流量。
4. Dashboard 的集群、命名空间、服务和 Agent Group 筛选项是否正确。

命令检查：

```bash
deepflow-ctl agent list
kubectl get pods -n deepflow -o wide
kubectl logs -n deepflow -l app=deepflow --since=10m --all-containers
```

若环境没有业务流量，即使部署完全正常，拓扑和指标也可能为空。应先对一个测试 API 持续发起请求。

### 12.2 使用 AutoMetrics

AutoMetrics 主要用于回答：

- 哪个服务请求量突然变化？
- 哪个 API 错误率升高？
- 时延发生在客户端、服务端还是网络？
- 是否存在 TCP 重传、建连失败或零窗口？

推荐操作步骤：

1. 在 Grafana 中打开 DeepFlow 的服务全景图或网络性能 Dashboard。
2. 设置最近 `15m` 或 `30m` 时间范围。
3. 选择目标 Kubernetes 集群、命名空间和服务。
4. 从服务拓扑定位高错误率或高时延链路。
5. 下钻到具体工作负载、Pod、API 和观测点。
6. 对比请求量、错误量、响应时延、重传和建连指标。

DeepFlow 能解析多种常见协议，包括 HTTP、HTTP/2、gRPC、DNS、MySQL、PostgreSQL、Redis、Kafka 等。协议是否可见还受到加密方式、内核能力、端口识别和采集配置影响。

### 12.3 使用 AutoTracing

AutoTracing 用于查看一次调用经过的应用、系统和网络路径。

操作步骤：

1. 打开 DeepFlow 分布式追踪相关 Dashboard。
2. 设置服务、API、响应状态和时间范围。
3. 选择一个高时延或错误请求。
4. 查看火焰图或 Span 时间线。
5. 判断耗时位于应用 Span、系统 Span 还是网络 Span。
6. 结合 Pod、Node、进程、IP、Kubernetes Label 等自动标签缩小范围。

仅使用 eBPF 时，DeepFlow 可以提供系统和网络层追踪。若要看到业务函数或框架内部 Span，应接入 OpenTelemetry、SkyWalking 等 APM 数据。

### 12.4 使用 AutoProfiling

On-CPU Profiling 用于定位哪些函数消耗了 CPU。默认情况下，通常还需要通过 Agent Group 配置指定要剖析的进程。

先导出默认配置作为参考：

```bash
deepflow-ctl agent-group-config example > agent-group-config-reference.yaml
```

查看当前组配置：

```bash
deepflow-ctl agent-group-config list <AGENT_GROUP_ID> -o yaml
```

配置 `inputs.proc.process_matcher` 时，应根据进程名、命令行或容器信息精确匹配目标进程。不要在生产环境中未经评估直接匹配所有进程。

查看剖析数据时：

1. 选择目标服务、实例或进程。
2. 选择 On-CPU 类型。
3. 设置覆盖问题发生时段的时间范围。
4. 在火焰图中从宽调用栈向下定位热点函数。
5. 结合同一时段的请求时延和错误指标验证因果关系。

社区版和企业版支持的 Profiling 类型不同。Off-CPU、Memory 等能力应以当前版本官方功能说明为准。

## 13. 接入 Prometheus

DeepFlow 可以通过 Prometheus Remote Write 接收指标，并为指标补充统一资源标签。

### 13.1 配置 Remote Write

先确认 Agent Service：

```bash
kubectl get service -n deepflow deepflow-agent
```

在 Prometheus 配置中添加：

```yaml
remote_write:
  - url: http://deepflow-agent.deepflow/api/v1/prometheus
```

如果 Prometheus 不在同一集群或无法解析该 Service，应使用实际可访问的 Agent 接收地址，并配置必要的网络策略和认证边界。

### 13.2 验证

检查 Prometheus：

```bash
kubectl logs -n <PROMETHEUS_NAMESPACE> \
  <PROMETHEUS_POD> \
  --since=10m
```

重点关注 Remote Write 队列积压、连接失败、HTTP 非 2xx 响应和超时。随后在 Grafana 中查询一个已知的 Prometheus 指标，并确认 Kubernetes 等标签是否正确关联。

## 14. 接入 OpenTelemetry

DeepFlow 推荐由节点级 OpenTelemetry Collector Agent 将 Trace 发送到同节点或集群内 DeepFlow Agent，以减少跨节点流量。

### 14.1 配置 OTLP HTTP Exporter

OpenTelemetry Collector 示例：

```yaml
exporters:
  otlphttp/deepflow:
    traces_endpoint: http://deepflow-agent.deepflow/api/v1/otel/trace
    tls:
      insecure: true
    retry_on_failure:
      enabled: true

processors:
  k8sattributes:

  resource/deepflow:
    attributes:
      - key: app.host.ip
        from_attribute: k8s.pod.ip
        action: insert

service:
  pipelines:
    traces:
      receivers:
        - otlp
      processors:
        - k8sattributes
        - resource/deepflow
      exporters:
        - otlphttp/deepflow
```

`k8sattributes` 必须先解析 Pod 信息，再将 `k8s.pod.ip` 写入 `app.host.ip`，这样 DeepFlow 才能更准确地将应用 Span 与 eBPF Span、Pod 和工作负载关联。

### 14.2 验证

检查 Collector 日志：

```bash
kubectl logs -n <OTEL_NAMESPACE> \
  <OTEL_COLLECTOR_POD> \
  --since=10m
```

在 Grafana 中选择一个已接入 OpenTelemetry 的服务，确认 Trace 中同时出现应用 Span 和 DeepFlow 采集的系统/网络 Span。若只有应用 Span，应检查 Agent Group 的外部数据接收配置和 Span 的 IP 属性。

## 15. Agent Group 配置管理

DeepFlow 使用 Agent Group 对一组 Agent 统一下发采集配置。

### 15.1 查看配置

```bash
deepflow-ctl agent-group list
deepflow-ctl agent-group-config list
deepflow-ctl agent-group-config list <AGENT_GROUP_ID> -o yaml
```

### 15.2 创建或更新配置

```bash
deepflow-ctl agent-group-config create \
  <AGENT_GROUP_ID> \
  -f agent-group-config.yaml
```

更新：

```bash
deepflow-ctl agent-group-config update \
  <AGENT_GROUP_ID> \
  -f agent-group-config.yaml
```

更新前保存当前配置：

```bash
deepflow-ctl agent-group-config list \
  <AGENT_GROUP_ID> \
  -o yaml > agent-group-config.backup.yaml
```

同一 Kubernetes 集群中的 Agent 通常应放在同一 Agent Group，并使用一致的 CPU、内存和采集配置。配置不一致可能导致采集结果不可比较，甚至引发反复重启。

## 16. 日常运维

### 16.1 健康检查

建议日常检查：

```bash
helm status deepflow -n deepflow
kubectl get pods -n deepflow -o wide
kubectl get pvc -n deepflow
kubectl get events -n deepflow --sort-by=.lastTimestamp
deepflow-ctl agent list
```

重点关注：

- Agent 离线数量。
- Server、ClickHouse、MySQL 重启次数。
- PVC 使用率和磁盘 I/O。
- ClickHouse 写入延迟和查询延迟。
- Agent CPU、内存、丢包和内部队列。
- 跨集群 30035/30033 端口可达性。
- 节点时间偏差。

### 16.2 查看日志

```bash
kubectl logs -n deepflow <POD_NAME> --all-containers --since=30m
kubectl logs -n deepflow <POD_NAME> --all-containers --previous
```

主机 Agent：

```bash
journalctl -u deepflow-agent --since="30 minutes ago" --no-pager
```

不要只查看最后几行。应将首次错误、Pod 事件、重启原因、探针失败和资源限制结合分析。

### 16.3 配置备份

至少备份：

```bash
helm get values deepflow -n deepflow -a > deepflow-values-backup.yaml
helm get manifest deepflow -n deepflow > deepflow-manifest-backup.yaml
deepflow-ctl domain list > deepflow-domains-backup.txt
deepflow-ctl agent-group list > deepflow-agent-groups-backup.txt
```

MySQL 和 ClickHouse 必须使用其原生、经过验证的备份与恢复方案。仅备份 Kubernetes YAML 无法恢复观测数据。

## 17. 升级

### 17.1 升级原则

升级前：

1. 阅读目标版本 Release Notes 和升级文档。
2. 备份 Helm values、MySQL 和 ClickHouse。
3. 确认 Agent 版本不会高于 Server。
4. 在测试环境验证 Dashboard、查询和采集协议。
5. 预留回滚时间和旧镜像。

### 17.2 升级 Server

先查看目标版本：

```bash
helm repo update deepflow
helm search repo deepflow/deepflow --versions
```

执行：

```bash
helm upgrade deepflow \
  -n deepflow \
  deepflow/deepflow \
  --version "<TARGET_CHART_VERSION>" \
  -f values-production.yaml
```

观察：

```bash
kubectl get pods -n deepflow -w
helm status deepflow -n deepflow
```

### 17.3 升级独立 K8s Agent

```bash
helm repo update deepflow

helm upgrade deepflow-agent \
  -n deepflow \
  deepflow/deepflow-agent \
  --version "<TARGET_CHART_VERSION>" \
  -f values-agent.yaml
```

### 17.4 更新 deepflow-ctl

```bash
export DEEPFLOW_MAJOR_VERSION="v7.0"

sudo curl -o /usr/bin/deepflow-ctl \
  "https://deepflow-ce.oss-cn-beijing.aliyuncs.com/bin/ctl/${DEEPFLOW_MAJOR_VERSION}/linux/$(arch | sed 's|x86_64|amd64|' | sed 's|aarch64|arm64|')/deepflow-ctl"

sudo chmod a+x /usr/bin/deepflow-ctl
deepflow-ctl --version
```

### 17.5 更新 Grafana Dashboard

检查 Grafana 初始化容器镜像和拉取策略：

```bash
kubectl get deployment \
  -n deepflow \
  deepflow-grafana \
  -o yaml | grep -E 'image:|imagePullPolicy'
```

确认 Dashboard 初始化镜像符合官方升级说明后，重启 Grafana：

```bash
kubectl delete pods \
  -n deepflow \
  -l app.kubernetes.io/instance=deepflow \
  -l app.kubernetes.io/name=grafana
```

## 18. 卸载

### 18.1 卸载独立 Agent

```bash
helm uninstall deepflow-agent -n deepflow
kubectl delete namespace deepflow
```

删除 Namespace 前应确认其中没有其他 DeepFlow Release 或业务资源。

### 18.2 卸载 DeepFlow Server

```bash
helm uninstall deepflow -n deepflow
```

Helm 通常不会自动删除 PVC。确认不再需要数据后再执行：

```bash
kubectl get pvc -n deepflow
kubectl delete pvc -n deepflow --all
kubectl delete namespace deepflow
```

删除 PVC 会造成不可逆的数据丢失。

### 18.3 卸载 Linux Agent

停止服务：

```bash
sudo systemctl disable --now deepflow-agent
```

RPM：

```bash
sudo yum remove deepflow-agent
```

DEB：

```bash
sudo dpkg -r deepflow-agent
```

二进制安装：

```bash
sudo rm -f /usr/sbin/deepflow-agent
sudo rm -f /etc/systemd/system/deepflow-agent.service
sudo systemctl daemon-reload
```

配置和日志是否保留应根据审计要求决定。

## 19. 常见问题与排查

### 19.1 Agent 未注册

现象：

```text
deepflow-ctl agent list 中看不到 Agent
```

排查：

```bash
nc -vz <SERVER_IP> 30035
nc -vz <SERVER_IP> 30033
```

检查：

- `controller-ips` 或 `deepflowServerNodeIPS` 是否正确。
- 防火墙、安全组、NetworkPolicy 是否放行。
- Server Node IP 是否稳定且可路由。
- Agent 与 Server 版本是否兼容。
- 主机 Agent 的 `vtap-group-id-request` 是否存在。
- Agent 日志中是否有注册、TLS、超时或版本错误。

### 19.2 K8s Agent Pod 处于 Pending

```bash
kubectl describe pod -n deepflow <AGENT_POD>
kubectl get nodes --show-labels
kubectl describe node <NODE_NAME>
```

常见原因：

- 节点污点没有对应 Toleration。
- Chart 的 NodeSelector 不匹配。
- Pod Security、Admission Policy 或安全产品拒绝高权限 Pod。
- 节点 CPU 或内存不足。

### 19.3 Agent CrashLoopBackOff

```bash
kubectl logs -n deepflow <AGENT_POD> --previous
kubectl describe pod -n deepflow <AGENT_POD>
```

常见原因：

- 内核版本或 eBPF 能力不兼容。
- `/sys/kernel/debug` 未挂载或无权限。
- SELinux、AppArmor、Seccomp 拦截。
- 配置字段与 Agent 版本不兼容。
- CPU/内存限制过低。

### 19.4 Grafana 没有数据

按顺序确认：

1. Agent 在线。
2. 应用有真实请求。
3. 时间范围和时区正确。
4. Dashboard 筛选条件未排除数据。
5. DeepFlow Server、Ingester、ClickHouse 正常。
6. 被观测协议受支持且未被无法解析的加密隐藏。

```bash
deepflow-ctl agent list
kubectl get pods -n deepflow
kubectl logs -n deepflow <SERVER_POD> --since=10m
```

### 19.5 只能看到网络 Span，看不到应用 Span

这是未接入 APM 时的常见结果。DeepFlow 的 eBPF AutoTracing 主要生成系统和网络层 Span。若需要代码和框架内部 Span，应接入 OpenTelemetry。

若已接入仍无法关联，检查：

- OTLP Exporter 是否成功发送。
- `k8sattributes` 是否获取到 `k8s.pod.ip`。
- 是否设置 `app.host.ip`。
- 应用、Collector 和 Agent 之间是否经过改变源地址的中间代理。
- 时间是否同步。

### 19.6 持续剖析无数据

检查：

```bash
cat /proc/sys/kernel/kptr_restrict
uname -r
```

同时确认：

- `process_matcher` 是否匹配目标进程。
- 目标进程在采样时段内是否实际消耗 CPU。
- Agent 是否具有 perf/eBPF 所需权限。
- 当前能力是否属于社区版支持范围。

### 19.7 ClickHouse 或 MySQL Pod 无法启动

```bash
kubectl get pvc -n deepflow
kubectl describe pod -n deepflow <POD_NAME>
kubectl logs -n deepflow <POD_NAME> --all-containers
```

常见原因：

- PVC 未绑定。
- 存储不支持所需访问模式。
- 节点磁盘已满或 inode 耗尽。
- 目录权限错误。
- 内存不足导致 OOMKilled。
- 外部数据库网络或认证失败。

### 19.8 跨集群链路不稳定

检查持续丢包、NAT、MTU、负载均衡和 NodePort 转发：

```bash
ping <SERVER_IP>
nc -vz <SERVER_IP> 30035
nc -vz <SERVER_IP> 30033
tracepath <SERVER_IP>
```

生产环境优先使用稳定的 LoadBalancer VIP。若继续使用 NodePort，应避免将 Agent 指向可能频繁下线的节点。

## 20. 生产环境最佳实践

### 20.1 使用固定 LTS 版本

生产环境必须显式设置 Chart 版本和镜像版本，不要依赖 `latest`。升级应通过版本评审和测试环境验证。

### 20.2 使用持久化和数据库备份

- MySQL 与 ClickHouse 使用可靠的持久化存储。
- 建立定期备份、恢复演练和容量告警。
- 监控磁盘容量、inode、I/O 延迟和数据保留周期。

### 20.3 优化 Agent 到 Server 的路径

有条件时将 DeepFlow Server Service 设置为 LoadBalancer：

```yaml
server:
  service:
    type: LoadBalancer
```

然后在 Agent Group 配置中固定控制面和数据面地址：

```yaml
proxy_controller_ip: 1.2.3.4
analyzer_ip: 1.2.3.4
proxy_controller_port: 30035
analyzer_port: 30033
```

没有 LoadBalancer 时，可评估：

```yaml
server:
  service:
    externalTrafficPolicy: Local
```

使用 `Local` 时，只有实际运行 Server Pod 的节点能够正确处理对应 NodePort 流量。必须结合 Pod 调度和节点故障设计，避免 Agent 指向无本地 Endpoint 的节点。

### 20.4 控制采集范围

- 按 Agent Group 区分生产、测试和特殊工作负载。
- 只对需要的进程启用持续剖析。
- 根据协议和业务价值设置流日志、指标和追踪采集范围。
- 修改采样率、队列、缓存和资源限制前先观察 Agent 自监控指标。

### 20.5 安全建议

- Grafana 默认密码首次登录后立即修改。
- 管理接口仅对运维网络开放。
- 跨集群通信通过专网、VPN 或受控网络进行。
- 对 Agent 高权限、HostPath 和 HostNetwork 使用进行安全评审。
- Helm values 中不要保存明文生产密码。
- 记录 `deepflow-ctl` 配置变更并纳入审计。

### 20.6 时间同步

追踪关联依赖时间。所有 Kubernetes Node、Linux 主机、数据库和管理节点都应通过 NTP 或 Chrony 同步，并监控时间偏差。

## 21. 部署验收清单

### 21.1 Server

- [ ] Helm Release 状态为 `deployed`。
- [ ] DeepFlow Server、ClickHouse、MySQL、Grafana Pod 正常。
- [ ] 所有 PVC 为 `Bound`。
- [ ] Grafana 可以登录且默认密码已修改。
- [ ] 已备份实际使用的 Helm values。

### 21.2 Agent

- [ ] K8s DaemonSet 的 `READY` 数量符合预期。
- [ ] Linux Agent systemd 服务为 `active (running)`。
- [ ] `deepflow-ctl agent list` 能看到全部 Agent。
- [ ] Agent 与 Server 的控制面和数据面端口可达。
- [ ] Agent、Server 和 CLI 版本兼容。

### 21.3 数据

- [ ] 测试应用产生流量后能看到服务拓扑。
- [ ] 能看到请求量、错误量和时延。
- [ ] 能查看一条 eBPF Trace。
- [ ] 配置目标进程后能看到 On-CPU Profiling 数据。
- [ ] Kubernetes Namespace、Pod、Service 和 Label 标签正确。
- [ ] Prometheus 或 OpenTelemetry 接入已完成验证。

### 21.4 运维

- [ ] 已设置存储容量和组件健康告警。
- [ ] 已建立 MySQL、ClickHouse 备份和恢复流程。
- [ ] 已记录升级、回滚和卸载步骤。
- [ ] 已限制 Grafana、Server 管理端口的访问范围。
- [ ] 所有节点时间已同步。

## 22. 总结

DeepFlow 的核心部署思路是：在 Kubernetes 中运行 Server 和存储组件，在每个需要观测的 Kubernetes Node 或 Linux 主机上运行 Agent，再通过 Grafana 和 `deepflow-ctl` 完成数据分析与配置管理。

建议按照以下顺序落地：

1. 使用 All-in-One 验证内核兼容性和观测效果。
2. 使用真实业务流量验证 AutoMetrics、AutoTracing 和 AutoProfiling。
3. 接入 OpenTelemetry，补充应用代码内部 Span。
4. 根据实际数据量完成存储、数据库、网络和保留周期规划。
5. 再部署生产环境，并建立监控、备份、升级和安全流程。

## 23. 官方参考资料

- [DeepFlow 社区版安装概览](https://deepflow.io/docs/zh/ce-install/overview/)
- [All-in-One 快速部署](https://deepflow.io/docs/zh/ce-install/all-in-one/)
- [监控单个 Kubernetes 集群](https://deepflow.io/docs/zh/ce-install/single-k8s/)
- [监控多个 Kubernetes 集群](https://www.deepflow.io/docs/zh/ce-install/multi-k8s/)
- [监控传统服务器](https://deepflow.io/docs/zh/ce-install/legacy-host/)
- [DeepFlow 升级](https://www.deepflow.io/docs/zh/ce-install/upgrade/)
- [生产环境部署建议](https://deepflow.io/docs/zh/best-practice/production-deployment/)
- [AutoMetrics](https://deepflow.io/docs/zh/features/universal-map/auto-metrics/)
- [持续性能剖析配置](https://www.deepflow.io/docs/zh/features/continuous-profiling/configuration/)
- [集成 Prometheus 数据](https://deepflow.io/docs/zh/integration/input/metrics/prometheus/)
- [导入 OpenTelemetry 数据](https://deepflow.io/docs/zh/integration/input/tracing/opentelemetry/)
- [全栈分布式追踪](https://deepflow.io/docs/zh/integration/input/tracing/full-stack-distributed-tracing/)
