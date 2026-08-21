# Jaeger 分布式追踪：从入门到生产实践

> 文档基线：Jaeger 2.20，核对日期：2026-08-21。Jaeger、OpenTelemetry 和 Helm Chart 更新较快，部署前应重新核对目标版本文档与 Release Notes。

## 1. 先讲结论

Jaeger 是一个开源的分布式追踪平台，用于接收、存储、查询和展示 Trace。它最适合回答以下问题：

- 一次请求经过了哪些微服务；
- 请求慢在网关、应用、数据库还是第三方接口；
- 错误最早出现在哪个 Span；
- 同一个接口为什么只有少数请求很慢；
- 服务之间实际存在什么调用关系；
- 日志中的 `trace_id` 对应哪一条完整调用链。

新项目推荐组合：

~~~text
应用
  → OpenTelemetry SDK 或自动探针
  → OTLP
  → OpenTelemetry Collector（推荐）
  → Jaeger
  → OpenSearch / Elasticsearch

工程师
  → Jaeger UI
  → 查询 Trace、分析延迟和错误
~~~

关键边界：

- Jaeger 不是 APM Agent，本身不会自动进入业务代码产生 Span；
- Jaeger 主要处理 Trace，不负责替代 Prometheus 指标和日志平台；
- 新应用应使用 OpenTelemetry，不再使用旧 Jaeger Client SDK；
- `all-in-one + memory` 只适合学习和测试，重启会丢数据；
- 生产环境通常使用外部 OpenSearch 或 Elasticsearch；
- Jaeger v2 建立在 OpenTelemetry Collector 框架上，配置方式与 v1 明显不同；
- 采样策略会直接决定成本、存储量和故障可见性。

---

## 2. Jaeger 是什么

Jaeger 最初由 Uber 开源，后来进入 CNCF。它负责分布式追踪后端和查询界面，核心能力包括：

- 接收 OTLP Trace；
- 持久化 Span；
- 按服务、操作、时间、耗时、标签和错误查询；
- 根据 Trace ID 读取完整调用链；
- 展示时间线、父子关系和关键路径；
- 展示服务依赖关系；
- 提供查询 API；
- 支持采样、归档和 Service Performance Monitoring；
- 与 OpenTelemetry、Prometheus、Grafana、OpenSearch 等系统集成。

Jaeger 的名字来自德语单词 Jäger，意为“猎人”。在运维场景中，可以把它理解成一个追踪请求去向的系统。

---

## 3. 为什么需要分布式追踪

单体应用中，一次请求通常只经过一个进程，查看一份日志就可能找到问题。微服务环境中的一次请求可能经过：

~~~text
用户
  → API Gateway
  → 订单服务
  → 库存服务
  → Redis
  → 支付服务
  → 第三方支付接口
  → MySQL
~~~

只依靠日志时会遇到：

- 多个服务的日志分散在不同机器或 Pod；
- 时间戳存在偏差；
- 同一时间存在大量并发请求；
- 无法直接看出父子调用关系；
- 很难区分网络等待、数据库等待和业务计算；
- 错误可能在上游表现为超时，但根因在更深层服务。

分布式追踪通过统一的 Trace 上下文把同一次请求的多个操作连接起来。

---

## 4. Trace、Span 与上下文

### 4.1 Trace

Trace 表示一次端到端请求。例如一次“创建订单”：

~~~text
Trace: 创建订单
├── Span: POST /orders
├── Span: inventory.reserve
│   └── Span: SELECT inventory
├── Span: payment.charge
│   └── Span: POST payment-provider.example
└── Span: INSERT orders
~~~

同一条 Trace 中的 Span 共享相同的 `trace_id`。

### 4.2 Span

Span 表示一个有开始时间和结束时间的操作，通常包含：

| 字段 | 说明 |
|---|---|
| `trace_id` | 所属 Trace 的唯一标识 |
| `span_id` | 当前 Span 的唯一标识 |
| `parent_span_id` | 父 Span 标识 |
| Name | 操作名称，例如 `GET /users/{id}` |
| Kind | Server、Client、Producer、Consumer、Internal |
| Start/Duration | 开始时间和持续时间 |
| Status | Unset、OK、Error |
| Attributes | HTTP、DB、消息队列、业务等属性 |
| Events | Span 内发生的事件，例如异常 |
| Links | 与其他 Span 的非父子关系 |
| Resource | 服务名、版本、环境、实例等资源信息 |

### 4.3 Trace Context

服务之间必须传播 Trace 上下文。HTTP 中通常使用 W3C Trace Context：

~~~text
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
tracestate: vendor_specific_value
~~~

如果上游没有注入，或者下游没有提取 `traceparent`，一条调用链就会断成多条 Trace。

### 4.4 Baggage

Baggage 是随调用链传播的键值数据。它适合传递少量路由或诊断上下文，不适合传递密码、Token、身份证号等敏感信息。

Baggage 会随请求传播，字段过多会增加网络和处理开销。

---

## 5. Jaeger 不是什么

### 5.1 不等于 OpenTelemetry

OpenTelemetry 是生成、处理和传输遥测数据的标准及工具集合；Jaeger 是 Trace 后端和查询系统。

~~~text
OpenTelemetry：负责把 Trace 造出来并送出去
Jaeger：负责接收、保存、查询和展示 Trace
~~~

### 5.2 不等于 Prometheus

Prometheus 适合聚合指标和告警，例如：

~~~text
错误率 5 分钟超过 2%
P99 延迟超过 1 秒
CPU 使用率超过 85%
~~~

Jaeger 适合进一步回答：

~~~text
具体哪一次请求失败
请求经过了哪些服务
哪一个 Span 最慢
错误属性和异常事件是什么
~~~

### 5.3 不等于日志平台

日志记录离散事件和文本；Trace 记录一次请求的结构和时间关系。最佳实践是让日志携带 `trace_id` 和 `span_id`，实现双向跳转。

### 5.4 不等于完整 APM 商业平台

Jaeger 提供核心追踪能力，但完整的告警、主机监控、真实用户监控、持续剖析、发布追踪和业务分析通常需要其他系统配合。

---

## 6. Jaeger v2 架构

Jaeger v2 是基于 OpenTelemetry Collector 框架构建的单一二进制程序。通过配置文件，它可以承担不同角色。

