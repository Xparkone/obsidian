# Nacos 注册中心与配置中心：从入门到生产实践

> 文档基线：Nacos 3.2.3，核对日期：2026-08-21。Nacos 3.3.0 当前仍为 Beta，本文不把预发布功能作为生产默认方案。

## 1. 先讲结论

Nacos 是一个面向云原生应用的服务发现、配置管理和 AI Registry 平台。传统微服务场景中，它最常被用作：

- 注册中心：记录“某个服务现在有哪些可用实例”；
- 配置中心：集中保存配置，并把变更推送给应用；
- 服务管理平台：管理服务、实例、集群、元数据和健康状态；
- AI Registry：管理 MCP Server、Agent、Skill、Prompt 等 AI 资源。

典型数据流：

~~~text
服务提供者启动
  → 向 Nacos 注册 IP、端口和元数据
  → 保持长连接或心跳

服务消费者
  → 向 Nacos 订阅服务实例列表
  → 从健康实例中选择一个发起调用

应用启动
  → 从 Nacos 读取配置
  → 监听配置变化
  → 收到变更后按应用规则刷新
~~~

生产使用时最重要的边界：

- Nacos 是内部基础设施，不应直接暴露到公网；
- 单机内置数据库只适合学习和测试；
- 生产应使用至少 3 个 Nacos 节点和外部 MySQL；
- Nacos 3.x 控制台默认使用 `8080`，Server API 使用 `8848`；
- 客户端还需要访问 `9848` gRPC 端口，不能只放行 `8848`；
- 从 Nacos 2.4 起不再提供默认管理员密码，首次使用需要初始化；
- Nacos 自带鉴权主要防止内部误用，不能替代网络隔离、TLS 和统一身份系统；
- 动态配置不是“改完一定能无风险生效”，应用必须正确处理刷新和失败回退；
- Nacos 3.2 主发行版已移除旧 v1/v2 HTTP API，新脚本应使用 v3 API 或官方 SDK。

---

## 2. Nacos 是什么

Nacos 名称来自 Dynamic Naming and Configuration Service。核心能力可以拆成三部分。

### 2.1 服务发现

服务提供者向 Nacos 注册：

~~~text
serviceName=order-service
ip=10.10.2.15
port=8080
clusterName=HZ-A
metadata.version=v2
~~~

消费者按服务名获取健康实例：

~~~text
order-service
├── 10.10.2.15:8080
├── 10.10.2.16:8080
└── 10.10.2.17:8080
~~~

实例上下线后，Nacos 会通知订阅者更新本地列表。

### 2.2 配置管理

Nacos 集中管理不同应用、环境和分组的配置：

~~~text
Namespace: production
Group: ORDER_GROUP
Data ID: order-service.yaml
Content:
  payment:
    timeout: 3s
~~~

应用可以读取并监听这份配置，但是否动态刷新 Bean、连接池或线程池，由客户端框架和应用代码决定。

### 2.3 AI Registry

Nacos 3.x 扩展了 AI Registry，用于登记和发现：

- MCP Server；
- A2A Agent；
- Skill；
- Prompt；
- AgentSpec 等 AI 资源。

这部分适合 AI 应用能力目录和运行时发现，不影响传统注册中心、配置中心的基本使用方式。

---

## 3. Nacos 不是什么

### 3.1 不等于 API Gateway

Nacos 告诉消费者“服务实例在哪里”，但通常不直接代理业务流量。认证、限流、路由、WAF 和协议转换通常由 Higress、Spring Cloud Gateway、APISIX、Kong 或其他网关负责。

### 3.2 不等于服务网格

Nacos 有服务发现、权重和元数据能力，但不是完整的流量治理数据面。mTLS、透明代理、细粒度流量路由和服务间访问策略通常由 Istio 等服务网格承担。

### 3.3 不等于数据库

配置中心存储的是配置资源，不适合存储订单、用户和业务状态。

### 3.4 不等于密钥管理系统

Nacos 可以存放配置，但不负责完整的密钥生成、轮换、吊销和审计。数据库密码、私钥和长期 Token 更适合 Vault、云 KMS 或 Kubernetes Secret 等专用系统。

### 3.5 不等于负载均衡器

Nacos 返回可用实例列表。实际选择实例和发起请求，通常由客户端负载均衡器、RPC 框架或网关完成。

---

## 4. 核心概念

### 4.1 Namespace

Namespace 用于隔离环境、租户或业务域。常见设计：

~~~text
dev
test
staging
prod
~~~

控制台显示的 Namespace 名称主要供人阅读，客户端通常配置 Namespace ID。把名称误填成 ID 是常见故障。

### 4.2 Group

Group 是 Namespace 内的二级分组：

~~~text
DEFAULT_GROUP
ORDER_GROUP
PAYMENT_GROUP
PLATFORM_GROUP
~~~

Group 不能替代 Namespace 的环境隔离。生产与测试不应只靠 Group 区分。

### 4.3 Data ID

Data ID 是一份配置的资源名：

~~~text
order-service.yaml
payment-service.properties
shared-datasource.yaml
feature-flags.json
~~~

一份配置的唯一身份：

~~~text
namespaceId → groupName → dataId
~~~

### 4.4 Service

服务发现中的 Service 由以下三部分确定：

~~~text
namespaceId → groupName → serviceName
~~~

### 4.5 Cluster

Cluster 是 Service 下的部署分组，常用于机房、地域或单元：

~~~text
order-service
├── HZ-A
├── HZ-B
└── SH-A
~~~

它不是 Nacos Server 集群本身，两者不要混淆。

### 4.6 Instance

Instance 是实际服务进程或 Pod，常见属性：

- IP；
- Port；
- Cluster Name；
- Weight；
- Healthy；
- Enabled；
- Ephemeral；
- Metadata。

---

## 5. 临时实例与持久实例

Nacos 的服务类型决定实例状态使用的主要一致性路径。

| 类型 | 特点 | 典型场景 |
|---|---|---|
| 临时实例 | 依赖活跃客户端，断连或心跳过期后会被移除 | 普通微服务、Pod |
| 持久实例 | 作为持久资源管理，可从服务端状态恢复 | 固定基础设施、特殊注册资源 |

临时实例主要走偏 AP 的 Distro 状态同步；持久元数据和部分服务端状态使用 Raft 等一致性机制。

不要在同一个 Service 身份下混用临时和持久语义。通过 HTTP OpenAPI 注册临时实例时，还必须周期性续约；真实应用应优先使用 SDK，由 SDK 维护长连接和续约。

---

## 6. 工作流程

### 6.1 服务注册与发现

~~~mermaid
sequenceDiagram
    participant P as Provider
    participant N as Nacos
    participant C as Consumer

    P->>N: 注册 order-service 实例
    P->>N: 长连接/心跳维持状态
    C->>N: 订阅 order-service
    N-->>C: 返回健康实例列表
    C->>P: 调用业务接口
    P--xN: 实例断连
    N-->>C: 推送新的实例列表
