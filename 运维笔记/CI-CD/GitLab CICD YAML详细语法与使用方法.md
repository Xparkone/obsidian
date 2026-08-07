# GitLab CI/CD YAML 详细语法与使用方法

> 本文是一份独立的 GitLab CI/CD 配置手册，面向第一次编写 `.gitlab-ci.yml` 的开发者，也可作为日常速查资料。示例以当前 GitLab 官方在线文档为依据核对（核对日期：2026-07-23）。  
> GitLab.com 会持续升级；Self-Managed 实例可能停留在较旧版本。凡涉及较新、实验性、Beta、Runner 版本或付费层级的功能，使用前都应对照实例对应版本的官方文档与 CI Lint。

## 目录

- [1. 先理解流水线模型](#1-先理解流水线模型)
- [2. 最小可运行配置](#2-最小可运行配置)
- [3. YAML 基础与常见陷阱](#3-yaml-基础与常见陷阱)
- [4. 配置解析、执行顺序与作用域](#4-配置解析执行顺序与作用域)
- [5. 全局关键字](#5-全局关键字)
- [6. Job 基础与脚本](#6-job-基础与脚本)
- [7. 镜像与服务容器](#7-镜像与服务容器)
- [8. 变量、敏感变量与预定义变量](#8-变量敏感变量与预定义变量)
- [9. rules：决定 Job 是否加入流水线](#9-rules决定-job-是否加入流水线)
- [10. workflow:rules：决定是否创建流水线](#10-workflowrules决定是否创建流水线)
- [11. Job 编排：stage、needs 与 dependencies](#11-job-编排stageneeds-与-dependencies)
- [12. artifacts：在 Job 间传递构建结果](#12-artifacts在-job-间传递构建结果)
- [13. cache：复用依赖下载](#13-cache复用依赖下载)
- [14. environment 与部署](#14-environment-与部署)
- [15. 并发、互斥与执行控制](#15-并发互斥与执行控制)
- [16. 配置复用：default、inherit、extends 与引用](#16-配置复用defaultinheritextends-与引用)
- [17. include：拆分和复用配置文件](#17-include拆分和复用配置文件)
- [18. 下游、父子与多项目流水线](#18-下游父子与多项目流水线)
- [19. release 与 Pages](#19-release-与-pages)
- [20. OIDC、id_tokens 与外部身份认证](#20-oidcid_tokens-与外部身份认证)
- [21. 完整实践一：Node.js 测试、构建与部署](#21-完整实践一nodejs-测试构建与部署)
- [22. 完整实践二：Docker 镜像构建](#22-完整实践二docker-镜像构建)
- [23. 完整实践三：模板与子流水线](#23-完整实践三模板与子流水线)
- [24. 配置校验与调试](#24-配置校验与调试)
- [25. 常见报错与排查](#25-常见报错与排查)
- [26. 最佳实践](#26-最佳实践)
- [27. 关键词速查索引](#27-关键词速查索引)
- [28. 官方参考资料](#28-官方参考资料)

---

## 1. 先理解流水线模型

GitLab CI/CD 使用仓库中的 `.gitlab-ci.yml` 描述自动化流程。一次代码推送、合并请求、标签、定时任务或 API 调用，可能创建一条 **pipeline（流水线）**；流水线由多个 **job（作业）** 组成，job 由 GitLab Runner 执行。

```text
事件（push / merge request / tag / schedule / API）
  ↓
workflow:rules：是否创建流水线
  ↓
解析并合并 include
  ↓
每个 job 的 rules：是否把 job 加入流水线
  ↓
按 stages 或 needs 形成执行图
  ↓
Runner 准备环境并执行 before_script → script → after_script
  ↓
上传 artifacts/cache，记录 environment/deployment/release
```

三个最重要的区分：

1. `workflow:rules` 控制**整条流水线是否存在**。
2. job 的 `rules` 控制**该 job 是否加入已经创建的流水线**。
3. `stages` 给出默认阶段顺序，`needs` 可以建立更精确的有向依赖图并提前执行 job。

---

## 2. 最小可运行配置

在仓库根目录创建 `.gitlab-ci.yml`：

```yaml
hello:
  script:
    - echo "Hello from GitLab CI"
```

这已经是一份有效配置：

- `hello` 是 job 名称。
- 未写 `stage` 时，job 默认属于 `test` 阶段。
- `script` 是 Runner 执行的命令；退出码非零通常表示 job 失败。
- 项目还必须有可接单的 Runner，否则 job 会停留在 `pending`。

稍完整的三阶段配置：

```yaml
stages:
  - test
  - build
  - deploy

unit-test:
  stage: test
  script:
    - npm ci
    - npm test

build-app:
  stage: build
  script:
    - npm run build

deploy-staging:
  stage: deploy
  script:
    - ./scripts/deploy.sh staging
```

默认行为是：

- 同一 stage 的 job 可以并行。
- 后一 stage 要等待前一 stage 的所有非允许失败 job 成功。
- 不同 job 的工作目录彼此隔离，不能假设上一个 job 生成的文件仍在；需要使用 `artifacts`。

---

## 3. YAML 基础与常见陷阱

### 3.1 缩进、映射与数组

YAML 使用空格表达层级，建议统一两个空格，禁止使用 Tab。

```yaml
job-name:                 # 映射键
  image: node:22-alpine   # 标量
  script:                 # 数组
    - npm ci
    - npm test
```

也可用行内数组，但长配置不易读：

```yaml
tags: [docker, linux]
```

### 3.2 字符串应在这些场景加引号

YAML 解析器可能把 `true`、`false`、`null`、数字、日期等识别成非字符串。GitLab 的变量值最终通常以字符串提供给 job，但解析阶段先受 YAML 类型影响。

```yaml
variables:
  ENABLE_FEATURE: "true"
  PORT: "8080"
  VERSION: "1.0"
  RELEASE_DATE: "2026-07-23"
  EMPTY_VALUE: ""
```

包含冒号后跟空格、`#`、`{}`、`[]` 或表达式的命令也适合加引号：

```yaml
script:
  - 'curl --header "Content-Type: application/json" "$API_URL"'
  - 'echo "value: $VALUE"'
```

陷阱：下面一行可能被 YAML 当作键值映射，而不是命令字符串。

```yaml
script:
  - curl --header Content-Type: application/json https://example.com
```

### 3.3 多行脚本

字面量块 `|` 保留换行，适合多个命令；折叠块 `>` 会折叠换行，适合一条很长的命令。

```yaml
job:
  script:
    - |
      set -eu
      echo "第一条命令"
      ./build.sh
    - >
      curl --fail --show-error
      --header "Authorization: Bearer $TOKEN"
      "$API_URL"
```

注意：

- `|` 块在 Runner 中通常作为一个 script 项执行。应自行使用 `set -e`/`set -eu`，不要依赖不同 shell 的隐式错误处理细节。
- Shell 语法取决于 Runner executor 和镜像。Linux 常见为 `sh`/`bash`，Windows 可能是 PowerShell。

### 3.4 注释与特殊字符

```yaml
job:
  script:
    - echo "这不是 # 注释"
    - echo hello # 从这里开始是 YAML 注释
```

### 3.5 变量引用不是模板语言

在 `script` 中，`$NAME` 或 `${NAME}` 由执行 shell 展开：

```yaml
script:
  - echo "$CI_COMMIT_SHA"
  - echo "${CI_PROJECT_PATH}"
```

在 `rules:if` 中则由 GitLab 表达式求值器解析，不要写成 shell 的 `[ ... ]`：

```yaml
rules:
  - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

并非所有关键字都支持变量展开，且展开时机不同。尤其是 `include` 在 job 之前解析，不能使用 job 内变量，也不能依赖顶层 `variables` 中刚定义的值来定位 include。

### 3.6 布尔值与空值陷阱

```yaml
variables:
  FLAG: "false" # 字符串 false；在 shell 中 [ "$FLAG" ] 仍为真
```

正确判断：

```yaml
script:
  - |
      if [ "$FLAG" = "true" ]; then
        echo "enabled"
      fi
```

清除继承配置时，`{}` 与 `null` 含义可能不同。例如使用 `extends`：

```yaml
.base:
  variables:
    A: "1"

keep-variables:
  extends: .base
  variables: {}   # 仍保留继承的 A

remove-variables:
  extends: .base
  variables: null # 删除 variables
```

---

## 4. 配置解析、执行顺序与作用域

理解时机可以避免很多“变量明明存在却不能用”的问题。

### 4.1 配置阶段

大致过程如下：

1. GitLab 读取主配置和 `include`。
2. 合并所有配置，解析 YAML anchor、`extends`、`!reference` 等复用关系。
3. 计算 `workflow:rules`，决定是否创建流水线。
4. 计算 job 的 `rules`，生成流水线图。
5. job 被 Runner 接收后，才进入 shell 执行阶段。

### 4.2 变量可用阶段

GitLab 官方将预定义变量按可用时机分为：

- **Pre-pipeline**：创建流水线前可用，可用于 `include:rules` 和 `workflow:rules`，例如部分 `CI_PROJECT_*`、`CI_COMMIT_REF_NAME`。
- **Pipeline**：创建流水线时可用，可用于 job `rules`；job-only 变量不在此阶段可用。
- **Job-only**：Runner 开始 job 后才有，只能在脚本中使用，不能决定 pipeline/job 是否被创建。

不要在 `rules` 中依赖 `dotenv` 报告生成的变量；规则计算早于任何 job 执行。

### 4.3 Job 脚本阶段

通常执行顺序：

```text
准备 executor / 拉取镜像
→ 获取代码
→ 恢复 cache
→ 下载 artifacts
→ before_script
→ script
→ after_script
→ 上传 cache/artifacts
```

精确顺序、失败处理和超时行为会受 GitLab Runner 版本、executor 和配置影响。`after_script` 在独立 shell 上下文中执行，不能依赖前一 shell 中的 `cd`、alias 或临时环境变量。

---

## 5. 全局关键字

当前配置中常见的全局关键字包括：

- `stages`
- `workflow`
- `include`
- `default`
- 顶层 `variables`
- `spec`（用于带输入参数的 CI/CD 配置组件/包含文件，版本支持需核对）

不建议再把 `image`、`services`、`cache`、`before_script`、`after_script` 直接作为旧式顶层默认值；官方文档已将这类写法标记为 deprecated。新配置应放进 `default`。

```yaml
default:
  image: node:22-alpine
  before_script:
    - node --version
  retry: 1

variables:
  NODE_ENV: test

stages: [lint, test, build]
```

---

## 6. Job 基础与脚本

### 6.1 Job 名称与隐藏 Job

普通 job 名称可自定义：

```yaml
unit-test:
  script:
    - npm test
```

以点开头的 job 是隐藏 job，不会直接执行，常用作模板：

```yaml
.node-template:
  image: node:22-alpine
  before_script:
    - npm ci

test:
  extends: .node-template
  script:
    - npm test
```

避免使用 GitLab 保留的顶层关键字作为 job 名。名称可以包含空格，但会增加引用和命令行操作的麻烦，推荐使用小写短横线。

### 6.2 `script`

**用途**：定义 job 的主要命令。  
**时机**：`before_script` 之后、`after_script` 之前。  
**行为**：数组项按顺序执行，失败通常终止主要脚本并使 job 失败。

```yaml
test:
  script:
    - npm ci
    - npm run lint
    - npm test
```

常见陷阱：

- 命令退出码被管道吞掉；需要 shell 支持时启用 `pipefail`。
- 在 `script` 中后台启动的服务可能在 job 结束时被终止；数据库等依赖优先用 `services`。
- 不要回显 token、密码或完整环境变量列表。

### 6.3 `before_script`

**用途**：在主脚本前做初始化。  
**推荐位置**：公共值放在 `default:before_script`，job 可覆盖。

```yaml
default:
  before_script:
    - echo "Pipeline $CI_PIPELINE_ID"

test:
  before_script:
    - npm ci # 覆盖默认数组，不是追加
  script:
    - npm test
```

陷阱：数组通常不会自动拼接。job 定义自己的 `before_script` 后，默认数组会被覆盖；需要组合时使用 anchor 或 `!reference`。

### 6.4 `after_script`

**用途**：清理、汇总日志、生成后处理文件。  
**行为**：即使主脚本失败，通常也会执行；也可以在取消场景执行，但具体行为与 Runner/GitLab 版本有关。

```yaml
test:
  script:
    - npm test
  after_script:
    - rm -f temporary-credentials.json
    - echo "job finished"
```

关键陷阱：

- `after_script` 在新的 shell 上下文运行，之前执行的 `cd` 和 `export TEMP=x` 不保留。
- 它有独立超时控制；Runner 较新版本可通过 Runner 变量配置。
- 在 `after_script` 中生成或修改、且位于 artifacts 路径内的文件，可随 artifacts 上传。
- job 被取消后，`CI_JOB_TOKEN` 可能立即失效，不适合在清理阶段继续调用需要该 token 的 API。

---

## 7. 镜像与服务容器

### 7.1 `image`

**用途**：指定 Docker/Kubernetes executor 中 job 的主容器镜像。Shell executor 不会因此自动进入容器。

```yaml
test:
  image: node:22-alpine
  script:
    - node --version
    - npm test
```

完整形式：

```yaml
test:
  image:
    name: registry.example.com/team/node-ci:22
    entrypoint: [""]
    pull_policy: if-not-present
  script:
    - npm test
```

注意：

- `pull_policy` 依赖支持它的 GitLab Runner 版本和 Runner 配置。
- 固定镜像 digest 可获得更强的可复现性：`image: alpine@sha256:...`。
- 私有 Registry 认证可使用 `DOCKER_AUTH_CONFIG`，但它属于敏感变量。
- 不要把语言镜像版本只写成 `latest`。

### 7.2 `services`

**用途**：为 job 启动数据库、缓存、Docker daemon 等旁路容器。

```yaml
integration-test:
  image: node:22-alpine
  services:
    - name: postgres:17-alpine
      alias: db
  variables:
    POSTGRES_DB: app_test
    POSTGRES_USER: app
    POSTGRES_PASSWORD: test-only-password
    DATABASE_URL: "postgres://app:test-only-password@db:5432/app_test"
  script:
    - npm ci
    - npm run test:integration
```

服务完整形式可包含 `name`、`alias`、`entrypoint`、`command`、`variables` 等；支持范围需要与 Runner 版本核对。

常见陷阱：

- 服务主机名应使用 `alias`，不要默认使用 `localhost`。主容器与 service 是不同容器。
- `services` 不会自动等待数据库“可接受连接”；脚本需执行健康检查或重试。
- service 变量不要误认为会覆盖所有 job 变量，具体优先级应按变量作用域核对。
- Docker-in-Docker 需要 Runner 允许相应能力，常涉及 privileged 模式，安全风险高。

---

## 8. 变量、敏感变量与预定义变量

### 8.1 `variables`

顶层变量为所有 job 提供默认值；job 变量覆盖同名值。

```yaml
variables:
  NODE_ENV: test
  APP_NAME: demo

build:
  variables:
    NODE_ENV: production
  script:
    - echo "$APP_NAME / $NODE_ENV"
```

可使用详细形式控制展开：

```yaml
variables:
  LITERAL_DOLLAR:
    value: '$DO_NOT_EXPAND'
    expand: false
```

该形式及 UI 中变量展开的默认行为曾随 GitLab 版本调整，旧版实例应查对应版本文档。

### 8.2 变量来源与优先级

变量可来自：

- pipeline execution policy / scan execution policy；
- API、trigger、schedule、手动运行时传入的 pipeline variables；
- 项目、组、实例 CI/CD 变量；
- `.gitlab-ci.yml` job 变量和顶层默认变量；
- dotenv 报告；
- deployment 变量；
- 预定义变量。

GitLab 的完整优先级规则会随功能演进，尤其策略变量与 pipeline inputs。出现覆盖问题时，不要凭记忆判断，应查当前版本的 [CI/CD variable precedence](https://docs.gitlab.com/ci/variables/#ci-cd-variable-precedence)。

### 8.3 安全变量

密码、token、私钥不得硬编码进 YAML，应在项目或组的 **Settings → CI/CD → Variables** 中配置：

- **Masked**：日志中尝试隐藏值；值必须满足 GitLab 的格式要求。
- **Hidden**：创建后 UI 不再显示值；是较新版本能力，旧版需核对。
- **Protected**：仅向受保护分支/标签的流水线暴露。
- **Environment scope**：只对匹配环境名的部署 job 生效；部分层级/能力可能与订阅有关。
- **File type**：环境变量的值是临时文件路径，实际秘密写在文件中，适合证书和 kubeconfig。

```yaml
deploy:
  script:
    - kubectl --kubeconfig "$KUBECONFIG_FILE" apply -f k8s/
```

安全注意：

1. Masked 不是万能防泄漏。编码、分段打印、上传 artifact、恶意依赖都可能绕过隐藏。
2. Fork 的合并请求默认不应获得上游项目受保护秘密；运行 MR pipeline 前先审查代码。
3. 避免 `set -x`、`printenv`、`env`。
4. 对生产变量同时设置 Protected，并配合 protected environment 与审批。
5. 优先使用短期 OIDC `id_tokens`，减少长期云密钥。

### 8.4 常用预定义变量

以下是常用而非完整列表：

| 变量 | 含义与注意点 |
|---|---|
| `CI` | 在 CI 中为 `"true"` |
| `CI_PROJECT_ID` | 项目 ID |
| `CI_PROJECT_PATH` | `group/project` |
| `CI_PROJECT_DIR` | Runner 上仓库工作目录，job-only |
| `CI_PIPELINE_ID` | 实例范围内的 pipeline ID |
| `CI_PIPELINE_IID` | 项目范围内的 pipeline IID |
| `CI_PIPELINE_SOURCE` | `push`、`merge_request_event`、`schedule`、`web`、`api`、`trigger`、`pipeline`、`parent_pipeline` 等 |
| `CI_COMMIT_SHA` | 当前提交完整 SHA |
| `CI_COMMIT_SHORT_SHA` | 短 SHA |
| `CI_COMMIT_BRANCH` | 分支 pipeline 中存在；MR/tag pipeline 中不可假定存在 |
| `CI_COMMIT_TAG` | tag pipeline 中存在 |
| `CI_COMMIT_REF_NAME` | 分支或标签名 |
| `CI_COMMIT_REF_SLUG` | 适合作为 DNS/镜像标签一部分的 slug |
| `CI_DEFAULT_BRANCH` | 默认分支名 |
| `CI_COMMIT_REF_PROTECTED` | ref 是否受保护，值是字符串 `"true"`/`"false"` |
| `CI_MERGE_REQUEST_IID` | MR pipeline 中的 MR IID |
| `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME` | MR 源分支 |
| `CI_MERGE_REQUEST_TARGET_BRANCH_NAME` | MR 目标分支 |
| `CI_REGISTRY` | GitLab Container Registry 地址 |
| `CI_REGISTRY_IMAGE` | 当前项目 Registry 镜像前缀 |
| `CI_REGISTRY_USER` / `CI_REGISTRY_PASSWORD` | job 中登录项目 Registry 的临时凭据 |
| `CI_JOB_ID` | 当前 job ID |
| `CI_JOB_TOKEN` | 当前 job 的短期 token，权限受 allowlist 与实例设置约束 |
| `CI_ENVIRONMENT_NAME` | job 声明 environment 后可用 |
| `CI_ENVIRONMENT_SLUG` | 环境 slug |

陷阱：

- MR pipeline 中 `CI_COMMIT_BRANCH` 不可用；用 MR 专属变量。
- `CI_PIPELINE_SOURCE == "push"` 同时可能是分支 push 和 tag push，再结合 `CI_COMMIT_TAG` 区分。
- 预定义变量集合和可用阶段不断演进，完整表见官方链接。
- 不要覆盖预定义变量，除非完全了解后果。

---

## 9. `rules`：决定 Job 是否加入流水线

### 9.1 基本行为

`rules` 是从上到下计算的规则数组，**第一条匹配规则生效，后续不再检查**。如果没有规则匹配，job 不加入流水线。

```yaml
test:
  script:
    - npm test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

每条规则可以组合 `if`、`changes`、`exists`；同一条中的条件都要满足。

### 9.2 `rules:if`

支持变量存在性、字符串比较、正则匹配和逻辑组合：

```yaml
deploy-preview:
  script:
    - ./deploy-preview.sh
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_LABELS =~ /(^|,)preview(,|$)/'
```

常见表达式：

```yaml
rules:
  - if: '$CI_COMMIT_TAG'                                  # 变量存在且非空
  - if: '$CI_COMMIT_BRANCH == "main"'                     # 字符串相等
  - if: '$CI_COMMIT_BRANCH != $CI_DEFAULT_BRANCH'
  - if: '$CI_COMMIT_BRANCH =~ /^release\/\d+\.\d+$/'      # 正则匹配
  - if: '$CI_COMMIT_BRANCH !~ /^docs\//'
  - if: '($CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH || $CI_COMMIT_TAG) && $DEPLOY_ENABLED == "true"'
```

表达式陷阱：

- 左侧应是变量；正则使用 GitLab 支持的 RE2 语法，不支持需要回溯等 RE2 不具备的能力。
- 正则字面量使用 `/.../`，不要把普通字符串误当正则。
- 比较空值可用 `null`，比较空字符串用 `""`；语义不要混用。
- 逻辑优先级不直观时使用括号。
- 表达式不是 shell，不能调用命令，也不能使用 `$(...)`。
- 变量内容被用作正则时有额外解析规则，使用前以当前版本文档和 CI Lint 验证。

### 9.3 `rules:changes`

**用途**：仅当指定路径发生变化时加入 job。

```yaml
frontend-test:
  script:
    - npm test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes:
        - frontend/**/*
        - package.json
        - package-lock.json
```

指定比较基准：

```yaml
docs-check:
  script:
    - ./check-docs.sh
  rules:
    - changes:
        paths:
          - docs/**/*
        compare_to: 'refs/heads/main'
```

陷阱：

- 没有 push diff 的 pipeline（如某些 schedule、手动或首次分支）中，`changes` 的结果可能与你直觉不同；需要明确 `compare_to` 或先限制 `CI_PIPELINE_SOURCE`。
- glob 语法和检查数量有上限；超大 monorepo 应核对当前版本限制。
- 变量在 `changes` 路径及 `compare_to` 中的支持经历过版本演进，旧实例需验证。

### 9.4 `rules:exists`

**用途**：当仓库中存在某些路径时加入 job，适合 monorepo 技术栈探测。

```yaml
node-test:
  image: node:22-alpine
  script:
    - npm ci
    - npm test
  rules:
    - exists:
        - package.json
```

可以使用 `paths`；较新版本还支持指定 `project` 和 `ref` 的形式。该高级形式存在版本差异，Self-Managed 使用前必须查对应版本。

```yaml
rules:
  - exists:
      paths:
        - templates/service.yml
      project: platform/ci-templates
      ref: v3
```

### 9.5 `when`

常用值：

- `on_success`：默认值，前置依赖成功后执行。
- `on_failure`：前面阶段失败时执行。
- `always`：无论前面状态如何都执行。
- `manual`：生成手动作业。
- `delayed`：延迟执行，需要 `start_in`。
- `never`：不加入/不执行。

```yaml
deploy-production:
  script:
    - ./deploy.sh production
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual
    - when: never
```

延迟执行：

```yaml
deploy-canary:
  script:
    - ./deploy.sh canary
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: delayed
      start_in: 30 minutes
```

注意：`start_in` 与 `when: delayed` 应位于一致、合法的层级。与 `rules` 配合时放在命中的规则中。

### 9.6 `allow_failure`

job 级：

```yaml
lint:
  script:
    - npm run lint
  allow_failure: true
```

规则级：

```yaml
compatibility-test:
  script:
    - npm run test:legacy
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      allow_failure: false
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      allow_failure: true
```

按退出码允许失败：

```yaml
scan:
  script:
    - ./scanner
  allow_failure:
    exit_codes:
      - 137
      - 255
```

重要差异：手动 job 的默认 `allow_failure` 行为会因它是直接写 `when: manual`，还是写在 `rules` 中而不同。为了避免升级或重构后行为变化，生产部署应显式写：

```yaml
rules:
  - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    when: manual
    allow_failure: false
```

### 9.7 避免重复流水线

job 最后一条宽泛的 `when: always` 可能让 push pipeline 和 MR pipeline 同时出现。应使用 `workflow:rules` 从流水线层面限制来源。

### 9.8 `only` / `except`

`only` 和 `except` 是历史语法。官方不建议新配置继续使用，应优先 `rules`。不要在同一流水线中无计划地混用 `rules` job 与 `only/except` job，因为它们的默认行为不同，容易产生重复或缺失 job。

旧写法：

```yaml
test:
  script: npm test
  only:
    - branches
```

推荐：

```yaml
test:
  script:
    - npm test
  rules:
    - if: '$CI_COMMIT_BRANCH'
```

---

## 10. `workflow:rules`：决定是否创建流水线

`workflow` 在 job 之前计算。即使某 job 的规则允许执行，如果 `workflow` 阻止了 pipeline，该 job 也不存在。

### 10.1 只创建 MR、tag 和默认分支流水线

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_TAG'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - when: never
```

### 10.2 分支有 MR 后切换为 MR pipeline

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS && $CI_PIPELINE_SOURCE == "push"'
      when: never
    - if: '$CI_COMMIT_BRANCH'
```

显式限制 `push` 很重要，否则可能误伤 `trigger` 或下游 `pipeline` 来源。

### 10.3 跳过 Draft MR

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_DRAFT == "true"'
      when: never
    - when: always
```

`CI_MERGE_REQUEST_DRAFT` 在 GitLab 17.10 引入。更早版本需基于 `CI_MERGE_REQUEST_TITLE` 正则判断，并接受标题格式差异。

### 10.4 流水线级变量

规则可设置默认变量，并会影响其中 job；向下游传递时还可能覆盖下游同名变量，因此命名要加前缀。

```yaml
workflow:
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      variables:
        DEPLOY_CHANNEL: production
    - variables:
        DEPLOY_CHANNEL: preview
```

---

## 11. Job 编排：`stage`、`needs` 与 `dependencies`

### 11.1 `stages` 与 `stage`

```yaml
stages:
  - lint
  - test
  - build
  - deploy

lint:
  stage: lint
  script: ["npm run lint"]

test:
  stage: test
  script: ["npm test"]
```

未在 `stages` 中列出的自定义 stage 会导致配置错误。GitLab 还存在 `.pre` 和 `.post` 特殊阶段；如果流水线只有 `.pre`/`.post` job，可能不会创建有效流水线，应至少有普通阶段 job。

### 11.2 `needs`

**用途**：建立 job 级依赖，使 job 不必等待整个前置 stage 完成，形成 DAG（有向无环图）。

```yaml
stages: [build, test, deploy]

build-api:
  stage: build
  script:
    - ./build-api.sh

build-web:
  stage: build
  script:
    - ./build-web.sh

test-api:
  stage: test
  needs:
    - job: build-api
      artifacts: true
  script:
    - ./test-api.sh
```

`test-api` 只等待 `build-api`，无需等待 `build-web`。

无需依赖、流水线创建后尽快运行：

```yaml
lint:
  stage: test
  needs: []
  script:
    - npm run lint
```

可选依赖：

```yaml
deploy:
  needs:
    - job: security-scan
      optional: true
  script:
    - ./deploy.sh
```

当 `security-scan` 因规则未加入流水线时，`optional: true` 避免 pipeline 创建失败。

跨项目或跨 pipeline 获取 artifacts 可使用 `needs:project`、`needs:pipeline:job` 等高级形式；它们有层级、权限、并发一致性和版本限制，使用前核对当前官方文档。

常见陷阱：

- `needs` 引用一个可能被 `rules` 排除的 job，却未设置 `optional: true`。
- DAG 必须无环。
- 使用 `needs` 后，job 默认只下载其 `needs` 指定 job 的 artifacts。
- 不要在同一 job 中把 `needs` 与传统 `dependencies` 混用，官方明确不建议。
- `needs` 数量存在实例级/版本限制。

### 11.3 `dependencies`

**用途**：在传统 stage 顺序中，指定从哪些前置 job 下载 artifacts。它不改变执行顺序。

```yaml
package:
  stage: build
  script:
    - mkdir -p dist
    - echo app > dist/app.txt
  artifacts:
    paths:
      - dist/

deploy:
  stage: deploy
  dependencies:
    - package
  script:
    - cat dist/app.txt
```

禁止下载任何前置 artifacts：

```yaml
lint:
  dependencies: []
  script:
    - npm run lint
```

新 DAG 配置通常优先使用 `needs`，并通过 `needs:artifacts` 控制下载。

---

## 12. `artifacts`：在 Job 间传递构建结果

### 12.1 基本用法

**用途**：保存 job 产生的文件，供后续 job、用户下载或 GitLab 报告功能使用。

```yaml
build:
  script:
    - npm ci
    - npm run build
  artifacts:
    name: "web-$CI_COMMIT_REF_SLUG-$CI_COMMIT_SHORT_SHA"
    paths:
      - dist/
    expire_in: 7 days
```

### 12.2 上传时机

```yaml
test:
  script:
    - npm test -- --reporter=junit
  artifacts:
    when: always
    paths:
      - test-results/
    reports:
      junit: test-results/junit.xml
    expire_in: 14 days
```

`when` 常用值：

- `on_success`：默认，成功时上传。
- `on_failure`：失败时上传。
- `always`：无论成功失败都尝试上传。

### 12.3 路径、排除与未跟踪文件

```yaml
artifacts:
  paths:
    - build/
  exclude:
    - build/**/*.map
  untracked: false
```

路径相对 `$CI_PROJECT_DIR`。不要试图上传工作目录之外的路径。

### 12.4 `artifacts:reports`

GitLab 可识别特定报告，例如：

- `junit`
- `coverage_report`
- `dotenv`
- `cobertura`
- `codequality`
- `sast`、`dependency_scanning` 等安全报告

不同报告的 UI 展示、合并方式与订阅层级不同，应查该报告专页。

`dotenv` 示例：

```yaml
prepare:
  script:
    - echo "BUILD_VERSION=1.2.$CI_PIPELINE_IID" > build.env
  artifacts:
    reports:
      dotenv: build.env

package:
  needs:
    - job: prepare
      artifacts: true
  script:
    - echo "Packaging $BUILD_VERSION"
```

不要在 dotenv 中存秘密；报告可被下载，且格式和大小有限制。

### 12.5 Artifacts 常见陷阱

- artifact 不是依赖缓存；它代表构建输出或报告。
- `expire_in` 到期后，后续 pipeline 或手动 job 可能无法下载。
- `needs` 会改变默认下载范围。
- 同名并行 job 的 artifact 下载到同一路径时可能互相覆盖。
- 上传超大目录会拖慢 job；只保留必要内容。
- `artifacts:public`、`access` 等访问控制能力随版本演进，敏感产物应核对实例版本与权限行为。

---

## 13. `cache`：复用依赖下载

### 13.1 Cache 与 artifact 的区别

| 对比 | cache | artifacts |
|---|---|---|
| 目的 | 加速后续 job/pipeline | 传递、保存构建结果 |
| 正确性依赖 | 不应依赖 cache 一定命中 | 可作为 job 的显式输入 |
| 常见内容 | 包管理器下载缓存 | dist、二进制、报告 |
| 保留策略 | 由 Runner/对象存储策略管理 | `expire_in` 等 |

### 13.2 Node.js 缓存示例

```yaml
default:
  image: node:22-alpine
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - .npm/
    policy: pull-push

test:
  script:
    - npm ci --cache .npm --prefer-offline
    - npm test
```

推荐缓存 npm 的下载目录，而不是缓存 `node_modules`；`npm ci` 会按锁文件重建依赖。

### 13.3 Cache key 与 policy

```yaml
cache:
  key: "node-$CI_COMMIT_REF_SLUG"
  paths:
    - .npm/
  policy: pull-push
```

策略：

- `pull-push`：下载并在结束时更新，默认常用。
- `pull`：只读取，适合多个并行消费者，避免争抢写入。
- `push`：只生成缓存。

按锁文件生成 key：

```yaml
cache:
  key:
    files:
      - package-lock.json
    prefix: node
  paths:
    - .npm/
```

可配置 fallback key；具体语法和多缓存上限随 GitLab/Runner 版本演进，旧实例应先 CI Lint。

### 13.4 Cache 常见陷阱

- cache 命中不是契约，脚本必须能在空缓存下成功。
- Runner 若不共享分布式缓存，不同 Runner 之间可能无法命中。
- 过宽 key 会导致不同分支或依赖版本污染；过窄 key 又无法复用。
- 多个 job 同时 `pull-push` 同一 key 可能产生最后写入覆盖。
- 不要缓存秘密、凭据或不可重建的发布文件。

---

## 14. `environment` 与部署

### 14.1 基本环境

```yaml
deploy-staging:
  stage: deploy
  script:
    - ./deploy.sh staging
  environment:
    name: staging
    url: https://staging.example.com
```

GitLab 会记录 deployment，并在 Environments 页面展示。

### 14.2 动态 Review App

```yaml
deploy-review:
  script:
    - ./deploy-review.sh "$CI_COMMIT_REF_SLUG"
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    on_stop: stop-review
    auto_stop_in: 2 days
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

stop-review:
  script:
    - ./stop-review.sh "$CI_COMMIT_REF_SLUG"
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      when: manual
      allow_failure: true
```

`on_stop` 指向停止 job，两个 job 的 environment 名必须匹配。

### 14.3 `action` 与部署层级

常见 `environment:action`：

- `start`：默认，创建部署。
- `stop`：停止环境。
- `prepare`、`verify`、`access`：用于准备、验证、访问等动作；具体 deployment 行为与版本有关。

可声明：

```yaml
environment:
  name: production
  deployment_tier: production
```

### 14.4 手动生产部署

```yaml
deploy-production:
  stage: deploy
  script:
    - ./deploy.sh production
  environment:
    name: production
    url: https://www.example.com
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: manual
      allow_failure: false
```

还应在 GitLab UI 中配置：

- protected environment；
- 允许部署的角色/用户/组；
- deployment approvals（可用层级和规则依订阅与版本而定）；
- 生产变量的 Protected 与 environment scope。

常见陷阱：

- environment 本身不会执行部署，真正部署命令仍在 `script`。
- URL 应来自可信输入，避免把未清洗分支名直接拼入域名。
- 同一环境并发部署可能覆盖，应配合 `resource_group`。

---

## 15. 并发、互斥与执行控制

### 15.1 `resource_group`

**用途**：同一资源组同一时刻只允许一个部署 job，防止并发修改同一环境。

```yaml
deploy-production:
  script:
    - ./deploy.sh production
  environment:
    name: production
  resource_group: production
```

它跨 pipeline 串行化同名资源组。排队模式可通过项目 API 配置；不同模式对旧流水线、顺序和死锁风险有差异。

陷阱：父子流水线配合资源组和 `trigger:strategy` 时可能形成等待环，设计前应阅读官方 resource group 文档。

### 15.2 `parallel`

复制同一 job N 份，并提供 `CI_NODE_INDEX`、`CI_NODE_TOTAL`：

```yaml
test-shards:
  parallel: 4
  script:
    - npm run test:shard -- "$CI_NODE_INDEX/$CI_NODE_TOTAL"
```

### 15.3 `parallel:matrix`

```yaml
integration:
  parallel:
    matrix:
      - NODE_VERSION: ["20", "22", "24"]
        DATABASE: ["postgres", "mysql"]
  image: "node:${NODE_VERSION}-alpine"
  script:
    - ./test-against.sh "$DATABASE"
```

会生成 3 × 2 个 job。矩阵表达式、按矩阵选择 `needs` 等能力在近年持续增强，Self-Managed 旧版本务必核对。

陷阱：

- 组合数量有限制。
- job 名由变量值生成，过长会触发长度限制，使用 `needs` 时限制可能更严格。
- 完全相同的矩阵值会生成重名 job，可能覆盖。
- 并行 job 输出同名 artifacts 时要用变量区分路径/名称。

### 15.4 `retry`

```yaml
flaky-network-job:
  retry:
    max: 2
    when:
      - runner_system_failure
      - stuck_or_timeout_failure
  script:
    - ./download-dependency.sh
```

只重试基础设施类失败，避免把确定的测试失败盲目执行三次。失败原因枚举会随版本增加；GitLab 19.1 对部分 Runner 失败分类有调整，使用新枚举前应确认实例版本。

### 15.5 `timeout`

```yaml
e2e:
  timeout: 45 minutes
  script:
    - npm run test:e2e
```

job timeout 受项目上限和 Runner 上限约束，job 配置不能绕过更低的上限。语法支持自然时长字符串；使用边界值前先 CI Lint。

### 15.6 `interruptible`

```yaml
test:
  interruptible: true
  script:
    - npm test
```

配合项目的 Auto-cancel redundant pipelines，可取消旧 commit 的未完成 job，节约 Runner。

部署 job 通常设为 `false`：

```yaml
deploy-production:
  interruptible: false
  script:
    - ./deploy.sh
```

`workflow:auto_cancel` 和 `rules:interruptible` 等更细控制属于较新能力，旧版本需核对。

### 15.7 `tags`

```yaml
build-arm:
  tags:
    - docker
    - arm64
  script:
    - ./build.sh
```

Runner 必须同时满足 job 的所有 tags。job 长期 `pending` 时，先确认：

- Runner 在线且未暂停；
- tag 完全匹配（区分拼写）；
- Runner 是否允许无 tag job；
- protected Runner 是否允许该 ref；
- Runner 是否锁定到其他项目。

---

## 16. 配置复用：`default`、`inherit`、`extends` 与引用

### 16.1 `default`

**用途**：给所有 job 提供默认配置。

```yaml
default:
  image: alpine:3.22
  retry: 1
  interruptible: true
  before_script:
    - echo "Starting $CI_JOB_NAME"
```

job 同名关键字通常整体覆盖默认值，不是逐项追加。并非所有 job 关键字都能出现在 `default`；支持列表以当前 YAML reference 为准。

### 16.2 `inherit`

控制 job 是否继承全局 defaults 和 variables：

```yaml
isolated:
  inherit:
    default: false
    variables: false
  image: alpine:3.22
  script:
    - echo "minimal environment"
```

只继承部分：

```yaml
job:
  inherit:
    default:
      - image
      - retry
    variables:
      - SAFE_GLOBAL
  script:
    - ./run.sh
```

### 16.3 `extends`

**用途**：继承隐藏模板或其他 job，可跨 include 使用。

```yaml
.node:
  image: node:22-alpine
  cache:
    key:
      files: [package-lock.json]
    paths: [.npm/]
  before_script:
    - npm ci --cache .npm --prefer-offline

test:
  extends: .node
  script:
    - npm test
```

可继承多个模板：

```yaml
test:
  extends:
    - .node
    - .merge-request-rules
  script:
    - npm test
```

合并规则：

- 哈希执行反向深合并。
- 数组不会自动拼接，后定义值通常覆盖。
- 最多支持 11 层继承，但官方建议避免超过 3 层，保持可读。

### 16.4 YAML anchors、aliases 与 map merge

同一 YAML 文件内：

```yaml
.job-template: &job-template
  image: node:22-alpine
  tags:
    - docker

test:
  <<: *job-template
  script:
    - npm test
```

anchor 只能在定义它的同一个 YAML 文件内使用，不能跨 `include` 文件。

脚本数组复用：

```yaml
.setup: &setup
  - npm ci
  - npm run generate

test:
  before_script:
    - *setup
  script:
    - npm test
```

GitLab 支持在 `script`、`before_script`、`after_script` 中使用 anchor；旧 GitLab 版本的支持范围可能不同。

### 16.5 `!reference`

GitLab 特有标签，可跨 include 选择某个关键字：

```yaml
.common:
  before_script:
    - npm ci
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

test:
  before_script:
    - !reference [.common, before_script]
  rules:
    - !reference [.common, rules]
  script:
    - npm test
```

选择单个变量：

```yaml
.vars:
  variables:
    API_URL: https://api.example.com

job:
  variables:
    TARGET_URL: !reference [.vars, variables, API_URL]
  script:
    - echo "$TARGET_URL"
```

注意：

- `!reference` 在 inputs 插值前处理，不能在引用标签中使用 CI/CD inputs。
- 脚本类关键字可有限层级嵌套引用；当前官方文档写明最多 10 层。
- 编辑器可能不识别自定义 YAML tag，不代表 GitLab 一定无效；以 CI Lint 为准。
- 与 `parallel:matrix` 的组合历史上存在已知问题，使用前查当前版本状态。

---

## 17. `include`：拆分和复用配置文件

### 17.1 本地文件

```yaml
include:
  - local: /.gitlab/ci/test.yml
  - local: /.gitlab/ci/deploy.yml
```

`local` 路径相对仓库根目录，必须位于同一仓库同一 ref。可使用受支持的 `*`、`**` glob。

### 17.2 其他项目

```yaml
include:
  - project: platform/ci-templates
    ref: v3.2.1
    file:
      - /templates/node.yml
      - /templates/security.yml
```

生产模板应固定到受保护 tag 或完整 commit SHA，避免跟随 `main` 发生供应链漂移。触发 pipeline 的用户必须有权限访问被 include 的私有项目。

### 17.3 远程 URL 与官方模板

```yaml
include:
  - remote: https://example.com/ci/common.yml
  - template: Jobs/Code-Quality.gitlab-ci.yml
```

`remote` 获取外部内容存在供应链风险；应使用 HTTPS，并在支持的版本中考虑 `integrity` 校验。官方模板名称、弃用和订阅能力会变化，必须查实例对应版本。

### 17.4 CI/CD Components

```yaml
include:
  - component: gitlab.com/example/components/node-test@1.2.0
    inputs:
      node-version: "22"
      stage: test
```

CI/CD Catalog components 和 `spec:inputs` 是现代参数化复用方式，但功能在近年快速演进。输入类型、默认值、校验、插值函数、版本选择和层级限制均应查对应 GitLab 版本文档，不要把普通变量语法与 `$[[ inputs.* ]]` 混用。

### 17.5 条件 include

```yaml
include:
  - local: /.gitlab/ci/frontend.yml
    rules:
      - exists:
          - frontend/package.json
  - local: /.gitlab/ci/docker.yml
    rules:
      - changes:
          - Dockerfile
          - docker/**/*
```

### 17.6 合并行为

GitLab 先按顺序递归合并 included 文件，再将主 `.gitlab-ci.yml` 合并到结果。大体规则：

- 哈希可深合并。
- 同名标量或数组由后者覆盖。
- 主文件通常可覆盖 include 中的值。
- 数组不能按元素自动合并，例如主文件重写 `rules` 会替换原数组。

### 17.7 Include 限制与陷阱

- 当前官方文档说明默认最多 150 个嵌套 include；GitLab 15.10 之前默认限制不同，Self-Managed 管理员也可调整。
- include 解析有超时和网络失败风险。
- `include` 不能使用 job-only 变量，也不能使用同一 YAML 顶层 `variables` 刚定义的值来选择文件。
- 在从其他项目 include 的文件里使用 `rules:exists` 时，默认文件存在性检查上下文可能是“定义 include 的项目/ref”，不是主项目；高级 `project/ref` 形式可显式指定，但有版本要求。
- YAML anchor 不能跨文件，跨文件复用使用 `extends` 或 `!reference`。

---

## 18. 下游、父子与多项目流水线

### 18.1 父子流水线

父配置：

```yaml
stages: [test, downstream]

unit-test:
  stage: test
  script:
    - npm test

backend-child:
  stage: downstream
  trigger:
    include:
      - local: .gitlab/ci/backend-child.yml
    strategy: mirror
  rules:
    - changes:
        - backend/**/*
```

子配置 `.gitlab/ci/backend-child.yml`：

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "parent_pipeline"'

stages: [build, test]

build-backend:
  stage: build
  script:
    - ./backend/build.sh

test-backend:
  stage: test
  script:
    - ./backend/test.sh
```

`strategy: mirror` 让 trigger job 状态反映下游 pipeline 状态，是当前推荐的状态镜像方式。`strategy: depend` 是较早写法，官方文档已倾向 `mirror`；旧实例是否支持 `mirror` 需核对版本。

父子 pipeline：

- 在同一项目、同一 ref/SHA 上运行。
- 子 pipeline 的 `CI_PIPELINE_SOURCE` 为 `parent_pipeline`。
- 默认只在父 pipeline 详情页关联显示，不等同独立项目 pipeline。

### 18.2 动态子流水线

先生成 YAML artifact，再触发：

```yaml
generate-config:
  stage: build
  script:
    - ./generate-child-config.sh > generated-child.yml
  artifacts:
    paths:
      - generated-child.yml

run-generated:
  stage: deploy
  trigger:
    include:
      - artifact: generated-child.yml
        job: generate-config
    strategy: mirror
```

生成器必须防止不可信输入注入任意 CI 配置。动态子配置对变量、include 和文件路径有额外限制。

### 18.3 多项目流水线

```yaml
deploy-service:
  trigger:
    project: platform/deployments
    branch: main
    strategy: mirror
  variables:
    TARGET_PROJECT: "$CI_PROJECT_PATH"
    TARGET_SHA: "$CI_COMMIT_SHA"
```

多项目 pipeline 在下游项目中独立运行。触发用户或 job token 必须对下游项目有相应权限。

### 18.4 向下游传递变量与 inputs

```yaml
child:
  trigger:
    include:
      - local: child.yml
    forward:
      yaml_variables: true
      pipeline_variables: false
```

现代配置可使用带类型约束的 `inputs` 向下游传参，比任意 pipeline variables 更可控；它属于版本演进较快的功能，应按实例版本采用。

### 18.5 下游常见陷阱

- 子 pipeline job 的 `CI_PIPELINE_SOURCE` 不是 `push`，规则应允许 `parent_pipeline`。
- 多项目下游来源通常为 `pipeline`。
- 默认分支中 `workflow:rules` 若只允许 push/MR，可能阻止下游 pipeline。
- 父 pipeline 成功并不天然代表异步下游成功；需要合适的 `strategy`。
- artifact 跨 pipeline 传递需要 `needs:pipeline:job`、`needs:project` 或 API，并受权限/版本限制。
- 下游变量优先级高，通用变量名可能覆盖下游配置；使用项目或团队前缀。

---

## 19. `release` 与 Pages

### 19.1 `release`

`release` job 在脚本成功后创建 GitLab Release。job 必须包含 `script`，即使只写一条简单命令。

```yaml
create-release:
  image: registry.gitlab.com/gitlab-org/cli:latest
  script:
    - echo "Creating release $CI_COMMIT_TAG"
  release:
    tag_name: "$CI_COMMIT_TAG"
    name: "Release $CI_COMMIT_TAG"
    description: "Release generated by pipeline $CI_PIPELINE_URL"
  rules:
    - if: '$CI_COMMIT_TAG'
```

可配置 milestones、released_at、assets links 等，支持情况以当前版本为准。

陷阱：

- pipeline 重试时若 Release 已存在，创建可能失败；设计幂等流程或在脚本中处理。
- `release` 创建的是 GitLab Release 元数据，不会自动构建/上传二进制。
- 镜像 tag 应固定版本而非 `latest`，上例为展示简洁；生产应固定。

### 19.2 GitLab Pages

现代 Pages job 使用 `pages` 关键字：

```yaml
deploy-pages:
  script:
    - npm ci
    - npm run docs:build
  pages:
    publish: public
  artifacts:
    paths:
      - public
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

版本提示：

- 使用名为 `pages` 的特殊 job 是历史模式；当前官方文档已标记“使用 `pages` 作为 job 名” deprecated。
- 顶层 `publish` 已 deprecated，应写为 `pages:publish`。
- 新版本中 `pages:publish` 会自动加入 artifact paths；为兼容旧版本，上例仍显式声明 artifacts。
- Pages 的 `path_prefix`、`expire_in` 等并行部署能力与订阅层级/版本有关。

---

## 20. OIDC、`id_tokens` 与外部身份认证

### 20.1 为什么使用 OIDC

传统做法把长期 AWS/GCP/Vault 密钥存在 CI 变量中。OIDC 允许 job 获得短期签名 JWT，再向云服务交换临时凭据，泄漏窗口更小。

```yaml
deploy:
  id_tokens:
    CLOUD_ID_TOKEN:
      aud: https://cloud.example.com
  script:
    - ./exchange-token.sh "$CLOUD_ID_TOKEN"
    - ./deploy.sh
```

可以生成多个、不同 audience 的 token：

```yaml
job:
  id_tokens:
    VAULT_TOKEN:
      aud: https://vault.example.com
    DEPLOY_TOKEN:
      aud: https://deploy.example.com
  script:
    - ./use-vault "$VAULT_TOKEN"
    - ./deploy "$DEPLOY_TOKEN"
```

### 20.2 安全要点

- `aud` 必须与外部服务信任策略严格匹配，不要使用无必要的宽泛 audience。
- 外部信任策略同时约束稳定标识（如 `project_id`、`namespace_id`，若服务支持）和 ref/protected/environment 等 claim。
- 不要只依赖可改名的 `user_login`、`user_email`。
- 不要打印 token；token 到期时间与 job timeout 有关，未指定 job timeout 时当前官方文档说明默认有效期为 5 分钟。
- 旧 `$CI_JOB_JWT_V2` 已弃用并被移除，应迁移到 `id_tokens`。

### 20.3 版本风险

ID token claims 会增加或调整。例如当前官方文档标注：

- `job_project_id`、`job_project_path`、`job_namespace_id`、`job_namespace_path` 在 GitLab 18.4 引入。
- `sub` 可含更多字段的相关变化在 GitLab 18.7 出现。
- `job_source`、`job_config` 在 GitLab 18.9 引入。

因此云端 trust policy 不应假定旧实例拥有新 claim。GitLab Self-Managed 还必须正确配置公开可访问的 OIDC discovery/JWKS。

---

## 21. 完整实践一：Node.js 测试、构建与部署

目标：

- MR：lint、单元测试、构建。
- 默认分支：CI 并自动部署 staging。
- 语义化 tag：构建并提供手动 production 部署。
- 缓存 npm 下载，使用 artifact 传递 `dist/`。

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_TAG'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - when: never

stages:
  - validate
  - build
  - deploy

default:
  image: node:22-alpine
  interruptible: true
  cache:
    key:
      files:
        - package-lock.json
      prefix: npm
    paths:
      - .npm/
    policy: pull-push
  before_script:
    - node --version
    - npm ci --cache .npm --prefer-offline

variables:
  NODE_ENV: test

.ci-rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - if: '$CI_COMMIT_TAG'

lint:
  stage: validate
  extends: .ci-rules
  script:
    - npm run lint

unit-test:
  stage: validate
  extends: .ci-rules
  script:
    - npm test -- --ci --reporters=default --reporters=jest-junit
  artifacts:
    when: always
    reports:
      junit: junit.xml
    paths:
      - coverage/
    expire_in: 7 days

build:
  stage: build
  extends: .ci-rules
  needs:
    - lint
    - job: unit-test
      artifacts: false
  variables:
    NODE_ENV: production
  script:
    - npm run build
  artifacts:
    name: "web-$CI_COMMIT_REF_SLUG-$CI_COMMIT_SHORT_SHA"
    paths:
      - dist/
    expire_in: 14 days

deploy-staging:
  stage: deploy
  interruptible: false
  resource_group: staging
  needs:
    - job: build
      artifacts: true
  before_script: [] # 部署脚本不需要 npm ci，覆盖默认 before_script
  script:
    - ./scripts/deploy.sh staging dist/
  environment:
    name: staging
    url: https://staging.example.com
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'

deploy-production:
  stage: deploy
  interruptible: false
  resource_group: production
  needs:
    - job: build
      artifacts: true
  before_script: []
  script:
    - ./scripts/deploy.sh production dist/
  environment:
    name: production
    url: https://www.example.com
    deployment_tier: production
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: manual
      allow_failure: false
```

说明：

- `workflow` 避免普通功能分支 push 与 MR 重复流水线。
- `needs` 使 build 在 lint/test 完成后立即开始。
- deploy 通过 `needs:artifacts` 取得 `dist/`。
- deploy 清空默认 `before_script`，避免无意义地安装 Node 依赖。
- 生产部署显式阻塞、互斥、不可中断。

---

## 22. 完整实践二：Docker 镜像构建

以下展示 Docker-in-Docker（DinD）。它要求 Docker executor、可用的 privileged Runner 或等效配置，安全边界较弱。生产环境也可评估 BuildKit rootless、Buildah、Kaniko 或平台提供的安全构建方案；具体选型取决于 Runner 和 Registry。

```yaml
stages: [test, image]

variables:
  DOCKER_HOST: tcp://docker:2375
  DOCKER_TLS_CERTDIR: ""
  DOCKER_BUILDKIT: "1"

docker-build:
  stage: image
  image: docker:27-cli
  services:
    - name: docker:27-dind
      alias: docker
  before_script:
    - echo "$CI_REGISTRY_PASSWORD" |
        docker login --username "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
  script:
    - |
      if [ -n "$CI_COMMIT_TAG" ]; then
        IMAGE_TAG="$CI_COMMIT_TAG"
      else
        IMAGE_TAG="$CI_COMMIT_SHORT_SHA"
      fi
      export IMAGE_TAG
    - docker build --pull --tag "$CI_REGISTRY_IMAGE:$IMAGE_TAG" .
    - docker push "$CI_REGISTRY_IMAGE:$IMAGE_TAG"
    - |
      if [ "$CI_COMMIT_BRANCH" = "$CI_DEFAULT_BRANCH" ]; then
        docker tag "$CI_REGISTRY_IMAGE:$IMAGE_TAG" "$CI_REGISTRY_IMAGE:latest"
        docker push "$CI_REGISTRY_IMAGE:latest"
      fi
  rules:
    - if: '$CI_COMMIT_TAG'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes:
        - Dockerfile
        - docker/**/*
        - package.json
        - package-lock.json
```

重要注意：

- 上例关闭了 DinD TLS，只适合隔离、可信的 Runner 网络。若使用官方 TLS 模式，应正确共享证书目录。
- 不要把 `$CI_REGISTRY_PASSWORD` 放在命令参数中，使用 `--password-stdin`。
- MR 中是否 push 镜像应由安全策略决定。来自 fork 的 MR 不应获得 Registry 写凭据；更稳妥的做法是 MR 只 `docker build`，默认分支/tag 才登录和 push。
- 应固定 `docker` 镜像的补丁版本或 digest，示例中的大版本仅便于阅读。
- 多架构镜像通常使用 buildx，需要独立设置 builder、缓存和权限。

更安全的规则拆分：

```yaml
docker-verify:
  image: docker:27-cli
  services:
    - docker:27-dind
  script:
    - docker build --pull .
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

docker-publish:
  image: docker:27-cli
  services:
    - docker:27-dind
  script:
    - echo "$CI_REGISTRY_PASSWORD" |
        docker login -u "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

---

## 23. 完整实践三：模板与子流水线

目录：

```text
.gitlab-ci.yml
.gitlab/ci/
├── templates.yml
├── backend-child.yml
└── frontend-child.yml
```

`.gitlab-ci.yml`：

```yaml
include:
  - local: /.gitlab/ci/templates.yml

workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - when: never

stages: [validate, children]

yaml-check:
  stage: validate
  image: alpine:3.22
  script:
    - echo "Root configuration accepted"

backend:
  stage: children
  trigger:
    include:
      - local: /.gitlab/ci/backend-child.yml
    strategy: mirror
  rules:
    - changes:
        - backend/**/*
        - .gitlab/ci/backend-child.yml

frontend:
  stage: children
  trigger:
    include:
      - local: /.gitlab/ci/frontend-child.yml
    strategy: mirror
  rules:
    - changes:
        - frontend/**/*
        - .gitlab/ci/frontend-child.yml
```

`.gitlab/ci/templates.yml`：

```yaml
.base-test:
  interruptible: true
  retry:
    max: 1
    when:
      - runner_system_failure
  artifacts:
    when: always
    expire_in: 7 days
```

`.gitlab/ci/backend-child.yml`：

```yaml
include:
  - local: /.gitlab/ci/templates.yml

workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "parent_pipeline"'

stages: [test, build]

backend-test:
  extends: .base-test
  stage: test
  image: node:22-alpine
  before_script:
    - cd backend
    - npm ci
  script:
    - npm test
  artifacts:
    reports:
      junit: backend/junit.xml

backend-build:
  stage: build
  image: node:22-alpine
  needs:
    - job: backend-test
      artifacts: false
  before_script:
    - cd backend
    - npm ci
  script:
    - npm run build
  artifacts:
    paths:
      - backend/dist/
```

`.gitlab/ci/frontend-child.yml` 可按相同模式编写。注意 include 合并时，子文件里的 job 可以继承模板；YAML anchors 则不能跨文件。

---

## 24. 配置校验与调试

### 24.1 Pipeline Editor 与 CI Lint

在项目中进入 **Build → Pipeline editor → Validate**：

1. 粘贴或编辑配置。
2. 运行 Lint，检查 YAML、关键字和 include 合并后的逻辑。
3. 使用“Simulate pipeline creation”模拟默认分支 push，发现 `needs`、`rules` 等创建阶段错误。

模拟只代表指定场景，不能替代 MR/tag/schedule 的真实规则测试。

### 24.2 CI Lint API

API 路径与认证方式以当前 GitLab API 文档为准。典型调用：

```bash
curl --request POST \
  --header "PRIVATE-TOKEN: $GITLAB_TOKEN" \
  --header "Content-Type: application/json" \
  --data @lint-request.json \
  "https://gitlab.example.com/api/v4/projects/123/ci/lint"
```

`lint-request.json`：

```json
{
  "content": "job:\n  script:\n    - echo hello\n",
  "dry_run": true,
  "include_jobs": true
}
```

字段和返回结构会随版本扩展；自动化前查实例 API 文档。

### 24.3 查看合并后的配置

Pipeline editor、CI Lint 或 pipeline 详情中的配置视图可帮助检查：

- include 是否按预期合并；
- `extends` 后的最终值；
- 数组是否被覆盖；
- 规则是否生成了目标 job。

不要只读源文件猜最终结果。

### 24.4 输出调试信息

```yaml
debug-context:
  image: alpine:3.22
  script:
    - echo "source=$CI_PIPELINE_SOURCE"
    - echo "ref=$CI_COMMIT_REF_NAME"
    - echo "branch=${CI_COMMIT_BRANCH:-<none>}"
    - echo "tag=${CI_COMMIT_TAG:-<none>}"
    - echo "sha=$CI_COMMIT_SHA"
  rules:
    - when: manual
      allow_failure: true
```

只输出白名单变量，不要 `printenv`。

### 24.5 Shell 调试

```yaml
job:
  script:
    - |
      set -eu
      # bash 中可按需使用：set -o pipefail
      echo "working directory: $(pwd)"
      ls -la
      ./build.sh
```

使用 `CI_DEBUG_TRACE=true` 会产生极详细日志并可能暴露秘密，只应临时、谨慎启用，完成后立即移除。

### 24.6 本地复现边界

本地 Docker 可复现镜像与脚本：

```bash
docker run --rm -it \
  -v "$PWD:/work" \
  -w /work \
  node:22-alpine \
  sh -lc 'npm ci && npm test'
```

但本地容器不能完全模拟：

- GitLab 配置编译和 `rules`；
- Runner checkout、cache、artifacts；
- service 网络；
- protected variables；
- OIDC 和 job token；
- environment/deployment 记录。

应把本地复现用于脚本问题，把 CI Lint/测试项目用于 GitLab 语义问题。

---

## 25. 常见报错与排查

### 25.1 `jobs:<name>:script config should be a string or a nested array of strings`

可能原因：

- 命令中 `: ` 被 YAML 解析成映射；
- 缩进错误；
- `!reference` 结果层级不合法。

解决：

```yaml
script:
  - 'echo "key: value"'
```

并用 CI Lint 查看合并结果。

### 25.2 `chosen stage does not exist`

job 的 `stage` 未列入顶层 `stages`，或 include 覆盖了 stages 数组。

```yaml
stages: [test, build, deploy]
```

数组不会深合并，检查最终配置。

### 25.3 Pipeline 无法创建：`needs job ... was not added`

被依赖 job 因 `rules` 未加入流水线。

```yaml
needs:
  - job: optional-scan
    optional: true
```

或者统一两个 job 的规则。

### 25.4 Job 一直 `pending`

检查：

1. 是否有在线 Runner。
2. job tags 是否全部匹配。
3. Runner 是否允许该项目、protected ref 或 untagged job。
4. Runner 并发是否已满。
5. 项目是否还有 CI/CD 配额。

### 25.5 `This job is stuck because the project doesn't have any runners online assigned to it`

这是调度问题，不是 script 问题。注册/启用 Runner，或修正 tags。

### 25.6 `No files to upload`

artifact 路径相对 `$CI_PROJECT_DIR`，文件可能：

- 未生成；
- 在错误目录；
- 被 `after_script` 删除；
- glob 不匹配。

失败排查时先 `pwd` 和 `ls -la`，不要无脑改成绝对路径。

### 25.7 Cache 每次 miss

检查：

- key 是否每次变化；
- Runner 是否共享缓存后端；
- 缓存路径是否在项目目录内；
- job 是否有 push cache 权限/策略；
- 并行 job 是否覆盖同一 key。

### 25.8 `Local file ... does not exist`（include）

检查路径大小写、开头 `/`、文件所在 ref。分布式 Gitaly/Praefect 环境也存在过间歇性系统问题；路径确认无误后可重试并查服务端日志。

### 25.9 重复的 branch/MR pipelines

原因通常是 push 同时满足分支 pipeline，job 规则又启用了 MR pipeline。使用前述 `workflow:rules` + `CI_OPEN_MERGE_REQUESTS` 切换模式。

### 25.10 MR 一直显示 `Checking pipeline status`

项目要求 pipeline 成功，但 `workflow:rules` 阻止了 MR pipeline。确保 MR 来源有至少一条可创建 pipeline 的规则。

### 25.11 变量在 `rules` 中为空

可能是：

- 该变量是 job-only；
- MR/tag pipeline 中变量本来不存在；
- protected 变量未向非 protected ref 暴露；
- dotenv 要等前置 job 执行，不能用于规则。

先查预定义变量的 Availability 列，再调整规则。

### 25.12 服务容器连不上

不要连 `localhost`：

```yaml
services:
  - name: postgres:17-alpine
    alias: db
```

应用连接 `db:5432`，并增加就绪等待：

```yaml
script:
  - until nc -z db 5432; do sleep 1; done
  - npm run test:integration
```

### 25.13 OIDC 返回 401

重点核对：

- 是否真的声明 `id_tokens`；
- `aud` 是否完全一致；
- 外部服务信任的 `sub`/claims 是否匹配；
- 是否仍使用已弃用的 `$CI_JOB_JWT_V2`；
- 实例时间与签名/JWKS 配置是否正常。

可在严格受控的调试 job 中解码 payload 检查 claims，但绝不能把完整 token 写入日志或 artifact。

---

## 26. 最佳实践

### 26.1 正确性

1. 锁定语言、工具和服务镜像版本；关键供应链镜像使用 digest。
2. 提交包管理器锁文件，并用锁文件生成 cache key。
3. 构建输出用 artifacts，不依赖 cache 保证正确性。
4. 为 `rules` 明确 pipeline source，尤其区分 push、MR、tag、schedule 和 downstream。
5. 对可能被规则移除的 `needs` 使用一致规则或 `optional: true`。
6. 每次重构 include/extends 后查看合并配置。

### 26.2 性能

1. 用 `needs` 缩短关键路径。
2. 缓存下载目录，不缓存巨大、不可复用的工作树。
3. 并行测试分片，并保证分片真正均衡。
4. 启用 `interruptible` 和冗余流水线自动取消。
5. 用 `changes` 避免 monorepo 无关模块运行，但为非 push pipeline 设计明确行为。

### 26.3 安全

1. 秘密只放 UI/API 管理的 CI/CD variables 或外部秘密管理器。
2. 生产秘密设置 Masked/Hidden、Protected 和正确 environment scope。
3. 生产环境启用 protected environment、审批与 `resource_group`。
4. 审查 fork MR，禁止不可信脚本获取上游秘密。
5. 优先 OIDC 短期凭据，限制 audience 和 claims。
6. 跨项目 include 固定 commit SHA/tag；remote include 使用完整性校验（若版本支持）。
7. 不在日志、dotenv、cache、artifact 中保存秘密。
8. 控制 `CI_JOB_TOKEN` allowlist 和最小权限。

### 26.4 可维护性

1. 小项目从单文件开始，按业务边界拆分 include，不要过早模板化。
2. `extends` 最多保持 2～3 层可读继承。
3. 数组覆盖处写注释，尤其 `rules`、`script`、`before_script`。
4. 隐藏 job 按用途命名：`.node-base`、`.docker-publish-rules`。
5. 复用跨项目逻辑时使用版本化 component/template 和变更日志。
6. 在测试项目验证模板的新版本，再升级生产项目引用。

### 26.5 发布与部署

1. 构建一次，多环境使用同一不可变 artifact/image digest。
2. 不要在生产部署 job 重新构建。
3. 生产部署设 `interruptible: false` 和稳定的 `resource_group`。
4. 手动生产 job 显式 `allow_failure: false`。
5. 部署脚本必须幂等，重试不会破坏环境。
6. 记录版本、commit SHA、pipeline URL 和回滚目标。

---

## 27. 关键词速查索引

| 关键字 | 作用 | 典型位置 | 首要陷阱 |
|---|---|---|---|
| `stages` | 定义阶段顺序 | 顶层 | 数组被 include 覆盖 |
| `stage` | 指定 job 阶段 | job | 自定义值必须存在于 stages |
| `script` | 主命令 | job | 冒号导致 YAML 类型错误 |
| `before_script` | 前置命令 | job/default | 覆盖而非追加 |
| `after_script` | 清理/后处理 | job/default | 独立 shell 上下文 |
| `image` | job 主容器 | job/default | 只对相应 executor 生效 |
| `services` | 旁路服务容器 | job/default | 不是 localhost，且需等待就绪 |
| `variables` | 配置变量 | 顶层/job | 作用域、优先级和展开时机 |
| `rules` | 决定 job 是否加入 | job | 第一条匹配即停止 |
| `workflow:rules` | 决定 pipeline 是否创建 | 顶层 | 可能阻止所有 MR pipeline |
| `needs` | DAG 依赖和 artifact 下载 | job | 可选 job 要 `optional` |
| `dependencies` | 限定前置 artifact 下载 | job | 不改变执行顺序；勿与 needs 混用 |
| `artifacts` | 保存/传递输出 | job | 过期、路径与下载范围 |
| `cache` | 加速可重建依赖 | job/default | 不保证命中，不能替代 artifact |
| `environment` | 记录部署环境 | job | 不会自动执行部署 |
| `resource_group` | 串行化同一资源 | job | 不当父子依赖可能死锁 |
| `parallel` | 复制 job | job | artifact 重名覆盖 |
| `parallel:matrix` | 参数矩阵 | job | 组合/名称限制和版本差异 |
| `retry` | 自动重试 | job/default | 不要重试确定性失败 |
| `timeout` | job 超时 | job/default | 受项目/Runner 上限限制 |
| `interruptible` | 允许取消旧 job | job/default/rules | 部署通常应 false |
| `tags` | 匹配 Runner | job/default | Runner 必须满足全部 tag |
| `default` | job 默认配置 | 顶层 | 子 job 同键通常整体覆盖 |
| `inherit` | 控制默认/变量继承 | job | false 可能移除必要配置 |
| `extends` | 继承模板 | job | 哈希合并，数组不合并 |
| `include` | 合并外部配置 | 顶层 | 权限、版本固定、合并顺序 |
| YAML anchor | 同文件复用 | 任意 YAML | 不能跨 include |
| `!reference` | 跨文件选择配置 | job/隐藏模板 | 处理时机和矩阵限制 |
| `trigger` | 创建下游 pipeline | trigger job | 来源变量和状态策略 |
| `release` | 创建 GitLab Release | job | 必须有 script；重试幂等 |
| `pages` | 发布 GitLab Pages | job | 新旧语法版本差异 |
| `id_tokens` | 生成 OIDC JWT | job/default（依版本） | audience/claims 必须严格匹配 |
| `allow_failure` | 允许失败 | job/rule | manual 默认值存在语境差异 |
| `when` | 执行条件/时机 | job/rule/artifacts | job 与 artifacts 的取值不同 |
| `only/except` | 旧式条件 | job | 已不推荐，新配置用 rules |

---

## 28. 官方参考资料

以下链接均指向 GitLab 当前在线文档；Self-Managed 用户可在文档站切换到实例对应版本：

- [CI/CD YAML syntax reference](https://docs.gitlab.com/ci/yaml/)
- [Get started with GitLab CI/CD](https://docs.gitlab.com/ci/)
- [Specify when jobs run with rules](https://docs.gitlab.com/ci/jobs/job_rules/)
- [`workflow` keyword](https://docs.gitlab.com/ci/yaml/workflow/)
- [Use CI/CD configuration from other files](https://docs.gitlab.com/ci/yaml/includes/)
- [Optimize YAML configuration](https://docs.gitlab.com/ci/yaml/yaml_optimization/)
- [Downstream pipelines](https://docs.gitlab.com/ci/pipelines/downstream_pipelines/)
- [Job artifacts](https://docs.gitlab.com/ci/jobs/job_artifacts/)
- [Caching in GitLab CI/CD](https://docs.gitlab.com/ci/caching/)
- [CI/CD variables](https://docs.gitlab.com/ci/variables/)
- [Predefined CI/CD variables reference](https://docs.gitlab.com/ci/variables/predefined_variables/)
- [Environments and deployments](https://docs.gitlab.com/ci/environments/)
- [OIDC authentication using ID tokens](https://docs.gitlab.com/ci/secrets/id_token_authentication/)
- [Validate GitLab CI/CD configuration](https://docs.gitlab.com/ci/yaml/lint/)
- [Debugging CI/CD pipelines](https://docs.gitlab.com/ci/debugging/)
- [GitLab Runner executors](https://docs.gitlab.com/runner/executors/)
- [GitLab CI/CD examples](https://docs.gitlab.com/ci/examples/)

---

## 总结

编写可靠 `.gitlab-ci.yml` 的核心不是记住全部关键字，而是始终分清四个层次：

1. `workflow:rules` 是否创建 pipeline。
2. job `rules` 是否把 job 放入 pipeline。
3. `stages`/`needs` 如何安排执行与 artifact 流向。
4. Runner 在何种镜像、变量、权限和网络条件下执行脚本。

建议从最小 job 开始，每增加一组 `include`、规则或 DAG 依赖就运行 CI Lint，并查看最终合并配置。涉及生产环境、外部模板、秘密或 OIDC 时，再对照当前实例版本和订阅层级完成一次权限与供应链审查。
