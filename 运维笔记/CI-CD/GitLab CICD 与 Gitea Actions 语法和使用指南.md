# GitLab CI/CD 与 Gitea Actions 语法和使用指南


## 1. 文档概述

本文帮助你理解并实际使用两套常见的持续集成与持续交付系统：

- **GitLab CI/CD**：与 GitLab 平台深度集成，通过 `.gitlab-ci.yml` 描述流水线。
- **Gitea Actions**：Gitea 提供的自动化能力，工作流语法大体兼容 GitHub Actions。

阅读后，你应该能够：

1. 为 Node.js 项目编写测试、构建和部署流水线。
2. 正确配置 Runner、变量、Secrets、缓存与构建产物。
3. 理解两套系统在任务编排和条件控制上的差异。
4. 将常见的 GitLab CI 流水线迁移到 Gitea Actions。
5. 根据日志和本地复现结果定位常见故障。

> **重要兼容性说明**  
> Gitea Actions 大体兼容 GitHub Actions 的工作流语法，但不保证所有 GitHub Actions 能力、表达式、事件、服务端 API 或第三方 Action 都完全兼容。兼容范围还可能受 Gitea、Runner、Action 自身及部署方式影响。迁移或引入第三方 Action 前，应查阅当前环境的官方文档，并在测试仓库验证。

## 2. 前置条件

开始前建议准备：

- 一个 GitLab 或 Gitea 仓库。
- 对仓库具有维护或管理权限，以便注册 Runner、配置变量或 Secrets。
- 一台可以执行流水线的 Runner 主机。
- 如需使用容器镜像和服务容器，Runner 主机还需要可用的 Docker 或兼容容器环境。
- 示例项目中包含 `package.json`，并提交锁文件，例如 `package-lock.json`。

本文不绑定具体产品版本。不同版本和安装方式的界面、配置项及兼容范围可能不同；涉及版本差异时，应以当前部署所对应的官方文档为准。

## 3. 先看结论：两套系统的核心思路

两者都解决同一个问题：当代码发生特定变化时，自动在 Runner 上执行测试、构建、发布或部署命令。

共同流程可以概括为：

```text
代码事件
  → CI/CD 平台解析 YAML
  → 选择可用 Runner
  → 准备执行环境
  → 下载代码与依赖
  → 执行测试、构建或部署
  → 保存日志、缓存和构建产物
```

主要差异如下：

- GitLab CI/CD 以 **pipeline → stages → jobs → script** 为主要模型。
- Gitea Actions 以 **workflow → jobs → steps** 为主要模型。
- GitLab 同一 stage 中的 job 默认可并行，不同 stage 默认按顺序推进。
- Gitea Actions 没有 GitLab 式的顶层 `stages`；job 默认可并行，通过 `needs` 显式建立依赖。
- GitLab 的常见复用单位是 `include`、模板、`extends` 和 YAML anchor。
- Gitea Actions 的常见复用单位是 Action、可复用工作流及 YAML 结构；具体支持范围需按当前版本验证。
- GitLab 缓存和 artifacts 是 CI 配置中的原生关键字。
- Gitea Actions 通常通过 `uses` 步骤调用缓存、上传和下载产物类 Action。

## 4. 配置文件放在哪里

### 4.1 GitLab CI/CD

默认入口文件位于仓库根目录：

```text
.gitlab-ci.yml
```

最小示例：

```yaml
stages:
  - test

unit-test:
  stage: test
  script:
    - npm ci
    - npm test
```

关键行说明：

- `stages` 定义阶段顺序。
- `unit-test` 是 job 名称，可自定义。
- `stage: test` 把该 job 放入 `test` 阶段。
- `script` 中的命令按顺序执行，任一命令失败通常会使 job 失败。

大型项目可以使用 `include` 拆分配置。被包含文件的位置和来源支持范围应以当前 GitLab 文档为准。

### 4.2 Gitea Actions

工作流文件通常放在：

```text
.gitea/workflows/*.yml
.gitea/workflows/*.yaml
```

例如：

```text
.gitea/workflows/ci.yml
```

最小示例：

```yaml
name: CI

on:
  push:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Test
        run: |
          npm ci
          npm test
```

关键行说明：

- `on` 声明触发事件。
- `jobs.test` 定义名为 `test` 的 job。
- `runs-on` 用标签匹配 Runner；它不一定代表真实的 Ubuntu 虚拟机。
- `steps` 按顺序执行。
- `uses` 调用一个 Action；`run` 直接执行 Shell 命令。

