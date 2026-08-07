# MongoDB 由浅到深：运维与开发指南

## 1. 文档概述

- **解决什么问题**：系统梳理 MongoDB 从入门到进阶的知识体系，覆盖开发建模/查询/性能，以及运维部署/高可用/备份/监控两条主线。
- **适合哪些读者**：
  - 后端/全栈开发者（需要正确建模与高效查询）
  - 运维/SRE（需要搭建、保障可用性与容量）
  - 希望同时理解「怎么写」和「怎么跑」的工程师
- **阅读后能获得什么**：建立正确心智模型，掌握分阶段学习路径，能在本地完成 CRUD/索引/副本集基础实践，并知道生产环境的关键检查项。

> 核心结论：MongoDB 难的不是语法，而是**按查询路径建模**、**索引设计**，以及生产上的**副本集 + 备份 + 监控**。先把单机 CRUD 和索引学透，再上副本集；分片是最后手段，不要过早引入。

---

## 2. 前置条件

### 2.1 环境要求

| 项目 | 建议 |
|------|------|
| 操作系统 | macOS / Linux（生产多为 Linux） |
| MongoDB 版本 | 7.x 或 8.x（【需要确认】以你实际环境为准） |
| 客户端 | `mongosh`（官方 Shell） |
| 可选 | Docker / Docker Compose（便于搭副本集） |
| 驱动（开发） | 官方驱动：Node.js / Python / Java / Go 等 |

### 2.2 必备基础知识

- 熟悉 JSON 基本结构
- 了解数据库基本概念：增删改查、索引、主从/高可用
- 会用终端执行基础命令
- 开发侧建议具备一门后端语言与 HTTP/API 基础

### 2.3 官方资料

- 官方文档：<https://www.mongodb.com/docs/>
- 手册入口：安装、CRUD、Aggregation、Replica Set、Sharding、Security

---

## 3. 核心概念

### 3.1 MongoDB 是什么

MongoDB 是**文档型数据库**（Document Database）：数据以 **document**（文档，BSON/类 JSON）存储，而不是传统关系库的「行 + 列」。

| 关系库概念 | MongoDB 对应 |
|------------|--------------|
| Database | Database |
| Table | Collection（集合） |
| Row | Document（文档） |
| Column | Field（字段） |
| Index | Index |
| JOIN | 多用嵌入，或 `$lookup`（慎用为默认） |

层级关系：

```text
Database → Collection → Document → Field
```

### 3.2 适合与不适合

**较适合**：

- 半结构化、字段经常演进的业务
- 以「一个业务对象」为中心读写（用户、订单、内容实体）
- 需要较高写入吞吐、水平扩展潜力的场景

**不太适合 / 需谨慎**：

- 强依赖复杂多表 JOIN 与规范化设计
- 跨大量文档的强一致事务为主（虽支持多文档事务，但有成本）
- 报表型重度分析（可考虑配合专用分析引擎）

### 3.3 开发与运维各自关心什么

| 维度 | 开发关注 | 运维关注 |
|------|----------|----------|
| 数据 | 建模、查询、聚合 | 存储引擎、磁盘、备份 |
| 性能 | 索引、分页、投影字段 | 缓存、IOPS、连接数、慢查询 |
| 可用 | 重试、幂等、超时 | 副本集、选举、监控告警 |
| 扩展 | 分片键友好的访问模式 | 分片集群、均衡器、容量规划 |
| 安全 | 最小权限、输入校验 | 认证、TLS、审计、网络隔离 |

### 3.4 存储引擎（运维必知）

默认存储引擎是 **WiredTiger**：

- 文档级并发控制
- 压缩（减少磁盘占用）
- 内存中维护 cache；**工作集**（热数据 + 热索引）尽量放进内存是性能关键

---

## 4. 开发视角：由浅到深

### 4.1 L1：CRUD 与基本查询

**要做什么**：掌握增删改查与常用查询操作符。  
**为什么**：所有业务读写都建立在此之上。  
**预期结果**：能用 `mongosh` 完成基本数据操作。

