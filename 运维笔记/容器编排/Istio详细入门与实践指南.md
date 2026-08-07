# Istio 是做什么的，以及如何使用

> 资料基准：Istio 官方文档，核实日期为 **2026-07-24**。  
> 当前稳定补丁版本：**Istio 1.30.3**，发布于 **2026-07-16**。  
> 本文以 Kubernetes 上的 Sidecar 模式为主线，并单独说明 Ambient Mesh。

## 1. 文档目标

### 适合读者

- 第一次接触 Istio、Service Mesh 的开发人员。
- 已具备 Kubernetes 基础的开发、运维和平台工程人员。
- 正在评估微服务流量治理、零信任安全和可观测性方案的团队。

### 阅读收益

完成本文后，你将能够：

1. 理解 Istio、Service Mesh、数据平面和控制平面的作用。
2. 在 Kubernetes 中安装 Istio 1.30.3。
3. 部署并访问完整的 Bookinfo 示例应用。
4. 配置 Sidecar 注入、流量路由、灰度发布和流量拆分。
5. 启用严格 mTLS、JWT 认证和服务间授权。
6. 查看指标、访问日志、链路追踪和 Kiali 服务拓扑。
7. 判断应该选择 Sidecar 还是 Ambient 模式。
8. 完成基本生产规划、故障排查和卸载。

---

## 2. 先讲结论：Istio 到底解决什么问题

Istio 是一个开源的 **Service Mesh（服务网格）**。它把微服务之间的网络通信能力从业务代码中抽离出来，统一处理：

- 服务发现和负载均衡。
- 按版本、请求头、路径等条件路由。
- 灰度发布和流量拆分。
- 超时、重试、熔断和故障注入。
- 服务间双向 TLS 加密。
- 工作负载身份认证和访问授权。
- 请求指标、访问日志和分布式链路追踪。
- 集群入口和出口流量控制。

没有 Istio 时，每个应用可能需要自行实现重试、TLS、指标和路由逻辑。使用 Istio 后，这些能力主要由代理和控制平面提供，业务代码通常不需要直接依赖 Istio SDK。

但 Istio 并不是“安装后自动解决所有微服务问题”：

- 它不会修复错误的业务逻辑。
- 它不能替代应用自身的超时、幂等和事务设计。
- 它增加了代理、控制平面、配置和排障复杂度。
- 小型系统或通信关系简单的系统未必值得引入。

---

## 3. 核心概念

### 3.1 Service Mesh

Service Mesh 是运行在应用之外的服务通信基础设施层。

可以把它理解成一个由代理构成的网络：

```text
服务 A → 代理 A → 网络 → 代理 B → 服务 B
```

代理负责路由、安全和遥测，应用继续使用普通 HTTP、gRPC 或 TCP 进行通信。

### 3.2 数据平面

**数据平面（Data Plane）** 是实际转发业务请求的代理集合。

Istio 支持两种数据平面模式：

- **Sidecar 模式**：每个应用 Pod 内运行一个 Envoy 代理。
- **Ambient 模式**：每个节点运行一个 `ztunnel` 四层代理，需要七层能力时再使用 Waypoint 代理。

### 3.3 控制平面

**控制平面（Control Plane）** 负责生成和下发代理配置，但通常不直接转发业务请求。

Istio 的控制平面核心组件是 `istiod`，负责：

- 读取 Kubernetes Service、Endpoint 和 Istio 配置。
- 将路由、负载均衡和安全策略转换为 Envoy 配置。
- 通过 xDS 协议向代理推送配置。
- 为工作负载签发和轮换身份凭证。
- 处理配置校验和 Sidecar 自动注入。

即使 `istiod` 短暂不可用，已有代理通常仍可使用最后一次收到的配置继续转发请求；但新配置、证书更新和新工作负载接入会受影响。

### 3.4 Envoy

Envoy 是 Istio Sidecar、Gateway 和 Waypoint 使用的高性能代理。

它可以处理：

- HTTP/1.1、HTTP/2、gRPC 和 TCP。
- 路由、重试、超时和负载均衡。
- TLS/mTLS。
- 指标、访问日志和链路追踪 Span。

### 3.5 mTLS

**mTLS（Mutual TLS，双向 TLS）** 是通信双方都验证对方证书的加密协议。

普通 TLS 通常只验证服务端；mTLS 同时验证客户端身份，因此可以回答：

- 请求是否被加密？
- 调用方是谁？
- 调用方是否被允许访问目标服务？

### 3.6 Gateway

Gateway 是网格边界上的独立代理，用于接收或发出集群流量：

- **Ingress Gateway**：处理进入集群的流量。
- **Egress Gateway**：集中处理离开集群的流量。
- **East-West Gateway**：处理多集群之间的流量。

---

## 4. 架构与请求处理流程

### 4.1 Sidecar 模式架构

```text
                         Kubernetes API
                               │
                               ▼
                         ┌───────────┐
                         │  istiod   │
                         │ 控制平面   │
                         └─────┬─────┘
                              │ xDS / 证书
                 ┌────────────┴────────────┐
                 ▼                         ▼
        ┌────────────────┐        ┌────────────────┐
        │ Pod A          │        │ Pod B          │
        │ 应用 A → Envoy ├───────►│ Envoy → 应用 B │
        └────────────────┘        └────────────────┘
```

### 4.2 一次请求经过哪些步骤

以 `productpage` 调用 `reviews` 为例：