> `runs-on: ubuntu-latest` 的实际环境由 Gitea Runner 标签映射决定。自建 Runner 可能把该标签映射到某个容器镜像，也可能直接在宿主机执行。不要仅根据标签名称推断操作系统和工具版本。

## 5. Runner 与执行器准备

Runner 是真正执行命令的工作进程。平台服务负责排队和调度，Runner 负责拉取任务并运行。

### 5.1 GitLab Runner

常见执行器包括：

- **Shell executor**：直接在 Runner 主机上执行。启动快，但环境隔离较弱。
- **Docker executor**：每个 job 使用容器环境。隔离性和可复现性更好。
- **Kubernetes executor**：在 Kubernetes 中为任务创建 Pod，适合已有集群的团队。

典型准备流程：

1. 在 GitLab 中创建或获取 Runner 注册信息。
2. 在执行主机安装 GitLab Runner。
3. 注册 Runner，并选择 executor。
4. 给 Runner 设置标签。
5. 在 job 中使用 `tags` 匹配 Runner。

示例：

```yaml
build:
  tags:
    - docker
    - linux
  image: node:20
  script:
    - npm ci
    - npm run build
```

这里的 `tags` 是 Runner 选择条件；只有满足标签和其他调度条件的 Runner 才能接单。

### 5.2 Gitea Actions Runner

Gitea Actions 通常使用 `act_runner`。典型准备流程：

1. 在 Gitea 的仓库、组织或实例管理范围内取得 Runner 注册信息。
2. 安装或运行 `act_runner`。
3. 执行注册流程并连接 Gitea 实例。
4. 配置 Runner 标签及其执行环境映射。
5. 启动 Runner 守护进程。
6. 在工作流中用 `runs-on` 匹配标签。

示例：

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run build
```

实际命令行参数、配置文件字段以及容器运行方式可能随部署方案变化，应使用与你当前 Gitea/Runner 环境匹配的官方安装文档。

### 5.3 Runner 安全建议

- 不要让不可信仓库或未经审查的外部贡献代码访问生产 Secrets。
- 避免在同一无隔离 Shell Runner 上混跑高信任和低信任任务。
- 限制 Runner 主机的网络、文件系统和云平台权限。
- 定期更新基础镜像与 Runner。
- 不要把 Docker Socket 暴露给不可信 job；获得 Docker Socket 往往等价于获得宿主机高权限。
- 为部署任务使用专用 Runner、受保护分支和最小权限凭据。

## 6. 触发条件

### 6.1 GitLab：`workflow: rules` 与 job `rules`

`workflow: rules` 决定是否创建整条 pipeline，job 的 `rules` 决定某个 job 是否进入 pipeline。

```yaml
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
    - if: '$CI_COMMIT_TAG'

test:
  script:
    - npm test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

关键点：

- 该配置允许合并请求、默认分支和标签创建 pipeline。
- `rules` 从上到下判断；规则组合和默认行为需要谨慎设计。
- 复杂配置应避免同时使用旧式 `only/except` 与 `rules`，以免行为难以理解。

按文件变化触发：

```yaml
frontend-test:
  script:
    - npm ci
    - npm test
  rules:
    - changes:
        - frontend/**/*
        - package.json
        - package-lock.json
```

### 6.2 Gitea Actions：`on`

```yaml
name: CI

on:
  push:
    branches:
      - main
    tags:
      - "v*"
  pull_request:
    branches:
      - main
  workflow_dispatch:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm test
```

关键点：

- `push.branches` 限制分支 push。
- `push.tags` 匹配版本标签。
- `pull_request` 针对拉取请求事件。
- `workflow_dispatch` 表示手动触发；其具体 UI 和输入能力要在当前 Gitea 环境验证。

按路径过滤的常见写法：

```yaml
on:
  push:
    paths:
      - "frontend/**"
      - "package.json"
      - "package-lock.json"
```

并非 GitHub Actions 支持的每个事件和过滤细节都必然被 Gitea Actions 完整实现。使用少见事件前，应先验证。

## 7. `jobs`、`stages` 与 `steps`

### 7.1 GitLab 的阶段模型

```yaml
stages:
  - lint
  - test
  - build

lint:
  stage: lint
  script:
    - npm run lint

unit-test:
  stage: test
  script:
    - npm test

build:
  stage: build
  script:
    - npm run build
```

执行逻辑：

1. `lint` 阶段先执行。
2. 成功后进入 `test`。
3. 成功后进入 `build`。
4. 同一阶段的多个 job 默认可以并行，但取决于 Runner 容量。