~~~

消费者通常会保留本地缓存。因此 Nacos 短时不可用时，已有服务调用不一定立即中断，但新实例、配置和变更可能无法及时获取。

### 6.2 配置读取与推送

~~~mermaid
sequenceDiagram
    participant A as Application
    participant N as Nacos
    participant O as Operator

    A->>N: 读取 namespace/group/dataId
    N-->>A: 返回配置与 MD5
    A->>N: 建立配置监听
    O->>N: 发布新配置
    N-->>A: 通知配置发生变化
    A->>N: 重新获取配置
    A->>A: 刷新允许动态更新的对象
~~~

---

## 7. Nacos 3.x 版本变化

本文使用当前稳定版 `3.2.3`。`3.3.0-BETA` 是预发布版本，不建议直接用于生产。

从旧教程迁移时重点注意：

| 项目 | 旧教程常见内容 | Nacos 3.2.x 当前方式 |
|---|---|---|
| 控制台 | `8848/nacos` | 默认 `8080` |
| Server API | v1/v2 HTTP API | v3 Client/Admin API |
| 管理员密码 | `nacos/nacos` | 首次初始化，无默认密码 |
| 客户端通信 | HTTP、UDP 等旧模式 | gRPC 长连接为主 |
| API 发布配置 | 普通 Client API | 使用 Admin API |
| Spring 配置 | `bootstrap.yml` | 新版本使用 `application.yml` + `spring.config.import` |

Nacos 3.x Java Client 的默认 Namespace ID 从空字符串调整为 `public`。旧 Server、新 Client 和默认 Namespace 混用时，需要单独验证兼容性。

Nacos 3.2 主发行版已移除旧 v1/v2 HTTP API。升级前必须盘点脚本、探针、网关和应用是否仍调用旧路径。

---

## 8. 端口说明

默认端口关系：

| 端口 | 相对 8848 | 用途 |
|---|---:|---|
| `8848` | `0` | Nacos Server HTTP API、登录等请求 |
| `9848` | `+1000` | 客户端 gRPC 长连接 |
| `9849` | `+1001` | Nacos Server 间 gRPC 通信 |
| `7848` | `-1000` | JRaft Server 间通信 |
| `8080` | 独立配置 | Nacos 3.x Console |

客户端通常只配置：

~~~text
nacos.internal.example:8848
~~~

客户端会按照端口偏移计算 `9848`。因此负载均衡、防火墙和端口映射必须同时正确处理。

生产网络建议：

~~~text
应用网络 → VIP:8848、VIP:9848
运维网络 → Console:8080
Nacos 节点之间 → 7848、8848、9848、9849
监控系统 → 8848 上的 Actuator 路径
~~~

`9848` 必须使用四层 TCP 转发，不要按普通 HTTP/HTTP2 反向代理，否则长连接可能被代理错误处理。

不要把任何 Nacos 端口暴露到公网。

---

## 9. Docker 单机快速体验

### 9.1 准备目录

~~~bash
sudo mkdir -p /opt/nacos-standalone/{data,logs,conf}
sudo chown -R "$(id -u):$(id -g)" /opt/nacos-standalone
cd /opt/nacos-standalone
~~~

### 9.2 生成鉴权材料

JWT Secret 必须是至少 32 个原始字符经过 Base64 编码后的值：

~~~bash
openssl rand -base64 48 | tr -d '\n'
printf '\n'
openssl rand -hex 16
openssl rand -hex 24
~~~

把三个结果分别保存为：

~~~text
NACOS_AUTH_TOKEN
NACOS_AUTH_IDENTITY_KEY
NACOS_AUTH_IDENTITY_VALUE
~~~

不要直接复用文档或网上示例值，否则任意知道该值的人都可能伪造身份或 Token。

### 9.3 `.env`

~~~dotenv
NACOS_VERSION=v3.2.3
NACOS_AUTH_TOKEN=替换为Base64密钥
NACOS_AUTH_IDENTITY_KEY=替换为随机IdentityKey
NACOS_AUTH_IDENTITY_VALUE=替换为随机IdentityValue
~~~

限制权限：

~~~bash
chmod 600 .env
~~~

不要把 `.env` 提交到 Git。

### 9.4 `docker-compose.yml`

~~~yaml
services:
  nacos:
    image: nacos/nacos-server:${NACOS_VERSION:-v3.2.3}
    container_name: nacos-standalone
    restart: unless-stopped
    environment:
      MODE: standalone
      PREFER_HOST_MODE: hostname
      NACOS_AUTH_ENABLE: "true"
      NACOS_AUTH_ADMIN_ENABLE: "true"
      NACOS_AUTH_CONSOLE_ENABLE: "true"
      NACOS_AUTH_SYSTEM_TYPE: nacos
      NACOS_AUTH_TOKEN: ${NACOS_AUTH_TOKEN:?NACOS_AUTH_TOKEN is required}
      NACOS_AUTH_IDENTITY_KEY: ${NACOS_AUTH_IDENTITY_KEY:?NACOS_AUTH_IDENTITY_KEY is required}
      NACOS_AUTH_IDENTITY_VALUE: ${NACOS_AUTH_IDENTITY_VALUE:?NACOS_AUTH_IDENTITY_VALUE is required}
    volumes:
      - ./data:/home/nacos/data
      - ./logs:/home/nacos/logs
    ports:
      - "127.0.0.1:8080:8080"
      - "127.0.0.1:8848:8848"
      - "127.0.0.1:9848:9848"
    security_opt:
      - no-new-privileges:true
~~~

启动：

~~~bash
docker compose config
docker compose up -d
docker compose ps
docker compose logs --tail 200 nacos
~~~

如果日志出现数据目录无写权限，应先通过 `docker inspect` 确认镜像运行用户，再把宿主机目录属主调整为对应 UID/GID。不要用 `chmod -R 777` 掩盖权限问题。Apple Silicon 等 ARM 环境还应确认目标版本是否需要使用带 `-slim` 后缀的镜像。

### 9.5 验证端口

~~~bash
ss -lntp | grep -E ':(8080|8848|9848)\b'
curl -fsS http://127.0.0.1:8848/nacos/v3/admin/core/state/liveness
curl -fsS http://127.0.0.1:8848/nacos/v3/admin/core/state/readiness
~~~

Console：

~~~text
http://127.0.0.1:8080/
~~~

第一次访问时会要求初始化管理员用户 `nacos` 的密码。Nacos 2.4 以后不再提供默认的 `nacos/nacos` 密码。

单机内置存储只适合学习和测试，不具备生产高可用。

---

## 10. 初始化管理员密码

推荐通过 Console 完成首次初始化。也可以调用 API：

~~~bash
export NACOS_SERVER='http://127.0.0.1:8848'
export NACOS_ADMIN_PASSWORD='替换为高强度密码'

