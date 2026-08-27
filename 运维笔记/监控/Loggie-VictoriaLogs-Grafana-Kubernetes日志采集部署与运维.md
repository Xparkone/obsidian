# Loggie + VictoriaLogs + Grafana Kubernetes 日志采集部署与运维

> 文档版本：1.0
>
> 更新日期：2026-08-26
>
> 适用范围：任意具备 Kubernetes、kubectl、Helm、Docker 与 Docker Compose 的 Linux 环境
>
> 部署模式：Loggie 运行在 Kubernetes；VictoriaLogs 与 Grafana 运行在独立 Docker 主机
>
> 验证边界：本文配置已按通用场景整理，仍需在目标环境完成版本兼容、网络、存储和端到端验证后才能认定生产可用

## 1. 文档目标

本文提供一套不绑定云厂商、服务器 IP、Kubernetes 发行版和业务应用的日志平台部署方法，用于完成以下能力：

- 通过 Loggie DaemonSet 采集 Kubernetes Pod 的标准输出或容器内文件日志。
- 通过 Loggie `LogConfig` CRD 按命名空间、Pod 标签和日志路径下发采集规则。
- 通过 Elasticsearch Bulk 兼容接口将日志写入 VictoriaLogs。
- 通过 Grafana VictoriaLogs 数据源插件使用 LogsQL 查询日志。
- 提供在线、离线、静态检查、测试验证、升级回滚和故障排查方法。

本文不包含：

- 自动修改防火墙、DNS、Ingress 或负载均衡器。
- 自动创建生产密码、证书或外部密钥。
- VictoriaLogs Cluster 高可用集群的完整部署。
- 未经验证的生产容量结论。

## 2. 架构与数据流

### 2.1 组件关系

```text
Kubernetes Cluster
├── Node A
│   ├── Business Pod
│   └── Loggie DaemonSet Pod
├── Node B
│   ├── Business Pod
│   └── Loggie DaemonSet Pod
└── LogConfig / ClusterLogConfig CRD
              │
              │ HTTP / Elasticsearch Bulk
              ▼
Docker Host
├── VictoriaLogs :9428
│   └── 持久化日志数据
└── Grafana :3000
    └── VictoriaLogs datasource
```

### 2.2 网络方向

至少需要保证：

| 来源 | 目标 | 端口 | 用途 |
| --- | --- | ---: | --- |
| Kubernetes 每个工作节点 | VictoriaLogs Docker 主机 | 9428/TCP | Loggie 写入日志 |
| Grafana 容器 | VictoriaLogs 容器 | 9428/TCP | Grafana 查询日志 |
| 管理员浏览器 | Grafana | 3000/TCP 或反向代理端口 | Web 查询与管理 |
| 运维终端 | Kubernetes API Server | 6443/TCP 或实际端口 | kubectl/Helm 操作 |

生产环境不建议把 `9428` 直接暴露到公网。优先使用内网地址、内部 DNS、防火墙白名单和带认证/TLS 的反向代理。

### 2.3 两种采集模式

#### 模式 A：标准输出

应用将日志输出到 stdout/stderr：

```text
应用 stdout/stderr
  -> 容器运行时日志文件
  -> Loggie
  -> VictoriaLogs
```

优点：

- 符合 Kubernetes 常见日志模式。
- 应用无需管理日志文件轮转。
- 可通过 `kubectl logs` 辅助排障。

#### 模式 B：容器内文件

应用写入 `/var/log/app/*.log` 等文件：

```text
应用日志文件
  -> emptyDir / PVC / hostPath
  -> 节点 kubelet 数据目录
  -> Loggie
  -> VictoriaLogs
```

优先将日志目录挂载为 `emptyDir`、PVC 或 hostPath。只有无法挂载日志卷时，才评估 `rootFsCollectionEnabled`；该模式会增加节点路径挂载和运行时适配复杂度。

不要同时采集内容完全相同的 stdout 和文件日志，否则会产生重复数据。

## 3. 版本与环境基线

### 3.1 示例版本

本文示例使用以下版本作为说明基线：

| 组件 | 示例版本 | 说明 |
| --- | --- | --- |
| VictoriaLogs | `v1.52.0` | Docker 单节点 |
| Grafana | 固定的受支持版本 | 不建议生产长期使用 `latest` |
| VictoriaLogs Grafana 插件 | `0.31.0` | 要求 Grafana 版本满足插件兼容范围 |
| Loggie | 与 Helm Chart 匹配的固定版本 | Chart、镜像和 CRD 应保持同一发布系列 |
| Kubernetes | 目标集群当前受支持版本 | 部署前验证 CRD API、PodSecurity 和运行时 |

版本号会变化。部署时应检查对应组件的官方 release、Chart `appVersion`、镜像标签和升级说明，不要只替换镜像标签后直接升级。

### 3.2 必需工具

管理终端或部署主机需要：

```bash
kubectl version --client
helm version
docker version
docker compose version
curl --version
jq --version
```

兼容旧环境时，也可能使用：

```bash
docker-compose version
```

后续命令默认使用 `docker compose`。如果环境只有 `docker-compose`，应先执行 `docker-compose config` 验证 Compose 文件兼容性，再替换命令。

### 3.3 Kubernetes 预检查

```bash
kubectl cluster-info

kubectl get nodes -o wide

kubectl get nodes \
  -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,RUNTIME:.status.nodeInfo.containerRuntimeVersion,KUBELET:.status.nodeInfo.kubeletVersion'

kubectl auth can-i create customresourcedefinitions.apiextensions.k8s.io
kubectl auth can-i create daemonsets.apps -n loggie
kubectl auth can-i create clusterroles.rbac.authorization.k8s.io
```

记录实际容器运行时：

- `containerd://...`：Loggie 配置使用 `containerRuntime: containerd`。
- `docker://...`：Loggie 配置使用 `containerRuntime: docker`。
- 其他运行时：先确认目标 Loggie 版本是否支持，不要直接套用示例。

## 4. 规划变量和域名

