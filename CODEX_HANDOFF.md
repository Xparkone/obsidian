# Codex 工作交接

更新时间：2026-09-01 10:48:05 +0800

当前主机：dpdeMacBook-Pro-86.local

项目路径：/Users/lijiaxuan/Documents/hermes

当前分支：main

## 当前目标

完善通用 Kubernetes Ingress 与 Ingress Controller 详细文档，解释是什么、为什么需要、如何部署使用，并用 Mermaid `sequenceDiagram` 展示配置生效和真实请求过程。

## 已确认事实

- 已有同主题文档位于 `运维笔记/容器编排/Kubernetes-Ingress-部署与使用详解.md`，本次直接完善，没有创建重复笔记。
- Ingress 是声明式 HTTP/HTTPS 路由规则；Ingress Controller 负责监听对象、调谐代理或负载均衡配置并实际接收流量。
- Ingress API 仍为稳定 API但已冻结；Gateway API 是新建平台的优先评估方向。
- Kubernetes 社区 `kubernetes/ingress-nginx` 已于 2026 年 3 月停止维护；F5/NGINX Ingress Controller 是不同项目。
- `运维笔记/README.md` 已增加该文档入口。

## 基于证据的判断

- 将“配置流”和“数据流”分成两张时序图，有助于避免把 `kubectl apply` 成功误认为业务请求已经可达。
- 通用文档同时保留 Traefik 和 F5/NGINX 两种仍在维护的示例，并明确不同 Controller 的 IngressClass、注解、CRD 和默认行为不能直接互换。
- Controller 的 Service 使用 `LoadBalancer`、NodePort 还是 MetalLB，必须根据公有云、裸金属或本地集群的入口能力选择。

## 尚未验证的可能性

- 尚未在真实 Kubernetes 集群执行 Helm 安装、Ingress 应用和端到端请求验证。
- Traefik 示例未固定通用 Chart 版本；生产部署必须根据目标 Kubernetes 版本选择并固定经测试的 Chart 和镜像版本。
- Mermaid 已完成静态结构检查，但本机没有 `mmdc`，尚未执行渲染级验证。

## 已完成

- 在原有 20 章文档中补充“是什么、为什么、怎么用”的阅读目标和原理说明。
- 新增 2 张 Mermaid `sequenceDiagram`：客户端请求数据流、Controller 配置调谐流。
- 新增 Controller 选型表、Traefik Helm 安装、IngressClass 关系、裸金属入口提示和跨 Controller 迁移边界。
- 更新官方资料日期和 Traefik/F5 官方参考链接。
- 把文档加入容器编排分类 README 索引。

## 修改文件

- `运维笔记/容器编排/Kubernetes-Ingress-部署与使用详解.md`
- `运维笔记/README.md`
- `CODEX_HANDOFF.md`

## 验证结果

- 文档共 1569 行，142 个 Markdown 代码围栏成对。
- 2 个 Mermaid 代码块均为 `sequenceDiagram`，围栏闭合。
- 17 个 YAML 代码块通过 Ruby Psych 语法解析。
- README 新增链接目标存在；全量 README 检查发现一个与本任务无关的既有缺失目录 `CI-CD/examples/gitlab-compose/`，未修改。
- `git diff --check` 无错误。
- 本任务未主动执行 Git 提交；工作期间仓库出现自动 `vault backup` 提交，最终状态仍以当前 `git status` 为准。

## 未解决问题

- 需要在目标环境确认 Kubernetes 版本、已有 Controller、IngressClass、入口类型、DNS 和证书方案。
- 需要在测试集群实际验证 `IngressClass -> Ingress -> Service -> EndpointSlice -> Pod`，并用正确 Host/SNI 发起请求。
- 如果现网仍使用社区 ingress-nginx，需要先盘点专有注解和行为，再制定并行迁移和回切方案。

## 下一步

