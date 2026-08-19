# Kubernetes Ingress 部署与使用详解

> 适用范围：Kubernetes 集群中的 HTTP、HTTPS 入口管理。  
> 文档状态：按 2026 年 8 月的官方资料整理。  
> 核心结论：Ingress API 仍是稳定 API，但功能已经冻结；新建平台优先评估 Gateway API。社区项目 `kubernetes/ingress-nginx` 已于 2026 年 3 月停止维护，不建议再用于新的生产环境。

## 1. Ingress 是什么

Ingress 是 Kubernetes 中用于描述 HTTP 和 HTTPS 入站流量路由规则的 API 对象。它可以根据域名和 URL 路径，把集群外部请求转发到不同的 Service。

典型流量路径如下：

```text
客户端
  │
  ▼
DNS
  │
  ▼
云负载均衡 / 裸金属负载均衡 / NodePort
  │
  ▼
Ingress Controller
  │  根据 Ingress 规则匹配 Host、Path、TLS
  ▼
Service
  │
  ▼
EndpointSlice
  │
  ▼
Pod
```

Ingress 本身只是一份声明式路由配置，不负责实际转发流量。集群必须安装 Ingress Controller，规则才会生效。

### 1.1 三个容易混淆的概念

| 对象 | 作用 | 示例 |
|---|---|---|
| Ingress | 定义域名、路径、后端 Service、TLS 等规则 | `app.example.com/api -> api-service:8080` |
| IngressClass | 指定由哪一类控制器处理 Ingress | `nginx`、`traefik`、云厂商提供的类 |
| Ingress Controller | 监听 Kubernetes API，并把 Ingress 转换成真实代理或负载均衡配置 | NGINX Ingress Controller、Traefik、云负载均衡控制器 |

### 1.2 Ingress 不负责什么

Ingress 不直接提供以下能力：

- 不会自动安装负载均衡器或反向代理。
- 不会自动创建 DNS 记录，除非另行部署 ExternalDNS 等组件。
- 不会自动签发 TLS 证书，除非另行部署 cert-manager 等组件。
- 不定义任意 TCP、UDP 转发；标准 Ingress API 面向 HTTP 和 HTTPS。
- 不保证所有控制器都支持相同的注解和高级功能。

## 2. 当前技术状态与选型建议

### 2.1 Ingress API 仍然可用，但已冻结

Kubernetes 官方将 Ingress API 标记为稳定 API，但已冻结，不再增加新功能，也没有删除计划。现有系统可以继续使用；需要更强路由、跨命名空间协作、标准化流量策略的新系统，优先考虑 Gateway API。

### 2.2 社区 ingress-nginx 已停止维护

这里必须区分两个名称相近但不是同一项目的产品：

| 名称 | 状态 | 常见标识 |
|---|---|---|
| Kubernetes 社区 `ingress-nginx` | 已于 2026 年 3 月停止维护 | 控制器通常为 `k8s.io/ingress-nginx`；注解常以 `nginx.ingress.kubernetes.io/` 开头 |
| F5/NGINX 的 NGINX Ingress Controller | 仍是独立维护的产品 | 控制器为 `nginx.org/ingress-controller`；注解常以 `nginx.org/` 开头 |

二者的 Helm Chart、镜像、IngressClass、注解和扩展资源均不同，不能把配置直接混用。

社区 `ingress-nginx` 停止维护后：

- 已部署实例不会自动停止工作。
- 不再发布新版本、错误修复和安全补丁。
- 已有生产集群应尽快制定迁移计划。
- 不建议为新生产集群继续安装它。

### 2.3 推荐的选型顺序

新建环境建议按以下顺序评估：

1. 云上集群优先评估云厂商托管的负载均衡或 Gateway 实现。
2. 新建 Kubernetes 平台优先选择支持 Gateway API 的控制器。
3. 确实需要 Ingress API 时，选择仍在维护且满足安全要求的控制器。
4. 已有社区 `ingress-nginx` 环境先做配置盘点，再平滑迁移，不要直接替换镜像或复用注解。

## 3. 部署前检查

### 3.1 基础条件

部署前应具备：

- 一个可用的 Kubernetes 集群。
- `kubectl` 已连接目标集群。
- 安装 Helm 3；如果使用清单部署，可以不安装 Helm。
- 集群节点能够拉取控制器镜像。
- 已决定入口 IP 的提供方式。
- 准备使用 HTTPS 时，已准备证书或 cert-manager。

检查集群：

```bash
kubectl cluster-info
kubectl get nodes -o wide
kubectl version
```

### 3.2 检查集群中已有的入口组件

```bash
kubectl get ingressclass
kubectl get ingress --all-namespaces
kubectl get gatewayclass 2>/dev/null || true
kubectl get gateway --all-namespaces 2>/dev/null || true

kubectl get deployment,daemonset --all-namespaces \
  | grep -Ei 'ingress|gateway|traefik|nginx|kong|haproxy'
```

检测是否仍在使用已停止维护的社区 `ingress-nginx`：

```bash
kubectl get pods --all-namespaces \
  --selector app.kubernetes.io/name=ingress-nginx
```

