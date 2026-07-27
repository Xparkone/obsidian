# AWS ParallelCluster (pcluster) 常用命令参考

> 最后更新：2026-06-16

---

## 一、安装与版本

```bash
# 安装 pcluster CLI（推荐 v3）
pip install aws-parallelcluster

# 查看版本
pcluster version
```

---

## 二、集群管理

### 创建集群

```bash
pcluster create-cluster --cluster-name <名称> --cluster-configuration <配置文件.yaml>
```

### 查看集群

```bash
# 列出所有集群
pcluster list-clusters

# 查看集群状态
pcluster list-clusters --region <区域> --status CREATE_COMPLETE

# 查看单个集群详情
pcluster describe-cluster --cluster-name <名称>

# 查看集群实例列表
pcluster describe-cluster-instances --cluster-name <名称>
```

### 更新集群

```bash
pcluster update-cluster --cluster-name <名称> --cluster-configuration <新配置.yaml>
```

### 删除集群

```bash
pcluster delete-cluster --cluster-name <名称>

# 删除集群并保留 EBS 卷
pcluster delete-cluster --cluster-name <名称> --keep-ebs-volumes
```

---

## 三、配置文件管理

### 验证配置

```bash
# 验证配置文件语法
pcluster validate-cluster-config --cluster-configuration <配置文件.yaml>

# 试运行（dryrun），检查资源是否足够
pcluster create-cluster --cluster-name <名称> --cluster-configuration <配置.yaml> --dryrun true
```

### 导出配置

```bash
# 导出已有集群的配置
pcluster describe-cluster --cluster-name <名称> --output yaml > 导出配置.yaml
```

### 生成模板

```bash
# 生成配置模板
pcluster configure --config <输出文件.yaml>
```

---

## 四、镜像管理

### 自定义 AMI 构建

```bash
# 查看构建日志
pcluster get-image-log-events --image-id <image-id> --log-stream-name <stream-name>

# 列出所有镜像
pcluster list-images

# 查看镜像状态
pcluster describe-image --image-id <image-id>

# 构建镜像
pcluster build-image --image-id <image-id> --image-configuration <image-config.yaml>

# 删除镜像
pcluster delete-image --image-id <image-id>
```

---

## 五、SSH 登录

```bash
# 通过 pcluster SSH 登录头节点
pcluster ssh --cluster-name <名称> -i <密钥.pem>

# 直接 SSH 登录头节点
ssh -i <密钥.pem> <用户名>@<头节点IP>

# 从头节点登录计算节点
ssh <计算节点IP>
```

### 获取集群实例信息

```bash
pcluster describe-cluster-instances --cluster-name <名称> --region <区域>
```

---

## 六、作业管理（Slurm 集成）

pcluster 3.x 默认集成 Slurm，常用 Slurm 命令：

```bash
# 查看队列状态
sinfo

# 查看作业列表
squeue

# 查看所有作业（含历史）
squeue -a

# 提交作业
sbatch <脚本.sh>

# 交互式作业
srun --pty /bin/bash

# 取消作业
scancel <作业ID>

# 查看节点状态
sinfo -N -l

# 查看分区
sinfo -p <分区名>

# 查看作业详情
scontrol show job <作业ID>

# 查看节点详情
scontrol show node <节点名>
```

---

## 七、日志与监控

### 查看日志

```bash
# 集群创建日志
pcluster get-cluster-log-events --cluster-name <名称> --log-stream-name <stream-name>

# CloudWatch 日志组
pcluster get-cluster-log-events --cluster-name <名称> \
  --log-stream-name <stream-name> \
  --region <区域>
```

### 日志流名称参考

| 日志流 | 说明 |
|--------|------|
| `clustermgtd` | 集群管理守护进程 |
| `computefleet` | 计算队列管理 |
| `chef-client` | 配置管理客户端 |
| `cfn-init` | CloudFormation 初始化 |
| `cloud-init` | 系统初始化 |
| `slurmctld` | Slurm 控制器 |
| `slurmd` | Slurm 节点守护进程 |

---

## 八、计算节点操作

```bash
# 启停计算队列
pcluster update-compute-fleet --cluster-name <名称> --status START_REQUESTED
pcluster update-compute-fleet --cluster-name <名称> --status STOP_REQUESTED

# 查看计算队列状态
pcluster describe-compute-fleet --cluster-name <名称>
```

---

## 九、网络与存储

```bash
# 查看 EFS 挂载信息
df -h | grep efs

# 查看 FSx Lustre
df -h | grep fsx

# 查看挂载点
mount | grep -E "efs|fsx"
```

---

## 十、常用操作流程

### 创建集群的完整流程

```bash
# 1. 生成配置模板
pcluster configure --config cluster.yaml

# 2. 编辑配置（修改 VPC、子网、实例类型等）
vim cluster.yaml

# 3. 验证配置
pcluster validate-cluster-config --cluster-configuration cluster.yaml

# 4. 创建集群
pcluster create-cluster --cluster-name my-cluster --cluster-configuration cluster.yaml

# 5. 监控创建进度
pcluster describe-cluster --cluster-name my-cluster
```

### 排查问题的流程

```bash
# 1. 查看集群状态
pcluster describe-cluster --cluster-name <名称>

# 2. 查看失败事件
pcluster get-cluster-log-events --cluster-name <名称> \
  --log-stream-name clustermgtd

# 3. SSH 登录头节点查看
pcluster ssh --cluster-name <名称> -i <密钥.pem>

# 4. 头节点上查看系统日志
sudo tail -f /var/log/chef-client.log
sudo tail -f /var/log/cloud-init-output.log
```

---

## 十一、快速参考卡片

| 操作 | 命令 |
|------|------|
| 列出集群 | `pcluster list-clusters` |
| 集群详情 | `pcluster describe-cluster -n <名称>` |
| 创建集群 | `pcluster create-cluster -n <名称> -c <配置>` |
| 删除集群 | `pcluster delete-cluster -n <名称>` |
| 更新集群 | `pcluster update-cluster -n <名称> -c <配置>` |
| SSH 登录 | `pcluster ssh -n <名称> -i <密钥>` |
| 验证配置 | `pcluster validate-cluster-config -c <配置>` |
| 启停队列 | `pcluster update-compute-fleet -n <名称> --status START/STOP_REQUESTED` |
| 查看实例 | `pcluster describe-cluster-instances -n <名称>` |
| 构建镜像 | `pcluster build-image -i <image-id> -c <配置>` |