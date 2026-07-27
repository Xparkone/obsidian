# 运维笔记

按主题分类的运维 / 云原生学习笔记索引。多数文档使用 Obsidian `[[双链]]`，按文件名即可跳转。

## 目录结构

| 分类 | 说明 |
|------|------|
| [容器编排](容器编排/) | Docker / K8s / K3s / Istio / Argo |
| [CI-CD](CI-CD/) | 流水线语法、镜像构建、Git、GitLab+ArgoCD 示例 |
| [云服务](云服务/) | 公有云 / 私有云 / 虚拟化 / GPU 硬件 / ParallelCluster |
| [网络](网络/) | DNS、VPN、Nginx、SSH 隧道 |
| [数据库](数据库/) | MySQL / PostgreSQL / MongoDB / Redis |
| [监控](监控/) | Prometheus / Grafana / Alertmanager |
| [中间件](中间件/) | 消息队列等 |
| [安全](安全/) | 访问控制（RBAC） |
| [脚本与工具](脚本与工具/) | kubectl 快捷脚本（k / kf） |
| [学习](学习/) | 学习路线、每日计划、资源汇总 |
| [ai](ai/) | LLM / MCP / Skill / Hermes |
| [go](go/) · [python](python/) | 语言入门与对比 |

---

### 容器编排

- [K8s-定义.md](容器编排/K8s-定义.md)
- [K8s-组件详解.md](容器编排/K8s-组件详解.md)
- [K8s-资源全览.md](容器编排/K8s-资源全览.md)
- [K8s-etcd详解.md](容器编排/K8s-etcd详解.md)
- [K8s-Pod生命周期详解.md](容器编排/K8s-Pod生命周期详解.md)
- [k8s-常用操作手册.md](容器编排/k8s-常用操作手册.md)
- [k8s-architecture.excalidraw.md](容器编排/k8s-architecture.excalidraw.md)
- [K3s-部署指南.md](容器编排/K3s-部署指南.md)
- [Docker-Build从入门到高级.md](容器编排/Docker-Build从入门到高级.md)
- [Istio-服务网格详解.md](容器编排/Istio-服务网格详解.md)
- [Argo-项目详解.md](容器编排/Argo-项目详解.md)

### CI-CD

- [Git-命令详解.md](CI-CD/Git-命令详解.md)
- [GitLab-CI-配置语法.md](CI-CD/GitLab-CI-配置语法.md)
- [GitHub-Actions-配置语法.md](CI-CD/GitHub-Actions-配置语法.md)
- [Jenkinsfile-配置语法.md](CI-CD/Jenkinsfile-配置语法.md)
- [Drone-CI-配置语法.md](CI-CD/Drone-CI-配置语法.md)
- [CircleCI-配置语法.md](CI-CD/CircleCI-配置语法.md)
- [Docker镜像构建流程.md](CI-CD/Docker镜像构建流程.md)
- [Kaniko-容器镜像构建工具.md](CI-CD/Kaniko-容器镜像构建工具.md)
- [海外弹性GitLab-Runner构建方案.md](CI-CD/海外弹性GitLab-Runner构建方案.md)
- [gitlab-ci-argocd/](CI-CD/gitlab-ci-argocd/) — GitLab CI + ArgoCD 示例工程

### 云服务

- [主流云厂商产品分类.md](云服务/主流云厂商产品分类.md)
- [私有云部署指南.md](云服务/私有云部署指南.md)
- [pcluster-常用命令.md](云服务/pcluster-常用命令.md)
- [AWS-AMI-清理脚本解析.md](云服务/AWS-AMI-清理脚本解析.md)
- [KVM-详解与命令速查.md](云服务/KVM-详解与命令速查.md)
- [Multipass-使用指南.md](云服务/Multipass-使用指南.md)
- [DGX-HGX-SXM-详解.md](云服务/DGX-HGX-SXM-详解.md)

### 网络

- [DNS-详解.md](网络/DNS-详解.md)
- [VPN-详解与配置.md](网络/VPN-详解与配置.md)
- [Nginx-完全指南.md](网络/Nginx-完全指南.md)
- [SSH-反向隧道配置.md](网络/SSH-反向隧道配置.md)

### 数据库

- [MySQL-常用命令.md](数据库/MySQL-常用命令.md)
- [PostgreSQL-常用命令.md](数据库/PostgreSQL-常用命令.md)
- [MongoDB-常用命令.md](数据库/MongoDB-常用命令.md)
- [Redis-常用命令.md](数据库/Redis-常用命令.md)
- [Redis-原理详解.md](数据库/Redis-原理详解.md)
- [Redis-缓存雪崩击穿穿透.md](数据库/Redis-缓存雪崩击穿穿透.md)

### 监控 / 中间件 / 安全

- [Prometheus-Grafana-Alertmanager-入门介绍.md](监控/Prometheus-Grafana-Alertmanager-入门介绍.md)
- [消息队列对比.md](中间件/消息队列对比.md)
- [RBAC详解.md](安全/RBAC详解.md)

### 脚本与工具

- [kubectl-快捷工具-k.md](kubectl-快捷工具-k.md) · [安装说明](kubectl-快捷工具-k-安装说明.md)
- [kubectl-交互式工具-kf.md](kubectl-交互式工具-kf.md) · [安装说明](kubectl-交互式工具-kf-安装说明.md)

### 学习

- [SRE-DevOps-云原生-AI-综合学习路线.md](学习/SRE-DevOps-云原生-AI-综合学习路线.md)
- [K8s-系统学习路线.md](学习/K8s-系统学习路线.md)
- [18周每日学习计划.md](学习/18周每日学习计划.md)
- [阿里云容器学习资源汇总.md](学习/阿里云容器学习资源汇总.md)

### AI / 语言

- [LLM-架构原理与实现.md](ai/LLM-架构原理与实现.md) · [MCP是什么.md](ai/MCP是什么.md) · [Skill是什么.md](ai/Skill是什么.md)
- [Go语言入门介绍.md](go/Go语言入门介绍.md) · [Go-vs-Python-适用场景.md](go/Go-vs-Python-适用场景.md)
- [Python入门介绍.md](python/Python入门介绍.md) · [Python-列表-元组-字典详解.md](python/Python-列表-元组-字典详解.md)