为了避免每次登录后重复输入变量，可以把通用变量集中到 `/opt/logging-stack/logging-env.sh`。这个文件是供 Shell 使用的环境变量脚本，与后文供 Docker Compose 使用的 `.env` 不是同一个文件。

先创建目录：

```bash
sudo mkdir -p /opt/logging-stack
sudo chown "$(id -u):$(id -g)" /opt/logging-stack
```

创建 `/opt/logging-stack/logging-env.sh`：

```bash
#!/usr/bin/env bash

# 日志平台在 Docker 主机上的部署根目录
export LOGGING_ROOT="${LOGGING_ROOT:-/opt/logging-stack}"

# 必须替换成所有 Kubernetes 节点都能访问的内网 IP 或 DNS
export VICTORIALOGS_HOST="${VICTORIALOGS_HOST:-REPLACE_WITH_PRIVATE_IP_OR_DNS}"

# 服务端口
export VICTORIALOGS_PORT="${VICTORIALOGS_PORT:-9428}"
export GRAFANA_PORT="${GRAFANA_PORT:-3000}"

# Loggie 在 Kubernetes 中的命名空间
export LOGGIE_NAMESPACE="${LOGGIE_NAMESPACE:-loggie}"

# 防止忘记替换 VictoriaLogs 地址后继续执行部署命令
if [[ "$VICTORIALOGS_HOST" == "REPLACE_WITH_PRIVATE_IP_OR_DNS" ]]; then
  printf '%s\n' \
    'ERROR: 请修改 logging-env.sh 中的 VICTORIALOGS_HOST' >&2
  return 1 2>/dev/null || exit 1
fi
```

不要在这个脚本中保存密码、Token、Cookie 或私钥。脚本只存放非敏感的路径、地址、端口和命名空间。

设置权限并加载：

```bash
chmod 640 /opt/logging-stack/logging-env.sh

source /opt/logging-stack/logging-env.sh

printf 'LOGGING_ROOT=%s\n' "$LOGGING_ROOT"
printf 'VICTORIALOGS_HOST=%s\n' "$VICTORIALOGS_HOST"
printf 'VICTORIALOGS_PORT=%s\n' "$VICTORIALOGS_PORT"
printf 'GRAFANA_PORT=%s\n' "$GRAFANA_PORT"
printf 'LOGGIE_NAMESPACE=%s\n' "$LOGGIE_NAMESPACE"
```

`source` 只对当前 Shell 会话及其子进程生效。重新登录后需要再次执行：

```bash
source /opt/logging-stack/logging-env.sh
```

地址要求：

- `VICTORIALOGS_HOST` 不能填写 Loggie Pod 自身的 `127.0.0.1`。
- Docker Compose 内的 Grafana 可以通过服务名 `victorialogs:9428` 访问 VictoriaLogs。
- Kubernetes 内的 Loggie 不能解析 Docker Compose 私有网络中的 `victorialogs` 服务名，必须使用节点可访问的 IP 或 DNS。
- 多节点集群要从每个可能运行 Loggie 的节点验证网络。

## 5. 部署 VictoriaLogs 和 Grafana

### 5.1 创建目录

以下步骤会写入 Docker 主机文件系统，执行前应确认目录和磁盘挂载点：

```bash
source /opt/logging-stack/logging-env.sh

sudo mkdir -p "$LOGGING_ROOT"/{data/victorialogs,data/grafana,grafana/provisioning/datasources,secrets}
sudo chown -R "$(id -u):$(id -g)" "$LOGGING_ROOT"
cd "$LOGGING_ROOT"
```

推荐把 `/opt/logging-stack/data/victorialogs` 放在独立数据盘或受监控的持久化文件系统上。

### 5.2 固定镜像和插件版本

创建 `/opt/logging-stack/.env`：

```dotenv
VICTORIALOGS_IMAGE=victoriametrics/victoria-logs:v1.52.0

# 替换成已验证的固定版本。测试环境可临时使用 latest，生产环境禁止长期使用 latest。
GRAFANA_IMAGE=grafana/grafana:<PINNED_GRAFANA_VERSION>

VICTORIALOGS_BIND_ADDR=0.0.0.0
VICTORIALOGS_PORT=9428
GRAFANA_BIND_ADDR=0.0.0.0
GRAFANA_PORT=3000

VICTORIALOGS_GRAFANA_PLUGIN=victoriametrics-logs-datasource@0.31.0
```

将 `<PINNED_GRAFANA_VERSION>` 替换为插件兼容范围内、已经完成测试的 Grafana 版本。例如先查看：

```bash
docker manifest inspect grafana/grafana:<PINNED_GRAFANA_VERSION> >/dev/null
```

### 5.3 创建 Grafana 管理员密码

不要把真实密码写入本文、Git、ConfigMap 或命令历史。

```bash
cd /opt/logging-stack
chmod 700 secrets
read -s -p 'Grafana admin password: ' GRAFANA_ADMIN_PASSWORD
echo
printf '%s' "$GRAFANA_ADMIN_PASSWORD" > secrets/grafana_admin_password.txt
unset GRAFANA_ADMIN_PASSWORD
chmod 600 secrets/grafana_admin_password.txt
```

### 5.4 配置 Grafana 数据源

创建 `/opt/logging-stack/grafana/provisioning/datasources/victorialogs.yml`：

```yaml
apiVersion: 1

datasources:
  - name: VictoriaLogs
    uid: victorialogs
    type: victoriametrics-logs-datasource
    access: proxy
    url: http://victorialogs:9428
    isDefault: true
    editable: false
    jsonData:
      maxLines: 1000
```

这里使用 Docker Compose 服务名 `victorialogs`。不要替换成 `localhost`，因为 Grafana 容器内的 `localhost` 指向 Grafana 容器自身。

### 5.5 Docker Compose 配置

创建 `/opt/logging-stack/docker-compose.yml`：