curl --fail-with-body \
  --request POST \
  "${NACOS_SERVER}/nacos/v3/auth/user/admin" \
  --data-urlencode "password=${NACOS_ADMIN_PASSWORD}"
~~~

该初始化接口成功后不能重复用于重置密码。密码应进入密码管理器或 Secret 系统，不能写入脚本和 Git。

登录获取 Access Token：

~~~bash
export NACOS_USERNAME='nacos'

export NACOS_ACCESS_TOKEN="$({
  curl --fail-with-body --silent \
    --request POST \
    "${NACOS_SERVER}/nacos/v3/auth/user/login" \
    --data-urlencode "username=${NACOS_USERNAME}" \
    --data-urlencode "password=${NACOS_ADMIN_PASSWORD}"
} | jq -r '.accessToken')"

test -n "$NACOS_ACCESS_TOKEN"
test "$NACOS_ACCESS_TOKEN" != "null"
~~~

Access Token 有有效期。自动化程序应使用专用账号并处理 Token 更新，不要长期使用管理员账号。

---

## 11. Console 基本使用

### 11.1 Namespace

操作路径通常为：

~~~text
命名空间 / Namespaces
  → 新建命名空间
~~~

建议创建：

| 名称 | ID 示例 | 用途 |
|---|---|---|
| development | `dev` 或生成的 UUID | 开发 |
| testing | `test` 或生成的 UUID | 测试 |
| production | `prod` 或生成的 UUID | 生产 |

如果平台自动生成 Namespace ID，应把实际 ID 记录到部署参数，不要只记录显示名称。

### 11.2 配置列表

进入：

~~~text
配置管理
  → 配置列表
  → 选择 Namespace
  → 新建配置
~~~

示例：

| 字段 | 值 |
|---|---|
| Data ID | `order-service.yaml` |
| Group | `ORDER_GROUP` |
| 配置格式 | YAML |

内容：

~~~yaml
order:
  payment-timeout: 3s
  max-items: 100
feature:
  new-checkout: false
~~~

发布前使用“配置校验”或本地 YAML 工具检查格式。

### 11.3 服务列表

进入：

~~~text
服务管理
  → 服务列表
  → 选择 Namespace
~~~

可以查看：

- 服务名；
- Group；
- Cluster；
- 实例 IP 和端口；
- 健康状态；
- 权重；
- 元数据；
- 订阅者。

不要仅凭 Console 中“有实例”就判断服务可用，还要验证实例业务健康接口和真实调用。

---

## 12. 使用 v3 OpenAPI 操作配置

Nacos 3.x 把普通客户端和管理操作分开：

- Client API：应用读取配置、注册实例、查询已知服务；
- Admin API：发布、删除、搜索和管理资源；
- Console API：供 Console 使用，不建议业务脚本依赖。

### 12.1 发布配置

~~~bash
export NACOS_NAMESPACE='dev'
export NACOS_GROUP='ORDER_GROUP'
export NACOS_DATA_ID='order-service.yaml'

curl --fail-with-body \
  --request POST \
  "${NACOS_SERVER}/nacos/v3/admin/cs/config" \
  --header "accessToken: ${NACOS_ACCESS_TOKEN}" \
  --data-urlencode "namespaceId=${NACOS_NAMESPACE}" \
  --data-urlencode "groupName=${NACOS_GROUP}" \
  --data-urlencode "dataId=${NACOS_DATA_ID}" \
  --data-urlencode $'content=order:\n  payment-timeout: 3s\n  max-items: 100'
~~~

真实配置较长时，不建议直接拼接 Shell 参数。应使用经过审查的发布工具、SDK 或 GitOps 流程，并避免秘密出现在进程参数和 Shell History 中。

### 12.2 获取配置

~~~bash
curl --fail-with-body \
  --get \
  "${NACOS_SERVER}/nacos/v3/client/cs/config" \
  --header "accessToken: ${NACOS_ACCESS_TOKEN}" \
  --data-urlencode "namespaceId=${NACOS_NAMESPACE}" \
  --data-urlencode "groupName=${NACOS_GROUP}" \
  --data-urlencode "dataId=${NACOS_DATA_ID}"
~~~

开启客户端鉴权后，应按目标 API 要求携带认证信息。脚本不要假设 Admin Token 可以永久使用。

### 12.3 API 设计变化

Nacos 3.x Client HTTP API 不提供发布、删除配置和全量枚举服务等控制面操作。普通应用只应消费自己已知的配置和下游服务，不应拥有平台级管理权限。

---

## 13. 使用 v3 OpenAPI 注册和发现服务

### 13.1 注册测试实例

~~~bash
export SERVICE_NAME='quickstart.order-service'
export INSTANCE_IP='127.0.0.1'
export INSTANCE_PORT='18080'

curl --fail-with-body \
  --request POST \
  "${NACOS_SERVER}/nacos/v3/client/ns/instance" \
  --header "accessToken: ${NACOS_ACCESS_TOKEN}" \
  --data-urlencode "serviceName=${SERVICE_NAME}" \
  --data-urlencode "ip=${INSTANCE_IP}" \
  --data-urlencode "port=${INSTANCE_PORT}"
~~~

### 13.2 查询实例

~~~bash
curl --fail-with-body \
  --get \
  "${NACOS_SERVER}/nacos/v3/client/ns/instance/list" \
  --header "accessToken: ${NACOS_ACCESS_TOKEN}" \
  --data-urlencode "serviceName=${SERVICE_NAME}"
~~~

### 13.3 重要限制

通过 HTTP 注册的临时实例需要定期续约。Nacos 3.x 把注册和续约合并在相关接口语义中，并通过请求参数区分。

生产应用不要使用一次 `curl` 代替 SDK：

- `curl` 不会自动维护长连接；
- 不会自动续约；
- 不会订阅实例变更；
- 不会正确管理本地缓存；
- 进程退出时不会自动注销。

---

## 14. Java SDK 使用

### 14.1 依赖

~~~xml
<dependency>
  <groupId>com.alibaba.nacos</groupId>
  <artifactId>nacos-client</artifactId>
  <version>${nacos.client.version}</version>
</dependency>
~~~

客户端版本要根据 Nacos Server、JDK 和框架兼容矩阵选择，不要机械使用 Server 相同版本号。

### 14.2 初始化

~~~java
import com.alibaba.nacos.api.NacosFactory;
import com.alibaba.nacos.api.PropertyKeyConst;
import com.alibaba.nacos.api.config.ConfigService;
import com.alibaba.nacos.api.naming.NamingService;

import java.util.Properties;

Properties properties = new Properties();
properties.setProperty(PropertyKeyConst.SERVER_ADDR, "nacos.internal.example:8848");
properties.setProperty(PropertyKeyConst.NAMESPACE, "dev");
properties.setProperty(PropertyKeyConst.USERNAME, System.getenv("NACOS_USERNAME"));
properties.setProperty(PropertyKeyConst.PASSWORD, System.getenv("NACOS_PASSWORD"));