### 6.1 核心角色

| 角色 | 职责 |
|---|---|
| Collector | 接收 Trace，处理并写入存储 |
| Query | 提供查询 API 和 Jaeger UI |
| Ingester | 从 Kafka 读取 Span 并写入存储 |
| All-in-one | 在一个进程中同时运行 Collector 和 Query |
| Agent | 靠近应用接收并转发数据；新架构更推荐 OTel Collector |

### 6.2 测试架构

~~~mermaid
flowchart LR
    A[应用与 OTel SDK] -->|OTLP 4317/4318| J[Jaeger all-in-one]
    J --> M[(内存存储)]
    U[浏览器] -->|16686| J
~~~

特点：

- 部署简单；
- 适合学习、开发和功能验证；
- 重启后 Trace 消失；
- 不具备存储高可用；
- 不应直接作为生产方案。

### 6.3 生产直写存储架构

~~~mermaid
flowchart LR
    A[应用 OTel SDK] --> C[OTel Collector Agent/Gateway]
    C -->|OTLP| JC[Jaeger Collector]
    JC --> OS[(OpenSearch)]
    JQ[Jaeger Query/UI] --> OS
    U[工程师] --> JQ
~~~

Collector 和 Query 是无状态组件，可以独立扩容。OpenSearch 承担持久化和检索。

### 6.4 使用 Kafka 缓冲

~~~mermaid
flowchart LR
    A[应用] --> OC[OTel Collector]
    OC --> JC[Jaeger Collector]
    JC --> K[(Kafka)]
    K --> I[Jaeger Ingester]
    I --> OS[(OpenSearch)]
    Q[Jaeger Query/UI] --> OS
~~~

Kafka 适用于：

- 峰值流量明显；
- 存储偶发变慢；
- 需要削峰和异步重试；
- 需要从 Trace 流构建额外处理管道。

Kafka 会增加部署、容量规划、消息积压和故障恢复复杂度。流量不大时不要为了“架构完整”强行引入。

---

## 7. 一条 Trace 的完整数据流

~~~text
1. 应用入口收到请求
2. OTel SDK 创建 Server Span
3. SDK 把 traceparent 注入下游 HTTP/gRPC/MQ 请求
4. 下游提取上下文并创建子 Span
5. SDK 根据采样决策导出 Span
6. OTel Collector 接收、批处理、过滤或采样
7. Jaeger Collector 接收 OTLP Trace
8. Jaeger 将 Trace 写入存储
9. 用户在 Jaeger UI 设置条件查询
10. Query 从存储读取 Trace 并返回 UI
~~~

任意一环失败都会造成“查不到 Trace”或“调用链不完整”。排障时必须先判断数据停在哪一层。

---

## 8. 版本与兼容边界

本文以 Jaeger `2.20.0` 为示例。需要特别区分：

| 内容 | v1 | v2 |
|---|---|---|
| 配置方式 | 大量 CLI 参数和环境变量 | OTel Collector 风格 YAML |
| 二进制 | 多组件二进制及 all-in-one | 单一二进制按配置承担角色 |
| SDK 建议 | 历史上使用 Jaeger Client | 使用 OpenTelemetry SDK |
| Agent | 常见 UDP Agent 模式 | 更推荐标准 OTel Collector |
| 主接入协议 | Jaeger Thrift 等 | OTLP gRPC/HTTP |
| 文档状态 | 1.76 已归档 | 2.x 是当前主线 |

看到以下内容时，要警惕它可能是旧教程：

- `jaeger-agent` DaemonSet；
- 应用直接向 `6831/UDP` 发送 Span；
- `JAEGER_AGENT_HOST`；
- `SPAN_STORAGE_TYPE` 作为 v2 主配置；
- `jaeger-client-java`、`jaeger-client-go`；
- 独立 `jaeger-collector` 和 `jaeger-query` v1 镜像。

这些能力可能仍为兼容而存在，但不应作为新项目的默认设计。

---

## 9. 常用端口

| 端口 | 协议 | 用途 | 建议 |
|---|---|---|---|
| `4317` | gRPC | 接收 OTLP Trace | 新项目首选之一 |
| `4318` | HTTP | `/v1/traces`，接收 OTLP | 新项目首选之一 |
| `16686` | HTTP | Jaeger UI 和 HTTP Query API | 只对受控网络开放 |
| `16685` | gRPC | Query API | 按需开放 |
| `5778` | HTTP | 远程采样配置 | 需要远程采样时使用 |
| `9411` | HTTP | Zipkin 兼容接收端口 | 迁移或兼容场景 |
| `14250` | gRPC | 旧 Jaeger Proto | 兼容用途 |
| `14268` | HTTP | 旧 Jaeger Thrift | 兼容用途 |
| `6831/6832` | UDP | 旧 Jaeger Agent Thrift | 新项目通常不用 |
| `8888` | HTTP | Prometheus 指标 | 仅监控网络访问 |
| `13133` | HTTP | v2 健康检查 | 取决于配置 |

不要把所有端口无差别暴露到公网。通常只有应用或 Collector 能访问 OTLP 端口，只有运维入口能访问 UI。

---

## 10. Docker 快速体验

### 10.1 启动 Jaeger

~~~bash
docker run --rm --name jaeger \
  -p 127.0.0.1:16686:16686 \
  -p 127.0.0.1:4317:4317 \
  -p 127.0.0.1:4318:4318 \
  -p 127.0.0.1:5778:5778 \
  -p 127.0.0.1:9411:9411 \
  cr.jaegertracing.io/jaegertracing/jaeger:2.20.0
~~~

打开：

~~~text
http://127.0.0.1:16686
~~~

该命令使用内存存储。容器停止后数据丢失。

### 10.2 后台运行

~~~bash
docker run -d --name jaeger \
  --restart unless-stopped \
  -p 127.0.0.1:16686:16686 \
  -p 127.0.0.1:4317:4317 \
  -p 127.0.0.1:4318:4318 \
  cr.jaegertracing.io/jaegertracing/jaeger:2.20.0
~~~

检查：

~~~bash
docker ps --filter name=jaeger
docker logs --tail 100 jaeger
curl -I http://127.0.0.1:16686/
ss -lntp | grep -E ':(16686|4317|4318)\b'
~~~

