# Helm 3 从入门到生产实践

> 验证基线：Helm `3.21.3`、Kubernetes `1.33–1.36`  
> 资料截止日期：2026-07-23

## 1. 文档概述

### 1.1 先讲结论

Helm 是 Kubernetes 的包管理器。它把一组 Kubernetes YAML、默认配置和发布元数据封装成可版本化的 Chart，并把一次实际部署记录为 Release。

生产使用 Helm 时，最重要的原则是：

1. 固定 Helm、Chart、依赖和镜像版本，不依赖“最新版”。
2. 部署前依次执行 Lint、模板渲染、Schema 校验和临时集群测试。
3. 使用 `upgrade --install` 建立统一发布入口。
4. 生产升级通常启用 `--wait --atomic --timeout`。
5. 不把生产 Secret 明文放入 Values 或 Git。
6. Helm 回滚只能恢复 Kubernetes 资源声明，不能自动回滚数据库、PVC 或外部系统。
7. 在升级 Kubernetes 前检查 Chart 中已废弃或移除的 API。
8. Helm 3 将于 2027-02-10 停止所有安全维护，应尽早验证 Helm 4。

### 1.2 适用读者

本文适合：

- 已了解容器和基本 Kubernetes 对象的开发人员；
- DevOps、平台工程师、SRE；
- 需要建设 Chart、CI/CD 或内部 Chart 仓库的团队。

阅读完成后，你应能够：

- 安装和配置 Helm；
- 安装、升级、回滚和卸载 Release；
- 编写、测试、打包和发布 Chart；
- 使用 HTTP Chart Repository 和 OCI Registry；
- 定位模板、权限、依赖和发布状态问题；
- 建立适合生产环境的 Helm 发布流程。

### 1.3 版本基线与生命周期

截至 2026-07-23：

- Helm 3 最新稳定版为 `v3.21.3`；
- Helm `3.21.x` 使用 Kubernetes `1.36` 客户端库；
- 官方支持 Kubernetes `1.33.x–1.36.x`；
- Helm 不保证与高于其编译客户端版本的 Kubernetes 向前兼容；
- `v3.22.0` 计划于 2026-09-09 发布，但当前尚未发布；
- `v3.22.0` 将是最后一个 Helm 3 次要版本，仅更新 Kubernetes 客户端兼容能力；
- Helm 3 普通缺陷修复持续至 2026-09-09；
- 安全修复持续至 2027-02-10，之后不再发布任何更新。

Helm 官网默认文档已经切换到 Helm 4。部分 `/docs/v3/` 页面显示的文档构建版本仍是 `3.21.1`，晚于页面构建的 `3.21.2`、`3.21.3` 补丁发布没有同步进入文档站版本标识。本文以官方 `v3.21.3` Release 和 `3.21.x` 命令行为基线。

---

## 2. 前置条件

### 2.1 所需工具

建议准备：

- Helm `3.21.3`；
- Kubernetes `1.33–1.36`；
- `kubectl`；
- 可用的 Kubeconfig；
- Git；
- 可选：Kind、Minikube、Docker Desktop Kubernetes；
- 可选：GnuPG、OCI Registry。

检查客户端和集群版本：

```bash
helm version
kubectl version
kubectl config current-context
kubectl cluster-info
```

预期：

- `helm version` 包含 `v3.21.3`；
- Kubernetes Server Version 位于 `v1.33.x–v1.36.x`；
- 当前 Context 指向预期集群。

### 2.2 检查身份和权限

Helm 3 没有 Helm 2 的 Tiller 服务端组件。它直接使用当前 Kubeconfig 身份调用 Kubernetes API，因此不会绕过 RBAC。

检查常见权限：

```bash
kubectl auth can-i create deployments -n default
kubectl auth can-i create services -n default
kubectl auth can-i create secrets -n default
kubectl auth can-i create namespaces
```

预期结果为 `yes`。如果使用 `--create-namespace`，调用者还需要创建 Namespace 的集群级权限。

### 2.3 本地练习集群

以 Kind 为例：

```bash
kind create cluster --name helm-lab

kubectl cluster-info --context kind-helm-lab
kubectl get nodes
```

预期至少有一个状态为 `Ready` 的节点。

---

## 3. 核心概念

### 3.1 Chart

Chart 是 Helm 的应用包，包含：

- Kubernetes 资源模板；
- 默认 Values；
- Chart 名称和版本；
- 依赖声明；
- 可选测试、Hook、CRD 和说明文件。

典型结构：

```text
demo-web/
├── Chart.yaml
├── Chart.lock
├── values.yaml
├── values.schema.json
├── charts/
├── crds/
└── templates/
```

### 3.2 Release

Release 是 Chart 安装到某个 Namespace 后形成的部署实例。

例如：

```bash
helm install demo-web ./demo-web -n demo-web
```

其中：

- `demo-web` 是 Release 名称；
- `./demo-web` 是 Chart；
- `demo-web` Namespace 是 Release 的作用域。

同一 Chart 可以安装多次：

```bash
helm install demo-a ./demo-web -n team-a
helm install demo-b ./demo-web -n team-b
```

两个 Release 的 Values、历史和资源相互独立。

### 3.3 Revision

Revision 是 Release 的历史修订号。首次安装通常为 Revision 1；每次成功或失败的升级、回滚都可能产生新 Revision。

```bash
helm history demo-web -n demo-web
```

不要把 Revision 与 Chart 版本混淆：

- Chart 版本描述软件包版本；
- Revision 描述某个 Release 的操作历史。

### 3.4 Values

Values 是传入模板的配置数据。它可以来自：

- Chart 的 `values.yaml`；
- 父 Chart；
- `-f` 指定的 Values 文件；
- `--set`、`--set-string`、`--set-file`、`--set-json` 等命令行参数。

Helm 将这些值合并后，通过 `.Values` 暴露给模板。

### 3.5 Repository 与 OCI Registry

传统 Chart Repository 是提供以下文件的 HTTP 服务：

```text
index.yaml
demo-web-0.1.0.tgz
demo-web-0.1.0.tgz.prov
```

OCI Registry 则使用容器镜像仓库协议保存 Chart。Helm 自 `3.8.0` 起默认启用 OCI 支持。

新建企业级分发平台时，通常优先评估 OCI，因为它更容易与现有 Registry 的认证、权限、复制和不可变策略结合。

---

## 4. 安装与配置

### 4.1 官方二进制安装

从官方 Release 下载与系统匹配的文件，以 Linux AMD64 为例：

```bash
curl -LO https://get.helm.sh/helm-v3.21.3-linux-amd64.tar.gz
curl -LO https://get.helm.sh/helm-v3.21.3-linux-amd64.tar.gz.sha256sum

sha256sum -c helm-v3.21.3-linux-amd64.tar.gz.sha256sum

tar -xzf helm-v3.21.3-linux-amd64.tar.gz
sudo install -m 0755 linux-amd64/helm /usr/local/bin/helm

helm version
```

为什么校验 SHA-256：防止下载内容损坏或被替换。

macOS Apple Silicon 应下载：

```text
helm-v3.21.3-darwin-arm64.tar.gz
```

官方 Release 页面提供所有平台文件及校验和。