ConfigService configService = NacosFactory.createConfigService(properties);
NamingService namingService = NacosFactory.createNamingService(properties);
~~~

一个 SDK 实例只能访问它所配置 Namespace 下的配置和服务。跨 Namespace 应创建不同客户端，不要在请求之间动态修改同一个客户端的 Namespace。

### 14.3 获取配置

~~~java
String dataId = "order-service.yaml";
String group = "ORDER_GROUP";
String content = configService.getConfig(dataId, group, 3000L);
System.out.println(content);
~~~

### 14.4 监听配置

~~~java
import com.alibaba.nacos.api.config.listener.Listener;

import java.util.concurrent.Executor;

configService.addListener(dataId, group, new Listener() {
    @Override
    public Executor getExecutor() {
        return null;
    }

    @Override
    public void receiveConfigInfo(String configInfo) {
        System.out.println("config changed: " + configInfo);
        // 应先校验、解析，再原子替换运行时配置。
    }
});
~~~

监听回调中不要执行长时间阻塞操作。复杂变更应交给独立线程池，并保留上一个有效配置。

### 14.5 注册实例

~~~java
namingService.registerInstance(
    "order-service",
    "ORDER_GROUP",
    "10.10.2.15",
    8080,
    "HZ-A"
);
~~~

### 14.6 获取健康实例

~~~java
var instances = namingService.selectInstances(
    "order-service",
    "ORDER_GROUP",
    true
);

instances.forEach(instance ->
    System.out.printf("%s:%d%n", instance.getIp(), instance.getPort())
);
~~~

应用关闭时应正常关闭 SDK，让实例尽快注销并 Flush 本地状态。

---

## 15. Spring Cloud Alibaba 接入

### 15.1 先确定版本组合

Spring Cloud Alibaba、Spring Cloud、Spring Boot、JDK 和 Nacos Client 必须使用兼容组合。

当前官方示例关系包括：

| Spring Cloud Alibaba | Spring Cloud | Spring Boot | 组件基线中的 Nacos |
|---|---|---|---|
| `2025.0.0.0` | `2025.0.0` | `3.5.x` | `3.0.3` |
| `2025.1.0.0` | `2025.1.0` | `4.0.x` | `3.1.1` |

表格表示官方 BOM 的组件组合，不代表 Nacos Server 必须使用完全相同的补丁版本。实际升级仍需验证兼容矩阵和 Release Notes。

### 15.2 BOM

~~~xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.alibaba.cloud</groupId>
      <artifactId>spring-cloud-alibaba-dependencies</artifactId>
      <version>${spring-cloud-alibaba.version}</version>
      <type>pom</type>
      <scope>import</scope>
    </dependency>
  </dependencies>
</dependencyManagement>
~~~

### 15.3 Starter

~~~xml
<dependencies>
  <dependency>
    <groupId>com.alibaba.cloud</groupId>
    <artifactId>spring-cloud-starter-alibaba-nacos-config</artifactId>
  </dependency>
  <dependency>
    <groupId>com.alibaba.cloud</groupId>
    <artifactId>spring-cloud-starter-alibaba-nacos-discovery</artifactId>
  </dependency>
</dependencies>
~~~

### 15.4 `application.yml`

~~~yaml
server:
  port: 8081

spring:
  application:
    name: order-service

  cloud:
    nacos:
      server-addr: ${NACOS_SERVER_ADDR:127.0.0.1:8848}
      username: ${NACOS_USERNAME}
      password: ${NACOS_PASSWORD}

      config:
        namespace: ${NACOS_NAMESPACE:dev}
        group: ORDER_GROUP

      discovery:
        namespace: ${NACOS_NAMESPACE:dev}
        group: ORDER_GROUP
        cluster-name: HZ-A
        metadata:
          version: v1

  config:
    import:
      - optional:nacos:order-service.yaml?group=ORDER_GROUP&refreshEnabled=true
~~~

`optional:` 表示 Nacos 配置不可用时，应用仍可能使用本地配置启动。关键配置是否允许降级启动，应按业务要求决定；不要为了避免启动失败无条件加 `optional:`。

从 Spring Cloud Alibaba 2025.1.x 起，不再支持 `bootstrap.yml` / `bootstrap.properties` 接入方式，应使用 `application.yml` 和 `spring.config.import`。

### 15.5 启动类

~~~java
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.cloud.client.discovery.EnableDiscoveryClient;

@SpringBootApplication
@EnableDiscoveryClient
public class OrderApplication {
    public static void main(String[] args) {
        SpringApplication.run(OrderApplication.class, args);
    }
}
~~~

部分新版本可通过自动配置完成发现客户端注册，`@EnableDiscoveryClient` 是否必需以当前 Spring Cloud 版本为准。

### 15.6 动态刷新

~~~java
import org.springframework.beans.factory.annotation.Value;
import org.springframework.cloud.context.config.annotation.RefreshScope;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RefreshScope
@RestController
public class ConfigController {
    @Value("${order.payment-timeout:3s}")
    private String paymentTimeout;

    @GetMapping("/config/payment-timeout")
    public String paymentTimeout() {
        return paymentTimeout;
    }
}
~~~

更复杂配置建议使用校验过的 `@ConfigurationProperties`。并非所有对象都适合运行时重建，例如数据库连接池、线程池和加密组件需要专门的更新流程。

---

## 16. Namespace、Group、Data ID 设计

推荐按环境使用 Namespace：

~~~text
Namespace: dev
Namespace: test
Namespace: prod
~~~

按应用或配置类别使用 Group：

~~~text
ORDER_GROUP
PAYMENT_GROUP
SHARED_GROUP
~~~

Data ID 使用稳定命名：

~~~text
order-service.yaml
order-service-feature-flags.yaml
shared-observability.yaml
~~~

推荐示例：

~~~text
prod / ORDER_GROUP / order-service.yaml
prod / ORDER_GROUP / order-service-feature-flags.yaml
prod / SHARED_GROUP / shared-observability.yaml
~~~

避免：

- 所有环境都放在 `public`；
- 所有应用都放在 `DEFAULT_GROUP`；
- Data ID 使用个人姓名或临时工单号；
- 一份 YAML 包含几十个无关服务的全部配置；
- 把 Secret 明文混在普通配置中；
- 频繁变化的业务数据放入配置中心。

---

## 17. 配置发布流程

生产配置不应由个人直接随意修改。推荐流程：

~~~text
Git 中修改配置模板
  → 代码评审
  → CI 校验 YAML/JSON/Properties
  → 生成差异
  → 发布到测试 Namespace
  → 验证客户端订阅和业务指标
  → 灰度发布生产
  → 扩大范围
  → 正式发布
  → 记录变更和回滚点
~~~

发布前检查：