1. **做什么**：应用向 Kubernetes Service `reviews:9080` 发起请求。  
   **为什么**：业务代码仍然使用普通服务发现方式。  
   **预期结果**：Pod 网络规则把出站连接重定向到本 Pod 的 Envoy。

2. **做什么**：源 Envoy 查找 `reviews` 的路由和目标实例。  
   **为什么**：路由、版本权重和负载均衡策略由 Envoy执行。  
   **预期结果**：Envoy选择 `reviews-v1`、`v2` 或 `v3`。

3. **做什么**：源 Envoy使用 Istio 身份证书建立 mTLS 连接。  
   **为什么**：加密链路并证明调用方身份。  
   **预期结果**：目标代理可识别来源 ServiceAccount。

4. **做什么**：目标 Envoy验证认证和授权策略。  
   **为什么**：阻止未授权服务访问目标工作负载。  
   **预期结果**：允许的请求转发给 `reviews`，其他请求返回 `403`。

5. **做什么**：双方代理生成指标、访问日志和追踪信息。  
   **为什么**：观察调用成功率、延迟和依赖关系。  
   **预期结果**：Prometheus、日志系统和追踪后端可采集数据。

`istiod` 不在这条业务请求链路中。

---

## 5. 适用场景、优缺点与不适用情况

### 5.1 适用场景

Istio 特别适合：

- 服务数量多、调用关系复杂的 Kubernetes 微服务。
- 需要按版本、用户、请求头进行精细路由。
- 需要统一实现灰度、金丝雀发布。
- 需要服务间加密和基于工作负载身份的零信任访问。
- 需要统一采集成功率、延迟和流量拓扑。
- 多团队共享 Kubernetes 平台，需要平台层通信规范。
- 需要多集群服务网格，但应额外评估相应功能成熟度。

### 5.2 优点

- 对业务代码侵入较小。
- 流量、安全和遥测策略集中管理。
- 支持渐进式启用，不要求一次性改造所有服务。
- 路由、mTLS、授权等核心能力成熟。
- 与 Kubernetes Gateway API、Prometheus、OpenTelemetry、Kiali 等生态集成。

### 5.3 缺点

- Sidecar 消耗额外 CPU、内存并增加请求延迟。
- 配置对象多，错误策略可能造成大范围流量故障。
- 请求会多经过代理，排障链路更长。
- 生产环境需要容量规划、升级策略和可观测性建设。
- L7 指标可能产生高基数标签和较大存储开销。

### 5.4 不适用或应谨慎使用的情况

- 只有少量服务，通信关系简单。
- 团队尚不能稳定运维 Kubernetes。
- 应用以 UDP、ICMP 为主；Istio主要代理 TCP 流量。
- 对极低延迟极其敏感，无法接受额外代理开销。
- 仅需要简单入口反向代理，普通 Gateway Controller 已足够。
- 希望用 Service Mesh 替代应用级幂等、事务或业务鉴权。
- 计划依赖仍为 Alpha/Experimental 的功能投入关键生产链路。

---

## 6. 版本、环境和前置条件

### 6.1 当前版本

截至 2026-07-24：

- 最新稳定补丁版：`1.30.3`。
- Istio `1.30.x` 官方支持 Kubernetes：
  - `1.32`
  - `1.33`
  - `1.34`
  - `1.35`
  - `1.36`
- `1.30.x` 预计支持至 2026 年 11 月左右。
- 官方建议在同一小版本中尽快采用最新补丁版。

不要因为旧 Kubernetes 版本“测试时似乎能运行”就视为受支持。生产环境应使用官方 Supported 列中的版本。

### 6.2 客户端工具

需要：

```text
kubectl
curl
一个可访问的 Kubernetes 集群
集群管理员或等价安装权限
```

检查环境：

```bash
kubectl version
kubectl cluster-info
kubectl get nodes
kubectl auth can-i create customresourcedefinitions.apiextensions.k8s.io
```

### 6.3 应用要求

- Istio主要拦截 TCP，不代理 UDP 和 ICMP。
- Service 端口建议使用 `appProtocol` 或规范端口名明确协议。
- 同一个 Pod 端口不能在不同 Service 中被声明为冲突协议。
- Sidecar 默认使用 `istio-init` 配置网络，需要 `NET_ADMIN` 和 `NET_RAW`；使用 Istio CNI 后可避免每个业务 Pod 使用特权初始化容器。
- 不要让应用进程使用 Istio 保留的 UID `1337`。
- 网络策略、防火墙和安全组必须允许 Istio 控制面、Webhook、健康检查和数据面所需端口。

协议明确的 Service 示例：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: example-api
spec:
  selector:
    app: example-api
  ports:
    - name: http-api
      appProtocol: http
      port: 8080
      targetPort: 8080
```

---

## 7. 在 Kubernetes 中安装 Istio 1.30.3

本教程使用 Sidecar 模式和 `demo` 配置，但不预装传统 Gateway Deployment，后续使用 Kubernetes Gateway API 自动创建入口网关。

> `demo` 适合学习和功能验证，不是默认生产建议。生产环境应从 `default` profile 开始定制。

### 7.1 下载固定版本

**做什么**：下载 Istio 1.30.3，并把 `istioctl` 加入当前终端的 `PATH`。  
**为什么**：固定版本可避免脚本将来下载到不同版本。  
**预期结果**：`istioctl version --remote=false` 显示 `1.30.3`。

macOS/Linux：

```bash
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.30.3 sh -