### 10.3 Docker Compose

~~~yaml
services:
  jaeger:
    image: cr.jaegertracing.io/jaegertracing/jaeger:2.20.0
    container_name: jaeger
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    ports:
      - "127.0.0.1:16686:16686"
      - "127.0.0.1:4317:4317"
      - "127.0.0.1:4318:4318"
    networks:
      - observability

networks:
  observability:
    name: observability
~~~

执行：

~~~bash
docker compose config
docker compose up -d
docker compose ps
docker compose logs --tail 100 jaeger
~~~

---

## 11. 使用官方 HotROD 示例产生 Trace

HotROD 是 Jaeger 官方的多服务演示应用，可以生成带错误和延迟的调用链。

~~~bash
git clone https://github.com/jaegertracing/jaeger.git
cd jaeger/examples/hotrod
export JAEGER_VERSION=2.20.0
docker compose up
~~~

打开：

~~~text
HotROD：http://127.0.0.1:8080
Jaeger：http://127.0.0.1:16686
~~~

在 HotROD 页面多次选择客户并发起请求，然后在 Jaeger UI 中选择对应服务查询。

这个示例会拉取多个镜像并启动多项服务，只适合实验环境。停止：

~~~bash
docker compose down
~~~

如果要同时删除该示例产生的卷，应先确认卷中没有需要保留的数据，再执行：

~~~bash
docker compose down --volumes
~~~

---

## 12. Jaeger UI 怎么使用

### 12.1 Search 页面

常用查询条件：

| 条件 | 用途 |
|---|---|
| Service | 选择服务，通常来自 `service.name` |
| Operation | 选择接口或操作名 |
| Tags | 按属性筛选，例如 `error=true` |
| Lookback | 查询最近一段时间 |
| Start/End Time | 指定绝对时间范围 |
| Min Duration | 查找慢请求 |
| Max Duration | 排除异常长任务 |
| Limit Results | 限制返回数量 |

常见查询方法：

~~~text
查某个接口错误：
Service = order-service
Operation = POST /orders
Tags = error=true

查 1 秒以上慢请求：
Service = payment-service
Min Duration = 1s
Lookback = 1h
~~~

如果 Service 下拉框为空，优先判断是否真的写入了 Span，不要先怀疑 UI。

### 12.2 Trace 页面

打开一条 Trace 后重点看：

- 总耗时；
- Span 数量；
- Error 标记；
- 最长 Span；
- 父子关系；
- Span 是否串行或并行；
- Tags/Attributes；
- Logs/Events；
- Process/Resource 信息；
- Critical Path。

### 12.3 时间线分析

瀑布图中横条代表 Span 的时间范围。常见形态：

~~~text
父 Span 很长，子 Span 总和很短
→ 可能是应用自身计算、锁等待或未埋点区域

数据库 Span 很长
→ 检查慢 SQL、连接池、锁和数据库负载

多个下游 Span 首尾相接
→ 可能是本可并行的调用被串行执行

多个下游 Span 同时结束于超时点
→ 可能是统一超时、网络或线程池耗尽

客户端 Span 很长，服务端 Span 很短
→ 可能是网络、代理、排队或连接建立耗时
~~~

### 12.4 Compare Traces

当同一接口偶发变慢时，可以比较一条正常 Trace 和一条异常 Trace，观察：

- 新增或缺失了哪些 Span；
- 哪个 Span 耗时变化最大；
- 服务版本、实例、区域是否不同；
- 是否发生重试；
- 数据库语句或第三方接口是否变化。

### 12.5 System Architecture / Dependencies

依赖图用于展示服务调用关系。生产环境通常需要额外的依赖聚合处理，而不是部署完成后立即就有完整历史关系图。

---

## 13. OpenTelemetry 接入原则

推荐所有新应用通过 OpenTelemetry 接入：

~~~text
业务应用
  → OTel API/SDK 或自动探针
  → BatchSpanProcessor
  → OTLP Exporter
  → OTel Collector 或 Jaeger
~~~

必须正确设置：

- `service.name`：服务的稳定名称；
- `service.version`：发布版本；
- `deployment.environment.name`：环境；
- OTLP Endpoint；
- OTLP 协议；
- Propagator；
- Sampling；
- Batch 和超时；
- TLS 与认证。

服务命名建议：

~~~text
order-service
payment-service
inventory-service
~~~

不要使用 Pod 名称作为 `service.name`，Pod/实例标识应放在 `service.instance.id`。

---

## 14. Python 应用接入

### 14.1 安装自动埋点组件

~~~bash
python3 -m venv .venv
source .venv/bin/activate
pip install opentelemetry-distro opentelemetry-exporter-otlp
opentelemetry-bootstrap --action=install
~~~

`opentelemetry-bootstrap` 会根据当前安装的框架和库安装对应 Instrumentation。执行后应检查依赖变化，不要在生产环境中跳过测试。

### 14.2 启动应用

OTLP/HTTP：

~~~bash
export OTEL_SERVICE_NAME='python-api'
export OTEL_RESOURCE_ATTRIBUTES='service.version=1.0.0,deployment.environment.name=test'
export OTEL_EXPORTER_OTLP_ENDPOINT='http://127.0.0.1:4318'
export OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'
export OTEL_TRACES_EXPORTER='otlp'

opentelemetry-instrument python app.py
~~~

OTLP/gRPC：

~~~bash
export OTEL_EXPORTER_OTLP_ENDPOINT='http://127.0.0.1:4317'
export OTEL_EXPORTER_OTLP_PROTOCOL='grpc'
~~~

容器中的 `127.0.0.1` 指向容器自身。如果应用和 Jaeger 在不同容器，应使用 Compose Service 名或 Kubernetes Service DNS，例如：

~~~text
http://jaeger:4318
http://otel-collector.observability.svc.cluster.local:4318
~~~

---

## 15. Java 应用接入

推荐先使用 OpenTelemetry Java Agent，无需大规模修改代码。

~~~bash
java \
  -javaagent:/opt/opentelemetry-javaagent.jar \
  -Dotel.service.name=order-service \
  -Dotel.resource.attributes=service.version=1.0.0,deployment.environment.name=test \
  -Dotel.exporter.otlp.endpoint=http://127.0.0.1:4318 \
  -Dotel.exporter.otlp.protocol=http/protobuf \
  -jar app.jar
