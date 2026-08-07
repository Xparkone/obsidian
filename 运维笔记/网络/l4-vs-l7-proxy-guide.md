# 四层代理与七层代理：原理、区别、场景与实践

> 文档版本：1.0  
> 适用读者：开发工程师、运维工程师、SRE、平台工程师、网络工程师  
> 文档目标：理解四层与七层代理的工作方式，能够为实际业务选择合适方案，并完成基本部署与排障  
> 更新日期：2026-07-30

## 1. 文档概述

四层代理和七层代理都是把客户端流量转发给后端服务的中间组件，但二者理解流量的深度不同：

- **四层代理（L4 Proxy）**主要依据源/目标 IP、端口和传输层协议转发 TCP、UDP 等连接。
- **七层代理（L7 Proxy）**能够理解 HTTP、gRPC、DNS、SMTP 等应用层协议，并依据域名、URL、Header、Cookie、请求方法等内容转发请求。

最简单的选择原则是：

```text
不需要理解业务协议，只需要转发连接或数据报 → 优先考虑四层代理
需要按域名、路径、Header、用户或接口规则处理 → 使用七层代理
需要极高吞吐、保留端到端 TLS、代理数据库或自定义 TCP/UDP → 常用四层
需要 WAF、鉴权、限流、灰度、API 路由、内容缓存 → 必须使用七层
```

四层不等于一定更好，七层也不等于一定更高级。真正的选择取决于协议、功能、性能、安全、可观测性和运维成本。

## 2. 核心术语

### 2.1 OSI 模型

OSI 模型把网络通信抽象为七层：

| 层级 | 名称 | 常见协议或数据 |
| --- | --- | --- |
| 7 | 应用层 | HTTP、DNS、SMTP、FTP、MySQL 协议 |
| 6 | 表示层 | 编码、压缩、加密等概念 |
| 5 | 会话层 | 会话建立与管理等概念 |
| 4 | 传输层 | TCP、UDP、SCTP |
| 3 | 网络层 | IPv4、IPv6、ICMP |
| 2 | 数据链路层 | Ethernet、VLAN、MAC |
| 1 | 物理层 | 光纤、电信号、无线信号 |

互联网实际使用的是 TCP/IP 协议族，和 OSI 七层模型并非完全一一对应。“四层代理”和“七层代理”是工程上的常用分类：

- 四层通常表示代理理解到 TCP/UDP 和端口。
- 七层通常表示代理理解具体应用协议，最常见的是 HTTP。

TLS 在 OSI 中没有一个完全严格的单独位置，因此不能简单地说 TLS 永远属于某一层。判断代理属于四层还是七层，重点应看它是否终止并理解应用协议。

### 2.2 代理

代理是位于客户端与服务端之间、代表一方建立或转发通信的中间组件。

```text
客户端 ──连接──> 代理 ──连接──> 后端服务
```

常见类型：

- **正向代理**：代表客户端访问外部服务，例如企业上网代理。
- **反向代理**：代表后端服务接收客户端请求，例如 Nginx、HAProxy、Envoy。
- **透明代理**：客户端通常不显式配置代理，由网络规则将流量引入代理。

本文重点讨论反向代理和负载均衡。

### 2.3 负载均衡

负载均衡是把流量分配到多个后端实例的能力。代理可以提供负载均衡，但代理与负载均衡不是完全相同的概念：

- 代理强调“代表另一端通信”。
- 负载均衡强调“从多个后端中选择一个”。
- 一个代理可以只转发到单个后端。
- LVS/IPVS 等设备可以在数据包层面负载均衡，并不一定采用传统的双连接全代理模式。

## 3. 四层代理是什么

### 3.1 定义

四层代理工作在传输层附近，主要处理：

- TCP 连接。
- UDP 数据报。
- 源 IP、目标 IP。
- 源端口、目标端口。
- 连接状态、超时和健康检查。

典型判断依据是网络五元组：

```text
源 IP + 源端口 + 目标 IP + 目标端口 + 传输层协议
```

普通四层代理通常不知道 TCP 载荷里是 HTTP、MySQL、Redis 还是某种私有协议。它看到的是连接和字节流。

### 3.2 TCP 四层全代理流程

以 HAProxy TCP 模式或 Nginx Stream 为例：

```text
1. Client 与 L4 Proxy 建立 TCP 连接
2. L4 Proxy 选择一个 Backend
3. L4 Proxy 与 Backend 建立第二条 TCP 连接
4. Proxy 在两条连接之间转发双向字节流
```

结构如下：

```text
        TCP 连接 A                  TCP 连接 B
Client ───────────> L4 Proxy ─────────────────> Backend
```

这类四层代理仍然可能维护两条独立 TCP 连接，但它不解析 HTTP 请求。因此不能把“有两条连接”当作七层代理的唯一判断标准。

### 3.3 数据包型四层负载均衡

LVS/IPVS、部分硬件负载均衡器和云负载均衡器可以直接转发或改写数据包：

```text
Client → Load Balancer → Real Server
```

常见模式：

- **NAT**：负载均衡器改写目标地址，返回流量通常也经过负载均衡器。
- **DR（Direct Routing）**：负载均衡器修改二层目标，后端直接向客户端返回。
- **IP Tunnel**：通过隧道把请求封装后发给后端，后端可直接返回。
- **DSR（Direct Server Return）**：请求经过负载均衡器，响应绕过负载均衡器直接返回客户端。

这种模式比全代理更接近数据包转发，通常具有很高吞吐，但高级应用层能力较少。

### 3.4 UDP 四层代理

UDP 没有 TCP 三次握手和可靠连接。代理通常根据五元组和超时维护临时会话：

```text
Client UDP Datagram
        ↓
L4 Proxy 根据五元组选择 Backend
        ↓
Backend UDP Datagram
```

常见场景：

- DNS。
- Syslog。
- NTP。
- RTP/部分实时音视频协议。
- 在线游戏私有 UDP 协议。
- QUIC 的纯 UDP 转发。

普通 UDP 四层代理不会理解 QUIC 内部的 HTTP/3 请求。如果需要按 HTTP/3 域名或路径路由，代理必须具备 QUIC 和 HTTP/3 七层能力。

### 3.5 四层代理能做什么

常见能力：