如果命令返回 Pod，需要继续盘点其版本、Ingress 对象和专有注解，参见本文的迁移章节。

### 3.3 确认入口 IP 如何产生

不同集群的入口方式不同：

| 环境 | 常见方式 |
|---|---|
| 公有云 Kubernetes | 控制器 Service 使用 `LoadBalancer`，云控制器创建外部负载均衡器 |
| 裸金属 Kubernetes | MetalLB、硬件负载均衡器、外部反向代理或 `NodePort` |
| 本地开发集群 | 端口映射、`minikube tunnel`、本地代理或集群提供的专用插件 |
| 私有网络 | 内网 LoadBalancer 或内部入口控制器 |

`Service.type: LoadBalancer` 在没有负载均衡实现的裸金属集群上，通常会一直处于 `EXTERNAL-IP: <pending>`。这不是 Ingress 规则本身的问题。

## 4. 部署一个仍在维护的 Ingress Controller

以下以 F5/NGINX 的开源 NGINX Ingress Controller 为例，目的是演示完整安装流程。它不是已经停止维护的社区 `kubernetes/ingress-nginx`。

> 版本说明：示例固定 Helm Chart `2.6.4`，对应官方文档所示控制器 `5.5.4`。正式部署前应查看发布说明，在测试环境验证后再升级版本。

### 4.1 使用 Helm 安装

```bash
helm upgrade --install nginx-ingress \
  oci://ghcr.io/nginx/charts/nginx-ingress \
  --namespace nginx-ingress \
  --create-namespace \
  --version 2.6.4 \
  --wait \
  --timeout 10m
```

检查控制器：

```bash
kubectl get pods -n nginx-ingress -o wide
kubectl get service -n nginx-ingress
kubectl get ingressclass
kubectl get ingressclass nginx -o yaml
```

正常情况下，IngressClass 的关键字段类似：

```yaml
spec:
  controller: nginx.org/ingress-controller
```

控制器对外 Service 的地址可以这样查看：

```bash
kubectl get service -n nginx-ingress -w
```

如果 `EXTERNAL-IP` 长时间为 `<pending>`，先确认集群是否具备 LoadBalancer 实现。

### 4.2 使用自定义 values.yaml

生产环境建议把安装参数放入版本管理，而不是堆叠大量 `--set`：

```yaml
# values.yaml
controller:
  replicaCount: 2

  service:
    type: LoadBalancer

  resources:
    requests:
      cpu: 100m
      memory: 128Mi
    limits:
      cpu: 1
      memory: 512Mi

  affinity:
    podAntiAffinity:
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 100
          podAffinityTerm:
            topologyKey: kubernetes.io/hostname
            labelSelector:
              matchLabels:
                app.kubernetes.io/name: nginx-ingress
```

部署：

```bash
helm upgrade --install nginx-ingress \
  oci://ghcr.io/nginx/charts/nginx-ingress \
  --namespace nginx-ingress \
  --create-namespace \
  --version 2.6.4 \
  --values values.yaml \
  --wait \
  --timeout 10m
```

上面的亲和性标签和 Chart 参数需要随实际 Chart 版本复核。可先查看默认值：

```bash
helm show values \
  oci://ghcr.io/nginx/charts/nginx-ingress \
  --version 2.6.4
```

### 4.3 关于其他控制器

也可以选择 Traefik、HAProxy、Kong、Contour、Istio、云厂商控制器或其他 Gateway API 实现。选型时至少确认：

- Kubernetes 版本兼容范围。
- 是否同时支持 Ingress API 和 Gateway API。
- 是否持续发布安全补丁。
- `IngressClass.spec.controller` 的实际值。
- TLS、WebSocket、gRPC、重写、限流、认证等功能如何配置。
- 高可用、扩缩容、监控和升级方式。
- 许可证与企业支持是否符合要求。

不要因为不同产品都带有 NGINX、Ingress 或 Gateway 名称，就假设其注解和配置可以互换。

## 5. 部署一个最小示例

下面部署两个简单 Web 服务，并通过不同路径访问。

### 5.1 创建命名空间和后端服务

保存为 `demo-backends.yaml`：

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ingress-demo
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: ingress-demo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: nginx:1.27-alpine
          ports:
            - name: http
              containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
          resources:
            requests:
              cpu: 20m
              memory: 32Mi
            limits:
              cpu: 200m
              memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: web
  namespace: ingress-demo
spec:
  selector:
    app: web
  ports:
    - name: http
      port: 80
      targetPort: http
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: ingress-demo
spec:
  replicas: 2
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
        - name: api
          image: registry.k8s.io/echoserver:1.10
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /
              port: http
            initialDelaySeconds: 3
            periodSeconds: 5
          resources:
            requests:
              cpu: 20m
              memory: 32Mi
            limits:
              cpu: 200m
              memory: 128Mi
---
apiVersion: v1
kind: Service
metadata:
  name: api
  namespace: ingress-demo
spec:
  selector:
    app: api
  ports:
    - name: http
      port: 8080
      targetPort: http