~~~

生产环境注意：

- Java Agent 版本必须固定，不要使用无版本的 latest；
- 先在测试环境验证框架和数据库驱动兼容性；
- 检查 Agent 对启动时间、堆内存和吞吐的影响；
- 不要自动采集敏感 HTTP Header 或 SQL 参数；
- 高流量服务必须设置采样策略。

Kubernetes 中常见写法：

~~~yaml
env:
  - name: JAVA_TOOL_OPTIONS
    value: "-javaagent:/otel/opentelemetry-javaagent.jar"
  - name: OTEL_SERVICE_NAME
    value: "order-service"
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://otel-collector.observability.svc:4318"
  - name: OTEL_EXPORTER_OTLP_PROTOCOL
    value: "http/protobuf"
~~~

Agent 文件可以通过基础镜像、Init Container 或 OpenTelemetry Operator 注入。不要在容器启动时临时从公网下载未校验的 Agent。

---

## 16. Node.js 应用接入

安装常用包：

~~~bash
npm install \
  @opentelemetry/api \
  @opentelemetry/sdk-node \
  @opentelemetry/auto-instrumentations-node \
  @opentelemetry/exporter-trace-otlp-proto
~~~

创建 `instrumentation.js`：

~~~javascript
const { NodeSDK } = require('@opentelemetry/sdk-node');
const {
  getNodeAutoInstrumentations,
} = require('@opentelemetry/auto-instrumentations-node');
const {
  OTLPTraceExporter,
} = require('@opentelemetry/exporter-trace-otlp-proto');

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({
    url: process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT ||
      'http://127.0.0.1:4318/v1/traces',
  }),
  instrumentations: [getNodeAutoInstrumentations()],
});

sdk.start();

process.on('SIGTERM', async () => {
  await sdk.shutdown();
  process.exit(0);
});
~~~

在业务模块之前加载：

~~~bash
export OTEL_SERVICE_NAME='node-api'
export OTEL_RESOURCE_ATTRIBUTES='service.version=1.0.0,deployment.environment.name=test'
node --require ./instrumentation.js server.js
~~~

自动埋点应在 Web 框架和数据库客户端被加载前初始化，否则部分模块可能不会被正确 Hook。

---

## 17. Go 应用接入

Go 通常需要显式初始化 Tracer Provider，并使用对应框架的 Instrumentation。

~~~go
package tracing

import (
    "context"
    "fmt"

    "go.opentelemetry.io/otel"
    "go.opentelemetry.io/otel/attribute"
    "go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
    "go.opentelemetry.io/otel/propagation"
    "go.opentelemetry.io/otel/sdk/resource"
    sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

func Init(ctx context.Context, endpoint, serviceName string) (func(context.Context) error, error) {
    exporter, err := otlptracegrpc.New(
        ctx,
        otlptracegrpc.WithEndpoint(endpoint),
        otlptracegrpc.WithInsecure(), // 仅限可信内网或本地测试
    )
    if err != nil {
        return nil, fmt.Errorf("create OTLP exporter: %w", err)
    }

    res, err := resource.New(
        ctx,
        resource.WithAttributes(attribute.String("service.name", serviceName)),
    )
    if err != nil {
        return nil, fmt.Errorf("create resource: %w", err)
    }

    provider := sdktrace.NewTracerProvider(
        sdktrace.WithBatcher(exporter),
        sdktrace.WithResource(res),
        sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.TraceIDRatioBased(0.1))),
    )

    otel.SetTracerProvider(provider)
    otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
        propagation.TraceContext{},
        propagation.Baggage{},
    ))

    return provider.Shutdown, nil
}
~~~

调用端点示例：

~~~text
jaeger:4317
otel-collector.observability.svc:4317
~~~

示例中的语义约定包版本需要与实际 OpenTelemetry Go 依赖对齐。升级 OTel 依赖后应运行测试和 `go mod tidy`。

---

## 18. 为什么推荐在 Jaeger 前部署 OTel Collector

应用可以直接向 Jaeger 发送 OTLP，但生产环境通常增加 OpenTelemetry Collector：

- 为应用提供稳定的接收地址；
- 批处理并减少网络请求；
- 限制内存；
- 增加资源属性；
- 删除敏感字段；
- 执行 Tail Sampling；
- 同时导出到 Jaeger 和其他后端；
- 在后端迁移时减少应用改动；
- 暂时吸收后端抖动。

### 18.1 基础 Collector 配置

~~~yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
    spike_limit_mib: 128
  batch:
    timeout: 5s
    send_batch_size: 8192

exporters:
  otlp/jaeger:
    endpoint: jaeger:4317
    tls:
      insecure: true

extensions:
  health_check:
    endpoint: 0.0.0.0:13133

service:
  extensions: [health_check]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/jaeger]
~~~

`tls.insecure: true` 只适合本地或受控测试网络。跨主机、跨集群或不可信网络应配置 TLS/mTLS。

### 18.2 推荐拓扑

~~~text
每节点或 Sidecar Collector
  → 就近接收，减少应用网络依赖

Gateway Collector
  → 统一处理、Tail Sampling、认证和后端路由

Jaeger
  → 存储、查询和展示
~~~

Collector 本身不是无限队列。后端长时间不可用时，如果没有持久队列或 Kafka，数据仍可能丢失。

---

## 19. Jaeger v2 配置文件结构

Jaeger v2 使用与 OpenTelemetry Collector 相同风格的 YAML：

~~~yaml
receivers:
processors:
exporters:
connectors:
extensions:
service:
  extensions:
  pipelines:
~~~

最小内存存储示意：

~~~yaml
service:
  extensions: [jaeger_storage, jaeger_query]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]

extensions:
  jaeger_query:
    storage:
      traces: trace_store
    grpc:
      endpoint: 0.0.0.0:16685
    http:
      endpoint: 0.0.0.0:16686

  jaeger_storage:
    backends:
      trace_store:
        memory:
          max_traces: 100000

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:

exporters:
  jaeger_storage_exporter:
    trace_storage: trace_store
~~~

启动：