### 4.2 官方安装脚本

官方也提供：

```bash
curl -fsSL -o get_helm.sh \
  https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3

less get_helm.sh
chmod 700 get_helm.sh
./get_helm.sh --version v3.21.3
```

生产环境应先审查脚本，并显式指定版本，不建议直接把远程脚本通过管道交给 Shell。

### 4.3 包管理器

macOS 可使用：

```bash
brew install helm
```

但包管理器版本可能晚于或高于本文基线。安装后必须确认：

```bash
helm version
```

### 4.4 配置目录

查看 Helm 环境：

```bash
helm env
```

常用环境变量：

- `HELM_CACHE_HOME`：缓存目录；
- `HELM_CONFIG_HOME`：配置目录；
- `HELM_DATA_HOME`：数据和插件目录；
- `HELM_NAMESPACE`：默认 Namespace；
- `HELM_DRIVER`：Release 存储驱动；
- `HELM_MAX_HISTORY`：最大历史数量；
- `HELM_REGISTRY_CONFIG`：Registry 凭据配置；
- `HELM_REPOSITORY_CONFIG`：Repository 配置；
- `KUBECONFIG`：Kubernetes 配置文件。

Helm 3 默认以 Secret 保存 Release 元数据。除非有明确需求，不应随意修改 `HELM_DRIVER`。

### 4.5 自动补全

Zsh：

```bash
helm completion zsh > "${fpath[1]}/_helm"
```

Bash：

```bash
helm completion bash | sudo tee /etc/bash_completion.d/helm >/dev/null
```

---

## 5. 常用命令

### 5.1 搜索与查看 Chart

```bash
helm search hub nginx
helm search repo nginx

helm show chart REPOSITORY/CHART
helm show values REPOSITORY/CHART
helm show readme REPOSITORY/CHART
helm show all REPOSITORY/CHART
```

`helm search hub` 搜索 Artifact Hub；`helm search repo` 仅搜索本地已经添加并缓存的仓库索引。

### 5.2 拉取 Chart

```bash
helm pull REPOSITORY/CHART --version 1.2.3
helm pull REPOSITORY/CHART --version 1.2.3 --untar
```

生产流水线应明确指定 `--version`。

### 5.3 安装来源

`helm install` 支持：

```bash
# 本地目录
helm install demo ./demo-web

# 本地包
helm install demo ./demo-web-0.1.0.tgz

# HTTP URL
helm install demo https://charts.example.com/demo-web-0.1.0.tgz

# Repository 引用
helm install demo internal/demo-web --version 0.1.0

# OCI
helm install demo \
  oci://registry.example.com/helm/demo-web \
  --version 0.1.0
```

### 5.4 查询 Release

```bash
helm list -n demo-web
helm list --all-namespaces
helm status demo-web -n demo-web
helm history demo-web -n demo-web

helm get values demo-web -n demo-web
helm get values demo-web -n demo-web --all
helm get manifest demo-web -n demo-web
helm get hooks demo-web -n demo-web
helm get notes demo-web -n demo-web
helm get all demo-web -n demo-web
```

`helm get values` 默认显示用户提供的值；加 `--all` 可查看计算后的完整值。

### 5.5 本地渲染和 Dry Run

```bash
helm template demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml

helm install demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml \
  --dry-run=client \
  --debug \
  --hide-secret
```

区别：

- `helm template` 只在本地渲染；
- `--dry-run=client` 不连接集群；
- `--dry-run=server` 会尝试连接集群，可执行依赖服务端能力的检查；
- Dry Run 可能输出 Secret，处理生产数据时应使用 `--hide-secret` 并保护日志。

---

## 6. 完整案例：demo-web Chart

本案例创建一个可安装的 NGINX Web 应用，包含：

- Deployment；
- Service；
- ConfigMap；
- 可选 Secret；
- ServiceAccount；
- 可选 Ingress；
- 可选 HPA；
- PodDisruptionBudget；
- Helm Test；
- Values Schema。

### 6.1 创建目录

```bash
mkdir -p demo-web/templates/tests
```

最终结构：

```text
demo-web/
├── .helmignore
├── Chart.yaml
├── values.yaml
├── values-prod.yaml
├── values.schema.json
└── templates/
    ├── _helpers.tpl
    ├── configmap.yaml
    ├── deployment.yaml
    ├── hpa.yaml
    ├── ingress.yaml
    ├── NOTES.txt
    ├── pdb.yaml
    ├── secret.yaml
    ├── service.yaml
    ├── serviceaccount.yaml
    └── tests/
        └── test-connection.yaml
```

### 6.2 `Chart.yaml`

```yaml
apiVersion: v2
name: demo-web
description: A production-oriented Helm demo web application
type: application
version: 0.1.0
appVersion: "1.27.4"
kubeVersion: ">=1.33.0-0 <1.37.0-0"
```

说明：

- `apiVersion: v2` 表示 Helm 3 Chart 格式；
- `version` 是 Chart 版本，必须遵循 SemVer；
- `appVersion` 是应用版本，仅作说明，不参与 Chart 版本比较；
- `kubeVersion` 限制本案例的 Kubernetes 版本。

### 6.3 `.helmignore`

```text
.DS_Store
.git/
.gitignore
.idea/
.vscode/
*.tgz
rendered.yaml
```

### 6.4 `values.yaml`

```yaml
replicaCount: 2

image:
  repository: nginxinc/nginx-unprivileged
  tag: "1.27.4-alpine"
  pullPolicy: IfNotPresent

imagePullSecrets: []

nameOverride: ""
fullnameOverride: ""

serviceAccount:
  create: true
  name: ""
  annotations: {}

podAnnotations: {}
podLabels: {}

podSecurityContext:
  runAsNonRoot: true
  runAsUser: 101
  runAsGroup: 101
  fsGroup: 101
  seccompProfile:
    type: RuntimeDefault

containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL

config:
  message: "Hello from demo-web"

secret:
  create: false
  apiKey: ""

service:
  type: ClusterIP
  port: 80
  targetPort: 8080

ingress:
  enabled: false
  className: ""
  annotations: {}
  hosts:
    - host: demo-web.local
      paths:
        - path: /
          pathType: Prefix
  tls: []

resources:
  requests:
    cpu: 50m
    memory: 64Mi
  limits:
    cpu: 200m
    memory: 128Mi

livenessProbe:
  httpGet:
    path: /
    port: http
  initialDelaySeconds: 10
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /
    port: http
  initialDelaySeconds: 3
  periodSeconds: 5

autoscaling:
  enabled: false
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70

podDisruptionBudget:
  enabled: true
  minAvailable: 1

nodeSelector: {}
tolerations: []
affinity: {}
```

### 6.5 `values-prod.yaml`

```yaml
replicaCount: 3

config:
  message: "Hello from the production profile"

secret:
  create: true
  # 仅用于演示。生产环境不要把真实密钥提交到 Git。
  apiKey: "demo-only-change-me"

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 256Mi

podDisruptionBudget:
  enabled: true
  minAvailable: 2
```