cd istio-1.30.3
export PATH="$PWD/bin:$PATH"

istioctl version --remote=false
```

Apple Silicon 或 ARM64 Linux 可明确指定架构：

```bash
curl -L https://istio.io/downloadIstio | \
  ISTIO_VERSION=1.30.3 TARGET_ARCH=arm64 sh -
```

### 7.2 安装 Sidecar 演示环境

**做什么**：安装控制平面，不预装传统 Ingress/Egress Gateway。  
**为什么**：后文采用 Kubernetes Gateway API，Gateway 资源会自动创建代理 Deployment 和 Service。  
**预期结果**：`istiod` 进入 `Running` 状态。

```bash
istioctl install \
  -f samples/bookinfo/demo-profile-no-gateways.yaml \
  -y
```

检查安装：

```bash
kubectl get pods -n istio-system
istioctl verify-install
```

预期至少看到：

```text
istiod-...   1/1   Running
```

生产环境的基础命令是：

```bash
istioctl install --set profile=default
```

如需在生产环境启用 Istio CNI，应根据平台和 Pod Security 约束单独规划，不能直接照搬演示 profile。

### 7.3 安装 Kubernetes Gateway API CRD

**做什么**：安装 Gateway API `v1.5.1` 标准通道 CRD。  
**为什么**：大部分 Kubernetes 集群不会预装这些 CRD。  
**预期结果**：能够查询 `Gateway` 和 `HTTPRoute` 资源。

```bash
kubectl get crd gateways.gateway.networking.k8s.io >/dev/null 2>&1 || \
  kubectl kustomize \
  "github.com/kubernetes-sigs/gateway-api/config/crd?ref=v1.5.1" |
  kubectl apply -f -
```

验证：

```bash
kubectl get crd \
  gateways.gateway.networking.k8s.io \
  httproutes.gateway.networking.k8s.io
```

当前状态需要明确：

- Gateway API 用于 Istio Ingress：**Stable**。
- Gateway API 用于 Mesh 流量：**Stable**。
- Istio仍支持自己的 `Gateway`、`VirtualService` API。
- Gateway API 尚未覆盖 Istio 原生 API 的全部功能。
- Istio官方计划未来将 Kubernetes Gateway API 作为默认流量管理 API。
- 不要为了普通 HTTP Gateway 安装 `experimental` CRD 包。

---

## 8. 部署完整 Bookinfo 示例应用

Bookinfo 包含以下服务：

```text
productpage
├── details
└── reviews
    └── ratings
```

`reviews` 同时部署三个版本：

- `reviews-v1`：无星级。
- `reviews-v2`：黑色星级。
- `reviews-v3`：红色星级。

### 8.1 启用 Sidecar 自动注入

**做什么**：为 `default` namespace 添加注入标签。  
**为什么**：注入 Webhook 会在新建 Pod 时自动添加 Envoy 容器。  
**预期结果**：后续创建的 Pod 包含应用容器和 `istio-proxy`。

```bash
kubectl label namespace default istio-injection=enabled
```

检查标签：

```bash
kubectl get namespace default --show-labels
```

该操作不会修改已经运行的 Pod。已有 Deployment 需要滚动重启：

```bash
kubectl rollout restart deployment -n default
```

也可以仅为单个 Pod 显式控制注入：

```yaml
metadata:
  annotations:
    sidecar.istio.io/inject: "true"
```

### 8.2 部署应用

**做什么**：应用发布包中的官方 Bookinfo 清单。  
**为什么**：该清单包含 ServiceAccount、Service 和全部 Deployment。  
**预期结果**：所有 Pod 为 `2/2 Running`。

```bash
kubectl apply \
  -f samples/bookinfo/platform/kube/bookinfo.yaml
```

等待就绪：

```bash
kubectl wait \
  --for=condition=available \
  --timeout=180s \
  deployment --all \
  -n default

kubectl get pods -n default
kubectl get services -n default
```

验证 Sidecar：

```bash
kubectl get pod \
  -l app=productpage \
  -o jsonpath='{.items[0].spec.containers[*].name}'

echo
```

预期包含：

```text
productpage istio-proxy
```

### 8.3 从集群内部验证

```bash
kubectl exec \
  "$(kubectl get pod -l app=ratings \
      -o jsonpath='{.items[0].metadata.name}')" \
  -c ratings -- \
  curl -sS productpage:9080/productpage |
  grep -o '<title>.*</title>'
```

预期：

```text
<title>Simple Bookstore App</title>
```

---

## 9. 配置 Ingress Gateway

### 9.1 创建 Gateway 和 HTTPRoute

**做什么**：创建 Kubernetes Gateway API 入口和 Bookinfo 路由。  
**为什么**：应用目前只有 ClusterIP，集群外无法直接访问。  
**预期结果**：Istio自动创建入口代理 Deployment 和 Service。

```bash
kubectl apply -f - <<'EOF'
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: bookinfo-gateway
  namespace: default
  annotations:
    networking.istio.io/service-type: ClusterIP
spec:
  gatewayClassName: istio
  listeners:
    - name: http
      protocol: HTTP
      port: 80
      allowedRoutes:
        namespaces:
          from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: bookinfo
  namespace: default
spec:
  parentRefs:
    - name: bookinfo-gateway
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /productpage
        - path:
            type: PathPrefix
            value: /static
        - path:
            type: PathPrefix
            value: /login
        - path:
            type: PathPrefix
            value: /logout
        - path:
            type: PathPrefix
            value: /api/v1/products
      backendRefs:
        - name: productpage
          port: 9080
