# K8s 排障进阶：5 个冷门 kubectl 命令详解

> 最后更新：2026-09-28
> 参考来源：公众号「不怕慢」同名文章（2026-08），并结合官方文档做了勘误与扩充

日常排障靠 `kubectl describe` 和 `kubectl logs` 能覆盖七八成问题，但剩下的疑难场景——跨 namespace 事件看不见、容器里没工具、Pod 反复重启抓不到现场、节点负载高却找不到元凶——需要这几个命令。**每个命令都给出使用场景、完整语法、实战套路和坑点。**

---

## 一、kubectl get events --all-namespaces：跨命名空间事件排查

### 为什么默认用法会漏信息

`kubectl get events` 默认只显示**当前 namespace** 的事件。而以下关键事件不在业务 ns 里：

- Node 级别事件（驱逐、磁盘压力、NotReady）挂在 Node 对象上，记录在 `default`/`kube-system` 等空间
- 跨 namespace 的引用类事件（如 PVC 绑定失败）可能被 ns 边界过滤

**典型翻车场景**：某 Node 上 Pod 全部被驱逐，`kubectl describe node` 显示正常，默认 ns 下 `get events` 空空如也——真相是被驱逐事件根本不在当前 ns。

### 核心用法

```bash
# 全集群事件
kubectl get events --all-namespaces

# 只看 Warning（生产排障第一板斧）
kubectl get events --all-namespaces --field-selector type=Warning

# 只看最近 1 小时
kubectl get events --all-namespaces --field-selector type=Warning --since=1h

# 只看某个 Node 相关事件
kubectl get events --all-namespaces \
  --field-selector involvedObject.kind=Node,involvedObject.name=worker-1

# 追踪某个 Deployment（含其下 Pod 的事件）
kubectl get events --all-namespaces \
  --field-selector involvedObject.kind=Deployment,involvedObject.name=my-app

# 按时间倒序（最新的排前面）
kubectl get events --all-namespaces --sort-by='.lastTimestamp'

# 实时跟踪
kubectl get events --all-namespaces -w

# 抓驱逐事件
kubectl get events --all-namespaces | grep -i evict
```

### 坑点

- **Event 默认只保留 1 小时**（由 apiserver `--event-ttl` 控制），超时后事件消失，"昨晚的事故查不到事件"就是 TTL 过期。重要集群应把事件接入外部系统（如 eventrouter / Loki）持久化。
- `--field-selector` 只支持 `type`、`reason`、`involvedObject.*` 等少数字段，不支持任意 label 过滤——按标签筛应用请用 `kubectl get events -n <ns> -l app=xxx` 之外的 jsonpath 方案：

```bash
kubectl get events --all-namespaces -o json | \
  jq '.items[] | select(.involvedObject.namespace=="prod")'
```

---

## 二、kubectl debug：容器里没工具时的救星

### 适用场景

生产镜像为瘦身只剩业务二进制，没有 `ping`、`curl`、`tcpdump`、`nslookup`。改 Dockerfile 重部署太慢——`kubectl debug` 直接启用**临时容器（Ephemeral Container）**。

> 版本要求：Ephemeral Containers 在 **K8s 1.23 Beta（需特性门控）/ 1.25 GA**。低于 1.25 的老集群可能不可用，用 `kubectl version` 确认。

### 两种调试模式

**模式 A：注入临时容器（推荐）**

在原 Pod 的 network namespace 里挂一个带全套网络工具的容器，原业务容器完全不受影响：

```bash
# 交互式进入
kubectl debug pod/my-app -it --image=nicolaka/netshoot

# 直接执行抓包（共享 network namespace，看到的就是业务流量）
kubectl debug pod/my-app -it --image=nicolaka/netshoot -- tcpdump -i any -nn port 8080

# 验证集群内 DNS
kubectl debug pod/my-app -it --image=nicolaka/netshoot -- nslookup kubernetes.default.svc.cluster.local

# 查路由 / 连接状态
kubectl debug pod/my-app -it --image=nicolaka/netshoot -- ip route
kubectl debug pod/my-app -it --image=nicolaka/netshoot -- ss -tlnp
```

**模式 B：复制 Pod 副本调试（`--copy-to`）**

适合需要改启动命令、替换镜像的调试：

