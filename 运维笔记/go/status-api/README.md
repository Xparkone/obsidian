# Status API

一个只读的服务器、Kubernetes、Pod 和中间件状态聚合 API。当前实现使用 Go 标准库，便于本地直接编译；Kubernetes 采集通过 Kubernetes REST API 完成。

## 本地运行

```bash
cd go/status-api
STATUS_API_TOKEN=change-me go run .
```

调用汇总接口：

```bash
curl -sS -H 'Authorization: Bearer change-me' \
  http://127.0.0.1:8080/api/v1/status | jq
```

## 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `STATUS_API_PORT` | `8080` | HTTP 监听端口 |
| `STATUS_API_TOKEN` | 空 | Bearer Token；为空时受保护接口全部返回 401 |
| `KUBERNETES_API_URL` | 集群内 DNS | Kubernetes API 地址；本地调试时可显式设置 |
| `STATUS_MIDDLEWARES` | 空 | `name|type|target` 逗号分隔，支持 `http`、`https`、`tcp`、`redis`、`mysql`、`kafka` |

示例：

```bash
STATUS_API_TOKEN=change-me \
STATUS_MIDDLEWARES='redis-prod|redis|redis.default.svc:6379,nacos|http|http://nacos.default.svc:8848/nacos/actuator/health' \
go run .
```

## 当前边界

- Kubernetes 未配置或不可访问时，Kubernetes 和 Pod 状态返回 `unknown`，不会阻塞主机接口。
- Linux 主机从 `/proc` 和根文件系统读取负载、内存、磁盘；非 Linux 环境部分指标可能为 `unknown`。
- 中间件探针只使用服务端配置的目标，不接受请求方传入任意地址。
- 当前为实时采集 MVP，尚未接入 Prometheus、历史存储、JWT/OIDC 和多集群配置。