~~~bash
docker run --rm --name jaeger \
  -p 127.0.0.1:16686:16686 \
  -p 127.0.0.1:4317:4317 \
  -p 127.0.0.1:4318:4318 \
  -v "$PWD/jaeger.yaml:/jaeger/config.yaml:ro" \
  cr.jaegertracing.io/jaegertracing/jaeger:2.20.0 \
  --config /jaeger/config.yaml
~~~

v2 不再像 v1 那样主要依靠一组 Jaeger 专属环境变量。需要动态值时，可在 YAML 中引用：

~~~yaml
endpoint: "${env:JAEGER_LISTEN_HOST:-0.0.0.0}:4317"
~~~

也可以通过 `--set` 覆盖特定字段，但生产环境应尽量保留一份可评审的完整配置。

---

## 20. 存储后端怎么选择

| 存储 | 适用场景 | 主要限制 |
|---|---|---|
| Memory | Demo、单元测试 | 重启丢失，不能持久化 |
| Badger | 小规模单机 | 单实例，不能水平扩展 |
| OpenSearch | 推荐的生产检索存储 | 资源和索引运维成本较高 |
| Elasticsearch | 常见生产选择 | 需要处理版本、许可和索引生命周期 |
| Cassandra | 已有 Cassandra 能力的场景 | 查询和索引体验通常不如搜索引擎 |
| Kafka | 中间缓冲，不是最终 Trace 存储 | 增加组件和运维复杂度 |
| Remote Storage | 自定义或第三方后端 | 兼容性和维护责任需单独评估 |

Jaeger 官方当前建议大规模生产优先考虑 OpenSearch，而不是 Cassandra。

容量规划至少考虑：

~~~text
每日 Span 数
× 每个 Span 平均存储大小
× 保留天数
× 索引和副本放大系数
× 安全余量
~~~

实际大小与 Attribute 数量、事件、索引策略、压缩和存储实现有关，必须通过真实流量测量。

---

## 21. OpenSearch 配置示例

下面展示 Jaeger v2 的关键结构，凭据应从 Secret 或环境变量注入：

~~~yaml
service:
  extensions: [jaeger_storage, jaeger_query, healthcheckv2]
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [jaeger_storage_exporter]
  telemetry:
    metrics:
      level: detailed
      readers:
        - pull:
            exporter:
              prometheus:
                host: 0.0.0.0
                port: 8888

extensions:
  healthcheckv2:
    use_v2: true
    http:
      endpoint: 0.0.0.0:13133

  jaeger_query:
    storage:
      traces: primary_store
    grpc:
      endpoint: 0.0.0.0:16685
    http:
      endpoint: 0.0.0.0:16686

  jaeger_storage:
    backends:
      primary_store:
        opensearch:
          server_urls:
            - https://opensearch.example.internal:9200
          auth:
            basic:
              username: "${env:OPENSEARCH_USERNAME}"
              password: "${env:OPENSEARCH_PASSWORD}"
          indices:
            index_prefix: jaeger-main
            spans:
              date_layout: "2006-01-02"
              rollover_frequency: day
              shards: 3
              replicas: 1

receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:

exporters:
  jaeger_storage_exporter:
    trace_storage: primary_store
~~~

注意：

- `opensearch`、`elasticsearch` 的字段应以目标 Jaeger 版本示例为准；
- 不要把真实密码写入 Git；
- TLS 证书校验不应为了省事而关闭；
- 分片数不是越多越好，小索引配大量分片会浪费资源；
- 保留策略应通过 OpenSearch ISM 或对应索引生命周期方案实现；
- 升级 Jaeger 前检查存储 Schema 和 Release Notes。

---

## 22. Kubernetes 使用 Helm 部署

Jaeger v2 可以通过 OpenTelemetry Operator 管理，也有 Jaeger Helm Chart。当前官方 Chart 仍标注为实验性，升级前必须审查变更。

### 22.1 添加仓库

~~~bash
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo update
helm search repo jaegertracing/jaeger --versions | head
~~~

### 22.2 测试部署

~~~bash
kubectl create namespace observability

helm upgrade --install jaeger jaegertracing/jaeger \
  --namespace observability \
  --version 4.12.0
~~~

该默认方式使用内存存储，仅适合测试。安装后验证：

~~~bash
kubectl -n observability get deploy,pod,svc
kubectl -n observability get events --sort-by=.lastTimestamp | tail -30
kubectl -n observability logs deploy/jaeger --tail=100
~~~

Chart 资源名称可能随版本或 Release Name 改变，先用 `kubectl get` 确认实际名称。

### 22.3 本地访问 UI

~~~bash
kubectl -n observability port-forward svc/jaeger 16686:16686
~~~

打开：

~~~text
http://127.0.0.1:16686
~~~

如果 Service 名不同：

~~~bash
kubectl -n observability get svc
~~~

### 22.4 应用写入地址

同一命名空间：

~~~text
http://jaeger:4318
jaeger:4317
~~~

跨命名空间：

~~~text
http://jaeger.observability.svc.cluster.local:4318
jaeger.observability.svc.cluster.local:4317
~~~

### 22.5 生产 values 需要具备

- 固定 Chart 和镜像版本；
- 外部 OpenSearch/Elasticsearch；
- Secret 注入凭据；
- `resources.requests` 和 `limits`；
- 多副本与反亲和；
- PodDisruptionBudget；
- NetworkPolicy；
- TLS/mTLS；
- Ingress/OIDC 或 OAuth Proxy；
- Prometheus ServiceMonitor；
- 存储保留策略；
- 升级和回滚方案。

安装前先渲染检查：

~~~bash
helm show values jaegertracing/jaeger --version 4.12.0 > values-reference.yaml

helm template jaeger jaegertracing/jaeger \
  --namespace observability \
  --version 4.12.0 \
  --values values.yaml > rendered.yaml

kubectl apply --dry-run=server -f rendered.yaml
~~~

不要直接把文档中的示例当成完整生产 values。Chart 字段会变化，应以固定版本的 `helm show values` 为准。

---

## 23. 采样策略

全量 Trace 的成本通常不可接受。采样分为 Head Sampling 和 Tail Sampling。

### 23.1 Head Sampling

在请求开始时决定是否采样。

优点：