```

应用并检查：

```bash
kubectl apply -f demo-backends.yaml
kubectl rollout status deployment/web -n ingress-demo
kubectl rollout status deployment/api -n ingress-demo
kubectl get pods,service,endpointslice -n ingress-demo
```

Ingress 后端的端口引用的是 Service 的 `spec.ports[].port` 或端口名称，不是直接填写 Pod 的 `containerPort`。

### 5.2 创建 Ingress

保存为 `demo-ingress.yaml`：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: demo
  namespace: ingress-demo
spec:
  ingressClassName: nginx
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  name: http
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: api
                port:
                  name: http
```

应用并检查：

```bash
kubectl apply -f demo-ingress.yaml
kubectl get ingress -n ingress-demo
kubectl describe ingress demo -n ingress-demo
```

如果使用的控制器不是 `nginx`，必须将 `ingressClassName` 改为 `kubectl get ingressclass` 显示的实际名称。

### 5.3 在 DNS 生效前测试

先获取控制器入口地址：

```bash
kubectl get service -n nginx-ingress
```

假设入口 IP 是 `203.0.113.10`，可以用以下方式测试 Host 路由：

```bash
curl -v -H 'Host: app.example.com' http://203.0.113.10/
curl -v -H 'Host: app.example.com' http://203.0.113.10/api
```

也可以使用 `--resolve`：

```bash
curl -v \
  --resolve app.example.com:80:203.0.113.10 \
  http://app.example.com/
```

确认无误后，再把 `app.example.com` 的 DNS A/AAAA 或 CNAME 记录指向入口地址。

## 6. Ingress 规则详解

### 6.1 按域名路由

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: host-routing
  namespace: ingress-demo
spec:
  ingressClassName: nginx
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: shop
                port:
                  number: 80
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: api
                port:
                  number: 8080
```

请求必须携带匹配的 HTTP `Host`，HTTPS 请求还会使用 SNI 选择证书和虚拟主机。

### 6.2 按路径路由

```yaml
spec:
  ingressClassName: nginx
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: api
                port:
                  number: 8080
          - path: /static
            pathType: Prefix
            backend:
              service:
                name: static
                port:
                  number: 80
          - path: /
            pathType: Prefix
            backend:
              service:
                name: frontend
                port:
                  number: 80
```

同一个 Host 下多个路径同时匹配时，通常由最长匹配路径优先。具体冲突行为仍应通过所选控制器的文档和测试确认。

### 6.3 pathType

`networking.k8s.io/v1` 要求每条路径明确指定 `pathType`。

| pathType | 含义 | 示例 |
|---|---|---|
| `Exact` | URL 路径精确匹配，区分大小写 | `/foo` 匹配 `/foo`，不匹配 `/foo/` |
| `Prefix` | 按 `/` 分隔的路径元素做前缀匹配 | `/foo` 匹配 `/foo`、`/foo/`、`/foo/bar`，不匹配 `/foobar` |
| `ImplementationSpecific` | 匹配方式由控制器决定 | 可能支持正则等控制器特性 |

生产配置优先使用 `Exact` 或 `Prefix`。只有明确理解控制器实现并接受可移植性下降时，才使用 `ImplementationSpecific`。

### 6.4 默认后端

Ingress 可以定义 `defaultBackend`，处理未命中任何规则的请求：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: default-backend
  namespace: ingress-demo
spec:
  ingressClassName: nginx
  defaultBackend:
    service:
      name: fallback
      port:
        number: 80
```

需要区分：

- Ingress 对象内的 `defaultBackend`。
- 控制器自身配置的全局默认后端。

没有规则命中时，最终使用哪个后端与控制器实现和配置有关。

### 6.5 通配符域名

```yaml
spec:
  ingressClassName: nginx
  rules:
    - host: '*.example.com'
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: wildcard-app
                port:
                  number: 80
```

标准通配符只覆盖单个 DNS 标签。例如 `*.example.com` 可匹配 `foo.example.com`，不匹配 `bar.foo.example.com`。证书也必须覆盖相应通配符域名。

### 6.6 不指定 host

不写 `host` 时，规则可能匹配发送到入口地址的所有 Host：

```yaml
spec:
  ingressClassName: nginx
  rules:
    - http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 80
```

生产环境通常应明确域名，避免意外接收不属于该应用的请求。

## 7. IngressClass 详解

### 7.1 显式指定控制器

推荐每个 Ingress 都写：

```yaml
spec:
  ingressClassName: nginx
```

旧写法：

```yaml
metadata:
  annotations:
    kubernetes.io/ingress.class: nginx
```

旧注解已由 `spec.ingressClassName` 取代。仅在老旧控制器明确要求时保留旧注解。

### 7.2 IngressClass 对象

```yaml
apiVersion: networking.k8s.io/v1
kind: IngressClass
metadata:
  name: nginx
spec:
  controller: nginx.org/ingress-controller
```

`metadata.name` 是 Ingress 中填写的类名，`spec.controller` 是控制器身份字符串。

### 7.3 默认 IngressClass

可通过以下注解把某个类标记为默认类：