```js
// 插入
db.users.insertOne({ name: "Alice", age: 28, tags: ["dev"] })
db.users.insertMany([{ name: "Bob", age: 30 }, { name: "Carol", age: 22 }])

// 查询
db.users.find({ age: { $gte: 18 } })
db.users.findOne({ name: "Alice" })

// 更新（推荐用更新操作符，避免整文档覆盖）
db.users.updateOne({ name: "Alice" }, { $set: { age: 29 } })
db.users.updateMany({ status: "pending" }, { $set: { status: "done" } })

// 删除
db.users.deleteOne({ name: "Bob" })
```

常用查询操作符：

- 比较：`$eq` / `$ne` / `$gt` / `$gte` / `$lt` / `$lte`
- 逻辑：`$and` / `$or` / `$not`
- 集合：`$in` / `$nin`
- 存在与类型：`$exists` / `$type`
- 数组：`$elemMatch` / `$all` / `$size`
- 文本：`$regex`（注意索引与性能）

### 4.2 L2：文档建模（开发分水岭）

**要做什么**：在「嵌入」与「引用」之间做正确取舍。  
**为什么**：建模错误会导致性能差、文档膨胀、更新困难。  
**预期结果**：能根据查询路径设计集合结构。

| 策略 | 何时用 | 例子 |
|------|--------|------|
| **嵌入（Embed）** | 一起读取、生命周期一致、不会无限增长 | 订单内嵌收货地址 |
| **引用（Reference）** | 一对多很大、多对多、独立更新频繁 | 用户与海量评论 |

建模原则：

1. **按查询路径建模**（how you query），不要照搬 ER 图。
2. 单文档尽量控制在合理大小（通常 KB 级；避免无界增长到 MB 级）。
3. 警惕无界数组（unbounded array），例如「用户所有事件」全塞进一个数组。
4. 热字段与冷字段可拆集合，降低读写放大。
5. 需要时用 Schema Validation（JSON Schema）做集合级约束。

嵌入示例：

```js
// 订单：地址随订单固化，适合嵌入
{
  _id: ObjectId("..."),
  userId: ObjectId("..."),
  amount: 19900,
  address: {
    province: "浙江",
    city: "杭州",
    detail: "XX 路 1 号"
  },
  items: [
    { sku: "A001", qty: 2, price: 9900 }
  ],
  createdAt: ISODate("2026-08-06T00:00:00Z")
}
```

引用示例：

```js
// 评论量大、独立分页 → 单独集合 + 引用
// posts 集合
{ _id: ObjectId("p1"), title: "Hello", authorId: ObjectId("u1") }

// comments 集合
{ _id: ObjectId("c1"), postId: ObjectId("p1"), content: "...", createdAt: ISODate("...") }
```

### 4.3 L3：索引（性能生死线）

**要做什么**：为高频查询/排序建立合适索引，并用 `explain` 验证。  
**为什么**：无索引会全表扫描（COLLSCAN），数据量大时延迟与 CPU 暴涨。  
**预期结果**：关键查询走 `IXSCAN`，扫描文档数接近返回数。

```js
// 唯一索引
db.users.createIndex({ email: 1 }, { unique: true })

// 复合索引（字段顺序很重要）
db.orders.createIndex({ userId: 1, createdAt: -1 })

// 文本索引 / 地理索引（按需）
db.products.createIndex({ name: "text" })
db.places.createIndex({ loc: "2dsphere" })
```

复合索引 **ESR 法则**：

1. **E**quality（等值条件）字段在前  
2. **S**ort（排序）字段其次  
3. **R**ange（范围条件）字段在后  

分析查询计划：

```js
db.orders.find({ userId: 1, createdAt: { $gte: ISODate("2026-01-01") } })
  .sort({ createdAt: -1 })
  .explain("executionStats")
```

注意：

- 索引加速读，但拖慢写；定期用 `$indexStats` 清理无用索引。
- 投影只取需要字段，减少网络与反序列化开销。
- 深分页少用大 `skip`，改用基于 `_id` / `createdAt` 的游标分页。

### 4.4 L4：聚合管道 Aggregation

**要做什么**：用管道做分组、统计、关联、多阶段变换。  
**为什么**：复杂统计与报表不宜在应用层硬拼大量查询。  
**预期结果**：能写出可维护的 `$match → $group → $sort` 类流水线。