- 简单；
- 成本低；
- 未采样请求不会产生完整导出开销。

缺点：

- 决策时还不知道请求是否失败或最终耗时；
- 低概率错误可能被丢掉。

Parent Based + 10% 示例：

~~~text
parentbased_traceidratio = 0.1
~~~

### 23.2 Tail Sampling

先收集完整 Trace，等待一段时间，再根据最终结果决定是否保留。

常见规则：

- 错误 Trace 全保留；
- 超过 1 秒的慢 Trace 全保留；
- 指定关键接口全保留；
- 其他正常请求按比例保留。

Tail Sampling 通常在 OTel Collector Gateway 完成，需要：

- 同一 Trace 的 Span 被路由到同一采样实例；
- 足够内存缓存等待中的 Trace；
- 合理的 decision wait；
- 对延迟到达 Span 的处理；
- 监控被丢弃和超时的 Trace。

### 23.3 采样建议

~~~text
开发环境：可以 100%
测试环境：按流量 10%～100%
生产环境：基于流量、成本和故障要求确定
错误与关键交易：优先保留
健康检查：通常不采样
~~~

采样率不能只按环境固定。一个每秒 5 次请求的服务和每秒 5 万次请求的服务，不应机械使用相同比例。

---

## 24. Trace、Metrics、Logs 关联

### 24.1 日志写入 Trace ID

推荐结构化日志：

~~~json
{
  "timestamp": "2026-08-21T10:00:00+08:00",
  "level": "ERROR",
  "service": "payment-service",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "message": "payment provider timeout"
}
~~~

这样可以：

~~~text
日志平台找到错误
  → 复制 trace_id
  → Jaeger 查询完整调用链

Jaeger 找到异常 Span
  → 使用 trace_id、服务名和时间范围
  → 跳转日志平台查看上下文
~~~

### 24.2 Metrics 到 Trace

Prometheus 告警先指出“哪个服务、哪个接口、什么时间发生异常”，再用 Jaeger 查那个时间范围的错误或慢 Trace。

支持 Exemplars 时，可以让直方图样本携带 Trace ID，从 Grafana 指标直接跳到 Trace。

### 24.3 与现有 Tempo 的关系

Jaeger 和 Grafana Tempo 都是 Trace 后端：

| 对比 | Jaeger | Tempo |
|---|---|---|
| UI | 自带 Jaeger UI | 通常使用 Grafana |
| 存储 | OpenSearch、Elasticsearch、Cassandra 等 | 主要使用对象存储 |
| 搜索 | 依赖后端索引，标签查询成熟 | 依赖 TraceQL 和对象存储架构 |
| 生态 | Jaeger Query/API、经典追踪体验 | 与 Grafana Metrics/Logs 联动紧密 |
| 接入 | 推荐 OTLP | 推荐 OTLP |

已有 Tempo 时不一定需要再部署 Jaeger。可以先阅读 [[Tempo-OpenTelemetry-SeaweedFS-Grafana分布式追踪]]，根据查询需求、存储成本和 Grafana 体系选择一种主后端。

---

## 25. Service Performance Monitoring

Jaeger 的 SPM 用 Trace 生成类似 RED 的服务指标：

- Request Rate；
- Error Rate；
- Duration；
- 服务依赖关系。

常见方案：

~~~text
OTel Collector Span Metrics Connector
  → Prometheus
  → Jaeger Monitor 页面
~~~

或者使用支持相应 Metrics Store 能力的 Elasticsearch/OpenSearch 配置。

SPM 不能替代业务原生指标：

- Trace 已采样，计算出的请求量可能不是原始全量；
- 高基数属性会增加成本；
- 指标时效性受 Collector 和存储影响；
- 告警仍应优先使用经过验证的 Prometheus 指标。

---

## 26. 安全设计

### 26.1 入口分区

~~~text
应用网络
  → OTLP Receiver 4317/4318

运维访问网络
  → Jaeger UI 16686

监控网络
  → Metrics 8888、Health 13133
~~~

这些入口不应全部暴露到同一公网 LoadBalancer。

### 26.2 TLS 与认证

应保护：

- SDK/Collector 到 Jaeger；
- Jaeger 到 OpenSearch/Elasticsearch；
- 浏览器到 Jaeger UI；
- Query API；
- Kafka 链路；
- Metrics 和管理端点。

Jaeger UI 常放在 Ingress、OAuth Proxy、OIDC Proxy 或企业统一网关后。仅配置 HTTPS 不能替代身份认证和授权。

### 26.3 敏感数据

不要采集：

- `Authorization`；
- Cookie；
- 密码和 Token；
- 完整身份证号、手机号、银行卡号；
- SQL 参数中的敏感值；
- 请求/响应完整 Body；
- 内部密钥和连接串。

应在 SDK 或 Collector 中建立属性白名单/删除规则，而不是只依赖使用者“不去搜索”。Trace 数据同样属于需要保护的生产数据。

### 26.4 最小权限

- Jaeger 到存储使用专用账号；
- 账号只允许访问 Jaeger 索引；
- Kubernetes 使用专用 ServiceAccount；
- Secret 不进入 ConfigMap、Git 和日志；
- UI 用户只获得所需访问权限；
- 管理端口限制来源地址。

---

## 27. 监控 Jaeger 自身

Jaeger v2 基于 OTel Collector，重点指标包括：

~~~text
otelcol_receiver_accepted_spans
otelcol_receiver_refused_spans
otelcol_exporter_sent_spans
otelcol_exporter_send_failed_spans
~~~

正常情况下，接收和成功写出的 Span 数应大致接近。需要告警的情况：

- `refused_spans` 持续增加；
- `send_failed_spans` 持续增加；
- Receiver 接收量突然为零；
- Collector 内存接近限制；
- Exporter Queue 长时间积压；
- Query P95/P99 延迟上升；
- OpenSearch 写入拒绝或磁盘水位过高；
- Kafka Consumer Lag 持续增加；
- Pod 重启或 OOMKilled；
- Trace 搜索结果明显断层。

Prometheus 抓取示例：

~~~yaml
scrape_configs:
  - job_name: jaeger-v2
    static_configs:
      - targets:
          - jaeger:8888
    scrape_interval: 15s
    metrics_path: /metrics
~~~

验证：