### 6.6 `values.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["replicaCount", "image", "service", "resources"],
  "properties": {
    "replicaCount": {
      "type": "integer",
      "minimum": 1
    },
    "image": {
      "type": "object",
      "required": ["repository", "tag", "pullPolicy"],
      "properties": {
        "repository": {
          "type": "string",
          "minLength": 1
        },
        "tag": {
          "type": "string",
          "minLength": 1
        },
        "pullPolicy": {
          "type": "string",
          "enum": ["Always", "IfNotPresent", "Never"]
        }
      }
    },
    "service": {
      "type": "object",
      "required": ["type", "port", "targetPort"],
      "properties": {
        "type": {
          "type": "string",
          "enum": ["ClusterIP", "NodePort", "LoadBalancer"]
        },
        "port": {
          "type": "integer",
          "minimum": 1,
          "maximum": 65535
        },
        "targetPort": {
          "type": "integer",
          "minimum": 1,
          "maximum": 65535
        }
      }
    },
    "secret": {
      "type": "object",
      "properties": {
        "create": {
          "type": "boolean"
        },
        "apiKey": {
          "type": "string"
        }
      }
    }
  }
}
```

Schema 能提前发现类型错误。例如：

```bash
helm lint ./demo-web --set replicaCount=zero
```

预期因 `replicaCount` 不是整数而失败。

### 6.7 `templates/_helpers.tpl`

```gotemplate
{{- define "demo-web.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "demo-web.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "demo-web.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "demo-web.labels" -}}
helm.sh/chart: {{ include "demo-web.chart" . }}
app.kubernetes.io/name: {{ include "demo-web.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "demo-web.selectorLabels" -}}
app.kubernetes.io/name: {{ include "demo-web.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "demo-web.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "demo-web.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}
```

Named Template 是通过 `define` 声明的可复用模板。模板名称是全局的，因此用 Chart 名称作为前缀可减少依赖之间的冲突。

### 6.8 `templates/serviceaccount.yaml`

```gotemplate
{{- if .Values.serviceAccount.create }}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ include "demo-web.serviceAccountName" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
  {{- with .Values.serviceAccount.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
automountServiceAccountToken: false
{{- end }}
```

应用不访问 Kubernetes API，因此关闭 ServiceAccount Token 自动挂载。

### 6.9 `templates/configmap.yaml`

```gotemplate
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "demo-web.fullname" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
data:
  index.html: |
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8">
        <title>demo-web</title>
      </head>
      <body>
        <h1>{{ .Values.config.message }}</h1>
        <p>Release: {{ .Release.Name }}</p>
        <p>Revision: {{ .Release.Revision }}</p>
        <p>Chart: {{ .Chart.Name }} {{ .Chart.Version }}</p>
      </body>
    </html>
```

### 6.10 `templates/secret.yaml`

```gotemplate
{{- if .Values.secret.create }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "demo-web.fullname" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
type: Opaque
stringData:
  api-key: {{ required "secret.apiKey is required when secret.create=true" .Values.secret.apiKey | quote }}
{{- end }}
```

`required` 会在值为空时让渲染失败。

注意：模板生成 Secret 并不意味着 Secret 被安全加密。Helm 默认会把 Release 内容保存在 Kubernetes Secret 中，Values 仍可能出现在发布元数据和流水线日志里。

### 6.11 `templates/deployment.yaml`

```gotemplate
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "demo-web.fullname" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  revisionHistoryLimit: 3
  selector:
    matchLabels:
      {{- include "demo-web.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
        {{- with .Values.podAnnotations }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
      labels:
        {{- include "demo-web.selectorLabels" . | nindent 8 }}
        {{- with .Values.podLabels }}
        {{- toYaml . | nindent 8 }}
        {{- end }}
    spec:
      serviceAccountName: {{ include "demo-web.serviceAccountName" . }}
      securityContext:
        {{- toYaml .Values.podSecurityContext | nindent 8 }}
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: web
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          securityContext:
            {{- toYaml .Values.containerSecurityContext | nindent 12 }}
          ports:
            - name: http
              containerPort: {{ .Values.service.targetPort }}
              protocol: TCP
          {{- if .Values.secret.create }}
          env:
            - name: DEMO_API_KEY
              valueFrom:
                secretKeyRef:
                  name: {{ include "demo-web.fullname" . }}
                  key: api-key
          {{- end }}
          livenessProbe:
            {{- toYaml .Values.livenessProbe | nindent 12 }}
          readinessProbe:
            {{- toYaml .Values.readinessProbe | nindent 12 }}
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          volumeMounts:
            - name: content
              mountPath: /usr/share/nginx/html/index.html
              subPath: index.html
              readOnly: true
            - name: tmp
              mountPath: /tmp
            - name: cache
              mountPath: /var/cache/nginx
      volumes:
        - name: content
          configMap:
            name: {{ include "demo-web.fullname" . }}
        - name: tmp
          emptyDir: {}
        - name: cache
          emptyDir: {}
      {{- with .Values.nodeSelector }}
      nodeSelector:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.affinity }}
      affinity:
        {{- toYaml . | nindent 8 }}
      {{- end }}
      {{- with .Values.tolerations }}
      tolerations:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

`checksum/config` 使 ConfigMap 内容变化时 Pod Template 同步变化，从而触发滚动更新。

### 6.12 `templates/service.yaml`

```gotemplate
apiVersion: v1
kind: Service
metadata:
  name: {{ include "demo-web.fullname" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
spec:
  type: {{ .Values.service.type }}
  selector:
    {{- include "demo-web.selectorLabels" . | nindent 4 }}
  ports:
    - name: http
      port: {{ .Values.service.port }}
      targetPort: http
      protocol: TCP
```

### 6.13 `templates/ingress.yaml`

```gotemplate
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ include "demo-web.fullname" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
  {{- with .Values.ingress.annotations }}
  annotations:
    {{- toYaml . | nindent 4 }}
  {{- end }}
spec:
  {{- with .Values.ingress.className }}
  ingressClassName: {{ . }}
  {{- end }}
  {{- with .Values.ingress.tls }}
  tls:
    {{- toYaml . | nindent 4 }}
  {{- end }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .host | quote }}
      http:
        paths:
          {{- range .paths }}
          - path: {{ .path }}
            pathType: {{ .pathType }}
            backend:
              service:
                name: {{ include "demo-web.fullname" $ }}
                port:
                  number: {{ $.Values.service.port }}
          {{- end }}
    {{- end }}
{{- end }}
```

在 `range` 内，`.` 指向当前列表元素；`$` 始终引用根作用域。

### 6.14 `templates/hpa.yaml`

```gotemplate
{{- if .Values.autoscaling.enabled }}
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: {{ include "demo-web.fullname" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: {{ include "demo-web.fullname" . }}
  minReplicas: {{ .Values.autoscaling.minReplicas }}
  maxReplicas: {{ .Values.autoscaling.maxReplicas }}
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: {{ .Values.autoscaling.targetCPUUtilizationPercentage }}
{{- end }}
```

HPA 依赖 Metrics API。没有 Metrics Server 时可以创建对象，但无法正常计算副本数。

### 6.15 `templates/pdb.yaml`

```gotemplate
{{- if .Values.podDisruptionBudget.enabled }}
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "demo-web.fullname" . }}
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
spec:
  minAvailable: {{ .Values.podDisruptionBudget.minAvailable }}
  selector:
    matchLabels:
      {{- include "demo-web.selectorLabels" . | nindent 6 }}
{{- end }}
```

PDB 只约束自愿中断，例如节点排空；它不保证应用不会因节点故障而中断。

### 6.16 `templates/tests/test-connection.yaml`

```gotemplate
apiVersion: v1
kind: Pod
metadata:
  name: "{{ include "demo-web.fullname" . }}-test-connection"
  labels:
    {{- include "demo-web.labels" . | nindent 4 }}
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  restartPolicy: Never
  containers:
    - name: wget
      image: busybox:1.36.1
      command:
        - wget
      args:
        - -qO-
        - "http://{{ include "demo-web.fullname" . }}:{{ .Values.service.port }}/"
```

测试容器退出码为 0 时，Helm Test 成功。

### 6.17 `templates/NOTES.txt`

```gotemplate
demo-web 已安装。

Release:
  {{ .Release.Name }}

Namespace:
  {{ .Release.Namespace }}

检查状态:
  helm status {{ .Release.Name }} -n {{ .Release.Namespace }}

本地访问:
  kubectl port-forward \
    -n {{ .Release.Namespace }} \
    service/{{ include "demo-web.fullname" . }} \
    8080:{{ .Values.service.port }}

然后访问:
  http://127.0.0.1:8080
```

---

## 7. 验证、安装、升级和回滚案例

### 7.1 Lint

做什么：

```bash
helm lint ./demo-web -f demo-web/values-prod.yaml
```

为什么：检查 Chart 结构、模板和 Values Schema。

预期：

```text
1 chart(s) linted, 0 chart(s) failed
```

### 7.2 模板渲染

```bash
helm template demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml \
  > rendered.yaml
```

检查关键资源：

```bash
grep '^kind:' rendered.yaml
```

也可以执行服务端 Dry Run：

```bash
helm install demo-web ./demo-web \
  -n demo-web \
  --create-namespace \
  -f demo-web/values-prod.yaml \
  --dry-run=server \
  --debug \
  --hide-secret
```

预期不会创建真实资源。

### 7.3 首次安装

```bash
helm install demo-web ./demo-web \
  -n demo-web \
  --create-namespace \
  -f demo-web/values-prod.yaml \
  --wait \
  --atomic \
  --timeout 5m
```

参数含义：

- `--wait`：等待 Pod、PVC、Service 及控制器达到就绪条件；
- `--atomic`：安装失败时删除本次安装，并自动启用 `--wait`；
- `--timeout 5m`：单个 Kubernetes 操作或 Hook 的等待上限。

检查结果：

```bash
helm status demo-web -n demo-web
helm history demo-web -n demo-web
kubectl get all,pdb -n demo-web
```

本地访问：

```bash
kubectl port-forward \
  -n demo-web \
  service/demo-web \
  8080:80
```

另一个终端：

```bash
curl http://127.0.0.1:8080
```

### 7.4 执行 Helm Test

```bash
helm test demo-web -n demo-web --logs
```

预期测试 Pod 成功访问 Service，并以退出码 0 结束。

### 7.5 成功升级

将页面消息和副本数改为新值：

```bash
helm upgrade demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml \
  --set replicaCount=4 \
  --set-string config.message="Hello from revision 2" \
  --wait \
  --atomic \
  --timeout 5m
```

检查：

```bash
helm history demo-web -n demo-web
helm get values demo-web -n demo-web
kubectl rollout status deployment/demo-web -n demo-web
kubectl get pods -n demo-web
```

预期 Release Revision 变为 2，Deployment 完成滚动更新。

### 7.6 制造失败

以下命令使用保留域名 `invalid.invalid`，使镜像无法拉取：

```bash
helm upgrade demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml \
  --set image.repository=invalid.invalid/demo-web \
  --set image.tag=does-not-exist \
  --set image.pullPolicy=Always \
  --wait \
  --timeout 90s
```

这里故意不使用 `--atomic`，以便观察失败状态。

预期：

- 命令超时并返回非零退出码；
- Pod 出现 `ImagePullBackOff`；
- Release 产生失败 Revision。

诊断：

```bash
helm status demo-web -n demo-web
helm history demo-web -n demo-web

kubectl get pods -n demo-web
kubectl describe pods -n demo-web
kubectl get events -n demo-web \
  --sort-by=.metadata.creationTimestamp
```

### 7.7 手动回滚

确认 Revision 2 是上一正常版本：

```bash
helm history demo-web -n demo-web
```

执行：

```bash
helm rollback demo-web 2 \
  -n demo-web \
  --wait \
  --timeout 5m
```

验证：

```bash
helm status demo-web -n demo-web
helm history demo-web -n demo-web
kubectl rollout status deployment/demo-web -n demo-web
helm test demo-web -n demo-web --logs
```

回滚本身会创建新 Revision。例如从失败的 Revision 3 回滚到 Revision 2 后，当前 Revision 通常变为 4。

如果省略 Revision 或指定 0，Helm 会尝试回滚至前一个版本：

```bash
helm rollback demo-web 0 -n demo-web
```

生产操作更推荐先通过 `helm history` 明确目标 Revision。

### 7.8 自动回滚

生产升级常用：

```bash
helm upgrade demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml \
  --wait \
  --atomic \
  --timeout 5m \
  --history-max 20
```

升级失败时，`--atomic` 会回滚本次变更。它不能撤销：

- 数据库迁移；
- 外部 API 操作；
- 云资源状态；
- PVC 中的数据修改；
- 不具备反向逻辑的 Hook。

### 7.9 卸载

```bash
helm uninstall demo-web -n demo-web
kubectl get all -n demo-web
```

如果 Namespace 也不再需要：

```bash
kubectl delete namespace demo-web
```

Helm 不一定删除：

- 带 `helm.sh/resource-policy: keep` 的资源；
- `crds/` 中安装的 CRD；
- Chart 外部创建的资源；
- 某些 PVC 和云基础设施。

---

## 8. Chart 开发与模板

### 8.1 模板基本语法

Helm 使用 Go Template：

```gotemplate
name: {{ .Release.Name }}
image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
```

常用控制结构：

```gotemplate
{{- if .Values.ingress.enabled }}
# ...
{{- end }}

{{- with .Values.podAnnotations }}
annotations:
  {{- toYaml . | nindent 2 }}
{{- end }}

{{- range .Values.ingress.hosts }}
- host: {{ .host | quote }}
{{- end }}
```

### 8.2 内置对象

常用对象：

- `.Values`：最终合并的配置；
- `.Release`：Release 名称、Namespace、Revision 等；
- `.Chart`：`Chart.yaml` 元数据；
- `.Capabilities`：集群 API 和 Kubernetes 版本能力；
- `.Template`：当前模板信息；
- `.Files`：访问 Chart 内非模板文件。

例如按 API 能力选择资源：

```gotemplate
{{- if .Capabilities.APIVersions.Has "policy/v1/PodDisruptionBudget" }}
apiVersion: policy/v1
{{- else }}
{{- fail "This chart requires policy/v1 PodDisruptionBudget" }}
{{- end }}
```

### 8.3 函数和 Pipeline

Pipeline 把左侧结果传给右侧函数：

```gotemplate
name: {{ .Values.name | default .Chart.Name | trunc 63 | trimSuffix "-" }}
```

常用函数：

```gotemplate
{{ required "image.repository is required" .Values.image.repository }}
{{ .Values.config | toYaml | nindent 4 }}
{{ include "demo-web.fullname" . }}
{{ .Values.enabled | default false }}
```

`tpl` 会把字符串再次当成模板执行：

```gotemplate
{{ tpl .Values.dynamicTemplate . }}
```

它提高灵活性，也扩大配置输入的执行能力，应限制不可信 Values 使用。

`lookup` 可以在渲染时查询集群：

```gotemplate
{{ lookup "v1" "Secret" .Release.Namespace "existing-secret" }}
```

它会使渲染结果依赖实时集群状态，降低可重复性；普通离线 `helm template` 也无法模拟全部行为。

### 8.4 YAML 类型与引号

以下值可能被 YAML 解析为不同类型：

```yaml
enabled: true
port: 8080
version: "1.0"
largeId: "12345678901234567890"
```

命令行需要强制字符串时使用：

```bash
helm install demo ./chart \
  --set-string image.tag=1.0
```

长文本或文件内容使用：

```bash
helm install demo ./chart \
  --set-file config.script=./startup.sh
```

JSON 对象或数组使用：

```bash
helm install demo ./chart \
  --set-json 'extraEnv=[{"name":"MODE","value":"prod"}]'
```

### 8.5 CRD

放在 `crds/` 的 CRD：

- 在普通模板前安装；
- 不经过模板渲染；
- 默认只在不存在时创建；
- Helm 不负责升级或删除。

原因是删除 CRD 可能同时删除所有 Custom Resource 数据。生产环境应为 CRD 建立独立升级和备份流程。

### 8.6 Hooks

Hook 是在发布生命周期特定阶段执行的 Kubernetes 资源。

常见注解：

```yaml
metadata:
  annotations:
    helm.sh/hook: pre-upgrade
    helm.sh/hook-weight: "-10"
    helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded
```

常见阶段：

- `pre-install`、`post-install`；
- `pre-upgrade`、`post-upgrade`；
- `pre-rollback`、`post-rollback`；
- `pre-delete`、`post-delete`；
- `test`。

Hook Job 应具备：

- 幂等性；
- 明确超时；
- 可重复执行能力；
- 清理策略；
- 数据变更的反向方案。

---

## 9. Values 优先级

从低到高：

1. 当前 Chart 的 `values.yaml`；
2. 父 Chart 对子 Chart 的覆盖；
3. 用户通过 `-f` 提供的文件；
4. 命令行 `--set*`。

多个文件或参数中，右侧优先：

```bash
helm upgrade demo ./chart \
  -f values-common.yaml \
  -f values-prod.yaml \
  --set replicaCount=4 \
  --set replicaCount=5
```

最终 `replicaCount` 为 5。

查看用户值：

```bash
helm get values demo -n namespace
```

查看计算后的全部值：

```bash
helm get values demo -n namespace --all
```

删除默认键可将其覆盖为 `null`：

```yaml
livenessProbe:
  httpGet: null
  exec:
    command:
      - /bin/check
```

### 9.1 升级时的 Values 策略

默认情况下，应明确重新提供期望的 Values 文件：

```bash
helm upgrade demo ./chart -f values-prod.yaml
```

`--reuse-values` 会复用上次 Release 的值，再合并新参数：

```bash
helm upgrade demo ./chart \
  --reuse-values \
  --set image.tag=2.0.0
```

风险是旧 Chart 已废弃的键可能继续存在。

`--reset-values` 会从新 Chart 默认值重新开始：

```bash
helm upgrade demo ./chart \
  --reset-values \
  -f values-prod.yaml
```

`--reset-then-reuse-values` 会先重置为新 Chart 默认值，再合并上次 Release 的值和本次覆盖。

生产上更可审计的做法是：

- 将期望配置保存在受版本控制的 Values 文件中；
- 每次发布显式传入；
- 避免依赖 Release 中不可见的历史值。

---

## 10. 依赖管理

### 10.1 声明依赖

依赖写在 `Chart.yaml`：

```yaml
dependencies:
  - name: redis
    version: "REPLACE_WITH_VERIFIED_VERSION"
    repository: "https://charts.bitnami.com/bitnami"
    condition: redis.enabled
```

这里没有写死第三方版本，因为可用版本会持续变化。先查询：

```bash
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update
helm search repo bitnami/redis --versions
```

从结果中选择经过测试的精确版本，然后替换占位符。

Values：

```yaml
redis:
  enabled: false
  auth:
    enabled: true
    existingSecret: demo-redis-auth
```

### 10.2 `dependency update` 与 `build`

更新依赖：

```bash
helm dependency update ./demo-web
```

作用：

- 读取 `Chart.yaml`；
- 解析满足约束的最新版本；
- 下载到 `charts/`；
- 生成或更新 `Chart.lock`。

根据锁文件重建：

```bash
helm dependency build ./demo-web
```

生产构建推荐：

1. 评审 `Chart.yaml` 和 `Chart.lock`；
2. 提交锁文件；
3. CI 使用 `helm dependency build`；
4. 不在每次生产构建时重新解析浮动范围。

### 10.3 子 Chart Values

父 Chart 可通过依赖名称覆盖子 Chart：

```yaml
redis:
  architecture: standalone
  auth:
    enabled: true
```

所有子 Chart 均可访问：

```yaml
global:
  imageRegistry: registry.example.com
```

是否支持某个 `global` 键取决于子 Chart 模板，不是 Helm 自动理解所有全局配置。

### 10.4 Alias、Condition 与 Tags

```yaml
dependencies:
  - name: redis
    alias: cache
    version: "REPLACE_WITH_VERIFIED_VERSION"
    repository: "https://charts.bitnami.com/bitnami"
    condition: cache.enabled
    tags:
      - backend
```

Alias 可多次引入同一 Chart；Condition 和 Tags 控制是否渲染该依赖。

---

## 11. HTTP Chart Repository

### 11.1 创建本地仓库

打包：

```bash
mkdir -p chart-repo

helm package ./demo-web \
  --destination ./chart-repo
```

预期生成：

```text
chart-repo/demo-web-0.1.0.tgz
```

生成索引：

```bash
helm repo index ./chart-repo \
  --url http://127.0.0.1:8879
```

启动本地 HTTP 服务：

```bash
python3 -m http.server 8879 \
  --directory ./chart-repo
```

另一个终端：

```bash
helm repo add local-demo http://127.0.0.1:8879
helm repo update
helm search repo local-demo/demo-web --versions
helm show values local-demo/demo-web --version 0.1.0
```

安装：

```bash
helm install demo-web local-demo/demo-web \
  --version 0.1.0 \
  -n demo-web \
  --create-namespace \
  -f demo-web/values-prod.yaml
```

### 11.2 更新索引

发布新版本前修改：

```yaml
version: 0.1.1
```

然后：

```bash
helm package ./demo-web --destination ./chart-repo

helm repo index ./chart-repo \
  --url https://charts.example.com \
  --merge ./chart-repo/index.yaml
```

应同时原子化上传：

- 新 `.tgz`；
- 新 `.prov`，如果启用签名；
- 更新后的 `index.yaml`。

不要覆盖已发布的相同版本包。否则客户端缓存、Digest 和审计记录可能互相矛盾。

### 11.3 Repository 缓存

```bash
helm repo update
```

会刷新本地索引缓存。遇到“服务器已有版本但搜索不到”时，先检查：

```bash
helm repo list
helm repo update
helm search repo REPO/CHART --versions
```

---

## 12. OCI Registry

### 12.1 登录

```bash
helm registry login registry.example.com
```

CI 中可使用标准输入：

```bash
printf '%s' "$REGISTRY_PASSWORD" |
  helm registry login registry.example.com \
    --username "$REGISTRY_USERNAME" \
    --password-stdin
```

避免把密码直接写入命令行参数或日志。

### 12.2 打包和推送

```bash
helm package ./demo-web
```

推送时目标地址不能包含 Chart 名称或 Tag；Helm 根据 `Chart.yaml` 推导它们：

```bash
helm push demo-web-0.1.0.tgz \
  oci://registry.example.com/helm
```

实际对象为：

```text
oci://registry.example.com/helm/demo-web:0.1.0
```

### 12.3 拉取和安装

```bash
helm pull \
  oci://registry.example.com/helm/demo-web \
  --version 0.1.0
```

安装：

```bash
helm install demo-web \
  oci://registry.example.com/helm/demo-web \
  --version 0.1.0 \
  -n demo-web \
  --create-namespace \
  -f demo-web/values-prod.yaml
```

生产 Registry 应启用：

- TLS；
- 最小权限；
- 不可变 Tag；
- 审计日志；
- 跨区域复制；
- 保留和清理策略；
- Chart 签名或组织级验证策略。

---

## 13. 发布生命周期

### 13.1 安装

简化流程：

1. 读取 Chart 和依赖；
2. 合并 Values；
3. 校验 Schema；
4. 渲染模板；
5. 安装 CRD；
6. 执行 Pre-install Hook；
7. 创建普通资源；
8. 根据参数等待就绪；
9. 执行 Post-install Hook；
10. 保存 Release Revision。

### 13.2 统一安装与升级入口

CI/CD 常用：

```bash
helm upgrade --install demo-web ./demo-web \
  -n demo-web \
  --create-namespace \
  -f demo-web/values-prod.yaml \
  --wait \
  --atomic \
  --timeout 10m \
  --history-max 20
```

`--install` 表示 Release 不存在时执行安装。

### 13.3 清理失败新资源

升级时可选：

```bash
helm upgrade demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml \
  --cleanup-on-fail
```

`--cleanup-on-fail` 会尝试删除本次升级中新创建的资源，但不能恢复外部副作用。

### 13.4 Release 历史

Helm 3.21 的 `helm upgrade --history-max` 默认值为 10；`0` 表示不限制。

不限制历史可能导致 Namespace 中积累大量 Release Secret。生产应根据审计和恢复需求设置合理上限。

---

## 14. 测试与验证

推荐流水线：

```text
Schema/Lint
    ↓
模板渲染
    ↓
Kubernetes Schema 校验
    ↓
安全与废弃 API 扫描
    ↓
临时集群安装
    ↓
helm test
    ↓
升级/回滚测试
    ↓
打包、签名、发布
```

### 14.1 基础验证

```bash
helm lint ./demo-web -f demo-web/values-prod.yaml

helm template demo-web ./demo-web \
  -n demo-web \
  -f demo-web/values-prod.yaml \
  > rendered.yaml
```

随后可将 `rendered.yaml` 交给：

- Kubernetes Schema 校验器；
- Policy as Code；
- 安全扫描器；
- 废弃 API 扫描器。

这些工具不是 Helm 内建命令，应在团队中固定版本和规则。

### 14.2 多 Kubernetes 版本测试

由于本文支持 Kubernetes `1.33–1.36`，关键 Chart 应至少对最低和最高版本测试：

```text
Kubernetes 1.33
Kubernetes 1.36
```

测试范围包括：

- 安装；
- 幂等升级；
- Values 变化；
- Chart 版本升级；
- 失败回滚；
- 卸载；
- CRD 和 Hook。

### 14.3 Helm Test

测试资源必须包含：

```yaml
annotations:
  helm.sh/hook: test
```

执行：

```bash
helm test RELEASE -n NAMESPACE --logs
```

Helm Test 适合验证：

- Service 是否可访问；
- 配置是否注入；
- 数据库认证是否有效；
- 关键应用 API 是否返回成功。

它不能替代完整端到端测试和监控。

---

## 15. 安全

### 15.1 RBAC 最小权限

Helm 使用当前 Kubernetes 身份。生产 CI 不应长期使用 `cluster-admin`。

检查实际权限：

```bash
kubectl auth can-i --list -n demo-web
```

对于只部署 Namespace 资源的流水线，应尽量使用 Namespace 级 Role 和 RoleBinding。

集群级资源需要单独审批，例如：

- CRD；
- ClusterRole；
- ClusterRoleBinding；
- ValidatingWebhookConfiguration；
- MutatingWebhookConfiguration；
- StorageClass。

### 15.2 Kubeconfig

建议：

- CI 使用短期凭据；
- 限制 Kubeconfig 文件权限；
- 不在日志打印 Token；
- 显式指定 Context；
- 不使用 `--kube-insecure-skip-tls-verify`；
- 私有 CA 应通过可信 CA 文件配置。

部署前检查：

```bash
kubectl config current-context
kubectl auth whoami
```

`kubectl auth whoami` 是否可用取决于 Kubernetes 版本；本文基线版本支持该命令。

### 15.3 Secret

不要这样做：

```bash
helm upgrade demo ./chart \
  --set database.password='real-production-password'
```

命令可能进入：

- Shell 历史；
- 进程参数；
- CI 日志；
- Helm Release 元数据。

推荐方案：

- External Secrets Operator；
- Secrets Store CSI Driver；
- SOPS 加密文件；
- 云密钥管理服务；
- 预先创建 Secret，然后让 Chart 只引用名称。

例如：

```yaml
secret:
  create: false
  existingSecret: demo-web-production
```

### 15.4 Chart 签名和验证

Helm Provenance 使用 OpenPGP 对 Chart 包进行签名，并生成 `.prov` 文件。

签名：

```bash
helm package ./demo-web \
  --sign \
  --key "release@example.com" \
  --keyring /secure/path/secring.gpg
```

验证：

```bash
helm verify demo-web-0.1.0.tgz \
  --keyring /secure/path/pubring.gpg
```

安装时验证：

```bash
helm install demo-web ./demo-web-0.1.0.tgz \
  --verify \
  --keyring /secure/path/pubring.gpg \
  -n demo-web
```

验证失败时，Helm 会在渲染前停止安装。

签名只有在以下条件成立时才有意义：

- 签名者身份可信；
- 公钥分发可信；
- 私钥得到保护；
- CI 对验证失败采取阻断策略。

### 15.5 插件和 Post-renderer

Helm 3 的插件和 Post-renderer 是本地可执行代码，能够：

- 访问当前用户文件；
- 使用当前网络权限；
- 修改全部渲染 Manifest；
- 读取传入的数据。

因此必须：

- 只安装可信来源；
- 固定版本；
- 检查代码和校验和；
- 隔离 CI 执行环境；
- 不允许未经审查的 Chart 自行决定 Post-renderer。

### 15.6 供应链

生产建议同时固定：

```text
Helm 版本
Chart 版本
Chart 依赖版本
Chart Digest
容器镜像 Digest
CI 工具版本
策略规则版本
```

仅固定 Chart 版本但使用浮动镜像 Tag，仍然不能保证可重复部署。

---

## 16. 生产最佳实践

### 16.1 Chart 设计

- 提供安全默认值；
- Values 是公开接口，应保持向后兼容；
- 避免在模板中加入过多业务逻辑；
- 始终提供资源 Requests；
- 合理设置 Limits；
- 配置 Readiness 和 Liveness Probe；
- 重要应用配置 PDB 和反亲和性；
- 支持外部 Secret；
- 使用标准 Kubernetes 标签；
- Hook 必须幂等。

### 16.2 多环境配置

推荐：

```text
values.yaml
values-dev.yaml
values-staging.yaml
values-prod.yaml
```

调用：

```bash
helm upgrade --install demo ./chart \
  -f values.yaml \
  -f values-prod.yaml
```

不要复制多份 Chart 分别服务不同环境，这会导致模板逻辑逐渐漂移。

### 16.3 版本策略

生产安装：

```bash
helm upgrade --install demo internal/demo-web \
  --version 1.4.2 \
  -f values-prod.yaml
```

不推荐省略 `--version`：

```bash
helm install demo internal/demo-web
```

后者会选择仓库中满足条件的最新稳定版本，导致不同时间执行得到不同结果。

### 16.4 发布记录

每次发布至少记录：

- Git Commit；
- Helm 版本；
- Chart 名称和版本；
- Chart Digest；
- 镜像 Digest；
- Values 文件版本；
- Kubernetes Context；
- Namespace；
- Release Revision；
- 审批人；
- 验证结果。

### 16.5 灰度和回滚

Helm 本身不提供完整的渐进式交付控制器。可以通过：

- 两个 Release；
- Ingress 权重；
- Service Mesh；
- 专门的 Rollout 控制器；

实现 Canary 或 Blue/Green。

必须明确谁拥有资源。不要让 Helm CLI、Argo CD 和 Flux 同时修改同一 Release 或同一批资源。

### 16.6 灾难恢复

应保存：

- Chart 包；
- `Chart.lock`；
- Values；
- 镜像；
- CRD；
- 数据备份；
- 外部依赖恢复流程。

只备份 Helm Release Secret 不等于完成应用灾难恢复。

---

## 17. 常见问题与系统化排障

### 17.1 标准排障顺序

#### 第一步：确认目标环境

```bash
helm version
kubectl version
kubectl config current-context
kubectl get namespace
```

#### 第二步：确认 Release

```bash
helm list --all-namespaces
helm status RELEASE -n NAMESPACE
helm history RELEASE -n NAMESPACE
```

#### 第三步：导出 Helm 输入和输出

```bash
helm get values RELEASE -n NAMESPACE --all
helm get manifest RELEASE -n NAMESPACE
helm get hooks RELEASE -n NAMESPACE
```

#### 第四步：检查 Kubernetes

```bash
kubectl get all -n NAMESPACE
kubectl get events -n NAMESPACE \
  --sort-by=.metadata.creationTimestamp

kubectl describe pod POD -n NAMESPACE
kubectl logs POD -n NAMESPACE --all-containers
```

#### 第五步：重新渲染比较

```bash
helm template RELEASE ./chart \
  -n NAMESPACE \
  -f values.yaml \
  --debug
```

比较：

- 期望 Manifest；
- Release 中保存的 Manifest；
- 集群实际对象。

### 17.2 `Kubernetes cluster unreachable`

常见原因：

- Kubeconfig 路径错误；
- Context 错误；
- 凭据过期；
- VPN 或网络未连接；
- API Server 证书或 DNS 问题。

检查：

```bash
kubectl cluster-info
kubectl auth can-i get pods -n default
helm env
```

### 17.3 `Forbidden`

现象：

```text
Error: INSTALLATION FAILED: ... is forbidden
```

检查：

```bash
kubectl auth can-i create deployments -n TARGET
kubectl auth can-i create secrets -n TARGET
```

注意 Helm 还需要保存 Release Secret。

### 17.4 `release: already exists`

检查：

```bash
helm list -n NAMESPACE --all
helm history RELEASE -n NAMESPACE
```

不要直接使用 `--replace` 作为常规修复。官方明确提示它在生产环境不安全。应先判断：

- Release 是否仍存在；
- 是否使用了错误 Namespace；
- 是否应升级而不是安装；
- 是否应卸载旧 Release。

### 17.5 `nil pointer evaluating interface`

通常是 Values 路径不存在：

```gotemplate
{{ .Values.database.credentials.username }}
```

如果 `database` 或 `credentials` 不存在，可能报错。

改进方式：

```gotemplate
{{- with .Values.database }}
{{- with .credentials }}
username: {{ required "database.credentials.username is required" .username }}
{{- end }}
{{- end }}
```

同时使用 `values.schema.json` 提前约束结构。

### 17.6 YAML 缩进错误

使用：

```bash
helm template demo ./chart --debug
```

常见问题：

```gotemplate
resources:
{{ toYaml .Values.resources }}
```

应写为：

```gotemplate
resources:
  {{- toYaml .Values.resources | nindent 2 }}
```

### 17.7 Pending 状态

可能原因：

- 上一次 Helm 进程中断；
- Hook 卡住；
- API Server 超时；
- 多个发布任务并发操作同一 Release。

检查：

```bash
helm history RELEASE -n NAMESPACE
kubectl get secrets -n NAMESPACE \
  -l owner=helm,name=RELEASE
```

先确认没有发布任务仍在运行，再决定回滚。不要未经分析直接删除 Release Secret，否则可能破坏历史链。

### 17.8 资源已存在但不属于当前 Release

Helm 通过标签和注解判断所有权。典型元数据包括：

```yaml
metadata:
  labels:
    app.kubernetes.io/managed-by: Helm
  annotations:
    meta.helm.sh/release-name: demo
    meta.helm.sh/release-namespace: default
```

不要随意接管现有资源。Helm 3.21 提供 `--take-ownership`，但它会忽略现有 Helm 所有权检查；使用前必须确认资源没有被其他 Release 或控制器管理。

### 17.9 升级因不可变字段失败

常见不可变字段：

- Deployment Selector；
- Service ClusterIP 的部分属性；
- StatefulSet 的部分字段；
- Job Pod Template。

优先方案：

- 保持不可变字段稳定；
- 迁移到新资源名；
- 制定有状态迁移流程。

`--force` 会采用替换策略，可能造成删除重建和中断，不能作为默认升级参数。

### 17.10 已移除 Kubernetes API

检查 Release：

```bash
helm get manifest RELEASE -n NAMESPACE
```

在升级 Kubernetes 前：

1. 找出废弃 API；
2. 升级到使用受支持 API 的 Chart；
3. 验证成功；
4. 再升级集群。

如果集群已经删除旧 API，Helm 可能无法解析历史 Manifest，从而无法升级。官方建议使用 `mapkubeapis` 插件或谨慎修改 Release 中保存的 Manifest。直接编辑 Release Secret 风险很高，必须先备份并在非生产环境演练。

### 17.11 Repository 找不到版本

```bash
helm repo list
helm repo update
helm search repo REPO/CHART --versions
```

再确认：

- `index.yaml` 是否包含目标版本；
- URL 是否正确；
- 客户端缓存是否刷新；
- Chart 版本是否为合法 SemVer；
- 是否为预发布版本。

预发布版本需要明确版本约束或使用适当的开发版本选项。

### 17.12 OCI 登录或推送失败

检查：

```bash
helm registry login registry.example.com
helm push chart-1.0.0.tgz oci://registry.example.com/team
```

常见原因：

- 登录地址包含错误路径；
- 推送目标包含了 Chart 名称或 Tag；
- Registry 不支持所需 OCI Artifact；
- Token 没有 Push 权限；
- 私有 CA 未配置；
- Registry 禁止覆盖现有 Tag。

---

## 18. 命令速查

### 环境

```bash
helm version
helm env
helm help
helm COMMAND --help
```

### Repository

```bash
helm repo add NAME URL
helm repo list
helm repo update
helm repo remove NAME
helm search repo KEYWORD
helm search hub KEYWORD
```

### Chart

```bash
helm create NAME
helm lint PATH
helm template RELEASE PATH
helm show chart CHART
helm show values CHART
helm pull CHART --version VERSION
helm package PATH
```

### 依赖

```bash
helm dependency list PATH
helm dependency update PATH
helm dependency build PATH
```

### Release

```bash
helm install RELEASE CHART
helm upgrade RELEASE CHART
helm upgrade --install RELEASE CHART
helm rollback RELEASE REVISION
helm uninstall RELEASE
```

### 查询

```bash
helm list -n NAMESPACE
helm list --all-namespaces
helm status RELEASE -n NAMESPACE
helm history RELEASE -n NAMESPACE
helm get values RELEASE -n NAMESPACE
helm get manifest RELEASE -n NAMESPACE
helm get hooks RELEASE -n NAMESPACE
helm get all RELEASE -n NAMESPACE
```

### 测试

```bash
helm lint PATH
helm template RELEASE PATH
helm install RELEASE PATH --dry-run=client --debug --hide-secret
helm test RELEASE -n NAMESPACE --logs
```

### OCI

```bash
helm registry login HOST
helm registry logout HOST
helm push PACKAGE oci://HOST/PATH
helm pull oci://HOST/PATH/CHART --version VERSION
helm install RELEASE oci://HOST/PATH/CHART --version VERSION
```

### 签名

```bash
helm package PATH --sign --key KEY --keyring SECRET_KEYRING
helm verify PACKAGE --keyring PUBLIC_KEYRING
helm install RELEASE PACKAGE --verify --keyring PUBLIC_KEYRING
```

### 常用发布参数

```text
-n, --namespace
-f, --values
--set
--set-string
--set-file
--set-json
--create-namespace
--version
--wait
--wait-for-jobs
--timeout
--atomic
--history-max
--dry-run=client
--dry-run=server
--debug
--hide-secret
--verify
```

---

## 19. Helm 4 迁移提示

Helm 3 Chart 通常可继续由 Helm 4 使用，但迁移前必须验证：

1. 在非生产环境用 Helm 4 安装现有 Chart；
2. 用 Helm 4 管理现有 Helm 3 Release；
3. 测试 CI/CD 脚本；
4. 检查插件；
5. 检查 Post-renderer；
6. 检查 Registry 登录；
7. 验证安装、升级和回滚；
8. 确认 Server-side Apply 行为。

重要差异包括：

- Helm 4 新 Release 默认采用 Server-side Apply；
- Helm 3 创建的既有 Release 升级时通常保持原有 Client-side Apply 行为；
- Helm 4 将 `--atomic` 更名为 `--rollback-on-failure`；
- Helm 4 将 `--force` 更名为 `--force-replace`；
- 旧参数目前可能仍兼容，但会产生弃用警告；
- Post-renderer 和插件机制存在变化。

建议在 2027-02-10 前完成迁移，不要把 Helm 3 停止维护视为普通补丁升级。

---

## 20. 总结

Helm 的核心不是“把 YAML 放进模板”，而是建立可版本化、可验证、可回滚的 Kubernetes 发布单元。

一套可靠的生产流程应当做到：

```text
固定版本
→ 校验依赖
→ Lint
→ 模板渲染
→ Schema 与安全检查
→ 临时集群测试
→ 审批
→ 原子升级
→ 业务验证
→ 记录 Revision
→ 保留可执行回滚方案
```

最后需要再次强调：

- Helm 回滚不等于数据回滚；
- Secret 模板不等于安全的 Secret 管理；
- Chart 版本固定不等于镜像版本固定；
- 安装成功不等于业务可用；
- Kubernetes 升级前必须审计已废弃 API；
- Helm 3 已进入生命周期末期，应尽快规划 Helm 4。

## 官方参考资料

- [Helm 3 文档首页](https://helm.sh/docs/v3/)
- [Helm v3.21.3 Release](https://github.com/helm/helm/releases/tag/v3.21.3)
- [Helm 版本兼容策略](https://helm.sh/docs/v3/topics/version_skew/)
- [Helm 3 生命周期公告](https://helm.sh/blog/helm-v3-end-of-life/)
- [安装 Helm](https://helm.sh/docs/v3/intro/install/)
- [Helm 命令参考](https://helm.sh/docs/v3/helm/helm/)
- [`helm install`](https://helm.sh/docs/v3/helm/helm_install/)
- [`helm upgrade`](https://helm.sh/docs/v3/helm/helm_upgrade/)
- [`helm rollback`](https://helm.sh/docs/v3/helm/helm_rollback/)
- [Chart 格式](https://helm.sh/docs/v3/topics/charts/)
- [Chart Template Guide](https://helm.sh/docs/v3/chart_template_guide/)
- [Values 文件](https://helm.sh/docs/v3/chart_template_guide/values_files/)
- [Chart 最佳实践](https://helm.sh/docs/v3/chart_best_practices/)
- [Chart Hooks](https://helm.sh/docs/v3/topics/charts_hooks/)
- [Chart Tests](https://helm.sh/docs/v3/topics/chart_tests/)
- [Chart Repository Guide](https://helm.sh/docs/v3/topics/chart_repository/)
- [OCI Registry](https://helm.sh/docs/v3/topics/registries/)
- [Provenance 与完整性](https://helm.sh/docs/v3/topics/provenance/)
- [RBAC](https://helm.sh/docs/v3/topics/rbac/)
- [废弃 Kubernetes API](https://helm.sh/docs/v3/topics/kubernetes_apis/)
