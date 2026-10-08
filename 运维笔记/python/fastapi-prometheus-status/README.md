# FastAPI + Prometheus Kubernetes 状态 API

这个示例使用 FastAPI 调用 Prometheus HTTP API，只读判断 Kubernetes 节点、Service Endpoint，以及 Node Exporter 提供的主机负载、内存和磁盘使用率。

## 指标前提

需要 Prometheus 已采集：

- `kube-state-metrics`：`kube_node_status_condition`、`kube_node_spec_unschedulable`、`kube_endpoint_address_available`；
- `node-exporter`：`node_load1`、`node_cpu_seconds_total`、`node_memory_MemAvailable_bytes`、`node_memory_MemTotal_bytes`、`node_filesystem_avail_bytes`、`node_filesystem_size_bytes`。

缺少某组指标时，接口会返回 `unknown` 或 `degraded`，不能把“没有数据”当作正常。

## 启动

```bash
cd python/fastapi-prometheus-status
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

应用会通过 `python-dotenv` 自动读取当前目录的 `.env`。已经在 Shell 中导出的同名环境变量优先于 `.env`。`.env` 只放本地配置，不要写入真实 Token 或提交到 Git。

接口：

```bash
curl http://127.0.0.1:8080/healthz
curl 'http://127.0.0.1:8080/api/v1/status?namespace=prod&service=order-api' | jq
curl http://127.0.0.1:8080/api/v1/kubernetes/nodes | jq
curl http://127.0.0.1:8080/api/v1/kubernetes/services | jq
curl http://127.0.0.1:8080/api/v1/host | jq
```

Prometheus 地址和 Token 只通过环境变量注入；不要把 Token 写入仓库或日志。默认阈值是负载/CPU `1.0/2.0`、内存 `80%/90%`、磁盘 `80%/90%`，需按节点规格和业务基线调整。

## 返回状态

`healthy` 表示所有已查询检查正常；`degraded` 表示有阈值告警或指标缺失；`unhealthy` 表示节点未 Ready、Service 没有可用 Endpoint，或主机指标达到 critical 阈值。该服务只反映 Prometheus 最近抓取到的时间序列，不替代真实业务请求、Pod 日志、EndpointSlice 和 Kubernetes API 验证。

## 验证 PromQL

先在 Prometheus UI 或 API 中逐条验证指标是否存在：

```bash
curl -G "$PROMETHEUS_URL/api/v1/query" --data-urlencode 'query=kube_node_status_condition{condition="Ready",status="true"}' | jq
curl -G "$PROMETHEUS_URL/api/v1/query" --data-urlencode 'query=node_load1' | jq
```

不同 kube-state-metrics 版本的 Service Endpoint 指标标签可能不同；如果 `kube_endpoint_address_available` 不存在，应按目标环境实际 series 调整 `service_checks` 的 PromQL。
