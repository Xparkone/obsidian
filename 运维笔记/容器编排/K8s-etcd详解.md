# etcd 深入详解

> K8s 的「大脑记忆」— 集群所有状态数据的唯一来源  
> 创建时间：2026-07-13

---

## 一、etcd 是什么

etcd 是一个**分布式、高可用的键值存储系统**，K8s 用它来存储所有集群数据：

```
┌─────────────────────────────────────────────────────┐
│                    K8s 集群                           │
│                                                      │
│  kubectl apply -f deployment.yaml                    │
│         │                                            │
│         ▼                                            │
│  ┌───────────┐     写入       ┌──────────────┐      │
│  │ API Server │ ────────────→ │    etcd      │      │
│  └───────────┘     读取       │  (键值存储)   │      │
│         ▲         ◀────────── └──────────────┘      │
│         │                                            │
│  Controller / Scheduler / kubelet                    │
│  (通过 watch 监听变化)                                │
└─────────────────────────────────────────────────────┘
```

| 特性 | 说明 |
|------|------|
| **一致性** | 基于 Raft 共识算法，保证强一致性 |
| **高可用** | 3/5 节点集群，容忍少数节点故障 |
| **Watch 机制** | 客户端可以监听 key 的变化，K8s 控制器靠这个工作 |
| **MVCC** | 多版本并发控制，支持历史版本查询 |
| **TTL** | 支持 key 过期（Lease 机制） |

---

## 二、etcd 在 K8s 中的角色

### 2.1 存储了什么

K8s 把所有资源对象以 JSON 格式存储在 etcd 中，key 的格式为：

```
/registry/<资源类型>/<命名空间>/<资源名>
```

**示例：**

```
/registry/pods/default/nginx-7b9f8c5d6-x8k2m
/registry/deployments/default/nginx
/registry/services/default/nginx-svc
/registry/configmaps/default/nginx-config
/registry/secrets/default/tls-cert
/registry/namespaces/default
/registry/nodes/worker-01
```

### 2.2 数据流向

```
kubectl apply -f pod.yaml
        │
        ▼
  API Server 接收请求
        │
        ├── 认证（Authentication）
        ├── 鉴权（Authorization）  
        ├── 准入控制（Admission Control）
        │
        ▼
  写入 etcd ──────────────────────┐
        │                         │
        ▼                         │
  API Server 返回成功              │
                                  │
  Scheduler watch 到新 Pod ───────┘（通过 watch 机制）
        │
        ▼
  调度决策写入 etcd（通过 API Server）
        │
        ▼
  kubelet watch 到分配给自己的 Pod
        │
        ▼
  启动容器 → 更新 Pod 状态到 etcd
```

---

## 三、etcd 核心操作

### 3.1 基本 CRUD

```bash
# 写入键值
etcdctl put /mykey "hello etcd"

# 读取键值
etcdctl get /mykey

# 按前缀读取（K8s 中常用）
etcdctl get /registry/pods/ --prefix --keys-only

# 删除键
etcdctl del /mykey

# 按前缀删除（危险！）
etcdctl del /registry/ --prefix
```

### 3.2 Watch 监听

这是 K8s 控制器工作的核心机制：

```bash
# 监听单个 key 的变化
etcdctl watch /mykey

# 终端 A 执行 watch，终端 B 执行 put，A 会实时收到通知
```

**K8s 中的应用：**

```
Controller Manager 的 Deployment Controller:
  ┌──────────────────────────────────────┐
  │  watch /registry/deployments/  ───→  发现新建 Deployment
  │          │                            │
  │          ▼                            │
  │  创建 ReplicaSet ───→ 写入 etcd       │
  │          │                            │
  │          ▼                            │
  │  watch /registry/replicasets/ ───→   发现 ReplicaSet 创建
  │          │                            │
  │          ▼                            │
  │  创建 Pod ───→ 写入 etcd              │
  └──────────────────────────────────────┘
```

### 3.3 Lease（租约）

```bash
# 创建一个 30 秒的租约
etcdctl lease grant 30

# 用租约写入 key（租约到期后 key 自动删除）
etcdctl put /temp-key "value" --lease=<lease-id>

# 续约（keep-alive）
etcdctl lease keep-alive <lease-id>
```

**K8s 中的应用：**
- Node 心跳：kubelet 定期续约，租约过期则节点标记为 Unknown
- Leader 选举：Controller Manager 和 Scheduler 通过 Lease 做高可用

---

## 四、etcd 集群架构

### 4.1 Raft 共识算法

```
┌──────────────────────────────────────┐
│           etcd 集群 (3 节点)          │
│                                      │
│   ┌──────────┐    ┌──────────┐      │
│   │  Node 1  │    │  Node 2  │      │
│   │ (Leader) │◀──▶│(Follower)│      │
│   └────┬─────┘    └──────────┘      │
│        │                             │
│        │        ┌──────────┐         │
│        └───────▶│  Node 3  │         │
│                 │(Follower)│         │
│                 └──────────┘         │
│                                      │
│  写入流程：                          │
│  1. 客户端 → Leader 发起写请求        │
│  2. Leader → 所有 Follower 复制日志  │
│  3. 多数节点确认 → Leader 提交       │
│  4. Leader 返回客户端成功            │
└──────────────────────────────────────┘
```

