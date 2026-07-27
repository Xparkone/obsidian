# K3s 部署指南

> 最后更新：2026-07-15 · 版本：v1.32+ · 项目：CNCF Sandbox

---

## 一、什么是 K3s

K3s 是 **Rancher (SUSE)** 推出的轻量级 Kubernetes 发行版，CNCF 沙箱项目。一句话概括：**打包成单个二进制文件（<100MB）、内存占用减半、5 分钟就能跑起来的完整 K8s。**

### K3s vs K8s

| 对比维度 | 标准 K8s (kubeadm) | K3s |
|----------|-------------------|-----|
| **二进制大小** | 数百 MB（多组件分散） | <100 MB（单个二进制） |
| **内存占用** | ~1GB+ | ~512MB |
| **默认存储** | etcd | **SQLite**（也可选 etcd/MySQL/PostgreSQL） |
| **安装复杂度** | 多步骤、多组件 | **一条命令** |
| **内置组件** | 需手动安装 CNI、Ingress 等 | 内置 Flannel、Traefik、CoreDNS、Metrics Server |
| **适用场景** | 生产大规模集群 | Edge / IoT / ARM / CI / 开发环境 |

### K3s 内置组件一览

| 组件 | 用途 | 可替换 |
|------|------|--------|
| **containerd** | 容器运行时 | ✅ |
| **Flannel** | CNI 网络插件 | ✅ (Calico/Cilium) |
| **CoreDNS** | 集群 DNS | ✅ |
| **Traefik** | Ingress Controller | ✅ (Nginx) |
| **Metrics Server** | 资源监控 | ✅ |
| **Klipper-lb** | Service LoadBalancer | ✅ (MetalLB) |
| **Local Path Provisioner** | 本地存储卷 | ✅ |
| **Helm Controller** | CRD 驱动 Helm 部署 | ✅ |

---

## 二、安装部署

### 2.1 前置要求

| 节点类型 | 最低配置 | 推荐配置 |
|----------|----------|----------|
| **Server (控制平面)** | 1 CPU, 512MB RAM | 2 CPU, 2GB RAM |
| **Agent (工作节点)** | 1 CPU, 256MB RAM | 1 CPU, 1GB RAM |

- 操作系统：Linux (主流发行版均可，kernel 需支持 cgroup)
- 每台机器 **hostname 必须唯一**
- 端口：6443 (API Server) 需开放

### 2.2 单节点部署（最简）

```bash
# 一条命令安装 K3s Server
curl -sfL https://get.k3s.io | sh -

# 安装完成后：
# - K3s 作为 systemd 服务自动启动
# - kubeconfig 写入 /etc/rancher/k3s/k3s.yaml
# - kubectl、crictl 等工具一并安装

# 验证集群
sudo kubectl get nodes
# NAME          STATUS   ROLES                  AGE   VERSION
# ubuntu        Ready    control-plane,master   60s   v1.32.3+k3s1

# 查看所有 Pod
sudo kubectl get pods -A
```

### 2.3 多节点集群部署

**架构示意：**
```
┌─────────────────────────────────────────────────┐
│  Server Node (控制平面)                          │
│  ┌─────────┐  ┌──────────┐  ┌────────────────┐ │
│  │ API     │  │ Scheduler│  │ Controller     │ │
│  │ Server  │  │          │  │ Manager        │ │ │
│  └─────────┘  └──────────┘  └────────────────┘ │
│  ┌─────────────────────────────────────────────┐│
│  │  SQLite / etcd (数据存储)                    ││
│  └─────────────────────────────────────────────┘│
└──────────────┬──────────────────────────────────┘
               │
    ┌──────────┴──────────┐
    │                     │
┌───▼────────┐   ┌───────▼───────┐
│ Agent Node │   │ Agent Node    │
│ (Worker)   │   │ (Worker)      │
│ ┌────────┐ │   │ ┌───────────┐ │
│ │ kubelet│ │   │ │ kubelet   │ │ │
│ │ +Pod   │ │   │ │ +Pod      │ │ │
│ └────────┘ │   │ └───────────┘ │
└────────────┘   └───────────────┘
```

