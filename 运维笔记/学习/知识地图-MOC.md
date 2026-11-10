# 知识地图 · MOC（Map of Content）

> 生成时间：2026-11-10
> 笔记总数：**160 篇**（不含 `.obsidian`）
> 用途：整个知识库的**唯一入口**。不知道从哪篇看起时，从这张图找人。
> 所属计划：[[Week18-总结与输出-每日安排]] 周二任务

---

## 怎么用这张图

三种找法，按你当下的状态选：

| 你的状态 | 用哪一节 |
|---|---|
| 「我知道要做什么，但不知道笔记里有没有」 | 直接 `Cmd+F` 搜关键词，或看下表 |
| 「我想系统过一遍某个领域」 | 按下面的**八大主题**顺序读，每节内部已按学习顺序排 |
| 「我遇到具体故障了」 | 跳到 [[#故障速查：从症状找笔记]] |

**每个主题内部的排列逻辑**：先总览 → 再机制 → 再工具 → 最后生产实践。带 ⭐ 的是该主题里质量最高、可反复查的几篇。

---

## 主题总览

| 主题 | 篇数 | 一句话定位 |
|---|---:|---|
| 一、云原生与容器 | 43 | 主战场。K8s 精通路线 10 章 + Docker/Helm/Istio + 网络 + 存储 |
| 二、CI/CD 与 GitOps | 32 | 从 Git 到流水线到 Argo CD 的完整交付链 |
| 三、SRE 与可观测性 | 24 | 监控 / 日志 / 追踪三支柱 + 主机排障工具 |
| 四、数据与中间件 | 11 | MySQL / PG / Mongo / Redis 速查与深挖 + Nacos + MQ 选型 |
| 五、AI 与开发 | 21 | LLM 原理、MCP/Skill 协议、Python/Go 工程化、自研项目 |
| 六、云平台与基础设施 | 11 | 虚拟化、HCI、GPU 硬件栈、公有云产品对照、Terraform |
| 七、安全 | 5 | 权限模型、防火墙、DDoS/WAF、真实入侵处置 |
| 八、学习路线与计划 | 6 | 路线总纲、18 周计划、Week 18 安排 |
| 根目录 | 2 | 库索引 + Codex 交接 |

---

# 一、云原生与容器（43 篇）

## 1.1 先建立全局图景

- [[K8s-定义]] — 官方解释 + 餐厅类比，给完全没接触过的人讲清 K8s 是什么
- ⭐ [[Kubernetes-从入门到生产实践：组件资源与常用操作指南]] — 一篇打通「组件→资源→操作」，新人第一篇读这个
- [[容器编排/k8s-architecture.excalidraw|K8s 架构全景图（Excalidraw）]] — 手绘风控制面/工作节点全景，贴给别人讲架构时用
- [[K8s-组件详解]] — 控制面（apiserver/scheduler/controller-manager/etcd）与节点侧（kubelet/kube-proxy/CNI）各自职责
- [[K8s-资源全览]] — 全部资源类型分类总览，当字典查

## 1.2 机制深入（K8s 精通路线 10 章）

这 10 篇是「不看文档也能推演行为」的核心，按依赖顺序排：

| # | 笔记 | 一句话定位 |
|---|---|---|
| 1 | ⭐ [[K8s-API机制深入]] | 一切控制循环都是 list-watch 把 status 拉向 spec |
| 2 | [[K8s-etcd详解]] | 集群唯一真相源：key 结构、quota、压缩、快照恢复 |
| 3 | ⭐ [[K8s-Pod生命周期详解]] | Init 容器、探针、重启策略、终止优雅期的完整时序 |
| 4 | ⭐ [[K8s-调度器深入]] | 一次性约束求解 + 持续 requeue 的妥协；亲和/污点/抢占 |
| 5 | ⭐ [[K8s-网络原理详解]] | 三件事：Pod 互通、Service 转发、外部进入；含 NetworkPolicy/Gateway API |
| 6 | ⭐ [[K8s-存储深入]] | PV/PVC/StorageClass/provisioner 三方分工与拓扑约束 |
| 7 | [[K8s-安全加固详解]] | CNCF 4C 模型逐层防御；RBAC/PSA/Seccomp/镜像签名 |
| 8 | [[K8s-自动伸缩深入]] | HPA/VPA/Cluster-Autoscaler 三个正交维度，各管各的 |
| 9 | [[K8s-Operator开发实战]] | CRD + controller + webhook 三者区别，避免写成「YAML 转换器」 |
| 10 | [[K8s-多集群与进阶生态]] | 多集群当一件事设计：集群联邦、多活、灾备 |

总纲见 [[K8s-精通路线-总纲]]（含 10 条验收标准与未勾选项）。

## 1.3 生产运维与排障

- ⭐ [[K8s-故障排查方法论]] — 声明式系统的排障顺序：先从 status/event 读意图，再下钻
- ⭐ [[K8s-生产集群运维手册]] — etcd 配额、证书轮转、升级顺序、kubelet 异常，黑盒集群里的事故处理
- [[K8s-排障进阶-5个冷门kubectl命令详解]] — 跨 ns 事件、无工具容器、抓活现场等疑难场景
- [[k8s-常用操作手册]] — 标签/亲和/驱逐等日常操作参考
- [[Docker-K8s-快捷批量操作手册]] — `-q --format --filter` 精准定位与批量操作

## 1.4 发行版与运行时

- [[K3s-部署指南]] — 单二进制、内存减半，5 分钟起集群；轻量环境首选
- [[Singularity-HPC容器平台详解]] — HPC 场景为什么不用 Docker，与 Docker 的能力对照

## 1.5 打包与部署

- ⭐ [[Helm-3-从入门到生产实践]] — Chart/Release/模板函数/依赖管理/生产注意事项
- [[Docker-Build从入门到高级]] — Dockerfile 指令、构建上下文、缓存、多阶段构建

## 1.6 流量入口与服务网格

- [[Kubernetes-Ingress-部署与使用详解]] — Ingress/IngressClass/Controller/Service 五者关系
- ⭐ [[Istio-服务网格详解]] — 数据面 Envoy + 控制面 xDS 的分工，流量治理/零信任/可观测
- [[Istio详细入门与实践指南]] — 面向第一次上手：安装、注入、灰度、熔断实操

## 1.7 扩展与生态组件

- [[Argo-项目详解]] — Workflows / CD / Rollouts / Events 四个子项目分工
- [[Velero-Kubernetes备份恢复与迁移指南]] — 资源对象 + PV 数据两类备份，迁移场景
- [[OpenKruise-原理作用使用与部署指南]] — 大规模发布/原地升级/可用性保护，超越原生 Deployment

## 1.8 网络基础（9 篇）

- ⭐ [[网络基础与进阶：从数据包到生产排障]] — 从一次 HTTPS 请求拆到 DNS/TCP/TLS/代理，排障主线
- [[DNS-详解]] — 递归/迭代查询、记录类型、TTL、常见解析故障
- [[domain-name-guide]] — 域名注册 → 改 NS → 加记录 → 验证的全流程实操
- ⭐ [[Nginx-完全指南]] — 反向代理、负载均衡、SSL、WebSocket、缓存、限流一网打尽
- [[nginx-lua-guide]] — 纯配置不够时的动态鉴权/灰度/改写 Header
- [[l4-vs-l7-proxy-guide]] — 四层与七层代理的理解深度差异与选型
- [[tcpdump-guide]] — BPF 表达式 + 抓包定位端口不通/握手失败
- [[SSH-反向隧道配置]] — 内网服务暴露到公网跳板的最小方案
- [[VPN-详解与配置]] — WireGuard 为主，内核态性能与漫游优势

## 1.9 存储基础（2 篇）

- ⭐ [[Longhorn-Kubernetes分布式块存储部署与运维指南]] — Engine + Replica 架构、CSI 接入、副本与快照运维
- [[RAID-原理选型与运维指南]] — RAID 级别选型、重建风险、运维要点

---

# 二、CI/CD 与 GitOps（32 篇）

## 2.1 Git 基础

- ⭐ [[Git-命令详解]] — 工作流/分支/撤销回退/贮藏/历史追溯，按场景组织而非按命令

## 2.2 流水线语法（各家一次看懂）

同一个概念在 6 套系统里怎么表达，适合横向对比着看：

- ⭐ [[GitLab CICD YAML详细语法与使用方法]] — 最详细的一份，stage/job/artifact/cache/rules 全覆盖
- [[GitLab CICD 与 Gitea Actions 语法和使用指南]] — 两套系统并排对照
- [[GitLab-CI-配置语法]] — 速查版
- [[GitHub-Actions-配置语法]] — workflow/job/step/matrix/条件函数
- [[Jenkinsfile-配置语法]] — 声明式 Pipeline
- [[CircleCI-配置语法]] — context 与环境变量组
- [[Drone-CI-配置语法]] — secret 管理

## 2.3 GitLab 平台本身

- [[GitLab 功能全景技术文档]] — 一体化 DevOps 平台的能力边界
- [[gitlab-docker-compose-guide]] — Omnibus 镜像 + Compose 部署
- [[GitLab 域名配置技术文档（自建 Omnibus）]] — `external_url` 如何决定一切
- [[GitLab 数据导入技术文档：场景分流与实操指南]] — 从其他平台迁入 / 项目间迁移
- [[GitLab-Runner-Ubuntu-22.04安装指南]] — 主机装 Runner（K8s 内装见下一节）
- ⭐ [[GitLab审计日志详细配置与运维指南]] — 合规取证视角的审计日志配置与验证

## 2.4 镜像构建与制品管理

- ⭐ [[Dockerfile-构建镜像详细指南]] — 写 Dockerfile 的完整决策清单
- [[Docker镜像构建流程]] — 理解标准流程，才能理解 Kaniko/BuildKit 为什么存在
- [[Kaniko-容器镜像构建工具]] — 无 Daemon 在 Pod 内构建，K8s 原生 CI 的标配
- [[Skopeo-容器镜像检查复制与同步指南]] — 不落地直接检查/复制/同步远程镜像
- [[Nexus-Repository-OSS作用功能与使用详细指南]] — 制品仓库：Maven/npm/PyPI/Docker 代理与私服

## 2.5 GitOps 与发布编排

- ⭐ [[Argo-CD-部署与使用详解]] — 声明式 GitOps 持续交付的核心机制
- [[Argocd 触发 webhook gitlab]] — 同步成功且健康后回调 GitLab Pipeline Trigger
- [[GitLab-ArgoCD-GitLab-Runner-GitOps完整部署流程]] — 三者串起来的标准部署顺序
- ⭐ [[GitLab-ArgoCD-Harbor-生产级CICD方案与实施验收Runbook]] — 目标架构→控制要求→实施阶段→验收证据，生产上线照这个走
- [[CI-CD/gitlab-ci-argocd/README|GitLab CI + ArgoCD 全链路（Deploy Recorder）]] — 一个可跑通的完整示例仓库
- ⭐ [[可落地CI-CD发布流程]] — 发布后能回答：哪个 commit、哪条流水线、哪个 digest、哪次合并进的生产
- [[CI-CD生产加固设计]] — 已有流程还漏的五个口子：集群侧验签、生产阻断等
- [[发布编排审计服务-多ArgoCD与飞书钉钉审批设计]] — Deploy Recorder 升级为发布编排服务的设计稿
- [[海外弹性GitLab-Runner构建方案]] — 阿里云 ASK + ECI 弹性构建机

## 2.6 配置管理与自动化

- ⭐ [[ansible-usage-guide]] — Inventory / ad-hoc / Playbook 从零到能用
- [[自动化/ansible-README|Ansible 使用指南（索引）]] — 文档入口与示例清单
- [[Rundeck-Runbook自动化平台详解]] — 把 Shell/Ansible/API 编排成可审计 Job，做运维自助
- [[ops-kb-workflow-guide]] — Dify 工作流搭本地 Markdown 笔记问答（自己笔记的 RAG 入口）

## 2.7 主机 HTTPS

- [[mkcert-本机HTTPS与多端信任部署指南]] — 内网 Harbor/GitLab 上 HTTPS 不买证书不做备案的解法

---

# 三、SRE 与可观测性（24 篇）

## 3.1 监控入门

- ⭐ [[Prometheus-Grafana-Alertmanager-入门介绍]] — PGA 三件套各司其职，先读这篇建立概念

## 3.2 生产级监控方案（可直接落地）

- ⭐ [[Kubernetes-Helm-Prometheus-Grafana-Alertmanager完整部署与告警方案]] — 标准 kube-prometheus-stack 路线，含告警规则
- ⭐ [[Kubernetes-Helm生产级监控方案]] — VictoriaMetrics Operator 全栈，替代 Prometheus 长期存储
- [[175.27.144.105-K3s监控流程与方案]] — 一台真实 K3s 的监控落地记录
- [[Zabbix-完善部署与使用运维指南]] — 传统主机/中间件监控，Server/Proxy/Agent 架构
- [[Grafana-Kubernetes与宿主机通用仪表盘模板说明]] — 现成 JSON 看板，按排障对象导入
- [[服务器与中间件巡检指标]] — 单台 Linux 该看哪些指标、什么算异常

## 3.3 日志平台

- ⭐ [[日志平台方案设计：Loki-Promtail-Grafana与VictoriaLogs]] — 两套方案的选型对比，先看这篇再动手
- [[VictoriaLogs-Grafana-Alloy部署运维文档]] — Compose 单机部署，保留 30 天
- [[Loggie-VictoriaLogs-Grafana-Kubernetes日志采集部署与运维]] — K8s 内 DaemonSet 采集 Pod 日志

## 3.4 分布式追踪

- ⭐ [[Jaeger-分布式追踪从入门到生产实践]] — Trace 能回答什么问题，先建立问题意识
- [[Tempo-OpenTelemetry-SeaweedFS-Grafana分布式追踪]] — 单机部署一套完整 OTel → Tempo → Grafana
- [[deepflow-deployment-and-usage]] — eBPF 零侵入采集，K8s 内全栈可观测

## 3.5 主机与系统排障

- ⭐ [[top-命令指标详解与性能排障指南]] — load/CPU/内存/Swap 怎么读，压力由谁造成
- [[Ubuntu-日志查看详解]] — journalctl 与 `/var/log` 两套体系对照

## 3.6 效率工具与脚本

- ⭐ [[自动巡检方案-FastAPI-Prometheus]] — 在 GitLab 运维语境下做只读健康巡检：Prometheus 查询 + FastAPI 暴露
- [[kubectl-交互式工具-kf]] — fzf 驱动的 kubectl 操作台
- [[kubectl-交互式工具-kf-安装说明]] / [[kubectl-快捷工具-k-安装说明]] / [[kubectl-快捷工具-k]] — 别名与快捷命令
- [[脚本与工具/README|脚本与工具索引]] — 按使用场景组织的入口
- [[日志审计-bash]] / [[日志审计-fish]] / [[日志轮转]] / [[卸载审计脚本]] — 交互式命令留痕，按 bash→fish→轮转 顺序用
- [[Rancher部署文档]] / [[一键部署 Rancher脚本]] — Helm 装进现有集群 + 一键脚本

---

# 四、数据与中间件（11 篇）

## 4.1 关系型数据库

- ⭐ [[PostgreSQL由浅到深-运维与开发指南]] — 开发侧 SQL/索引/事务 + 运维侧部署/复制/备份/监控
- [[数据库技术文档：从入门到落地使用]] — PG 落地实操版，按步骤走
- [[PostgreSQL-常用命令]] — psql 速查
- [[MySQL-常用命令]] — mysql 客户端速查

## 4.2 文档型数据库

- ⭐ [[MongoDB由浅到深-运维与开发指南]] — 建模/查询/性能 + 副本集/分片/备份
- [[MongoDB-常用命令]] — mongosh 速查

## 4.3 缓存

- ⭐ [[Redis-原理详解]] — 单线程为何能扛 10 万并发：IO 多路复用 + 内存操作
- [[Redis-缓存雪崩击穿穿透]] — 三个词长得像但原因和方案完全不同
- [[Redis-常用命令]] — redis-cli 速查

## 4.4 中间件

- ⭐ [[Nacos-注册中心与配置中心从入门到生产实践]] — 服务发现 + 配置管理 + AI Registry
- [[消息队列对比]] — Kafka/RabbitMQ/RocketMQ 等选型对照

---

# 五、AI 与开发（21 篇）

## 5.1 AI 原理与协议

- ⭐ [[LLM-架构原理与实现]] — 「巨大 Transformer 解码器 + 海量数据 + 预测下一 token」
- [[MCP是什么]] — Model Context Protocol：AI 连接外部工具的标准协议
- [[Skill是什么]] — Hermes 里的可复用知识模块
- ⭐ [[Skill-Tool-MCP-概念关系与使用指南]] — 三者边界：Skill 说怎么做、Tool 能做、MCP 怎么连
- [[LangChain-LangGraph-从入门到实战学习指南]] — LangChain 是应用框架，LangGraph 是编排运行时

## 5.2 模型能力跟踪（按周更新）

- ⭐ [[大模型能力对比-2026-11-09]] — 最新一份，先看这个
- [[大模型能力对比-2026-11-02]] / [[大模型能力对比-2026-10-25]] / [[大模型能力对比-2026-10-19]] — 历史快照，看趋势变化用

## 5.3 Python

- [[Python入门介绍]] — 语言定位与设计哲学
- ⭐ [[Python-列表-元组-字典详解]] — 三种容器怎么选，按使用场景讲
- [[Python基础数据结构学习指南]] — 列表/元组/字典/集合的增删改查与遍历
- [[Python常见Web框架对比与选型指南]] — FastAPI / Django / Flask 怎么选
- [[python/fastapi-prometheus-status/README|FastAPI + Prometheus K8s 状态 API]] — 只读判断节点/Endpoint/主机负载
- [[python/status-api/README|Python Status API]] — 与 Go 版同接口的只读状态服务
- [[cost-estimate]] — 资源升配成本估算（阿里云账单口径）

## 5.4 Go

- [[Go语言入门介绍]] — 语言定位、并发模型、生态
- ⭐ [[Go-vs-Python-适用场景]] — 不是二选一，是组合使用
- ⭐ [[Python与Go-标准开发流程详解]] — 环境→初始化→依赖→测试→构建→Docker→CI/CD→部署全流程
- [[go/status-api/README|Go Status API]] — HTTP 暴露服务器/K8s/Pod/中间件状态

## 5.5 JavaScript

- [[Node.js-npm-Vite-入门指南]] — 运行时 / 包管理 / 构建工具三件套

## 5.6 自研项目

- ⭐ [[code/aegis/README|Aegis：AI 堡垒机服务]] — 身份、显式授权、规则引擎、执行适配器四层
- [[code/aegis/ARCHITECTURE|Aegis MVP 架构与扩展边界]] — 规则引擎如何扩展而不改路由
- [[code/feishu-task-agent/README|feishu-task-agent]] — 飞书消息驱动多 Agent，WebSocket 长连接免公网

---

# 六、云平台与基础设施（11 篇）

## 6.1 公有云全景

- ⭐ [[主流云厂商产品分类]] — AWS/Azure/GCP/阿里云/腾讯云/火山引擎六大厂商产品线横向对照
- [[pcluster-常用命令]] — AWS ParallelCluster + Slurm

## 6.2 私有云与虚拟化

- ⭐ [[私有云部署指南]] — 自有数据中心做 IaaS/PaaS 的整体路径
- ⭐ [[Proxmox-VE虚拟化平台详解]] — Debian 基座 + KVM/LXC，Web 统一管理
- [[Harvester-HCI超融合平台详解]] — 把 KVM 虚拟机当 K8s 资源管的 HCI
- [[KVM-详解与命令速查]] — Linux 内核原生 Hypervisor，virsh/qemu 命令
- [[Multipass-使用指南]] — 一条命令起 Ubuntu VM，本地开发/测试最省事

## 6.3 GPU 与 AI 硬件栈

- ⭐ [[DGX-HGX-SXM-详解]] — SXM 模组 → HGX 基板 → DGX 整机的三层关系
- ⭐ [[NVIDIA显卡驱动与CUDA-Toolkit关系作用安装验证与排障指南]] — 从硬件到业务的完整软件栈，装错版本时查这个

## 6.4 云上运维

- [[AWS-AMI-清理脚本解析]] — 把运行中 EC2 重置到出厂状态以便打包 AMI

## 6.5 基础设施即代码

- [[Terraform-入门到实战]] — 声明式描述基础设施，Config/State/实际状态三者对齐

---

# 七、安全（5 篇）

- ⭐ [[RBAC详解]] — 权限给角色、角色给用户；K8s 与通用模型都适用
- ⭐ [[iptables-从入门到生产实践]] — Netfilter 表/链/规则/连接跟踪的完整心智模型
- [[ufw-usage-guide]] — Ubuntu 上 iptables 的简化封装，含「别把自己锁在外面」
- [[高防与WAF技术说明]] — 两者防护什么、如何协作、怎么选型
- ⭐ [[挖矿木马入侵排查与清除实录]] — 真实案例：从异常现象到定位到清除的完整过程

---

# 八、学习路线与计划（6 篇）

- ⭐ [[SRE-DevOps-云原生-AI-综合学习路线]] — 顶层设计：云原生是底座、DevOps 是实践、SRE 是哲学
- [[18周每日学习计划]] — 正在执行的主计划（起始 2026-07-14）
- ⭐ [[Week18-总结与输出-每日安排]] — 本周（11/10-11/15）的 6 天拆解
- ⭐ [[K8s-精通路线-总纲]] — 10 条验收标准 + 10 章清单 + 未勾选项
- [[K8s-系统学习路线]] — 阿里云课程资源为主的学习路径
- [[阿里云容器学习资源汇总]] — 课程/实验/自测/认证资源清单

---

# 故障速查：从症状找笔记

遇到问题时不用翻目录，直接对症状：

| 症状 | 先看 |
|---|---|
| Pod 起不来 / 反复重启 / 卡在 Pending | [[K8s-故障排查方法论]] → [[K8s-Pod生命周期详解]] → [[K8s-排障进阶-5个冷门kubectl命令详解]] |
| 集群 API 变慢 / etcd 报 quota | [[K8s-生产集群运维手册]] → [[K8s-etcd详解]] |
| Pod 之间不通 / Service 访问不到 | [[K8s-网络原理详解]] → [[tcpdump-guide]] → [[网络基础与进阶：从数据包到生产排障]] |
| PVC 一直 Pending / 存储写不进去 | [[K8s-存储深入]] → [[Longhorn-Kubernetes分布式块存储部署与运维指南]] |
| 域名解析不对 / HTTPS 证书报错 | [[domain-name-guide]] → [[DNS-详解]] → [[mkcert-本机HTTPS与多端信任部署指南]] |
| Nginx 502/504 / 代理转发异常 | [[Nginx-完全指南]] → [[l4-vs-l7-proxy-guide]] |
| 机器变慢 / 怀疑被挖矿 | [[top-命令指标详解与性能排障指南]] → [[挖矿木马入侵排查与清除实录]] |
| 端口该开没开 / 防火墙拦住 | [[iptables-从入门到生产实践]] → [[ufw-usage-guide]] |
| 镜像构建失败 / 拉不到镜像 | [[Dockerfile-构建镜像详细指南]] → [[Docker镜像构建流程]] → [[Skopeo-容器镜像检查复制与同步指南]] |
| 流水线跑不通 / GitOps 不同步 | [[GitLab CICD YAML详细语法与使用方法]] → [[Argo-CD-部署与使用详解]] → [[可落地CI-CD发布流程]] |
| 监控没数据 / 告警不发 | [[Prometheus-Grafana-Alertmanager-入门介绍]] → [[Kubernetes-Helm-Prometheus-Grafana-Alertmanager完整部署与告警方案]] |
| 日志查不到 | [[日志平台方案设计：Loki-Promtail-Grafana与VictoriaLogs]] → [[Ubuntu-日志查看详解]] |
| 显卡/CUDA 装不上 | [[NVIDIA显卡驱动与CUDA-Toolkit关系作用安装验证与排障指南]] |
| 数据库慢 / 连接数打满 | [[PostgreSQL由浅到深-运维与开发指南]] / [[MongoDB由浅到深-运维与开发指南]] → [[服务器与中间件巡检指标]] |
| Redis 命中率低 / 缓存穿透 | [[Redis-缓存雪崩击穿穿透]] → [[Redis-原理详解]] |

---

# 分布视图

按目录统计（与主题分类不完全对应，用于核对是否有遗漏）：

```
容器编排      30    ← 主战场
CI-CD        28
脚本与工具     13
监控          13
云服务        10
网络           9
数据库         9
学习           6
安全           5
ai            5
模型           4
自动化         4
go            4
python        7
code          3
存储           2
中间件         2
Gitlab         2
基础设施即代码    1
javascript     1
根目录         2
────────────────
合计         160
```

---

# 待补缺口（MOC 暴露出的空白）

整理这张图时，以下主题在库里**没有对应笔记**，属于结构性缺口：

| 缺口 | 影响 | 建议 |
|---|---|---|
| Terraform 只有 1 篇 | Week 16 只有刷题记录，无 State/Module 成稿 | 列入 Week 18 周五补缺候选 |
| 存储只有 2 篇（Longhorn + RAID） | 缺 Ceph、NFS、CSI 开发 | 非当前优先级 |
| 中间件只有 2 篇 | 缺 Kafka 单独深挖（只有选型对比） | 用到再补 |
| 无 CKA/CKS 考点映射 | 认证准备无索引 | 列入 Week 18 周五补缺候选 |
| 云服务缺 CDN/VPC/云监控 | Reminders「阿里云」任务第一阶段 | 列入 Week 18 周五补缺候选 |
| 3 个综合实战项目无产出 | Week 12-14 计划项 | 见周三薄弱环节清单 |

---

## 相关

- [[学习/知识地图-MOC]] 本身 —— 新增笔记后回来补到对应主题
- [[Week18-总结与输出-每日安排]] —— 本周任务来源
- [[README]] —— 库里另一份按目录组织的索引（本 MOC 按主题重组）
- [[CODEX_HANDOFF]] —— Codex 工作交接记录（分支、项目路径、待办），非知识笔记