**关键数字：**

| 集群大小 | 多数(Quorum) | 可容忍故障 | 说明 |
|:---:|:---:|:---:|------|
| 1 | 1 | 0 | 仅开发环境 |
| 3 | 2 | 1 | **生产推荐最小配置** |
| 5 | 3 | 2 | 更大容错 |
| 7 | 4 | 3 | 性能开始下降 |

> ❗ **为什么是奇数？** 偶数节点不会提高容错能力（4 节点容忍 1 个故障，和 3 节点一样），反而增加网络开销。

---

## 五、etcd 运维实战

### 5.1 查看 K8s 集群的 etcd 数据

```bash
# 方式一：通过 API Server 直接访问 etcd（需要进入 etcd 容器）
# 在 kubeadm 部署的集群中：
kubectl -n kube-system exec -it etcd-<master-node> -- sh

# 进入容器后：
export ETCDCTL_API=3
etcdctl \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  get / --prefix --keys-only

# 方式二：查看所有 Deployment
etcdctl get /registry/deployments/ --prefix --keys-only

# 方式三：查看 etcd 集群状态
etcdctl endpoint status --write-out=table
etcdctl endpoint health
etcdctl member list
```

### 5.2 etcd 备份与恢复

```bash
# == 备份 ==
# 备份到文件
ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-snapshot.db \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key

# 验证备份文件
etcdctl snapshot status /backup/etcd-snapshot.db

# == 恢复 ==
# 1. 停止所有 etcd 实例
# 2. 在每个 etcd 节点上恢复
etcdctl snapshot restore /backup/etcd-snapshot.db \
  --name=master-1 \
  --data-dir=/var/lib/etcd-restore \
  --initial-cluster="master-1=https://master-1:2380" \
  --initial-advertise-peer-urls="https://master-1:2380"

# 3. 修改 etcd.yaml 的 data-dir 指向新目录
# 4. 重启 etcd
```

### 5.3 碎片整理（Defragmentation）

etcd 长期运行后会产生空间碎片，需要定期整理：

```bash
# 查看碎片率
etcdctl endpoint status --write-out=table

# 整理碎片（会短暂阻塞请求）
etcdctl defrag

# 整理所有节点
etcdctl defrag --cluster

# 建议：碎片率超过 50% 或 DB 大小超过 2GB 时执行
```

### 5.4 告警处理

```bash
# 查看告警
etcdctl alarm list

# 常见告警：
# NOSPACE — 存储空间不足（默认 2GB 限制）
# 处理：先 compact + defrag，再解除告警
etcdctl compact <revision>
etcdctl defrag
etcdctl alarm disarm
```

### 5.5 性能调优

```yaml
# etcd 关键配置参数（kubeadm: /etc/kubernetes/manifests/etcd.yaml）
spec:
  containers:
  - command:
    - etcd
    - --quota-backend-bytes=8589934592    # 存储配额（默认 2GB，生产建议 8GB）
    - --snapshot-count=10000              # 多少次写操作后触发快照
    - --heartbeat-interval=100            # Raft 心跳间隔（ms）
    - --election-timeout=1000             # 选举超时（ms）
    - --auto-compaction-mode=periodic     # 自动压缩模式
    - --auto-compaction-retention=1h      # 保留 1 小时的历史版本
```

---

## 六、常见问题排查

| 问题现象 | 可能原因 | 排查命令 |
|---------|---------|---------|
| API Server 响应慢 | etcd 磁盘 IO 高 | `etcdctl endpoint status` 查看 DB 大小 |
| `etcdserver: mvcc: database space exceeded` | 存储空间满 | 执行 compact + defrag |
| 节点 NotReady | etcd Leader 频繁切换 | `etcdctl endpoint health` 检查网络延迟 |
| `context deadline exceeded` | etcd 过载或网络问题 | 检查磁盘 IOPS、网络延迟 |
| 集群不可写 | 超过半数节点故障 | `etcdctl member list` 确认存活节点数 |

---

## 七、速查命令

```bash
# 集群状态
etcdctl endpoint status --write-out=table
etcdctl endpoint health
etcdctl member list

# 数据操作
etcdctl get <key>                          # 读取
etcdctl get <prefix> --prefix --keys-only  # 按前缀列出所有 key
etcdctl put <key> <value>                  # 写入
etcdctl del <key>                          # 删除

# 备份恢复
etcdctl snapshot save <file>               # 备份
etcdctl snapshot status <file>             # 查看备份
etcdctl snapshot restore <file> --data-dir=<dir>  # 恢复

# 维护
etcdctl defrag                            # 碎片整理
etcdctl alarm list                        # 查看告警
etcdctl alarm disarm                      # 解除告警
etcdctl compact <revision>                # 压缩历史版本
```

---

## 八、关键要点

1. **etcd 是 K8s 的唯一数据源**，etcd 挂了 = 集群不可用（虽然已有 Pod 继续运行）
2. **生产环境最少 3 节点**，使用 SSD 磁盘，独立部署或与 Master 节点同机
3. **定期备份**，建议用 cronjob 每小时备份一次
4. **Watch 机制是 K8s 控制器模式的基础**，理解它就理解了 K8s 的工作原理
5. **不要手动修改 etcd 中的数据**，始终通过 API Server 操作