```bash
# 复制一个 Pod 副本并把命令换成 sleep，方便留现场慢慢查
kubectl debug pod/my-app -it --image=busybox --copy-to=my-app-debug -- sh

# 共享进程命名空间，可以看到原容器的进程和文件系统（/proc/<pid>/root）
kubectl debug pod/my-app -it --image=busybox --share-processes --copy-to=my-app-debug
```

**模式 C：直接调试 Node**（相当于免 SSH 进节点）

```bash
kubectl debug node/worker-1 -it --image=ubuntu
# 节点文件系统挂载在 /host
chroot /host
```

### 坑点

- 临时容器**不能改端口、不能加资源限制以外的声明**，退出后随 Pod 销毁，适合应急不适合常驻。
- `--profile`（1.27+）可控制权限档位：`general`（默认）、`baseline`、`netadmin`（抓包需要）、`restricted`。多数集群抓包要 `--profile=netadmin`。
- 排完记得删副本：`kubectl delete pod my-app-debug`。

---

## 三、kubectl logs --previous：CrashLoopBackOff 现场勘查

### 适用场景

Pod 反复重启，`logs` 只看到当前这一轮的残片，甚至窗口太短什么都抓不到。`--previous` 取**上一次容器终止前**的日志。

### 全套排查流程

```bash
# 1. 看上一轮为什么挂
kubectl logs my-app --previous --tail=100

# 2. 对比当前轮和上一轮（第二次崩溃原因可能不同）
kubectl logs my-app --tail=50 > /tmp/now.log
kubectl logs my-app --previous --tail=50 > /tmp/prev.log
diff /tmp/prev.log /tmp/now.log

# 3. 看退出码——这是定性问题的关键
kubectl get pod my-app -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'
kubectl get pod my-app -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
```

**退出码速查：**

| 退出码 | 含义 | 常见根因 |
|--------|------|----------|
| 0 | 正常退出 | 命令执行完就退出（Job 正常 / 长期服务 main 函数返回 = bug） |
| 1 | 应用自身报错 | 配置文件错误、依赖服务连不上、未捕获异常 |
| 137 | SIGKILL（128+9） | **OOMKilled**（超 memory limit）、或被节点驱逐、或被 liveness 探针杀 |
| 143 | SIGTERM（128+15） | 正常收到终止信号（滚动更新/缩容属正常；频繁出现查探针配置） |

```bash
# 4. 核对实际的启动命令与参数（和 YAML 预期是否一致）
kubectl get pod my-app -o jsonpath='{.spec.containers[0].command}'
kubectl get pod my-app -o jsonpath='{.spec.containers[0].args}'

# 5. 查环境变量（注意可能含敏感信息，勿外发）
kubectl get pod my-app -o jsonpath='{.spec.containers[0].env}'

# 6. config 类问题：直接把配置拷出来看
kubectl cp my-app:/etc/app/config /tmp/config -c <container-name>
```

### 坑点

- `--previous` 只在容器**已经重启过**时才有内容；首次启动就用会报 `previous terminated container not found`。
- 节点重启或容器被 GC 回收后，`--previous` 日志也可能丢失——重要服务永远要靠集中式日志（Loki/ES）兜底，本地 stdout 不可信。

---

## 四、kubectl top + describe node：定位资源争抢

### 典型迷雾

`kubectl top node` 显示某节点 CPU 95%，但 `kubectl top pod` 逐个看都不高——这类"看不见的消耗"几乎都是：**有 Pod 没设 resources.limits**（或运行了大量夯死的子进程），`top` 的采样间隔抓不到峰值。

### 四步定位法

```bash
# 第 1 步：找出压力最大的节点
kubectl top node --sort-by=cpu

# 第 2 步：该节点上所有 Pod 的实时消耗（注意 --sort-by 是跨 ns 全局排序）
kubectl top pod --all-namespaces --sort-by=cpu | head -20

# 第 3 步：看节点非终止 Pod 的资源账本（requests/limits 汇总）
kubectl describe node worker-1 | sed -n '/Non-terminated Pods/,/Allocated resources/p'

# 第 4 步：揪出没设 limits 的裸奔 Pod
kubectl get pods --all-namespaces \
  -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\t"}{.spec.containers[*].resources.limits}{"\n"}{end}' \
  | grep -v -E 'cpu|memory'
```