**步骤 1：部署 Server 节点**

```bash
# 在 Server 机器上
curl -sfL https://get.k3s.io | sh -

# 获取 Token（Agent 加入时需要）
sudo cat /var/lib/rancher/k3s/server/node-token
# 输出类似：K1012345678abcdef::server:mysecrettoken

# 获取 Server IP
hostname -I | awk '{print $1}'
```

**步骤 2：加入 Agent 节点**

```bash
# 在每台 Agent 机器上执行
curl -sfL https://get.k3s.io | \
  K3S_URL=https://<SERVER_IP>:6443 \
  K3S_TOKEN=<TOKEN> \
  sh -

# 参数说明：
# K3S_URL   - Server 的 API 地址
# K3S_TOKEN - 从 Server 的 /var/lib/rancher/k3s/server/node-token 获取
```

**步骤 3：在 Server 上验证**

```bash
sudo kubectl get nodes
# NAME          STATUS   ROLES                  AGE   VERSION
# server-node   Ready    control-plane,master   10m   v1.32.3+k3s1
# agent-node1   Ready    <none>                 5m    v1.32.3+k3s1
# agent-node2   Ready    <none>                 5m    v1.32.3+k3s1
```

### 2.4 高可用部署（Embedded etcd）

3 台 Server 节点组成 etcd 集群，实现控制平面高可用。

```bash
# 第一台 Server（初始化 etcd 集群）
curl -sfL https://get.k3s.io | \
  sh -s - server --cluster-init

# 第二、三台 Server（加入 etcd 集群）
curl -sfL https://get.k3s.io | \
  K3S_TOKEN=<TOKEN> \
  sh -s - server --server https://<FIRST_SERVER_IP>:6443

# Agent 节点加入方式不变
curl -sfL https://get.k3s.io | \
  K3S_URL=https://<ANY_SERVER_IP>:6443 \
  K3S_TOKEN=<TOKEN> \
  sh -
```

### 2.5 高可用部署（外部数据库）

使用 MySQL/PostgreSQL 代替嵌入式 etcd：

```bash
# 所有 Server 节点共享同一个外部数据库
curl -sfL https://get.k3s.io | \
  sh -s - server \
  --datastore-endpoint="mysql://k3suser:k3spass@tcp(192.168.1.100:3306)/k3s"
```

### 2.6 离线安装（Air-Gap）

```bash
# 1. 在有网的机器上下载
wget https://github.com/k3s-io/k3s/releases/download/v1.32.3+k3s1/k3s
wget https://github.com/k3s-io/k3s/releases/download/v1.32.3+k3s1/k3s-airgap-images-amd64.tar.gz
wget https://get.k3s.io -O install.sh

# 2. 复制到离线机器
scp k3s install.sh k3s-airgap-images-amd64.tar.gz root@offline-host:/tmp/

# 3. 在离线机器上安装
sudo mkdir -p /var/lib/rancher/k3s/agent/images/
sudo cp /tmp/k3s-airgap-images-amd64.tar.gz /var/lib/rancher/k3s/agent/images/
sudo cp /tmp/k3s /usr/local/bin/
sudo chmod +x /usr/local/bin/k3s
sudo INSTALL_K3S_SKIP_DOWNLOAD=true /tmp/install.sh
```

---

## 三、配置方式

K3s 支持三种配置方式，优先级从高到低：

### 3.1 配置文件（推荐）

```bash
# /etc/rancher/k3s/config.yaml
write-kubeconfig-mode: "0644"
tls-san:
  - "k3s.example.com"
  - "192.168.1.10"
node-label:
  - "env=production"
  - "role=server"
cluster-init: true
disable:
  - traefik        # 禁用内置 Traefik
  - servicelb      # 禁用内置 ServiceLB
```

### 3.2 环境变量