- TCP/UDP 端口转发。
- 连接级负载均衡。
- 基于 IP 的访问控制。
- 连接数限制。
- TCP Keepalive 和空闲超时。
- TCP、TLS 握手或自定义探测健康检查。
- 源地址保持或通过 PROXY Protocol 传递源地址。
- TLS 透传。
- 基于 TLS ClientHello 中 SNI 的有限路由。

最后一项属于边界能力：代理虽然没有解密 HTTP，但读取了 TLS 握手元数据。它常被产品称为 L4 SNI Routing、TLS Passthrough Routing 或 L4+ 路由，不应误认为完整的七层 HTTP 代理。

## 4. 七层代理是什么

### 4.1 定义

七层代理理解应用层协议。以 HTTP 代理为例，它能够识别：

```http
GET /api/orders/1001 HTTP/1.1
Host: api.example.com
Authorization: Bearer ...
Cookie: user_id=10086
X-Canary: true
```

因此它可以按照以下内容转发或处理请求：

- 域名 `Host`。
- URL Path。
- Query 参数。
- HTTP Method。
- Header。
- Cookie。
- 请求体内容。
- HTTP 状态码和响应 Header。
- gRPC Service、Method 和 Metadata。

### 4.2 HTTP 七层代理流程

HTTPS 场景通常如下：

```text
1. Client 与 L7 Proxy 建立 TCP/TLS 连接
2. Proxy 完成 TLS 解密
3. Proxy 解析 HTTP 请求
4. Proxy 根据 Host、Path、Header 等选择 Backend
5. Proxy 与 Backend 建立或复用另一条连接
6. Proxy 转发请求并解析响应
7. Proxy 将响应返回 Client
```

```text
Client
  │ HTTPS
  ▼
L7 Proxy
  ├─ TLS 终止
  ├─ HTTP 解析
  ├─ 鉴权/限流/WAF
  └─ 路由
       │ HTTP 或 HTTPS
       ▼
    Backend
```

### 4.3 请求级负载均衡

在 HTTP/1.1 Keep-Alive、HTTP/2 或 HTTP/3 中，一个客户端连接可以承载多个请求。七层代理可以按请求选择后端：

```text
同一客户端连接：

GET /api/users   → user-service
GET /api/orders  → order-service
GET /static/a.js → static-service
```

四层代理通常在连接建立时选择后端，该连接内所有数据会发往同一个后端。

### 4.4 七层代理能做什么

- 按域名和路径路由。
- HTTP 重定向和 URL Rewrite。
- Header 增删改。
- Cookie 会话保持。
- JWT、OAuth2 或外部鉴权。
- API 限流和配额。
- WAF 规则。
- 响应压缩。
- 静态内容缓存。
- CORS 处理。
- A/B 测试和灰度发布。
- 请求镜像。
- 超时、重试、熔断。
- 按状态码和方法记录访问日志。
- 分布式追踪 Header 注入与传递。
- gRPC、WebSocket 和 HTTP/3 协议处理。

这些功能依赖代理理解相应的应用层协议。一个只理解 HTTP/1.1 的七层代理，不一定能够正确代理任意其他应用层协议。

## 5. 四层和七层的核心区别

### 5.1 功能对比

| 对比项 | 四层代理 | 七层代理 |
| --- | --- | --- |
| 主要理解内容 | IP、端口、TCP/UDP、连接状态 | HTTP、gRPC、DNS 等应用协议 |
| 典型调度粒度 | 每个连接或 UDP 会话 | 每个请求、流或消息 |
| HTTP Host/Path 路由 | 不支持，SNI 路由除外 | 支持 |
| TLS 透传 | 支持 | 通常需要终止 TLS |
| TLS 终止 | 部分产品支持，但不一定解析 HTTP | 常见能力 |
| Header/Cookie 修改 | 不支持 | 支持 |
| WAF/应用鉴权 | 不支持 | 支持 |
| TCP/UDP 私有协议 | 非常适合 | 需要专用协议插件 |
| 性能开销 | 通常较低 | 通常较高 |
| 日志粒度 | 连接、字节、源/目标地址 | URL、状态码、用户、接口时延 |
| 后端健康检查 | TCP、TLS、简单协议探测 | HTTP 状态、响应内容、gRPC 健康检查 |
| 出错重试 | 通常只能连接级处理 | 可请求级重试，但需谨慎 |
| 典型软件 | LVS、Nginx Stream、HAProxy TCP | Nginx HTTP、HAProxy HTTP、Envoy |

### 5.2 代理所见内容

四层代理看到：

```text
192.0.2.10:51324 → 198.51.100.20:443 TCP
连接已建立
客户端发送 1260 bytes
服务端返回 5380 bytes
```

七层 HTTP 代理看到：

```text
客户端：192.0.2.10
域名：api.example.com
方法：POST
路径：/v1/orders
状态码：201
总时延：83 ms
上游时延：75 ms
User-Agent：...
```

### 5.3 调度粒度

四层：

```text
TCP Connection 1 → Backend A
TCP Connection 2 → Backend B
```

七层：

```text
Request 1 → Backend A
Request 2 → Backend B
```

当客户端长期复用少量连接时，四层连接级负载可能不均衡。例如一个 HTTP/2 连接承载数万个请求，它们通常会落到同一个四层后端。七层代理可以理解 HTTP/2 Stream，并按请求或 Stream 分配。

### 5.4 性能差异

四层通常更快的原因：

- 不需要完整解析应用协议。
- 不需要处理 Header、Cookie 和正文。
- TLS 透传时不承担加解密。
- 可以使用内核 IPVS、eBPF、DPDK 或硬件卸载。
- 数据包型方案可能不复制或重组完整字节流。

七层开销通常来自：

- TCP/TLS 连接终止。
- HTTP/2、HTTP/3 等协议解析。
- Header、正文和压缩处理。
- WAF、鉴权、限流和日志。
- 请求缓冲、重试和内容缓存。

但“七层一定慢很多”并不准确。现代 Nginx、HAProxy、Envoy 的七层代理性能很高。最终差异取决于：

- TLS 算法和握手复用。
- 请求大小和连接复用率。
- 规则复杂度。
- 是否启用 WAF、日志和压缩。
- CPU、网卡、内核和 NUMA。
- 后端响应时间。

应使用真实协议和真实规则压测，而不是只看产品宣传的最大 QPS。

### 5.5 故障域差异

