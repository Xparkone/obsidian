# SRE + DevOps + 云原生 + AI 开发 综合学习路线

> 创建时间：2026-07-14
> 基于现有知识储备制定，串联已有笔记，补齐缺失领域
> 
> 📎 配套每日执行计划：[[18周每日学习计划]] — 每天早上 10:00 微信推送当日任务，下午 4:45 询问学习成果

---

## 📊 现状评估

### 已掌握 / 已有笔记覆盖

| 领域 | 内容 | 深度 |
|------|------|:---:|
| K8s | 核心组件、资源全览、etcd、Pod 生命周期 | 🟢 中 |
| CI/CD | GitLab CI、Drone CI、ArgoCD、Kaniko | 🟢 中 |
| 监控 | Prometheus + Grafana + Alertmanager | 🟡 基础 |
| 数据库 | MySQL / PostgreSQL / MongoDB / Redis | 🟢 中 |
| 网络 | DNS、VPN、Nginx、SSH 隧道 | 🟡 基础 |
| 编程 | Go 入门、Python 入门 | 🟡 基础 |
| AI | LLM 架构、MCP 协议、Skill | 🟡 基础 |
| 容器 | Docker、镜像构建流程 | 🟢 中 |

### 待补齐（本次路线重点）

| 领域 | 内容 |
|------|------|
| SRE | SLI/SLO/SLA、故障管理、混沌工程、容量规划 |
| DevOps | IaC（Terraform）、配置管理、GitOps 深度 |
| 云原生 | 服务网格、Serverless、eBPF、多集群 |
| AI 开发 | RAG 实战、Agent 框架、模型微调、AI 应用部署 |

---

## 🗺️ 四领域关系图

```
                   ┌──────────────┐
                   │   AI 开发     │  ← 最上层：用 AI 赋能一切
                   └──────┬───────┘
                          │
            ┌─────────────┼─────────────┐
            │             │             │
      ┌─────▼─────┐ ┌─────▼─────┐       │
      │   SRE     │ │  DevOps   │       │
      │ 可靠性工程 │ │ 开发运维  │       │
      └─────┬─────┘ └─────┬─────┘       │
            │             │             │
            └─────────────┼─────────────┘
                          │
                   ┌──────▼───────┐
                   │   云原生     │  ← 底座：K8s + 容器 + 服务网格
                   └──────────────┘
```

- **云原生**是底座，你的 K8s 学习路线已经覆盖了大部分
- **DevOps** 是工程实践，你在 CI/CD 方面已有基础
- **SRE** 是运维哲学，用工程方法解决运维问题
- **AI 开发** 是增值层，把 AI 能力嵌入到 DevOps/SRE 流程中

---

## Phase 1：云原生进阶（4 周）— 补齐 K8s 路线

> 你已有 [[K8s-系统学习路线]]，以下是当前进度推进

### 1.1 当前进度

| 主题 | 状态 | 笔记 |
|------|:---:|------|
| etcd 深入 | ✅ 完成 | [[K8s-etcd详解]] |
| Pod 生命周期 | ✅ 完成 | [[K8s-Pod生命周期详解]] |
| Controller Manager 控制循环 | ⚠️ 待学习 | 新建 |
| Scheduler 调度流程 | ⚠️ 待学习 | 新建 |

### 1.2 本周重点

1. **Controller Manager 控制循环** — ReplicaSet → Deployment → StatefulSet → DaemonSet 的控制器实现原理
2. **Scheduler 调度流程** — 预选（Filtering）→ 优选（Scoring）→ 绑定（Binding），插件化架构
3. **网络深入** — CNI 原理（Flannel VXLAN / Calico BGP / Cilium eBPF），Service iptables/IPVS 模式
4. **存储深入** — CSI 驱动开发，PV/PVC 动态供给，StatefulSet 有状态应用

### 1.3 动手实验

```bash
# 用 kind 搭建多节点集群
kind create cluster --config kind-multi-node.yaml

# 手动模拟 scheduler 调度过程
kubectl get events --watch  # 观察调度事件

# 用 tcpdump 抓包理解 CNI 网络
kubectl run netshoot --image=nicolaka/netshoot --rm -it -- bash
```

---

## Phase 2：DevOps 工程实践（4 周）

> 你在 CI/CD 方面已有 GitLab CI、Drone、ArgoCD 经验，以下补齐 IaC 和 GitOps 深度

### 2.1 基础设施即代码 (IaC)

| 主题 | 要点 | 动手 |
|------|------|------|
| **Terraform 基础** | Provider、Resource、State、Module | 写一个 AWS/阿里云 VPC 模块 |
| **Terraform 进阶** | Workspace、Backend（S3/OSS）、Terraform Cloud | 管理远程 State |
| **Ansible 入门** | Playbook、Role、Inventory、变量 | 自动化配置你的两台服务器 |
| **Packer** | 构建自定义镜像（AMI、Docker） | 打一个含预装工具的镜像 |