```yaml
metadata:
  annotations:
    ingressclass.kubernetes.io/is-default-class: 'true'
```

如果 Ingress 没有设置 `ingressClassName`，默认类可能接管它。一个集群不应同时存在多个默认 IngressClass，否则创建或处理无类 Ingress 时可能出现歧义。

检查默认类：

```bash
kubectl get ingressclass \
  -o custom-columns='NAME:.metadata.name,CONTROLLER:.spec.controller,DEFAULT:.metadata.annotations.ingressclass\.kubernetes\.io/is-default-class'
```

### 7.4 公网与内网入口分离

生产集群经常运行两套控制器：

- `public`：对公网暴露。
- `internal`：只分配内网地址。

应用通过不同的 `ingressClassName` 选择入口。应同时使用 RBAC、准入策略或策略引擎，限制哪些命名空间可以使用公网类。

## 8. 配置 HTTPS

### 8.1 手动创建 TLS Secret

准备证书和私钥：

```bash
kubectl create secret tls app-example-com-tls \
  --namespace ingress-demo \
  --cert=fullchain.pem \
  --key=privkey.pem
```

检查 Secret 类型：

```bash
kubectl get secret app-example-com-tls \
  -n ingress-demo \
  -o jsonpath='{.type}{"\n"}'
```

预期输出：

```text
kubernetes.io/tls
```

TLS Secret 通常必须与 Ingress 位于同一个命名空间。

### 8.2 在 Ingress 中引用证书

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-tls
  namespace: ingress-demo
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - app.example.com
      secretName: app-example-com-tls
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  name: http
```

这里通常表示 TLS 在 Ingress Controller 终止，然后控制器以 HTTP 访问后端。若要求控制器到后端也使用 TLS，需要按控制器文档配置后端协议、证书校验和信任链。

### 8.3 使用 cert-manager 自动签发证书

前提：集群已安装 cert-manager，并存在可用的 `ClusterIssuer`，例如 `letsencrypt-prod`。

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web-tls
  namespace: ingress-demo
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - app.example.com
      secretName: app-example-com-tls
  rules:
    - host: app.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 80
```

cert-manager 的 ingress-shim 会根据注解和 `spec.tls` 创建或维护 Certificate。

检查签发状态：

```bash
kubectl get certificate,certificaterequest,order,challenge \
  -n ingress-demo

kubectl describe certificate app-example-com-tls \
  -n ingress-demo
```

常见签发失败原因：

- DNS 尚未指向入口地址。
- 80 端口被防火墙拦截，导致 HTTP-01 校验失败。
- Issuer 名称、类型或账户配置错误。
- IngressClass 与 solver 使用的控制器不一致。
- CAA 记录不允许目标 CA 签发。
- Secret 名称冲突或权限不足。

### 8.4 验证 HTTPS 和 SNI

```bash
curl -vk \
  --resolve app.example.com:443:203.0.113.10 \
  https://app.example.com/
```

查看服务端证书：

```bash
openssl s_client \
  -connect 203.0.113.10:443 \
  -servername app.example.com \
  -showcerts </dev/null
```

不要只使用 `https://IP` 验证多域名入口，因为没有正确 SNI 时可能拿到默认虚拟主机证书。

## 9. 注解与高级功能

标准 Ingress API 只覆盖基础的 Host、Path、Service 和 TLS。下面这些功能通常依赖控制器注解、自定义资源或全局配置：

- HTTP 自动跳转 HTTPS。
- URL 重写和重定向。
- 请求体大小限制。
- 连接、读取和发送超时。
- WebSocket 和长连接。
- gRPC、gRPC-Web。
- 后端 HTTPS 与 mTLS。
- 会话保持。
- 灰度或金丝雀发布。
- 跨域 CORS。
- Basic Auth、OIDC 和外部认证。
- 限流、连接数限制和熔断。
- 来源 IP 白名单。
- WAF 和自定义安全规则。

### 9.1 注解不可跨控制器复制

例如：

```text
nginx.ingress.kubernetes.io/*
```

属于已停止维护的社区 `ingress-nginx` 的常见注解前缀；而 F5/NGINX 控制器通常使用：

```text
nginx.org/*
```

Traefik、Kong、HAProxy 和云厂商控制器也有各自的配置方式。迁移控制器时，应逐条建立能力映射并重新测试，不能仅替换 `ingressClassName`。

### 9.2 谨慎使用代码片段类注解

允许用户向代理配置中注入原始配置片段，会扩大权限边界，并可能造成：

- 配置注入。
- 读取非预期 Secret 或内部路径。
- 绕过平台统一的安全策略。
- 单个错误配置导致整个控制器重载失败。

多租户集群应默认禁用 snippet 类能力；确实需要时，通过独立控制器、受限命名空间、准入策略和代码审查控制使用范围。

### 9.3 gRPC 和 gRPC-Web

标准 Ingress API 不提供用于声明后端协议的统一字段。配置 gRPC 时需要确认：

- 控制器是否支持 HTTP/2 到后端。
- TLS 在入口终止还是透传。
- 后端是明文 gRPC、TLS gRPC 还是 gRPC-Web。
- 控制器使用什么注解或自定义资源声明协议。
- 超时是否适合流式 RPC。
- 健康检查是否兼容 gRPC。

