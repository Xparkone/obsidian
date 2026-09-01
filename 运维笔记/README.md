# 运维笔记

按主题分类的运维 / 云原生学习笔记索引。多数文档使用 Obsidian `[[双链]]`，按文件名即可跳转。

## 目录结构

| 分类 | 说明 |
|------|------|
| [容器编排](容器编排/) | Docker / K8s / K3s / Helm / Istio / Argo |
| [CI-CD](CI-CD/) | 流水线语法、GitLab、镜像构建、示例工程 |
| [基础设施即代码](基础设施即代码/) | Terraform、IaC、State、Module 与基础设施自动化 |
| [云服务](云服务/) | 公有云 / 私有云 / 虚拟化 / GPU 硬件 / ParallelCluster |
| [网络](网络/) | DNS、VPN、Nginx、代理、抓包、域名 |
| [数据库](数据库/) | MySQL / PostgreSQL / MongoDB / Redis |
| [监控](监控/) | Prometheus / Grafana / Jaeger / Tempo / Loki / VictoriaLogs / DeepFlow |
| [自动化](自动化/) | Ansible、Rundeck、知识库工作流与示例 |
| [中间件](中间件/) | Nacos 注册配置中心、消息队列等 |
| [安全](安全/) | RBAC、UFW、高防与 WAF |
| [脚本与工具](脚本与工具/) | kubectl 快捷脚本（k / kf） |
| [学习](学习/) | 学习路线、每日计划、资源汇总 |
| [ai](ai/) | LLM / MCP / Skill / Hermes |
| [go](go/) · [python](python/) · [javascript](javascript/) | 语言入门、运行环境、包管理和开发工具 |

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
- [Kubernetes-Ingress-部署与使用详解.md](容器编排/Kubernetes-Ingress-部署与使用详解.md)
- [Docker-Build从入门到高级.md](容器编排/Docker-Build从入门到高级.md)
- [Helm-3-从入门到生产实践.md](容器编排/Helm-3-从入门到生产实践.md)
- [Istio-服务网格详解.md](容器编排/Istio-服务网格详解.md)
- [Istio详细入门与实践指南.md](容器编排/Istio详细入门与实践指南.md)
- [Argo-项目详解.md](容器编排/Argo-项目详解.md)
- [Velero-Kubernetes备份恢复与迁移指南.md](容器编排/Velero-Kubernetes备份恢复与迁移指南.md)

### CI-CD

- [Git-命令详解.md](CI-CD/Git-命令详解.md)
- [GitLab-CI-配置语法.md](CI-CD/GitLab-CI-配置语法.md)
- [GitLab CICD YAML详细语法与使用方法.md](CI-CD/GitLab%20CICD%20YAML详细语法与使用方法.md)
- [GitLab CICD 与 Gitea Actions 语法和使用指南.md](CI-CD/GitLab%20CICD%20与%20Gitea%20Actions%20语法和使用指南.md)
- [GitLab 功能全景技术文档.md](CI-CD/GitLab%20功能全景技术文档.md)
- [GitLab 域名配置技术文档（自建 Omnibus）.md](CI-CD/GitLab%20域名配置技术文档（自建%20Omnibus）.md)
- [GitLab 数据导入技术文档：场景分流与实操指南.md](CI-CD/GitLab%20数据导入技术文档：场景分流与实操指南.md)
- [gitlab-docker-compose-guide.md](CI-CD/gitlab-docker-compose-guide.md)
- [GitHub-Actions-配置语法.md](CI-CD/GitHub-Actions-配置语法.md)
- [Jenkinsfile-配置语法.md](CI-CD/Jenkinsfile-配置语法.md)
- [Drone-CI-配置语法.md](CI-CD/Drone-CI-配置语法.md)
- [CircleCI-配置语法.md](CI-CD/CircleCI-配置语法.md)
- [Docker镜像构建流程.md](CI-CD/Docker镜像构建流程.md)
- [Kaniko-容器镜像构建工具.md](CI-CD/Kaniko-容器镜像构建工具.md)
- [Skopeo-容器镜像检查复制与同步指南.md](CI-CD/Skopeo-容器镜像检查复制与同步指南.md)
- [海外弹性GitLab-Runner构建方案.md](CI-CD/海外弹性GitLab-Runner构建方案.md)
- [gitlab-ci-argocd/](CI-CD/gitlab-ci-argocd/) — GitLab CI + ArgoCD 示例工程
- [examples/gitlab-compose/](CI-CD/examples/gitlab-compose/) — GitLab Docker Compose 示例

### 基础设施即代码

- [Terraform-入门到实战.md](基础设施即代码/Terraform-入门到实战.md)

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
- [nginx-lua-guide.md](网络/nginx-lua-guide.md)
- [l4-vs-l7-proxy-guide.md](网络/l4-vs-l7-proxy-guide.md)
- [domain-name-guide.md](网络/domain-name-guide.md)
- [tcpdump-guide.md](网络/tcpdump-guide.md)
- [SSH-反向隧道配置.md](网络/SSH-反向隧道配置.md)

### 数据库