~~~bash
curl -sS http://jaeger:8888/metrics | head
curl -sS http://jaeger:13133/status
~~~

管理端口是否启用、健康路径是什么，由当前 v2 配置决定。

---

## 28. 容量与保留策略

### 28.1 需要收集的数据

上线前至少记录：

- 每秒请求数；
- 平均每条 Trace 的 Span 数；
- Head/Tail Sampling 后的 Span/s；
- 每个 Span 平均序列化大小；
- 峰值倍率；
- 保留天数；
- 查询并发；
- 标签基数；
- 副本数；
- 压缩率。

### 28.2 粗略估算

~~~text
每日原始容量
= Span/s × 平均 Span 字节数 × 86400

实际磁盘预算
= 每日原始容量 × 保留天数 × 索引/副本系数 × 安全余量
~~~

这只是初步估算。最终容量应以试运行期间 OpenSearch 实际索引增长为准。

### 28.3 降低成本的方法

- 调整采样；
- 不采集健康检查；
- 删除无用和高基数属性；
- 缩短普通 Trace 保留期；
- 对重要 Trace 使用归档存储；
- 合理设计索引和分片；
- 修复异常重试造成的 Span 风暴；
- 给 SDK 和 Collector 设置批处理。

---

## 29. 常见故障排查

### 29.1 UI 打不开

检查：

~~~bash
docker ps --filter name=jaeger
docker logs --tail 200 jaeger
ss -lntp | grep ':16686'
curl -v http://127.0.0.1:16686/
~~~

Kubernetes：

~~~bash
kubectl -n observability get pod,svc,endpoints
export JAEGER_POD='替换为实际 Pod 名称'
kubectl -n observability describe pod "$JAEGER_POD"
kubectl -n observability logs "$JAEGER_POD" --tail=200
~~~

### 29.2 UI 能打开但 Service 为空

按数据路径检查：

1. 应用是否真的初始化 OTel；
2. `OTEL_TRACES_EXPORTER` 是否为 `otlp`；
3. Endpoint 是否指向正确主机；
4. HTTP/gRPC 协议是否与端口匹配；
5. 容器内是否错误使用 `127.0.0.1`；
6. SDK 是否因为采样没有导出；
7. Collector 是否接收到 Span；
8. Exporter 是否写入失败；
9. Jaeger 是否能连接存储；
10. 查询时间范围是否覆盖 Trace 产生时间。

### 29.3 `connection refused`

~~~bash
nc -vz jaeger 4317
curl -v http://jaeger:4318/
getent hosts jaeger
~~~

`4318/` 返回 404 不一定代表端口不可用，OTLP/HTTP 真正写入路径是 `/v1/traces`。重点确认 TCP、DNS 和 Collector 日志。

### 29.4 gRPC 与 HTTP 配错

常见错误：

~~~text
Exporter 使用 grpc，但 Endpoint 指向 4318
Exporter 使用 http/protobuf，但 Endpoint 指向 4317
HTTP Exporter 已自动拼接 /v1/traces，却又手工重复路径
~~~

标准对应：

~~~text
OTLP/gRPC      → 4317
OTLP/HTTP      → 4318，Trace 路径 /v1/traces
~~~

### 29.5 有 Trace 但调用链断裂

检查：

- HTTP/gRPC/MQ Instrumentation 是否启用；
- 上游是否注入 `traceparent`；
- 下游是否提取；
- 是否同时使用不兼容的 Propagator；
- 消息消费端是否正确建立 Link 或 Parent；
- 是否有服务重新创建 Root Span；
- 采样决策是否正确继承。

### 29.6 服务名显示为 unknown_service

说明 `service.name` 未正确设置。修复 OTel Resource：

~~~bash
export OTEL_SERVICE_NAME='order-service'
~~~

### 29.7 时间线出现异常重叠

可能原因：

- 主机时钟偏差；
- NTP/Chrony 异常；
- SDK 时间来源问题；
- Jaeger UI 应用了 Clock Skew Adjustment。

检查：

~~~bash
timedatectl status
chronyc tracking
chronyc sources -v
~~~

### 29.8 Trace 写入成功但查不到

检查：

- 查询时间范围；
- 时区；
- Service 和 Operation 条件；
- OpenSearch 索引是否创建；
- Jaeger Query 与 Collector 是否使用同一个 backend 名称和存储集群；
- 索引是否已被生命周期规则提前删除；
- 查询账号是否有索引权限。

### 29.9 OpenSearch 写入失败

重点查看：

- TLS 证书；
- Basic/API Key 权限；
- 磁盘高水位；
- 索引只读；
- Mapping 冲突；
- 分片数量；
- 429 写入拒绝；
- Jaeger 与 OpenSearch 版本兼容。

### 29.10 Span 丢失

检查指标：

~~~text
accepted_spans
refused_spans
sent_spans
send_failed_spans
queue_size / queue_capacity
Kafka consumer lag
~~~

再检查：

- SDK 进程退出前是否调用 Shutdown/Flush；
- Batch 超时；
- Collector OOM；
- Tail Sampling 等待时间；
- Load Balancer 是否破坏 Trace 亲和；
- 网络丢包；
- 后端限流。

---

## 30. 从 Jaeger v1 迁移到 v2

建议分阶段：

~~~text
1. 盘点当前 SDK、Agent、端口和存储
2. 应用迁移到 OpenTelemetry SDK/Agent
3. 接入 OTLP，并保留旧接入路径做短期兼容
4. 建立 OTel Collector 层
5. 使用 v2 配置连接现有或新存储
6. 双写或小流量验证查询一致性
7. 迁移 Dashboard、告警、依赖计算和安全入口
8. 切换主要写入路径
9. 观察一个完整保留周期
10. 下线旧 Agent、旧端口和 v1 组件
~~~

迁移时不要直接把 v1 环境变量照搬到 v2。v2 的 receiver、processor、exporter、extension 和 pipeline 需要重新建模。

重点验证：

- Trace ID 是否保持一致；
- Service Name 是否变化；
- 标签字段是否变化；
- 旧 Trace 是否仍可查询；
- 采样率是否意外改变；
- Query API 使用方是否兼容；
- 存储 Schema 是否需要迁移；
- UI 入口和认证是否保持可用。

---