`grpc-web` 是浏览器到代理之间的协议适配，和 Argo CD CLI 的 `--grpc-web` 参数不是 Ingress API 字段。代理是否需要额外配置，取决于应用和控制器。

## 10. DNS、负载均衡与客户端真实 IP

### 10.1 DNS 配置

获得入口地址后，为业务域名创建：

- A 记录：指向 IPv4 地址。
- AAAA 记录：指向 IPv6 地址。
- CNAME：指向云负载均衡器域名；根域名是否支持取决于 DNS 服务商。

验证：

```bash
dig +short app.example.com
nslookup app.example.com
```

自动化场景可部署 ExternalDNS，但必须限制它可管理的域名范围和 DNS 权限。

### 10.2 客户端真实 IP

入口前面可能存在多层代理：

```text
客户端 -> CDN/WAF -> 云负载均衡器 -> Ingress Controller -> 应用
```

需要明确：

- 哪一层写入 `X-Forwarded-For` 或 Proxy Protocol。
- Ingress Controller 信任哪些代理地址。
- 应用从哪个请求头读取真实 IP。
- `externalTrafficPolicy` 是否需要设为 `Local`。

错误地信任任意来源的 `X-Forwarded-For` 会让客户端伪造来源 IP，影响审计、限流和访问控制。

### 10.3 裸金属环境

裸金属集群常见方案：

- MetalLB 为 `LoadBalancer` Service 分配地址。
- 外部硬件或软件负载均衡器转发到 NodePort。
- 控制器使用 `hostNetwork` 或固定宿主机端口。
- 在集群外部署反向代理，再转发到集群入口。

这些方案在高可用、源 IP 保留、故障切换和运维复杂度上不同。不要为了让 `EXTERNAL-IP` 不再显示 `<pending>` 就直接暴露节点端口到公网。

## 11. 多个 Ingress 与规则冲突

多个 Ingress 可以由同一个控制器合并处理，但不同控制器对冲突的处理方式并不完全一致。

容易冲突的情况包括：

- 两个 Ingress 使用相同 Host 和相同 Path。
- 不同命名空间声明同一个域名。
- 多个控制器同时监听未指定类的 Ingress。
- 多个 Ingress 为同一域名声明不同 TLS Secret。
- 一个 Ingress 使用精确路径，另一个使用控制器特有正则规则。

治理建议：

- 强制填写 `ingressClassName`。
- 只保留一个默认 IngressClass，或完全不设默认类。
- 通过 GitOps 统一管理域名所有权。
- 使用准入策略限制命名空间可声明的域名后缀。
- 在变更前检查集群中是否已有相同 Host 和 Path。

查找指定域名：

```bash
kubectl get ingress --all-namespaces -o yaml \
  | grep -n -B 5 -A 10 'app.example.com'
```

更可靠的做法是使用 `jq` 或策略工具对结构化数据进行检查，而不是只依赖文本搜索。

## 12. 生产环境建议

### 12.1 高可用

- 控制器至少部署两个副本。
- 副本尽量分布到不同节点或可用区。
- 配置 PodDisruptionBudget，防止维护时全部下线。
- 配置合理的 requests 和 limits。
- 确保负载均衡器健康检查与控制器就绪状态一致。
- 验证节点缩容、控制器滚动升级和单可用区故障。

### 12.2 安全

- 仅开放必需的 80/443，管理接口和指标端点不直接暴露公网。
- 使用受信任证书并自动续期。
- 限制可使用公网 IngressClass 的命名空间。
- 禁止或严格管控配置片段注解。
- 限制跨命名空间引用 Secret 和后端。
- 给控制器使用最小化 RBAC。
- 定期升级控制器、镜像和 Helm Chart。
- 配置 NetworkPolicy，限制控制器到后端的访问范围。
- 日志中避免记录 Authorization、Cookie、令牌和敏感查询参数。
- 对互联网入口配合 WAF、DDoS 防护和速率限制。

### 12.3 发布与变更

- 固定 Chart 和镜像版本，不直接追踪 `latest`。
- 在测试集群验证升级和配置兼容性。
- 用 `helm diff` 或 GitOps diff 审核变更。
- 保存控制器 values、IngressClass 和全局配置。
- 检查废弃注解和 API。
- 准备回滚版本和流量切换方案。
- 变更证书、域名和负载均衡地址时，提前调整 DNS TTL。

### 12.4 容量

容量评估至少考虑：

- 每秒请求数和并发连接数。
- TLS 握手和证书数量。
- 长连接、WebSocket、SSE 和流式 gRPC。
- 请求与响应体大小。
- 访问日志量。
- Ingress 对象数量和配置重载时间。
- 控制器副本间的流量分配。
- 后端故障时重试带来的放大效应。

## 13. 监控与日志

### 13.1 建议监控的指标