- Namespace、Group、Data ID 是否正确；
- 格式是否能解析；
- 单位是否明确；
- 是否包含敏感值；
- 动态刷新是否安全；
- 旧客户端是否认识新字段；
- 回滚内容是否准备好；
- 是否会引起全量连接重建或缓存失效。

---

## 18. 灰度发布

Nacos 支持同一配置的灰度版本：

~~~text
namespaceId → groupName → dataId → grayName
~~~

常见规则：

| 规则 | 匹配方式 |
|---|---|
| Beta | 客户端 IP 命中 Beta IP 列表 |
| Tag | 请求标签命中指定 Tag |

推荐步骤：

1. 选择少量非关键实例；
2. 发布灰度配置；
3. 验证这些实例读取的新值；
4. 观察错误率、延迟和资源；
5. 扩大灰度或撤回；
6. 确认后发布为正式配置；
7. 删除已无用的灰度版本。

默认每份配置允许的灰度版本数量有限。不要把灰度版本当长期分支管理系统。

---

## 19. 配置历史与回滚

Nacos 会记录配置发布、删除和灰度操作历史，可用于查看：

- 谁修改；
- 何时修改；
- 修改前后内容；
- 发布类型；
- MD5。

回滚前：

1. 找到目标历史版本；
2. 对比当前配置；
3. 确认回滚不会破坏已升级应用；
4. 先对灰度实例验证；
5. 再把历史内容重新发布为正式配置。

服务端本地 Dump 是查询缓存，不是权威备份。不能把本地 Dump 当作正式回滚源；数据库或内置存储才是权威数据源。

---

## 20. 服务元数据与版本路由

实例元数据示例：

~~~yaml
version: v2
zone: cn-hangzhou-a
region: cn-hangzhou
protocol: http
management.port: "18081"
~~~

元数据可被客户端负载均衡、网关或治理组件用于筛选，但 Nacos 本身不会自动完成所有版本路由。

合理做法：

~~~text
Nacos 保存 version=v2
  → 消费者或网关按规则选择 v2 实例
  → 未命中时回退 v1 或失败
~~~

不要让业务方任意创建高基数元数据，也不要在元数据中存放密码、Token 或完整连接串。

---

## 21. 权重与实例上下线

Weight 可以影响支持权重的客户端选择概率，但不是严格流量百分比。实际效果还受：

- 客户端负载均衡算法；
- 本地实例缓存；
- 长连接和连接池；
- 请求数量；
- 网关或服务网格策略；
- 实例健康状态影响。

手工下线实例前：

1. 从流量入口摘除或将实例设为不可用；
2. 等待客户端列表刷新；
3. 等待已有请求和连接排空；
4. 再停止应用；
5. 验证剩余容量。

不能只在 Console 点“下线”后立即杀进程，特别是长连接和耗时请求服务。

---

## 22. 生产集群架构

~~~mermaid
flowchart TB
    A[业务应用] -->|8848 + 9848| VIP[内部域名 / SLB]
    VIP --> N1[Nacos 1]
    VIP --> N2[Nacos 2]
    VIP --> N3[Nacos 3]
    N1 --> DB[(MySQL HA)]
    N2 --> DB
    N3 --> DB
    O[运维人员] -->|8080 + SSO/VPN| CONSOLE[Console 入口]
    P[Prometheus] -->|8848 actuator| N1
    P --> N2
    P --> N3
~~~

推荐：

- 3 或 5 个 Nacos 节点；
- 节点跨故障域部署；
- 外部高可用 MySQL；
- 内部域名 + SLB/VIP；
- 8848 与 9848 配套转发；
- Console 独立访问控制；
- 每个节点独立监控；
- 配置、插件和数据库有备份；
- 所有节点使用相同鉴权身份和 JWT Secret。

不要只在 Nacos 前加一个负载均衡器就宣称“高可用”。MySQL、DNS、SLB、网络和鉴权 Secret 都可能成为单点。

---

## 23. 发行包集群部署

### 23.1 环境要求

准备：

- 至少 3 台 Linux 主机；
- 兼容的 JDK；
- MySQL；
- 时间同步；
- 节点间端口连通；
- 固定主机名或 IP；
- 足够的文件句柄和内存。

具体 JDK 版本和资源需求必须按 Nacos 3.2.3 Release 说明确认。

### 23.2 初始化 MySQL

从与 Nacos 版本对应的发行包中取得：

~~~text
conf/mysql-schema.sql
~~~

不要从不明博客复制旧 Schema。初始化后检查表是否完整，并使用专用数据库账号。

### 23.3 `cluster.conf`

~~~text
10.0.10.11:8848
10.0.10.12:8848
10.0.10.13:8848
~~~

所有节点的 `cluster.conf` 应保持一致。

### 23.4 `application.properties`

~~~properties
spring.sql.init.platform=mysql

db.num=1
db.url.0=jdbc:mysql://mysql.internal:3306/nacos_config?characterEncoding=utf8&connectTimeout=1000&socketTimeout=3000&autoReconnect=true&useSSL=true
db.user=nacos
db.password=${NACOS_DB_PASSWORD}

nacos.core.auth.system.type=nacos
nacos.core.auth.enabled=true
nacos.core.auth.admin.enabled=true
nacos.core.auth.console.enabled=true
nacos.core.auth.server.identity.key=${NACOS_IDENTITY_KEY}
nacos.core.auth.server.identity.value=${NACOS_IDENTITY_VALUE}
nacos.core.auth.plugin.nacos.token.secret.key=${NACOS_AUTH_TOKEN}

management.endpoints.web.exposure.include=prometheus
~~~

说明：

- 所有节点必须使用相同的 Identity 和 JWT Secret；
- 数据库密码不要直接进入 Git；
- 环境变量引用和配置优先级应在目标启动方式中实际验证；
- MySQL TLS 还需要证书和驱动参数，不能只写 `useSSL=true`；
- 连接池参数应按数据库容量设置。

### 23.5 启动

~~~bash
sh bin/startup.sh
tail -f logs/start.out
~~~

逐台启动并验证，不要在没有观察集群状态时一次性重启全部节点。

---

## 24. MySQL 设计与运维

官方最低兼容要求不等于生产推荐版本。新部署可优先选择受支持的 MySQL 8 LTS，并完成兼容测试。

建议：

- 使用独立数据库和专用账号；
- 开启高可用和自动故障转移；
- 限制 Nacos 账号权限范围；
- 监控连接数、慢查询、锁等待和复制延迟；
- 定期备份并演练恢复；
- 数据库时区、字符集和排序规则保持一致；
- 不与高峰业务数据库争抢资源；
- 升级 Nacos 前核对 Schema 变化。

数据库故障会影响配置发布、查询和集群状态。客户端本地缓存可能让部分业务暂时运行，但不能把缓存当成数据库高可用方案。

---

## 25. Kubernetes 部署

官方提供 `nacos-k8s` 示例。生产中建议使用 StatefulSet、Headless Service、外部 MySQL 和持久卷。

### 25.1 获取示例

