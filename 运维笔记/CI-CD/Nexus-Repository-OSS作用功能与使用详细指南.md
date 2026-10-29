# Nexus Repository OSS 作用、功能与使用详细指南

> 适用对象：需要使用 Nexus 保存依赖、发布构建产物、管理 Docker 镜像或接入 Jenkins 的开发、测试和运维人员。
> 截图基线：Sonatype Nexus Repository OSS 3.73.0-12。不同版本、Edition 和 UI 可能存在菜单、仓库格式和功能差异。
> 验证边界：本文是通用使用教程。示例中的域名、端口、仓库名称和账号均为占位值，未连接实际 Nexus 实例执行。

## 1. 先理解 Nexus 是什么

Nexus Repository 是一个制品仓库管理服务。它保存软件开发过程中产生或使用的组件，例如：

- Java 的 `.jar`、`.war`、`.pom`
- Python 的 `.whl`、`.tar.gz`
- Go 的模块或构建二进制文件
- C/C++ 的库、头文件、安装包和压缩包
- Docker/OCI 镜像
- Helm Chart、npm 包、NuGet 包和通用文件

Nexus 的主要价值是把依赖和构建产物集中管理，提供统一的下载地址、权限控制、版本管理、缓存、审计和清理能力。

它不负责：

- 编写源代码
- 代替 Git 仓库
- 代替 Python、GCC、Clang、JDK 等编译器
- 代替 Jenkins、GitLab CI 等流水线平台
- 代替 Kubernetes、Docker Compose 等运行平台

在 CI/CD 中通常采用下面的关系：

```text
开发者提交代码
      ↓
Jenkins 拉取代码并构建
      ↓
执行测试和安全扫描
      ↓
生成 JAR、Python 包、二进制文件或镜像
      ↓
上传到 Nexus
      ↓
部署系统下载固定版本
      ↓
发布到测试或生产环境
```