EOF
```

等待 Gateway 编程完成：

```bash
kubectl wait \
  --for=condition=programmed \
  --timeout=180s \
  gateway/bookinfo-gateway

kubectl get gateway
kubectl get deployment,service \
  -l gateway.networking.k8s.io/gateway-name=bookinfo-gateway
```

### 9.2 本地访问

```bash
kubectl port-forward \
  service/bookinfo-gateway-istio \
  8080:80
```

浏览器访问：

```text
http://localhost:8080/productpage
```

生产环境通常使用 `LoadBalancer` Service、云负载均衡器和 HTTPS 证书，不应依赖 `port-forward`。

### 9.3 Gateway API 与 Istio Gateway 的区别

- Kubernetes `Gateway` 默认可以同时创建和配置 Gateway Deployment/Service。
- Istio原生 `Gateway` 通常只配置一个已经部署的网关工作负载，并配合 `VirtualService` 路由。
- 两套 API 当前都受支持。
- 新建通用入口优先评估 Gateway API；依赖 Istio特有高级能力时可使用 Istio API。

---

## 10. 流量治理：路由、灰度和流量拆分

Bookinfo 已经部署三个 `reviews` 版本。首先为每个版本定义子集。

### 10.1 定义版本子集

**做什么**：创建 `DestinationRule`。  
**为什么**：`VirtualService` 中的 `subset` 必须对应这里定义的 Pod 标签。  
**预期结果**：`v1`、`v2`、`v3` 分别匹配三个 Deployment。

```bash
kubectl apply -f - <<'EOF'
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: reviews
  namespace: default
spec:
  host: reviews
  subsets:
    - name: v1
      labels:
        version: v1
    - name: v2
      labels:
        version: v2
    - name: v3
      labels:
        version: v3
EOF
```

### 10.2 将所有流量路由到 v1

```bash
kubectl apply -f - <<'EOF'
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: reviews
  namespace: default
spec:
  hosts:
    - reviews
  http:
    - route:
        - destination:
            host: reviews
            subset: v1
            port:
              number: 9080
EOF
```

刷新页面，评论区域应稳定显示无星级的 `v1`。

### 10.3 按用户路由

下面把登录用户 `jason` 的请求送到 `v2`，其他请求继续使用 `v1`：

```bash
kubectl apply -f - <<'EOF'
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: reviews
  namespace: default
spec:
  hosts:
    - reviews
  http:
    - match:
        - headers:
            end-user:
              exact: jason
      route:
        - destination:
            host: reviews
            subset: v2
            port:
              number: 9080
    - route:
        - destination:
            host: reviews
            subset: v1
            port:
              number: 9080
EOF
```

### 10.4 90%/10% 灰度发布

**做什么**：将 10% 流量切到 `v3`。  
**为什么**：在小范围真实流量下观察新版本错误率和延迟。  
**预期结果**：多次刷新时，约 10% 请求显示红色星级。

```bash
kubectl apply -f - <<'EOF'
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: reviews
  namespace: default
spec:
  hosts:
    - reviews
  http:
    - route:
        - destination:
            host: reviews
            subset: v1
            port:
              number: 9080
          weight: 90
        - destination:
            host: reviews
            subset: v3
            port:
              number: 9080
          weight: 10
EOF
```

检查配置：

```bash
istioctl analyze
kubectl get virtualservice reviews -o yaml
kubectl get destinationrule reviews -o yaml
```

权重表示大量请求下的统计比例，不保证每 10 个请求恰好有 1 个进入 `v3`。

生产灰度通常按以下顺序推进：

```text
1% → 5% → 10% → 25% → 50% → 100%
```

每一步应设置错误率、P95/P99 延迟和业务指标的自动回滚阈值。

---

## 11. mTLS、认证与授权

### 11.1 自动 mTLS 与 STRICT 的区别

Istio通常会自动为网格代理之间的通信启用 mTLS，但工作负载在默认 `PERMISSIVE` 模式下仍可能接受明文请求。

`STRICT` 表示目标工作负载只接受 mTLS 网格流量。

### 11.2 启用命名空间严格 mTLS

确认 `default` namespace 内需要通信的 Pod 都已加入网格后执行：

```bash
kubectl apply -f - <<'EOF'
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata:
  name: default
  namespace: default
spec:
  mtls:
    mode: STRICT
EOF
```

验证：

```bash
istioctl analyze
istioctl proxy-config secret \
  "$(kubectl get pod -l app=productpage \
      -o jsonpath='{.items[0].metadata.name}')"
```

生产迁移建议：

1. 先盘点未注入 Sidecar 的调用方。
2. 保持 `PERMISSIVE` 并完成工作负载迁移。
3. 通过遥测确认没有明文调用。
4. 再切换为 `STRICT`。

### 11.3 限制只有 productpage 可以调用 reviews

`productpage` 使用的 ServiceAccount 为 `bookinfo-productpage`。下面仅允许该身份访问 `reviews`：

```bash
kubectl apply -f - <<'EOF'
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: reviews-allow-productpage
  namespace: default
spec:
  selector:
    matchLabels:
      app: reviews
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/default/sa/bookinfo-productpage
      to:
        - operation:
            ports:
              - "9080"