四层代理的故障多表现为：

- 连接拒绝。
- 连接超时。
- TCP Reset。
- 丢包和重传。
- UDP 请求无响应。

七层代理还可能产生：

- `400 Bad Request`。
- `401 Unauthorized`。
- `403 Forbidden`。
- `404 Not Found`。
- `413 Payload Too Large`。
- `429 Too Many Requests`。
- `502 Bad Gateway`。
- `503 Service Unavailable`。
- `504 Gateway Timeout`。

七层代理引入更多功能，也引入更多策略配置和故障点。

## 6. TLS 模式

TLS 是四层与七层选型中最容易混淆的部分。

### 6.1 TLS 透传

```text
Client ═════ TLS ═════> Backend
             │
          L4 Proxy
        只转发密文字节
```

特点：

- 证书和私钥保存在后端。
- 代理通常无法读取 HTTP Header、Path 和正文。
- 后端看到并处理 TLS。
- 适合端到端加密、客户端证书认证或合规要求。
- 无法直接在代理执行 HTTP WAF、Header 改写和缓存。

典型场景：

- 银行或合规系统要求代理不能接触明文。
- Kubernetes Ingress 的 SSL Passthrough。
- MySQL TLS、PostgreSQL TLS、MQTT TLS。
- 后端应用自行管理证书和双向 TLS。

### 6.2 TLS 终止

```text
Client ═══ TLS ═══> L7 Proxy ─── HTTP ───> Backend
                    解密并解析
```

特点：

- 证书部署在代理。
- 代理可以读取和处理 HTTP。
- 后端网络中是明文，需要可信网络或其他安全控制。
- 减少后端 TLS 计算和证书管理压力。
- 适合 WAF、鉴权、路径路由、缓存。

### 6.3 TLS 终止后重新加密

```text
Client ═══ TLS A ═══> L7 Proxy ═══ TLS B ═══> Backend
```

这不是同一条端到端 TLS 会话，而是两条独立 TLS 会话：

- 客户端验证代理证书。
- 代理验证后端证书。
- 代理中可以看到明文。

适合既需要七层能力，又要求内部链路加密的场景。

代理应开启后端证书验证，不能仅设置“使用 TLS”却关闭证书校验。

### 6.4 TLS Bridge 与 mTLS

代理可以在客户端侧或后端侧使用双向 TLS（mTLS）：

```text
Client ⇄ mTLS ⇄ Proxy ⇄ mTLS ⇄ Backend
```

两侧证书身份可能不同。代理需要分别管理信任链、证书轮换、SNI 和验证规则。

### 6.5 SNI 路由

TLS ClientHello 中通常包含 SNI，表示客户端希望访问的域名。四层代理可以只读取握手开头，按 SNI 选择后端，但不终止 TLS：

```text
SNI = api.example.com → Backend A
SNI = web.example.com → Backend B
```

限制：

- 只能按握手元数据路由，不能按 HTTP Path。
- 没有 SNI 的客户端无法使用此规则。
- TLS ECH 会隐藏真实 ClientHello 中的域名，可能影响传统 SNI 路由。
- 它是“透传 + 预读”，不是完整七层 HTTP 代理。

## 7. 常见使用场景

### 7.1 适合四层代理的场景

#### 场景一：数据库

```text
Application → L4 Proxy → MySQL Primary/Replica
```

适用协议：

- MySQL。
- PostgreSQL。
- Redis。
- MongoDB。
- Oracle TNS。

原因：

- 不是普通 HTTP。
- 通常只需要 TCP 连接转发、健康检查和连接级负载均衡。
- 可以保持 TLS 透传。

注意：数据库连接具有会话状态、事务和主从角色。不能仅按轮询随意分配，需要使用数据库感知的健康检查或独立读写入口。

#### 场景二：高性能 TCP/UDP 入口

```text
Internet → L4 Load Balancer → L7 Proxy Cluster
```

四层入口用于：

- 承担大规模连接。
- 提供固定 VIP。
- DDoS 清洗后的流量接入。
- 将流量分散到多个七层代理实例。

#### 场景三：TLS 透传

后端必须直接终止 TLS，或者代理不能持有私钥时，使用四层透传。

#### 场景四：私有协议

在线游戏、IoT、金融网关或设备管理系统使用自定义 TCP/UDP 协议时，四层代理无需理解业务格式即可转发。

#### 场景五：DNS、邮件和消息协议

- DNS TCP/UDP。
- SMTP、IMAP、POP3。
- MQTT。
- AMQP。
- Kafka。

如果需要协议级路由或认证，可能需要专用七层网关，而不是通用 HTTP 代理。

### 7.2 适合七层代理的场景

#### 场景一：网站和 API

```text
api.example.com/users  → user-service
api.example.com/orders → order-service
www.example.com        → web-service
```

需要域名、Path、Header 路由时，使用七层。

#### 场景二：API Gateway

需要以下能力时使用七层：

- JWT/OAuth2 鉴权。
- 租户配额。
- 接口限流。
- API 版本路由。
- Header 转换。
- 请求和响应审计。

#### 场景三：WAF

WAF 需要分析 HTTP 请求方法、URI、Header、Cookie 和正文，因此必须在能够看到明文 HTTP 的七层位置工作。

#### 场景四：灰度发布

```text
Header: X-Canary=true → v2
其他请求              → v1
```

或者：

```text
Cookie user_group=beta → v2
普通用户               → v1
```

#### 场景五：微服务入口和 Service Mesh

Ingress Gateway、API Gateway 和 Sidecar/Node Proxy 通常需要理解 HTTP/gRPC，提供细粒度路由、重试、熔断、遥测和安全策略。

#### 场景六：CDN 和缓存

缓存必须理解 URL、Header、缓存控制和响应状态，因此属于七层能力。

## 8. 常见协议如何选择

