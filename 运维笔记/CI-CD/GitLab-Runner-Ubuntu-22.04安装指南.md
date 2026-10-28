# Ubuntu 22.04 安装 GitLab Runner

> 文档核对日期：2026-10-28  
> 适用范围：在 Ubuntu 22.04（代号 Jammy）上安装 GitLab 官方发布的 GitLab Runner。  
> 参考：[Install GitLab Runner using the official GitLab repositories](https://docs.gitlab.com/runner/install/linux-repository/)、[Install GitLab Runner manually on GNU/Linux](https://docs.gitlab.com/runner/install/linux-manually/)。  
> 验证边界：命令与下载地址核对自上述官方文档。本文没有在目标机器上执行安装。包版本、GPG 密钥和注册令牌以安装当时的官方页面和 GitLab 实例为准。

Kubernetes 里用 Helm 安装 Runner 的流程见 [[GitLab-ArgoCD-GitLab-Runner-GitOps完整部署流程]]。本文只覆盖 Ubuntu 主机上的软件包和二进制安装。

## 1. 文档概述

这份笔记解决「在 Ubuntu 22.04 上下载并安装 GitLab Runner」这件事。GitLab Runner 是安装在主机上的代理进程，负责向 GitLab 领取 CI Job 并在本机执行。

适合要在一台 Linux 构建机上安装 Runner 的运维人员。读完可以完成三件事：用官方 apt 源安装、直接下载 deb 安装、只下载二进制并注册成系统服务。

优先使用第 4 节的官方 apt 源。直接下载 deb 或二进制适合不能访问 `packages.gitlab.com` 软件源、或需要把安装包拷到隔离环境的场景。

## 2. 前置条件

- 操作系统是 Ubuntu 22.04。官方软件源的发行版代号是 Jammy，该版本在支持列表中。
- 具有 `sudo` 权限。
- 能访问 `packages.gitlab.com`，或能访问 `s3.dualstack.us-east-1.amazonaws.com` 上的发布桶。
- 先确认 CPU 架构。x86_64 使用 `amd64`，ARM 使用 `arm64`。

```bash
# 预期输出含 Ubuntu 22.04 与 jammy
lsb_release -a

# x86_64 对应 amd64；aarch64 对应 arm64
uname -m
```

使用 Docker executor 时，先在这台机器上安装 Docker。本文不包含 Docker 安装。

## 3. 核心概念

GitLab Runner 本体和 helper 镜像是两个包。

- `gitlab-runner`：领取并执行 Job 的程序，安装后默认以 `gitlab-runner` 系统用户运行服务。
- `gitlab-runner-helper-images`：Job 里克隆仓库、上传产物、处理缓存时使用的预置容器镜像。从 GitLab Runner 17.7.1 起，用 apt 固定旧版本时必须同时安装同版本的 helper 包，否则 apt 会报依赖无法满足。
- 二进制安装不带 helper 镜像。Docker executor 在缺少本地 helper 镜像时会在执行 Job 时自动下载。

`latest` 不是一个固定版本，它指向当前稳定发布。生产机器应把 URL 或 apt 版本号换成明确版本。版本目录形如 `v18.4.0`，apt 包版本形如 `18.4.0-1`，两者写法不同。

## 4. 实现步骤

### 4.1 用官方 apt 源安装

这是 Ubuntu 22.04 的默认方式。软件源配置脚本会写入 apt 源并导入仓库元数据签名密钥。先把脚本下载到本地检查，再执行。

```bash
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" -o script.deb.sh
less script.deb.sh
sudo bash script.deb.sh
sudo apt-get update
sudo apt-get install gitlab-runner
```

做什么：添加 GitLab Runner 的 apt 源并安装当前稳定版。  
为什么：apt 会处理依赖、服务单元和后续升级。  
预期结果：`gitlab-runner --version` 打印版本号，`systemctl status gitlab-runner` 显示服务处于 active。

安装过程中，包脚本可能清理本机未使用的 Docker 镜像和容器。要跳过这次清理：

```bash
sudo apt-get update
NO_DOCKER_PRUNE=1 sudo apt-get install gitlab-runner
```

### 4.2 用 apt 固定版本

先列出仓库里实际存在的版本，再把下面的版本号换成 `apt-cache madison` 输出中的那一列。从 17.7.1 起，`gitlab-runner` 和 `gitlab-runner-helper-images` 必须是同一版本。

```bash
apt-cache madison gitlab-runner
sudo apt-get install gitlab-runner=17.7.1-1 gitlab-runner-helper-images=17.7.1-1
```

只安装 `gitlab-runner=17.7.1-1`、不安装同版本 helper 包时，apt 会报 `Depends: gitlab-runner-helper-images` 无法满足。

### 4.3 直接下载 deb

隔离环境或不能添加 apt 源时，从发布桶下载 deb。`${arch}` 换成 `amd64` 或 `arm64`。helper 包和 Runner 包一起安装。

```bash
# 查看该版本目录下的真实文件名
# https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/latest/index.html

curl -LJO "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/latest/deb/gitlab-runner-helper-images.deb"
curl -LJO "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/latest/deb/gitlab-runner_amd64.deb"
sudo dpkg -i gitlab-runner-helper-images.deb gitlab-runner_amd64.deb
```

固定版本时，把 URL 中的 `latest` 换成带 `v` 的版本目录，例如 `v17.10.0`：

```bash
curl -LJO "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/v17.10.0/deb/gitlab-runner-helper-images.deb"
curl -LJO "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/v17.10.0/deb/gitlab-runner_amd64.deb"
sudo dpkg -i gitlab-runner-helper-images.deb gitlab-runner_amd64.deb
```

`v17.10.0` 只是路径写法示例。下载前打开对应版本的 `index.html`，确认文件名存在。

### 4.4 只下载二进制

二进制方式不创建 apt 记录。x86_64 的 Ubuntu 22.04 使用下面的 `linux-amd64` 文件。

```bash
sudo curl -L --output /usr/local/bin/gitlab-runner \
  "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/latest/binaries/gitlab-runner-linux-amd64"
sudo chmod +x /usr/local/bin/gitlab-runner
sudo useradd --comment 'GitLab Runner' --create-home gitlab-runner --shell /bin/bash
sudo gitlab-runner install --user=gitlab-runner --working-directory=/home/gitlab-runner
sudo gitlab-runner start
```

ARM 机器把二进制名换成 `gitlab-runner-linux-arm64`。`/usr/local/bin` 必须在 root 的 `PATH` 中，否则服务会报 `command not found`。

升级二进制时先停服务，替换文件，再启动：

```bash
sudo gitlab-runner stop
sudo curl -L --output /usr/local/bin/gitlab-runner \
  "https://s3.dualstack.us-east-1.amazonaws.com/gitlab-runner-downloads/latest/binaries/gitlab-runner-linux-amd64"
sudo chmod +x /usr/local/bin/gitlab-runner
sudo gitlab-runner start
```

## 5. 完整示例

下面是一台 x86_64 Ubuntu 22.04 上的推荐安装序列。脚本下载后应先阅读，再执行。

```bash
lsb_release -cs          # 预期：jammy
uname -m                 # 预期：x86_64

curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" -o script.deb.sh
less script.deb.sh
sudo bash script.deb.sh

sudo apt-get update
sudo apt-get install gitlab-runner

gitlab-runner --version
systemctl status gitlab-runner --no-pager
```

安装完成只说明本机进程在运行。要让它执行项目流水线，还需要在 GitLab 里创建 Runner，并用实例给出的 authentication token 注册。注册命令和 Kubernetes 部署见 [[GitLab-ArgoCD-GitLab-Runner-GitOps完整部署流程]]。

## 6. 常见问题与排查

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `apt-get install gitlab-runner=版本` 报 helper 依赖无法满足 | 只钉住了 Runner 包，helper 包仍是别的版本 | 同一条命令安装相同版本的 `gitlab-runner` 和 `gitlab-runner-helper-images` |
| `dpkg -i` 报依赖缺失 | 直接装 deb 时系统缺少包依赖 | 执行 `sudo apt-get install -f`，或改用第 4.1 节的 apt 源 |
| 服务报 `command not found` | 二进制不在 root 的 `PATH` | 确认文件在 `/usr/local/bin/gitlab-runner` 且具有执行权限 |
| Job 失败并出现 `No such file or directory` | 旧的 `gitlab-runner` 家目录带有 skel 生成的 shell 配置 | 删除 `/home/gitlab-runner/.profile`、`.bashrc`、`.bash_logout` 后重试 |
| 下载 `latest` 后版本与预期不符 | `latest` 指向当前稳定版，会变化 | 把 URL 中的 `latest` 换成 `v<版本号>`，或用 apt 钉住 `x.y.z-1` |

校验 deb 包签名时，安装 `dpkg-sig`，导入 Runner 包签名公钥后再执行 `dpkg-sig --verify`。核对文档时，官方页面列出的包签名密钥指纹为 `931D A69C FA3A FEBB C97D AA8C 6C57 C29C 6BA7 5A4E`，页面上的到期日是 2026-04-28。这个日期已经过去，安装前到 [官方仓库安装文档](https://docs.gitlab.com/runner/install/linux-repository/) 核对当前密钥，不要沿用过期公钥。

## 7. 注意事项与最佳实践

- Ubuntu 22.04 优先使用 apt 源。deb 和二进制是软件源不可用时的安装方式。
- 生产环境固定版本。apt 版本号不带前缀 `v`，发布桶目录带前缀 `v`。
- 从 17.7.1 起，apt 固定版本必须同时安装同版本 `gitlab-runner-helper-images`。
- 安装或升级 apt 包时，默认可能清理未使用的 Docker 镜像。构建机上有需要保留的本地镜像时，使用 `NO_DOCKER_PRUNE=1`。
- 不要把 `curl ... | sudo bash` 当作唯一入口。先把 `script.deb.sh` 保存到本地并阅读。
- Runner 安装完成还不等于 CI 可用。下一步是注册到具体的 GitLab 实例，并按 Job 的 `tags` 打上对应标签。

## 8. 总结

Ubuntu 22.04 在 GitLab Runner 官方软件源的支持范围内，默认用 `script.deb.sh` 添加源后执行 `apt-get install gitlab-runner`。需要离线或固定文件时，从发布桶同时下载 `gitlab-runner-helper-images.deb` 和 `gitlab-runner_amd64.deb`。只需要可执行文件时，下载 `gitlab-runner-linux-amd64` 并安装成系统服务。

装好后执行 `gitlab-runner --version` 和 `systemctl status gitlab-runner`。确认版本后，再注册到 GitLab。
