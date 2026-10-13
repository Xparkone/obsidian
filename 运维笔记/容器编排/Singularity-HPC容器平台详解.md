# Singularity / Apptainer HPC 容器平台详解

> Singularity(现官方名称为 **Apptainer**)是专为**高性能计算(HPC)与科研计算**设计的容器平台。它解决了 Docker 不适合超算/多租户集群的根本问题：**不安全的权限模型、重隔离的网络、以及臃肿的镜像分发方式**。一句话理解：**Docker 为微服务而生,Singularity 为「在共享超算上安全地跑科学计算」而生**。

---

## 目录

1. [Singularity 是什么](#1-singularity-是什么)
2. [为什么 HPC 需要它(设计动机)](#2-为什么-hpc-需要它设计动机)
3. [与 Docker 的对比](#3-与-docker-的对比)
4. [核心概念与架构](#4-核心概念与架构)
5. [安装](#5-安装)
6. [镜像获取与构建](#6-镜像获取与构建)
7. [运行容器](#7-运行容器)
8. [HPC 特性:GPU、MPI、调度器](#8-hpc-特性gpumpi调度器)
9. [安全机制](#9-安全机制)
10. [与 Kubernetes 的关系](#10-与-kubernetes-的关系)
11. [常用命令速查表](#11-常用命令速查表)
12. [常见问题与排查](#12-常见问题与排查)
13. [最佳实践与检查清单](#13-最佳实践与检查清单)
14. [总结与参考资料](#14-总结与参考资料)

---

## 1. Singularity 是什么

### 1.1 一句话定位

Singularity 是一个**容器运行时**:把应用及其依赖打包成一个**单一镜像文件(SIF)**,在任何安装了 Singularity/Apptainer 的 Linux 机器上,**以普通用户身份**直接运行,无需守护进程、无需 root。

### 1.2 历史与改名(容易混淆的地方)

| 时间 | 事件 |
|------|------|
| 2015-2016 | Gregory Kurtzer 在**劳伦斯伯克利国家实验室(LBNL)**创建 Singularity,初衷是让科学家能把计算环境打包后在不同超算中心复现 |
| 2018 | Kurtzer 创立 **Sylabs** 公司,提供商业化支持 |
| 2021 | 项目捐献给 **Linux 基金会**,正式更名为 **Apptainer**(1.0 于 2022 年发布) |
| 2021 至今 | Sylabs 从原仓库分叉出 **SingularityCE**(社区版),并提供商业版 **SingularityPRO**;4.x 起 SingularityCE 又改回叫 **Singularity** |

**现在市面上有两条同源分支,CLI 基本兼容:**

| 分支 | 维护方 | 命令 | 配置目录 | 环境变量前缀 |
|------|--------|------|----------|--------------|
| **Apptainer** | Linux 基金会 | `apptainer` | `/etc/apptainer/`、`~/.apptainer/` | `APPTAINER_` / `APPTAINERENV_` |
| **SingularityCE / SingularityPRO** | Sylabs | `singularity` | `/etc/singularity/`、`~/.singularity/` | `SINGULARITY_` / `SINGULARITYENV_` |

> 两家的 `.sif` 镜像格式和命令参数高度一致,**学会了 `apptainer` 就等于学会了 `singularity`**,镜像可以互相跑。本文命令以 `apptainer` 为例,换到 Sylabs 分支只需把命令换成 `singularity`。

---

## 2. 为什么 HPC 需要它(设计动机)

在超算中心 / GPU 集群上直接用 Docker 会遇到四个绕不开的问题,Singularity 的设计逐一对应:

### 2.1 多租户安全:普通用户不能被信任

- Docker 的 `docker` 组 ≈ root 等价权限(root daemon + 容器内默认 root),超算中心**不可能**给每个用户 docker 权限。
- Singularity **无 root 守护进程**,容器进程就是调用者本人的进程树:容器内的 UID = 宿主机 UID,逃不出自己原本的权限。管理员可以放心让所有用户直接运行。

### 2.2 直接使用宿主机资源

- HPC 作业要用 **InfiniBand / RDMA 网卡、Lustre/GPFS 并行文件系统、GPU**。Docker 默认的网络命名空间隔离和设备隔离让这些事变得非常麻烦。
- Singularity 默认**不隔离网络**(直接用宿主机网络栈)、默认挂载 `$HOME`、`$PWD`、`/tmp`、`/proc`、`/sys`、`/dev`,InfiniBand、共享存储开箱即用。

### 2.3 与批调度器(Slurm / PBS)天然集成

- 调度器要管理的是「进程」,而 Docker 把进程藏进 daemon,`srun`/`qsub` 无法直接管控容器内进程。
- Singularity 容器进程就是普通进程,出现在调度器的进程树里,`srun apptainer exec ...` 与跑一个普通二进制没有任何区别,资源限制(cgroup)、记账、信号传递全部正常。

### 2.4 单文件镜像:科研可复现

- Docker 镜像存在 registry/层缓存里,跨中心分发不便。
- Singularity 的镜像是**一个不可变的 `.sif` 文件**(SquashFS),`scp` 拷到任何机器就能跑,可以签名验证,天然满足科研「环境可复现」的诉求。

---

## 3. 与 Docker 的对比

| 对比维度 | Docker / OCI | Singularity / Apptainer |
|----------|--------------|-------------------------|
| 设计理念 | 微服务、长驻服务 | 科学计算、批量作业 |
| 守护进程 | 需要 root 权限的 dockerd | **无守护进程** |
| 容器内默认身份 | root(可降权但常被忽略) | **= 调用者本人**,无法提权 |
| 镜像格式 | OCI 分层镜像(仓库/本地 cache) | **单文件 SIF**(SquashFS),可签名 |
| 镜像写权限 | 分层写时复制 | 默认只读(`--writable-tmpfs` 可临时写) |
| 网络 | 独立 net namespace,端口映射 | **默认共享宿主机网络** |
| 文件系统访问 | 默认隔离,需 `-v` 挂载 | 默认挂 `$HOME`、`$PWD`、`/tmp` 等 |
| GPU 支持 | `--gpus all`(nvidia-container-toolkit) | `--nv` / `--rocm` |
| MPI | 基本不适用 | 原生支持(hybrid / bind 模型) |
| 调度器集成 | 需要额外封装(K8s) | 与 Slurm/PBS 零摩擦 |
| 服务化能力 | 强(重启策略、网络、编排) | `instance` 提供基础常驻能力,定位是补充 |
| 典型场景 | Web 服务、CI/CD、云原生 | 超算、生信、气象、AI 训练作业 |

> **实践结论**:两者不是替代关系。常见工作流是——**开发侧用 Docker 构建/分发镜像,HPC 侧用 `apptainer pull docker://...` 转成 SIF 跑作业**。

---

## 4. 核心概念与架构

### 4.1 SIF(Singularity Image Format)

- 单文件镜像格式,内容是一个**只读 SquashFS** 根文件系统 + 元数据头。
- 不可变 ⇒ 可哈希、可签名、可审计;跑不起来永远是「环境问题」而不是「镜像被改了」。
- 查看镜像内部结构:

```bash
apptainer sif list my.sif      # 列出 SIF 内的数据分区
apptainer sif dump 1 my.sif    # 查看定义头(def 头信息)
apptainer inspect -d my.sif    # 查看 labels/runscript 等元数据
```

### 4.2 sandbox(沙箱目录)

- `apptainer build --sandbox dir/ ...` 构建出来的是**目录**而不是单文件,**可写**,适合调试构建过程。
- 调好后 `apptainer build final.sif dir/` 打包成 SIF 固化。

### 4.3 运行时生命周期(与 Docker 的关键差异)

```
apptainer exec my.sif python app.py
        │
        ▼ (无 daemon)
starter 进程(setuid 或 user namespace)
        │ 挂载 squashfs、应用 bind、设置最小化 namespace
        ▼
容器内 PID 1 == python app.py(就是你的命令)
        │
        ▼ 命令退出
容器销毁,无残留
```

- 没有镜像层缓存、没有 `docker ps`;容器 = 一个进程组。
- 时间戳、退出码、stdout/stderr 全部直通宿主。

### 4.4 Definition 文件(`.def`)

构建配方的各 section:

| Section | 作用 |
|---------|------|
| `Header` | `Bootstrap: docker` + `From: ubuntu:22.04`,指定基底来源 |
| `%help` | `apptainer inspect --help` 显示的使用说明 |
| `%setup` | 在宿主机上执行的准备动作(拷贝文件进 `$SINGULARITY_ROOTFS`) |
| `%files` | 从宿主机拷文件进镜像:`src dest` |
| `%environment` | 容器运行时生效的环境变量(`export PATH=...`) |
| `%post` | **构建时**在容器内执行的命令(装软件、编译) |
| `%runscript` | `apptainer run` 时执行的默认命令 |
| `%startscript` | `apptainer instance start` 时执行的命令 |
| `%test` | 构建后验证(`apptainer test`) |
| `%labels` | 元数据键值对(作者、版本) |

---

## 5. 安装

### 5.1 RHEL / Rocky / Alma(EPEL)

```bash
sudo dnf install -y epel-release
sudo dnf install -y apptainer           # 用户命名空间模式
sudo dnf install -y apptainer-suid      # setuid 模式,功能更全(推荐)
```

### 5.2 Ubuntu / Debian

```bash
# 从 GitHub Releases 下载(版本以最新为准)
sudo apt install -y ./apptainer_1.*_amd64.deb ./apptainer-suid_1.*_amd64.deb
```

### 5.3 Sylabs SingularityCE(另一条分支)

从 Sylabs GitHub Releases 下载对应发行版包,或直接编译安装;装完后命令为 `singularity`。

### 5.4 源码安装(适用于无包环境)

依赖:**Go ≥ 1.20**、`libseccomp-dev`、`squashfs-tools`、`cryptsetup` 等。流程为 `./mconfig && make -C builddir && sudo make -C builddir install`,日常使用优先用发行版包。

### 5.5 macOS / Windows

- macOS:通过 **Lima** 虚拟机运行(`brew install apptainer`),LOS 桌面仅是客户端。
- Windows:经 **WSL2** 安装 Linux 发行版后按 Linux 方式安装。

### 5.6 装后关键文件

| 路径 | 作用 |
|------|------|
| `/etc/apptainer/apptainer.conf` | 全局配置:默认 bind、是否允许 setuid/`--fakeroot`、loop 设备等 |
| `/etc/apptainer/ecl.toml` | 执行控制列表(见 §9 安全) |
| `/etc/subuid` `/etc/subgid` | `--fakeroot` 所需的 UID 映射 |
| `~/.apptainer/cache/` | pull/build 缓存(可用 `APPTAINER_CACHEDIR` 改位置) |

---

## 6. 镜像获取与构建

### 6.1 拉取现成镜像

```bash
# Sylabs Cloud 官方库
apptainer pull alpine.sif library://alpine:latest

# Docker Hub(自动转换成 SIF,最常用)
apptainer pull docker://ubuntu:22.04

# 私有 registry / OCI 制品
apptainer pull docker://registry.example.com/team/app:v1
apptainer pull oras://registry.example.com/team/app-sif:v1

# Docker Hub 匿名拉取被限流时
apptainer remote login   # 或用 --docker-login 交互输入账号
```

> `pull docker://` 时 Singularity 会把 OCI 层展平重建为 SIF;大部分镜像可直接转换,个别依赖 systemd/守护进程语义的镜像需要改写启动方式。

### 6.2 编写 def 并构建

`python-app.def` 完整示例:

```singularity
Bootstrap: docker
From: ubuntu:22.04

%labels
    Author ops-team
    Version v1.0

%post
    export DEBIAN_FRONTEND=noninteractive
    apt-get update && apt-get install -y python3 python3-pip
    pip3 install numpy pandas
    apt-get clean && rm -rf /var/lib/apt/lists/*

%files
    ./app.py /opt/app.py

%environment
    export LANG=C.UTF-8
    export APP_HOME=/opt

%runscript
    echo "开始执行分析任务,参数:$@"
    exec python3 /opt/app.py "$@"

%test
    python3 --version
    python3 -c "import numpy; print('numpy ok')"

%help
    用法:apptainer run python-app.sif <输入文件>
```

构建:

```bash
# 方式一:有 root 权限
sudo apptainer build python-app.sif python-app.def

# 方式二:普通用户 + fakeroot(需要管理员先配置映射)
sudo apptainer config fakeroot --add zhangsan    # 管理员执行一次
apptainer build --fakeroot python-app.sif python-app.def

# 方式三:remote(用 Sylabs 云端构建,无需本机权限)
apptainer remote login                            # 获取 token 后登录
apptainer build --remote python-app.sif python-app.def
```

调试构建过程:

```bash
sudo apptainer build --sandbox debug-dir/ python-app.def
sudo apptainer shell --writable debug-dir/        # 进去手动调
sudo apptainer build python-app.sif debug-dir/    # 调好后固化为 SIF
```

---

## 7. 运行容器

### 7.1 三种基本入口

```bash
# run —— 执行 %runscript(单命令容器的主要用法)
apptainer run python-app.sif input.csv

# exec —— 执行任意命令(最常用)
apptainer exec python-app.sif python3 /opt/app.py --threads 8

# shell —— 交互式进入容器(调试)
apptainer shell python-app.sif
Apptainer> python3
```

### 7.2 instance:跑常驻服务(可选能力)

```bash
apptainer instance start nginx.sif web1    # 执行 %startscript 后台常驻
apptainer instance list                    # 查看实例
apptainer shell instance://web1            # 进入运行中的实例
apptainer instance stop web1               # 停止
```

> 适合「在计算节点上临时起一个服务」的场景;不要拿它当 systemd/K8s 的替代品。

### 7.3 挂载(bind mount)

```bash
# 宿主机 /data 挂到容器 /data(默认 $HOME、$PWD、/tmp 已自动挂载)
apptainer exec -B /data:/data my.sif ls /data

# 多个挂载、只读挂载
apptainer exec -B /data:/data:ro -B /scratch:/scratch my.sif cmd
```

### 7.4 环境与隔离控制

```bash
# 传环境变量(容器内可见 FOO=bar)
APPTAINERENV_FOO=bar apptainer exec my.sif env
apptainer exec --env FOO=bar,TZ=Asia/Shanghai my.sif env
apptainer exec --env-file ./env.list my.sif env

# 干净环境:不带入宿主机环境变量
apptainer exec --cleanenv my.sif env        # 简写 -e

# 最小化文件系统混入:不自动挂 HOME/tmp
apptainer exec --contain my.sif cmd
# 更严格:--containall(连 /dev、ipc 也隔离)
```

### 7.5 镜像默认只读,需要写怎么办

| 需求 | 做法 |
|------|------|
| 临时写一点日志/临时文件 | `--writable-tmpfs`(内存 overlay,退出即丢,常用) |
| 永久修改镜像 | 构建时改;或用 sandbox 目录 `--writable` 运行 |
| 作业数据读写 | **不要写进镜像**,把数据目录 `-B` 挂进来读写(正确姿势) |

---

## 8. HPC 特性:GPU、MPI、调度器

### 8.1 GPU

```bash
# NVIDIA:宿主机装好驱动 + nvidia-container-cli(libnvidia-container-tools)
apptainer exec --nv cuda-app.sif nvidia-smi

# AMD ROCm
apptainer exec --rocm rocm-app.sif rocm-smi
```

- `--nv` 会把宿主机的驱动库自动挂进容器,**容器 CUDA 版本 ≤ 宿主机驱动支持的版本**即可。
- 容器里不需要装 NVIDIA 驱动,只要 CUDA runtime。
- `--nvccli` 可强制使用 nvidia-container-cli 路径(新版默认行为)。

### 8.2 MPI

两种集成模型:

| 模型 | 做法 | 特点 |
|------|------|------|
| **Hybrid(推荐)** | 容器内装与宿主机**同系/ABI 兼容**的 MPI,外部起 `mpirun`,进程在容器里跑 | 镜像可移植,最常用 |
| **Bind** | 把宿主机 MPI 库 `-B` 挂进容器 | 镜像简单,但镜像-宿主机强耦合 |

Hybrid 示例:

```bash
# 宿主机与容器内均为 OpenMPI 4.x(ABI 兼容)
mpirun -np 8 apptainer exec mpi-app.sif /opt/mpi_hello
```

> 关键点:容器内、宿主机的 **MPI 实现与大版本要一致**(都是 OpenMPI 4.x,或都是 MPICH 3.x),否则进程间无法联手。

### 8.3 Slurm 集成

```bash
#!/bin/bash
#SBATCH -N 2 --ntasks-per-node=4 --gres=gpu:2

srun --mpi=pmix_v3 apptainer exec --nv train.sif \
    python /opt/train.py --epochs 100
```

- 容器进程直接挂在 `srun` 的进程树下,cgroup 限额、记账、信号全部生效。
- InfiniBand 无需任何配置:容器用宿主机网络,verbs 设备默认可见。

---

## 9. 安全机制

### 9.1 签名与验证(PGP)

```bash
apptainer key newpair              # 生成密钥对
apptainer key push <指纹>          # 上传到 keystore(可选)
apptainer sign python-app.sif      # 给镜像签名
apptainer verify python-app.sif    # 运行方校验来源与完整性
```

签名的 SIF 被篡改后无法通过校验——满足了「这个镜像确实是张三构建的且没被动过」。

### 9.2 加密镜像

```bash
apptainer build --encrypt --pem-path=pub.pem secret.sif app.def
apptainer run --pem-path=key.pem secret.sif
```

镜像内容静态加密,仅在运行时内存中解密,适用于**数据集/代码涉密**但必须共享存储的场景。

### 9.3 ECL(执行控制列表,管理员侧)

`/etc/apptainer/ecl.toml` 可配置:**只有指定签名者签名的镜像才允许在本集群运行**,并可按组授权。这是超算中心多租户策略的落点。

### 9.4 权限模型的的两句话总结

1. 普通用户模式下,容器里你是谁、宿主机上就是谁,**Singularity 不授予任何额外权限**;
2. setuid starter(`apptainer-suid`)只用于挂载 squashfs 等少量特权操作,攻击面远小于 root daemon。

---

## 10. 与 Kubernetes 的关系

- **SIF 不能直接作为 K8s 镜像**;K8s 生态要求 OCI 镜像。历史上曾有 Singularity-CRI,已停止维护。
- Apptainer 1.1+ 提供 **OCI 模式**(`apptainer run --oci docker://nginx`),底层调 OCI runtime,可运行 OCI bundle,用于对齐兼容性,但不改变主打场景。
- 典型分工:
  - **K8s/Docker**:在线服务、流水线、平台组件
  - **Singularity/Apptainer**:离线批作业、大模型训练、科学计算——也就是 Slurm 管的那摊
  - 交集是镜像:`docker build` → 推 registry → `apptainer pull docker://...` → 上超算跑

---

## 11. 常用命令速查表

| 命令 | 说明 |
|------|------|
| `apptainer pull x.sif docker://ubuntu:22.04` | 拉取并转换镜像 |
| `apptainer build x.sif x.def` | 从 def 构建(root/--fakeroot/--remote) |
| `apptainer run x.sif [args]` | 执行 %runscript |
| `apptainer exec x.sif cmd` | 执行任意命令(最常用) |
| `apptainer shell x.sif` | 交互进入容器 |
| `apptainer inspect [--runscript/-d] x.sif` | 查看镜像元数据 |
| `apptainer sif list/dump x.sif` | 查看 SIF 内部结构 |
| `apptainer instance start/list/stop` | 常驻实例管理 |
| `apptainer exec --nv x.sif cmd` | 启用 NVIDIA GPU |
| `apptainer exec -B /d:/d:ro x.sif cmd` | 绑定挂载(只读) |
| `apptainer exec --cleanenv x.sif cmd` | 干净环境 |
| `apptainer exec --writable-tmpfs x.sif cmd` | 临时可写层 |
| `apptainer exec --fakeroot x.sif cmd` | 容器内伪装 root(需映射) |
| `apptainer sign/verify x.sif` | 签名 / 校验 |
| `apptainer cache list/clean` | 缓存管理 |
| `apptainer remote login/list` | Sylabs 远程构建服务 |
| `apptainer config fakeroot --add <user>` | (管理员)开通 fakeroot |

---

## 12. 常见问题与排查

| 症状 | 原因与处理 |
|------|-----------|
| `container creation failed: mount ... permission denied` | 只装了 `apptainer` 未装 `apptainer-suid`,且内核未开用户命名空间;装 suid 包或确认 `kernel.unprivileged_userns_clone=1`(Debian 系) |
| `Failed to create user namespace` | RHEL 系检查 `user.max_user_namespaces` sysctl,调大如 `15000` |
| `--fakeroot` 报 mapping 不存在 | `/etc/subuid` / `/etc/subgid` 无该用户条目;管理员执行 `apptainer config fakeroot --add <user>` |
| fakeroot 下构建连不上网 | 走 slirp4netns;检查安装 `slirp4netns` 包,或换 root/remote 构建 |
| `FATAL: no space left on device` 构建失败 | 构建临时目录默认在 `$TMPDIR`,改 `APPTAINER_TMPDIR` 到大分区 |
| pull 后家目录被撑爆 | 缓存默认在 `~/.apptainer/cache`,设 `APPTAINER_CACHEDIR=/scratch/xxx` |
| Docker Hub 限流 `toomanyrequests` | `apptainer remote login` 或加 `--docker-login`;中转私有 registry |
| 容器内写文件报只读 | SIF 是只读的;数据挂 `-B`,临时写用 `--writable-tmpfs` |
| 容器里 home 里出现宿主机文件 | 默认挂载 `$HOME` 导致;用 `--contain` 或 `--no-home` |
| MPI 作业卡在启动/报错 PMI | 容器内外 MPI 实现/大版本不一致;统一为同一家同一主版本(Hybrid 模型) |
| `--nv` 提示 nvidia-container-cli 缺失 | 宿主机安装 `libnvidia-container-tools`,驱动本身也要装好 |
| 转换某些 Docker 镜像后启动异常 | 原镜像依赖 systemd/entrypoint 守护进程语义;把启动命令显式写进 %runscript |

---

## 13. 最佳实践与检查清单

### 13.1 构建侧

1. **优先复用 Docker 生态**:用 CI 构建并推 OCI 镜像,HPC 侧 `pull docker://` 转换,避免维护两套配方。
2. def 文件纳入 Git 管理,镜像产物与 def 一一对应(labels 里写 commit hash)。
3. 构建用 `--fakeroot`(普通用户)或 CI 里的 remote builder;不要在共享登录节点用 `sudo` 构建。
4. 生产镜像构建后**签名**,集群开启 ECL 校验。
5. 缓存目录 `APPTAINER_CACHEDIR`/`TMPDIR` 指向大容量文件系统(Lustre/NFS/数据盘),别用满家目录。

### 13.2 运行侧

1. 数据永远走 `-B` 挂载,**绝不写进镜像**;需要写临时文件用 `--writable-tmpfs`。
2. 跑作业加 `--cleanenv --contain` 提升可复现性;环境变量用 `--env/--env-file` 显式注入。
3. CUDA 容器版本不超过宿主机驱动支持上限;MPI 容器内外保持同实现同大版本。
4. 作业脚本里直接 `srun/mpirun apptainer exec ...`,不要套 `nohup`/`&` 之类的 shell 守护化技巧。

### 13.3 检查清单(镜像上超算前)

- [ ] 镜像可在目标机器 `apptainer run` 正常拉起
- [ ] `apptainer inspect -d` 元数据完整(作者/版本/来源)
- [ ] 已签名且 `verify` 通过(集群策略要求时)
- [ ] 数据目录间定好 bind 约定(路径、权限、读写模式)
- [ ] GPU / MPI 版本与宿主机兼容矩阵确认过
- [ ] 缓存/临时目录指向共享大文件系统

---

## 14. 总结与参考资料

### 14.1 总结

1. **Singularity = Apptainer = 为 HPC 设计的容器运行时**;SingularityCE 是 Sylabs 同源分支,镜像与命令互通。
2. 与 Docker 的本质差异:**无 root 守护进程、容器内身份 = 调用者、默认共享宿主网络与文件系统、单文件可签名 SIF 镜像**。
3. 核心工作流:`pull/build` 拿镜像 → `exec/run/shell` 跑作业 → `--nv`/MPI 上算力 → `srun` 交给调度器。
4. 它与 K8s/Docker 是**互补**而非竞争:服务归 Docker/K8s,批作业归 Singularity/Slurm。

### 14.2 参考资料

- Apptainer 官方文档:https://apptainer.org/docs/
- Apptainer GitHub:https://github.com/apptainer/apptainer
- Sylabs SingularityCE:https://sylabs.io/docs/
- 原始论文:*Singularity: Scientific containers for mobility of compute*(PLOS ONE, 2017)