| 协议或业务 | 推荐方式 | 原因 |
| --- | --- | --- |
| HTTP/HTTPS 网站 | L7 | 需要域名、路径、缓存、重定向 |
| REST API | L7 | 需要鉴权、限流、Header 和 Path 路由 |
| gRPC | L7 优先 | 可按 Service/Method 路由并处理 HTTP/2 |
| WebSocket | L7 或 L4 | 需要 HTTP Upgrade、鉴权时用 L7；纯透传可用 L4 |
| MySQL/PostgreSQL | L4 | 长连接、非 HTTP 协议 |
| Redis | L4 | TCP 协议，通常按连接转发 |
| DNS | L4 或专用 L7 | 简单转发用 TCP/UDP L4；智能 DNS 需协议感知 |
| Kafka | L4/专用代理 | 普通 TCP 转发可用 L4，但需注意 Broker 地址发现 |
| MQTT | L4/专用 MQTT 网关 | 是否需要 Topic/身份策略决定 |
| SMTP/IMAP | L4/邮件代理 | 简单透传用 L4，反垃圾等需协议级代理 |
| QUIC/HTTP/3 | L4 UDP 或 L7 HTTP/3 | 是否需要理解 HTTP/3 决定 |
| 自定义 TCP/UDP | L4 | 通用七层代理无法理解协议 |

### 8.1 WebSocket

WebSocket 先通过 HTTP/1.1 Upgrade 建立连接，然后变成长连接：

```http
Connection: Upgrade
Upgrade: websocket
```

七层代理需要正确支持 Upgrade 和长连接超时。建立后，通常不再按每个 WebSocket 消息重新选择后端。

### 8.2 gRPC

gRPC 通常基于 HTTP/2。四层代理只能转发整个 HTTP/2 连接；七层 gRPC 代理可以识别：

```text
package.Service/Method
```

需要注意：

- HTTP/2 长连接会导致四层负载不均。
- 七层代理必须原生支持 HTTP/2 和 gRPC Trailer。
- 重试非幂等 RPC 可能造成重复操作。

### 8.3 Kafka

Kafka 客户端连接 Bootstrap Server 后，会获取 Broker 地址并直接连接 Broker。仅在入口放一个普通四层负载均衡器，可能因返回的 Broker 地址不可达而失败。需要：

- 正确配置 `advertised.listeners`。
- 为 Broker 提供可达地址。
- 或使用真正理解 Kafka 协议的代理。

这说明“协议能通过 TCP”不等于“随便加一个四层负载均衡器就能工作”。

## 9. 常见产品与定位

### 9.1 LVS/IPVS

定位：

- 内核态四层负载均衡。
- 高吞吐、低开销。
- 常用于大规模入口、Kubernetes Service 或前置负载均衡。

优点：

- 性能高。
- 支持 NAT、DR、Tunnel 等模式。

限制：

- 不理解 HTTP Path、Header 和 Cookie。
- 应用层治理能力弱。

### 9.2 Nginx

Nginx 有两类主要代理能力：

```text
stream {} → TCP/UDP 四层代理
http {}   → HTTP/HTTPS 七层代理
```

适合：

- Web 反向代理。
- 静态资源和缓存。
- TLS 终止。
- 中小规模 TCP/UDP 代理。

### 9.3 HAProxy

HAProxy 通过模式区分：

```text
mode tcp  → 四层 TCP 代理
mode http → 七层 HTTP 代理
```

适合：

- 高性能 TCP/HTTP 负载均衡。
- 灵活健康检查。
- ACL 路由。
- 连接和请求级治理。

### 9.4 Envoy

Envoy 主要面向云原生和服务网格：

- TCP Proxy Filter 提供四层代理。
- HTTP Connection Manager 提供七层 HTTP/gRPC 代理。
- 支持 xDS 动态配置。
- 提供重试、熔断、Tracing、mTLS 和丰富遥测。

功能强，但配置和运维复杂度通常高于基础 Nginx。

### 9.5 云负载均衡

不同云厂商名称不同，常见分类：

- 网络型负载均衡：L4 TCP/UDP/TLS。
- 应用型负载均衡：L7 HTTP/HTTPS/HTTP2/gRPC。

“TLS Listener”不一定代表七层。若产品只终止或转发 TLS，但不能按 HTTP 内容路由，仍应按实际能力判断。

### 9.6 CDN、WAF 和 API Gateway

| 产品 | 主要层级 | 核心能力 |
| --- | --- | --- |
| CDN | L7 | HTTP 内容缓存、边缘加速 |
| WAF | L7 | 检查 HTTP 请求和攻击特征 |
| API Gateway | L7 | API 路由、认证、限流、配额 |
| DDoS 清洗 | L3/L4 为主，也可含 L7 | 流量清洗和攻击缓解 |
| Service Mesh | L4 + L7 | 服务间流量治理与安全 |

## 10. Nginx 四层代理示例

### 10.1 TCP 代理

确认 Nginx 包含 Stream 模块：

```bash
nginx -V 2>&1 | grep -- --with-stream
```

配置示例：

```nginx
stream {
    upstream mysql_backend {
        least_conn;

        server 10.0.1.11:3306 max_fails=3 fail_timeout=10s;
        server 10.0.1.12:3306 max_fails=3 fail_timeout=10s;
    }

    server {
        listen 3306;

        proxy_connect_timeout 3s;
        proxy_timeout 1h;
        proxy_pass mysql_backend;
    }
}
```

检查并重载：

```bash
sudo nginx -t
sudo nginx -s reload
```

验证：

```bash
nc -vz <NGINX_IP> 3306
mysql -h <NGINX_IP> -P 3306 -u <USER> -p
```

### 10.2 UDP 代理

```nginx
stream {
    upstream dns_backend {
        server 10.0.2.11:53;
        server 10.0.2.12:53;
    }

    server {
        listen 53 udp reuseport;
        proxy_timeout 5s;
        proxy_responses 1;
        proxy_pass dns_backend;
    }
}
```

验证：

```bash
dig @<NGINX_IP> example.com
```

### 10.3 TLS SNI 透传

```nginx
stream {
    map $ssl_preread_server_name $tls_backend {
        api.example.com api_tls;
        web.example.com web_tls;
        default         default_tls;
    }

    upstream api_tls {
        server 10.0.3.11:443;
    }

    upstream web_tls {
        server 10.0.3.12:443;
    }

    upstream default_tls {
        server 10.0.3.13:443;
    }

    server {
        listen 443;
        ssl_preread on;
        proxy_pass $tls_backend;
    }
}
```

代理不会解密 HTTP，证书仍由后端提供。

## 11. Nginx 七层代理示例

### 11.1 按域名和路径路由