### 7.2 Gitea Actions 的依赖图模型

```yaml
name: CI

on:
  push:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run lint

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm test

  build:
    needs:
      - lint
      - test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run build
```

执行逻辑：

- `lint` 和 `test` 没有相互依赖，可以并行。
- `build` 只有在二者完成并满足成功条件后才开始。
- 每个 job 通常是独立环境；不能假设前一个 job 安装的依赖或生成的文件会自动存在。

## 8. 镜像与服务

### 8.1 GitLab 的 `image` 与 `services`

下面的测试任务使用 Node.js 容器，并启动 PostgreSQL 服务容器：

```yaml
integration-test:
  image: node:20
  services:
    - name: postgres:16
      alias: db
  variables:
    POSTGRES_DB: app_test
    POSTGRES_USER: app
    POSTGRES_PASSWORD: test-password
    DATABASE_URL: postgres://app:test-password@db:5432/app_test
  script:
    - npm ci
    - npm run test:integration
```

关键点：

- `image` 是主 job 容器镜像。
- `services` 启动与 job 配套的服务容器。
- `alias: db` 让应用通过主机名 `db` 访问 PostgreSQL。
- CI 中的测试密码只能用于临时测试数据库，不应复用生产凭据。
- 服务启动不代表已经就绪；必要时应增加健康检查或重试逻辑。

### 8.2 Gitea Actions 的 job 容器与服务

兼容工作流的常见写法如下：

```yaml
name: Integration Test

on:
  push:

jobs:
  integration-test:
    runs-on: ubuntu-latest
    container:
      image: node:20
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: app_test
          POSTGRES_USER: app
          POSTGRES_PASSWORD: test-password
    env:
      DATABASE_URL: postgres://app:test-password@postgres:5432/app_test
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run test:integration
```

注意：

- `container`、`services`、网络别名、端口映射和健康检查的具体行为依赖 Runner 执行方式。
- 自建 Gitea 环境必须确认 Runner 能访问容器引擎。
- 若当前 Gitea/Runner 对某些容器选项支持不完整，可改用 Runner 标签映射到预装环境，或在步骤中显式启动测试服务。

## 9. 变量与 Secrets

### 9.1 GitLab 变量

普通变量可以写在 YAML 中：

```yaml
variables:
  NODE_ENV: test

test:
  script:
    - echo "NODE_ENV=$NODE_ENV"
    - npm test
```

敏感值应通过 GitLab 项目、群组或实例的 CI/CD Variables 配置，不应提交到仓库。

```yaml
deploy:
  script:
    - ./scripts/deploy.sh
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

脚本可读取管理界面中配置的环境变量，例如 `$DEPLOY_TOKEN`。

建议：

- 对敏感变量启用适当的遮蔽和保护选项。
- 只允许受保护分支或标签使用生产凭据。
- 不要 `echo` Secrets，也不要打开会打印命令参数的调试模式。
- 注意遮蔽并非万能：转换、编码或写入文件后仍可能泄漏。

### 9.2 Gitea Actions 的变量与 Secrets

工作流普通变量使用 `env`：

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      NODE_ENV: test
    steps:
      - uses: actions/checkout@v4
      - run: npm test
```

敏感值从 Secrets 上下文读取：

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Deploy
        env:
          DEPLOY_TOKEN: ${{ secrets.DEPLOY_TOKEN }}
        run: ./scripts/deploy.sh
```

关键点：

- `${{ ... }}` 是工作流表达式，不是 Shell 变量语法。
- 把 Secret 映射到单个步骤的 `env`，比放到整个 workflow 更符合最小暴露原则。
- 仓库、组织和实例级 Secrets 的可见性与覆盖规则应以当前 Gitea 文档和实际配置为准。
- 来自外部贡献者的拉取请求不应默认获得高权限 Secrets。

## 10. 缓存与 Artifacts

二者用途不同：

- **缓存（cache）**：加快未来 job 或 pipeline，例如复用包管理器下载目录。缓存可能失效或被清理，不能当作可靠交付物。
- **构建产物（artifacts）**：保存本次执行生成的文件，例如 `dist/`、测试报告和覆盖率报告。

### 10.1 GitLab 缓存

Node.js 项目更适合缓存 npm 下载缓存，而不是直接缓存 `node_modules`：

```yaml
test:
  image: node:20
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - .npm/
  script:
    - npm ci --cache .npm --prefer-offline
    - npm test