```yaml
version: "3.8"

services:
  victorialogs:
    image: ${VICTORIALOGS_IMAGE}
    container_name: victorialogs
    restart: unless-stopped
    command:
      - -storageDataPath=/vlogs-data
      - -retentionPeriod=30d
      - -retention.maxDiskUsagePercent=80
    ports:
      - "${VICTORIALOGS_BIND_ADDR}:${VICTORIALOGS_PORT}:9428"
    volumes:
      - ./data/victorialogs:/vlogs-data
    networks:
      - logging
    logging:
      driver: local
      options:
        max-size: "20m"
        max-file: "3"

  grafana:
    image: ${GRAFANA_IMAGE}
    container_name: grafana
    restart: unless-stopped
    depends_on:
      - victorialogs
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD__FILE: /run/secrets/grafana_admin_password
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_PLUGINS_PREINSTALL: ${VICTORIALOGS_GRAFANA_PLUGIN}
    ports:
      - "${GRAFANA_BIND_ADDR}:${GRAFANA_PORT}:3000"
    volumes:
      - ./data/grafana:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    secrets:
      - grafana_admin_password
    networks:
      - logging
    logging:
      driver: local
      options:
        max-size: "20m"
        max-file: "3"

networks:
  logging:
    driver: bridge

secrets:
  grafana_admin_password:
    file: ./secrets/grafana_admin_password.txt
```

配置说明：

- `version: "3.8"` 用于兼容部分旧版 `docker-compose`；新版 Docker Compose 可能提示该字段已过时并忽略它。如果所有目标主机均使用 Compose v2，可以删除该字段。
- `-retentionPeriod=30d`：按时间保留 30 天日志。
- `-retention.maxDiskUsagePercent=80`：磁盘占用达到阈值后开始按分区清理旧数据。
- 时间保留和磁盘占用限制同时生效，不能把它们理解为二选一。
- 仍应预留至少约 20% 磁盘空间用于合并、索引和短时突增。
- `GF_PLUGINS_PREINSTALL` 需要 Grafana 容器具备访问插件仓库的网络能力；离线方法见后文。

### 5.6 静态检查

不要直接执行 `up -d`，先检查变量和最终渲染结果：

```bash
cd /opt/logging-stack

docker compose config --services
docker compose config --images
docker compose config >/tmp/logging-compose-rendered.yml
```

重点检查：

```bash
grep -nE 'image:|ports:|source:|target:' /tmp/logging-compose-rendered.yml
```

确认渲染结果中不存在：

- 空镜像名。
- 未替换的 `<PINNED_GRAFANA_VERSION>`。
- 错误的公网监听地址。
- 误挂载到根目录或错误数据盘的路径。

### 5.7 启动与状态检查

以下命令会修改运行状态，只能在变更窗口或已授权环境执行：

```bash
cd /opt/logging-stack
docker compose pull
docker compose up -d
docker compose ps
```

只读验证：

```bash
curl -fsS "http://127.0.0.1:${VICTORIALOGS_PORT}/health"

curl -fsS "http://127.0.0.1:${GRAFANA_PORT}/api/health" | jq .

docker compose logs --tail=100 victorialogs
docker compose logs --tail=100 grafana
```

VictoriaLogs 内置查询页面：

```text
http://<Docker主机地址>:9428/select/vmui/
```

## 6. 部署 Loggie

### 6.1 获取与目标版本匹配的 Chart

优先从 Loggie 官方 release 获取与目标镜像版本匹配的 Helm Chart。不要把旧 Chart 与新镜像直接组合后用于生产。

官方文档中的下载形式类似：

```bash
export LOGGIE_VERSION=v1.4.0

helm pull \
  "https://gitea.cncfstack.com/loggie-io/installation/releases/download/${LOGGIE_VERSION}/loggie-${LOGGIE_VERSION}.tgz"

tar -xzf "loggie-${LOGGIE_VERSION}.tgz"
```

不同 release 的资产名称可能变化。下载前应在官方 release 页面确认实际文件名，并验证摘要或签名。

检查 Chart：

```bash
helm show chart ./loggie
helm show values ./loggie | sed -n '1,220p'
```

### 6.2 Loggie 覆盖配置

创建 `loggie-values.yml`：

```yaml
# 镜像版本必须与选定的 Loggie release/Chart 兼容
image: loggieio/loggie:<PINNED_LOGGIE_VERSION>
pullPolicy: IfNotPresent

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: "1"
    memory: 512Mi

config:
  loggie:
    discovery:
      enabled: true
      kubernetes:
        # 根据 kubectl get nodes 显示的实际运行时修改
        containerRuntime: containerd

        # 采集 stdout 时开启，用于解析容器运行时封装格式
        parseStdout: true

        # 大规模 Pod 变动场景可减少配置频繁渲染和 reload
        dynamicContainerLog: true

        # 使用 emptyDir/PVC/hostPath 时保持 false
        # 只有需要采集容器 writable layer 文件时才评估开启
        rootFsCollectionEnabled: false

        typePodFields:
          logconfig: "${_k8s.logconfig}"
          namespace: "${_k8s.pod.namespace}"
          nodename: "${_k8s.node.name}"
          podname: "${_k8s.pod.name}"
          containername: "${_k8s.pod.container.name}"

    http:
      enabled: true
      port: 9196
```

注意：

- `${_k8s.*}` 是 Loggie 的元数据表达式，不是 Shell 环境变量，不要对该文件执行无差别 `envsubst`。
- `resources` 只是测试起点，不是生产容量结论。
- Chart 键名可能随版本变化。必须以目标 Chart 的 `helm show values` 为准。
- 如果 Chart 默认已经包含 `/var/log/pods`、`/var/lib/kubelet/pods` 和 registry 持久化挂载，不要重复挂载。

### 6.3 Helm 静态检查

```bash
helm lint ./loggie -f loggie-values.yml

helm template loggie ./loggie \
  --namespace loggie \
  -f loggie-values.yml \
  >/tmp/loggie-rendered.yml

kubectl apply --dry-run=client \
  -f /tmp/loggie-rendered.yml \
  >/dev/null
```

检查最终镜像集合：

```bash
awk '$1 == "image:" {gsub(/"/, "", $2); print $2}' \
  /tmp/loggie-rendered.yml \
  | sort -u
```

检查 DaemonSet 挂载：

```bash
rg -n '/var/log/pods|/var/lib/kubelet/pods|/var/lib/docker|containerd|loggie.db' \
  /tmp/loggie-rendered.yml
```