EOF
```

一旦某工作负载存在 `ALLOW` 策略，不匹配任何 `ALLOW` 规则的请求会被拒绝。

查看授权状态：

```bash
REVIEWS_POD="$(
  kubectl get pod -l app=reviews,version=v1 \
    -o jsonpath='{.items[0].metadata.name}'
)"

istioctl x authz check "$REVIEWS_POD"
```

### 11.4 JWT 请求认证

`RequestAuthentication` 验证终端用户 JWT。它具有一个容易忽略的行为：

- 带有无效 Token 的请求会被拒绝。
- 完全不带 Token 的请求仍可通过。
- 如要强制登录，必须同时配置 `AuthorizationPolicy`。

以下配置需要替换成组织真实的 OIDC/OAuth 2.0 发行方：

```bash
kubectl apply -f - <<'EOF'
apiVersion: security.istio.io/v1
kind: RequestAuthentication
metadata:
  name: productpage-jwt
  namespace: default
spec:
  selector:
    matchLabels:
      app: productpage
  jwtRules:
    - issuer: https://login.example.com/
      jwksUri: https://login.example.com/.well-known/jwks.json
      audiences:
        - bookinfo
---
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: productpage-require-jwt
  namespace: default
spec:
  selector:
    matchLabels:
      app: productpage
  action: ALLOW
  rules:
    - from:
        - source:
            requestPrincipals:
              - "*"
EOF
```

使用示例：

```bash
export TOKEN='替换为真实JWT'

curl \
  -H "Authorization: Bearer ${TOKEN}" \
  http://localhost:8080/productpage
```

生产注意事项：

- `issuer` 必须与 Token 中 `iss` 完全一致。
- 校验 `aud`，避免其他系统签发的 Token 被误用。
- mTLS 解决工作负载身份，JWT 解决终端用户身份，两者不是替代关系。
- 授权策略发布前应通过测试 namespace 验证，避免误配置导致全流量拒绝。

---

## 12. 指标、日志、链路追踪和 Kiali

### 12.1 当前官方状态

Istio安装后会让代理产生遥测数据，但默认不会部署完整的生产遥测后端。

官方 `samples/addons` 中的：

- Prometheus
- Grafana
- Jaeger
- Kiali

都属于快速体验配置，不针对生产性能、安全、持久化和高可用进行调优。

生产环境应使用：

- 托管或独立部署的 Prometheus。
- 正式部署的 Grafana。
- Jaeger、Tempo 或兼容 OpenTelemetry 的追踪后端。
- 按 Kiali 官方安装文档定制的 Kiali。
- 集中日志系统，如 Loki、OpenSearch 或云日志服务。

### 12.2 安装演示插件

**做什么**：部署官方示例可观测性组件。  
**为什么**：快速观察 Bookinfo 的指标、拓扑和 Trace。  
**预期结果**：相关 Deployment 在 `istio-system` 中可用。

```bash
kubectl apply -f samples/addons/prometheus.yaml
kubectl apply -f samples/addons/grafana.yaml
kubectl apply -f samples/addons/jaeger.yaml
kubectl apply -f samples/addons/kiali.yaml

kubectl rollout status deployment/prometheus \
  -n istio-system --timeout=180s

kubectl rollout status deployment/kiali \
  -n istio-system --timeout=180s
```

### 12.3 生成测试流量

```bash
for i in $(seq 1 100); do
  curl -sS \
    http://localhost:8080/productpage \
    >/dev/null
done
```

### 12.4 指标

Istio常用指标包括：

```text
istio_requests_total
istio_request_duration_milliseconds
istio_request_bytes
istio_response_bytes
istio_tcp_connections_opened_total
```

打开 Prometheus：

```bash
istioctl dashboard prometheus
```

示例查询：

```promql
sum(
  rate(
    istio_requests_total{
      destination_service_name="reviews"
    }[5m]
  )
) by (response_code)
```

生产环境应控制标签基数，并通过 recording rules、合理保留时间和分层联邦降低成本。

### 12.5 访问日志

通过 Telemetry API 为网格启用 Envoy 访问日志：

```bash
kubectl apply -f - <<'EOF'
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: mesh-access-logging
  namespace: istio-system
spec:
  accessLogging:
    - providers:
        - name: envoy
EOF
```

查看 `productpage` Sidecar 日志：

```bash
PRODUCTPAGE_POD="$(
  kubectl get pod -l app=productpage \
    -o jsonpath='{.items[0].metadata.name}'
)"

kubectl logs \
  "$PRODUCTPAGE_POD" \
  -c istio-proxy \
  --since=10m
```

高流量生产环境不要无条件永久记录全部成功请求。可按错误状态、采样策略或业务要求过滤，并配置日志轮转和脱敏。

### 12.6 链路追踪

分布式链路追踪把一次跨多个服务的请求表示为多个 Span。

仅代理无法自动修复应用内的上下文传播。应用必须把这些请求头传递给下游调用，例如：

```text
traceparent
tracestate
b3
x-b3-traceid
x-b3-spanid
x-b3-sampled
x-request-id
```

配置 Jaeger OpenTelemetry Provider：

```bash
cat > /tmp/istio-tracing.yaml <<'EOF'
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
spec:
  meshConfig:
    enableTracing: true
    defaultConfig:
      tracing: {}
    extensionProviders:
      - name: jaeger
        opentelemetry:
          service: jaeger-collector.istio-system.svc.cluster.local
          port: 4317
EOF

istioctl install \
  -f /tmp/istio-tracing.yaml \
  -y