```nginx
http {
    upstream user_service {
        least_conn;
        server 10.0.10.11:8080;
        server 10.0.10.12:8080;
        keepalive 64;
    }

    upstream order_service {
        least_conn;
        server 10.0.11.11:8080;
        server 10.0.11.12:8080;
        keepalive 64;
    }

    server {
        listen 443 ssl http2;
        server_name api.example.com;

        ssl_certificate     /etc/nginx/tls/fullchain.pem;
        ssl_certificate_key /etc/nginx/tls/private.key;

        location /api/users/ {
            proxy_pass http://user_service;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 3s;
            proxy_read_timeout 30s;
        }

        location /api/orders/ {
            proxy_pass http://order_service;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 3s;
            proxy_read_timeout 30s;
        }
    }
}
```

### 11.2 灰度路由

```nginx
map $http_x_canary $order_upstream {
    default order_v1;
    "true"  order_v2;
}

upstream order_v1 {
    server 10.0.11.11:8080;
}

upstream order_v2 {
    server 10.0.12.11:8080;
}

server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate     /etc/nginx/tls/fullchain.pem;
    ssl_certificate_key /etc/nginx/tls/private.key;

    location /api/orders/ {
        proxy_pass http://$order_upstream;
    }
}
```

客户端：

```bash
curl -H 'X-Canary: true' https://api.example.com/api/orders/1001
```

生产灰度还应考虑用户一致性、回滚、监控、缓存和数据库兼容，不能只依赖一个 Header。

## 12. HAProxy 四层与七层示例

### 12.1 四层 TCP 模式

```haproxy
global
    log stdout format raw local0
    maxconn 100000

defaults
    log global
    mode tcp
    timeout connect 3s
    timeout client  1h
    timeout server  1h

frontend mysql_frontend
    bind *:3306
    mode tcp
    default_backend mysql_backend

backend mysql_backend
    mode tcp
    balance leastconn
    option tcp-check
    server mysql1 10.0.1.11:3306 check
    server mysql2 10.0.1.12:3306 check
```

### 12.2 七层 HTTP 模式

```haproxy
global
    log stdout format raw local0
    maxconn 100000

defaults
    log global
    mode http
    option httplog
    timeout connect 3s
    timeout client  30s
    timeout server  30s

frontend https_frontend
    bind *:443 ssl crt /etc/haproxy/certs/api.example.com.pem
    mode http

    acl is_users  path_beg /api/users/
    acl is_orders path_beg /api/orders/
    acl is_canary req.hdr(X-Canary) -i true

    use_backend order_v2 if is_orders is_canary
    use_backend order_v1 if is_orders
    use_backend user_backend if is_users
    default_backend web_backend

backend user_backend
    mode http
    balance roundrobin
    option httpchk GET /health
    http-check expect status 200
    server user1 10.0.10.11:8080 check
    server user2 10.0.10.12:8080 check

backend order_v1
    mode http
    server order1 10.0.11.11:8080 check

backend order_v2
    mode http
    server order2 10.0.12.11:8080 check

backend web_backend
    mode http
    server web1 10.0.20.11:8080 check
```

验证配置：

```bash
haproxy -c -f /etc/haproxy/haproxy.cfg
```

## 13. Kubernetes 中的四层和七层

### 13.1 Service：主要是四层

Kubernetes Service 为变化的 Pod 提供稳定地址，常见类型：

- `ClusterIP`：集群内部访问。
- `NodePort`：每个 Node 开放端口。
- `LoadBalancer`：申请外部负载均衡器。
- `ExternalName`：返回 DNS CNAME，不执行代理。

示例：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mysql
  namespace: database
spec:
  type: LoadBalancer
  selector:
    app: mysql
  ports:
    - name: mysql
      protocol: TCP
      port: 3306
      targetPort: 3306
```

Service 通常依据 IP、端口和协议转发，属于四层能力。具体数据路径可能由 iptables、IPVS、eBPF 或云负载均衡实现。

### 13.2 Ingress：HTTP/HTTPS 七层入口

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api
  namespace: production
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.example.com
      secretName: api-example-com-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /api/users
            pathType: Prefix
            backend:
              service:
                name: user-service
                port:
                  number: 8080
          - path: /api/orders
            pathType: Prefix
            backend:
              service:
                name: order-service
                port:
                  number: 8080
```

Ingress 资源本身不会转发流量，必须安装对应的 Ingress Controller。

Kubernetes 官方已冻结 Ingress API 的功能演进，新增高级能力建议优先评估 Gateway API。Ingress 不会被立即移除，现有稳定工作负载仍可继续使用。

### 13.3 Gateway API

Gateway API 可以同时表达多种路由：

- `HTTPRoute`：HTTP 七层路由。
- `GRPCRoute`：gRPC 七层路由。
- `TCPRoute`：TCP 四层路由。
- `UDPRoute`：UDP 四层路由。
- `TLSRoute`：基于 TLS 信息的路由。

HTTPRoute 示例：

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public-gateway
  namespace: gateway-system
spec:
  gatewayClassName: example-gateway-class
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      hostname: "*.example.com"
      tls:
        mode: Terminate
        certificateRefs:
          - kind: Secret
            name: wildcard-example-com
      allowedRoutes:
        namespaces:
          from: All
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api
  namespace: production
spec:
  parentRefs:
    - name: public-gateway
      namespace: gateway-system
  hostnames:
    - api.example.com
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api/users
      backendRefs:
        - name: user-service
          port: 8080
    - matches:
        - path:
            type: PathPrefix
            value: /api/orders
      backendRefs:
        - name: order-service
          port: 8080
```

Gateway API 是 CRD 规范，仍需安装支持它的 Controller。不同实现对扩展路由类型和高级能力的支持程度不同。

### 13.4 常见 Kubernetes 流量路径

```text
Internet
   │
   ▼
Cloud L4 LoadBalancer
   │
   ▼
Ingress/Gateway L7 Proxy
   │
   ▼
Kubernetes Service L4
   │
   ▼