如果目标主机没有 `rg`，可替换为：

```bash
grep -nE '/var/log/pods|/var/lib/kubelet/pods|/var/lib/docker|containerd|loggie.db' \
  /tmp/loggie-rendered.yml
```

### 6.4 安装 Loggie

以下命令会创建 CRD、RBAC、DaemonSet 和相关资源：

```bash
helm upgrade --install loggie ./loggie \
  --namespace loggie \
  --create-namespace \
  -f loggie-values.yml \
  --wait \
  --timeout 10m
```

检查：

```bash
helm status loggie -n loggie
helm get values loggie -n loggie

kubectl get crd | grep loggie.io
kubectl get daemonset -n loggie -o wide
kubectl get pods -n loggie -o wide
```

正常情况下，需要采集日志的每个 Kubernetes 节点都应运行一个 Loggie Pod。若节点有污点、特殊架构或调度限制，需要在 Chart 中配置相应 tolerations、nodeSelector 或 affinity。

## 7. 配置标准输出采集

### 7.1 业务应用要求

业务应用应：

- 将日志写到 stdout/stderr。
- 使用稳定的 Pod 标签，例如 `app.kubernetes.io/name`。
- 优先输出单行 JSON，至少包含时间、级别、服务名和正文。
- 避免在日志中输出密码、Token、Cookie、完整认证头和个人敏感数据。

推荐 JSON：

```json
{"@timestamp":"2026-08-26T10:00:00Z","level":"info","service":"orders","body":"order created","request_id":"req-example"}
```

### 7.2 LogConfig 示例

创建 `orders-stdout-logconfig.yml`：

```yaml
apiVersion: loggie.io/v1beta1
kind: LogConfig
metadata:
  name: orders-stdout
  namespace: production
spec:
  selector:
    type: pod
    labelSelector:
      app.kubernetes.io/name: orders

  pipeline:
    sources: |
      - type: file
        name: stdout
        paths:
          - stdout

    sink: |
      type: elasticsearch
      hosts:
        - "http://<VICTORIALOGS_PRIVATE_IP_OR_DNS>:9428/insert/elasticsearch/"
      parameters:
        _msg_field: "body"
        _time_field: "@timestamp"
        _stream_fields: "logconfig,namespace,podname,containername"
```

替换：

```text
<VICTORIALOGS_PRIVATE_IP_OR_DNS>
```

为所有 Kubernetes 节点可访问的 VictoriaLogs 地址。

静态检查：

```bash
kubectl apply --dry-run=client -f orders-stdout-logconfig.yml

kubectl get pods -n production \
  -l 'app.kubernetes.io/name=orders' \
  -o wide
```

应用：

```bash
kubectl apply -f orders-stdout-logconfig.yml
```

检查：

```bash
kubectl get logconfig -n production
kubectl describe logconfig orders-stdout -n production
```

`LogConfig` 是命名空间级资源，只能匹配自身命名空间中的 Pod。跨命名空间统一采集应评估 `ClusterLogConfig`，同时限制命名空间和标签范围，避免误采集系统日志和敏感日志。

## 8. 配置文件日志采集

### 8.1 应用日志卷示例

以下仅展示 Deployment 中与日志目录有关的片段：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders
  namespace: production
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: orders
  template:
    metadata:
      labels:
        app.kubernetes.io/name: orders
    spec:
      containers:
        - name: orders
          image: example.registry.local/orders:<PINNED_VERSION>
          volumeMounts:
            - name: app-logs
              mountPath: /var/log/app
      volumes:
        - name: app-logs
          emptyDir: {}