```

启用追踪并为教程设置 100% 采样：

```bash
kubectl apply -f - <<'EOF'
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: mesh-tracing
  namespace: istio-system
spec:
  tracing:
    - providers:
        - name: jaeger
      randomSamplingPercentage: 100.0
EOF
```

打开 Jaeger：

```bash
istioctl dashboard jaeger
```

默认追踪采样率通常为 `1%`。教程使用 `100%` 方便观察，但生产环境应根据流量、成本和合规要求设置较低采样率或尾部采样。

### 12.7 Kiali

Kiali 根据 Istio 配置和 Prometheus 指标展示：

- 服务调用拓扑。
- 流量比例。
- 成功率和延迟。
- 配置校验结果。
- 工作负载和代理状态。

打开 Kiali：

```bash
istioctl dashboard kiali
```

选择：

```text
Graph → Namespace: default
```

Kiali不是指标数据库，也不自行生成追踪数据。它依赖 Prometheus，并可集成 Grafana 和 Jaeger。

---

## 13. Ambient Mesh 与 Sidecar 对比

### 13.1 Ambient Mesh 是什么

Ambient Mesh 不再为每个应用 Pod 注入 Sidecar，而是分为两层：

- `ztunnel`：每个节点一个，处理四层连接、身份和 mTLS。
- `waypoint`：按 namespace 或 Service 部署的 Envoy，按需提供 HTTP/gRPC 七层策略。

```text
Pod A
  │
  ▼
节点 ztunnel
  │ HBONE + mTLS
  ▼
目标节点 ztunnel
  │
  ├── 直接到 Pod B：L4 能力
  │
  └── Waypoint → Pod B：L7 路由、授权和遥测
```

HBONE 是 Ambient 数据平面使用的基于 HTTP/2 CONNECT 的安全隧道协议。

### 13.2 当前官方成熟度

截至 Istio 1.30：

稳定能力：

- 单集群 Ambient 使用。
- `ztunnel` 核心。
- Waypoint 核心。
- Waypoint 的 `HTTPRoute`、`GRPCRoute`。
- Waypoint 的 `DestinationRule`。
- `AuthorizationPolicy`。
- `PeerAuthentication`。

需要谨慎评估的能力：

- Ambient `RequestAuthentication`：Beta。
- 跨 namespace Waypoint：Beta。
- Ambient 多网络多集群：Beta，且存在拓扑限制。
- Waypoint `VirtualService`：Alpha。
- Waypoint `TLSRoute`、`TCPRoute`：Alpha。
- Waypoint `WasmPlugin`：Alpha。
- Ambient IPv6/双栈、DNS 代理：Beta。

因此，不能简单地说“Ambient 全部功能均已稳定”。准确说法是：

> Ambient 的单集群核心数据平面已可用于生产，但具体功能仍需逐项核对 Feature Status。

### 13.3 对比

| 维度 | Sidecar | Ambient |
|---|---|---|
| 代理位置 | 每个 Pod 一个 Envoy | 每节点 `ztunnel`，按需 Waypoint |
| 应用 Pod 修改 | 需要注入和重建 | 通过 namespace/workload 标签加入 |
| L4 mTLS | 支持 | 默认由 `ztunnel` 提供 |
| L7 流量治理 | 完整 | 需要 Waypoint |
| 资源成本 | 随 Pod 数增长 | 通常更低、共享代理 |
| Job/CronJob | Sidecar 生命周期需处理 | 更自然 |
| VM 支持 | 支持 | 当前以 Kubernetes 为主 |
| 多集群 | Sidecar 更成熟 | 当前仍有限制 |
| 功能覆盖 | 最完整 | 部分能力仍为 Alpha/Beta |

### 13.4 如何选择

选择 Sidecar，如果：

- 需要最完整、最成熟的 Istio 功能。
- 使用多集群或虚拟机工作负载。
- 已有成熟 Sidecar 运维体系。
- 依赖 Ambient 中仍处于 Alpha/Beta 的功能。

选择 Ambient，如果：

- 主要是单 Kubernetes 集群。
- 首要目标是 mTLS 和 L4 身份安全。
- 希望减少每个 Pod 的资源和生命周期影响。
- 可以只为需要 L7 功能的服务添加 Waypoint。
- 已验证所需功能在 Ambient 中达到合适成熟度。

不要在同一工作负载上同时保留 Sidecar 注入标签和 Ambient 加入标签。

---

## 14. 生产配置与最佳实践

### 14.1 安装方式

- `istioctl` 控制平面安装能力为 Stable，带配置校验，适合安装和升级。
- Helm 是官方安装路径，适合 GitOps 和 Helm 生命周期管理；Istio Feature Status 当前仍将 Helm Installation 标为 Beta。
- `demo` profile 仅用于教程和测试。
- 生产环境从 `default` profile 开始，按容量和安全需求定制。
- 安装器、Chart 和控制平面版本必须保持一致。

### 14.2 高可用和容量

生产环境至少规划：

- 多副本 `istiod`，跨可用区分散。
- PodDisruptionBudget。
- 合理的 CPU、内存 request/limit。
- Gateway 独立伸缩。
- HorizontalPodAutoscaler。
- 控制平面和数据平面的容量压测。
- 证书和 CA 根信任管理。
- Prometheus 标签基数与存储容量。

### 14.3 配置作用域

减少无关配置下发：

- 使用 namespace 隔离团队资源。
- 谨慎使用导出到全网格的配置。
- 大型网格可评估 `Sidecar` 资源或 `discoverySelectors`。
- 避免在根 namespace 创建未经评审的全局策略。

### 14.4 安全

- 从 `PERMISSIVE` 渐进迁移到 `STRICT` mTLS。
- 授权采用最小权限。
- 使用 ServiceAccount 身份，不依赖源 IP 表示服务身份。
- Ingress 使用 HTTPS，证书存入 Kubernetes Secret 或外部证书系统。
- 不公开 Envoy 管理端口和 Istiod 调试端口。
- 保护 Prometheus、Kiali、Grafana 和 Jaeger，不要直接暴露到公网。
- 在生产中安全采集代理指标；默认代理遥测端口并不自动受到 mTLS 保护。
- 对授权策略先测试再发布，关键变更应支持快速回滚。

### 14.5 路由和韧性

- 超时应显式配置，不能无限等待。
- 重试只用于安全或幂等操作。
- 避免多层重试造成重试风暴。
- 灰度发布必须关联错误率、延迟和业务指标。
- 熔断和连接池阈值需通过压测确定。
- 应用仍需实现幂等、取消传播和正确的截止时间。

### 14.6 升级

官方支持控制平面最多比数据平面领先一个版本，但建议使用 revision 升级，避免长期版本偏差。

升级前执行：

```bash
istioctl x precheck
istioctl analyze --all-namespaces
istioctl proxy-status
```

升级原则：

1. 阅读目标版本升级说明和已知问题。
2. 先升级控制平面 revision。
3. 迁移少量 namespace 或工作负载。
4. 观察错误率、延迟和代理同步状态。
5. 分批重启数据平面。
6. 最后移除旧 revision。
7. 不跨多个不受支持的小版本直接升级。

---

## 15. 常见问题与排查

### 15.1 Pod 没有 Sidecar

检查：

```bash
kubectl get namespace default --show-labels