~~~bash
git clone https://github.com/nacos-group/nacos-k8s.git
cd nacos-k8s
git log -1 --oneline
~~~

正式使用前应固定 Commit 或 Release，并审查清单，不要长期跟随默认分支。

### 25.2 推荐资源

~~~text
Namespace: nacos-system
StatefulSet: nacos，replicas=3
Headless Service: 节点发现
ClusterIP Service: 客户端入口
Secret: DB 与鉴权信息
ConfigMap: 非敏感配置
PVC: 日志或确需持久化的本地状态
PodDisruptionBudget: 控制同时中断数量
NetworkPolicy: 限制客户端、节点和数据库访问
ServiceMonitor: Prometheus 监控
~~~

### 25.3 需要开放的 Service 端口

~~~yaml
ports:
  - name: server-http
    port: 8848
    targetPort: 8848
  - name: client-grpc
    port: 9848
    targetPort: 9848
  - name: server-grpc
    port: 9849
    targetPort: 9849
  - name: raft
    port: 7848
    targetPort: 7848
  - name: console
    port: 8080
    targetPort: 8080
~~~

客户端 Service 通常只需要暴露 `8848/9848`；`7848/9849` 只给 Nacos 节点间通信；Console 应使用单独入口和访问策略。

### 25.4 探针

Server：

~~~text
/nacos/v3/admin/core/state/liveness
/nacos/v3/admin/core/state/readiness
~~~

Console：

~~~text
/v3/console/health/liveness
/v3/console/health/readiness
~~~

探针不能过于敏感，否则网络抖动可能同时重启多个 Pod。应结合启动时间、数据库抖动和集群恢复时间设置阈值。

### 25.5 验证

~~~bash
kubectl -n nacos-system get pod,svc,pvc
kubectl -n nacos-system get events --sort-by=.lastTimestamp | tail -30
kubectl -n nacos-system logs statefulset/nacos --tail=200
~~~

资源名称以实际清单为准。

---

## 26. 负载均衡和域名

推荐入口：

~~~text
nacos.internal.example:8848
nacos.internal.example:9848
~~~

负载均衡要求：

- `8848` 转发 Nacos Server HTTP；
- `9848` 使用 TCP 四层转发；
- 健康检查使用 readiness 接口；
- 不把 `7848/9849` 暴露给普通客户端；
- DNS TTL 和故障切换时间合理；
- 空闲超时支持 gRPC 长连接；
- Console `8080` 使用单独域名和认证。

如果修改主端口，例如从 `8848` 改为 `18848`，客户端按 `+1000` 计算的 gRPC 端口也会变化。端口映射必须整体设计，不能只修改 HTTP 端口。

---

## 27. 鉴权与 RBAC

### 27.1 三层开关

~~~properties
nacos.core.auth.enabled=true
nacos.core.auth.admin.enabled=true
nacos.core.auth.console.enabled=true
~~~

分别控制客户端、Admin API 和 Console 访问。生产建议全部显式开启。

### 27.2 用户、角色、权限

推荐：

- 管理员：只用于平台管理；
- 应用账号：只读指定 Namespace 的配置和服务；
- 发布账号：只能发布指定 Group/Data ID；
- CI 账号：短期 Token，限制来源和权限；
- 审计账号：只读历史和资源。

不要让所有应用共用 `nacos` 管理员账号。

### 27.3 LDAP、OIDC/OAuth2

Nacos 3.2 支持默认 Nacos 鉴权插件，也支持 LDAP、OIDC/OAuth2 等模式。企业环境优先考虑统一身份、MFA 和集中授权。

Nacos 官方明确把内置简单鉴权定位为内部防误用机制。即使开启鉴权，也必须保留：

- 内网隔离；
- TLS；
- 防火墙或 NetworkPolicy；
- Console 单独入口；
- 操作审计；
- Secret 轮换。

---

## 28. 配置安全

不要在普通 Nacos 配置中直接保存：

- 数据库管理员密码；
- 云 AccessKey/SecretKey；
- SSH 私钥；
- JWT 签名密钥；
- OAuth Client Secret；
- 长期 API Token；
- 完整证书私钥。

推荐：

~~~text
Nacos 保存：
  功能开关、超时、限流阈值、服务地址、非敏感业务参数

Secret 系统保存：
  密码、Token、私钥、证书、AccessKey
~~~

如果必须通过 Nacos 分发敏感配置，应使用加密插件、严格 RBAC、密钥轮换和审计，并确认客户端落盘缓存的保护方式。

---

## 29. 监控 Nacos

### 29.1 暴露 Prometheus 指标

~~~properties
management.endpoints.web.exposure.include=prometheus
~~~

访问：

~~~text
http://nacos-node:8848/nacos/actuator/prometheus
~~~

### 29.2 Prometheus 配置

~~~yaml
scrape_configs:
  - job_name: nacos
    metrics_path: /nacos/actuator/prometheus
    scrape_interval: 15s
    static_configs:
      - targets:
          - 10.0.10.11:8848
          - 10.0.10.12:8848
          - 10.0.10.13:8848
~~~

应直接监控每个节点，不要只抓取 SLB，否则无法发现单节点异常。

### 29.3 重点监控

- JVM Heap、GC、线程数；
- CPU、内存、文件句柄；
- HTTP/gRPC 请求和错误；
- 客户端长连接数；
- 配置数量和订阅者；
- 服务和实例数量；
- 推送失败；
- Raft Leader 和状态；
- Distro 同步异常；
- MySQL 连接池；
- 数据库延迟与错误；
- 节点 Ready 状态；
- 集群成员数量。

### 29.4 健康检查

~~~bash
curl -fsS http://10.0.10.11:8848/nacos/v3/admin/core/state/liveness
curl -fsS http://10.0.10.11:8848/nacos/v3/admin/core/state/readiness
curl -fsS http://10.0.10.12:8848/nacos/v3/admin/core/state/readiness
curl -fsS http://10.0.10.13:8848/nacos/v3/admin/core/state/readiness
~~~

健康检查只代表组件当前状态，不代表配置发布、服务订阅和数据库写入全链路一定正常。还应定期执行合成验证。

---

## 30. 日志

发行包日志位于：

~~~text
${nacos.home}/logs/
~~~

排障时重点关注：

- `start.out`：启动过程；
- 服务端核心日志；
- 配置中心日志；
- Naming/服务发现日志；
- Auth 日志；
- Raft、Distro、gRPC 日志；
- 数据源和连接池错误；
- 客户端本地日志。

生产要求：

- 配置日志轮转；
- 监控磁盘占用；
- 不记录密码和 Token；
- 统一采集到日志平台；
- 保留节点名、版本和时间；
- 所有节点启用时间同步。

---

## 31. 备份与恢复

### 31.1 需要备份

- MySQL 数据库；
- `application.properties`；
- `cluster.conf`；
- 自定义插件；
- TLS 证书配置；
- Console 和网关配置；
- Prometheus 告警规则；
- 发布流水线和配置 Git 仓库；
- 鉴权 Secret 的安全备份。