## 31. 生产上线检查清单

### 架构

- [ ] 已确认 Jaeger、Chart、OTel SDK 和 Collector 版本；
- [ ] 未使用 memory 存储承载生产数据；
- [ ] Collector、Query 和存储边界明确；
- [ ] 是否需要 Kafka 有实际容量依据；
- [ ] 有高可用和故障恢复设计。

### 接入

- [ ] 所有服务设置稳定的 `service.name`；
- [ ] W3C Trace Context 能跨 HTTP、gRPC 和 MQ 传播；
- [ ] 容器中没有错误使用 localhost；
- [ ] 采样策略经过压测；
- [ ] 进程退出时能 Flush Span。

### 安全

- [ ] UI 有认证和访问控制；
- [ ] OTLP、存储和跨网络通信启用 TLS/mTLS；
- [ ] Secret 未写入 YAML、Git 和日志；
- [ ] 已过滤敏感 Header、Body 和 SQL 参数；
- [ ] 管理端口没有暴露到公网。

### 存储

- [ ] 已测量每日索引增长；
- [ ] 保留期明确；
- [ ] 分片和副本合理；
- [ ] 磁盘水位有告警；
- [ ] 已验证备份、快照和恢复；
- [ ] 已测试索引生命周期策略。

### 可运维性

- [ ] Prometheus 已采集 Jaeger 指标；
- [ ] 对拒绝和写入失败 Span 配置告警；
- [ ] 有 Query 延迟和存储健康告警；
- [ ] 日志包含版本、实例和错误上下文；
- [ ] 有升级、回滚和兼容性验证流程。

---

## 32. 推荐学习顺序

1. 用 Docker 启动 Jaeger all-in-one；
2. 运行 HotROD 并查看第一条 Trace；
3. 学会按 Service、Operation、Duration 和 Error 查询；
4. 分析父子 Span 和关键路径；
5. 给一个 Python 或 Java 测试服务接入 OTel；
6. 验证 `traceparent` 跨服务传播；
7. 在日志中加入 `trace_id`；
8. 在应用和 Jaeger 之间加入 OTel Collector；
9. 实验 Head Sampling 和 Tail Sampling；
10. 用 Helm 在测试 Kubernetes 集群部署；
11. 接入外部 OpenSearch；
12. 配置 Prometheus 监控和数据丢失告警；
13. 进行一次后端不可用和恢复演练；
14. 最后再设计生产容量、高可用和保留策略。

完成后应能回答：

- Trace 在哪个环节产生；
- 上下文如何跨服务传播；
- 4317 和 4318 分别是什么协议；
- 为什么 UI 为空；
- 哪些 Span 被采样丢弃；
- Jaeger 写入哪个存储；
- 如何从指标或日志跳到具体 Trace；
- 如何判断 Collector 正在丢数据；
- 后端中断后能否恢复以及会丢多少数据。

---

## 33. 常用命令速查

### Docker

~~~bash
docker ps --filter name=jaeger
docker logs -f --tail 100 jaeger
docker inspect jaeger
curl -I http://127.0.0.1:16686/
nc -vz 127.0.0.1 4317
~~~

### Kubernetes

~~~bash
kubectl -n observability get pod,svc,endpoints
kubectl -n observability logs deploy/jaeger --tail=200
kubectl -n observability port-forward svc/jaeger 16686:16686
kubectl -n observability get events --sort-by=.lastTimestamp | tail -30
~~~

### Helm

~~~bash
helm repo update
helm search repo jaegertracing/jaeger --versions
helm -n observability list
helm -n observability get values jaeger --all
helm -n observability get manifest jaeger
helm -n observability history jaeger
~~~

### OTLP 连通性

~~~bash
getent hosts jaeger
nc -vz jaeger 4317
nc -vz jaeger 4318
~~~

### Prometheus 指标

~~~bash
curl -sS http://jaeger:8888/metrics | \
  grep -E 'otelcol_(receiver|exporter)_.*spans'
~~~

---

## 34. Jaeger、Tempo、Zipkin 简要选择

| 场景 | 建议 |
|---|---|
| 想快速使用经典 Trace UI 和标签搜索 | Jaeger |
| 已全面使用 Grafana，重视对象存储和 TraceQL | Tempo |
| 已有 Zipkin 生态或轻量兼容需求 | Zipkin |
| 希望避免后端绑定 | 应用统一使用 OpenTelemetry + OTLP |

最重要的不是先争论后端，而是：

- 统一 OpenTelemetry 接入；
- 正确传播上下文；
- 控制采样和敏感属性；
- 建立 Metrics、Logs、Traces 关联；
- 验证后端容量和故障恢复。

---

## 35. 官方资料

- [Jaeger 官方文档](https://www.jaegertracing.io/docs/)
- [Jaeger 2.20 Getting Started](https://www.jaegertracing.io/docs/2.20/getting-started/)
- [Jaeger v2 Architecture](https://www.jaegertracing.io/docs/2.20/architecture/)
- [Jaeger v2 Deployment](https://www.jaegertracing.io/docs/2.20/deployment/)
- [Jaeger v2 Configuration](https://www.jaegertracing.io/docs/2.20/deployment/configuration/)
- [Jaeger APIs 与端口](https://www.jaegertracing.io/docs/2.20/apis/)
- [Jaeger Storage](https://www.jaegertracing.io/docs/2.20/storage/)
- [Jaeger OpenSearch Storage](https://www.jaegertracing.io/docs/2.20/storage/opensearch/)
- [Jaeger Sampling](https://www.jaegertracing.io/docs/2.20/architecture/sampling/)
- [Jaeger Security](https://www.jaegertracing.io/docs/2.20/deployment/security/)
- [Jaeger Monitoring](https://www.jaegertracing.io/docs/2.20/operations/monitoring/)
- [Jaeger GitHub](https://github.com/jaegertracing/jaeger)
- [Jaeger Releases](https://github.com/jaegertracing/jaeger/releases)
- [Jaeger Helm Charts](https://github.com/jaegertracing/helm-charts)
- [OpenTelemetry 文档](https://opentelemetry.io/docs/)

部署前应以目标版本的官方配置示例、Helm `values.yaml` 和 Release Notes 为准，不要直接套用其他大版本的环境变量或命令。