kubectl get pod \
  -l app=productpage \
  -o jsonpath='{.items[0].spec.containers[*].name}'

kubectl get mutatingwebhookconfiguration |
  grep istio
```

常见原因：

- namespace 没有 `istio-injection=enabled`。
- Pod 在添加标签之前已经创建。
- Pod 显式设置 `sidecar.istio.io/inject: "false"`。
- 注入 Webhook 不可达或证书异常。

处理：

```bash
kubectl rollout restart deployment -n default
```

### 15.2 Sidecar 为 `1/2` 或启动失败

```bash
kubectl describe pod <POD_NAME>
kubectl logs <POD_NAME> -c istio-proxy
kubectl logs <POD_NAME> -c istio-init
kubectl get events --sort-by=.lastTimestamp
```

重点检查：

- Pod Security 是否拒绝 `NET_ADMIN`/`NET_RAW`。
- 是否需要安装 Istio CNI。
- 镜像是否可拉取。
- 就绪探针和应用端口是否正确。
- 节点资源是否不足。

### 15.3 配置已经应用但路由没有生效

```bash
istioctl analyze
istioctl proxy-status

POD_NAME="$(
  kubectl get pod -l app=productpage \
    -o jsonpath='{.items[0].metadata.name}'
)"

istioctl proxy-config routes "$POD_NAME"
istioctl proxy-config clusters "$POD_NAME"
istioctl proxy-config endpoints "$POD_NAME"
```

常见原因：

- `VirtualService.host` 与实际 Service 不一致。
- `DestinationRule.subset` 标签没有匹配 Pod。
- 配置位于错误 namespace。
- Sidecar 尚未同步最新配置。
- Service 端口协议识别错误。
- 请求没有经过预期的 Gateway。

### 15.4 返回 503

检查：

```bash
kubectl get endpointslices \
  -l kubernetes.io/service-name=reviews

kubectl get pods \
  -l app=reviews \
  -o wide

istioctl proxy-config endpoints "$POD_NAME"
```

可能原因：

- Service 没有就绪 Endpoint。
- subset 标签写错。
- 目标端口错误。
- mTLS 模式不匹配。
- 上游连接失败或被熔断。

### 15.5 返回 403

```bash
kubectl get authorizationpolicy \
  --all-namespaces

istioctl x authz check "$REVIEWS_POD"

kubectl logs \
  "$REVIEWS_POD" \
  -c istio-proxy \
  --since=10m
```

常见原因：

- `ALLOW` 策略存在，但请求没有匹配任何规则。
- ServiceAccount principal 写错。
- JWT 缺失、过期、`issuer` 或 `audience` 不匹配。
- 在 `PERMISSIVE` 模式下依赖 mTLS 身份进行授权。

### 15.6 Gateway 无地址或未 Programmed

```bash
kubectl describe gateway bookinfo-gateway
kubectl get gatewayclass
kubectl get deployment,service \
  -l gateway.networking.k8s.io/gateway-name=bookinfo-gateway
kubectl get events --sort-by=.lastTimestamp
```

本地集群没有云 LoadBalancer 时：

- 使用 `ClusterIP` 加 `kubectl port-forward`。
- Minikube 可使用 `minikube tunnel`。
- kind 可使用端口映射或本地 LoadBalancer 方案。

### 15.7 没有指标或 Trace

检查：

```bash
kubectl get pods -n istio-system
kubectl get telemetry --all-namespaces
kubectl get service -n istio-system
kubectl logs deployment/prometheus -n istio-system
```

Trace 缺失通常因为：

- 没有发送足够请求。
- 采样率太低。
- 应用未传播追踪请求头。
- Extension Provider 地址或端口错误。
- Collector 不可达。

### 15.8 通用诊断命令

```bash
istioctl version
istioctl verify-install
istioctl x precheck
istioctl analyze --all-namespaces
istioctl proxy-status