```

应用必须实际写入 `/var/log/app/*.log`。仅创建空目录不会产生可采集数据。

### 8.2 文件 LogConfig

创建 `orders-file-logconfig.yml`：

```yaml
apiVersion: loggie.io/v1beta1
kind: LogConfig
metadata:
  name: orders-file
  namespace: production
spec:
  selector:
    type: pod
    labelSelector:
      app.kubernetes.io/name: orders

  pipeline:
    sources: |
      - type: file
        name: application
        paths:
          - /var/log/app/*.log

    sink: |
      type: elasticsearch
      hosts:
        - "http://<VICTORIALOGS_PRIVATE_IP_OR_DNS>:9428/insert/elasticsearch/"
      parameters:
        _msg_field: "body"
        _time_field: "@timestamp"
        _stream_fields: "logconfig,namespace,podname,containername"
```

执行前确认：

```bash
kubectl get pods -n production \
  -l 'app.kubernetes.io/name=orders' \
  -o wide

kubectl exec -n production <ORDERS_POD> -- \
  sh -c 'find /var/log/app -maxdepth 1 -type f -name "*.log" -print'
```

第二条命令只查看文件名，不应读取日志正文。正式排障时应注意日志内容可能包含敏感信息。

## 9. 网络验证

### 9.1 Docker 主机本机检查

```bash
curl -fsS http://127.0.0.1:9428/health
ss -lntp | grep ':9428'
```

### 9.2 Kubernetes 节点检查

在每个工作节点执行：

```bash
curl -fsS "http://<VICTORIALOGS_PRIVATE_IP_OR_DNS>:9428/health"
```

如果不能直接登录节点，可以在获得授权后创建临时测试 Pod。测试 Pod 属于集群写操作，不应在只读诊断阶段执行。

```bash
kubectl run network-test \
  --namespace default \
  --image=curlimages/curl:<PINNED_VERSION> \
  --restart=Never \
  --rm -it \
  -- curl -fsS "http://<VICTORIALOGS_PRIVATE_IP_OR_DNS>:9428/health"
```

测试完成后确认临时 Pod 已被清理：

```bash
kubectl get pod network-test -n default
```

## 10. 端到端测试

### 10.1 测试边界

端到端测试会创建命名空间、Pod 和 LogConfig，并持续产生测试日志。只能在测试集群或已授权的生产验证窗口执行。

仅通过以下结果不能认定日志链路正常：

- Loggie Pod `Running`。
- VictoriaLogs `/health` 返回 HTTP 200。
- Grafana 页面能打开。
- YAML 解析成功。

必须验证：

```text
测试日志产生
  -> Loggie 匹配 Pod
  -> source offset 增长
  -> sink 发送成功
  -> VictoriaLogs 查询到唯一测试标识
  -> Grafana Explore 查询到同一条日志
```

### 10.2 测试 Pod

创建 `loggie-e2e-test.yml`：

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: logging-demo
---
apiVersion: v1
kind: Pod
metadata:
  name: loggie-e2e
  namespace: logging-demo
  labels:
    app.kubernetes.io/name: loggie-e2e
spec:
  restartPolicy: Never
  containers:
    - name: generator
      image: busybox:1.36.1
      command:
        - sh
        - -c
        - |
          while true; do
            now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
            printf '{"@timestamp":"%s","level":"info","service":"loggie-e2e","body":"LOGGIE_E2E_TEST"}\n' "$now"
            sleep 5
          done
```

对应 `loggie-e2e-logconfig.yml`：

```yaml
apiVersion: loggie.io/v1beta1
kind: LogConfig
metadata:
  name: stdout-e2e
  namespace: logging-demo
spec:
  selector:
    type: pod
    labelSelector:
      app.kubernetes.io/name: loggie-e2e
  pipeline:
    sources: |
      - type: file
        name: stdout
        paths:
          - stdout
    sink: |
      type: elasticsearch
      hosts:
        - "http://<VICTORIALOGS_PRIVATE_IP_OR_DNS>:9428/insert/elasticsearch/"
      parameters:
        _msg_field: "body"
        _time_field: "@timestamp"
        _stream_fields: "logconfig,namespace,podname,containername"
```

先做 dry-run：

```bash
kubectl apply --dry-run=client -f loggie-e2e-test.yml
kubectl apply --dry-run=client -f loggie-e2e-logconfig.yml
```

再执行测试：

```bash
kubectl apply -f loggie-e2e-test.yml
kubectl apply -f loggie-e2e-logconfig.yml

kubectl get pods -n logging-demo -o wide
kubectl describe logconfig stdout-e2e -n logging-demo
```

### 10.3 VictoriaLogs 查询验证

设置查询地址：

```bash
export VICTORIALOGS_URL='http://<VICTORIALOGS_PRIVATE_IP_OR_DNS>:9428'
```

查询最近 10 分钟的测试日志：

```bash
curl -fsS -G \
  "${VICTORIALOGS_URL}/select/logsql/query" \
  --data-urlencode 'query={namespace="logging-demo",logconfig="stdout-e2e"} _time:10m | first 20 by (_time desc)' \
  --data-urlencode 'limit=20'
```

只统计数量：

```bash
curl -fsS -G \
  "${VICTORIALOGS_URL}/select/logsql/query" \
  --data-urlencode 'query={namespace="logging-demo",logconfig="stdout-e2e"} _time:10m | stats count() as rows'
```

若流字段尚未生成，可先用唯一正文缩小查询：

```bash
curl -fsS -G \
  "${VICTORIALOGS_URL}/select/logsql/query" \
  --data-urlencode 'query=_time:10m "LOGGIE_E2E_TEST" | first 20 by (_time desc)' \
  --data-urlencode 'limit=20'
```

### 10.4 Grafana 验证

打开：

```text
http://<GRAFANA_ADDRESS>:3000/
```

进入 `Explore`，选择 `VictoriaLogs`，执行：

```text
{namespace="logging-demo",logconfig="stdout-e2e"} _time:10m
```

确认：

- 能看到 `LOGGIE_E2E_TEST`。
- `_time` 与测试 Pod 时间一致。
- `_msg` 显示 `body` 内容。
- `namespace`、`podname`、`containername` 和 `logconfig` 字段存在。

### 10.5 清理测试资源

确认不再需要测试数据后，执行定向清理：

```bash
kubectl delete namespace logging-demo
```

该操作会删除命名空间内的测试 Pod 和 LogConfig。执行前必须确认命名空间只包含本测试资源。

## 11. Loggie 采集状态检查

### 11.1 查找目标 Pod 所在节点

```bash
kubectl get pods -n production \
  -l 'app.kubernetes.io/name=orders' \
  -o wide
```

### 11.2 查找同节点 Loggie Pod

```bash
kubectl get pods -n loggie -o wide
```

确认目标节点存在处于 `Running` 且 Ready 的 Loggie Pod。

### 11.3 查看 LogConfig Events

```bash
kubectl describe logconfig orders-stdout -n production
```

重点关注：

- selector 是否匹配 Pod。
- 配置是否同步成功。
- CRD 校验错误。
- source、sink 或 interceptor 解析错误。

### 11.4 查看 Loggie 日志

```bash
kubectl logs -n loggie <LOGGIE_POD> \
  --since=30m \
  --tail=300
```

不要把包含凭据、完整业务日志或敏感字段的输出直接粘贴到公开渠道。

### 11.5 Loggie 帮助接口

如果目标版本启用了 `9196` 管理接口，可通过端口转发查看：

```bash
kubectl port-forward -n loggie pod/<LOGGIE_POD> 19196:9196
```

另一个终端执行：

```bash
curl -fsS 'http://127.0.0.1:19196/api/v1/help?detail=all'
```

重点查看：

- Pipeline Status。
- 实际节点文件路径。
- active/inactive 文件数量。
- 已确认 offset。
- sink 发送和重试状态。

端口转发只应绑定 `127.0.0.1`，不要把 Loggie 管理接口直接暴露到公网。

## 12. 常用 LogsQL

最近 15 分钟：

```text
_time:15m
```

按命名空间：

```text
namespace:="production" _time:15m
```

按日志流：

```text
{namespace="production",logconfig="orders-stdout"} _time:15m
```

查询错误：

```text
{namespace="production"} _time:15m (error OR exception OR panic)
```

按服务统计：

```text
_time:15m service:* | stats by (service) count() as rows
```

查询最新 20 条：

```text
{namespace="production"} _time:15m | first 20 by (_time desc)
```

查询时必须设置合理时间范围和返回上限，避免无条件扫描长期历史数据。

## 13. 在线与离线部署

### 13.1 在线环境

在线环境需要确认以下出口：

- Docker 主机可以拉取 VictoriaLogs、Grafana 镜像和 Grafana 插件。
- Kubernetes 节点可以拉取 Loggie 和测试镜像。
- 管理终端可以下载 Loggie Chart。

只读验证：

```bash
docker manifest inspect victoriametrics/victoria-logs:v1.52.0 >/dev/null
docker manifest inspect grafana/grafana:<PINNED_GRAFANA_VERSION> >/dev/null
docker manifest inspect loggieio/loggie:<PINNED_LOGGIE_VERSION> >/dev/null
```

### 13.2 离线镜像准备

在联网且 CPU 架构匹配的机器上：

```bash
docker pull victoriametrics/victoria-logs:v1.52.0
docker pull grafana/grafana:<PINNED_GRAFANA_VERSION>
docker pull loggieio/loggie:<PINNED_LOGGIE_VERSION>
docker pull busybox:1.36.1

docker save \
  -o victorialogs-v1.52.0.tar \
  victoriametrics/victoria-logs:v1.52.0

docker save \
  -o grafana.tar \
  grafana/grafana:<PINNED_GRAFANA_VERSION>

docker save \
  -o loggie.tar \
  loggieio/loggie:<PINNED_LOGGIE_VERSION>

docker save \
  -o busybox-1.36.1.tar \
  busybox:1.36.1
```

计算并保存摘要：

```bash
sha256sum *.tar > SHA256SUMS
sha256sum -c SHA256SUMS
```

### 13.3 Docker 主机导入

```bash
docker load -i victorialogs-v1.52.0.tar
docker load -i grafana.tar
docker image ls
```

### 13.4 containerd 节点导入

每个可能调度 Loggie 的 Kubernetes 节点都需要导入：

```bash
sudo ctr -n k8s.io images import loggie.tar
sudo ctr -n k8s.io images import busybox-1.36.1.tar
sudo ctr -n k8s.io images ls | grep -E 'loggie|busybox'
```

如果节点使用 CRI-O、Docker 或厂商封装运行时，使用对应运行时工具；向 Docker 导入镜像不会自动让 containerd 可用。

### 13.5 离线 Grafana 插件

`GF_PLUGINS_PREINSTALL` 默认需要网络。离线环境应：

1. 在联网环境下载与 Grafana 版本兼容的 VictoriaLogs 插件 ZIP。
2. 校验下载文件摘要。
3. 解压到 Grafana 持久化插件目录。
4. 将插件目录挂载到 `/var/lib/grafana/plugins`。
5. 删除或清空 `GF_PLUGINS_PREINSTALL`，避免启动时等待网络。

Compose 挂载示例：

```yaml
services:
  grafana:
    volumes:
      - ./grafana/plugins:/var/lib/grafana/plugins:ro
```

插件目录权限必须允许 Grafana 容器用户读取。不要使用 `chmod -R 777` 作为默认解决方案。

### 13.6 离线完整性检查

离线包应至少包括：

```text
Loggie Helm Chart
Loggie CRD
Loggie 镜像
VictoriaLogs 镜像
Grafana 镜像
VictoriaLogs Grafana 插件
测试镜像
SHA256SUMS
版本清单和部署说明
```

仅检查 tar 能解包还不够。还要确认：

- CPU 架构与节点一致。
- 镜像标签与 Helm 渲染结果一致。
- 所有节点都已导入。
- `imagePullPolicy` 不会强制联网拉取。
- 实际 Pod `imageID` 与计划摘要一致。

## 14. 容量与保留期

### 14.1 需要测量的输入

至少记录：

```text
平均每秒日志行数
平均每行字节数
峰值每秒日志行数
峰值持续时间
日志保留天数
压缩后实际磁盘占用
查询并发和查询时间范围
Loggie sink 响应延迟
```

### 14.2 粗略估算

原始日志量：

```text
每日原始日志字节数
= 平均每秒日志行数 × 平均每行字节数 × 86400
```

计划磁盘空间不能直接用原始日志量乘保留天数，还应考虑：

- VictoriaLogs 实际压缩率。
- 索引和分区开销。
- 每日峰值和突发流量。
- 数据合并期间的临时空间。
- 至少约 20% 的磁盘余量。

压缩率必须用真实业务日志测量。不要把其他项目的压缩率当作本环境既定值。

### 14.3 Loggie 容量观察

Loggie 容量应同时看：

- CPU 和内存。
- 活跃文件数量。
- 每秒读取字节数和行数。
- sink 并发与响应延迟。
- 重试数量和队列堆积。
- source offset 与文件大小之间的差距。

单纯提高并发可能增加 VictoriaLogs 压力；单纯增加队列只能延后故障暴露。需要一起观察吞吐、积压和端到端延迟。

## 15. 监控与告警

### 15.1 VictoriaLogs

VictoriaLogs 暴露 `/metrics`。至少监控：

- 写入请求和写入错误。
- 查询请求、查询错误和超时。
- 磁盘使用率和剩余空间。
- 进程 CPU、内存和文件描述符。
- 日志写入速率突然归零。

```bash
curl -fsS http://127.0.0.1:9428/metrics | head
```

### 15.2 Loggie

至少监控：

- DaemonSet 期望与就绪数量。
- Pod 重启和 OOMKilled。
- source 读取速率。
- sink 成功、错误和重试。
- pipeline reload 失败。
- 文件 offset 长时间不增长。

### 15.3 业务无日志告警

平台健康告警与业务日志告警应分开：

- 平台健康：Prometheus/VictoriaMetrics 采集 `/metrics`。
- 业务日志：使用 LogsQL 统计结果，再由 vmalert/Alertmanager 或 Grafana-managed alert 评估。

不要让同一条业务规则同时由多个告警执行器评估，否则可能重复通知。

## 16. 安全要求

### 16.1 凭据

不得把以下内容写入 Git、LogConfig 或普通 ConfigMap：

- Grafana 管理员密码。
- API Key、Token 和 Cookie。
- VictoriaLogs 多租户认证头。
- 反向代理密码。
- 完整数据库连接凭据。

使用 Docker Secret、Kubernetes Secret、External Secrets 或企业密钥管理系统。

### 16.2 网络

- `9428` 只允许 Loggie、Grafana 和受控运维终端访问。
- `3000` 通过内网、VPN 或带认证的 HTTPS 反向代理访问。
- 不直接公开 Loggie `9196` 管理端口。
- 跨网络部署时验证 MTU、代理、DNS 和连接超时。

### 16.3 Kubernetes 权限

- 使用 Chart 提供的最小 RBAC 基线并复核 ClusterRole。
- 不给 Loggie Pod 挂载不需要的节点路径。
- root filesystem 采集会扩大可见范围，启用前进行安全审查。
- 不为了排障默认使用 privileged 或宿主机根目录挂载。

### 16.4 日志内容

应用侧应在写日志前脱敏：

- 密码、Token、Cookie。
- 身份证号、银行卡号、手机号等个人信息。
- 完整请求体和认证头。
- 私钥和证书私钥内容。

## 17. 升级、回滚与备份

### 17.1 升级前

```bash
docker compose config >/tmp/docker-compose-before-upgrade.yml
docker image ls --digests

helm history loggie -n loggie
helm get values loggie -n loggie >/tmp/loggie-values-before-upgrade.yml
helm get manifest loggie -n loggie >/tmp/loggie-manifest-before-upgrade.yml
```

同时记录：

- 当前镜像 digest。
- 当前 CRD 版本。
- 当前 VictoriaLogs 数据目录大小和磁盘空间。
- Grafana 数据库和 provisioning 文件备份状态。
- 最近一次端到端测试结果。

### 17.2 Loggie 升级

先渲染新版本并检查差异：

```bash
helm lint ./loggie-new -f loggie-values.yml

helm template loggie ./loggie-new \
  -n loggie \
  -f loggie-values.yml \
  >/tmp/loggie-new-rendered.yml
```

确认后执行：

```bash
helm upgrade loggie ./loggie-new \
  -n loggie \
  -f loggie-values.yml \
  --wait \
  --timeout 10m
```

回滚：

```bash
helm history loggie -n loggie
helm rollback loggie <REVISION> -n loggie --wait --timeout 10m
```

CRD 升级和回滚可能不受普通 Helm revision 完整覆盖。升级前必须单独检查 CRD schema 变更和官方迁移说明。

### 17.3 VictoriaLogs 与 Grafana

升级前应先完成数据和配置备份。对于单节点 VictoriaLogs，最稳妥的文件系统快照流程通常需要控制写入并确保快照一致性；具体方法取决于使用的 LVM、云盘、ZFS、存储阵列或备份工具。

不要在未验证数据格式兼容性时，简单替换镜像后依赖旧数据目录启动。

回滚至少需要：

- 原镜像 tag 和 digest。
- 原 Compose 文件和 `.env`。
- Grafana 数据目录或数据库备份。
- VictoriaLogs 一致性数据快照。
- 明确的最大可接受停机和数据丢失窗口。

## 18. 常见故障

### 18.1 `no matches for kind LogConfig`

现象：

```text
no matches for kind "LogConfig" in version "loggie.io/v1beta1"
```

检查：

```bash
kubectl get crd logconfigs.loggie.io
kubectl api-resources | grep -i logconfig
```

可能原因：

- Loggie CRD 未安装。
- CRD 安装失败。
- YAML `apiVersion` 与当前 CRD 不一致。

### 18.2 LogConfig 存在但未匹配 Pod

```bash
kubectl get pods -n <NAMESPACE> -l '<LABEL_SELECTOR>' -o wide
kubectl describe logconfig <NAME> -n <NAMESPACE>
```

常见原因：

- 标签键或值写错。
- LogConfig 与 Pod 不在同一命名空间。
- Pod 标签在发布过程中发生变化。

### 18.3 文件存在但没有采集

检查：

```bash
kubectl exec -n <NAMESPACE> <POD> -- \
  sh -c 'find /var/log/app -maxdepth 1 -type f -name "*.log" -print'
```

常见原因：

- `paths` 与容器内实际路径不一致。
- 文件扩展名或 glob 不匹配。
- 日志目录没有通过 volume 暴露。
- Loggie 未挂载实际 kubelet root 目录。
- 文件权限不允许 Loggie 读取。
- 文件没有继续增长。
- registry 中的 offset 已到文件末尾。

### 18.4 stdout 无数据

检查：

```bash
kubectl logs -n <NAMESPACE> <POD> --tail=20
```

如果 `kubectl logs` 本身为空，先检查应用是否实际输出日志。如果 `kubectl logs` 有数据但 VictoriaLogs 无数据，再检查：

- `paths` 是否为 `stdout`。
- `parseStdout` 是否符合目标运行时。
- Loggie 是否运行在同一节点。
- LogConfig Events 和 Loggie sink 状态。

### 18.5 Loggie 无法连接 VictoriaLogs

常见错误：

```text
connection refused
context deadline exceeded
no route to host
```

检查：

```bash
curl -v --max-time 5 \
  "http://<VICTORIALOGS_PRIVATE_IP_OR_DNS>:9428/health"
```

依次检查：

- VictoriaLogs 容器是否运行。
- Docker 端口是否正确监听。
- Kubernetes 节点路由和防火墙。
- DNS 解析。
- 是否误用 `localhost` 或 Docker 私有服务名。

### 18.6 VictoriaLogs 有数据但 `_msg` 为空

检查事件是否存在 `body` 字段，以及 sink 参数：

```yaml
parameters:
  _msg_field: "body"
```

如果业务日志正文使用 `message`、`msg` 或其他字段，应统一字段规范或调整 `_msg_field`。调整后需要重新验证查询和历史数据展示差异。

### 18.7 时间不正确或查询不到最近日志

检查：

- `@timestamp` 是否存在。
- 是否符合 ISO8601/RFC3339。
- 应用、节点和 VictoriaLogs 的时钟是否同步。
- 时间是否超出 VictoriaLogs retention 接受范围。
- Grafana 查询时区和时间范围。

### 18.8 Grafana 找不到插件

```bash
docker compose logs --tail=200 grafana
docker compose exec grafana grafana cli plugins ls
```

常见原因：

- Docker 主机无法访问插件仓库。
- 插件版本与 Grafana 不兼容。
- 离线插件目录错误或权限不足。
- Grafana 数据目录未持久化。

### 18.9 Grafana 数据源连接失败

在 Grafana 容器中测试 Docker 服务名：

```bash
docker compose exec grafana \
  wget -qO- http://victorialogs:9428/health
```

如果镜像内没有 `wget`，不要为了排障临时安装软件并修改容器；可使用同网络的临时 curl 容器或在 Docker 主机检查网络。

### 18.10 离线环境 `ImagePullBackOff`

检查：

```bash
kubectl describe pod -n loggie <LOGGIE_POD>
kubectl get pod -n loggie <LOGGIE_POD> \
  -o jsonpath='{.spec.containers[*].image}{"\n"}'
```

确认：

- 实际镜像名与导入名称完全一致。
- 镜像已导入 Pod 所在节点的实际运行时。
- CPU 架构匹配。
- `imagePullPolicy` 没有强制联网拉取。

### 18.11 日志重复

常见原因：

- stdout 和文件采集了同一份内容。
- 多个 LogConfig 选择器重叠。
- Loggie registry 未持久化，重启后重新读取。
- 文件轮转方式导致 inode/文件名识别变化。
- 升级过程中两套采集器同时运行。

先使用唯一业务字段、文件名、Pod 名和时间范围定位重复来源，不要直接删除历史数据。

## 19. 生产验收清单

### 19.1 配置与版本

- [ ] Loggie Chart、镜像和 CRD 版本匹配。
- [ ] VictoriaLogs、Grafana 和插件使用固定版本或 digest。
- [ ] `helm lint` 和 `helm template` 通过。
- [ ] `docker compose config` 通过。
- [ ] 所有 YAML dry-run 通过。
- [ ] 未使用未替换的占位符。

### 19.2 网络与安全

- [ ] 每个 Kubernetes 节点都能访问 VictoriaLogs `9428`。
- [ ] `9428` 未直接暴露公网。
- [ ] Grafana 通过 HTTPS、VPN 或内网访问。
- [ ] 密码和 Token 未写入 Git、ConfigMap 或文档。
- [ ] Loggie ClusterRole 和节点挂载已审查。
- [ ] Loggie `9196` 未公开暴露。

### 19.3 采集

- [ ] selector 能匹配预期 Pod。
- [ ] stdout 或文件路径与应用实际行为一致。
- [ ] Loggie 每个目标节点均 Ready。
- [ ] source offset 持续增长。
- [ ] sink 无持续错误、重试和积压。
- [ ] 不存在重复采集规则。

### 19.4 存储与查询

- [ ] VictoriaLogs 数据目录使用持久化存储。
- [ ] retention 与业务要求一致。
- [ ] 磁盘至少保留约 20% 空间。
- [ ] Grafana 能查询最近日志。
- [ ] `_msg`、`_time` 和 stream fields 正确。
- [ ] 大时间范围查询设置了限制。

### 19.5 真实验证

- [ ] 唯一测试日志能从源端查询到。
- [ ] VictoriaLogs 能查询到相同唯一标识。
- [ ] Grafana Explore 能查询到相同日志。
- [ ] 记录端到端延迟。
- [ ] 停止测试日志后能确认数据不再增长。
- [ ] 测试资源已定向清理。
- [ ] 已验证升级和回滚步骤。
- [ ] 已验证备份可恢复，而不只是备份任务显示成功。

## 20. 推荐目录结构

```text
logging-platform/
├── README.md
├── versions.env
├── docker/
│   ├── .env
│   ├── docker-compose.yml
│   ├── grafana/
│   │   ├── plugins/
│   │   └── provisioning/
│   │       └── datasources/
│   │           └── victorialogs.yml
│   └── secrets/
├── helm/
│   └── loggie/
├── values/
│   └── loggie-values.yml
├── logconfigs/
│   ├── production-orders-stdout.yml
│   └── production-orders-file.yml
├── tests/
│   ├── loggie-e2e-test.yml
│   └── loggie-e2e-logconfig.yml
└── offline/
    ├── images/
    ├── plugins/
    └── SHA256SUMS
```

不要把 `secrets/`、真实密码文件和环境专用凭据提交到 Git。

## 21. 官方参考资料

- Loggie GitHub：<https://github.com/loggie-io/loggie>
- Loggie Kubernetes 安装：<https://loggie.website.cncfstack.com/getting-started/install/kubernetes/>
- Loggie LogConfig：<https://loggie.website.cncfstack.com/reference/discovery/kubernetes/logconfig/>
- Loggie Kubernetes Discovery：<https://loggie.website.cncfstack.com/reference/global/discovery/>
- Loggie 日志采集排障：<https://loggie.website.cncfstack.com/user-guide/troubleshot/log-collection/>
- VictoriaLogs 快速入门：<https://docs.victoriametrics.com/victorialogs/quickstart/>
- VictoriaLogs 数据写入：<https://docs.victoriametrics.com/victorialogs/data-ingestion/>
- VictoriaLogs 查询：<https://docs.victoriametrics.com/victorialogs/querying/>
- VictoriaLogs 保留与存储：<https://docs.victoriametrics.com/victorialogs/>
- VictoriaLogs Grafana 插件：<https://grafana.com/grafana/plugins/victoriametrics-logs-datasource/>
- Grafana Docker 部署：<https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/>

## 22. 验证状态声明

本文将验证分为三层：

1. **文档与静态配置检查**：检查 Markdown、YAML、Helm 渲染和 Compose 渲染。
2. **测试环境验证**：实际创建测试 Pod 和 LogConfig，验证 VictoriaLogs 与 Grafana 查询。
3. **生产确认**：在目标生产版本、网络、存储、权限和容量下完成变更、监控、回滚和恢复演练。

文档中的命令和配置即使通过静态检查，也不能替代第 2、3 层验证。只有完整日志路径实际产生、采集、写入并查询成功，才能认定部署有效。