```js
db.orders.aggregate([
  { $match: { status: "paid" } },                 // 尽早过滤
  { $group: { _id: "$userId", total: { $sum: "$amount" } } },
  { $sort: { total: -1 } },
  { $limit: 10 }
])
```

常用阶段：`$match`、`$project`、`$group`、`$sort`、`$limit`、`$lookup`、`$unwind`、`$facet`。

习惯：`$match` 尽量靠前，让后续阶段处理更少数据。

### 4.5 L5：一致性、事务与读写关注点

- **单文档操作是原子的**。
- **多文档事务**需要副本集或分片集群；有延迟、冲突与超时成本，不要滥用。
- 关键概念：
  - `writeConcern`：写成功需要多少节点确认（如 `majority`）
  - `readConcern`：读到的数据一致性级别
  - `readPreference`：从 primary 还是 secondary 读

经验规则：

- 资金/库存等关键写：`w: "majority"`（并评估 journal）
- 日志/埋点：可放宽以换吞吐
- 并发更新：用条件更新或版本号做乐观控制

### 4.6 L6：驱动与应用层实践

- 使用官方驱动与连接池，避免每次请求新建连接。
- 查询条件用驱动 API / 参数化对象，不要拼字符串。
- 设置合理超时、重试（仅对幂等操作或可安全重试的错误）。
- **Change Streams**：监听集合变更，做同步、通知、CDC。
- Schema 演进：文档加 `schemaVersion` 字段，兼容读写旧新格式。

---

## 5. 运维视角：由浅到深

### 5.1 L1：安装与基础运维

**要做什么**：会安装、配置、观察实例状态。  
**为什么**：所有高可用与备份都建立在稳定单实例认知上。  
**预期结果**：能启动 `mongod`，用 `mongosh` 连接，查看 `serverStatus`。

部署形态演进：

```text
单机开发 → Replica Set（生产标配） → Sharded Cluster（容量/吞吐不够时）
```

关键配置文件段（`mongod.conf` 概念示例）：

```yaml
storage:
  dbPath: /var/lib/mongo
systemLog:
  destination: file
  path: /var/log/mongodb/mongod.log
net:
  port: 27017
  bindIp: 127.0.0.1  # 生产改为内网 IP，并配合防火墙
# replication:
#   replSetName: rs0
# security:
#   authorization: enabled
```

常用观测命令：

```js
db.serverStatus()
db.currentOp()
db.stats()
```

命令行工具：`mongostat`、`mongotop`。

生产最低要求（基线）：

- 至少 **3 节点副本集**
- 开启认证，传输建议 TLS
- `bindIp` 限制、安全组/防火墙收紧
- 数据盘独立；Linux 上文件系统常见推荐为 XFS（【需要确认】以你们规范为准）

### 5.2 L2：副本集（高可用）

**要做什么**：搭建 Primary / Secondary，理解选举与复制。  
**为什么**：单机宕机不可接受；副本集是 MongoDB 生产标配。  
**预期结果**：杀掉 Primary 后能自动选举，业务可重连恢复。

角色：

- **Primary**：处理写（默认也处理读）
- **Secondary**：复制数据，可按需承担读
- **Arbiter**：只投票不存数据（生产数据节点场景通常不优先推荐）

运维要点：

- 心跳、选举超时、优先级（priority）、投票权（votes）
- Oplog：操作日志窗口决定 Secondary 可落后多久；过小可能导致需要重建
- 监控：`rs.status()`、复制延迟、选举次数
- 读写分离用 `readPreference`，但要接受可能读到稍旧数据

初始化概念（示意）：

```js
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo1:27017" },
    { _id: 1, host: "mongo2:27017" },
    { _id: 2, host: "mongo3:27017" }
  ]
})
rs.status()
```

### 5.3 L3：分片（水平扩展）

**要做什么**：理解何时分片、组件职责与分片键选型。  
**为什么**：单副本集磁盘/CPU/连接打满时，需要水平拆分。  
**预期结果**：能判断「还不需要分片」或「分片键该怎么选」。

组件：

- `mongos`：路由层
- Config Server：元数据
- Shard：每个分片本身通常是一个副本集