```

锁文件变化后，缓存 key 随之变化，降低错误复用旧依赖的风险。

### 10.2 GitLab Artifacts

```yaml
build:
  image: node:20
  script:
    - npm ci
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 7 days
```

`dist/` 会作为本次 job 的产物保存。保留时间和存储策略应结合平台容量设置。

### 10.3 Gitea Actions 缓存

常见兼容写法：

```yaml
steps:
  - uses: actions/checkout@v4

  - name: Cache npm downloads
    uses: actions/cache@v4
    with:
      path: ~/.npm
      key: npm-${{ runner.os }}-${{ hashFiles('package-lock.json') }}
      restore-keys: |
        npm-${{ runner.os }}-

  - run: npm ci
  - run: npm test
```

### 10.4 Gitea Actions Artifacts

```yaml
steps:
  - uses: actions/checkout@v4
  - run: npm ci
  - run: npm run build

  - name: Upload dist
    uses: actions/upload-artifact@v4
    with:
      name: web-dist
      path: dist/
```

> 缓存和 artifact Action 的可用版本必须与当前 Gitea Actions 实现兼容。第三方或 GitHub 官方 Action 可能依赖 GitHub 专属 API、Node 运行时、网络访问或特定服务端协议。若失败，应检查 Gitea 官方兼容说明，并考虑固定到已验证版本、使用 Gitea 可访问的 Action 镜像源，或改成显式脚本和对象存储。

## 11. 依赖关系与条件执行

### 11.1 GitLab：`needs`、`dependencies` 和 `rules`

```yaml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  script:
    - npm ci
    - npm run build
  artifacts:
    paths:
      - dist/

test:
  stage: test
  script:
    - npm ci
    - npm test

deploy:
  stage: deploy
  needs:
    - job: build
      artifacts: true
    - job: test
      artifacts: false
  script:
    - ./scripts/deploy-dist.sh dist/
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual
```

关键点：

- `needs` 显式建立 job 依赖，并可形成有向无环图执行路径。
- `artifacts: true` 表示从对应依赖获取产物。
- `dependencies` 主要控制从哪些早期 job 下载 artifacts；新设计通常优先考虑清晰的 `needs` 关系。
- `when: manual` 把生产部署设为人工确认。

始终执行清理或报告：

```yaml
report:
  stage: deploy
  script:
    - ./scripts/report.sh
  when: always
```

### 11.2 Gitea Actions：`needs` 与 `if`

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: web-dist
          path: dist/

  deploy:
    needs: build
    if: ${{ gitea.ref == 'refs/heads/main' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: web-dist
          path: dist/
      - run: ./scripts/deploy-dist.sh dist/
```

关键点：

- `needs: build` 保证先构建。
- 不同 job 之间用 artifact 传文件，不能依赖共享工作目录。
- Gitea 提供与工作流有关的上下文；上下文字段及表达式兼容程度应按当前版本验证。
- `if: ${{ always() }}` 常用于即使依赖失败也要运行的收尾步骤，但函数兼容性也应在目标环境测试。

步骤级条件示例：

```yaml
- name: Upload logs after failure
  if: ${{ failure() }}
  uses: actions/upload-artifact@v4
  with:
    name: failure-logs
    path: logs/
```

## 12. 完整 Node.js CI 示例

假设项目脚本如下：

```json
{
  "scripts": {
    "lint": "eslint .",
    "test": "vitest run",
    "build": "vite build"
  }
}
```

### 12.1 GitLab CI 完整示例

文件：

```text
.gitlab-ci.yml
```

内容：

```yaml
default:
  image: node:20

stages:
  - verify
  - build

variables:
  npm_config_cache: "$CI_PROJECT_DIR/.npm"

.node-job:
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - .npm/
  before_script:
    - node --version
    - npm --version
    - npm ci --prefer-offline

lint:
  extends: .node-job
  stage: verify
  script:
    - npm run lint

test:
  extends: .node-job
  stage: verify
  script:
    - npm test
  artifacts:
    when: always
    paths:
      - coverage/
    expire_in: 7 days

build:
  extends: .node-job
  stage: build
  needs:
    - lint
    - test
  script:
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 7 days

workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

关键行说明：

- `default.image` 为全部 job 设置 Node.js 镜像。
- `.node-job` 以点开头，是不会直接运行的隐藏模板 job。
- `extends` 复用安装依赖和缓存配置。
- `lint` 与 `test` 同属 `verify`，可并行执行。
- `build.needs` 明确要求检查任务成功。
- `artifacts.when: always` 让测试失败时也尽量保留覆盖率或诊断文件。

### 12.2 Gitea Actions 完整示例

文件：

```text
.gitea/workflows/ci.yml
```

内容：

```yaml
name: Node.js CI