- 请求量、状态码、延迟和响应大小。
- 活跃连接、连接建立失败和 TLS 握手失败。
- 4xx、5xx 比例。
- 上游连接失败、重试、超时。
- 控制器 Pod CPU、内存、重启次数。
- 配置重载成功率和耗时。
- 证书剩余有效期。
- 外部负载均衡器健康状态。

### 13.2 基础诊断命令

```bash
kubectl get pods -n nginx-ingress -o wide
kubectl describe pod -n nginx-ingress <CONTROLLER_POD>
kubectl logs -n nginx-ingress <CONTROLLER_POD> --tail=200
kubectl logs -n nginx-ingress <CONTROLLER_POD> --previous --tail=200
kubectl top pod -n nginx-ingress
```

实际标签、容器名和日志格式取决于所选控制器。

### 13.3 日志关联

建议让上游代理和应用统一传递请求 ID，例如：

```text
X-Request-ID
traceparent
```

排查一次失败请求时，可以从入口访问日志关联到应用日志和分布式追踪。请求 ID 应由可信入口生成或验证，不能盲目信任客户端提供的值。

## 14. 故障排查

建议沿实际流量方向逐层检查，不要一开始就修改注解。

### 14.1 第一步：检查 DNS

```bash
dig +short app.example.com
```

确认解析结果是否为当前入口 IP 或负载均衡器域名。

### 14.2 第二步：检查入口 Service

```bash
kubectl get service -n nginx-ingress -o wide
kubectl describe service -n nginx-ingress <CONTROLLER_SERVICE>
```

重点检查：

- `type` 是否符合预期。
- 是否有外部地址。
- 80/443 端口是否存在。
- 云负载均衡器事件是否报错。
- 后端健康检查是否通过。

### 14.3 第三步：检查控制器

```bash
kubectl get pods -n nginx-ingress
kubectl logs -n nginx-ingress <CONTROLLER_POD> --tail=200
kubectl get events -n nginx-ingress --sort-by=.lastTimestamp
```

关注：

- Pod 是否 Ready。
- 是否发生 CrashLoopBackOff 或 OOMKilled。
- 是否拒绝 Ingress 配置。
- 是否缺少 Secret、Service 或权限。
- 配置重载是否失败。

### 14.4 第四步：检查 IngressClass 和 Ingress

```bash
kubectl get ingressclass
kubectl get ingress demo -n ingress-demo -o yaml
kubectl describe ingress demo -n ingress-demo
```

重点检查：

- `spec.ingressClassName` 是否正确。
- 控制器是否监听这个类。
- `status.loadBalancer` 是否有地址。
- Events 是否提示后端、证书或规则错误。
- Host、Path 和 `pathType` 是否符合请求。

### 14.5 第五步：检查 Service 和 EndpointSlice

```bash
kubectl get service web -n ingress-demo -o yaml
kubectl get endpointslice -n ingress-demo \
  -l kubernetes.io/service-name=web
```

如果 EndpointSlice 没有可用地址，检查：

- Service selector 是否匹配 Pod labels。
- Pod 是否 Ready。
- Service 的 `targetPort` 是否存在。
- 应用是否监听正确地址和端口。

从集群内部测试 Service：

```bash
kubectl run curl-test \
  --namespace ingress-demo \
  --image=curlimages/curl \
  --restart=Never \
  --rm -it \
  -- http://web:80/
```

该命令会临时创建测试 Pod，并在退出时删除。受限生产集群应使用预先批准的诊断方式。

### 14.6 第六步：绕过 DNS 测试路由

HTTP：

```bash
curl -v \
  -H 'Host: app.example.com' \
  http://203.0.113.10/
```

HTTPS：

```bash
curl -vk \
  --resolve app.example.com:443:203.0.113.10 \
  https://app.example.com/
```

### 14.7 常见现象与判断

| 现象 | 常见原因 | 检查方向 |
|---|---|---|
| 域名无法解析 | DNS 记录缺失或未传播 | `dig`、DNS 控制台、TTL |
| 连接超时 | 安全组、防火墙、LB、NodePort 或路由不通 | 入口 IP、端口、LB 健康检查 |
| 连接被拒绝 | 入口没有监听对应端口 | 控制器 Service、Pod 监听端口 |
| 默认 404 | Host/Path 未匹配，或请求被错误控制器接收 | 请求 Host、IngressClass、Path |
| 502 | 控制器连接后端失败或协议不匹配 | Service 端口、后端协议、应用日志 |
| 503 | 没有可用后端或上游全部不健康 | EndpointSlice、Pod Ready、selector |
| 504 | 后端响应超时 | 应用性能、代理超时、网络 |
| 413 | 请求体超过限制 | 控制器请求体限制 |
| 证书不匹配 | SNI、TLS Secret、域名或默认证书错误 | `openssl s_client`、Ingress TLS 配置 |
| 重定向循环 | CDN、LB、Ingress 和应用对协议判断不一致 | `X-Forwarded-Proto`、TLS 终止位置 |
| 客户端 IP 错误 | 代理头或 Proxy Protocol 配置不一致 | LB 与控制器真实 IP配置 |

### 14.8 NetworkPolicy

如果集群启用了 NetworkPolicy，控制器必须能够访问应用 Pod 的目标端口。应检查：