分片键（shard key）原则：

- 基数高、写入尽量均匀
- 查询条件尽量带上分片键，避免散射查询
- 避免纯单调递增键造成热点（可评估 hashed）
- **选错代价极高**，上线前务必压测与评审

### 5.4 L4：备份与恢复

**要做什么**：建立可恢复的备份策略并定期演练。  
**为什么**：只备份不恢复等于没有备份。  
**预期结果**：能在演练环境完成一次完整恢复。

常见方案：

1. 文件系统/云盘快照（注意一致性）
2. `mongodump` / `mongorestore`（逻辑备份，适合中小规模）
3. Ops Manager / Cloud Manager / Atlas 连续备份
4. 延迟节点（delayed secondary）缓解误删误操作

```bash
# 逻辑备份示例
mongodump --uri="mongodb://user:pass@host:27017" --out=/backup/2026-08-06

# 恢复示例
mongorestore --uri="mongodb://user:pass@host:27017" /backup/2026-08-06
```

### 5.5 L5：监控、性能与容量

必看指标：

- 连接数、全局锁/排队、当前慢操作
- WiredTiger cache 使用率与驱逐
- 磁盘延迟 / IOPS / 空间
- 复制延迟、Oplog 窗口
- 慢查询（profiler 或托管平台顾问）

调优方向：

- 让工作集尽量进入内存
- 使用 SSD/NVMe，避免嘈杂邻居盘
- 应用侧控制连接池大小
- 拆分热点文档，避免单文档更新风暴

### 5.6 L6：安全与合规

- SCRAM 认证 + 最小权限角色
- 网络隔离、IP 白名单、禁止公网裸奔
- TLS；静态加密按合规要求开启
- 审计日志（如有合规需求）
- 定期轮换密码/密钥，关闭不必要接口与过高权限账号

---

## 6. 完整示例：本地「用户-订单」小练习

以下示例可在本地单机 MongoDB 上直接练习（开发向），并为后续副本集演练打基础。

### 6.1 准备数据

```js
use shop

db.users.insertMany([
  { _id: 1, name: "Alice", email: "alice@example.com", level: "vip" },
  { _id: 2, name: "Bob", email: "bob@example.com", level: "normal" }
])

db.orders.insertMany([
  { userId: 1, amount: 100, status: "paid", createdAt: ISODate("2026-08-01T10:00:00Z") },
  { userId: 1, amount: 50, status: "paid", createdAt: ISODate("2026-08-02T11:00:00Z") },
  { userId: 2, amount: 80, status: "pending", createdAt: ISODate("2026-08-03T09:00:00Z") }
])
```

### 6.2 建索引并验证

```js
db.users.createIndex({ email: 1 }, { unique: true })
db.orders.createIndex({ userId: 1, createdAt: -1 })

db.orders.find({ userId: 1 }).sort({ createdAt: -1 }).explain("executionStats")
// 预期：winningPlan 中出现 IXSCAN，而非 COLLSCAN
```

### 6.3 聚合统计用户消费

```js
db.orders.aggregate([
  { $match: { status: "paid" } },
  { $group: { _id: "$userId", total: { $sum: "$amount" }, cnt: { $sum: 1 } } },
  { $sort: { total: -1 } }
])
// 预期：Alice(userId=1) total=150, cnt=2
```

### 6.4 运维向下一步（可选）

用 Docker Compose 拉起三节点，执行 `rs.initiate`，然后：

1. 写入几条订单  
2. 停止 Primary 容器  
3. 观察选举与应用重连  
4. 做一次 `mongodump` → 新环境 `mongorestore`

---

## 7. 常见问题与排查

| 现象 | 可能原因 | 解决方法 |
|------|----------|----------|
| 查询突然变慢 | 无索引 / 索引失效 / 数据量暴涨 / 工作集超出内存 | `explain` 看是否 COLLSCAN；补索引；扩内存或冷热分离 |
| 写入变慢 | 索引过多、磁盘慢、`w:majority` 延迟、锁竞争 | 查磁盘延迟与复制延迟；减少无用索引；评估 writeConcern |
| Secondary 一直落后 | 网络差、磁盘慢、负载高、Oplog 太小 | 扩 IOPS；增大 oplog；排查慢查询 |
| 连接数打满 | 连接泄漏、池过大、突发流量 | 限制池大小；修泄漏；加中间层限流 |
| 磁盘将满 | 未清理、索引膨胀、journal/oplog 过大 | 扩容；清理；检查增长来源 |
| 事务频繁 abort | 冲突高、事务过大过久 | 缩小事务范围；降冲突；改为单文档建模 |
| 认证失败 | 用户库不对、机制不匹配、权限不足 | 确认 `authSource`、角色与连接串 |