Pod
```

这不是重复设计：

- 外部 L4 提供固定 VIP、高吞吐和连接分发。
- L7 Gateway 提供域名、路径、TLS、鉴权和路由。
- Service 为动态 Pod 提供稳定后端集合。

## 14. 源 IP 保留

### 14.1 为什么后端看不到客户端 IP

全代理模式下，后端 TCP 连接由代理发起，因此后端看到的源 IP 通常是代理 IP：

```text
Client 192.0.2.10 → Proxy 198.51.100.10
Proxy 10.0.0.10   → Backend 10.0.1.10
```

### 14.2 七层 Header

HTTP 代理常添加：

```http
X-Forwarded-For: 192.0.2.10
X-Forwarded-Proto: https
X-Forwarded-Host: api.example.com
Forwarded: for=192.0.2.10;proto=https;host=api.example.com
```

安全要求：

- 只信任受控代理添加的 Header。
- 入口代理应清理客户端伪造的转发 Header。
- 应用应配置可信代理网段，不能无条件信任最左侧 IP。

### 14.3 PROXY Protocol

PROXY Protocol 可以在 TCP 连接开头传递原始源/目标地址，适用于四层代理：

```text
PROXY TCP4 192.0.2.10 198.51.100.20 51324 443\r\n
```

要求：

- 上游代理开启发送。
- 后端或下一级代理明确开启接收。
- 两端配置不一致会导致后端把 PROXY Header 当作业务数据，连接失败。

### 14.4 DSR

DSR 模式可让后端直接向客户端返回，从而减轻负载均衡器响应流量压力。但它对网络、VIP、ARP、路由和后端配置有更高要求。

## 15. 负载均衡算法

### 15.1 Round Robin

按顺序选择后端：

```text
A → B → C → A
```

适合请求或连接处理能力接近的无状态实例。

### 15.2 Weighted Round Robin

按权重分配：

```text
A weight=5
B weight=3
C weight=2
```

适合实例规格不同或灰度流量。

### 15.3 Least Connections

选择当前连接数较少的后端。适合连接持续时间差异较大的场景，但连接数不一定等价于实际负载。

### 15.4 Hash

根据源 IP、Cookie、Header 或一致性哈希选择后端：

- 源 IP Hash：四层常用。
- Cookie/Header Hash：七层常用。
- URL Hash：缓存场景。

Hash 可提高会话一致性，但会降低负载均衡灵活性。后端增删时应使用一致性哈希减少大规模映射变化。

### 15.5 随机与 Power of Two Choices

随机选择两个后端，再从中选负载较低者，在大规模集群中能以较低开销获得较好均衡效果。

## 16. 健康检查

### 16.1 四层健康检查

TCP Connect：

```text
能建立 TCP 连接 → 健康
```

优点是简单，缺点是应用进程可能接受连接却无法正常提供业务。

TLS 检查可以验证握手和证书，但仍不一定证明业务接口正常。

### 16.2 七层健康检查

```http
GET /health/ready HTTP/1.1
Host: api.example.com
```

期望：

```http
HTTP/1.1 200 OK
```

七层检查能确认应用协议状态，但健康接口设计应避免：

- 每次检查执行昂贵数据库查询。
- 因一个非关键依赖异常让所有实例下线。
- 返回固定 `200`，完全不反映服务状态。
- Readiness 与 Liveness 混用。

### 16.3 主动与被动检查

- **主动检查**：代理定期请求后端。
- **被动检查**：代理根据真实流量中的超时、Reset、状态码判断异常。

二者结合通常比单独使用更可靠。

## 17. 超时、重试与连接复用

### 17.1 超时

至少区分：

- 连接超时。
- TLS 握手超时。
- 请求 Header 超时。
- 请求体读取超时。
- 上游响应超时。
- 空闲连接超时。
- 整体请求 Deadline。

四层代理常使用连接和空闲字节流超时；七层代理可以使用请求级超时。

### 17.2 重试风险

对以下幂等请求，失败后通常更适合重试：

```http
GET
HEAD
OPTIONS
```

对以下操作重试必须谨慎：

```http
POST /payments
POST /orders
```

请求可能已经被后端执行，只是响应丢失。自动重试可能造成重复扣款或重复下单。应使用幂等键、业务去重和明确的 Retry Policy。

四层代理无法可靠判断业务请求边界，因此通常不应随意对已发送数据的 TCP 连接做“业务级重试”。

### 17.3 连接池

七层代理常复用到后端的 Keep-Alive 或 HTTP/2 连接：

- 减少握手开销。
- 降低后端连接数量。
- 提高吞吐。

但连接池过大可能压垮后端，过小则造成频繁握手。需要结合并发和后端容量调整。

## 18. 可观测性差异

### 18.1 四层指标

推荐监控：

- 新建连接数。
- 当前连接数。
- TCP 建连失败。
- Reset。
- 重传和丢包。
- 接收/发送字节。
- UDP 数据报和丢弃。
- 后端连接时延。
- 会话持续时间。

### 18.2 七层指标

除四层指标外，还可监控：

- 请求量。
- HTTP 状态码。
- P50/P90/P95/P99 时延。
- 上游服务时延。
- 请求和响应大小。
- 每个 Host、Path、Method 的错误率。
- 限流、鉴权和 WAF 拒绝数量。
- 重试、熔断和超时。

### 18.3 日志

四层日志示例：

```text
client=192.0.2.10:51324 backend=10.0.1.11:3306
duration=128s bytes_in=10240 bytes_out=51320 result=closed
```

七层日志示例：

```text
client=192.0.2.10 host=api.example.com method=POST
path=/v1/orders status=201 duration=83ms upstream=10.0.11.12:8080
```

访问日志可能包含 Token、Cookie、个人信息和请求参数。生产环境应脱敏并设置保留周期。

## 19. 安全差异

### 19.1 四层代理安全能力

- IP/CIDR Allowlist。
- 端口控制。
- 连接数限制。
- SYN Flood 防护。
- TLS 透传。
- mTLS 透传。

它通常无法判断某个 HTTP 请求是否是 SQL 注入或恶意文件上传。

### 19.2 七层代理安全能力

- WAF。
- JWT/OAuth2 鉴权。
- API Key。
- HTTP Method 限制。
- URL 和 Header 规则。
- Body 大小限制。
- Bot 防护。
- 细粒度限流。

七层代理能够看到明文，意味着它本身成为高价值安全边界：

- 私钥必须安全保存。
- 管理面必须隔离。
- 日志必须脱敏。
- 软件必须及时更新。
- 后端证书必须验证。

## 20. 常见架构

### 20.1 纯四层

```text
Client
  │ TCP/TLS
  ▼
L4 Load Balancer
  │ TCP/TLS Passthrough
  ▼