1. 在目标集群执行部署前只读检查，确认是否已经存在 Traefik、APISIX、云 Controller 或其他入口。
2. 根据公有云、裸金属或本地集群选择 LoadBalancer、MetalLB、NodePort 或端口映射。
3. 固定 Controller Chart 和镜像版本，在测试命名空间应用最小后端与 Ingress。
4. 验证入口地址、Host/Path、TLS、Service、EndpointSlice、Pod 和 Controller 日志后，再进入生产变更流程。

## 重要命令

```bash
git -C /Users/lijiaxuan/Documents/hermes status --short
git -C /Users/lijiaxuan/Documents/hermes diff --check
kubectl get ingressclass
kubectl get ingress --all-namespaces
kubectl get pods --all-namespaces | grep -Ei 'ingress|gateway|traefik|nginx|kong|haproxy'
```

## 既有阶段记录（2026-08-26，GitLab CI/CD，保留）

此前已完善运维笔记库中的 GitLab CI/CD YAML 中文教程，使其适合初学者循序学习，并与 GitLab 19.3 当时官方语法保持一致：

- 主教程位于 `运维笔记/CI-CD/GitLab CICD YAML详细语法与使用方法.md`，README 已有索引。
- GitLab 19.3 于 2026-08-20 发布。
- GitLab 18.10 引入 job inputs，要求 GitLab Runner 18.9 或更高版本。
- `include:cache` 从 GitLab 19.0 起正式可用，仅适用于 `include:remote`。
- 已增加六步学习路线和四层验证边界、Job `inputs`、`spec:inputs`、`include:inputs`、`include:cache`、`manual_confirmation` 和关键词速查项。
- 110 个 YAML 代码块通过 Ruby Psych 语法解析，232 个 Markdown 围栏配对正常，本地 Markdown 链接和 `git diff --check` 通过。
- 尚未连接目标 GitLab 项目执行 CI Lint，也未在真实 Runner 或部署环境运行示例。
- Self-Managed 实例可能低于 GitLab 19.3，新增语法是否可用需要按实例和 Runner 版本确认。
- 后续应在练习项目逐步提交 `.gitlab-ci.yml`，使用目标项目 Pipeline editor 的 CI Lint 和 pipeline simulation，再结合实际技术栈补充构建、发布、健康检查和回滚命令。

## 既有阶段记录（2026-08-25，Grafana 仪表盘，保留）

此前已完成运维笔记中 Kubernetes 与 Linux 宿主机 Grafana 通用仪表盘的静态交付：

- 原有两份模板，新增 Kubernetes 工作负载与 Pod、节点容量与调度、网络与存储、控制面以及 Node Exporter 宿主机性能深挖五份模板；七份模板共 198 个顶层面板，均使用 `DS_PROMETHEUS` 数据源变量。
- 已修正原宿主机概览“最高磁盘使用率”的 PromQL 括号和聚合位置错误，并完成 JSON 语法、schema、UID、面板 ID、变量引用、PromQL 括号和文档链接静态检查。
- 相关文件位于 `运维笔记/监控/`，总索引为 `运维笔记/README.md`。
- 尚未在真实 Grafana 和 Prometheus 验证全部查询。现场仍需确认 Grafana、kube-state-metrics 版本以及 `job`、`instance`、`node` 等标签；控制面、PSI、conntrack、卷统计等面板是否有数据取决于实际抓取指标。
- Dashboard 展示阈值不能代替告警规则；部分 cAdvisor 指标可能缺少 `node` 标签，需要按现场数据做关联或 relabel。

## 注意事项

- 当前只完成文档和静态验证，没有实际部署或修改 Kubernetes 集群。
- 不得把密码、Token、Cookie、私钥、TLS 私钥或完整认证头补写到文档和交接文件中。
- Helm 返回成功、Pod Ready、Ingress 有地址都不等于业务已经端到端可用，必须发起实际 Host/SNI 请求。
- 不要在没有盘点业务 Ingress 的情况下卸载或替换 Controller。
- 当前工作区可能受自动 `vault backup` 任务影响；继续修改前重新读取文件并检查 Git 状态。