慢查询定位示意：

```js
// 谨慎在生产开启，注意采样与开销
db.setProfilingLevel(1, { slowms: 100 })
db.system.profile.find().sort({ ts: -1 }).limit(5)
```

---

## 8. 注意事项与最佳实践

1. **生产必须副本集**，不要单机裸奔关键业务。
2. **先优化查询与索引，再谈分片**；分片键评审要严肃。
3. **建模优先于微优化**：嵌入/引用选错，索引再多也难救。
4. **备份必须可恢复**：定期演练 restore。
5. **安全默认关闭公网访问**，最小权限、强制认证。
6. **关注工作集与磁盘延迟**，这是性能的两大物理底座。
7. **多文档事务按需使用**，能单文档原子完成的不要上事务。
8. **版本与 FCV**（featureCompatibilityVersion）升级前读发行说明，走滚动升级。

开发与运维交叉必懂：

- Write/Read Concern 如何影响正确性与延迟  
- Schema 演进与双写/兼容读  
- 容量规划：数据 + 索引 + oplog + 余量  
- 典型故障：Primary 宕机、网络分区、磁盘满、Oplog 被冲掉  

---

## 9. 推荐学习路径

| 阶段 | 目标 | 练习 |
|------|------|------|
| 第 1 周 | CRUD + 查询 + 聚合入门 | 完成本文「用户-订单」示例 |
| 第 2 周 | 索引 + `explain` + 建模 | 故意制造慢查询再优化 |
| 第 3 周 | 副本集 | 三节点 failover 演练 |
| 第 4 周 | 备份恢复 + 监控指标 | dump/restore；看 `rs.status` / 延迟 |
| 第 5–6 周 | 事务 / Change Streams / 分片概念 | 驱动写小事务；弄清何时该分片 |
| 持续 | 官方文档 + 生产案例 | 关注 WiredTiger、慢查询、分片键 |

---

## 10. 总结

- MongoDB 的核心是 **文档模型 + 查询路径驱动的设计**。  
- 开发侧优先掌握：**CRUD → 建模 → 索引/explain → 聚合 → 事务与驱动实践**。  
- 运维侧优先掌握：**单机配置 → 副本集 → 备份恢复 → 监控容量 → 安全；分片最后上**。  
- 两边交汇点是：**一致性级别、性能（内存/磁盘/索引）、可用性与可恢复性**。

### 下一步建议

1. 本地安装 MongoDB / 用 Docker 跑单机，把第 6 节示例跑通。  
2. 用 Docker Compose 搭三节点副本集，做一次主节点故障切换。  
3. 结合你实际业务选一个集合，做建模评审 + 索引评审 + `explain` 留档。  
4. 若需要，可继续补充专题文档：  
   - 《Docker Compose 三节点副本集实验》  
   - 《订单域建模与聚合实战》  
   - 《生产部署 Checklist（配置/监控/备份/告警）》

---

## 附录 A：开发速查

```js
// 分页（游标）
db.orders.find({ userId: 1, _id: { $gt: lastId } }).sort({ _id: 1 }).limit(20)

// 条件更新（乐观）
db.products.updateOne(
  { _id: 1, stock: { $gte: 1 } },
  { $inc: { stock: -1 } }
)

// 查看索引
db.orders.getIndexes()
```

## 附录 B：运维速查

```js
rs.status()
rs.printSecondaryReplicationInfo()
db.serverStatus().connections
db.currentOp({ "active": true, "secs_running": { $gt: 5 } })
```

```bash
mongostat --uri="mongodb://127.0.0.1:27017"
mongotop  --uri="mongodb://127.0.0.1:27017"
```