- 控制器所在命名空间和 Pod labels。
- 后端命名空间的 ingress 策略。
- DNS egress 是否被放行。
- 控制器是否通过 Pod IP 直接访问后端。

策略应精确允许控制器到目标应用端口，不建议为了排障永久开放全部来源。

## 15. 从社区 ingress-nginx 迁移

### 15.1 迁移原则

迁移不是简单替换 Deployment 或 Helm 仓库。不同控制器的以下内容可能不兼容：

- 注解。
- ConfigMap 参数。
- TCP/UDP 映射。
- 自定义模板。
- snippet 配置。
- TLS 透传。
- 外部认证。
- 灰度、镜像流量和会话保持。
- 指标、日志和告警规则。

### 15.2 盘点现状

检测 Pod：

```bash
kubectl get pods --all-namespaces \
  --selector app.kubernetes.io/name=ingress-nginx
```

列出控制器镜像：

```bash
kubectl get deployment,daemonset --all-namespaces \
  -l app.kubernetes.io/name=ingress-nginx \
  -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .spec.template.spec.containers[*]}{.image}{" "}{end}{"\n"}{end}'
```

列出所有 Ingress 及其类：

```bash
kubectl get ingress --all-namespaces \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,CLASS:.spec.ingressClassName,HOSTS:.spec.rules[*].host'
```

查找专有注解：

```bash
kubectl get ingress --all-namespaces -o yaml \
  | grep -n 'nginx.ingress.kubernetes.io/'
```

还应导出并审查：

- Helm values。
- 控制器 ConfigMap。
- 默认 TLS Secret。
- TCP/UDP ConfigMap。
- Service 注解和云负载均衡配置。
- NetworkPolicy、PodDisruptionBudget、HPA。
- PrometheusRule、Dashboard 和日志解析规则。

导出内容中可能包含敏感信息，存储和共享前必须脱敏。

### 15.3 建立能力映射表

建议为每个应用记录：

| 项目 | 旧实现 | 新实现 | 验证结果 |
|---|---|---|---|
| 域名和路径 | Ingress | Ingress 或 HTTPRoute | 待验证 |
| TLS | Secret/自动签发 | Secret/Certificate | 待验证 |
| URL 重写 | 专有注解 | 新控制器配置或 HTTPRoute filter | 待验证 |
| 超时 | 专有注解 | 新控制器策略 | 待验证 |
| 外部认证 | auth-url 等 | 新控制器插件或策略 | 待验证 |
| 灰度流量 | canary 注解 | 权重路由 | 待验证 |
| 真实 IP | ConfigMap/LB 参数 | 新入口信任链 | 待验证 |

### 15.4 并行部署和切流

安全做法是让新旧控制器并行运行：

1. 安装新控制器，使用新的 IngressClass 或 GatewayClass。
2. 新控制器获得独立入口 IP 或负载均衡器。
3. 为选定应用创建等价的新路由。
4. 用 `curl --resolve` 绕过 DNS 验证。
5. 完成协议、证书、性能、日志和故障测试。
6. 使用低 TTL、加权 DNS、CDN 或上游负载均衡器逐步切流。
7. 观察错误率、延迟、连接和应用日志。
8. 保留明确的回切窗口。
9. 全量稳定后再移除旧路由和旧控制器。

Gateway API 项目提供 `ingress2gateway` 作为转换起点，但生成结果仍需人工审查，尤其是控制器专有注解。

## 16. Gateway API：新建平台的推荐方向

### 16.1 为什么使用 Gateway API

Gateway API 是 Ingress 的后继方案，主要改进包括：

- 将基础设施入口和应用路由分开管理。
- 使用角色更清晰的 `GatewayClass`、`Gateway`、`HTTPRoute` 等对象。
- 支持更标准的流量拆分、请求头修改、重定向等能力。
- 支持跨命名空间授权模型。
- 扩展能力比 Ingress 注解更结构化。

### 16.2 核心对象

| 对象 | 通常由谁管理 | 作用 |
|---|---|---|
| GatewayClass | 平台或控制器管理员 | 声明 Gateway 的实现类型 |
| Gateway | 平台团队 | 定义监听地址、端口、协议和证书 |
| HTTPRoute | 应用团队 | 定义 Host、Path、后端和过滤器 |
| ReferenceGrant | 被引用资源的所有者 | 显式允许跨命名空间引用 |

### 16.3 安装 CRD 不等于安装控制器

安装标准 Gateway API CRD：

```bash
kubectl apply --server-side \
  -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml
```

这只会安装 API 定义。还必须安装一个支持 Gateway API 的控制器，并由它提供 `GatewayClass`。

检查：

```bash
kubectl get crd | grep gateway.networking.k8s.io
kubectl get gatewayclass
```

版本应根据所选控制器的兼容矩阵固定，不要盲目使用未经验证的新版本。

### 16.4 Gateway 与 HTTPRoute 示例

下面的 `gatewayClassName` 只是占位示例，必须替换为实际控制器提供的名称。

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-web
  namespace: ingress-demo