```bash
# 所有 CLI flag 都有对应的环境变量
# 格式：K3S_<FLAG>，横线转下划线，大写
export K3S_TOKEN="mysecret"
export K3S_KUBECONFIG_MODE="644"
export K3S_DATASTORE_ENDPOINT="mysql://..."
k3s server
```

### 3.3 CLI 参数

```bash
k3s server \
  --write-kubeconfig-mode 644 \
  --tls-san k3s.example.com \
  --disable traefik \
  --flannel-backend wireguard-native
```

---

## 四、常用操作

### 4.1 kubectl 配置

```bash
# 方式一：sudo 使用
sudo kubectl get nodes

# 方式二：复制 kubeconfig 到用户目录（推荐）
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config

# 之后无需 sudo
kubectl get nodes

# 远程访问：修改 server 地址
sed -i 's/127.0.0.1/<SERVER_IP>/' ~/.kube/config
```

### 4.2 部署第一个应用

```bash
# 创建 Nginx Deployment
kubectl create deployment nginx --image=nginx:alpine --replicas=2

# 暴露为 Service
kubectl expose deployment nginx --port=80 --type=NodePort

# 查看访问地址
kubectl get svc nginx
# NAME    TYPE       CLUSTER-IP     PORT(S)        AGE
# nginx   NodePort   10.43.120.55   80:30080/TCP   10s

# 访问：http://<任意节点IP>:30080
```

### 4.4 服务管理

```bash
# 查看 K3s 服务状态
sudo systemctl status k3s        # Server
sudo systemctl status k3s-agent  # Agent

# 重启
sudo systemctl restart k3s

# 查看日志
sudo journalctl -u k3s -f
```

### 4.5 升级

```bash
# 使用安装脚本升级（自动检测当前版本）
curl -sfL https://get.k3s.io | sh -

# 升级到指定版本
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.32.3+k3s1 sh -

# 手动升级
wget https://github.com/k3s-io/k3s/releases/download/v1.32.3+k3s1/k3s
sudo cp k3s /usr/local/bin/k3s
sudo systemctl restart k3s
```

### 4.6 卸载

```bash
# Server 卸载
sudo /usr/local/bin/k3s-uninstall.sh

# Agent 卸载
sudo /usr/local/bin/k3s-agent-uninstall.sh
```

---

## 五、常用配置项速查

### Server 常用配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `--token` | 集群 Token（自动生成） | 随机 |
| `--tls-san` | 证书 SAN（可重复） | — |
| `--cluster-init` | 初始化 etcd 集群 | false |
| `--disable traefik` | 禁用内置 Traefik | — |
| `--disable servicelb` | 禁用内置 ServiceLB | — |
| `--flannel-backend` | CNI 后端：vxlan/ipsec/host-gw/wireguard-native | vxlan |
| `--node-taint` | 节点污点 | — |
| `--write-kubeconfig-mode` | kubeconfig 权限 | 600 |
| `--datastore-endpoint` | 外部数据库连接串 | — |
| `--etcd-expose-metrics` | 暴露 etcd 指标 | false |

### Agent 常用配置

| 配置项 | 说明 |
|--------|------|
| `K3S_URL` | Server 地址 |
| `K3S_TOKEN` | 集群 Token |
| `--node-label` | 节点标签 |

---

## 六、常见场景实战

### 6.1 用 Multipass 本地搭建 K3s 集群

```bash
# 创建 3 台 VM
multipass launch 24.04 --name k3s-server --cpus 2 --memory 4G --disk 20G
multipass launch 24.04 --name k3s-agent1 --cpus 1 --memory 2G
multipass launch 24.04 --name k3s-agent2 --cpus 1 --memory 2G

# 在 Server 上安装 K3s
multipass exec k3s-server -- bash -c "curl -sfL https://get.k3s.io | sh -"

# 获取 Token 和 IP
TOKEN=$(multipass exec k3s-server -- sudo cat /var/lib/rancher/k3s/server/node-token)
SERVER_IP=$(multipass info k3s-server | grep IPv4 | awk '{print $2}')

# Agent 加入
multipass exec k3s-agent1 -- bash -c \
  "curl -sfL https://get.k3s.io | K3S_URL=https://$SERVER_IP:6443 K3S_TOKEN=$TOKEN sh -"

multipass exec k3s-agent2 -- bash -c \
  "curl -sfL https://get.k3s.io | K3S_URL=https://$SERVER_IP:6443 K3S_TOKEN=$TOKEN sh -"

# 验证
multipass exec k3s-server -- sudo kubectl get nodes
```

