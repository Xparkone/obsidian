# GitLab 功能全景技术文档

## 目录

1. [文档概述](#1-文档概述)
2. [前置条件与版本边界](#2-前置条件与版本边界)
3. [产品定位：一体化 DevOps 平台](#3-产品定位一体化-devops-平台)
4. [项目管理与协作](#4-项目管理与协作)
5. [源代码管理](#5-源代码管理)
6. [CI/CD](#6-cicd)
7. [安全与合规](#7-安全与合规)
8. [包与制品](#8-包与制品)
9. [运维、发布与可观测性](#9-运维发布与可观测性)
10. [自动化与集成](#10-自动化与集成)
11. [权限与身份](#11-权限与身份)
12. [管理后台（自建）](#12-管理后台自建)
13. [AI / Duo 等新能力](#13-ai--duo-等新能力)
14. [功能速查表：场景 → 功能](#14-功能速查表场景--功能)
15. [注意事项与最佳实践](#15-注意事项与最佳实践)
16. [总结与下一步](#16-总结与下一步)

---

## 1. 文档概述

### 1.1 解决什么问题

GitLab 远不止「放代码的 Git 服务器」。团队常遇到的困惑是：

- 知道有 Issue、MR、Pipeline，但**不清楚模块如何串成一条交付链路**
- 从 GitHub / Gitea / 纯自建 Git 迁入后，**不知道下一步该启用哪些能力**
- 分不清 **CE / EE / GitLab.com 免费与付费** 的功能边界，选型时容易踩坑

本文提供一份**功能地图**：按 DevOps 生命周期说明各模块「是什么、解决什么问题、谁在用、入口与关键概念、与相邻模块的关系」，并给出少量可落地的示例。

> **与导入文档的关系**：仓库 / 项目 / Issue / 备份等迁入细节，见同目录 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md)。本文不重复导入长文，仅在相关处交叉引用。

### 1.2 适合哪些读者

- **开发者**：日常写代码、提 MR、看 Pipeline
- **运维 / 平台工程师**：管 Runner、Registry、自建实例与权限
- **技术负责人 / 工程经理**：选协作与合规能力、规划落地路径

### 1.3 阅读后能获得什么

- 建立「从需求 → 代码 → 构建 → 安全 → 发布 → 运维」的 GitLab 功能全景
- 能按场景快速对照「该用哪个功能」（第 14 节速查表）
- 知道 CE/EE/SaaS 的大致差异，避免把高级功能当成「人人都有」
- 迁入或新建实例后，知道优先打开哪些模块、如何与相邻能力配合

### 1.4 先讲结论（核心思路）

把 GitLab 当成**一条可配置的交付流水线平台**，而不是一堆独立工具：

| 阶段 | 主要能力 | 典型产物 |
|------|----------|----------|
| 计划与协作 | Group/Project、Issue、Epic、Board、Milestone | 需求与排期可见 |
| 开发与评审 | 仓库、Protected Branch、MR、CODEOWNERS | 可合并的变更 |
| 构建与验证 | Pipeline、Job、Runner、缓存/Artifacts | 可部署制品 |
| 安全与合规 | SAST/依赖扫描等、审计、合规框架 | 风险与审计证据 |
| 发布与运行 | Environments、Deploy、Pages、Feature Flags | 可回滚的发布 |
| 包与集成 | Package/Container Registry、Webhook、API | 可复用制品与外部联动 |

**落地建议（多数团队）**：先打通 **仓库 + 保护分支 + MR + 基础 CI**，再按需要加 Issue Board、Registry、安全扫描与合规；不要第一天就打开全部高级功能。

---

## 2. 前置条件与版本边界

### 2.1 环境与角色

| 项目 | 说明 |
|------|------|
| 实例形态 | **GitLab.com（SaaS）**，或 **自建 CE / EE** |
| 建议版本语境 | 功能描述以较新的 **16.x / 17.x** 习惯为主；菜单文案、侧边栏位置随版本与语言包会变，**以你实例 UI 为准** |
| 账号权限 | 读本文无需特殊权限；动手配置通常需要 **Maintainer / Owner**，实例级设置需要 **Admin** |
| 基础知识 | 熟悉 Git 分支与 Merge；了解「CI 在 Runner 上执行」的基本概念即可 |

### 2.2 CE / EE / GitLab.com 怎么读本文

| 形态 | 特点（概括） |
|------|----------------|
| **GitLab CE（社区版）** | 核心 SCM + Issue + MR + CI/CD + Registry 等基础能力；多数高级安全、Epic、高级合规、部分治理功能不可用或能力较弱 |
| **GitLab EE（企业版）** | 在 CE 之上按 **Tier（如 Premium / Ultimate）**【需要确认：具体 Tier 名称与打包随商业策略变化】开放 Epic、高级 MR 规则、安全扫描套件、合规框架、高级审计等 |
| **GitLab.com** | 托管 SaaS；个人/免费组有功能上限，付费套餐解锁更多协作与安全能力；**无 Admin Area**，部分自建专属项（LDAP 全量、外观深度定制等）不适用 |

本文在涉及付费/高级能力处会标注 **（多为 EE / 高级套餐）**，**不展开过时定价与 SKU 细节**。是否可用以实例 **Admin → Settings → License / Subscription** 或官方 Feature comparison 为准。

### 2.3 官方入口

- 产品文档总入口：[https://docs.gitlab.com/](https://docs.gitlab.com/)
- Feature comparison（CE/EE 能力对照）：以 docs.gitlab.com 当前「Feature comparison」页为准

---

## 3. 产品定位：一体化 DevOps 平台

### 3.1 这是什么

GitLab 是一体式 **DevOps 平台**（也常称 DevSecOps 平台）：用**同一套权限、同一套项目上下文**，覆盖计划、代码、CI/CD、安全、包管理、发布与协作，而不是「Git 托管 + 再接十个外部系统」。

### 3.2 解决什么问题

| 纯 Git 托管常见痛点 | GitLab 一体化带来的变化 |
|---------------------|---------------------------|
| Issue 在 Jira、CI 在 Jenkins、包在 Nexus，上下文割裂 | Issue ↔ MR ↔ Pipeline ↔ Deploy 可在同一项目串联 |
| 权限、审计分散 | Group/Project 角色与审计事件集中管理（深度因版本/套餐而异） |
| 工具链对接成本高 | Webhook / API / 官方 Integration 作为「外接」补充，而非默认必接 |

### 3.3 谁在用 / 典型用法

- **中小团队**：一套 GitLab 覆盖协作 + CI，少运维多系统
- **企业平台组**：自建 EE，统一 Runner、合规与 SSO
- **已有强工具链的团队**：GitLab 做 SCM + CI，Issue/看板可继续对接 Jira 等（见第 10 节）

### 3.4 与相邻概念的关系

```
需求/缺陷 (Issue/Epic)
    ↓ 关联
变更评审 (Merge Request)
    ↓ 触发
构建验证 (Pipeline / Job)
    ↓ 产出
制品 (Artifacts / Registry)
    ↓ 部署到
环境 (Environments / Pages / 外部集群)
    ↑ 安全扫描与合规策略贯穿其中
```

迁入现有仓库时：代码历史可用导入或 `git push` 完成；**协作与 CI 规则需要在 GitLab 侧重新配置**。导入路径详见 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md)。

---

## 4. 项目管理与协作

### 4.1 Group / Project / Namespace

**是什么**

- **Project（项目）**：代码仓库 + Issue + MR + CI + 包等能力的基本容器
- **Group（群组）**：组织多个 Project（及子 Group）的目录与权限边界
- **Namespace**：URL 与归属空间的概念——可以是个人用户命名空间，也可以是 Group

典型路径：`https://gitlab.example.com/<namespace>/<project>`

**解决什么问题**

- 用「公司 → 业务线 → 产品 → 仓库」树状结构管权限与可见性
- 在 Group 层统一成员、变量、部分策略（具体能力随版本/套餐变化）

**谁在用**

- 平台/架构：设计 Group 树与命名规范
- 开发者：在所属 Project 内日常工作

**入口 / 关键概念**

- 左侧边栏或顶部：**Groups / Projects**；创建：**New project / New group**
- **Visibility**：Private / Internal / Public（自建还可受实例策略限制）
- **Subgroup**：多级群组，便于大型组织拆分

**与相邻模块**

- 权限继承自 Group 到 Project（可再单独加人）
- Group 级 CI 变量、Runner、安全策略可向下影响 Project

---

### 4.2 Issue、Epic、Label、Milestone、Board、Roadmap

| 能力 | 是什么 | 解决什么问题 | 备注 |
|------|--------|--------------|------|
| **Issue** | 工作项：需求、缺陷、任务 | 跟踪「要做什么」 | CE/各形态均有基础 Issue |
| **Epic（史诗）** | 跨多个 Issue 的上层主题 | 大需求拆解与进度汇总 | **多为 EE** |
| **Label** | 彩色标签 | 分类、筛选、自动化规则输入 | 可在 Group 级复用 |
| **Milestone** | 里程碑 / 版本节奏 | 按迭代或版本聚合 Issue/MR | 可挂到 Group 或 Project |
| **Issue Board** | 看板（列 = Label 或状态） | 可视化流转 | 类似轻量看板工具 |
| **Roadmap** | Epic 时间线视图 | 看中长期规划 | **多为 EE**，依赖 Epic |

**典型用法**

1. 用 **Milestone** 表示迭代（如 `2026-Q3-Sprint-1`）
2. 用 **Label** 表示类型/优先级（`bug` / `feature` / `priority::high`）
3. 用 **Board** 列：`Open` → `Doing` → `Review` → `Closed`
4. 大主题用 **Epic** 挂多个 Issue（若实例支持）

**与相邻模块**

- Issue 可关联 MR；MR 合并后可自动关闭 Issue（提交信息或 MR 描述中的 closing pattern，如 `Closes #123`）
- Issue 本身不构建代码；构建走 CI

---

### 4.3 Merge Request（MR）

**是什么**

**Merge Request（合并请求）**：把源分支的变更请求合并到目标分支，并附带讨论、评审、流水线结果与签核状态。对应其他平台常称 Pull Request（PR）。

**解决什么问题**

- 强制「变更可见、可评审、可验证」后再进受保护分支
- 把讨论、CI 状态、审批收敛到一次变更上

**谁在用**

- 开发者：创建与更新 MR
- Reviewer / Maintainer：评论、Approve、合并
- 自动化：Pipeline 结果作为合并门禁

**入口 / 关键概念**

- 项目 → **Merge requests**；或推送分支后 UI 提示创建 MR
- **Draft / WIP**：草稿 MR，标明未就绪，默认可限制合并
- **Approve**：审批（规则数量、CODEOWNERS 强制审批等能力随套餐增强）
- **冲突解决**：UI 或本地解决后 push
- **Squash / 删除源分支**：合并策略选项

**与相邻模块**

- MR 通常触发 **Pipeline**；可配置「Pipeline 必须成功才能合并」
- 与 **Protected branches**、**CODEOWNERS**、**Approval rules** 组成质量门禁
- 与 Issue 双向关联，形成「需求 ↔ 变更」追溯

---

### 4.4 Wiki 与 Snippet

| 能力 | 是什么 | 适用场景 |
|------|--------|----------|
| **Wiki** | 项目内轻量文档库（常基于 Git） | 模块说明、Onboarding、运维备忘；不适合替代完整文档站时可用 Pages |
| **Snippet** | 片段托管（个人或项目级） | 分享脚本、配置片段、一次性示例；支持多文件 Snippet |

**关系**：正式架构文档可放仓库 `docs/` 或 Wiki/Pages；Snippets 不适合作为唯一知识库。

---

## 5. 源代码管理

### 5.1 仓库与分支模型

**是什么**

每个 Project 默认带一个 Git 仓库（可配置是否含 README、默认分支名如 `main`）。

**解决什么问题**

- 集中托管历史、分支、标签、合并
- 通过权限与保护规则约束谁能推、谁能合

**典型分支策略（示例，非强制）**

- `main` / `master`：受保护，仅 MR 合并
- `feature/*`：开发分支
- `release/*` 或 tag：发布锚点

**入口**：项目 → **Code → Repository / Branches / Commits / Tags**

---

### 5.2 Protected branches / tags

**是什么**

**Protected branch（保护分支）**：对指定分支限制谁可以 push、谁可以 merge、是否允许强制推送、是否允许开发者推送等。

**Protected tag**：限制谁能创建/更新标签，防止随意打正式版本号。

**解决什么问题**

- 防止直接 push 到主干、防止 force-push 抹历史
- 与 MR + CI 一起构成「主干只进评审过的变更」

**示意配置（概念）**

| 规则项 | 示例（`main`） |
|--------|----------------|
| Allowed to merge | Maintainers |
| Allowed to push and merge | No one（强制走 MR） |
| Allowed to force push | No |
| Require approval / CODEOWNERS | 按套餐开启 |

**入口**：项目 → **Settings → Repository → Protected branches / Protected tags**

**与相邻模块**：保护分支是 MR 流程的底座；不设保护时，MR 容易变成「可选仪式」。

---

### 5.3 CODEOWNERS 与签核规则（概括）

| 能力 | 说明 |
|------|------|
| **CODEOWNERS** | 在仓库中用文件声明「某路径默认由谁拥有/评审」（如 `/docs/ @docs-team`） |
| **Approval rules** | 在项目/MR 规则中要求特定用户/组审批、最少审批人数等 |

二者常与 **Protected branches**、**MR 合并门禁** 联用。高级强制规则多为 **EE**。具体语法与强制行为以实例版本文档为准。

---

### 5.4 Git LFS 与子模块（点到为止）

| 能力 | 是什么 | 注意 |
|------|--------|------|
| **Git LFS** | 大文件指针化存储，适合二进制、模型、安装包 | 自建需考虑对象存储与配额；导入时 LFS 常需单独处理，见导入文档 |
| **Git Submodule** | 仓库引用另一仓库固定提交 | 克隆需 `--recurse-submodules`；CI 中要显式处理 |

---

## 6. CI/CD

### 6.1 核心概念

| 术语 | 一句话 |
|------|--------|
| **`.gitlab-ci.yml`** | 放在仓库根目录（或自定义路径）的流水线定义文件 |
| **Pipeline** | 一次完整流水线运行（由 push、MR、定时、API 等触发） |
| **Stage** | 阶段（如 `build` → `test` → `deploy`）；同 Stage 内 Job 默认可并行 |
| **Job** | 最小执行单元：一组脚本，跑在某个 Runner 上 |
| **Runner** | 执行 Job 的代理（共享 Runner、项目/群组 Runner、或自建机器/K8s） |

**解决什么问题**

- 把构建、测试、扫描、部署变成可重复、可审计的自动化
- 与 MR 状态联动，形成合并门禁

**谁在用**

- 开发者：看 Job 日志、修失败流水线
- 平台：维护 Runner、缓存、并发与密钥

**入口**

- 配置：仓库中的 `.gitlab-ci.yml`；或 **CI/CD → Editor**
- 观察：**Build → Pipelines / Jobs**
- Runner：**Settings → CI/CD → Runners**（实例级在 Admin）

---

### 6.2 最简 `.gitlab-ci.yml` 示例

```yaml
# 最简示例：测试阶段跑单元测试（语言无关示意）
stages:
  - test

unit-test:
  stage: test
  image: python:3.12-slim   # Job 使用的容器镜像（Docker/Kubernetes executor 常见）
  script:
    - pip install -r requirements.txt
    - pytest -q
  # 仅当存在 requirements.txt 时更贴近真实项目；可按栈替换
```

**预期结果**：向默认分支或 MR 推送后，出现一条 Pipeline；`unit-test` Job 成功则该 Stage 通过。

稍完整的「构建 → 测试 → 保留产物」示意：

```yaml
stages:
  - build
  - test

build-app:
  stage: build
  script:
    - echo "Building..."
    - mkdir -p dist && echo "artifact" > dist/app.txt
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test-app:
  stage: test
  script:
    - test -f dist/app.txt
  needs: ["build-app"]   # 显式依赖，可跳过无关等待（语法随版本演进）
```

---

### 6.3 变量、缓存、Artifacts、Environments、Deploy

| 能力 | 是什么 | 典型用途 |
|------|--------|----------|
| **CI/CD Variables** | 密钥与配置（项目/群组/实例级；可 Masked/Protected） | Token、环境名、开关 |
| **Cache** | 在 Job 间复用依赖目录（如 `node_modules`） | 加速构建（**不保证**长期可靠存储） |
| **Artifacts** | Job 产出文件，供后续 Job 或人工下载 | 测试报告、二进制、覆盖率 |
| **Environments** | 逻辑环境（`staging` / `production`） | 展示部署版本、URL、停止/回滚入口 |
| **Deploy jobs** | `environment:` 字段关联的部署任务 | 持续交付到服务器/K8s/云 |

**关系**：Cache 提速 ≠ Artifacts 传产物；正式「可下载构建结果」用 Artifacts。生产部署建议配合 Protected variables + 保护分支 + 手动/受控 Job。

---

### 6.4 Auto DevOps（简述）

**Auto DevOps**：GitLab 提供的「约定大于配置」模板化流水线，试图自动检测语言并完成构建、测试、扫描、部署等。

**适用**：原型、标准 12-factor 应用、愿意接受默认意见的团队。  
**不适用**：高度定制构建或已有成熟 `.gitlab-ci.yml` 的复杂单体——此时直接维护自己的 YAML 更清晰。

---

## 7. 安全与合规

> 能力地图级说明。许多扫描与合规能力属于 **EE / 高级套餐**；CE 或免费档可能仅有基础能力或需自建外部工具替代。

### 7.1 安全扫描能力地图

| 能力 | 做什么 | 常见接入方式 |
|------|--------|----------------|
| **SAST** | 静态应用安全测试，扫源码中的常见漏洞模式 | CI 模板 / 安全扫描 Job |
| **Secret Detection** | 检测提交中的密钥、Token | CI；也可在推送侧策略中出现（随版本） |
| **Dependency Scanning** | 依赖组件漏洞（语言包依赖） | CI |
| **Container Scanning** | 容器镜像漏洞 | CI，常接 Container Registry |
| **DAST** | 动态扫描运行中的 Web 应用 | 需可访问的测试环境 |
| **License Compliance 等** | 开源许可证风险（命名与打包随产品演进） | 安全/合规报告视图 |

**谁在用**：安全左移的开发团队、AppSec、平台合规岗。  
**与相邻模块**：结果展示在 MR / Security 面板；可与合并门禁、安全策略（实例/群组级）联动。

### 7.2 审计与合规（概括）

| 能力 | 说明 |
|------|------|
| **Audit Events（审计事件）** | 记录谁在何时做了敏感操作（登录、权限变更、仓库设置等）；深度与导出能力随套餐变化 |
| **Compliance Framework / 合规流水线** | 给项目打合规标签、要求必须通过的 CI 检查（**多为 EE**） |
| **分支/MR 强制规则** | 与第 5、6 节门禁叠加，形成「流程合规」 |

**注意**：扫描「发现漏洞」≠「已合规」；合规通常还要策略、责任人、例外流程与证据留存。

---

## 8. 包与制品

### 8.1 Package Registry

**是什么**：项目/群组级的包仓库，按生态支持多种格式（如 npm、Maven、PyPI、Generic Package 等，具体列表以版本文档为准）。

**解决什么问题**：私有包不必另建一套 Nexus/Artifactory（小型到中型场景）；与 CI 用同一套权限拉取/发布。

### 8.2 Container Registry

**是什么**：容器镜像仓库，镜像路径通常与项目路径关联。

**典型用法**：CI `build` 阶段 `docker build` + `docker push`，`deploy` 阶段从 Registry 拉取。

### 8.3 Terraform State 等

| 能力 | 说明 |
|------|------|
| **Terraform State** | GitLab 可作为 Terraform HTTP state backend，带锁与权限控制 |
| **其他制品** | 如 Dependency Proxy（缓存上游镜像）、Helm Chart 相关能力等——以实例启用组件为准 |

**与导入的关系**：迁项目时，Registry / Package / LFS **默认不会**像 Git 历史一样完整跟过来，需单独迁移。详见 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md) 场景六。

---

## 9. 运维、发布与可观测性

### 9.1 GitLab Pages

**是什么**：从 CI 产物发布静态网站（文档站、产品手册、内部门户静态页）。

**典型用法**：Job 生成 `public/` 目录并配置 `pages` Job；适合文档与前端静态资源，不适合当通用应用服务器。

### 9.2 Environments 与 Feature Flags

| 能力 | 是什么 | 用途 |
|------|--------|------|
| **Environments** | 部署目标的一等公民对象 | 看当前部署、部署历史、可选的「停止环境」 |
| **Feature Flags** | 特性开关（GitLab 内置或集成） | 灰度、按用户/百分比启闭功能；深度随版本/套餐变化 |

### 9.3 Error Tracking / 可观测性集成（概括）

GitLab 可集成错误追踪与可观测性相关能力（产品形态含内置集成或对接外部 APM/日志系统，**演进较快**）。

**实践建议**：把「谁构建、谁部署、部署到哪」留在 GitLab Environments；日志/指标/链路优先用团队已有的可观测性栈，经 Webhook/API 或 Integration 回链到 MR/Issue。

---

## 10. 自动化与集成

### 10.1 Webhooks

**是什么**：在 Push、MR、Issue、Pipeline 等事件发生时，向外部 URL 发送 HTTP 回调。

**用途**：通知机器人、触发外部 CD、同步工单系统。注意校验 Secret、HTTPS 与重试/幂等。

### 10.2 REST / GraphQL API

**是什么**：可编程操作几乎所有一等资源（项目、成员、Issue、Pipeline、变量等）。

**用途**：批量管理、门户封装、迁移补数据（Issue CSV/API 等见导入文档）、ChatOps。

认证常用 **Personal Access Token（PAT）**、Project/Group Access Token、或 OAuth——按最小权限原则签发。

### 10.3 Integrations（概括）

项目/群组/实例可启用集成，例如：

- 聊天通知：Slack、飞书/Teams 等（以实例可用列表为准）
- 外部工单：Jira 等
- 告警与监控类集成

**选型**：能用官方 Integration 就少写胶水；复杂双向同步再用 Webhook + API。

### 10.4 Scheduled pipelines 与 Triggers

| 能力 | 是什么 | 典型场景 |
|------|--------|----------|
| **Pipeline schedules** | 定时跑流水线 | 夜间全量测试、定期报表、定时同步 |
| **Trigger / Trigger Token** | 用 Token 经 API 触发 Pipeline | 外部系统回调、多项目编排 |
| **下游流水线 / Multi-project** | 一项目触发另一项目 | 单体拆多仓后的编排（配置复杂度更高） |

---

## 11. 权限与身份

### 11.1 角色模型（项目级概括）

GitLab 项目角色由低到高大致为：

| 角色 | 典型能做的事（概括） |
|------|----------------------|
| **Guest** | 有限只读与评论（私有项目上能力很受限） |
| **Reporter** | 读代码、提 Issue、拉仓库等（不可随意写保护分支） |
| **Developer** | 推送非保护分支、创建 MR、常规开发 |
| **Maintainer** | 管理仓库设置、保护分支、多数 CI/Registry 配置等 |
| **Owner** | 项目/群组所有权相关（敏感权限、转让等）；群组场景更关键 |

另有 **自定义角色（Custom roles）** 等能力在高级版本中出现——以实例为准。

**Group 成员**可继承到子群组与项目；也可在项目中单独覆写。

### 11.2 可见性与「能看见什么」

权限 = **角色能力** ∩ **可见性（Public/Internal/Private）** ∩ **实例限制**。  
自建实例常关闭 Public，或限制 External users。

### 11.3 SSO / LDAP / SAML（自建常见）

| 方式 | 说明 |
|------|------|
| **LDAP / AD** | 自建常见：账号同步、登录认证 |
| **SAML / OIDC 等 SSO** | 企业统一登录；GitLab.com 与 EE 的可用范围不同 |
| **SCIM 等** | 用户生命周期自动供给（多为高级/SaaS 企业能力） |

**与导入文档**：批量「建用户」通常走 SSO/LDAP 或 Users API，而不是项目导入。见 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md) 场景四。

---

## 12. 管理后台（自建）

> **GitLab.com 无此章对应的实例 Admin Area**；SaaS 上你管理的是 Group/Project，不是整站。

### 12.1 Admin Area 概览

**入口**：通常以管理员账号访问 **/admin**。

常见管理域（概括）：

| 域 | 做什么 |
|----|--------|
| **Users / Groups** | 用户封禁、权限、群组治理 |
| **CI/CD → Runners** | 实例 Runner、共享 Runner 策略 |
| **Settings** | 注册开关、可见性默认、导入源、限流、外观（Logo/Favicon）等 |
| **Monitoring** | 后台任务、健康与资源相关视图（随安装方式变化） |
| **Deploy / License** | EE 许可证（若适用） |

### 12.2 配额、外观与 Runner（概括）

- **配额**：磁盘、仓库大小、CI 分钟（SaaS 更突出；自建多为磁盘与并发）
- **外观**：登录页与导航品牌化，便于内部平台识别
- **Runner 治理**：哪些项目能用共享 Runner、是否允许实例 Runner、executor 安全隔离（Docker/K8s/Shell 风险模型不同）

运维安装与备份恢复不在本文展开；整站备份属「实例运维」而非功能模块教程，导入/灾备边界见导入文档场景五。

---

## 13. AI / Duo 等新能力

**是什么**：GitLab 将 AI 助手能力（常以 **GitLab Duo** 等品牌出现）嵌入代码建议、MR 总结、安全解释、Chat 等场景。

**阅读本节能得到的正确预期**

- 能力**随版本与套餐快速变化**，本文不罗列易过时的功能清单
- 可用性取决于：**实例版本**、是否启用 AI 功能、网络出站策略、许可证/订阅
- 落地前在测试组验证：数据是否出网、是否满足合规、是否对开发体验有净收益

**建议**：把 Duo 当「加速建议层」，门禁仍以 MR 评审 + CI + 权限为准，不把 AI 输出当作唯一审批依据。

---

## 14. 功能速查表：场景 → 功能

| 你想… | 优先用 | 备注 |
|-------|--------|------|
| 建组织与权限边界 | Group + Project + 角色 | 先设计树，再批量加人 |
| 管需求与缺陷 | Issue + Label + Milestone + Board | 大主题加 Epic（EE） |
| 做代码评审 | MR + Protected branch | 再加 CODEOWNERS / Approve |
| 自动测试与构建 | `.gitlab-ci.yml` + Runner | 先通再优化缓存 |
| 保留构建产物 | Artifacts | 别用 Cache 当制品库 |
| 存容器镜像 / 私有包 | Container / Package Registry | 迁入需单独搬 |
| 部署到环境并可见 | Environments + deploy Job | 生产用 Protected 变量 |
| 发静态文档站 | Pages | CI 产出 `public/` |
| 定时任务 | Pipeline schedules | 注意 Runner 负载 |
| 通知到聊天/外部 CD | Webhooks / Integrations | 校验 Secret |
| 批量改资源、做门户 | API（REST/GraphQL） | 最小权限 Token |
| 安全左移 | SAST / Secret / Dependency / Container 扫描 | 多为 EE；先看套餐 |
| 审计谁改了权限 | Audit Events | 深度随套餐 |
| 企业统一登录 | SSO / LDAP / SAML | 自建高频 |
| 灰度发版 | Feature Flags + Environments | 确认实例是否启用 |
| 从 GitHub 等迁入 | Import / Direct Transfer / git push | **详见导入文档** |
| AI 辅助编码/总结 | Duo 等 | 以版本与合规为准 |

---

## 15. 注意事项与最佳实践

1. **先门禁后繁荣**：保护分支 + MR + 最小 CI，再扩展 Board、安全、合规。
2. **变量分级**：生产密钥用 Protected + Masked；禁止写进仓库。
3. **Runner 隔离**：生产部署 Runner 与普通共享 Runner 分离，避免不可信 Job 触达生产凭据。
4. **Cache ≠ 可靠存储**：依赖加速用 Cache；发布物用 Artifacts 或 Registry。
5. **Group 变量与策略慎用**：影响面大，变更要有公告与回滚思路。
6. **CE/EE 预期管理**：不要在方案里默认「一定有 Ultimate 扫描与 Epic」。
7. **版本以实例为准**：菜单路径、YAML 关键字、安全报告 UI 都会变；升级前读 Release note。
8. **迁入后还有「功能开通」**：导入只解决数据搬迁；分支规则、CI、权限模型要单独设计（见 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md)）。

---

## 16. 总结与下一步

### 16.1 核心要点

- GitLab 是**一体化 DevOps 平台**：协作、代码、CI/CD、安全、包、发布在同一项目上下文中协作。
- 日常交付主链路是：**Issue（可选）→ 分支 → MR → Pipeline →（Registry）→ Environment**。
- **Protected branches + MR + CI** 是质量底座；安全扫描与合规是增强层（常依赖 EE/高级套餐）。
- 自建还要规划 **身份（SSO/LDAP）、Admin 策略、Runner 与存储**；SaaS 则聚焦 Group 治理与套餐能力。

### 16.2 建议的下一步

1. 在目标实例上画一张 Group/Project 树，并定默认分支保护规则  
2. 给一个样板项目加上最小 `.gitlab-ci.yml`，打通 Runner  
3. 按需打开：Issue Board、Container Registry、安全扫描模板  
4. 若处于迁入阶段：先读 [`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md) 选对导入路径，再回到本文开通功能  
5. 对照官方 Feature comparison，确认本团队套餐真正可用的高级项  

### 16.3 延伸阅读

- GitLab 官方文档：[https://docs.gitlab.com/](https://docs.gitlab.com/)
- CI/CD YAML 参考：docs 中「CI/CD YAML syntax reference」
- 同目录导入实操：[`gitlab-import-guide.md`](GitLab%20数据导入技术文档：场景分流与实操指南.md)

---

*文档定位：功能全景与模块关系说明，非官方手册全文替代。功能可用性以你所使用的 GitLab 版本与许可证为准。*