Backend
```

适合数据库、私有协议和端到端 TLS。

### 20.2 纯七层

```text
Client
  │ HTTPS
  ▼
L7 Proxy
  ├─ TLS
  ├─ WAF
  ├─ Auth
  └─ Routing
      ▼
   Backend
```

适合中小规模 Web/API。

### 20.3 L4 + L7 分层

```text
Internet
   │
   ▼
Anycast / DDoS / L4 Load Balancer
   │
   ▼
L7 Proxy Cluster
   │
   ▼
Application Services
```

优点：

- L4 处理大规模连接和固定 VIP。
- L7 专注应用路由和治理。
- 可以水平扩展多个 L7 代理。

代价：

- 链路更长。
- 源 IP 传递更复杂。
- 超时和健康检查必须协调。
- 故障定位需要跨层观测。

### 20.4 CDN + WAF + L4 + L7

```text
Client
  ▼
CDN / WAF
  ▼
Cloud L4 Load Balancer
  ▼
Ingress / API Gateway
  ▼
Service
  ▼
Pod
```

应明确每层职责，避免多层同时重试、缓存、改写 Header 或终止 TLS 导致行为不可预测。

## 21. 选型决策

### 21.1 决策树

```text
流量是 HTTP、HTTPS、gRPC 或 WebSocket 吗？
├─ 否
│  ├─ 是否存在专用的协议感知网关需求？
│  │  ├─ 是 → 使用专用 L7 网关或协议代理
│  │  └─ 否 → 使用 L4
│  └─ 是否需要 TLS 透传？
│     ├─ 是 → L4 TLS Passthrough
│     └─ 否 → L4 TCP/UDP
└─ 是
   ├─ 是否需要 Path/Header/Cookie/WAF/Auth/Cache？
   │  ├─ 是 → L7
   │  └─ 否
   ├─ 是否必须端到端 TLS，代理不能看到明文？
   │  ├─ 是 → L4 TLS Passthrough，可选 SNI 路由
   │  └─ 否 → L7 通常更灵活
   └─ 是否有极端吞吐或海量连接要求？
      ├─ 是 → 前置 L4，再接 L7 集群
      └─ 否 → 单层 L7 即可
```

### 21.2 需求问卷

选型前回答：

1. 业务使用什么协议？
2. 是否需要按域名、路径、Header 或 Cookie 路由？
3. TLS 在哪里终止？代理是否允许看到明文？
4. 是否需要 WAF、鉴权、限流、缓存或灰度？
5. 单连接是否承载大量请求，例如 HTTP/2、gRPC？
6. 是否需要保留客户端真实 IP？
7. 峰值连接数、QPS、带宽、包速率是多少？
8. 后端是否有会话状态？
9. 请求是否可以安全重试？
10. 需要什么日志、指标和追踪？
11. 故障时是否允许绕过七层功能？
12. 团队能否承担复杂代理规则和证书运维？

### 21.3 典型推荐

| 需求 | 推荐 |
| --- | --- |
| 高并发 HTTPS 网站，需要 WAF 和 Path 路由 | L4 入口 + L7 集群 |
| 中小型网站/API | L7 |
| MySQL 高可用入口 | L4 + 数据库角色感知方案 |
| Redis Cluster | 优先让客户端理解拓扑；必要时使用适配方案 |
| Kubernetes Web 入口 | Gateway API/Ingress L7 + Service L4 |
| Kubernetes 数据库入口 | Service LoadBalancer L4 |
| 端到端 mTLS 且代理不可解密 | L4 TLS Passthrough |
| gRPC 微服务 | L7 gRPC Proxy |
| 游戏私有 UDP | L4 UDP 或协议专用网关 |

## 22. 常见误区

### 22.1 “Nginx 就是七层代理”

错误。Nginx 的 HTTP 模块是七层代理，Stream 模块可提供四层 TCP/UDP 代理。

### 22.2 “负载均衡器一定是代理”

不完全正确。LVS-DR、DSR 等方案主要做数据包转发，返回流量甚至不经过负载均衡器。

### 22.3 “HTTPS 只能用七层代理”

错误。HTTPS 可以通过四层 TCP/TLS 透传，TLS 在后端终止。

### 22.4 “代理能看到 SNI，所以它是完整七层代理”

错误。读取 TLS ClientHello 的 SNI 只提供有限握手信息，代理仍看不到加密的 HTTP Path、Header 和 Body。

### 22.5 “四层一定保留真实源 IP”

错误。全代理或 NAT 模式可能让后端只看到代理 IP。需要 DSR、透明代理、PROXY Protocol 或其他源地址传递机制。

### 22.6 “七层代理可以安全重试所有请求”

错误。非幂等请求可能已经被后端执行，自动重试会造成重复操作。

### 22.7 “Kubernetes Service 永远通过 kube-proxy”

不一定。实现可能是 iptables、IPVS、eBPF 数据面或云厂商负载均衡器。Service API 描述目标行为，不限定唯一数据路径。

### 22.8 “有健康检查就不会把流量发到故障实例”

错误。检查存在间隔、阈值和传播延迟，可能出现短暂误判。应用还可能只对特定接口故障，而健康接口正常。

## 23. 故障排查

### 23.1 先判断在哪一层失败

```text
DNS 能否解析？
  ↓
IP 是否可达？
  ↓
TCP/UDP 是否可达？
  ↓
TLS 是否成功？
  ↓
HTTP/应用协议是否正常？
  ↓
代理路由是否匹配？
  ↓
后端应用是否正常？
```

### 23.2 四层排查命令

DNS：

```bash
dig api.example.com
```

TCP：

```bash
nc -vz api.example.com 443
```

路由：

```bash
traceroute api.example.com
tracepath api.example.com
```

连接状态：

```bash
ss -s
ss -ntp
```

抓包：

```bash
sudo tcpdump -ni any host <CLIENT_OR_BACKEND_IP> and port 443
```

观察：

- SYN 是否到达。
- SYN-ACK 是否返回。
- 是否出现 Reset。
- 是否反复重传。
- 返回路径是否对称。

### 23.3 TLS 排查

```bash
openssl s_client \
  -connect api.example.com:443 \
  -servername api.example.com \
  -showcerts