不要把 Secret 明文放在普通备份文档中。

### 31.2 恢复顺序

~~~text
1. 准备与备份兼容的 Nacos 版本
2. 恢复 MySQL
3. 恢复 Nacos 配置和插件
4. 恢复统一的鉴权 Identity/JWT Secret
5. 启动一个节点并验证数据库
6. 逐步启动剩余节点
7. 验证集群成员和健康状态
8. 验证配置读取、监听、服务注册和发现
9. 恢复客户端流量
10. 再进行版本升级
~~~

不要一边跨大版本升级一边恢复故障现场。先恢复到兼容版本，再单独执行升级。

### 31.3 恢复演练

至少验证：

- 指定配置能否恢复；
- 历史记录是否存在；
- 用户角色是否有效；
- 客户端能否重新连接；
- 服务能否注册和发现；
- MySQL 主备切换是否影响 Nacos；
- 丢失一个 Nacos 节点时集群是否仍可用。

---

## 32. 升级策略

升级前：

1. 阅读目标版本 Release Notes；
2. 检查 v1/v2 API、SDK、插件和 Schema 兼容；
3. 备份数据库和配置；
4. 在测试集群恢复生产数据副本；
5. 验证 Spring Cloud Alibaba 和其他客户端；
6. 观察配置监听、注册、订阅和鉴权；
7. 准备回滚镜像和数据库方案。

滚动升级原则：

- 一次只升级一个 Nacos 节点；
- 等待节点 Ready 并加入集群；
- 检查客户端连接和错误率；
- 再继续下一个节点；
- 不同时升级 MySQL、Nacos 和全部客户端；
- 遇到 Schema 变化必须遵守官方升级顺序。

升级完成后验证：

~~~text
Console 登录
Client/Admin API
配置读取和推送
实例注册和订阅
9848 长连接
Raft/Distro 状态
Prometheus 指标
用户、角色与权限
~~~

---

## 33. 常见故障排查

### 33.1 Console 访问 `8848/nacos` 打不开

Nacos 3.x Console 默认已经独立到 `8080`：

~~~text
http://nacos-host:8080/
~~~

`8848` 是 Server API，不要继续套用 2.x 控制台地址。

### 33.2 应用连接 8848 成功但仍注册失败

检查 `9848`：

~~~bash
nc -vz nacos.internal.example 8848
nc -vz nacos.internal.example 9848
~~~

常见原因：

- 防火墙只开放 8848；
- SLB 没有监听 9848；
- 9848 被按 HTTP 代理；
- NAT 端口偏移映射错误；
- gRPC 空闲连接被代理回收。

### 33.3 登录失败

检查：

- 是否完成管理员初始化；
- 用户名是否为实际账号；
- 密码是否被 Shell 特殊字符破坏；
- 所有节点 JWT Secret 是否一致；
- Identity Key/Value 是否一致；
- Token 是否过期；
- 请求是否落到了不同配置的节点；
- 时间是否同步。

### 33.4 配置查不到

逐项对比：

~~~text
Namespace ID
Group Name
Data ID
文件后缀
大小写
客户端账号权限
~~~

最常见错误是把 Namespace 显示名称当成 ID，或应用读取 `DEFAULT_GROUP`，Console 发布在其他 Group。

### 33.5 配置修改后应用没刷新

检查：

- 应用是否成功建立监听；
- `refreshEnabled` 是否开启；
- Spring Bean 是否支持刷新；
- 是否使用 `@RefreshScope` 或支持动态更新的配置绑定；
- 回调是否报解析错误；
- 新内容是否合法；
- 客户端是否回退到本地快照；
- Nacos Server 是否成功推送。

### 33.6 服务存在但没有健康实例

检查：

- 实例是否仍保持长连接/心跳；
- 实例 IP 是否是消费者可访问地址；
- 应用是否注册了 Pod 内不可达地址；
- Namespace、Group、Service Name 是否一致；
- 临时/持久服务类型是否匹配；
- 实例是否被手工禁用；
- Cluster 筛选是否排除了全部实例。

### 33.7 容器应用注册成错误 IP

容器或多网卡主机可能自动选择错误网卡。应显式配置注册 IP 或使用框架提供的网络选择参数，并从消费者网络验证：

~~~bash
curl -v http://REGISTERED_IP:REGISTERED_PORT/actuator/health
~~~

### 33.8 Docker 中使用 `127.0.0.1:8848` 失败

容器内的 `127.0.0.1` 是应用容器自身。Compose 中应使用服务名：

~~~text
nacos:8848
~~~

Kubernetes 中使用 Service DNS：

~~~text
nacos.nacos-system.svc.cluster.local:8848
~~~

### 33.9 MySQL 连接失败

检查：

~~~bash
nc -vz mysql.internal 3306
mysql --host=mysql.internal --user=nacos --password nacos_config
~~~

并确认：

- Schema 已初始化；
- JDBC URL 正确；
- 字符集和 TLS 参数正确；
- 数据库账号有权限；
- MySQL 连接数未耗尽；
- DNS 未解析到错误实例；
- 所有 Nacos 节点使用同一数据库。

### 33.10 Nacos 节点无法组成集群

检查：

- `cluster.conf` 是否一致；
- 主机名能否互相解析；
- `7848/8848/9848/9849` 是否互通；
- 所有节点时间是否同步；
- Identity Key/Value 是否一致；
- 节点 IP 是否发生变化；
- Raft 日志和数据目录是否损坏；
- 是否误把客户端 VIP 写入 `cluster.conf`。

### 33.11 客户端仍调用旧 v1 API

Nacos 3.2 主发行版已移除旧 v1/v2 HTTP API。处理方法：

1. 找出调用方；
2. 升级 SDK 或脚本到 v3；
3. 区分 Client API 和 Admin API；
4. 在测试环境验证认证和字段；
5. 不要通过网关伪造旧接口长期拖延迁移。

---

## 34. Nacos 与其他工具对比

| 工具 | 主要能力 | 更适合的场景 |
|---|---|---|
| Nacos | 服务发现、配置中心、AI Registry | Spring Cloud Alibaba、中国云原生生态 |
| Eureka | 服务注册发现 | 传统 Spring Cloud Netflix 项目 |
| Consul | 服务发现、KV、健康检查、服务网格能力 | 多语言、HashiCorp 体系 |
| etcd | 强一致 KV、Watch | Kubernetes 和基础设施控制面 |
| Apollo | 配置中心、发布治理 | 强配置治理和多环境发布 |
| ZooKeeper | 协调、选举、节点模型 | 旧分布式系统和特定中间件 |

选型时不要只比较功能列表，还要看：

- 客户端语言生态；
- 一致性和故障语义；
- 运维经验；
- 配置发布审核；
- 多集群和多机房；
- 托管服务可用性；
- 迁移成本；
- 安全和审计要求。

