# Docker 与 K8s 快捷批量操作手册

> 最后更新：2026-10-12

日常运维里最耗时间的不是「不会」，而是「一条一条敲」。本文档收集 Docker 与 Kubernetes 的快捷技巧与批量操作方法：用 `-q`、`--format`、`--filter` 精准定位，用 `$(...)`、`xargs`、`for` 循环和标签选择器批量处理，并给出危险批量操作的安全清单。

> 定位说明：单资源常规操作（标签、调度、探针等）见 [k8s-常用操作手册](k8s-常用操作手册.md)；镜像构建见 [Docker-Build从入门到高级](Docker-Build从入门到高级.md)。

## 目录

1. [快捷环境准备](#一快捷环境准备)
2. [Docker 常用快捷操作](#二docker-常用快捷操作)
3. [Docker 批量操作](#三docker-批量操作)
4. [K8s 常用快捷操作](#四k8s-常用快捷操作)
5. [K8s 批量操作](#五k8s-批量操作)
6. [跨命名空间与节点批量](#六跨命名空间与节点批量)
7. [并行提速](#七并行提速)
8. [危险批量操作安全清单](#八危险批量操作安全清单)
9. [速查表](#九速查表)

---

## 一、快捷环境准备

### 1.1 开启命令补全

```bash
# bash
source <(kubectl completion bash)
source <(docker completion bash)   # docker 官方包自带补全脚本，macOS/Homebrew 通常已装好

# zsh（第二行写入 ~/.zshrc 永久生效）
source <(kubectl completion zsh)
echo 'source <(kubectl completion zsh)' >> ~/.zshrc
```

补全生效后，`kubectl get p<Tab>` 能直接补出 pods，对象名也能 Tab 补齐。

### 1.2 推荐 alias

写入 `~/.bashrc` 或 `~/.zshrc`：

| alias | 展开 | 用途 |
|---|---|---|
| `k` | `kubectl` | 最常用，少敲 6 个字符 |
| `kgp` | `kubectl get pods` | 查看 Pod |
| `kgpa` | `kubectl get pods -A -o wide` | 全集群 Pod + 所在节点 |
| `kgs` | `kubectl get svc` | 查看 Service |
| `kd` | `kubectl describe` | 描述资源 |
| `kl` | `kubectl logs` | 查日志 |
| `kx` | `kubectl exec -it` | 进容器 |
| `dps` | `docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"` | 容器速览 |
| `dimg` | `docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"` | 镜像速览 |
| `dclean` | `docker system prune` | 一键清理（见 3.3） |

> alias 只影响交互式 Shell；脚本里请写完整命令，避免换环境后失效。

### 1.3 kubectl 资源缩写

| 缩写 | 全称 | 缩写 | 全称 |
|---|---|---|---|
| po | pods | deploy | deployments |
| svc | services | ns | namespaces |
| no | nodes | ing | ingress |
| cm | configmaps | sa | serviceaccounts |
| pv | persistentvolumes | pvc | persistentvolumeclaims |
| rs | replicasets | sts | statefulsets |
| ds | daemonsets | cj | cronjobs |
| ev | events | ep | endpoints |

```bash
# 查看所有缩写与资源支持的动词
kubectl api-resources -o wide
```

### 1.4 快速切换上下文与命名空间

```bash
# 查看所有 context
kubectl config get-contexts

# 切换集群
kubectl config use-context prod-cluster

# 免每次打 -n：给当前 context 绑定默认命名空间
kubectl config set-context --current --namespace=kube-system

# 多集群场景推荐安装 kubectx / kubens（brew install kubectx）
kubectx            # 交互切换 context
kubens dev         # 切换默认命名空间
```

---

## 二、Docker 常用快捷操作

### 2.1 `-q`：只取容器 / 镜像 ID

`-q` 是批量操作的原料：输出只有 ID 列表，方便传给下一条命令。

```bash
docker ps -q                 # 所有运行中容器的 ID
docker ps -aq                # 所有容器（含已退出）
docker images -q             # 所有镜像 ID
```

### 2.2 `--format`：自定义输出

```bash
# 表格化查看容器：名字、状态、端口
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 镜像按「仓库:标签」列出（批量导出 / 删镜像时用）
docker images --format "{{.Repository}}:{{.Tag}}"

# 只看容器 IP
docker ps --format "{{.Names}}: {{.Networks}}"
```

### 2.3 `--filter`：精准过滤

`-q` 决定「拿到什么」，`--filter` 决定「拿哪些」。

```bash
docker ps --filter status=exited          # 已退出
docker ps --filter status=running         # 运行中
docker ps --filter "exited=0"             # 正常退出的容器
docker ps --filter "exited=1"             # 异常退出的容器
docker ps --filter "name=web"             # 按名称模糊匹配
docker ps --filter label=env=prod         # 按标签
docker ps --filter ancestor=nginx         # 按镜像
docker ps --filter before=web-01          # 在 web-01 之前创建
docker ps --filter since=web-01           # 在 web-01 之后创建

docker images --filter dangling=true      # 悬空镜像（<none>）
docker images --filter "reference=myapp*" # 按镜像名通配
docker images --filter before=myapp:v2    # 比某镜像更早构建的镜像
```

### 2.4 快速进入容器与查日志

```bash
# 进入最近启动的容器（-lq = 最新一个容器的 ID）
docker exec -it $(docker ps -lq) sh
docker exec -it $(docker ps -lq) bash    # 容器里有 bash 时用这个

# 跟踪最近容器的日志
docker logs -f --tail 100 $(docker ps -lq)

# 一次性看所有容器的资源占用
docker stats --no-stream
```

---

## 三、Docker 批量操作

### 3.1 批量停止 / 启动 / 重启 / 删除容器

```bash
# 停止所有运行中的容器
docker stop $(docker ps -q)

# 启动所有已退出的容器
docker start $(docker ps -aq --filter status=exited)

# 重启所有运行中的容器
docker restart $(docker ps -q)

# 删除所有已退出的容器（运行中的不动）
docker rm $(docker ps -aq --filter status=exited)

# 按名称模式批量删除，例如所有 web- 开头
docker rm -f $(docker ps -aq --filter "name=web-")

# 按镜像批量删除，例如所有基于 nginx 的容器
docker rm -f $(docker ps -aq --filter ancestor=nginx)

# 核选项：删除所有容器（运行中的也强删）
docker rm -f $(docker ps -aq)
```

> **注意：** 过滤结果为空时，`$(...)` 展开为空，`docker stop` 不带参数会报 "requires at least 1 argument"，可忽略；想干净处理可写：
>
> ```bash
> ids=$(docker ps -q) && [ -n "$ids" ] && docker stop $ids
> ```

### 3.2 批量删除镜像

```bash
# 删除所有悬空镜像（构建残留）
docker rmi $(docker images -q --filter dangling=true)

# 删除指定名称的所有版本
docker rmi $(docker images --format "{{.Repository}}:{{.Tag}}" | grep '^myapp:')

# 删除所有镜像（容器正在引用的会报 in use，可加 -f 强制）
docker rmi $(docker images -q)
```

### 3.3 prune 家族：一键清理

| 命令 | 清理对象 | 说明 |
|---|---|---|
| `docker container prune` | 所有已退出的容器 | 等效于 3.1 的按状态批量删除 |
| `docker image prune` | 悬空镜像 | 只删 `<none>` 层 |
| `docker image prune -a` | 未被任何容器使用的全部镜像 | 范围大，确认后再用 |
| `docker volume prune` | 未被引用的卷 | 会丢数据，慎用 |
| `docker network prune` | 未被使用的自定义网络 | 默认网桥不动 |
| `docker builder prune` | 构建缓存 | 磁盘暴涨时先查这里 |
| `docker system prune` | 容器 + 网络 + 悬空镜像 + 构建缓存 | 日常清理主力 |
| `docker system prune -a --volumes` | 以上全部 + 未用卷 | 释放空间最多，也最危险 |

```bash
# 常用组合：加 -f 跳过交互确认
docker system prune -af

# 按时间过滤：只清理 24 小时前的无用资源
docker system prune -a --filter "until=24h"
```

### 3.4 批量导出 / 导入 / 改标签

```bash
# 导出所有带有效 tag 的镜像到一个 tar（排除 <none> 悬空层）
docker save -o all-images.tar $(docker images --format "{{.Repository}}:{{.Tag}}" | grep -v '<none>')

# 批量导入目录下所有 tar 镜像
for f in images/*.tar; do docker load -i "$f"; done

# 批量改 tag：把本地 myapp:* 统一打上 registry 前缀并推送
for img in $(docker images --format "{{.Repository}}:{{.Tag}}" | grep '^myapp:'); do
  new="registry.example.com/${img}"
  docker tag "$img" "$new"
  docker push "$new"
done
```

### 3.5 批量巡检：循环收集所有容器信息

```bash
# 所有容器的健康状态与重启策略一览
for c in $(docker ps -aq); do
  docker container inspect -f '{{.Name}} | 状态={{.State.Status}} | 重启策略={{.HostConfig.RestartPolicy.Name}}' "$c"
done

# 收集每个容器最后 20 行日志做快照
mkdir -p /tmp/docker-logs
for c in $(docker ps --format '{{.Names}}'); do
  docker logs --tail 20 "$c" > "/tmp/docker-logs/${c}.log" 2>&1
done

# 磁盘占用定位大户
docker system df -v
```

### 3.6 两种批量范式对比

| 范式 | 写法 | 优点 | 坑 |
|---|---|---|---|
| 命令替换 `$(...)` | `docker rm $(docker ps -aq --filter status=exited)` | 简短直观 | 结果为空会报参数缺失；名称含空格会切错 |
| 管道 + xargs | `docker ps -aq --filter status=exited \| xargs docker rm` | 可加 `-n` 分批、`-P` 并行 | 同样按空白切分；macOS 的 xargs 没有 GNU 的 `-r`（GNU 下 `-r` 表示空输入时不执行） |

> 容器 / 镜像名只含 `[a-zA-Z0-9_.-]`，正常使用不会遇到空格问题；处理任意义字符（如文件路径）时改用 `xargs -0` 并按 NUL 分隔输出。

---

## 四、K8s 常用快捷操作

### 4.1 全局开关：`-A` / `-o wide` / `-w`

```bash
kubectl get po -A -o wide          # 全集群 Pod，带节点与 IP
kubectl get deploy,svc,ing -A      # 一次查多类资源（逗号拼接）
kubectl get events -A --field-selector type=Warning  # 全集群告警事件
kubectl get po -n app -w           # 实时跟踪变化（Ctrl+C 退出）
```

### 4.2 jsonpath：精确提取字段

```bash
# 所有 Pod 的容器镜像（批量更新镜像前先盘点）
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"/"}{.metadata.name}{"\t"}{.spec.containers[*].image}{"\n"}{end}'

# 所有节点 InternalIP
kubectl get nodes -o jsonpath='{.items[*].status.addresses[?(@.type=="InternalIP")].address}'

# 某个 Pod 调度在哪个节点
kubectl get pod mypod -o jsonpath='{.spec.nodeName}'

# 去重列出全集群在用的镜像
kubectl get pods -A -o jsonpath='{.items[*].spec.containers[*].image}' | tr ' ' '\n' | sort -u
```

### 4.3 配合 jq 处理 JSON

```bash
# 找出重启总次数 > 5 的 Pod
kubectl get pods -A -o json | jq -r '
  .items[]
  | select(((.status.containerStatuses // []) | map(.restartCount) | add // 0) > 5)
  | .metadata.namespace + "/" + .metadata.name'

# 列出使用 hostNetwork 的 Pod
kubectl get pods -A -o json \
  | jq -r '.items[] | select(.spec.hostNetwork == true) | .metadata.namespace + "/" + .metadata.name'
```

### 4.4 排序与标签展示

```bash
# 按创建时间排序（找最新 / 最老的 Pod）
kubectl get pods -A --sort-by=.metadata.creationTimestamp

# 显示全部标签
kubectl get pods --show-labels

# 把指定标签提升为列
kubectl get pods -L app,version
```

### 4.5 `--field-selector`：按字段过滤

```bash
# 只看非 Running 状态的 Pod
kubectl get pods -A --field-selector=status.phase!=Running

# 某节点上的所有 Pod（排障、drain 前盘点必用）
kubectl get pods -A --field-selector=spec.nodeName=node-01 -o wide
```

### 4.6 dry-run：快速生成 YAML 模板

```bash
kubectl run tmp --image=nginx:1.27 --dry-run=client -o yaml > pod.yaml
kubectl create deploy web --image=nginx:1.27 --replicas=3 --dry-run=client -o yaml > deploy.yaml
kubectl create cm app-cm --from-literal=k=v --dry-run=client -o yaml | kubectl apply -f -
```

### 4.7 explain / api-resources：不用翻文档

```bash
kubectl explain pod.spec.containers.resources    # 字段含义速查
kubectl api-resources --namespaced=true -o wide  # 哪些资源属于命名空间、支持什么动词
kubectl api-versions                             # 集群支持的 API 版本
```

---

## 五、K8s 批量操作

标签选择器（`-l`）和「资源类型后不跟名字 = 命中该类型全部」是 kubectl 批量能力的核心，优先于手写 for 循环。

### 5.1 按标签批量查看 / 删除

```bash
# 第一步永远是查看（先确认范围）
kubectl get pods -l app=old-service -n prod

# 按标签删除 Pod（注意：被 Deployment/RS 管理的 Pod 会被立即重建，见第八章）
kubectl delete pods -l app=old-service -n prod

# 按标签删除多类资源
kubectl delete deploy,svc -l app=old-service -n prod

# 删除某命名空间里所有 Pod
kubectl delete pods --all -n test

# 删除命名空间里全部工作负载与网络资源
kubectl delete all -n test   # 注意：all 不含 pv、pvc、cm、secret、rbac 等
```

### 5.2 批量滚动重启

```bash
# 重启指定命名空间全部 Deployment（资源类型后不跟名字 = 该类型全部）
kubectl rollout restart deploy -n app

# 按标签重启
kubectl rollout restart deploy -l tier=backend -n app

# StatefulSet / DaemonSet 同理
kubectl rollout restart sts -n app
kubectl rollout restart ds -n kube-system

# 观察进度
kubectl rollout status deploy -n app
```

### 5.3 批量扩缩容

```bash
# 命名空间内所有 Deployment 统一缩为 1（测试环境收资源）
kubectl scale deploy --all --replicas=1 -n test

# 按标签扩缩容
kubectl scale deploy -l batch-job=true --replicas=4 -n app

# 缩到 0（暂停全部业务）
kubectl scale deploy --all --replicas=0 -n test
```

### 5.4 批量更新镜像

```bash
# 先用 4.2 的命令盘点在用镜像，再更新
# *=新镜像 表示对该工作负载的所有容器统一更新
kubectl set image deploy -l app=web '*=registry.internal/web:v1.2.3' -n prod

# 循环按工作负载名更新镜像（约定镜像名与 Deployment 同名时适用）
for d in $(kubectl get deploy -n prod -o name); do
  kubectl set image "$d" '*=registry.internal/'"${d#*/}"':v2.0.0' -n prod
done

# 验证
kubectl rollout status deploy -n prod
```

### 5.5 批量打标签 / 打注解

```bash
# 给命名空间内所有 Pod 加/改标签（--overwrite 覆盖已有值）
kubectl label pods --all --overwrite tier=batch -n app

# 按标签筛选后再打
kubectl label pods -l app=web --overwrite version=v2 -n app

# 全集群节点统一打标签
kubectl label nodes --all zone=cn-north --overwrite

# 注解同理：给所有 Service 记录负责人
kubectl annotate svc --all owner=platform-team -n app --overwrite

# 删除标签：键名后加 -
kubectl label pods --all tier- -n app
```

### 5.6 批量清理异常 / 已完成 Pod

```bash
# Evicted / Error 属于 Failed 阶段，一条命令清掉全集群
kubectl delete pods -A --field-selector=status.phase=Failed

# 清理已完成的 Job 残留 Pod
kubectl delete pods -A --field-selector=status.phase=Succeeded

# 只想精准清理 Evicted（jq 匹配 reason）
kubectl get pods -A -o json \
  | jq -r '.items[] | select(.status.reason == "Evicted") | "\(.metadata.namespace) \(.metadata.name)"' \
  | while read -r ns name; do kubectl delete pod -n "$ns" "$name"; done
```

---

## 六、跨命名空间与节点批量

### 6.1 for 循环遍历命名空间

```bash
# 在每个业务命名空间跑一次清理（排除系统命名空间）
for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep -Ev '^(kube-|default$)'); do
  echo "=== $ns ==="
  kubectl delete pods -n "$ns" --field-selector=status.phase=Failed
done
```

### 6.2 批量导出 YAML 做备份

```bash
# 导出全部命名空间的核心工作负载与配置
backup_dir="k8s-backup-$(date +%F)"
for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}'); do
  mkdir -p "$backup_dir/$ns"
  for res in deployments services configmaps ingress pvc; do
    kubectl get "$res" -n "$ns" -o yaml > "$backup_dir/$ns/${res}.yaml" 2>/dev/null
  done
done
```

> 直接导出的 YAML 带有 `managedFields`、`resourceVersion`、`uid` 等运行时字段，重灌前用 `yq` 清洗或装 [kubectl-neat](https://github.com/itaysk/kubectl-neat)：
>
> ```bash
> kubectl get deploy web -n app -o yaml \
>   | yq 'del(.metadata.managedFields, .metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp, .status)' \
>   > web.yaml
> # kubectl neat 更省事：kubectl get deploy web -n app -o yaml | kubectl neat
> ```
>
> 注意：`kubectl get -o yaml` 的 `--export` 参数自 Kubernetes 1.18 起已移除，不要再抄老教程。

### 6.3 节点批量维护（cordon / drain / uncordon）

```bash
# 单节点下线维护的标准三步
kubectl cordon node-01
kubectl drain node-01 --ignore-daemonsets --delete-emptydir-data
# ……维护动作……
kubectl uncordon node-01
```

```bash
# 批量驱逐所有工作节点（滚动升级场景）；务必逐个处理，出错即停
for node in $(kubectl get nodes -l node-role.kubernetes.io/worker= -o jsonpath='{.items[*].metadata.name}'); do
  echo "===== drain $node ====="
  kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data || break
  # 升级 / 重启节点的动作放在这里
  kubectl uncordon "$node"
done
```

> `--delete-emptydir-data` 在旧版本 kubectl 中叫 `--delete-local-data`；drain 会驱逐节点上的业务 Pod，被 PDB 卡住或失败属预期保护行为。

---

## 七、并行提速

### 7.1 xargs -P：多路并行

```bash
# 并行导出每个命名空间的 Deployment（4 路并发）
kubectl get ns -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' \
  | xargs -P 4 -I{} sh -c 'kubectl get deploy -n {} -o yaml > deploy-{}.yaml'

# 并行删除大量 Job（8 路并发）
kubectl get jobs -n batch -o name | xargs -P 8 -n 1 kubectl delete -n batch
```

### 7.2 什么时候别并行

| 场景 | 建议 |
|---|---|
| 删除大量同类资源 | 直接用 kubectl 内置批量（`-l` / `--all`），单条请求一次 API 调用，比并行 for 更温和 |
| 并行导出 / 巡检 | `xargs -P 4~8` 为宜，再高会给 apiserver / etcd 造成尖峰压力 |
| 生产集群批量写 | 先 `kubectl get` 确认清单再动手；批量写操作串行执行，出错立即中断（`|| break`） |

---

## 八、危险批量操作安全清单

### 8.1 两步法：先列出，再执行

```bash
# 第一步：只看不动
kubectl get pods -l app=old-service -n prod

# 第二步：确认无误后，同一选择器换动词
kubectl delete pods -l app=old-service -n prod
```

### 8.2 二次确认脚本模板

```bash
targets=$(kubectl get pods -l app=old -n prod -o name)
[ -z "$targets" ] && { echo "没有命中任何对象，退出"; exit 0; }
echo "$targets"
read -p "确认删除以上对象？输入 yes 继续: " ans
[ "$ans" = "yes" ] && kubectl delete pods -l app=old -n prod || echo "已取消"
```

### 8.3 生产环境禁忌

- `kubectl delete pods -l ...` 删除的如果是 Deployment / RS 管理的 Pod，**控制器会立刻重建**，达不到「下线」目的；要缩容用 `kubectl scale`，要下线删 `deploy`
- `kubectl delete all -n xxx` **不会**删除 pv / pvc / configmap / secret / rbac / rolebinding 等资源，残留会造成权限与数据困惑，需要逐一核对
- drain 前必须先查 PDB（`kubectl get pdb -A`）与节点上的本地存储（local-path / hostPath / emptyDir 中是否有不可丢数据）
- `docker system prune -a --volumes` 会删除所有未被容器引用的镜像与数据卷；**有状态容器（MySQL 等）停机瞬间，其卷就成了「未使用」**，执行前先 `docker volume ls` 人工核对
- 在跳板机 / 堡垒机上批量操作前，先确认当前集群：`kubectl config current-context`

---

## 九、速查表

### Docker

| 场景 | 命令 |
|---|---|
| 停掉所有容器 | `docker stop $(docker ps -q)` |
| 删所有已退出容器 | `docker rm $(docker ps -aq --filter status=exited)` |
| 删悬空镜像 | `docker image prune -f` |
| 按名称批量删容器 | `docker rm -f $(docker ps -aq --filter "name=web-")` |
| 一键大扫除 | `docker system prune -af` |
| 批量导出镜像 | `docker save -o all.tar $(docker images --format '{{.Repository}}:{{.Tag}}' \| grep -v '<none>')` |
| 进最近启动的容器 | `docker exec -it $(docker ps -lq) sh` |
| 看容器资源占用 | `docker stats --no-stream` |
| 磁盘占用大户 | `docker system df -v` |

### Kubernetes

| 场景 | 命令 |
|---|---|
| 全集群 Pod 总览 | `kubectl get po -A -o wide` |
| 全集群告警事件 | `kubectl get events -A --field-selector type=Warning` |
| 删某命名空间全部 Pod | `kubectl delete pods --all -n test` |
| 按标签删多类资源 | `kubectl delete deploy,svc -l app=old -n prod` |
| 批量滚动重启 | `kubectl rollout restart deploy -n app` |
| 批量缩容到 1 | `kubectl scale deploy --all --replicas=1 -n test` |
| 清理失败 / 被驱逐 Pod | `kubectl delete pods -A --field-selector=status.phase=Failed` |
| 清理已完成 Pod | `kubectl delete pods -A --field-selector=status.phase=Succeeded` |
| 某节点上有哪些 Pod | `kubectl get pods -A --field-selector=spec.nodeName=<node> -o wide` |
| 节点维护三步 | `kubectl cordon` → `kubectl drain --ignore-daemonsets --delete-emptydir-data` → `kubectl uncordon` |
| 盘点在用的镜像 | `kubectl get pods -A -o jsonpath='{.items[*].spec.containers[*].image}' \| tr ' ' '\n' \| sort -u` |
| 快速生成 YAML | `kubectl create deploy web --image=nginx --dry-run=client -o yaml` |

---

## 相关文档

- [k8s-常用操作手册](k8s-常用操作手册.md) — 单资源常规操作（标签、亲和性、调度、探针等）
- [Docker-Build从入门到高级](Docker-Build从入门到高级.md) — 镜像构建、多阶段构建、BuildKit
- [Kubernetes-从入门到生产实践：组件资源与常用操作指南](Kubernetes-从入门到生产实践：组件资源与常用操作指南.md)
- [kubectl 快捷工具 k](../脚本与工具/kubectl/kubectl-快捷工具-k.md) — 本项目封装的 `k` 快捷脚本