Nexus 官方将仓库分为 Hosted、Proxy 和 Group 三种类型，并按 Maven、PyPI、Docker、Go、Raw 等格式提供不同的客户端访问方式。[Repository Management](https://help.sonatype.com/en/repository-management.html)

## 2. 核心概念

### 2.1 Component、Asset、Repository 和 Blob Store

| 概念 | 含义 |
|---|---|
| Component | 用户看到的一个软件组件或版本，例如 `demo-1.2.0.jar` |
| Asset | Component 实际包含的文件，例如 JAR、POM、元数据和校验文件 |
| Repository | 对外提供访问的仓库，例如 `maven-public` |
| Blob Store | 实际保存文件内容的存储位置 |
| Format | 仓库使用的协议格式，例如 Maven2、PyPI、Docker、Raw |
| Endpoint | 用户访问仓库的 URL |

例如一个 Maven 包可能包含：

```text
Component: com.example:payment-service:1.4.0
├── payment-service-1.4.0.jar
├── payment-service-1.4.0.pom
└── maven-metadata.xml
```

Repository 保存元数据和访问规则，Blob Store 保存实际文件内容。删除 Repository 配置或 Blob Store 数据前必须先确认备份和恢复方案。

### 2.2 Hosted、Proxy 和 Group

| 类型 | 作用 | 典型例子 |
|---|---|---|
| Hosted | 保存公司自己发布的制品 | `maven-releases`、`pypi-hosted` |
| Proxy | 代理并缓存远程公共仓库 | `maven-central`、`pypi-proxy` |
| Group | 聚合多个仓库，提供一个统一 URL | `maven-public`、`pypi-group` |

Hosted 的正式版本建议关闭 redeploy，避免同一个版本被覆盖。

Proxy 会先检查本地缓存，未命中时从远程仓库下载并保存。它能减少重复下载、统一出网入口，但不等于永久镜像，缓存有效期和远端状态仍会影响请求。

Group 例如：

```text
maven-public
├── maven-releases
├── maven-snapshots
└── maven-central
```

开发者只配置：

```text
https://nexus.example.com/repository/maven-public/
```

Group 成员顺序会影响查找顺序，通常把内部 Hosted 仓库放在 Proxy 仓库之前。[Repository Types](https://help.sonatype.com/en/repository-types.html)

### 2.3 用户、角色和权限

Nexus 使用基于角色的访问控制：

```text
用户 / 服务账号
      ↓
角色
      ↓
权限
      ↓
指定仓库、操作和路径
```

常见权限包括 Browse、Read、Add、Edit、Delete、Repository Administration 和 Task。

建议区分：

| 账号 | 用途 | 典型权限 |
|---|---|---|
| 管理员 | 初始化和运维 | 管理权限，日常少用 |
| 开发者 | 下载依赖 | Group 仓库 Browse/Read |
| Jenkins 发布账号 | 上传构建产物 | 指定 Hosted 仓库 Add/Read |
| 部署账号 | 下载正式制品 | Release 仓库 Read |
| 审计账号 | 查看和导出 | 只读权限 |

Sonatype 建议使用最小权限、专用服务账号和外部身份系统；匿名访问应按实际需要限制，不能默认允许匿名上传。[Users](https://help.sonatype.com/en/users.html) [Access Control](https://help.sonatype.com/en/access-control.html)

## 3. 第一次登录后的初始化

### 3.1 登录和初始密码

浏览器访问：

```text
https://nexus.example.com
```

截图中的页面右上角有 `Sign in`。首次安装通常使用数据目录中的 `admin.password`：

```bash
docker exec <nexus-container> cat /nexus-data/admin.password
```

首次登录后：

1. 修改 admin 密码。
2. 确认服务域名和 HTTPS。
3. 创建普通管理员或运维账号。
4. 创建 Jenkins 和部署专用账号。
5. 检查匿名访问是否符合要求。
6. 创建或确认 Blob Store。
7. 创建 Hosted、Proxy 和 Group 仓库。
8. 保存每个仓库的访问 URL。
9. 配置备份、清理策略和磁盘监控。

### 3.2 常用管理菜单

Classic UI 中通常可以从设置菜单进入：

```text
Settings → Repository → Repositories
Settings → Security → Users
Settings → Security → Roles
Settings → Repository → Blob Stores
Settings → Repository → Cleanup Policies
Settings → System → Tasks
```

不同版本可能显示为 Administration、Repository 或 Settings，实际以当前页面为准。

### 3.3 Blob Store 规划

学习环境可以使用默认 Blob Store。生产环境可以按数据类型规划：

```text
blobstore-maven
blobstore-pypi
blobstore-docker
blobstore-raw
```

规划时考虑容量、增长速度、备份方式、清理策略、镜像与软件包隔离、监控和配额。

## 4. 创建常用仓库

创建入口通常是：

```text
Settings → Repository → Repositories → Create repository
```

### 4.1 Maven

建议创建：

| 名称 | 类型 | 用途 |
|---|---|---|
| maven-releases | maven2 hosted | 正式版本 |
| maven-snapshots | maven2 hosted | 开发快照 |
| maven-central | maven2 proxy | Maven Central 缓存 |
| maven-public | maven2 group | 统一下载入口 |

`maven-releases` 重点配置：

- Version policy：Release
- Layout policy：Strict
- Deployment policy：Disable redeploy
- Blob store：对应的 Blob Store

`maven-snapshots` 使用 Snapshot 策略。Group 成员建议：

```text
maven-releases
maven-snapshots
maven-central
```

官方 Maven 文档建议通过 Group 暴露多个 Maven 仓库，并用一个 URL 配置客户端。[Maven Repositories](https://help.sonatype.com/en/maven-repositories.html)

### 4.2 PyPI

建议创建：

| 名称 | 类型 | 用途 |
|---|---|---|
| pypi-hosted | pypi hosted | 公司自己的 Python 包 |
| pypi-proxy | pypi proxy | `https://pypi.org/` |
| pypi-group | pypi group | 统一下载入口 |

发布使用 `pypi-hosted`，安装依赖通常使用 `pypi-group`。pip 的 Simple API 地址通常为：

```text
https://nexus.example.com/repository/pypi-group/simple
```

### 4.3 Docker/OCI

建议创建：

```text
docker-hosted  # 内部镜像
docker-proxy   # Docker Hub 代理
docker-group   # 统一拉取入口
```

截图版本为 3.73.0-12。官方文档说明 Path-Based Routing 是 3.83.0 引入的能力，因此 3.73 环境不能直接套用新版本路径路由示例。旧版本应根据当前 UI 使用 Docker Connector、子域名或外部反向代理。

生产环境建议通过反向代理提供 HTTPS，并限制直接暴露 Nexus 管理端口。[Docker Registry](https://help.sonatype.com/en/docker-registry.html)

### 4.4 Raw

Raw Hosted 适合保存没有专用格式的制品：

- Linux 安装包
- C/C++ 编译产物
- Go 二进制文件
- 压缩包
- 配置模板
- SBOM、校验和和构建元数据

推荐目录：

```text
raw-releases/
└── app-a/
    └── 1.0.0/
        ├── app-a-linux-amd64.tar.gz
        ├── app-a.sha256
        └── sbom.spdx.json
```

Go 可以按目标版本使用 Go 仓库或 Raw Hosted。C/C++ 如果没有合适的原生格式，可以使用 Raw Hosted，并记录编译器、架构、ABI、C++ 标准、Git commit、构建号和 SHA256。

## 5. 客户端使用方式

### 5.1 Maven

使用 Group 地址下载依赖：

```xml
<repositories>
  <repository>
    <id>nexus-public</id>
    <url>https://nexus.example.com/repository/maven-public/</url>
  </repository>
</repositories>
```

发布地址：

```xml
<distributionManagement>
  <repository>
    <id>nexus-releases</id>
    <url>https://nexus.example.com/repository/maven-releases/</url>
  </repository>
  <snapshotRepository>
    <id>nexus-snapshots</id>
    <url>https://nexus.example.com/repository/maven-snapshots/</url>
  </snapshotRepository>
</distributionManagement>
```

在 `settings.xml` 中配置与 `id` 对应的认证信息，然后执行：

```bash
./mvnw test
./mvnw deploy
```

不要把长期密码提交到 Git，应使用受保护的 Maven settings、User Token 或 CI 凭据。

### 5.2 Python

下载依赖：

```bash
python -m pip install \
  --index-url https://nexus.example.com/repository/pypi-group/simple \
  requests
```

构建和发布：

```bash
python -m build
twine upload \
  --repository-url https://nexus.example.com/repository/pypi-hosted/ \
  dist/*
```

也可以通过 `pip.conf`、`pip.ini`、`PIP_INDEX_URL`、Poetry 或 uv 配置统一接入。官方文档建议使用 HTTPS，并将发布目标指向 PyPI Hosted 仓库。[Configure PyPI with Nexus](https://help.sonatype.com/en/configure-pypi-with-nexus.html)

### 5.3 Docker

以旧版本常用的端口 Connector 为例：

```bash
docker login nexus.example.com:18082

docker tag app:1.0.0 \
  nexus.example.com:18082/team/app:1.0.0

docker push nexus.example.com:18082/team/app:1.0.0
docker pull nexus.example.com:18082/team/app:1.0.0
```

实际端口必须以 Docker Hosted 或 Group 仓库配置为准。镜像发布建议同时记录 Git commit、构建号、digest、SBOM 和扫描结果。

### 5.4 Raw 文件

上传：

```bash
curl -u "$NEXUS_USER:$NEXUS_PASS" \
  --fail \
  --upload-file app-linux-amd64.tar.gz \
  https://nexus.example.com/repository/raw-releases/app/1.0.0/app-linux-amd64.tar.gz
```

下载：

```bash
curl -u "$NEXUS_USER:$NEXUS_PASS" \
  --fail \
  -o app-linux-amd64.tar.gz \
  https://nexus.example.com/repository/raw-releases/app/1.0.0/app-linux-amd64.tar.gz
```

不要把密码写入 Shell 历史、脚本仓库或 Jenkinsfile。

## 6. Jenkins 集成

### 6.1 创建 Jenkins 凭据

在 Jenkins 中创建：

```text
Kind: Username with password
ID: nexus-publish
Username: Jenkins 发布账号
Password: 密码或 User Token
```

建议按用途分开：

```text
nexus-maven-publish
nexus-pypi-publish
nexus-docker-publish
nexus-raw-publish
```

### 6.2 Maven 发布

```groovy
pipeline {
    agent any

    options {
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Test') {
            steps {
                sh './mvnw test'
            }
        }

        stage('Publish') {
            when {
                branch 'main'
            }
            steps {
                withCredentials([
                    usernamePassword(
                        credentialsId: 'nexus-maven-publish',
                        usernameVariable: 'NEXUS_USER',
                        passwordVariable: 'NEXUS_PASS'
                    )
                ]) {
                    sh '''
                        set +x
                        ./mvnw deploy
                    '''
                }
            }
        }
    }

    post {
        always {
            junit allowEmptyResults: true,
                  testResults: 'target/surefire-reports/*.xml'
        }
    }
}
```

实际 Maven 认证通常放在受保护的 `settings.xml` 中，项目应按自身 POM、服务器 ID 和 Maven 配置调整。

### 6.3 Python 发布

```groovy
stage('Publish Python Package') {
    when {
        branch 'main'
    }
    steps {
        withCredentials([
            usernamePassword(
                credentialsId: 'nexus-pypi-publish',
                usernameVariable: 'TWINE_USERNAME',
                passwordVariable: 'TWINE_PASSWORD'
            )
        ]) {
            sh '''
                set +x
                python -m build
                python -m twine upload \
                  --repository-url https://nexus.example.com/repository/pypi-hosted/ \
                  dist/*
            '''
        }
    }
}
```

### 6.4 Raw 文件发布

```groovy
stage('Publish Raw Artifact') {
    steps {
        withCredentials([
            usernamePassword(
                credentialsId: 'nexus-raw-publish',
                usernameVariable: 'NEXUS_USER',
                passwordVariable: 'NEXUS_PASS'
            )
        ]) {
            sh '''
                set +x
                sha256sum dist/app-linux-amd64.tar.gz > dist/app-linux-amd64.tar.gz.sha256

                curl --fail \
                  -u "$NEXUS_USER:$NEXUS_PASS" \
                  --upload-file dist/app-linux-amd64.tar.gz \
                  "https://nexus.example.com/repository/raw-releases/app/BUILD_TAG/app-linux-amd64.tar.gz"
            '''
        }
    }
}
```

上例中的 `BUILD_TAG` 是 Jenkins 构建标识占位符，实际使用时应由 Jenkins 环境变量或受控版本变量替换。

### 6.5 推荐流水线

```text
Checkout
→ Prepare Toolchain
→ 从 Nexus 获取依赖
→ Lint / SAST / Dependency Scan
→ Build
→ Unit Test / Integration Test
→ Package
→ Publish to Nexus
→ Deploy
→ Smoke Test
→ Notify
```

Jenkins 只在构建和测试成功、分支或标签满足发布条件时上传正式制品。部署阶段下载同一个不可变版本，避免重新构建导致测试版本和上线版本不一致。

## 7. 版本、命名和制品管理规则

推荐命名：

```text
app-1.4.0-linux-amd64.tar.gz
app-1.4.0+git.a1b2c3d.whl
payment-service-1.4.0.jar
app-1.4.0.sha256
sbom-1.4.0.spdx.json
```

每个正式制品建议关联：

- 业务版本
- Git commit SHA
- Jenkins build number
- 构建时间
- 构建镜像或工具链版本
- 目标操作系统和 CPU 架构
- SHA256
- 测试报告
- 安全扫描结果
- SBOM

建议：

- Release 版本不可覆盖。
- Snapshot 版本只用于开发和测试。
- 生产部署固定到版本或镜像 digest。
- 制品构建一次，多环境晋级。
- 不要在生产阶段重新编译。
- 不要把 Jenkins 工作区当作长期制品存储。
- 不要把 `latest` 当作生产发布版本。

## 8. 权限设计示例

### 8.1 开发者只读

```text
developer-read
├── maven-public: browse, read
├── pypi-group: browse, read
├── docker-group: browse, read
└── raw-releases: browse, read
```

### 8.2 Jenkins 发布

```text
jenkins-publisher
├── maven-releases: browse, read, add
├── maven-snapshots: browse, read, add, edit
├── pypi-hosted: browse, read, add
├── docker-hosted: browse, read, add
└── raw-releases: browse, read, add
```

### 8.3 部署账号

```text
deployer
├── maven-releases: read
├── docker-hosted: read
└── raw-releases: read
```

部署账号通常不应拥有 Add、Edit 或 Delete 权限。多个团队共用仓库时，可以使用 Content Selector 按项目名称、命名空间或路径限制上传范围。

## 9. 运维管理

### 9.1 备份和恢复

需要保护：

- Nexus 使用的数据库
- Blob Store
- 数据目录中的配置、节点标识和密钥材料
- 外部对象存储或文件系统中的相关数据

数据库和 Blob Store 应尽量在接近的时间点备份，减少元数据和文件内容不一致。官方文档要求根据数据库和存储类型选择对应备份方案，PostgreSQL 场景使用 PostgreSQL 原生工具或基础设施备份能力。[Backup and Restore](https://help.sonatype.com/en/backup-and-restore.html)

恢复演练：

```text
备份
→ 创建隔离恢复环境
→ 恢复数据库和 Blob Store
→ 登录 Nexus
→ 下载 Maven、Python、Docker 和 Raw 制品
→ 校验 SHA256
```

### 9.2 清理策略

长期运行的 Proxy、Snapshot 和 Docker 仓库会持续增长。可以在：

```text
Settings → Repository → Cleanup Policies
```

创建规则，关联仓库并执行清理任务。

典型规则：

- 只保留最近 30 天的 Snapshot
- 只保留最近 N 个开发版本
- 删除长时间未下载的代理缓存
- 清理旧 Docker tag 和未引用层
- 正式 Release 不按短周期自动删除

清理通常包含软删除和 Blob Store 压缩两个阶段。执行前先预览结果，并在业务低峰期运行。[Cleanup Policies](https://help.sonatype.com/en/cleanup-policies.html)

### 9.3 HTTPS 和访问边界

建议：

- 通过反向代理或 Ingress 提供 HTTPS
- 管理端口只对运维网络开放
- 禁止匿名上传
- Jenkins、部署系统使用专用账号
- 优先使用 User Token 或外部身份系统
- 不在命令行、Git、日志中暴露密码
- 对 Docker、PyPI、Maven 客户端配置证书信任
- 记录登录、权限和制品变更事件

### 9.4 监控指标

建议监控：

- HTTP 请求错误率和延迟
- 进程和 JVM 内存
- CPU 和磁盘使用率
- Blob Store 容量
- 数据库连接和错误
- 任务执行失败
- Proxy 远程仓库连接失败
- Docker 上传失败
- 401、403、404、409 响应比例

## 10. 常见问题排查

| 现象 | 常见原因 | 检查方向 |
|---|---|---|
| 401 Unauthorized | 未登录、账号密码错误、Token 失效 | 检查认证信息和 User Token |
| 403 Forbidden | 角色缺少仓库权限 | 检查 Browse、Read、Add、Delete 权限 |
| 404 Not Found | URL、仓库名或版本错误 | 先在 Browse 中确认路径 |
| 409 Conflict | 禁止重复发布同一版本 | 修改版本或调整部署策略 |
| Maven 无法下载依赖 | Group 未包含目标成员、Proxy 远程地址错误 | 检查 Group 成员和 Proxy 配置 |
| pip 找不到包 | 缺少 `/simple`、仓库地址错误 | 检查 PyPI URL 和仓库类型 |
| Docker push 失败 | Connector、TLS、反向代理或镜像路径错误 | 检查 Registry 路由和证书 |
| 构建突然变慢 | Proxy 未命中、远程源慢、缓存失效 | 检查 Nexus 日志和远程仓库 |
| 磁盘持续增长 | Snapshot、Docker 或代理缓存未清理 | 检查 Blob Store 和 Cleanup Task |
| 页面能打开但客户端失败 | 管理端口可达，仓库端点未正确暴露 | 分别测试具体仓库 URL |

排查时保留：

```text
请求 URL
HTTP 状态码
客户端完整错误
Nexus 请求日志
Jenkins 构建号
仓库名称
组件坐标或镜像 digest
账号对应角色
```

## 11. 最小验收流程

### 服务和仓库

```bash
curl -I https://nexus.example.com
```

确认 HTTPS、证书和反向代理正常，并检查 Hosted、Proxy、Group、Blob Store 配置。

### Java

```bash
./mvnw test
./mvnw deploy
```

确认 Jenkins 发布账号可以上传，开发者账号可以从 Group 下载，部署账号无法上传。

### Python

```bash
python -m build
twine upload --repository-url <pypi-hosted-url> dist/*
pip install --index-url <pypi-group-simple-url> <package>
```

### Docker

```bash
docker login <registry>
docker push <registry>/<namespace>/<image>:<version>
docker pull <registry>/<namespace>/<image>:<version>
```

### 恢复和清理

- 创建测试备份。
- 在隔离环境恢复。
- 下载已恢复制品并校验 SHA256。
- 预览清理策略。
- 确认不会删除正式 Release。
- 检查任务执行结果和磁盘变化。

## 12. 与 Jenkins、Harbor 和 Git 的分工

```text
Git / GitLab
  保存源代码、分支、Tag 和代码评审

Jenkins
  编排构建、测试、扫描、打包、上传和部署

Nexus
  保存 Maven、PyPI、Raw 等软件包和依赖缓存

Harbor
  主要保存 Docker/OCI 镜像并进行镜像治理

Kubernetes / Argo CD
  运行或发布应用
```

一个常见生产流程：

```text
Git Tag
  ↓
Jenkins 构建并测试
  ↓
Jenkins 上传 JAR / Python 包 / 二进制到 Nexus
  ↓
Jenkins 构建镜像并推送 Harbor
  ↓
部署系统引用固定版本或 digest
  ↓
Kubernetes 发布
```

## 13. 使用边界和版本注意事项

- 本文按截图中的 Nexus Repository OSS 3.73.0-12 作为界面参考。
- Nexus 版本升级后，菜单名称、Docker 路由、数据库、清理策略和安全能力可能变化。
- OSS、Pro、Pro+ 和 Cloud 的功能范围可能不同。
- Docker Path-Based Routing 等新能力不能直接套用到 3.73 版本。
- 生产部署前应以目标版本官方文档、发行说明和兼容矩阵为准。
- 本文示例没有宣称真实 Nexus、Jenkins、Maven、PyPI 或 Docker 环境已经连通。

## 14. 官方参考资料

- [Repository Management](https://help.sonatype.com/en/repository-management.html)
- [Repository Types](https://help.sonatype.com/en/repository-types.html)
- [Maven Repositories](https://help.sonatype.com/en/maven-repositories.html)
- [Configure PyPI with Nexus](https://help.sonatype.com/en/configure-pypi-with-nexus.html)
- [Docker Registry](https://help.sonatype.com/en/docker-registry.html)
- [Users](https://help.sonatype.com/en/users.html)
- [Roles](https://help.sonatype.com/en/roles.html)
- [Privileges](https://help.sonatype.com/en/privileges.html)
- [Backup and Restore](https://help.sonatype.com/en/backup-and-restore.html)
- [Cleanup Policies](https://help.sonatype.com/en/cleanup-policies.html)
- [Securing Nexus Repository](https://help.sonatype.com/en/securing-nexus-repository-manager.html)
