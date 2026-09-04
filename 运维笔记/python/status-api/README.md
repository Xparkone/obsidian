# Python Status API

与 `go/status-api` 保持相同接口契约的 Python 标准库实现，不需要安装第三方依赖。

## 运行

```bash
cd "/Users/lijiaxuan/Documents/hermes/运维笔记/python/status-api"
STATUS_API_TOKEN=change-me python3 -m status_api
```

调用：

```bash
curl -sS -H 'Authorization: Bearer change-me' \
  http://127.0.0.1:8080/api/v1/status | python3 -m json.tool
```

## 配置

```text
STATUS_API_HOST=0.0.0.0
STATUS_API_PORT=8080
STATUS_API_TOKEN=change-me
KUBERNETES_API_URL=https://kubernetes.default.svc
STATUS_MIDDLEWARES=name|type|target,name2|http|http://example.com/health
```

支持接口：`/api/v1/status`、`/api/v1/host`、`/api/v1/k8s`、`/api/v1/k8s/pods`、`/api/v1/middlewares`、`/healthz`。

当前版本使用 Python 标准库：`http.server`、`urllib`、`socket` 和 `/proc`。Kubernetes Pod 内运行时，主机指标是容器视角；节点级数据仍需 Node Exporter/Prometheus 或独立 Host Collector。