### 2.2 GitOps 深度

| 主题 | 要点 | 已有笔记 |
|------|------|:---:|
| ArgoCD 应用管理 | Application / AppProject / ApplicationSet | ✅ [[Argo-项目详解]] |
| Helm Chart 开发 | 模板语法、依赖管理、共享 Chart | 新建 |
| 多环境管理 | Kustomize overlay、ArgoCD 多集群 | 新建 |
| 渐进式交付 | Argo Rollouts 蓝绿/金丝雀 | 新建 |

### 2.3 动手实验

```bash
# Terraform 管理阿里云资源
terraform init && terraform plan && terraform apply

# 搭建 ArgoCD + 多集群 GitOps
# 一个 Git 仓库，自动同步到 staging/prod 两个集群
```

### 2.4 阿里云课程推荐

- **基于 Docker 与 Jenkins 实现自动化部署**（3,666 学员）
- **企业级运维之云原生与 Kubernetes 实战课程**（3,720 学员）

---

## Phase 3：SRE 可靠性工程（4 周）

> 这是你目前最缺的领域，也是运维能力从"会用"到"专家"的跃迁

### 3.1 SRE 核心方法论

| 主题 | 要点 |
|------|------|
| **SLI / SLO / SLA** | 服务水平指标 → 目标 → 协议，如何定义和度量 |
| **错误预算 (Error Budget)** | 用 error budget 决策发布节奏 |
| **故障管理** | 故障分级、on-call 制度、blameless postmortem |
| **变更管理** | 渐进式发布、回滚策略、变更审批 |

### 3.2 可观测性工程

| 主题 | 要点 | 已有笔记 |
|------|------|:---:|
| 三大支柱 | Metrics / Logs / Traces 的关系与互补 | ✅ [[Prometheus-Grafana-Alertmanager-入门介绍]] |
| Prometheus 深度 | Recording Rules、Alerting Rules、Federation | 新建 |
| 分布式追踪 | OpenTelemetry、Jaeger、Tempo | 新建 |
| 日志聚合 | Loki + Promtail、ELK Stack | 新建 |

### 3.3 混沌工程

| 主题 | 要点 |
|------|------|
| Chaos Mesh | Pod 故障、网络延迟、IO 故障注入 |
| LitmusChaos | 混沌实验编排、GitOps 集成 |
| 故障演练 | 模拟节点宕机、网络分区、磁盘满 |

### 3.4 容量规划与性能

| 主题 | 要点 |
|------|------|
| 压测工具 | wrk / vegeta / k6 / Locust |
| 容量模型 | 基于历史数据的线性回归预测 |
| 自动扩缩 | HPA / VPA / KEDA / Cluster Autoscaler |

### 3.5 推荐阅读

- 《Site Reliability Engineering》— Google SRE 圣经（有中文版）
- 《The Site Reliability Workbook》— 实践篇
- https://sre.google/books/

---

## Phase 4：AI 开发（6 周，持续）

> 这是最前沿、最有增值空间的领域

### 4.1 AI 基础理论（已有笔记补充）

| 主题 | 要点 | 已有笔记 |
|------|------|:---:|
| LLM 架构 | Transformer、Attention、Tokenization | ✅ [[LLM-架构原理与实现]] |
| MCP 协议 | 工具集成标准、Server/Client 模型 | ✅ [[MCP是什么]] |
| Skill 机制 | Hermes Agent 的可复用知识模块 | ✅ [[Skill是什么]] |
| Prompt Engineering | 系统提示、Few-shot、Chain-of-Thought | 新建 |

### 4.2 RAG（检索增强生成）

| 主题 | 要点 |
|------|------|
| RAG 原理 | Embedding → 向量检索 → 上下文注入 → 生成 |
| 向量数据库 | Milvus / Qdrant / Pinecone / pgvector |
| 文档处理 | 分块策略、多模态 RAG（文本+图片） |
| 实战项目 | 搭建一个运维知识库 RAG 系统 |

### 4.3 AI Agent 开发

| 主题 | 要点 |
|------|------|
| Agent 架构 | Planning → Tool Use → Memory → Reflection |
| 多 Agent 协作 | 任务分解、Agent 间通信、结果汇总 |
| Hermes Agent 开发 | Skill 编写、Plugin 开发、Tool 扩展 |
| 实战项目 | 用 Agent 自动巡检两台服务器并生成报告 |

### 4.4 模型微调与部署

| 主题 | 要点 |
|------|------|
| 微调方法 | LoRA / QLoRA、全量微调、指令微调 |
| 工具链 | HuggingFace Transformers、vLLM、llama.cpp |
| 模型部署 | GPU 推理优化、量化（GGUF/GPTQ）、API 服务化 |
| 实战项目 | 微调一个运维问答模型 |