### 6.2 替换 CNI 为 Calico

```bash
# 安装时禁用 Flannel
curl -sfL https://get.k3s.io | \
  sh -s - server --flannel-backend none

# 安装 Calico
kubectl apply -f https://docs.projectcalico.org/manifests/calico.yaml
```

### 6.3 替换 Ingress 为 Nginx

```bash
# 安装时禁用 Traefik
curl -sfL https://get.k3s.io | \
  sh -s - server --disable traefik

# 安装 Nginx Ingress
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.0/deploy/static/provider/cloud/deploy.yaml
```

### 6.4 启用内置 Registry 镜像缓存

```bash
# /etc/rancher/k3s/registries.yaml
mirrors:
  docker.io:
    endpoint:
      - "https://mirror.gcr.io"
      - "https://registry-1.docker.io"
  "*":
    endpoint:
      - "http://192.168.1.100:5000"
```

---

## 七、与 K8s 学习路径的关系

对照你的 [18 周学习计划](../学习/18周每日学习计划.md)，K3s 是极佳的 K8s 学习工具：

| 学习周 | 主题 | K3s 如何配合 |
|--------|------|-------------|
| Week 1 | Pod 生命周期 | `kubectl run` 快速起 Pod 观察状态 |
| Week 2 | Controller 详解 | Deployment 滚动更新、回滚实验 |
| Week 3 | Service 网络 | ClusterIP/NodePort/LoadBalancer 实战 |
| Week 4 | 存储 | Local Path Provisioner 自动创建 PV |
| Week 5+ | Ingress / Helm / 监控 | 替换 Traefik、装 Prometheus |

**优势：** 不需要 minikube 的虚拟机嵌套，K3s 直接跑在 Multipass VM 里，资源利用率高，跟生产环境一致。

---

## 八、快速参考卡片

```
┌─ 安装 ────────────────────────────────────────┐
│ # Server（单节点）                              │
│ curl -sfL https://get.k3s.io | sh -             │
│                                                 │
│ # Agent（加入集群）                              │
│ curl -sfL https://get.k3s.io | \                │
│   K3S_URL=https://<IP>:6443 \                   │
│   K3S_TOKEN=<TOKEN> sh -                        │
│                                                 │
│ # HA（etcd）                                    │
│ curl -sfL https://get.k3s.io | \                │
│   sh -s - server --cluster-init                 │
├─ 管理 ────────────────────────────────────────┤
│ sudo kubectl get nodes          # 查看节点      │
│ sudo systemctl status k3s       # 服务状态      │
│ sudo journalctl -u k3s -f       # 查看日志      │
│ sudo cat /var/lib/rancher/k3s/  # 获取 Token    │
│        server/node-token                         │
├─ 配置 ────────────────────────────────────────┤
│ /etc/rancher/k3s/config.yaml    # 配置文件      │
│ /etc/rancher/k3s/k3s.yaml       # kubeconfig    │
│ /var/lib/rancher/k3s/           # 数据目录      │
├─ 卸载 ────────────────────────────────────────┤
│ sudo /usr/local/bin/k3s-uninstall.sh            │
└─────────────────────────────────────────────────┘
```

---

## 参考资料

- [K3s 官方文档](https://docs.k3s.io)
- [K3s GitHub](https://github.com/k3s-io/k3s)
- [快速入门](https://docs.k3s.io/quick-start)
- [架构说明](https://docs.k3s.io/architecture)
- [配置选项](https://docs.k3s.io/installation/configuration)