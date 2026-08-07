# GitLab 数据导入技术文档：场景分流与实操指南

## 目录

1. [文档概述](#1-文档概述)
2. [前置条件](#2-前置条件)
3. [核心概念与场景选型](#3-核心概念与场景选型)
4. [场景一：从其他平台迁入项目](#4-场景一从其他平台迁入项目)
5. [场景二：纯 Git 仓库导入](#5-场景二纯-git-仓库导入)
6. [场景三：Issue / 工单等业务数据导入](#6-场景三issue--工单等业务数据导入)
7. [场景四：用户 / 成员数据](#7-场景四用户--成员数据)
8. [场景五：备份恢复式整站数据](#8-场景五备份恢复式整站数据)
9. [场景六：容器镜像 / Package Registry / LFS](#9-场景六容器镜像--package-registry--lfs)
10. [完整示例：GitHub 项目迁入自建 GitLab](#10-完整示例github-项目迁入自建-gitlab)
11. [常见问题与排查](#11-常见问题与排查)
12. [注意事项与最佳实践](#12-注意事项与最佳实践)
13. [命令与入口速查](#13-命令与入口速查)
14. [总结与下一步](#14-总结与下一步)

---

## 1. 文档概述

### 1.1 解决什么问题

人们说「GitLab 怎么导入数据」时，往往把几种**完全不同**的能力混在一起：

| 口头说法 | 实际含义 | 推荐手段 |
|----------|----------|----------|
| 把 GitHub / 另一套 GitLab 的项目搬过来 | 项目 / 群组迁移 | UI Import、Direct Transfer、导出文件 |
| 把已有 Git 仓库放进 GitLab | 仅代码与历史 | `git push`、Repository by URL、Mirror |
| 批量建 Issue | 工单业务数据 | CSV / API |
| 批量建账号、加人 | 身份与成员 | API / SSO / Admin（**不是**项目导入） |
| 整台 GitLab 搬家 / 灾备 | 实例级数据 | `gitlab-backup`（**不是**日常项目导入） |
| 镜像、包、大文件 | Registry / LFS | 专用工具，默认不随「仓库导入」一起完整迁完 |

本文把上述场景**分开说明**，给出适用条件、能导入什么、不能导入什么，以及可复制的步骤与命令。

### 1.2 适合哪些读者

- 需要把外部代码托管迁入 **GitLab.com** 或 **自建 GitLab（CE/EE）** 的开发者、技术负责人
- 负责自建实例的运维 / 平台工程师（导入源开关、备份恢复、用户供给）
- 需要批量补 Issue、成员或仓库的工程师

### 1.3 阅读后能获得什么

- 先选对「导入」类型，避免用错工具（例如用备份恢复去「迁一个 GitHub 项目」）
- 掌握 GitHub / Bitbucket / Gitea / GitLab→GitLab 等主流迁入路径
- 理解 Direct Transfer 与「纯 Git push」在数据完整度上的差异
- 能用 CSV / API 处理 Issue 与用户供给的基本思路
- 分清项目导入与 `gitlab-backup` 整站恢复的边界

### 1.4 先讲结论（核心思路）

按目标选路径，不要一上来就找「万能导入按钮」：

1. **只要代码历史** → 空项目 + `git push`，或 **Repository by URL**（最快、最稳）
2. **要 Issue / MR（PR）/ Wiki / 成员映射** → 用对应平台的 **Import project**（或 GitLab→GitLab 的 **Direct Transfer**）
3. **GitLab 实例之间整组搬迁** → 优先 **Direct Transfer（Bulk Import）**；单项目可用 **Project export/import**
4. **批量工单** → Issue **CSV** 或 **Issues API**
5. **账号体系** → SSO/LDAP 或 **Users API**（GitLab **没有**一等公民的「Admin 上传 CSV 批量建用户」官方流程，见第 7 节）
6. **整站同版本迁移 / 灾备** → **`gitlab-backup`**，与「从一个外部项目导入」无关

> **UI 说明**：下文菜单路径以 GitLab **16/17** 代习惯写法为主（如「左侧边栏 → Create new → New project/repository → Import project」）。不同小版本、语言包、CE/EE 与 GitLab.com 的文案可能略有差异，**以你实例实际 UI 为准**。官方文档入口：[Import and migrate groups and projects](https://docs.gitlab.com/user/project/import/)。

---

## 2. 前置条件

### 2.1 环境与权限

| 项目 | 建议 / 要求 |
|------|-------------|
| 目标实例 | GitLab.com，或自建 CE/EE（建议 **16.x / 17.x**；命令与能力以目标实例版本为准） |
| 角色 | 导入到某 Group：通常至少 **Maintainer**；部分管理项需 **Owner** 或实例 **Admin** |
| 自建 Admin | 开启对应 **Import sources**（见下）；大仓库需足够磁盘、Sidekiq 与网络带宽 |
| 网络 | 目标实例能访问源平台 API / Git（或能上传导出包）；私有网络需代理或跳板 |
| 令牌 | 源侧 PAT / OAuth；目标侧需有创建项目权限的账号 |

### 2.2 自建实例：开启导入源（Import sources）

自建 GitLab **默认不一定**打开所有导入源；GitLab.com 上多数已默认开启。

**做什么**：管理员在 Admin 中打开需要的导入源。  
**为什么**：未开启时，UI 看不到「GitHub / Bitbucket / …」入口，或提示不可用。  
**预期结果**：`Import project` 页面出现对应图标。

近似路径（Admin）：

1. 使用 Admin 账号登录  
2. **Admin Area**（扳手图标）→ **Settings** → **General**  
3. 展开 **Import and export** / **Import sources**（名称因版本而异）  
4. 勾选：GitHub、Bitbucket Cloud、Bitbucket Server、Gitea、GitLab export、Repository by URL、Manifest file 等  
5. 保存

也可在 `gitlab.rb` 中配置（Omnibus 示例思路，具体键名以你版本文档为准，不确定处标为 **【需要确认】**）：

```ruby
# /etc/gitlab/gitlab.rb（示意）
gitlab_rails['import_sources'] = [
  'github',
  'bitbucket',
  'bitbucket_server',
  'gitea',
  'git',
  'gitlab_project',
  'manifest',
]
```

```bash
sudo gitlab-ctl reconfigure
```

### 2.3 必备基础知识

- 熟悉 Git：`remote`、`push`、`mirror`、分支与 tag  
- 理解 GitLab 的 **Group / Project / Namespace**  
- 了解 PAT（Personal Access Token）与权限范围（scope）  
- 若做整站备份：会在 Omnibus 上执行 `gitlab-backup` / `gitlab-ctl`

### 2.4 CE / EE / GitLab.com 差异（先记住）

| 能力 | GitLab.com | 自建 CE | 自建 EE |
|------|------------|---------|---------|
| 平台 Import（GitHub 等） | 通常已开 | 需 Admin 开 Import sources | 同 CE，另有商业特性 |
| Direct Transfer | 可用 | 可用（需两端可达、权限足够） | 同左；部分 Group 级资源更完整 |
| Repository Mirror 拉镜像 | 高级层可能限制 | CE 多为 push mirror 等；**pull mirror 多为 Premium+** | Premium/Ultimate 常见 |
| `gitlab-backup` | **不可用**（SaaS） | **可用** | **可用** |
| CSV 导 Issue | 可用（角色足够） | 可用 | 可用 |
| 用户供给 | 邀请 / SCIM 等 | LDAP/SAML/API/Admin | 同左 + 更多企业身份能力 |

---

## 3. 核心概念与场景选型

### 3.1 关键术语（一句话）

- **Import project**：通过 UI/API 从外部源**创建新项目**并尽量带上 Issue、MR 等元数据。  
- **Direct Transfer（曾称 Bulk Import）**：用 API 在 **GitLab → GitLab** 之间**复制** Group（可选带 Project），不是「移动」。  
- **Project / Group export**：导出 `.tar.gz`，再到目标实例导入；适合单项目或网络隔离场景。  
- **Repository by URL**：只按 Git URL 拉仓库，**几乎只有 Git 数据**。  
- **Mirror**：持续同步远端 Git；**不**等价于完整业务数据迁移。  
- **gitlab-backup**：实例级备份/恢复（数据库、仓库等），用于同版本灾备或整机迁移。

### 3.2 选型流程图（文字版）

```
要导入什么？
├─ 仅 Git 提交历史 ──────────────► git push / Repository by URL / mirror
├─ GitHub/Bitbucket/Gitea 项目 ──► Import project（对应源）
├─ 另一套 GitLab 的 Group/Project
│   ├─ 网络互通、要尽量全 ───────► Direct Transfer
│   └─ 单项目或离线 ─────────────► Project export → import
├─ 只要批量 Issue ───────────────► CSV / Issues API
├─ 账号与成员 ───────────────────► SSO/LDAP / Users API / 成员 API
└─ 整台实例搬家/恢复 ────────────► gitlab-backup（同版本）
```

### 3.3 「能导入 / 不能导入」总览（务必先读）

| 数据类型 | 平台 Import（如 GitHub） | Direct Transfer | 纯 git push | gitlab-backup |
|----------|--------------------------|-----------------|-------------|---------------|
| Git 仓库（分支/tag） | 通常 ✓ | ✓ | ✓ | ✓（整站） |
| Issue / MR（PR） | 多数 ✓（视源） | ✓ | ✗ | ✓（整站） |
| Wiki | 多数 ✓ | ✓ | ✗（除非另推 wiki.git） | ✓ |
| CI/CD 变量 | ✗（敏感，通常排除） | ✗（排除） | ✗ | ✓（在备份范围内时） |
| Job 日志 / Artifacts | ✗ | ✗ | ✗ | 视备份配置 |
| Container Registry 镜像 | ✗ | ✗ | ✗ | 常需另备；默认备份策略 **【需要确认】** |
| Package Registry | ✗ | ✗ | ✗ | 视配置 |
| LFS | 常 ✓（需权限/配置） | ✓ | 需 `git lfs` 正确推送 | ✓（通常含） |
| 用户账号本身 | ✗（映射到已有用户或占位） | ✗（不迁用户实体） | ✗ | ✓（整站含用户表） |

---

## 4. 场景一：从其他平台迁入项目

**适用条件**：需要把**代码 + 协作元数据**（Issue、MR/PR、Wiki、标签等）迁到 GitLab；源平台受官方 Importer 支持。

**不适用**：只要代码 → 用第 5 节；整站灾备 → 用第 8 节。

### 4.1 通用 UI 入口（近似路径）

1. 登录目标 GitLab  
2. 左上角 **Create new（+）** → **New project/repository**  
3. 选择 **Import project**  
4. 选择源：GitHub / Bitbucket Cloud / Bitbucket Server / Gitea / GitLab export / Repository by URL 等  
5. 授权或粘贴 Token → 勾选仓库 → **Import**

**Group 级导入历史**（Direct Transfer 等）：Group → **Settings** 或独立的 **Import** / **Group import history** 页面（路径因版本而异）。

**Admin 视角**：部分实例在 Admin 提供全局 Import 相关设置；日常导入仍以用户在 Namespace 下操作为主。

### 4.2 从 GitHub 导入

**适用**：GitHub.com 或 GitHub Enterprise；要带 PR→MR、Issue、Wiki 等。

**权限要点**：

- 对目标 Group 至少 **Maintainer**  
- GitHub 侧能访问该仓库；Classic PAT 常用 scope：`repo`；导入协作者或 LFS 时可能需要 `read:org`  
- **UI 固定从 `github.com` 导入**；自建 **GitHub Enterprise Server** 请用 **Import API**（指定主机）

#### 步骤（OAuth 或 PAT）

1. **做什么**：打开 **Import project → GitHub**，用 OAuth 授权或粘贴 GitHub Classic PAT。  
   **为什么**：GitLab 需代表你调用 GitHub API 拉元数据。  
   **预期结果**：出现可导入仓库列表（Owner / Collaborated / Organization 等 Tab）。

2. **做什么**：选择是否导入 Markdown 附件、协作者、大量评论的替代导入方式等（可选，会显著变慢）。  
   **为什么**：默认偏快，附件/超大评论量需显式打开。  
   **预期结果**：勾选项被保存到本次导入任务。

3. **做什么**：对每个仓库点 **Import**，或 **Import all**；必要时改目标 Namespace / 项目名。  
   **为什么**：避免命名冲突，控制落在哪个 Group。  
   **预期结果**：状态变为 Complete / Partially completed / Failed。

#### API 示例（适合 GHES 或自动化）

先准备 GitLab PAT（需有创建项目权限）与 GitHub Token：

```bash
# 示意：通过 GitLab Import API 从 GitHub 导入
# 具体参数名以你目标版本 API 文档为准
curl --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --header "Content-Type: application/json" \
  --data '{
    "personal_access_token": "'"${GITHUB_TOKEN}"'",
    "repo_id": 123456789,
    "target_namespace": "my-group",
    "new_name": "my-project"
  }' \
  "https://gitlab.example.com/api/v4/import/github"
```

自建 GHES 时还需传 GitHub 主机相关参数（见官方 [Import your project from GitHub](https://docs.gitlab.com/user/project/import/github/)），主机字段以当前文档为准 **【需要确认】**。

#### GitHub 通常能导入 / 不能导入

**常见可导入**（随版本增强，以官方 “Imported data” 为准）：

- 仓库描述、Git 数据、分支、分支保护（部分规则映射）  
- Issues、Pull Requests（含评论、部分 review）  
- Wiki、Milestones、Labels、Release 说明  
- LFS 对象  
- Collaborators（可选；角色映射到 Guest/Reporter/Developer/…）

**常见不导入或受限**：

- GitHub **Organization/Team 结构本身**不会变成 GitLab Group 树  
- GitHub Actions 工作流**不会**自动变成等价的 `.gitlab-ci.yml` 语义完整迁移（文件若在仓库里会随 Git 进来，但密钥、Environment secrets 等需重建）  
- 部分附件、超大评论量、私有仓库历史附件有已知限制  
- **CI 变量、Deploy keys、Webhook 密钥**等敏感项不会「自动安全搬家」

### 4.3 从 Bitbucket / Gitea 导入

**Bitbucket Cloud**

- 入口：**Import project → Bitbucket Cloud**  
- 通常导入：仓库、Issue（含评论）、PR（含评论）、Milestones、Wiki、Labels、LFS 等  
- 需完成 Bitbucket OAuth / 授权；用户映射依赖昵称与 GitLab 侧身份匹配，失败时作者常回落到导入发起人

**Bitbucket Server（自建 Stash）**

- 入口：**Bitbucket Server**；需填写 Server URL 与凭据  
- 适合内网 Bitbucket；防火墙需放行目标 GitLab → Bitbucket

**Gitea**

- 入口：**Gitea**；提供 Gitea 地址与 Access Token  
- 适合从轻量自建 Git 服务迁入；元数据覆盖面通常弱于 GitHub importer，细节以你版本文档为准 **【需要确认】**

### 4.4 GitLab → GitLab：Direct Transfer（推荐）

**Direct Transfer**：目标 GitLab 通过 API 连接源 GitLab，**复制**顶层 Group（API 也可迁 subgroup），可选一并迁项目。

**适用条件**：

- 源、目标均为 GitLab，且目标能访问源的 API  
- 需要尽量保留 Group 结构、Issue、MR、部分设置等  
- 两端版本不要差太离谱（过旧源/过新目标可能缺 relation；官方建议较新的 16+ 以利用批量 relation 导出）

**不适用**：

- 源不是 GitLab  
- 想「剪切移动」同实例 Group（同实例请用 **Transfer group/project**，不是 Direct Transfer）  
- 期望连 CI 变量、Registry 镜像、Job 日志一起自动迁完（这些被排除）

#### UI 步骤（近似）

1. 在**目标**实例：进入 Group 导入 / **Migrate groups by direct transfer** 相关页面（常从 **New group** 旁的 import/migrate，或 Group 导入历史入口进入）  
2. 填写**源** GitLab URL，用有足够权限的源账号授权（Personal Access Token 等）  
3. 选择要导入的顶层 Group：**Import with projects** 或 **Import without projects**  
4. 等待任务完成 → 在 **Group import history** 查看 **View details** / 错误

**做什么**：先在源实例建好只读或迁移用账号，并确认 Token scope 足够。  
**为什么**：权限不足会导致部分 relation 失败，出现 Partially completed。  
**预期结果**：目标出现新 Group 副本；项目内部分对象带 **Imported** 标记（16.x/17.x 常见）。

#### 能迁 / 不能迁（摘要）

官方清单见：[Items migrated when using direct transfer](https://docs.gitlab.com/user/group/import/migrated_items/)。以下为常用结论：

**Group 侧常迁**：Badges、Boards、Epics（EE）、Labels、Milestones、Iterations、Subgroups、Uploads、Wikis 等。

**Project 侧常迁**：仓库与分支、Issues、MRs、Labels、Milestones、LFS、Designs、Snippets、Releases、部分 Pipeline **记录**（状态/时间等）、Protected branches、部分 Settings 等。

**明确排除（敏感或不支持）示例**：

- **CI/CD variables**、Pipeline schedule variables、Pipeline triggers  
- **Job logs / Job artifacts**  
- **Container Registry images**、Package Registry  
- Deploy tokens / Deploy keys、Webhooks、加密 Token  
- 用户账号实体与用户的 PAT  
- Environments、Feature flags、Agents、部分 Approval rules / MR dependencies 等（以当前版本文档为准）

> 复制完成后，**务必在目标手工重建**：CI 变量、Webhook、Registry 镜像、Runner、集成密钥。

### 4.5 GitLab 单项目：导出文件再导入

**适用**：网络隔离、只迁一两个项目、或 Direct Transfer 不可用。

**步骤概要**：

1. 源项目：**Settings → General → Advanced → Export project**  
2. 下载导出包（邮件或 UI 通知）  
3. 目标：**Import project → GitLab export**，上传文件并选择 Namespace  

**限制**：

- 大项目导出/导入易超时，需调 Sidekiq、Puma、工作超时等（自建）  
- 导出内容集合与 Direct Transfer **不完全相同**，仍以官方 `import_export.yml` 为准  
- 同样**不要假设** CI 变量与 Registry 会完整包含

### 4.6 导入后必做清单

- [ ] 核对默认分支、保护分支、MR 审批规则  
- [ ] 重建 **CI/CD Variables**、密钥、Webhook  
- [ ] 配置 **Runner** 与 `.gitlab-ci.yml`  
- [ ] 检查成员与权限（占位用户 / 映射用户）  
- [ ] 验证 LFS、子模块 URL  
- [ ] 通知团队改 `git remote`，旧平台设归档只读

---

## 5. 场景二：纯 Git 仓库导入

**适用条件**：只需要提交历史、分支、标签；Issue/MR 可不要，或以后用别的方式补。

这是**最可控、最不容易踩权限坑**的路径。

### 5.1 空项目 + git push（推荐日常）

1. **做什么**：在 GitLab 创建 **空白项目**（不要勾选 README，以免首推冲突）。  
   **为什么**：已有 README 的非空仓库会导致 `push` 被拒绝，需先 pull `--allow-unrelated-histories`。  
   **预期结果**：得到仓库 URL（HTTPS 或 SSH）。

```bash
# 已有本地仓库
cd /path/to/existing-repo
git remote add gitlab git@gitlab.example.com:my-group/my-project.git
# 或：git remote set-url origin git@gitlab.example.com:my-group/my-project.git

# 推送所有分支与标签
git push -u gitlab --all
git push gitlab --tags
```

若源是裸镜像副本：

```bash
git clone --mirror https://github.com/org/repo.git
cd repo.git
git remote set-url origin git@gitlab.example.com:my-group/my-project.git
git push --mirror
```

**注意**：`--mirror` 会镜像删除等行为，目标应是**空仓库**；生产上先在测试项目验证。

### 5.2 Repository by URL（UI）

1. **Import project → Repository by URL**  
2. 填写 Git URL；私有库填写用户名/密码或 Token  
3. 选择 Namespace 与项目名 → 创建  

**预期结果**：GitLab 代为 clone；一般**只有 Git 数据**，没有 GitHub Issue。

### 5.3 Pull / Push Mirror（持续同步）

- **Push mirror**：GitLab 为源，向外推（CE 也常见）  
- **Pull mirror**：从外部拉到 GitLab（多为 **Premium/Ultimate**）  

路径近似：项目 **Settings → Repository → Mirroring repositories**。

**适用**：过渡期双写、只读镜像。  
**不适用**：当作「带 Issue 的完整迁移」；Mirror **不**同步 PR/Issue。

### 5.4 Wiki 仓库（可选）

GitLab 项目 Wiki 有独立 Git 仓库，URL 形如：

```text
git@gitlab.example.com:my-group/my-project.wiki.git
```

若源平台 Wiki 也是 Git，可单独 clone 再 push 到上述地址（需项目已启用 Wiki）。

---

## 6. 场景三：Issue / 工单等业务数据导入

**适用**：项目已在 GitLab，只需批量补 Issue；或不想迁整个外部项目。

### 6.1 CSV 导入 Issue

**权限**：对项目具备 Planner / Reporter / Developer / Maintainer / Owner 等足够角色（具体角色名随版本微调）。

**CSV 要求**（官方约定）：

- 必须有表头 **`title`**、**`description`**（大小写不敏感）  
- 还可识别：`due_date`、`milestone`、`type` 等；**其他列默认忽略**  
- 分隔符可为逗号、分号或 Tab  
- 导入发起人会成为 Issue **作者**  
- 可在 `description` 里写 **quick actions**（如 `/label ~bug`、`/assign @user`），且标签、里程碑、被指派人须**已存在**

示例 `issues.csv`：

```csv
title,description,due_date,milestone
登录页 500,"复现步骤：
1. 打开 /login
2. 提交空表单

/label ~bug
/assign @alice",2026-08-01,Sprint-32
补充文档,"/label ~docs",,
```

**UI 步骤**：

1. 进入项目 **Plan → Issues**（或 **Issues** 列表）  
2. 若已有 Issue：右上角 **Actions → Import CSV**；若无列表：页面中部 **Import CSV**  
3. 上传文件 → 后台处理 → 邮件通知结果  

官方说明：[Importing issues from CSV](https://docs.gitlab.com/user/project/issues/csv_import/)。

### 6.2 API / 脚本批量导入

适合从 Jira、飞书、自建工单系统导出后转换。

```bash
# 创建一个 Issue
curl --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --header "Content-Type: application/json" \
  --data '{
    "title": "无法重置密码",
    "description": "来自旧系统 TICKET-10086",
    "labels": "bug,customer",
    "assignee_ids": [42]
  }' \
  "https://gitlab.example.com/api/v4/projects/123/issues"
```

脚本思路：

1. 导出源系统 → 规范化 JSON/CSV  
2. 先在 GitLab 创建 labels / milestones / members  
3. 按依赖顺序调用 Issues API；需要评论再用 Notes API  
4. 记录「旧 ID → 新 IID」映射，便于改链接  

**MR 批量导入**：无通用 CSV；应走平台 Importer，或对 `merge_requests` API 谨慎编写（需源分支存在，复杂度高）。

---

## 7. 场景四：用户 / 成员数据

**适用**：自建 GitLab 开户、给 Group/Project 批量加人。  
**关键澄清**：这与「项目 Import」是两条线——**迁项目不会在目标实例自动建齐所有源用户账号**（Direct Transfer 也不迁用户实体；贡献者映射到已有用户或占位/导入者）。

### 7.1 官方常见供给方式

| 方式 | 适用 | 说明 |
|------|------|------|
| Admin UI 手动创建 | 少量用户 | **Admin → Users → New user** |
| **Users API** | 批量脚本 | 自建最常见自动化手段 |
| LDAP / AD 同步 | 企业内网 | 账号以目录为准 |
| SAML / OIDC / SCIM | SSO | GitLab.com Group 与 EE 常见；登录即开户或由 IdP 推送 |
| 邀请邮件 | SaaS/自建 | 适合外部协作 |

> **关于「CSV 导入用户」**：GitLab **没有**像「Admin 上传 CSV 一键创建全部用户」这样的一等公民通用功能（易与 Issue CSV、或 Duo 座位 CSV 混淆）。若业务强依赖 CSV，请用 **API 读 CSV 建用户**，或走 **LDAP/SSO**。部分 Rake 任务支持用 CSV **给已有用户分配 Duo 座位**，那是许可证座位，不是开户。

### 7.2 Users API 批量开户示例

```bash
# 从 CSV 读入并创建用户的示意（bash + curl）
# CSV 列：username,email,name,password
while IFS=, read -r username email name password; do
  [ "$username" = "username" ] && continue  # 跳过表头
  curl --request POST \
    --header "PRIVATE-TOKEN: ${GITLAB_ADMIN_TOKEN}" \
    --header "Content-Type: application/json" \
    --data "{
      \"username\": \"${username}\",
      \"email\": \"${email}\",
      \"name\": \"${name}\",
      \"password\": \"${password}\",
      \"skip_confirmation\": true
    }" \
    "https://gitlab.example.com/api/v4/users"
done < users.csv
```

然后将用户加入 Group：

```bash
# access_level: 10 Guest, 20 Reporter, 30 Developer, 40 Maintainer, 50 Owner
curl --request POST \
  --header "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  --data "user_id=42&access_level=30" \
  "https://gitlab.example.com/api/v4/groups/my-group/members"
```

### 7.3 自建 Rake：把已有用户加进项目/组（不是开户）

```bash
# 将某用户加到所有项目（慎用）
sudo gitlab-rake gitlab:import:user_to_projects[user@example.com]

# 将所有用户加到所有组（极度慎用，仅实验环境）
sudo gitlab-rake gitlab:import:all_users_to_all_groups
```

### 7.4 权限与 SSO 注意

- 先定 **Group 继承权限** 模型，再批量加成员，避免每人直接塞进上百项目  
- SSO 开启后，尽量**不要**再靠脚本设永久本地密码；密码策略与 IdP 一致  
- 导入项目时的 **collaborators** 可能占用 License Seat，并映射到较高角色（如 Owner），导入前看清选项  
- 用户映射失败时，历史 Issue 作者会变成导入者或占位用户——迁项目前最好先统一邮箱/账号

---

## 8. 场景五：备份恢复式「整站数据」

**一句话**：`gitlab-backup` 解决的是 **「整台 GitLab 实例」** 的备份与同版本恢复，**不是**「把一个 GitHub 仓库搬进现有 GitLab」的日常手段。

### 8.1 适用 / 不适用

| 适用 | 不适用 |
|------|--------|
| 自建实例灾备 | GitLab.com（你不能 SSH 上去跑 backup） |
| 同版本迁移到新服务器 | 从 GitHub「导入一个项目」 |
| 演练恢复、勒索/磁盘故障 | 跨大版本直接 restore（通常必须先对齐版本） |

### 8.2 创建备份（Omnibus）

```bash
# 创建备份（默认路径常见为 /var/opt/gitlab/backups）
sudo gitlab-backup create

# 仅备份部分组件示例（跳过 Registry 等，按需）
sudo gitlab-backup create SKIP=registry,builds,artifacts
```

同时务必备份 **密钥与配置**（否则恢复后会话/CI 密钥对不上）：

```bash
# 典型需另行备份的文件（路径以 Omnibus 为准）
# /etc/gitlab/gitlab.rb
# /etc/gitlab/gitlab-secrets.json
```

### 8.3 恢复（必须同版本）

**做什么**：在**相同 GitLab 版本**的实例上执行 restore。  
**为什么**：备份与应用 schema 强绑定，跨版本极易失败。  
**预期结果**：数据库与仓库回到备份点；随后启动服务并检查。

```bash
# 1. 停止连接数据库的组件（官方文档步骤随版本微调）
sudo gitlab-ctl stop puma
sudo gitlab-ctl stop sidekiq

# 2. 将备份文件放到备份目录，文件名形如：1710000000_2026_03_10_17.0.0_gitlab_backup.tar
sudo cp /path/to/1710000000_2026_03_10_17.0.0_gitlab_backup.tar /var/opt/gitlab/backups/
sudo chown git:git /var/opt/gitlab/backups/*_gitlab_backup.tar

# 3. 恢复（BACKUP=时间戳前缀，不含 _gitlab_backup.tar）
sudo gitlab-backup restore BACKUP=1710000000_2026_03_10_17.0.0

# 4. 恢复 gitlab-secrets.json / gitlab.rb 后
sudo gitlab-ctl reconfigure
sudo gitlab-ctl start
sudo gitlab-rake gitlab:check SANITIZE=true
```

### 8.4 与「项目导入」如何配合

若只想从整站备份里救出**某一个项目**：

1. 在临时实例 **同版本 restore** 全量备份  
2. 在临时实例对该项目做 **Export**  
3. 在正式实例 **Import GitLab export**  

不要尝试手工从备份 tar 里抠单个项目目录拼到生产库（极易不一致）。

---

## 9. 场景六：容器镜像 / Package Registry / LFS

这些**不是**「代码仓库导入」的默认路径；平台 Import / Direct Transfer **通常排除** Registry 镜像与 Package。

### 9.1 Git LFS

- GitHub / Direct Transfer 等场景下，LFS 对象**常常可以**随导入过来（需 Token 权限与源上确有 LFS）  
- 纯 `git push` 时，客户端需安装 LFS，并保证指针与对象都推上：

```bash
git lfs install
git lfs push --all gitlab
git push gitlab --all
```

### 9.2 Container Registry

迁移思路（示意）：

```bash
# 源拉取
docker pull registry.github.example/org/app:1.2.3
docker tag registry.github.example/org/app:1.2.3 registry.gitlab.example.com/my-group/my-project/app:1.2.3
docker login registry.gitlab.example.com
docker push registry.gitlab.example.com/my-group/my-project/app:1.2.3
```

或用 `skopeo copy` / 镜像同步工具做批量。CI 中的镜像地址要一并改掉。

### 9.3 Package Registry（npm / Maven / PyPI 等）

按包类型用官方客户端重新 publish 到 GitLab Package Registry；或从旧 Registry 拉取后再推送。**没有**与「Import project」绑定的一键完整迁移。

---

## 10. 完整示例：GitHub 项目迁入自建 GitLab

**背景**：自建 `https://gitlab.example.com`（17.x），Group `platform`，从 GitHub.com 导入 `acme/payments-api`，并保留 Issue/PR。

### 10.1 准备

1. Admin 确认已勾选 **GitHub** Import source  
2. 目标 Group `platform` 中你的角色 ≥ Maintainer  
3. GitHub Classic PAT：`repo`（+ 按需 `read:org`）  
4. 相关同事在 GitLab 已有账号，且邮箱尽量与 GitHub 公开邮箱一致（利于映射）

### 10.2 执行导入

1. GitLab：**+ → New project/repository → Import project → GitHub**  
2. 粘贴 PAT → 授权  
3. 找到 `acme/payments-api`，目标设为 `platform/payments-api`  
4. 按需勾选 Import Markdown attachments / collaborators  
5. 点击 **Import**，等待 **Complete**

### 10.3 导入后加固

```bash
# 开发者改远程
git remote set-url origin git@gitlab.example.com:platform/payments-api.git
git fetch origin
git branch -u origin/main main
```

在 GitLab UI：

1. **Settings → CI/CD → Variables** 写入原 GitHub Secrets 对应变量  
2. **Settings → Webhooks** 重建  
3. 确认 **Settings → Repository → Protected branches**  
4. 跑一次 Pipeline，修 `.gitlab-ci.yml` 与镜像路径  

若只需代码、不要 Issue：跳过 Importer，改用第 5 节 `--mirror` push，通常更快。

---

## 11. 常见问题与排查

| 现象 | 可能原因 | 解决方法 |
|------|----------|----------|
| Import 页没有 GitHub 图标 | 自建未开 Import sources | Admin 开启并保存；`reconfigure`（若改了 rb） |
| 一直 Pending / 失败 | Sidekiq 未跑、队列堆积、磁盘满 | `gitlab-ctl status`；看 Sidekiq 日志；加磁盘与 worker |
| Partially completed | 单类 relation 失败（附件、某条 MR） | Import 详情 View details；必要时对失败项 API 补齐或重导到新项目名 |
| GHES 无法用 UI | UI 只认 github.com | 改用 Import API 并指定 GHES 主机 |
| 作者全是自己 | 用户映射失败 | 统一邮箱；或接受占位/事后改；迁前先建用户 |
| `git push` 拒绝 | 目标非空（有 README） | 空项目重建，或先协调 histories |
| LFS 缺对象 | 未推 LFS 或 Token 缺 scope | `git lfs push --all`；检查 PAT |
| Direct Transfer 连不上 | 防火墙、证书、Token 权限 | 目标→源网络；用可信证书；换有 Group Owner 权限的 Token |
| restore 失败 | 版本不一致、secrets 不匹配 | 对齐 GitLab 版本；恢复 `gitlab-secrets.json` |
| Registry 镜像没了 | 本就不在 Direct Transfer 范围 | 按第 9 节单独迁镜像 |
| CSV Issue 没标签 | quick action 标签不存在 | 先建 label再导入；或 API 创建时带 `labels` |

日志位置（Omnibus 常见）：

```bash
sudo gitlab-ctl tail
# 或查看
# /var/log/gitlab/gitlab-rails/importer.log
# /var/log/gitlab/sidekiq/current
```

---

## 12. 注意事项与最佳实践

1. **先选场景再动手**：备份恢复 ≠ 项目导入 ≠ 纯 Git push。  
2. **敏感配置默认不会跟着来**：CI 变量、Webhook 密钥、Deploy token 必须重建。  
3. **先小后大**：用小项目试 Importer / Direct Transfer，再迁巨型单体。  
4. **冻结窗口**：大迁移期间源仓库只读，避免迁完又丢提交。  
5. **许可证座位**：导入 collaborators 可能占用 Seat，并给予高权限。  
6. **版本与文档**：Direct Transfer 的「迁了什么」以**目标版本**官方清单为准。  
7. **菜单文案**：16/17 代路径仅供导航；以实例 UI 与 [现行文档](https://docs.gitlab.com/) 为准。  
8. **合规**：导出包与备份含代码与评论，按公司数据分级存放与加密。  
9. **不要用生产做实验**：mirror、`--mirror` push、全员 Rake 加组等破坏性操作先在测试实例验证。  
10. **迁完改 DNS/文档/CI 模板**：避免团队仍向旧远端推送。

---

## 13. 命令与入口速查

| 目标 | 入口 / 命令 |
|------|-------------|
| 平台项目导入 | `+` → New project → **Import project** |
| Direct Transfer | 目标实例 Group 迁移 / Import history（GitLab→GitLab） |
| 纯 Git | `git push --all` / `--mirror`；或 Repository by URL |
| Issue CSV | Issues → **Actions → Import CSV** |
| 建用户 | `POST /api/v4/users` 或 LDAP/SSO |
| 加成员 | `POST /api/v4/groups/:id/members` |
| 整站备份 | `sudo gitlab-backup create` |
| 整站恢复 | `sudo gitlab-backup restore BACKUP=...`（同版本） |
| 开导入源 | Admin → Settings → General → Import sources |

---

## 14. 总结与下一步

「GitLab 导入数据」应拆成六条路径理解：**平台迁项目、纯 Git、Issue CSV/API、用户供给、整站 backup、Registry/LFS/包**。日常把外部托管搬进 GitLab，优先 **Import project** 或 **Direct Transfer**；只要代码就用 **git push**；账号走 **SSO/API**；灾备才用 **gitlab-backup**。

**建议下一步**：

1. 写下你的源类型（GitHub / 另一 GitLab / 仅 Git）与必须保留的数据清单  
2. 在自建实例核对 Import sources 与磁盘/Sidekiq  
3. 用一个非关键项目做端到端演练，并列出「重建 CI 变量」清单  
4. 需要官方细节时，对照：  
   - [Import and migrate](https://docs.gitlab.com/user/project/import/)  
   - [Direct transfer migrated items](https://docs.gitlab.com/user/group/import/migrated_items/)  
   - [GitHub importer](https://docs.gitlab.com/user/project/import/github/)  
   - [Issues CSV import](https://docs.gitlab.com/user/project/issues/csv_import/)  
   - [Backup and restore](https://docs.gitlab.com/administration/backup_restore/)（自建）

若你提供源平台、目标版本（CE/EE/com）和「必须保留的数据」，可以据此缩成一份更短的「只含你场景」的操作 runbook。