- [数据库技术文档：从入门到落地使用.md](数据库/数据库技术文档：从入门到落地使用.md)
- [MySQL-常用命令.md](数据库/MySQL-常用命令.md)
- [PostgreSQL-常用命令.md](数据库/PostgreSQL-常用命令.md)
- [PostgreSQL由浅到深-运维与开发指南.md](数据库/PostgreSQL由浅到深-运维与开发指南.md)
- [MongoDB-常用命令.md](数据库/MongoDB-常用命令.md)
- [MongoDB由浅到深-运维与开发指南.md](数据库/MongoDB由浅到深-运维与开发指南.md)
- [Redis-常用命令.md](数据库/Redis-常用命令.md)
- [Redis-原理详解.md](数据库/Redis-原理详解.md)
- [Redis-缓存雪崩击穿穿透.md](数据库/Redis-缓存雪崩击穿穿透.md)

### 监控

- [Prometheus-Grafana-Alertmanager-入门介绍.md](监控/Prometheus-Grafana-Alertmanager-入门介绍.md)
- [Grafana-Kubernetes与宿主机通用仪表盘模板说明.md](监控/Grafana-Kubernetes与宿主机通用仪表盘模板说明.md)
- [Grafana-Node-Exporter-宿主机监控仪表盘.json](监控/Grafana-Node-Exporter-宿主机监控仪表盘.json)
- [Grafana-Node-Exporter-宿主机性能深挖仪表盘.json](监控/Grafana-Node-Exporter-宿主机性能深挖仪表盘.json)
- [Grafana-Kubernetes-集群整体监控仪表盘.json](监控/Grafana-Kubernetes-集群整体监控仪表盘.json)
- [Grafana-Kubernetes-工作负载与Pod详细监控.json](监控/Grafana-Kubernetes-工作负载与Pod详细监控.json)
- [Grafana-Kubernetes-节点容量与调度监控.json](监控/Grafana-Kubernetes-节点容量与调度监控.json)
- [Grafana-Kubernetes-网络与存储详细监控.json](监控/Grafana-Kubernetes-网络与存储详细监控.json)
- [Grafana-Kubernetes-控制面健康监控.json](监控/Grafana-Kubernetes-控制面健康监控.json)
- [Jaeger-分布式追踪从入门到生产实践.md](监控/Jaeger-分布式追踪从入门到生产实践.md)
- [Tempo-OpenTelemetry-SeaweedFS-Grafana分布式追踪.md](监控/Tempo-OpenTelemetry-SeaweedFS-Grafana分布式追踪.md)
- [日志平台方案设计：Loki-Promtail-Grafana与VictoriaLogs.md](监控/日志平台方案设计：Loki-Promtail-Grafana与VictoriaLogs.md)
- [VictoriaLogs-Grafana-Alloy部署运维文档.md](监控/VictoriaLogs-Grafana-Alloy部署运维文档.md)
- [Loggie-VictoriaLogs-Grafana-Kubernetes日志采集部署与运维.md](监控/Loggie-VictoriaLogs-Grafana-Kubernetes日志采集部署与运维.md)
- [deepflow-deployment-and-usage.md](监控/deepflow-deployment-and-usage.md)

### 自动化

- [Rundeck-Runbook自动化平台详解.md](自动化/Rundeck-Runbook自动化平台详解.md)
- [ansible-README.md](自动化/ansible-README.md)
- [ansible-usage-guide.md](自动化/ansible-usage-guide.md)
- [ops-kb-workflow-guide.md](自动化/ops-kb-workflow-guide.md)
- [examples/nginx-site/](自动化/examples/nginx-site/) — Ansible Nginx 站点示例
- [workflows/](自动化/workflows/) — 知识库 chatbot 等工作流配置

### 中间件 / 安全

- [Nacos-注册中心与配置中心从入门到生产实践.md](中间件/Nacos-注册中心与配置中心从入门到生产实践.md)
- [消息队列对比.md](中间件/消息队列对比.md)
- [RBAC详解.md](安全/RBAC详解.md)
- [ufw-usage-guide.md](安全/ufw-usage-guide.md)
- [iptables-从入门到生产实践.md](安全/iptables-从入门到生产实践.md)
- [高防与WAF技术说明.md](安全/高防与WAF技术说明.md)

### 脚本与工具

- [kubectl-快捷工具-k.md](脚本与工具/kubectl-快捷工具-k.md) · [安装说明](脚本与工具/kubectl-快捷工具-k-安装说明.md)
- [kubectl-交互式工具-kf.md](脚本与工具/kubectl-交互式工具-kf.md) · [安装说明](脚本与工具/kubectl-交互式工具-kf-安装说明.md)

### 学习

- [SRE-DevOps-云原生-AI-综合学习路线.md](学习/SRE-DevOps-云原生-AI-综合学习路线.md)
- [K8s-系统学习路线.md](学习/K8s-系统学习路线.md)
- [18周每日学习计划.md](学习/18周每日学习计划.md)
- [阿里云容器学习资源汇总.md](学习/阿里云容器学习资源汇总.md)

### AI / 语言

- [LLM-架构原理与实现.md](ai/LLM-架构原理与实现.md) · [MCP是什么.md](ai/MCP是什么.md) · [Skill是什么.md](ai/Skill是什么.md)
- [Go语言入门介绍.md](go/Go语言入门介绍.md) · [Go-vs-Python-适用场景.md](go/Go-vs-Python-适用场景.md)
- [todo-api/](go/todo-api/) — Go Todo API 示例
- [Python入门介绍.md](python/Python入门介绍.md) · [Python-列表-元组-字典详解.md](python/Python-列表-元组-字典详解.md)
- [Node.js、npm、Vite 入门指南](javascript/Node.js-npm-Vite-入门指南.md)