on:
  push:
    branches:
      - main
  pull_request:
    branches:
      - main

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm

      - name: Install dependencies
        run: npm ci

      - name: Lint
        run: npm run lint

      - name: Test
        run: npm test

  build:
    needs: verify
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm

      - name: Install dependencies
        run: npm ci

      - name: Build
        run: npm run build

      - name: Upload dist
        uses: actions/upload-artifact@v4
        with:
          name: web-dist
          path: dist/
```

关键行说明：

- 每个 job 都重新 checkout，因为 job 环境彼此独立。
- `setup-node` 选择 Node.js 环境，并尝试使用 npm 缓存。
- `npm ci` 严格依据锁文件安装，适合 CI。
- `build` 通过 `needs` 等待 `verify`。
- `upload-artifact` 保存构建结果。

如果当前 Gitea 环境无法运行某个 `actions/*` Action，可以改用 Runner 已准备好的 Node.js 环境和普通命令：

```yaml
steps:
  - uses: actions/checkout@v4
  - run: |
      node --version
      npm ci
      npm test
      npm run build
```

即使是 `actions/checkout`，也应确认 Runner 能从配置的 Action 来源下载它。完全离线环境通常需要内部镜像、预置 Action 或替代脚本。

## 13. 部署示例

下面用 SSH 将 `dist/` 同步到部署服务器。生产环境还应结合审批、回滚、健康检查和审计。

### 13.1 GitLab 部署示例

```yaml
deploy-production:
  image: alpine:3.20
  stage: deploy
  needs:
    - job: build
      artifacts: true
  before_script:
    - apk add --no-cache openssh-client rsync
    - install -m 700 -d ~/.ssh
    - printf '%s' "$SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
    - chmod 600 ~/.ssh/id_ed25519
    - printf '%s\n' "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - rsync -az --delete dist/ "$DEPLOY_USER@$DEPLOY_HOST:/srv/www/app/"
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual
```

关键点：

- 私钥和 `known_hosts` 通过受保护 CI/CD Variables 注入。
- 使用预先保存的 `known_hosts`，不要用关闭主机校验的方式绕过安全检查。
- `when: manual` 提供人工发布闸门。
- `--delete` 会删除目标目录中源端不存在的文件，使用前必须确认目标路径正确。

### 13.2 Gitea Actions 部署示例

```yaml
name: Deploy

on:
  push:
    branches:
      - main

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: web-dist
          path: dist/

  deploy:
    needs: build
    runs-on: deploy-runner
    environment: production
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: web-dist
          path: dist/

      - name: Configure SSH
        env:
          SSH_PRIVATE_KEY: ${{ secrets.SSH_PRIVATE_KEY }}
          SSH_KNOWN_HOSTS: ${{ secrets.SSH_KNOWN_HOSTS }}
        run: |
          install -m 700 -d ~/.ssh
          printf '%s' "$SSH_PRIVATE_KEY" > ~/.ssh/id_ed25519
          chmod 600 ~/.ssh/id_ed25519
          printf '%s\n' "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts

      - name: Deploy
        env:
          DEPLOY_HOST: ${{ secrets.DEPLOY_HOST }}
          DEPLOY_USER: ${{ secrets.DEPLOY_USER }}
        run: rsync -az --delete dist/ "$DEPLOY_USER@$DEPLOY_HOST:/srv/www/app/"
```

注意：

- `deploy-runner` 是示例标签，必须在你的 Runner 中实际配置。
- 该 Runner 需要预装 `ssh` 和 `rsync`。
- Gitea 对 `environment`、审批及保护规则的支持范围不能直接等同于 GitHub；生产发布前应验证当前实例能力。
- 若必须人工批准，可使用平台当前支持的环境保护机制，或把生产发布设计为受权限控制的手动工作流。不要假设 GitHub 的审批行为会原样存在。

## 14. 调试方法

### 14.1 先缩小问题范围

按以下顺序排查：

1. **确认是否创建了 pipeline/workflow run**  
   没创建通常是 YAML 路径、语法、事件或过滤条件问题。
2. **确认 job 是否进入队列**  
   长时间排队通常是 Runner 离线、标签不匹配或并发容量不足。
3. **确认失败发生在哪个步骤**  
   区分环境准备、checkout、依赖安装、测试、artifact 或部署失败。
4. **在相同镜像或 Runner 环境复现命令**  
   避免只在开发机上测试。
5. **最后检查平台兼容与权限**  
   尤其是 Gitea 上的第三方 Action 和服务端 API 依赖。

### 14.2 输出必要的环境信息

可以临时加入：

```yaml
script:
  - node --version
  - npm --version
  - pwd
  - find . -maxdepth 2 -type f | sort
  - npm ci
```

Gitea Actions：

```yaml
- name: Print environment
  run: |
    node --version
    npm --version
    pwd
    find . -maxdepth 2 -type f | sort
```

不要输出完整环境变量列表，因为其中可能包含 Secrets。调试完成后删除多余日志。

### 14.3 使用 YAML 校验

- 检查缩进是否使用空格。
- 检查冒号、引号和多行字符串。
- 使用平台提供的配置校验或试运行能力。
- 对表达式中的冒号、`!`、`*` 等 YAML 特殊字符谨慎加引号。

### 14.4 在本地复现容器命令

GitLab Docker job 可以用接近的方式复现：

```bash
docker run --rm \
  -v "$PWD:/app" \
  -w /app \
  node:20 \
  sh -lc 'npm ci && npm test && npm run build'
```

Gitea Actions 与 GitHub Actions 风格工作流可考虑使用兼容的本地执行工具辅助排查，但本地模拟器与真实 Gitea Runner 并不完全等价。最终结果仍应以目标 Gitea 实例执行为准。

### 14.5 Runner 日志

如果 job 一直排队或初始化失败，应检查：

- Runner 进程是否在线。
- Runner 是否成功连接服务器。
- 标签是否与 `tags` 或 `runs-on` 匹配。
- 容器引擎是否可访问。
- Runner 用户是否有工作目录、缓存目录和网络访问权限。
- 反向代理、TLS 证书和服务器 URL 是否配置正确。

## 15. 常见问题与排查

### 15.1 YAML 正确，但流水线没有触发

可能原因：

- 文件路径不正确。
- `rules`、`workflow: rules` 或 `on` 未匹配当前事件。
- 分支、标签或路径过滤规则排除了本次提交。
- Gitea 仓库或实例未启用 Actions。

解决方法：

- 确认 GitLab 文件名是仓库根目录的 `.gitlab-ci.yml`。
- 确认 Gitea 文件位于 `.gitea/workflows/`。
- 临时简化触发规则，验证基础事件后逐项加回过滤条件。

### 15.2 Job 一直处于 Pending

可能原因：

- 没有在线 Runner。
- Runner 标签不匹配。
- Runner 不允许执行当前受保护分支或任务类型。
- 并发槽位已满。

解决方法：

- 查看 Runner 在线状态与日志。
- 对照 `tags` 或 `runs-on`。
- 检查 Runner 范围、权限和保护设置。

### 15.3 `npm ci` 失败

可能原因：

- 未提交 `package-lock.json`。
- `package.json` 与锁文件不一致。
- 私有 npm Registry 凭据缺失。
- Node.js 或 npm 环境与项目不兼容。

解决方法：

- 在本地更新并提交锁文件。
- 固定并打印 Node.js 版本。
- 以 Secret 配置 Registry Token，不要提交 `.npmrc` 中的明文凭据。

### 15.4 服务容器连接失败

可能原因：

- 数据库尚未就绪。
- 使用了错误主机名；容器内的 `localhost` 通常指当前容器自身。
- Runner 的服务网络或端口映射与预期不同。

解决方法：

- 使用服务别名，例如 GitLab 示例中的 `db` 或 Gitea 示例中的 `postgres`。
- 增加带超时的就绪检测。
- 检查 Runner 容器网络配置。

### 15.5 缓存没有命中

可能原因：

- key 每次都变化。
- 缓存路径写错。
- Runner 未配置共享缓存，任务又在不同 Runner 上执行。
- 缓存已过期或被清理。

解决方法：

- 让 key 主要依赖锁文件和必要的平台信息。
- 打印并确认实际缓存目录。
- 把缓存视为优化，不要让构建正确性依赖缓存。

### 15.6 前一个 job 的文件在后一个 job 中消失

原因：

- job 通常运行在隔离环境，工作目录不会自动共享。

解决方法：

- GitLab 使用 `artifacts` 配合 `needs`。
- Gitea Actions 使用上传和下载 artifact 的步骤。

### 15.7 Gitea 无法运行某个第三方 Action

可能原因：

- Action 调用了 GitHub 专属 API 或依赖 GitHub Token 语义。
- Action 要求 Gitea 尚未实现的事件、表达式或服务端协议。
- Runner 无法访问 Action 仓库或容器镜像。
- Action 所需运行时与 Runner 不兼容。

解决方法：

1. 查阅 Action 文档和当前 Gitea Actions 兼容说明。
2. 在隔离测试仓库运行最小示例。
3. 固定到已验证的 tag、commit SHA 或内部镜像。
4. 必要时将 Action 替换为透明的 Shell 脚本。

### 15.8 Secret 在日志中泄漏

立即执行：

1. 停止或取消相关任务。
2. 撤销并轮换泄漏凭据。
3. 删除或限制日志与 artifacts 的访问。
4. 修复脚本中的输出、调试选项和错误处理。
5. 检查凭据是否已被滥用。

日志遮蔽只能降低风险，不能替代最小权限和凭据轮换。

## 16. 从 GitLab CI 迁移到 Gitea Actions

迁移不是简单地重命名字段。建议先迁移触发、执行环境和命令，再处理缓存、产物、发布与高级能力。

### 16.1 语法对照

- GitLab `.gitlab-ci.yml`  
  对应 Gitea `.gitea/workflows/*.yml`。

- GitLab `workflow: rules`、job `rules`  
  对应 Gitea `on` 事件过滤和 job/step 的 `if`。两者表达能力和求值时机并不完全相同。

- GitLab `stages`  
  Gitea 没有直接等价的顶层阶段列表；使用 job `needs` 构造依赖图。

- GitLab job 下的 `script`  
  对应 Gitea job 下一个或多个 `steps[].run`。

- GitLab `before_script`、`after_script`  
  对应前置或收尾 `steps`。收尾步骤可能需要 `if: ${{ always() }}`，并验证兼容性。

- GitLab `image`  
  常对应 Gitea job 的 `container.image`，也可能由 `runs-on` 的 Runner 标签映射提供环境。

- GitLab `services`  
  常对应 Gitea job 的 `services`，但网络和容器能力要在目标 Runner 验证。

- GitLab `tags`  
  对应 Gitea `runs-on` 标签。

- GitLab `variables` 和 CI/CD Variables  
  对应 Gitea `env`、配置变量和 `${{ secrets.NAME }}`。

- GitLab `cache`  
  对应缓存类 Action，例如 `actions/cache`，但必须确认兼容版本。

- GitLab `artifacts`  
  对应上传和下载 artifact 的 Action。

- GitLab `needs`  
  对应 Gitea job `needs`，但 artifact 不会仅因声明依赖而自动传递，需要显式上传和下载。

- GitLab `extends`、隐藏 job 模板  
  Gitea 中通常改为 Action、可复用工作流或重复的清晰步骤；复用能力应按当前 Gitea 版本验证。

- GitLab `environment` 和手动 job  
  对应 Gitea 的环境、手动工作流或实例可用的审批机制，但不能假设保护与审批语义完全一致。

### 16.2 示例迁移

原 GitLab 配置：

```yaml
stages:
  - test
  - build

test:
  image: node:20
  stage: test
  script:
    - npm ci
    - npm test

build:
  image: node:20
  stage: build
  needs:
    - test
  script:
    - npm ci
    - npm run build
  artifacts:
    paths:
      - dist/
```

迁移后的 Gitea Actions：

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    container:
      image: node:20
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm test

  build:
    needs: test
    runs-on: ubuntu-latest
    container:
      image: node:20
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm run build
      - uses: actions/upload-artifact@v4
        with:
          name: web-dist
          path: dist/
```

关键变化：

1. `stage` 顺序改为 `needs`。
2. `script` 拆成 `steps`。
3. 每个 job 显式 checkout。
4. `artifacts` 改为上传 Action。
5. `image` 改为 job `container.image`。
6. 触发条件从 GitLab 规则改为 `on`。

### 16.3 推荐迁移步骤

#### 第一步：盘点当前流水线

要做什么：

- 列出触发来源、Runner 标签、镜像、服务、变量、Secrets、缓存、artifacts、部署目标和外部集成。

为什么：

- YAML 字段只是表象，真正需要迁移的是行为、权限和数据流。

预期结果：

- 得到一份可逐项验证的迁移清单。

#### 第二步：建立最小工作流

要做什么：

- 先实现 `push` 触发、checkout、安装依赖和单元测试。

为什么：

- 尽早确认 Runner、网络、Action 下载和基础语法可用。

预期结果：

- 最小 CI 在 Gitea 中稳定通过。

#### 第三步：恢复并行与依赖图

要做什么：

- 将 GitLab stages 转换为 `needs` 关系，识别可并行 job。

为什么：

- 照搬串行阶段会损失效率；省略依赖又可能让部署提前运行。

预期结果：

- 执行顺序与原流水线一致或更清晰。

#### 第四步：迁移缓存和 artifacts

要做什么：

- 为依赖下载设置缓存；用上传/下载 artifact 步骤连接 job。

为什么：

- Gitea job 之间不自动共享文件。

预期结果：

- 构建速度合理，部署 job 能获得准确产物。

#### 第五步：迁移 Secrets 和部署

要做什么：

- 在 Gitea 中重新创建 Secrets，配置专用 Runner 和分支保护，先部署到测试环境。

为什么：

- 不应复制明文凭据；GitLab 和 Gitea 的权限模型不完全相同。

预期结果：

- 凭据保持最小权限，测试环境部署成功。

#### 第六步：并行验证后切换

要做什么：

- 在一段时间内对比两套系统的测试结果、构建产物和部署行为。

为什么：

- 可以发现偶发测试、缓存污染、环境差异和兼容性问题。

预期结果：

- Gitea 流水线达到可替代标准后，再停用旧流水线。

### 16.4 迁移时尤其要注意

- 不要把 GitLab 预定义变量名称直接复制到 Gitea；应逐个映射到 Gitea 上下文、环境变量或自定义变量。
- 不要假设 `runs-on: ubuntu-latest` 与 GitLab 的 `node:20` 镜像等价。
- 不要假设声明 `needs` 就会传递文件。
- 不要假设 GitHub Marketplace 中的 Action 在 Gitea 中一定可用。
- 不要把第三方 Action 浮动引用视为稳定供应链。对高风险部署 Action，建议固定经过审核的 commit SHA，并建立更新流程。
- 检查 Action 拉取地址、私有仓库认证、网络代理和离线镜像策略。
- 核实拉取请求事件中 Secrets 的暴露规则。
- 核实部署审批、环境保护、并发控制和取消旧任务等高级行为。
- 迁移前保留原系统配置和回滚路径。

## 17. 最佳实践

1. **让 YAML 保持薄层**  
   把复杂构建逻辑放进版本化脚本，例如 `scripts/ci-test.sh`，这样本地和不同 CI 系统可以复用。

2. **固定运行环境**  
   明确 Node.js、包管理器和基础镜像范围，提交锁文件。

3. **失败要快，部署要稳**  
   先运行 lint 和单元测试，再构建和部署；生产部署增加审批、健康检查和回滚。

4. **最小化 Secret 暴露**  
   只在需要的 job 或 step 注入，并限制到受保护分支和专用 Runner。

5. **缓存只用于提速**  
   删除缓存后流水线仍应正确执行。

6. **产物只构建一次**  
   推荐“构建一次、逐环境发布同一产物”，减少环境间差异。

7. **审查第三方 Action**  
   阅读源码和权限需求，固定可信版本，特别关注会读取仓库、Token 或 Docker Socket 的 Action。

8. **为 Runner 做容量和安全隔离**  
   将普通 CI、外部贡献和生产部署分配到不同 Runner 池。

9. **控制并发部署**  
   避免同一环境被多个提交同时覆盖。具体并发控制语法需按当前平台能力配置和验证。

10. **保留可诊断信息**  
    保存测试报告、覆盖率、失败日志和部署版本号，但避免包含凭据或个人数据。

## 18. 总结与下一步

GitLab CI/CD 与 Gitea Actions 的目标一致，但编排思路不同：

- GitLab 侧重点是 `stages`、job、`script`、`rules` 和原生 artifacts/cache。
- Gitea Actions 侧重点是事件、job、step、`needs`、表达式和 Action。
- Gitea Actions 大体兼容 GitHub Actions，但不能把这种兼容理解为完全等价。

建议下一步：

1. 先为现有项目添加只包含 checkout、`npm ci` 和 `npm test` 的最小流水线。
2. 确认 Runner、标签和网络正常。
3. 再加入缓存、构建产物和服务容器。
4. 最后迁移部署，并在测试环境验证权限、审批、回滚与第三方 Action 兼容性。

对于生产系统，所有示例都应结合你当前部署的 GitLab/Gitea、Runner 配置、安全策略和官方文档进行验证后再使用。