### 4.5 AI + DevOps 融合场景

| 场景 | 说明 |
|------|------|
| AI 日志分析 | 用 LLM 自动分析错误日志并给出修复建议 |
| AI 故障诊断 | 告警 → LLM 分析 → 自动拉起诊断容器 → 返回结论 |
| AI 代码审查 | PR 提交 → LLM 审查安全/性能问题 → 自动评论 |
| AI 文档生成 | 从代码/配置自动生成运维文档 |

---

## 🏆 认证路径

| 认证 | 领域 | 难度 | 说明 |
|------|------|:---:|------|
| CKA | 云原生 | ⭐⭐⭐ | K8s 管理员认证，实战含金量高 |
| CKAD | 云原生 | ⭐⭐ | K8s 应用开发者，比 CKA 简单 |
| CKS | 云原生 | ⭐⭐⭐⭐ | K8s 安全专家，需先有 CKA |
| Terraform Associate | DevOps | ⭐⭐ | HashiCorp 官方认证 |
| AWS SAA | 云平台 | ⭐⭐⭐ | AWS 解决方案架构师 |
| 阿里云 ACA | 云平台 | ⭐⭐ | 入门级，适合检验基础 |

---

## 📅 建议学习节奏

```
Week  1- 4  ████████  Phase 1: 云原生进阶（Controller/Scheduler/网络/存储）
Week  5- 8  ████████  Phase 2: DevOps（IaC/GitOps/Helm）
Week  9-12  ████████  Phase 3: SRE（SLI/SLO/可观测性/混沌工程）
Week 13-18  ████████  Phase 4: AI 开发（RAG/Agent/微调/AI+DevOps）
Week 19+    ████████  持续学习 + 认证准备 + 实战项目
```

**每天 1-1.5 小时**，周末可以做实战项目（2-3 小时）。

---

## 🔗 笔记索引

### 云原生
- [[K8s-系统学习路线]]
- [[K8s-定义]]
- [[K8s-组件详解]]
- [[K8s-资源全览]]
- [[K8s-etcd详解]]
- [[K8s-Pod生命周期详解]]
- [[Istio-服务网格详解]]
- [[Argo-项目详解]]
- [[KVM-详解与命令速查]]

### DevOps
- [[Docker镜像构建流程]]
- [[Docker-Build从入门到高级]]
- [[Drone-CI-配置语法]]
- [[Kaniko-容器镜像构建工具]]
- [[CI-CD/gitlab-ci-argocd/README]]

### SRE
- [[Prometheus-Grafana-Alertmanager-入门介绍]]
- [[监控/ 目录]]

### AI
- [[LLM-架构原理与实现]]
- [[MCP是什么]]
- [[Skill是什么]]

### 编程
- [[Go语言入门介绍]]
- [[Go-vs-Python-适用场景]]
- [[Python入门介绍]]
- [[Python-列表-元组-字典详解]]

### 基础设施
- [[DNS-详解]]
- [[VPN-详解与配置]]
- [[Nginx-完全指南]]
- [[SSH-反向隧道配置]]

---

## 📝 待新建笔记清单

| 笔记 | 阶段 | 优先级 |
|------|------|:---:|
| K8s-Controller-Manager详解.md | Phase 1 | 🔴 高 |
| K8s-Scheduler调度流程.md | Phase 1 | 🔴 高 |
| K8s-网络详解.md | Phase 1 | 🟡 中 |
| K8s-存储详解.md | Phase 1 | 🟡 中 |
| Terraform-入门到实战.md | Phase 2 | 🟡 中 |
| Helm-Chart开发指南.md | Phase 2 | 🟡 中 |
| SRE-SLI-SLO-SLA详解.md | Phase 3 | 🔴 高 |
| SRE-可观测性三大支柱.md | Phase 3 | 🟡 中 |
| SRE-混沌工程实践.md | Phase 3 | 🟢 低 |
| RAG-原理与实战.md | Phase 4 | 🟡 中 |
| AI-Agent开发实战.md | Phase 4 | 🟡 中 |
| LLM-微调与部署.md | Phase 4 | 🟢 低 |

---

## 💡 学习建议

1. **动手 > 阅读**：每个主题看完后立刻用 kind/minikube 做实验，你的两台服务器（115.191.5.215 / 47.92.2.43）也是很好的实验田
2. **笔记驱动**：学完一个主题写一篇笔记，放在 `~/Documents/hermes/运维笔记/学习/` 下，形成知识体系
3. **项目驱动**：每个 Phase 结束时做一个综合项目，比纯学理论有效得多
4. **AI 辅助学习**：用 AI 解释概念、生成练习题、审查你的理解是否正确
5. **先广后深**：Phase 1-4 先过一遍建立全局视野，然后挑最感兴趣的方向深耕