```

检查：

- 返回证书是否正确。
- SNI 是否生效。
- 证书链是否完整。
- TLS 协议和 Cipher 是否匹配。
- 是代理证书还是后端证书。

### 23.4 七层 HTTP 排查

```bash
curl -vk \
  --resolve api.example.com:443:<PROXY_IP> \
  https://api.example.com/api/health
```

记录详细时延：

```bash
curl -sS -o /dev/null \
  -w 'dns=%{time_namelookup}\nconnect=%{time_connect}\ntls=%{time_appconnect}\nfirst_byte=%{time_starttransfer}\ntotal=%{time_total}\nstatus=%{http_code}\n' \
  https://api.example.com/api/health
```

### 23.5 常见状态码

#### 400

可能原因：

- 请求格式错误。
- Header 太大或非法。
- PROXY Protocol 配置不匹配。
- HTTP 请求发送到了 HTTPS 端口。

#### 404

可能原因：

- Host 或 Path 路由未匹配。
- Rewrite 后路径不正确。
- 请求已到后端，但后端没有该路由。

#### 502

可能原因：

- 代理无法连接后端。
- 后端立即 Reset。
- 上游协议不匹配，例如 HTTPS 配成 HTTP。
- DNS 解析到错误地址。

#### 503

可能原因：

- 没有健康后端。
- 熔断或维护规则。
- Service 没有 Endpoint。

#### 504

可能原因：

- 后端响应超过代理超时。
- 网络丢包或后端线程池阻塞。
- 多层代理超时配置顺序错误。

### 23.6 多层超时原则

外层超时通常应略大于内层：

```text
Client Timeout
  > Edge Proxy Timeout
    > Internal Gateway Timeout
      > Application/Dependency Timeout
```

否则外层先断开时，内层和应用可能继续执行无意义工作。

## 24. 性能测试

### 24.1 测试指标

不能只看 QPS。应同时测：

- 每秒新建连接数。
- 并发连接数。
- 请求吞吐。
- 包速率 PPS。
- 带宽。
- P50/P95/P99/P999 时延。
- 错误率。
- CPU、内存和上下文切换。
- TLS 握手率和 Session Reuse。
- 后端连接池。
- 日志 I/O。

### 24.2 测试原则

- 使用与生产一致的 TLS、Header、正文大小和连接复用。
- 测试长连接、短连接和突发流量。
- 开启实际会使用的 WAF、鉴权、日志和追踪。
- 测试单后端故障、代理重启和网络抖动。
- 客户端压测机不能成为瓶颈。
- 观察代理和后端，而不是只看客户端结果。

HTTP 示例：

```bash
wrk -t8 -c1000 -d60s https://api.example.com/api/health
```

TCP 连接测试可使用适合目标协议的工具。不要用只会发送空 TCP 数据的工具代表真实数据库或消息协议性能。

## 25. 生产最佳实践

### 25.1 明确每层职责

记录：

- 哪一层终止 TLS。
- 哪一层执行鉴权。
- 哪一层限流。
- 哪一层重试。
- 哪一层修改 Header。
- 哪一层记录审计日志。

避免多层重复执行同一功能。

### 25.2 配置即代码

- 将代理配置纳入 Git。
- 使用 CI 执行语法检查。
- 变更前生成配置 Diff。
- 使用小流量灰度。
- 保留快速回滚版本。

Nginx：

```bash
nginx -t
```

HAProxy：

```bash
haproxy -c -f /etc/haproxy/haproxy.cfg
```

Kubernetes：

```bash
kubectl diff -f gateway.yaml
kubectl apply --server-side --dry-run=server -f gateway.yaml
```

### 25.3 高可用

- 至少两个代理实例。
- 实例跨节点或可用区分布。
- 健康检查不能只检查进程存活。
- 配置和证书发布应支持滚动升级。
- 确认连接 Drain 行为。
- 长连接业务应设置足够的优雅退出时间。

### 25.4 容量保护

- 设置最大连接数。
- 设置请求体上限。
- 设置合理超时。
- 限制单客户端连接和请求速率。
- 对后端设置连接池和并发上限。
- 监控文件描述符和端口耗尽。

### 25.5 证书管理

- 自动签发和轮换证书。
- 监控证书到期时间。
- 私钥使用最小权限。
- 后端 TLS 开启证书校验。
- 清理不安全 TLS 协议和 Cipher。

### 25.6 可观测性

至少建立：

- L4 连接、流量和错误 Dashboard。
- L7 请求量、错误率和延迟 Dashboard。
- 后端健康状态。
- TLS 握手和证书告警。
- 配置发布记录。
- 跨代理和应用的 Trace ID。

## 26. 总结

四层代理和七层代理的本质差异，不是软件名字，也不是是否使用 TLS，而是代理对流量理解到什么程度、以什么粒度做决策：

- 四层理解连接和传输协议，适合高性能、协议无关、TCP/UDP、数据库和 TLS 透传。
- 七层理解应用协议，适合 Web/API、域名与路径路由、鉴权、WAF、限流、缓存和灰度。
- 大型系统经常组合使用：前置四层承担连接和流量分发，后置七层完成应用治理。

最终选型应围绕协议、TLS、安全、调度粒度、性能和运维复杂度，而不是简单比较“哪一层更高级”。

## 27. 官方参考资料

- [RFC 1122：Requirements for Internet Hosts — Communication Layers](https://www.rfc-editor.org/rfc/rfc1122)
- [RFC 9112：HTTP/1.1](https://www.rfc-editor.org/rfc/rfc9112)
- [NGINX Stream：TCP/UDP Session Processing](https://nginx.org/en/docs/stream/stream_processing.html)
- [NGINX Stream Proxy Module](https://nginx.org/en/docs/stream/ngx_stream_proxy_module.html)
- [NGINX Stream SSL Module](https://nginx.org/en/docs/stream/ngx_stream_ssl_module.html)
- [HAProxy：Layer 4 and Layer 7 Proxy Mode](https://www.haproxy.com/blog/layer-4-and-layer-7-proxy-mode)
- [HAProxy Configuration Manual Introduction](https://www.haproxy.com/documentation/haproxy-configuration-manual/new/latest/intro/)
- [Kubernetes Service](https://kubernetes.io/docs/concepts/services-networking/service/)
- [Kubernetes Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/)
- [Kubernetes Gateway API](https://kubernetes.io/docs/concepts/services-networking/gateway/)