### EPA 关键概念（判断时必须带着）

- **requests**：调度依据，决定 Pod 放哪个节点；超发没事，但节点 requests 总和超容量 = 新 Pod Pending
- **limits**：硬上限。CPU 超限被**节流（throttle）拖慢**，内存超限被**OOMKill（退出码 137）**
- **QoS 三档**：`Guaranteed`（requests=limits，驱逐顺序最后）→ `Burstable`（设了但不相等）→ `BestEffort`（什么都没设，**最先被驱逐**）。排"为什么我的 Pod 先被驱逐"先查 QoS：

```bash
kubectl get pod my-app -o jsonpath='{.status.qosClass}'
```

### 坑点

- `kubectl top` 依赖 metrics-server，离线/私有化集群没装时会报 `Metrics API not available`。
- `top` 是**快照**不是趋势，抓毛刺要配 Grafana/Prometheus 看历史曲线。

---

## 五、kubectl explain + api-resources：离线 API 手册

### 适用场景

记不住字段名、升级集群后字段变了、不清楚某资源能不能删——不用开浏览器，解释结果**精确匹配当前集群版本**（1.28 的集群就不会给你 1.30 的字段）。

### 核心用法

```bash
# 集群里有哪些资源（短名、API 组、namespaced 与否）
kubectl api-resources

# 按关键词找资源
kubectl api-resources | grep -i network

# 某资源支持哪些动词（找"能不能 patch/delete"）
kubectl api-resources -o wide
kubectl api-resources --verbs=list,get -o name | grep pod

# 查字段到任意深度，带类型和说明
kubectl explain deployment.spec.template.spec.topologySpreadConstraints
kubectl explain pod.spec.containers.resources.requests.cpu

# 递归展开全字段（配合 head/grep 当文档目录用）
kubectl explain pod --recursive | head -80

# CRD 同样适用（这是它比官网强的地方——官网不收录你的 CRD）
kubectl explain virtualservice.spec.http
```

### 坑点

- `explain` 显示的字段是当前 apiserver 的版本，**不是**你 YAML 文件里写的 apiVersion——多版本并存时以集群为准。
- 字段说明文字源自 OpenAPI，CRD 作者没写描述的话就只有字段名没有解释。

---

## 六、实战决策表

| 症状 | 首选命令 | 第二招 |
|------|----------|--------|
| Pod 被驱逐但原因不明 | `get events --all-namespaces --field-selector type=Warning` | `describe node` 看 conditions |
| `describe` 看不出问题 | `get events --sort-by='.lastTimestamp'` | events 过 TTL 了 → 查外部日志系统 |
| 容器里没排查工具 | `kubectl debug --image=nicolaka/netshoot` | exec 进 sidecar 容器 |
| CrashLoopBackOff | `logs --previous` + 退出码 | `jsonpath` 核对 command/env |
| 节点负载高、Pod 都不高 | `top node --sort-by=cpu` + 查无 limits Pod | `describe node` 资源账本 |
| Pod 莫名其妙变慢 | 查 QoS + CPU throttle | Grafana 看历史曲线 |
| 字段名记不住 | `kubectl explain` | `api-resources -o wide` 查 verb |

### 通用排障顺序（推荐肌肉记忆）

```
现象确认 → events（全 ns + Warning）→ logs（含 --previous）→
退出码/QoS → 资源账本（top + describe node）→ debug 容器验证网络/文件系统
```

---

## 总结

这 5 个命令覆盖了 `describe`/`logs` 看不到的四类盲区：

1. **`get events --all-namespaces`** —— 看不见的 ns 边界外的事件
2. **`debug`** —— 没有工具的镜像内部世界
3. **`logs --previous`** —— 已经消失的上一次现场
4. **`top` + `describe node`** —— 无 limits Pod 的隐形资源侵占
5. **`explain`** —— 版本不匹配的文档误导

共同原则：**排障的难点从来不是"看这个命令"，而是"这个命令此刻还能看到真相吗"**——events 有 TTL、logs 有滚动、`--previous` 依赖现场未回收。重要场景永远提前把事件和日志接入外部系统，本地只能救急不能留证。