Kubernetes 已经提供 Service 和 ConfigMap/Secret，但 Nacos 仍可能用于跨集群、多语言应用、动态配置和非 Kubernetes 工作负载。不要因为用了 Kubernetes 就自动判定 Nacos 无用，也不要重复建设两套职责不清的注册发现体系。

---

## 35. 生产上线检查清单

### 架构

- [ ] 使用稳定版，不使用 Beta；
- [ ] 至少 3 个 Nacos 节点；
- [ ] 使用外部高可用 MySQL；
- [ ] Nacos、MySQL、SLB、DNS 均无明显单点；
- [ ] 节点分布在不同故障域；
- [ ] 客户端和管理入口分离。

### 网络

- [ ] 应用能访问 8848 和 9848；
- [ ] 9848 使用 TCP 四层转发；
- [ ] 7848/9849 仅节点间开放；
- [ ] Console 8080 只对运维入口开放；
- [ ] 没有端口暴露到公网；
- [ ] DNS、SLB 和防火墙配置已做故障演练。

### 安全

- [ ] 客户端、Admin、Console 鉴权全部开启；
- [ ] 没有使用示例 JWT Secret 和 Identity；
- [ ] 所有节点使用一致的鉴权材料；
- [ ] 应用使用独立最小权限账号；
- [ ] 管理员密码不是默认值或弱密码；
- [ ] 敏感信息使用 Secret/KMS；
- [ ] TLS 和操作审计已配置。

### 配置治理

- [ ] Namespace 按环境隔离；
- [ ] Group/Data ID 命名规范明确；
- [ ] 生产发布需要评审；
- [ ] 有灰度、验证和回滚流程；
- [ ] 动态刷新经过测试；
- [ ] 不把本地 Dump 当备份；
- [ ] 配置内容已过滤敏感数据。

### 可观测性

- [ ] Prometheus 直接抓取每个节点；
- [ ] 监控 JVM、gRPC、连接、推送、Raft、Distro 和数据库；
- [ ] 日志集中收集并轮转；
- [ ] 有集群成员减少、节点不 Ready、数据库异常告警；
- [ ] 有配置读取和服务注册合成检查。

### 备份与升级

- [ ] MySQL 定期备份；
- [ ] 配置、插件和鉴权材料安全备份；
- [ ] 完成恢复演练；
- [ ] 固定 Server、Client 和框架版本；
- [ ] 升级前检查 API、Schema 和插件兼容；
- [ ] 有滚动升级和回滚方案。

---

## 36. 推荐学习顺序

1. 用 Docker 启动 Nacos 3.2.3；
2. 初始化管理员密码并登录 8080 Console；
3. 创建 dev Namespace；
4. 创建第一份 YAML 配置；
5. 用 v3 Client API读取配置；
6. 用 v3 API 注册一个测试实例并查询；
7. 使用 Java SDK监听配置；
8. 使用 Spring Cloud Alibaba 完成注册和配置导入；
9. 验证配置动态刷新；
10. 验证 8848 与 9848 网络边界；
11. 练习 Namespace、Group 和 Data ID 设计；
12. 练习灰度发布和回滚；
13. 部署 3 节点测试集群和外部 MySQL；
14. 接入 Prometheus 和日志平台；
15. 演练单节点、MySQL和 SLB 故障；
16. 最后设计生产权限、备份和升级流程。

完成后应能回答：

- 注册中心和配置中心分别解决什么问题；
- 8080、8848、9848、9849、7848 各做什么；
- 为什么只开放 8848 仍然连接失败；
- Namespace 名称和 ID 有什么区别；
- 应用为什么收不到配置变化；
- 临时实例断连后会发生什么；
- Nacos 短时故障时客户端缓存如何工作；
- 如何安全发布和回滚配置；
- 哪些数据必须备份；
- 如何判断集群是否真的健康。

---

## 37. 常用命令速查

### Docker

~~~bash
docker compose up -d
docker compose ps
docker compose logs -f --tail 100 nacos
docker inspect nacos-standalone
~~~

### 健康检查

~~~bash
curl -fsS http://127.0.0.1:8848/nacos/v3/admin/core/state/liveness
curl -fsS http://127.0.0.1:8848/nacos/v3/admin/core/state/readiness
curl -fsS http://127.0.0.1:8080/v3/console/health/readiness
~~~

### 端口

~~~bash
nc -vz nacos.internal.example 8848
nc -vz nacos.internal.example 9848
ss -lntp | grep -E ':(7848|8080|8848|9848|9849)\b'
~~~

### Kubernetes

~~~bash
kubectl -n nacos-system get pod,svc,endpoints,pvc
kubectl -n nacos-system get events --sort-by=.lastTimestamp | tail -30
kubectl -n nacos-system logs statefulset/nacos --tail=200
~~~

### Prometheus

~~~bash
curl -fsS http://127.0.0.1:8848/nacos/actuator/prometheus | head
~~~

---

## 38. 官方资料

- [Nacos 官方文档](https://nacos.io/docs/latest/)
- [Nacos 概览](https://nacos.io/docs/latest/overview/)
- [Nacos 快速开始](https://nacos.io/docs/latest/quickstart/quick-start/)
- [Nacos GitHub Releases](https://github.com/alibaba/nacos/releases)
- [部署架构说明](https://nacos.io/docs/latest/manual/admin/deployment/deployment-overview/)
- [集群部署](https://nacos.io/docs/latest/manual/admin/deployment/deployment-cluster/)
- [系统参数](https://nacos.io/docs/latest/manual/admin/system-configurations/)
- [服务发现概览](https://nacos.io/docs/latest/manual/user/naming/overview/)
- [配置管理概览](https://nacos.io/docs/latest/manual/user/config/overview/)
- [配置灰度发布](https://nacos.io/docs/latest/manual/user/config/gray-release/)
- [Nacos v3 Client API](https://nacos.io/docs/latest/manual/user/open-api/)
- [Nacos v3 Admin API](https://nacos.io/docs/latest/manual/admin/admin-api/)
- [Java SDK 使用](https://nacos.io/docs/latest/manual/user/java-sdk/usage/)
- [鉴权与权限](https://nacos.io/docs/latest/manual/admin/auth/)
- [监控手册](https://nacos.io/docs/latest/manual/admin/monitor/)
- [Nacos Docker](https://github.com/nacos-group/nacos-docker)
- [Nacos Kubernetes](https://github.com/nacos-group/nacos-k8s)
- [Spring Cloud Alibaba Nacos 指南](https://sca.aliyun.com/docs/2025.x/user-guide/nacos/quick-start/)
- [Spring Cloud Alibaba 版本说明](https://sca.aliyun.com/docs/2025.x/overview/version-explain/)

生产部署前，应根据固定版本重新核对 Server、Client、Spring Cloud Alibaba、JDK、MySQL、API 和插件兼容关系。