spec:
  gatewayClassName: example-gateway-class
  listeners:
    - name: http
      protocol: HTTP
      port: 80
      hostname: app.example.com
      allowedRoutes:
        namespaces:
          from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: web
  namespace: ingress-demo
spec:
  parentRefs:
    - name: public-web
      sectionName: http
  hostnames:
    - app.example.com
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api
      backendRefs:
        - name: api
          port: 8080
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: web
          port: 80
```

检查状态：

```bash
kubectl get gateway,httproute -n ingress-demo
kubectl describe gateway public-web -n ingress-demo
kubectl describe httproute web -n ingress-demo
```

重点查看 Conditions 中的 `Accepted`、`Programmed`、`ResolvedRefs` 等状态，而不是只看对象是否创建成功。

## 17. GitOps 管理建议

建议把以下内容纳入 Git：

- 控制器 Helm values 和版本。
- IngressClass 或 GatewayClass 相关配置。
- Ingress、Gateway、HTTPRoute。
- cert-manager Issuer 或 ClusterIssuer 的非敏感配置。
- NetworkPolicy、PodDisruptionBudget、HPA。
- 监控规则和仪表盘。
- 域名、入口类型和负责人清单。

不要把 TLS 私钥、DNS API Token、云访问密钥直接提交到 Git。应使用外部密钥管理、密封密钥或组织批准的 Secret 管理方案。

多环境仓库可采用：

```text
platform/
├── base/
│   ├── ingress-controller/
│   ├── certificate/
│   └── policies/
└── overlays/
    ├── dev/
    ├── staging/
    └── production/
```

## 18. 上线检查清单

### 控制器

- [ ] 控制器仍处于维护状态，并有明确的安全更新渠道。
- [ ] Chart 和镜像版本已固定。
- [ ] 至少两个副本，并已验证跨节点或跨可用区调度。
- [ ] 配置 requests、limits 和 PodDisruptionBudget。
- [ ] 入口负载均衡器健康检查正常。
- [ ] 管理端口和指标端点未直接暴露公网。

### 路由

- [ ] 每个 Ingress 显式设置正确的 `ingressClassName`。
- [ ] Host、Path、`pathType` 和 Service 端口正确。
- [ ] 没有重复 Host/Path 冲突。
- [ ] 已从入口 IP 直接验证 Host 路由。
- [ ] WebSocket、gRPC、上传、长请求等特殊流量已测试。

### TLS 与 DNS

- [ ] DNS 指向正确入口地址。
- [ ] TLS Secret 与 Ingress 在正确命名空间。
- [ ] 证书覆盖所有域名，完整证书链正常。
- [ ] 自动续期和到期告警已验证。
- [ ] HTTP 到 HTTPS 的行为符合预期。
- [ ] CDN、负载均衡器和入口之间没有重定向循环。

### 安全与运维

- [ ] 已限制公网 IngressClass 的使用范围。
- [ ] 已禁用或限制高风险配置片段。
- [ ] NetworkPolicy 只允许必要流量。
- [ ] 访问日志已脱敏并设置保留周期。
- [ ] 已配置请求量、延迟、5xx、上游失败和证书告警。
- [ ] 有升级、回滚、DNS 切流和故障演练方案。
- [ ] 若仍使用社区 ingress-nginx，已有明确迁移计划和完成时间。

## 19. 清理演示资源

确认不再需要演示环境后执行：

```bash
kubectl delete namespace ingress-demo
```

如果控制器只是为测试安装，并确认没有其他业务使用：

```bash
helm uninstall nginx-ingress -n nginx-ingress
kubectl delete namespace nginx-ingress
```

删除入口控制器可能中断所有由它承载的业务。执行前必须先检查：

```bash
kubectl get ingress --all-namespaces \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,CLASS:.spec.ingressClassName,HOSTS:.spec.rules[*].host'
```

## 20. 官方参考资料

- [Kubernetes：Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/)
- [Kubernetes：Ingress Controllers](https://kubernetes.io/docs/concepts/services-networking/ingress-controllers/)
- [Kubernetes：Ingress NGINX Retirement](https://kubernetes.io/blog/2025/11/11/ingress-nginx-retirement/)
- [Kubernetes：Ingress NGINX Retirement Statement](https://kubernetes.io/blog/2026/01/29/ingress-nginx-statement/)
- [Gateway API：Getting Started](https://gateway-api.sigs.k8s.io/guides/getting-started/introduction/)
- [Gateway API：Migrating from Ingress](https://gateway-api.sigs.k8s.io/guides/getting-started/migrating-from-ingress/)
- [Gateway API：Welcome ingress-nginx Users](https://gateway-api.sigs.k8s.io/guides/getting-started/migrating-from-ingress-nginx/)
- [cert-manager：Securing Ingress Resources](https://cert-manager.io/docs/usage/ingress/)
- [F5 NGINX Ingress Controller：Helm 安装](https://docs.nginx.com/nginx-ingress-controller/install/helm/open-source/)
- [Traefik：Kubernetes Quick Start](https://doc.traefik.io/traefik/getting-started/quick-start-with-kubernetes/)