kubectl get pods -A
kubectl get events -A --sort-by=.lastTimestamp
kubectl get virtualservice,destinationrule,gateway \
  --all-namespaces
kubectl get peerauthentication,requestauthentication,authorizationpolicy \
  --all-namespaces
```

生成代理错误报告：

```bash
istioctl bug-report
```

该命令可能收集大量集群配置和日志。提交给第三方前应检查并删除凭证、内部域名和敏感业务信息。

---

## 16. 卸载

### 16.1 删除教程配置和应用

```bash
kubectl delete \
  httproute/bookinfo \
  gateway/bookinfo-gateway \
  --ignore-not-found

kubectl delete \
  virtualservice/reviews \
  destinationrule/reviews \
  --ignore-not-found

kubectl delete \
  peerauthentication/default \
  authorizationpolicy/reviews-allow-productpage \
  requestauthentication/productpage-jwt \
  authorizationpolicy/productpage-require-jwt \
  --ignore-not-found

kubectl delete \
  telemetry/mesh-access-logging \
  telemetry/mesh-tracing \
  -n istio-system \
  --ignore-not-found

kubectl delete \
  -f samples/bookinfo/platform/kube/bookinfo.yaml \
  --ignore-not-found

kubectl delete \
  -f samples/addons \
  --ignore-not-found
```

### 16.2 卸载 Istio

```bash
istioctl uninstall --purge -y
kubectl delete namespace istio-system
kubectl label namespace default istio-injection-
```

### 16.3 可选：删除 Gateway API CRD

只有确认集群中没有其他 Gateway Controller 或应用使用 Gateway API 时才能删除：

```bash
kubectl kustomize \
  "github.com/kubernetes-sigs/gateway-api/config/crd?ref=v1.5.1" |
  kubectl delete -f -
```

CRD 是集群级共享资源，删除它会同时删除对应自定义资源，生产环境必须谨慎。

---

## 17. 总结与学习路线

Istio的核心价值可以概括为：

```text
把服务间通信从应用代码提升为统一的平台能力
```

最重要的知识点：

1. `istiod` 是控制平面，不直接承载普通业务请求。
2. Sidecar 或 Ambient 数据平面负责实际转发、加密和策略执行。
3. 自动 mTLS 不等于严格拒绝明文，应逐步迁移到 `STRICT`。
4. `RequestAuthentication` 验证 JWT，但强制登录还需要授权策略。
5. Gateway API 已是 Istio稳定能力和长期方向，但尚未覆盖全部 Istio功能。
6. Ambient 单集群核心已可生产使用，具体能力仍须逐项检查成熟度。
7. `samples/addons` 仅适合演示，不是生产遥测方案。
8. 灰度、重试、日志和追踪都必须结合容量与成本设计。

推荐学习顺序：

```text
第 1 阶段：安装 + Bookinfo + Sidecar 注入
第 2 阶段：VirtualService + DestinationRule + Gateway API
第 3 阶段：STRICT mTLS + AuthorizationPolicy
第 4 阶段：Prometheus + Kiali + 链路追踪
第 5 阶段：超时、重试、熔断、故障注入
第 6 阶段：revision 升级、容量规划、生产安全
第 7 阶段：评估 Ambient、Waypoint 和多集群
```

## 18. 官方权威资料

- [Istio 1.30.3 发布说明](https://istio.io/latest/news/releases/1.30.x/announcing-1.30.3/)
- [Istio 支持版本与 Kubernetes 兼容矩阵](https://istio.io/latest/docs/releases/supported-releases/)
- [Istio 功能成熟度](https://istio.io/latest/docs/releases/feature-stages/)
- [下载 Istio](https://istio.io/latest/docs/setup/additional-setup/download-istio-release/)
- [使用 istioctl 安装](https://istio.io/latest/docs/setup/install/istioctl/)
- [安装配置 Profile](https://istio.io/latest/docs/setup/additional-setup/config-profiles/)
- [Istio Getting Started](https://istio.io/latest/docs/setup/getting-started/)
- [应用要求](https://istio.io/latest/docs/ops/deployment/application-requirements/)
- [流量管理概念](https://istio.io/latest/docs/concepts/traffic-management/)
- [Kubernetes Gateway API](https://istio.io/latest/docs/tasks/traffic-management/ingress/gateway-api/)
- [安全概念](https://istio.io/latest/docs/concepts/security/)
- [PeerAuthentication](https://istio.io/latest/docs/reference/config/security/peer_authentication/)
- [RequestAuthentication](https://istio.io/latest/docs/reference/config/security/request_authentication/)
- [AuthorizationPolicy](https://istio.io/latest/docs/reference/config/security/authorization-policy/)
- [Telemetry API](https://istio.io/latest/docs/tasks/observability/telemetry/)
- [可观测性生产实践](https://istio.io/latest/docs/ops/best-practices/observability/)
- [Kiali 集成](https://istio.io/latest/docs/ops/integrations/kiali/)
- [Sidecar 与 Ambient 对比](https://istio.io/latest/docs/overview/dataplane-modes/)
- [Ambient Mesh 文档](https://istio.io/latest/docs/ambient/)
- [生产部署最佳实践](https://istio.io/latest/docs/ops/best-practices/)
