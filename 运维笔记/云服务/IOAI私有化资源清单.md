# IOAI 私有化资源清单

## 火山云

### 生产账号

#### 负载均衡

**CLB-xeVL**

- ID：`clb-13g4rn4d1cum83n6nu4yqfe2o`
- 公网：`124.174.49.32`
- 公网带宽上限：100 Mbps

| 名称 | 协议 | 端口 | 后端服务器组 |
|------|------|------|----------------|
| TCP-32477 | TCP | 32477 | centre-service |
| TCP-30080 | TCP | 30080 | nfsmanager-service |
| TCP-30081 | TCP | 30081 | storage-manager-service |
| TCP-30630 | TCP | 30630 | tiefblue |
| TCP-30083 | TCP | 30083 | tiefblue-nas-search-service |
| nginx | TCP | 9081 | nginx |
| k8s_bf10d31c45f8456f8167250bc8628e30_4321 | TCP | 4321 | k8s_bf10d31c45f8456f8167250bc8628e30_4321 |

**ioai-clb-common**

- ID：`clb-miznhoekrthc5smt1ap337hv`
- 公网：`101.126.29.131`
- 公网带宽上限：1000 Mbps

| 名称 | 协议 | 端口 | 后端服务器组 |
|------|------|------|----------------|
| minio-9000 | TCP | 9000 | minio-9000 |
| nginx | TCP | 443 | nginx |
| lbg-9081 | TCP | 9081 | lbg-9081 |

**sandbox-ioai**

- ID：`clb-rrnl9kx6oum8v0x5786mpfu`
- 公网：`101.126.159.230`
- 公网带宽上限：500 Mbps

#### Kubernetes

| 字段 | 值 |
|------|----|
| 实例 ID | ioai |
| 实例名称 | ccvq87jb0mbf393fvitl0 |
| Kubernetes 版本 | v1.24.17-vke.39 |

#### 镜像仓库

- `dp-harbor-registry.cn-zhangjiakou.cr.aliyuncs.com`
- `harbor.private.dplink.cc`
  - 实例名称：ioai-harbor
  - 地域：华北2

#### MySQL

| 字段 | 值 |
|------|----|
| 实例 ID | mysql-8bb650d727c2 |
| 实例名称 | ioai-mysql |
| 存储类型 | 本地 SSD |
| 实例类型 | 双节点 |
| 数据库版本 | MySQL 8.0.32_20241215（已开启小版本升级策略） |
| 引擎类型 | InnoDB |
| 主节点规格 | 4 核 8 GB（rds.mysql.d1.n.4c8g） |
| 磁盘使用量 | 已使用 12.69 GiB / 总计 100 GiB（2026-10-10 记录） |
| 全量备份保留期 | 7 |
| Binlog 日志备份 | 已开启 |
| 全量备份周期 | 周一，周三，周六 |

#### Nacos

| 字段 | 值 |
|------|----|
| 实例 ID | ncvidnpmlhht60sqvac3g |
| 实例名称 | ioai-nacos |
| 存储类型 | Nacos / 2.2.4.10 |
| 节点数量 | 3 |
| 性能规格 | 2 核 4 GB |
| 控制台地址 | https://console.volcengine.com/mse/nacos/cn-beijing/ncvidnpmlhht60sqvac3g |
| 公网地址 | 101.126.5.227 |
| 私网地址 | 10.180.0.16 |

## 腾讯云

### 测试账号

| 名称 | 公网 IP | 实例 ID | 状态 |
|------|---------|---------|------|
| 中山大学化学语料项目 | 118.195.218.139 | ins-k66k3k4n8 | 运行中 |
| 厦门大学01 | 118.195.222.113 | ins-56ryeutg | 运行中 |
| 厦门大学02 | 43.137.4.185 | ins-bg54rblg | 运行中 |
| 厦门大学03 | 119.45.194.198 | ins-llym51je | 运行中 |
| 厦门大学04-gpu | 43.137.6.211 | ins-lpwrj4q | 运行中 |
| 厦门大学-test1-马燕辰 | 118.195.195.247 | ins-3lsvkyr2 | 运行中 |
| 厦门大学-test2-马燕辰 | 146.56.240.62 | ins-2yulnogc | 运行中 |
| 材料数据库1 | 119.45.178.241 | ins-d3592sfc | 运行中 |
| 材料数据库2 | 118.195.193.152 | ins-kmwpylii | 运行中 |
| 材料数据库3 | 175.27.214.86 | ins-3b8uy86c | 运行中 |
| 帮普01 | 175.27.144.105 | ins-m5xr0gck | 运行中 |
| 帮普02 | 146.56.238.223 | ins-krmx0pce | 运行中 |
| 邦普03gpu | 119.45.92.242 | ins-kzk98yh8 | 运行中 |
| 郁正1 | 119.45.114.191 | ins-1z2180ly | 运行中 |
| 郁正2 | 1.13.168.93 | ins-kz8nzgxy | 运行中 |
| 郁正中间件 | 146.56.217.114 | ins-npv4xubm | 运行中 |
| 锂宝-1 | 118.195.155.4 | ins-cxwopylc | 已关机 |
| 锂宝-2 | 118.195.242.80 | ins-332b0puo | 已关机 |
| dify-ioail比赛 | 1.13.6.191 | ins-hbsaq6le | 运行中 |

## 阿里云

### 生产账号

### 测试账号

- 中科院：`101.200.219.174`
