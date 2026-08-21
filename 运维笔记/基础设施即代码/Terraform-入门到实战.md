# Terraform：从入门到生产实践

> 验证基线：Terraform CLI `1.15.8`  
> 资料截止日期：2026-08-21  
> 适用范围：Terraform CLI、HCL、Provider、State、Backend、Module、Workspace、CI/CD 与团队协作

---

## 1. 文档概述

### 1.1 先讲结论

Terraform 是 HashiCorp 推出的基础设施即代码（Infrastructure as Code，IaC）工具。它通过声明式配置描述目标基础设施，再根据配置、State 和云平台实际状态生成执行计划。

生产环境使用 Terraform，最重要的不是记住多少语法，而是建立以下边界：

1. 代码描述期望状态，Provider 调用目标系统 API，State 记录 Terraform 资源地址与真实对象的绑定关系。
2. `terraform plan` 是变更预览，不是绝对保证；Plan 与 Apply 之间仍可能发生权限、配额或外部状态变化。
3. State 可能包含密码、连接串和资源属性，必须按敏感数据保护，不能提交到 Git。
4. 团队协作应使用支持锁定、加密、版本控制和权限隔离的远程 Backend。
5. `.terraform.lock.hcl` 应提交到版本库，`.terraform/`、State 和 Plan 文件不应提交。
6. 自动化中应保存 Plan，再批准并执行同一个 Plan，避免审批内容与实际执行内容不一致。
7. `-target`、`state push`、`force-unlock` 等命令只用于特定恢复场景，不应成为日常流程。
8. 生产和测试环境应使用不同 State；仅依靠 CLI Workspace 通常不足以形成强隔离。
9. 删除资源、替换资源、修改 State 前必须备份 State，并检查 Plan 中的地址和资源 ID。
10. Terraform 管理的是资源生命周期，不自动替代配置管理、应用发布、备份和灾难恢复。

### 1.2 适用读者

本文适合：

- DevOps、SRE、云平台和基础设施工程师；
- 希望用代码管理 AWS、Azure、Google Cloud、阿里云或 Kubernetes 的人员；
- 需要建设 Terraform Module、远程 State 和 CI/CD 流程的团队；
- 已经会手工创建云资源，希望逐步转向 IaC 的运维人员。

阅读完成后，应能够：

- 理解 Terraform 的核心组件和执行过程；
- 编写和组织 HCL 配置；
- 使用变量、输出、数据源、表达式和元参数；
- 管理 Provider 版本和依赖锁文件；
- 安全管理 State 和远程 Backend；
- 开发和调用 Module；
- 导入、移动和移除已有资源；
- 在 CI/CD 中执行格式检查、验证、Plan、审批和 Apply；
- 排查常见初始化、锁、漂移、认证和 State 问题。

### 1.3 版本基线

本文以 HashiCorp 官方安装页在资料截止日期提供的 Terraform `1.15.8` 为基线。

检查当前版本：

```bash
terraform version
terraform -help
```

团队项目应显式约束 Terraform 版本：

```hcl
terraform {
  required_version = ">= 1.15.0, < 2.0.0"
}
```

版本约束并不会自动安装对应版本。多人和 CI 环境还应使用版本管理工具或固定容器镜像，确保实际执行版本一致。

---

## 2. Terraform 是什么

### 2.1 IaC 的含义

传统方式通常是在控制台中逐项创建资源：

```text
登录控制台 → 创建 VPC → 创建交换机 → 创建安全组 → 创建主机
```

Terraform 将目标状态写成代码：

```hcl
resource "example_vpc" "main" {
  name       = "prod-vpc"
  cidr_block = "10.20.0.0/16"
}
```

由此得到：

- 变更可审查；
- 配置可重复执行；
- 历史可追踪；
- 环境可以按相同规则重建；
- 基础设施依赖关系可以由 Terraform 计算。

### 2.2 声明式模型

Terraform 配置通常描述“最终要什么”，而不是“依次点击什么”。例如：

```hcl
resource "aws_s3_bucket" "logs" {
  bucket = "example-prod-logs"
}
```

Terraform 会比较：

```text
配置中的期望状态
        +
State 中的绑定关系
        +
Provider 从远端读取的当前状态
        ↓
      执行计划
```

### 2.3 Terraform 能管理什么

Terraform 通过 Provider 管理具有 API 的系统，例如：

- AWS、Azure、Google Cloud、阿里云和其他云平台；
- Kubernetes、Helm；
- GitHub、GitLab；
- Cloudflare、DNS、监控平台；
- 数据库、SaaS 平台和身份系统。

是否支持某个资源，以对应 Provider 在 Terraform Registry 中的文档为准。

### 2.4 Terraform 不是什么

Terraform 不等于以下工具：

| 需求 | 更适合的工具 |
|---|---|
| 在系统内安装软件和修改配置 | Ansible、Salt、Chef |
| 发布 Kubernetes 应用 | Helm、Argo CD、Flux |
| 构建容器镜像 | BuildKit、Kaniko、Buildah |
| 备份 Kubernetes 业务对象和数据卷 | Velero、存储快照 |
| 持续监控和告警 | Prometheus、Grafana、Alertmanager |

Terraform 可以创建虚拟机和集群，但不代表它适合处理所有主机内部配置或持续应用发布。

---

## 3. 核心组件与执行原理

### 3.1 Terraform Core

Terraform Core 负责：

- 解析 `.tf` 配置；
- 读取变量和 Module；
- 加载 State；
- 构建资源依赖图；
- 与 Provider 协商资源 Schema；
- 生成 Plan；
- 按依赖顺序执行变更；
- 更新 State。

### 3.2 Provider

Provider 是 Terraform 与目标 API 之间的插件。

```text
Terraform Core
  ├── AWS Provider ───── AWS API
  ├── Alicloud Provider ─ 阿里云 API
  ├── Kubernetes Provider ─ Kubernetes API
  └── GitLab Provider ── GitLab API
```

Provider 定义：

- 可管理的 Resource；
- 可查询的 Data Source；
- 参数类型和校验规则；
- 创建、读取、更新、删除逻辑；
- 导入格式；
- 哪些属性会触发资源替换。

### 3.3 Resource

Resource 表示由 Terraform 管理的对象：

```hcl
resource "aws_instance" "web" {
  ami           = "ami-placeholder"
  instance_type = "t3.micro"
}
```

资源地址为：

```text
aws_instance.web
```

### 3.4 Data Source

Data Source 读取已有信息，但通常不负责创建对象：

```hcl
data "aws_caller_identity" "current" {}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}
```

### 3.5 State

State 保存 Terraform 资源地址与真实对象之间的绑定以及 Provider 返回的属性快照：

```text
aws_instance.web  →  i-0123456789abcdef0
```

State 不是普通缓存。丢失 State 后，Terraform 不再知道哪些真实资源归当前配置管理。

### 3.6 Backend

Backend 决定 State 的存储位置，并可能提供 State Locking：

- 本地文件；
- S3；
- Consul；
- Kubernetes Secret；
- HTTP 服务；
- HCP Terraform / Terraform Enterprise。

Backend 是 Terraform Core 内置能力，不像 Provider 一样动态安装插件。

### 3.7 Module

Module 是一组放在同一目录中的 Terraform 配置文件。当前工作目录中的配置称为 Root Module；通过 `module` 块调用的称为 Child Module。

---

## 4. 安装 Terraform

### 4.1 Ubuntu / Debian

使用 HashiCorp 官方 APT 仓库：

```bash
sudo apt-get update
sudo apt-get install -y gpg wget

wget -O- https://apt.releases.hashicorp.com/gpg \
  | sudo gpg --dearmor \
  -o /usr/share/keyrings/hashicorp-archive-keyring.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" \
  | sudo tee /etc/apt/sources.list.d/hashicorp.list

sudo apt-get update
sudo apt-get install -y terraform
```

验证：

```bash
terraform version
command -v terraform
```

如果系统不支持 `grep -P`，手工确认发行版代号：

```bash
. /etc/os-release
printf '%s\n' "$VERSION_CODENAME"
```

### 4.2 RHEL / Rocky Linux / AlmaLinux

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo \
  https://rpm.releases.hashicorp.com/RHEL/hashicorp.repo
sudo dnf install -y terraform
```

### 4.3 macOS

```bash
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
```

升级：

```bash
brew update
brew upgrade hashicorp/tap/terraform
```

### 4.4 二进制安装

二进制安装适合离线环境或需要固定版本的场景。生产环境应同时验证：

- 下载来源；
- SHA256 校验和；
- HashiCorp 发布签名；
- CPU 架构；
- 文件权限。

不要只下载压缩包后直接执行而跳过完整性验证。

### 4.5 多版本管理

不同项目可能使用不同 Terraform 版本。可以使用版本管理工具，也可以在 CI 中固定官方镜像标签。

无论采用哪种工具，都应以项目中的 `required_version` 为最低约束，并在流水线开始时输出：

```bash
terraform version
```

### 4.6 Shell 自动补全

安装补全脚本：

```bash
terraform -install-autocomplete
```

重新打开 Shell 后生效。重复执行可能提示补全已经存在。

---

## 5. 第一个可运行示例

下面使用 Terraform 内置的 `terraform_data`，不需要云账号，也不会创建收费资源。

### 5.1 创建目录

```bash
mkdir terraform-first-demo
cd terraform-first-demo
```

### 5.2 编写 `main.tf`

```hcl
terraform {
  required_version = ">= 1.15.0, < 2.0.0"
}

variable "environment" {
  description = "环境名称"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment 只能是 dev、test 或 prod。"
  }
}

locals {
  resource_name = "demo-${var.environment}"
}

resource "terraform_data" "example" {
  input = {
    name        = local.resource_name
    environment = var.environment
  }
}

output "result" {
  description = "示例资源的输入值"
  value       = terraform_data.example.output
}
```

### 5.3 标准工作流

```bash
terraform fmt
terraform init
terraform validate
terraform plan -out=tfplan
terraform show tfplan
terraform apply tfplan
terraform output
```

清理：

```bash
terraform plan -destroy -out=destroy.tfplan
terraform show destroy.tfplan
terraform apply destroy.tfplan
```

这个示例会生成本地 State。实验结束后可以删除整个实验目录；真实项目不要随意删除 State。

---

## 6. 项目目录与文件组织

### 6.1 推荐的简单结构

```text
terraform-live/
├── versions.tf       # Terraform 和 Provider 版本约束
├── providers.tf      # Provider 配置
├── backend.tf        # Backend 类型
├── variables.tf      # 输入变量声明
├── locals.tf         # 局部值
├── main.tf           # 主要资源
├── outputs.tf        # 输出值
├── terraform.tfvars  # 非敏感变量值，是否提交取决于团队规范
├── .terraform.lock.hcl
└── README.md
```

Terraform 会读取当前目录顶层所有 `.tf` 和 `.tf.json` 文件，并把它们视为同一个 Module。文件名主要用于帮助人类组织内容，不决定执行顺序。

### 6.2 多环境结构

推荐让环境拥有独立 Root Module 和独立 State：

```text
infrastructure/
├── modules/
│   ├── vpc/
│   └── kubernetes-cluster/
└── environments/
    ├── dev/
    │   ├── main.tf
    │   └── backend.hcl
    ├── test/
    │   ├── main.tf
    │   └── backend.hcl
    └── prod/
        ├── main.tf
        └── backend.hcl
```

这样比把所有环境放在一个 State 中更容易控制权限和故障范围。

### 6.3 `.gitignore`

常见配置：

```gitignore
.terraform/
*.tfstate
*.tfstate.*
crash.log
crash.*.log
*.tfplan
*.plan
override.tf
override.tf.json
*_override.tf
*_override.tf.json
.terraform.tfstate.lock.info
```

通常应提交：

```text
*.tf
.terraform.lock.hcl
模块 README
非敏感示例变量文件
测试文件
```

不要盲目忽略所有 `*.tfvars`。是否提交取决于内容：非敏感环境参数可以提交，密码、Token 和私钥不能提交。

---

## 7. HCL 基础语法

### 7.1 Block 与 Argument

```hcl
resource "aws_instance" "web" {
  instance_type = "t3.micro"

  tags = {
    Name = "web-01"
  }
}
```

- `resource` 是 Block 类型；
- `aws_instance` 和 `web` 是标签；
- `instance_type`、`tags` 是 Argument；
- 右侧是 Expression。

### 7.2 常用类型

```hcl
# string
name = "web"

# number
replicas = 3

# bool
enabled = true

# list / tuple
zones = ["cn-hangzhou-h", "cn-hangzhou-i"]

# map / object
tags = {
  Environment = "prod"
  ManagedBy   = "terraform"
}

# null
description = null
```

变量声明应尽量指定明确类型：

```hcl
variable "subnets" {
  type = map(object({
    cidr = string
    zone = string
  }))
}
```

### 7.3 字符串模板

```hcl
name = "${var.project}-${var.environment}"
```

只有单个引用时直接写引用即可：

```hcl
name = var.project
```

多行字符串：

```hcl
user_data = <<-EOT
  #!/bin/sh
  echo "environment=${var.environment}"
EOT
```

### 7.4 注释

```hcl
# 单行注释
// 单行注释

/*
多行注释
*/
```

### 7.5 格式化

```bash
terraform fmt
terraform fmt -recursive
terraform fmt -check -recursive
```

CI 中用 `-check` 检查，开发机上用 `terraform fmt -recursive` 修正。

---

## 8. Terraform 与 Provider 版本

### 8.1 `required_providers`

```hcl
terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
```

Provider 地址的完整形式是：

```text
registry.terraform.io/hashicorp/aws
```

### 8.2 版本约束

```hcl
version = "= 6.2.0"             # 只允许该版本
version = ">= 6.0.0"            # 允许所有更高版本，范围过宽
version = "~> 6.2"              # >= 6.2.0 且 < 7.0.0
version = ">= 6.2.0, < 7.0.0"   # 显式范围
```

Root Module 通常可以设置合理的上界；可复用 Child Module 通常声明已验证的最低版本，避免过度限制调用方。

### 8.3 `.terraform.lock.hcl`

`terraform init` 会创建或更新 Provider 依赖锁文件：

```text
.terraform.lock.hcl
```

它记录：

- 实际选择的 Provider 版本；
- 包校验和；
- Provider 地址；
- 版本约束信息。

应将其提交到 Git，使开发机和 CI 使用相同 Provider 版本。

为多个平台预填校验和：

```bash
terraform providers lock \
  -platform=linux_amd64 \
  -platform=linux_arm64 \
  -platform=darwin_arm64
```

升级 Provider：

```bash
terraform init -upgrade
terraform plan
```

不要在没有审查 Plan 和 Provider Changelog 的情况下自动合并升级。

### 8.4 Provider 配置与凭据

```hcl
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}
```

优先使用 Provider 支持的标准凭据链，例如：

- 工作负载身份；
- 实例角色；
- OIDC 联邦；
- 环境变量；
- 本地凭据配置文件。

不要把 Access Key、Secret、Token 写进 `.tf` 或 `tfvars`。

### 8.5 Provider Alias

多区域示例：

```hcl
provider "aws" {
  region = "ap-southeast-1"
}

provider "aws" {
  alias  = "backup"
  region = "ap-northeast-1"
}

resource "aws_s3_bucket" "backup" {
  provider = aws.backup
  bucket   = "example-backup-bucket"
}
```

---

## 9. 变量、局部值与输出

### 9.1 Input Variable

```hcl
variable "environment" {
  description = "部署环境"
  type        = string
  nullable    = false
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment 必须是 dev、test 或 prod。"
  }
}
```

引用：

```hcl
name = "api-${var.environment}"
```

### 9.2 变量赋值优先级

常见来源包括：

- `default`；
- `terraform.tfvars`；
- `*.auto.tfvars`；
- `-var-file`；
- `-var`；
- `TF_VAR_<name>` 环境变量；
- HCP Terraform Workspace 变量。

实际优先级和自动加载规则应以当前 Terraform 官方文档为准。为了减少混乱，团队应固定一种主要传参方式。

```bash
terraform plan -var-file=environments/prod.tfvars
```

命令行的 `-var` 可能进入 Shell 历史，不适合传密码。

### 9.3 Local Value

```hcl
locals {
  name_prefix = "${var.project}-${var.environment}"

  common_tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

引用：

```hcl
tags = local.common_tags
```

变量是 Module 的输入接口，Local 是 Module 内部计算结果。

### 9.4 Output

```hcl
output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}
```

读取：

```bash
terraform output
terraform output -raw vpc_id
terraform output -json
```

敏感输出：

```hcl
output "database_password" {
  value     = var.database_password
  sensitive = true
}
```

`sensitive = true` 只会抑制常规 CLI/UI 显示，不代表该值不会进入 State。

### 9.5 Ephemeral 值

Terraform 1.10 及以上可在受支持位置使用 Ephemeral 值，使值不写入 State 和 Plan：

```hcl
variable "session_token" {
  type      = string
  sensitive = true
  ephemeral = true
}
```

Ephemeral 值只能用于允许 Ephemeral 的上下文。Provider 是否提供 Ephemeral Resource 或 Write-only 参数，需要查对应 Provider 文档。

---

## 10. 表达式与函数

### 10.1 条件表达式

```hcl
instance_type = var.environment == "prod" ? "m6i.large" : "t3.micro"
```

### 10.2 `for` 表达式

```hcl
locals {
  subnet_ids = [for subnet in aws_subnet.app : subnet.id]

  enabled_services = {
    for name, config in var.services : name => config
    if config.enabled
  }
}
```

### 10.3 Splat 表达式

```hcl
output "instance_ids" {
  value = aws_instance.web[*].id
}
```

对于 `for_each` 生成的 Map，通常使用 `for` 表达式更清晰。

### 10.4 常用函数

```hcl
lower("PROD")
trimspace(" value ")
join(",", ["a", "b"])
split(",", "a,b")
merge(local.common_tags, { Name = "web" })
lookup(var.settings, "size", "small")
try(var.object.optional_field, null)
can(regex("^[a-z]+$", var.name))
toset(["a", "a", "b"])
jsonencode(local.policy)
yamldecode(file("config.yaml"))
file("${path.module}/templates/config.txt")
templatefile("${path.module}/templates/user-data.tftpl", {
  environment = var.environment
})
```

### 10.5 `terraform console`

交互测试表达式：

```bash
terraform console
```

```hcl
> merge({a = 1}, {b = 2})
> cidrsubnet("10.0.0.0/16", 8, 10)
> jsonencode({name = "api"})
```

Console 可能读取当前配置和 State，不要把敏感输出复制到工单或聊天中。

---

## 11. 资源依赖与执行图

### 11.1 隐式依赖

通过属性引用自动建立依赖：

```hcl
resource "aws_subnet" "app" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.20.1.0/24"
}
```

Terraform 能看出 `aws_subnet.app` 依赖 `aws_vpc.main`。

### 11.2 显式依赖

只有依赖无法通过值引用表达时才使用 `depends_on`：

```hcl
resource "example_service" "api" {
  depends_on = [example_policy_attachment.api]
}
```

滥用 `depends_on` 会使 Plan 更保守，产生更多 `(known after apply)`，尤其不要轻易对整个 Module 建立宽泛依赖。

### 11.3 查看依赖图

```bash
terraform graph > graph.dot
dot -Tsvg graph.dot -o graph.svg
```

`dot` 由 Graphviz 提供。

### 11.4 并行度

Terraform 默认会并行处理无依赖关系的操作：

```bash
terraform apply -parallelism=5 tfplan
```

降低并行度可以缓解 API 限流，但也会延长执行时间。不要把它当成修复错误依赖关系的方法。

---

## 12. `count`、`for_each` 与动态块

### 12.1 `count`

```hcl
resource "terraform_data" "node" {
  count = 3

  input = {
    name = "node-${count.index + 1}"
  }
}
```

地址：

```text
terraform_data.node[0]
terraform_data.node[1]
terraform_data.node[2]
```

列表中间插入或删除元素时，索引变化可能导致大量实例地址变化。

### 12.2 `for_each`

```hcl
variable "nodes" {
  type = map(object({
    size = string
    zone = string
  }))
}

resource "terraform_data" "node" {
  for_each = var.nodes

  input = {
    name = each.key
    size = each.value.size
    zone = each.value.zone
  }
}
```

地址稳定地使用业务键：

```text
terraform_data.node["api-01"]
terraform_data.node["worker-01"]
```

如果实例有稳定名称，通常优先选择 `for_each`。

### 12.3 `for_each` 的限制

`for_each` 的 Key 必须在 Plan 前已知，不能依赖 Apply 后才产生的 ID；Key 也不应包含敏感值。

### 12.4 Dynamic Block

动态生成重复嵌套块：

```hcl
resource "example_firewall" "main" {
  dynamic "rule" {
    for_each = var.rules

    content {
      port     = rule.value.port
      protocol = rule.value.protocol
      cidr     = rule.value.cidr
    }
  }
}
```

Dynamic Block 只适合 Provider Schema 中的嵌套块，不能动态生成任意顶层 Block。过度使用会降低可读性。

---

## 13. Lifecycle 与条件检查

### 13.1 `create_before_destroy`

```hcl
lifecycle {
  create_before_destroy = true
}
```

先创建替代对象，再删除旧对象。使用前必须确认名称唯一性、配额和目标 API 是否允许新旧对象同时存在。

### 13.2 `prevent_destroy`

```hcl
lifecycle {
  prevent_destroy = true
}
```

它能阻止 Plan 删除当前仍有该配置的资源，但不是绝对保险：如果整个 Resource Block 被移除，这条规则也随配置消失。关键资源还应使用云平台删除保护、权限策略和备份。

### 13.3 `ignore_changes`

```hcl
lifecycle {
  ignore_changes = [tags["LastModifiedBy"]]
}
```

只应忽略明确由外部系统管理的属性。大范围 `ignore_changes = all` 会掩盖真实漂移，使代码逐渐失去控制力。

### 13.4 `replace_triggered_by`

```hcl
lifecycle {
  replace_triggered_by = [terraform_data.release_version]
}
```

被引用对象发生指定变化时触发资源替换。

### 13.5 Precondition 与 Postcondition

```hcl
resource "example_server" "api" {
  image_id = var.image_id

  lifecycle {
    precondition {
      condition     = startswith(var.image_id, "img-")
      error_message = "image_id 必须以 img- 开头。"
    }

    postcondition {
      condition     = self.status == "running"
      error_message = "服务器创建后必须处于 running 状态。"
    }
  }
}
```

### 13.6 Check Block

`check` 用于在常规资源生命周期之外验证基础设施，例如检查服务健康状态。Check 失败通常产生警告而不是阻止整个操作，具体行为和 Data Source 时机应按官方文档验证。

---

## 14. 核心 CLI 工作流

### 14.1 `terraform init`

```bash
terraform init
```

它会：

- 初始化 Backend；
- 安装 Provider；
- 下载 Module；
- 创建或更新依赖锁文件；
- 准备 `.terraform/` 工作目录。

常用参数：

```bash
terraform init -upgrade
terraform init -reconfigure
terraform init -migrate-state
terraform init -backend=false
```

- `-upgrade`：重新选择满足约束的较新 Provider/Module；
- `-reconfigure`：忽略已有 Backend 初始化信息并重新配置；
- `-migrate-state`：更换 Backend 时迁移 State；
- `-backend=false`：跳过 Backend 初始化，适合部分静态检查场景。

### 14.2 `terraform validate`

```bash
terraform validate
terraform validate -json
```

它检查配置语法和内部一致性，但不会证明：

- 远程凭据有效；
- API 一定允许创建；
- 配额足够；
- Apply 一定成功。

### 14.3 `terraform plan`

```bash
terraform plan
terraform plan -out=tfplan
```

Plan 符号常见含义：

```text
+       创建
~       原地更新
-/+     删除后重建
+/-     创建后删除
-       删除
<=      读取 Data Source
```

保存并检查机器可读 Plan：

```bash
terraform plan -out=tfplan
terraform show -json tfplan > tfplan.json
```

Plan 文件和 JSON 可能包含敏感数据，不应作为公开流水线制品。

### 14.4 `terraform apply`

交互模式：

```bash
terraform apply
```

执行已保存 Plan：

```bash
terraform apply tfplan
```

传入已保存 Plan 时不会再次重新生成 Plan。自动化流程应对 Plan 进行审批，再执行同一个文件。

### 14.5 `terraform destroy`

```bash
terraform plan -destroy -out=destroy.tfplan
terraform show destroy.tfplan
terraform apply destroy.tfplan
```

比直接执行下面命令更适合审查：

```bash
terraform destroy
```

生产环境应对 Destroy 使用额外权限和人工审批。

### 14.6 Refresh-only

仅更新 State 和 Output 以反映远端状态：

```bash
terraform plan -refresh-only
terraform apply -refresh-only
```

不要在未审查情况下接受外部漂移；Refresh-only 会让 State 接受远端现状，但不会自动把配置改成一致。

### 14.7 `-replace`

```bash
terraform plan -replace='aws_instance.web' -out=tfplan
```

这是主动要求替换资源的标准方式之一。旧的 `terraform taint` 工作流不适合作为新流程首选。

### 14.8 `-target`

```bash
terraform plan -target='module.network'
```

只应在故障恢复、分阶段修复或官方建议的特殊情况下使用。长期依赖 `-target` 通常说明 State 或 Module 边界需要调整。

---

## 15. State 深入理解

### 15.1 State 为什么必要

仅有 HCL 不足以判断：

- 哪个云资源对应哪个 Resource 地址；
- 资源上次已知属性是什么；
- Provider 私有元数据是什么；
- 资源是否被移动到新地址；
- 应更新、替换还是删除哪个真实对象。

### 15.2 本地 State 文件

默认文件：

```text
terraform.tfstate
terraform.tfstate.backup
```

State 是 JSON，但不应手工编辑。使用 Terraform CLI 操作可以降低破坏 State 格式和绑定关系的风险。

### 15.3 常用 State 命令

```bash
terraform state list
terraform state show 'aws_instance.web'
terraform state pull
terraform state mv '旧地址' '新地址'
terraform state rm '资源地址'
```

危险命令：

```bash
terraform state push state.json
```

`state push` 会尝试覆盖远程 State。只有在确认 Lineage、Serial、备份和恢复目标后才应使用。

### 15.4 State 备份

远程 State 操作前：

```bash
umask 077
terraform state pull > state-backup.json
```

备份文件仍包含敏感信息。应存放到加密、受控的位置，并在恢复窗口结束后按制度销毁。

### 15.5 State Lock

支持锁定的 Backend 会在写操作期间加锁，避免多人同时修改 State。

锁冲突时先确认：

- 是否有其他 Plan/Apply 正在运行；
- 流水线是否仍在执行；
- 锁 ID、创建者和时间；
- 上一次进程是否异常退出。

确认锁已经失效后才执行：

```bash
terraform force-unlock LOCK_ID
```

不要为了快速通过而关闭锁或强制解锁仍在使用的 State。

### 15.6 State 中的秘密

以下内容可能进入 State：

- 数据库初始密码；
- 用户数据和启动脚本；
- 证书或连接串；
- Provider 返回的敏感属性；
- 标记为 `sensitive` 的普通变量值。

因此 State 必须：

- 传输加密；
- 静态加密；
- 最小权限访问；
- 开启审计；
- 有版本恢复能力；
- 禁止公开下载；
- 不写入 Git 和普通日志。

---

## 16. Remote Backend 与团队协作

### 16.1 为什么需要远程 Backend

本地 State 不适合多人协作，因为：

- 容易丢失；
- 难以锁定；
- 难以共享；
- 难以审计；
- 容易被误提交；
- 无法稳定支持 CI/CD。

### 16.2 S3 Backend 示例

```hcl
terraform {
  backend "s3" {
    bucket       = "example-terraform-state"
    key          = "platform/prod/terraform.tfstate"
    region       = "ap-southeast-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

当前官方 S3 Backend 支持通过 `use_lockfile = true` 启用 S3 锁文件。旧的 DynamoDB 锁机制已经被标记为弃用，新项目应按当前官方文档选择锁定方式。

生产要求：

- Bucket 禁止公开访问；
- 开启版本控制；
- 开启服务端加密；
- Apply 身份只访问所需前缀；
- State 和 `.tflock` 同时授权；
- CloudTrail 或等价审计开启；
- 定期验证版本恢复。

### 16.3 Partial Backend Configuration

代码中只声明 Backend 类型：

```hcl
terraform {
  backend "s3" {}
}
```

环境配置文件 `backend.hcl`：

```hcl
bucket       = "example-terraform-state"
key          = "platform/prod/terraform.tfstate"
region       = "ap-southeast-1"
encrypt      = true
use_lockfile = true
```

初始化：

```bash
terraform init -backend-config=backend.hcl
```

不要在 `backend.hcl` 或 `-backend-config` 中放长期凭据。合并后的 Backend 配置会存入 `.terraform/`，保存的 Plan 也可能包含相关信息。

### 16.4 Backend 迁移

迁移前：

```bash
umask 077
terraform state pull > state-before-backend-migration.json
```

修改 Backend 后：

```bash
terraform init -migrate-state
terraform state list
terraform plan
```

迁移窗口内禁止其他人 Apply。

### 16.5 Backend 的引导问题

存放 State 的 Bucket、权限和加密密钥本身也可能由 Terraform 管理。常见做法是：

1. 用独立 Bootstrap 配置创建 Backend 基础设施；
2. Bootstrap 使用独立且严格保护的 State；
3. 业务 Stack 再引用已创建的 Backend；
4. 不要让业务 Stack 销毁自己的 State 存储。

---

## 17. Workspace 与环境隔离

### 17.1 CLI Workspace

```bash
terraform workspace list
terraform workspace new dev
terraform workspace select dev
terraform workspace show
```

引用当前 Workspace：

```hcl
locals {
  environment = terraform.workspace
}
```

### 17.2 Workspace 做了什么

CLI Workspace 主要是在同一个 Backend 配置下选择不同 State 实例。它不会自动提供：

- 不同云账号；
- 不同 IAM 权限；
- 不同 Backend 凭据；
- 不同代码审批；
- 强网络隔离。

### 17.3 什么时候不应只用 Workspace

生产和非生产需要以下任一边界时，优先使用独立 Root Module 和独立 Backend：

- 不同账号或订阅；
- 不同审批流程；
- 不同 State 访问权限；
- 不同维护窗口；
- 不同故障范围；
- 不同合规要求。

误选 Workspace 是常见事故来源。流水线必须显式输出并校验当前目标环境。

---

## 18. Module 设计与复用

### 18.1 最小 Module 结构

```text
modules/vpc/
├── main.tf
├── variables.tf
├── outputs.tf
├── versions.tf
└── README.md
```

### 18.2 Child Module 示例

`modules/network/variables.tf`：

```hcl
variable "name" {
  description = "网络名称"
  type        = string
}

variable "cidr_block" {
  description = "网络 CIDR"
  type        = string
}
```

`modules/network/main.tf`：

```hcl
resource "terraform_data" "network" {
  input = {
    name       = var.name
    cidr_block = var.cidr_block
  }
}
```

`modules/network/outputs.tf`：

```hcl
output "network" {
  description = "网络信息"
  value       = terraform_data.network.output
}
```

Root Module 调用：

```hcl
module "network" {
  source = "../../modules/network"

  name       = "prod-vpc"
  cidr_block = "10.20.0.0/16"
}
```

### 18.3 Module Source 与版本

Registry Module：

```hcl
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "明确审查过的版本约束"
}
```

Git Source：

```hcl
module "network" {
  source = "git::ssh://git@example.com/platform/modules.git//network?ref=v1.4.0"
}
```

生产环境不要引用会移动的默认分支，使用不可变 Tag 或 Commit，并做好供应链审查。

### 18.4 Provider 传递

Child Module 应声明 `required_providers`，但通常不应在内部定义用于认证和区域选择的 `provider` 块。Provider 配置由 Root Module 传入：

```hcl
module "backup" {
  source = "../../modules/storage"

  providers = {
    aws = aws.backup
  }
}
```

### 18.5 Module 设计原则

- 围绕可识别的基础设施能力划分，不按单个 Resource 机械包装；
- 输入变量都有类型、描述和必要校验；
- Output 只暴露调用者需要的稳定接口；
- 不在 Module 内硬编码账号、区域和凭据；
- 避免大量布尔开关组成难以理解的“万能 Module”；
- 记录升级影响、依赖版本和示例；
- 为关键 Module 编写测试；
- 重大不兼容变更使用语义化版本。

---

## 19. 导入现有基础设施

### 19.1 导入的真实含义

Import 主要建立：

```text
Terraform Resource 地址 ↔ 已存在的远端对象
```

它不会自动证明现有配置正确，也不会自动把所有关联资源一并纳管。

### 19.2 配置驱动 Import

```hcl
import {
  to = aws_s3_bucket.logs
  id = "existing-log-bucket"
}

resource "aws_s3_bucket" "logs" {
  bucket = "existing-log-bucket"
}
```

执行：

```bash
terraform plan
terraform apply
```

Import Block 是声明式且幂等的，可以保留作为历史记录，也可以在团队确认后按规范清理。

### 19.3 生成配置

```hcl
import {
  to = aws_s3_bucket.logs
  id = "existing-log-bucket"
}
```

生成候选配置：

```bash
terraform plan -generate-config-out=generated_resources.tf
```

生成内容只是起点，可能包含默认值、只读属性或冲突参数。必须人工精简并重新 Plan。

### 19.4 CLI Import

```bash
terraform import 'aws_s3_bucket.logs' 'existing-log-bucket'
```

CLI Import 只写入 State，不生成对应 HCL。执行前需要先准备匹配的 Resource Block。

### 19.5 导入检查清单

1. 备份 State；
2. 确认目标账号、区域和 Workspace；
3. 查 Provider 文档确认 Import ID；
4. 确保一个远端对象只绑定一个资源地址；
5. Import 后运行 `terraform state show`；
6. 运行 Plan；
7. 如果 Plan 要立即删除或替换资源，先停止并修正配置；
8. 对关联资源逐个确认边界。

---

## 20. 重构资源地址而不重建资源

### 20.1 `moved` Block

资源改名：

```hcl
moved {
  from = aws_instance.web
  to   = aws_instance.api
}
```

移入 Module：

```hcl
moved {
  from = aws_vpc.main
  to   = module.network.aws_vpc.main
}
```

运行 Plan，确认显示地址移动而不是删除并创建。

### 20.2 `terraform state mv`

```bash
terraform state mv \
  'aws_instance.web' \
  'module.compute.aws_instance.web'
```

`moved` Block 可审查、可随代码传播，一般更适合协作项目。`state mv` 适合受控的即时 State 操作。

### 20.3 从 Terraform 管理中移除但不删除

声明式方式：

```hcl
removed {
  from = aws_s3_bucket.legacy

  lifecycle {
    destroy = false
  }
}
```

命令式方式：

```bash
terraform state rm 'aws_s3_bucket.legacy'
```

这只解除 Terraform 绑定，不会让真实资源消失。之后要明确新的负责人、监控和删除流程，避免形成无人管理资源。

---

## 21. 漂移检测与变更审查

### 21.1 什么是漂移

漂移是远端对象被 Terraform 之外的操作修改，导致实际状态与配置或 State 不一致。

来源包括：

- 控制台手工修改；
- 其他自动化系统；
- 云平台自动调整；
- Incident 临时操作；
- 同一资源被多个 Terraform State 管理。

### 21.2 检测

```bash
terraform plan -detailed-exitcode
```

退出码：

```text
0  无差异
1  命令错误
2  有差异
```

CI 必须正确处理退出码 `2`，不能把它简单当成命令失败。

### 21.3 处理原则

发现漂移后选择其一：

- 用 Terraform 恢复到代码定义；
- 修改代码接受合理的外部变更；
- 明确由外部系统负责的属性，并精确配置 `ignore_changes`；
- 将不应继续管理的对象安全移出 State。

不要仅运行 Refresh-only 就宣布漂移已经解决，因为配置可能仍然不一致。

### 21.4 Plan 审查重点

- 目标账号、区域、Workspace 和 State Key 是否正确；
- 是否出现非预期 Destroy 或 Replace；
- Resource 地址是否发生大规模变化；
- 安全组、IAM、路由和公网入口是否扩大；
- 数据库、磁盘和集群是否会重建；
- Provider 是否升级；
- 未知值是否会在 Apply 时影响策略；
- 变更窗口和回退方案是否明确。

---

## 22. 测试与静态检查

### 22.1 基础检查

```bash
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

### 22.2 Terraform Test

测试文件通常放在 `tests/`，扩展名为 `.tftest.hcl`：

```hcl
run "valid_environment" {
  command = plan

  variables {
    environment = "dev"
  }

  assert {
    condition     = terraform_data.example.output.environment == "dev"
    error_message = "环境名称不正确。"
  }
}
```

运行：

```bash
terraform test
terraform test -verbose
```

测试可以执行 `plan` 或 `apply`。使用 Apply 的测试可能创建真实资源并产生费用，必须使用隔离账号、最小权限和可靠清理流程。

### 22.3 可选工具

团队可按需要增加：

- TFLint：规则和 Provider 相关静态检查；
- Checkov、tfsec、Trivy：IaC 安全扫描；
- Conftest / OPA：自定义策略；
- Infracost：成本变化估算；
- Terraform Docs：生成 Module 文档。

这些工具不能替代 Provider 官方文档、Terraform Plan 和人工审查。版本、规则集和误报处理需要团队维护。

---

## 23. CI/CD 推荐流程

### 23.1 Pull Request 阶段

```text
代码变更
   ↓
terraform fmt -check
   ↓
terraform init
   ↓
terraform validate / test / 安全扫描
   ↓
terraform plan -out=tfplan
   ↓
发布经过脱敏和权限控制的 Plan 摘要
   ↓
人工审查
```

### 23.2 Apply 阶段

```text
批准合并或环境审批
   ↓
校验 Commit、环境和 Plan 来源
   ↓
执行已审批的 tfplan
   ↓
记录 Apply 结果和 State 版本
   ↓
执行目标环境验证
```

### 23.3 GitLab CI 示例

```yaml
stages:
  - validate
  - plan
  - apply

default:
  image:
    name: hashicorp/terraform:1.15.8
    entrypoint: [""]
  before_script:
    - terraform version
    - terraform init -input=false

validate:
  stage: validate
  script:
    - terraform fmt -check -recursive
    - terraform validate

plan:
  stage: plan
  script:
    - terraform plan -input=false -out=tfplan
  artifacts:
    paths:
      - tfplan
    expire_in: 1 day
    access: developer

apply:
  stage: apply
  script:
    - terraform apply -input=false tfplan
  dependencies:
    - plan
  when: manual
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

这是流程示例，投入生产前还需要解决：

- Plan 制品中可能有秘密；
- Plan Job 与 Apply Job 身份是否相同；
- Plan 是否严格绑定同一 Commit；
- 远程 State 锁；
- OIDC 或短期凭据；
- Environment 保护和审批；
- 并发流水线互斥；
- Runner 与 Provider 下载供应链。

### 23.4 自动化参数

```bash
export TF_IN_AUTOMATION=true

terraform init -input=false
terraform plan -input=false -out=tfplan
terraform apply -input=false tfplan
```

不要为了方便直接对生产使用：

```bash
terraform apply -auto-approve
```

除非审批已经在外部系统完成，而且执行的是经过审批的不可变 Plan。

### 23.5 并发控制

除了 Backend Lock，还应在 CI 层对同一 State Key 设置并发组或资源锁。Backend Lock 保护 State 一致性，CI 并发控制减少重复 Plan、长时间等待和误操作。

---

## 24. 阿里云实战结构示例

下面展示配置组织方式。资源参数和 Provider 版本会变化，执行前必须根据当前 Alicloud Provider Registry 文档核对。

### 24.1 `versions.tf`

```hcl
terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  required_providers {
    alicloud = {
      source  = "aliyun/alicloud"
      version = ">= 1.200.0, < 2.0.0"
    }
  }
}
```

### 24.2 `providers.tf`

```hcl
provider "alicloud" {
  region = var.region
}
```

凭据通过工作负载身份、RAM Role、OIDC 或 Provider 支持的标准环境变量提供，不写入代码。

### 24.3 `variables.tf`

```hcl
variable "region" {
  description = "阿里云地域"
  type        = string
  default     = "cn-hangzhou"
}

variable "environment" {
  description = "环境名称"
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment 必须是 dev、test 或 prod。"
  }
}

variable "vpc_cidr" {
  description = "VPC CIDR"
  type        = string
  default     = "10.20.0.0/16"
}
```

### 24.4 `main.tf`

```hcl
locals {
  name_prefix = "platform-${var.environment}"

  common_tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
    Project     = "platform"
  }
}

resource "alicloud_vpc" "main" {
  vpc_name   = "${local.name_prefix}-vpc"
  cidr_block = var.vpc_cidr
  tags       = local.common_tags
}

resource "alicloud_vswitch" "app" {
  vswitch_name = "${local.name_prefix}-app"
  vpc_id       = alicloud_vpc.main.id
  cidr_block   = "10.20.10.0/24"
  zone_id      = "cn-hangzhou-h"
  tags         = local.common_tags
}
```

### 24.5 `outputs.tf`

```hcl
output "vpc_id" {
  description = "VPC ID"
  value       = alicloud_vpc.main.id
}

output "vswitch_id" {
  description = "应用交换机 ID"
  value       = alicloud_vswitch.app.id
}
```

### 24.6 执行

```bash
terraform init
terraform fmt -check -recursive
terraform validate
terraform plan -var='environment=dev' -out=tfplan
terraform show tfplan
terraform apply tfplan
```

这个示例会创建真实云资源并可能产生费用。执行前确认账号、Region、Zone、配额、网络规划和回收流程。

---

## 25. Kubernetes Provider 使用边界

Terraform 可以管理 Kubernetes 对象：

```hcl
terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "使用团队已验证的版本约束"
    }
  }
}

provider "kubernetes" {
  config_path = var.kubeconfig_path
}

resource "kubernetes_namespace_v1" "platform" {
  metadata {
    name = "platform"
  }
}
```

建议边界：

- Terraform 管理集群、节点池、基础 Namespace、必要 CRD 和平台级依赖；
- Argo CD / Flux 管理频繁发布的应用工作负载；
- Helm Provider 适合受控的基础组件，但仍需明确 Release State 的归属；
- 不要让 Terraform 和 GitOps 同时管理同一个 Kubernetes 字段或对象。

创建集群和配置 Kubernetes Provider 放在同一个 Root Module 时，Provider 初始化时机可能与集群创建形成依赖问题。生产中通常拆成不同 State 和流水线阶段。

---

## 26. 安全实践

### 26.1 身份与权限

- 本地优先使用 SSO 和短期凭据；
- CI 优先使用 OIDC / Workload Identity；
- Plan 身份可以只读加必要模拟权限；
- Apply 身份使用最小权限；
- Destroy 和 State 管理使用更严格的审批；
- 不使用长期共享管理员密钥。

### 26.2 State 与 Plan

- State、Plan 和 Crash Log 都按敏感文件处理；
- Backend 开启加密、锁、版本控制和审计；
- 制品设置短过期时间和严格下载权限；
- 不把 `terraform show -json` 输出发到公开日志；
- 定期测试 State 版本恢复。

### 26.3 Provider 与 Module 供应链

- 约束 Provider 和 Module 版本；
- 提交 `.terraform.lock.hcl`；
- 审查锁文件变化；
- 私有环境使用 Provider Mirror；
- Module 使用固定版本或 Commit；
- 不直接使用来源不明的 Module；
- 关注 Provider Changelog 和安全公告。

### 26.4 Provisioner

`local-exec` 和 `remote-exec` 应作为最后手段：

```hcl
provisioner "local-exec" {
  command = "some-command"
}
```

问题包括：

- 幂等性难保证；
- 执行环境依赖强；
- 秘密容易进入日志；
- 错误恢复复杂；
- Destroy 阶段行为容易被忽略。

优先选择云初始化、镜像构建、配置管理或目标系统原生 Provider。

### 26.5 策略控制

可以在 CI 或 HCP Terraform 中增加策略，例如：

- 禁止公网安全组 `0.0.0.0/0` 开放管理端口；
- 关键存储必须加密；
- 生产资源必须带成本和负责人标签；
- 禁止创建未批准规格；
- Destroy 数量超过阈值时阻止 Apply。

策略应检查 Plan JSON，并维护例外审批机制。

---

## 27. 常见故障排查

### 27.1 `terraform: command not found`

检查：

```bash
command -v terraform
printf '%s\n' "$PATH"
terraform version
```

确认二进制安装目录在 PATH 中，并检查 CPU 架构是否正确。

### 27.2 Provider 下载失败

典型原因：

- DNS 或代理问题；
- 无法访问 Registry；
- Provider 版本约束冲突；
- 锁文件只有其他平台校验和；
- 私有镜像源配置错误；
- TLS 中间人证书未受信任。

诊断：

```bash
terraform providers
terraform init -upgrade
```

不要通过关闭 TLS 校验长期绕过证书问题。

### 27.3 `Inconsistent dependency lock file`

先确认代码和锁文件来自同一 Commit，然后执行：

```bash
terraform init
```

如果是有意升级：

```bash
terraform init -upgrade
git diff -- .terraform.lock.hcl
```

### 27.4 State Lock 获取失败

先查看是否有真实执行任务。确认锁失效后：

```bash
terraform force-unlock LOCK_ID
```

如果 Backend 不支持锁，应迁移到支持锁定的方案，而不是让多人约定“不要同时运行”。

### 27.5 Plan 要删除大量资源

立即停止 Apply，检查：

```bash
terraform workspace show
terraform state list
terraform providers
terraform version
```

重点确认：

- State Key 是否切错；
- Workspace 是否选错；
- Resource 是否改名但没有 `moved`；
- Module Source 是否变化；
- `for_each` Key 是否变化；
- Provider Alias 是否传错；
- 变量文件是否加载错误。

### 27.6 `Resource already exists`

说明真实对象存在，但当前 State 没有对应绑定。不要反复 Apply，应判断：

- 对象是否应导入；
- 名称是否冲突；
- 是否被另一个 State 管理；
- 是否是上次失败遗留对象。

### 27.7 Apply 部分失败

Terraform 可能已经创建部分资源并更新部分 State。处理顺序：

1. 保存完整错误信息；
2. 不要直接删除 State；
3. 检查远端对象和 `terraform state list`；
4. 修复权限、参数、配额或依赖问题；
5. 重新执行 Plan；
6. 确认 Terraform 是否能收敛到目标状态。

### 27.8 调试日志

```bash
export TF_LOG=DEBUG
export TF_LOG_PATH=terraform-debug.log
terraform plan
unset TF_LOG
unset TF_LOG_PATH
```

日志可能包含请求信息和敏感数据。只在短时间诊断时启用，脱敏后再共享。

### 27.9 Provider Schema 查看

```bash
terraform providers schema -json > provider-schema.json
```

该文件可能很大，主要用于工具集成和深度诊断。

---

## 28. 生产落地流程

### 28.1 新项目

1. 确定账号、Region、资源边界和责任人；
2. 创建独立 Backend 和访问策略；
3. 固定 Terraform 与 Provider 版本策略；
4. 建立目录、变量、标签和命名规范；
5. 编写最小可用 Root Module；
6. 增加格式、验证、测试和安全扫描；
7. 建立 Plan 审批和 Apply 权限；
8. 从开发环境验证；
9. 验证 State 备份和恢复；
10. 再逐步推广到生产。

### 28.2 接管已有环境

1. 盘点真实资源和依赖；
2. 明确哪些资源纳入 Terraform；
3. 按故障范围拆分 State；
4. 编写最小配置；
5. 使用 Import Block 导入；
6. 反复 Plan，直到不出现意外修改；
7. 禁止多个 State 管理同一对象；
8. 将控制台变更改为紧急例外流程；
9. 建立定期漂移检测。

### 28.3 变更窗口

变更前：

- 确认当前 Commit、Terraform 版本、Provider 锁文件；
- 确认账号、Region、Workspace 和 State Key；
- 确认 State Lock 正常；
- 审查 Plan；
- 对关键数据资源确认备份；
- 记录替换和删除对象；
- 准备目标系统级回退措施。

变更后：

- 检查 Apply 完成状态；
- 再运行一次 Plan，确认是否收敛；
- 验证云资源和业务健康；
- 记录 State 版本和变更结果；
- 不把“Terraform Apply 成功”等同于“业务验证成功”。

---

## 29. 命令速查表

### 29.1 初始化与检查

```bash
terraform version
terraform fmt -recursive
terraform fmt -check -recursive
terraform init
terraform init -upgrade
terraform validate
terraform providers
```

### 29.2 Plan 与 Apply

```bash
terraform plan
terraform plan -out=tfplan
terraform show tfplan
terraform show -json tfplan
terraform apply tfplan
terraform plan -destroy -out=destroy.tfplan
terraform apply destroy.tfplan
```

### 29.3 变量与输出

```bash
terraform plan -var-file=prod.tfvars
terraform output
terraform output -raw vpc_id
terraform output -json
terraform console
```

### 29.4 State

```bash
terraform state list
terraform state show '资源地址'
terraform state pull
terraform state mv '旧地址' '新地址'
terraform state rm '资源地址'
terraform force-unlock LOCK_ID
```

### 29.5 Workspace

```bash
terraform workspace list
terraform workspace new dev
terraform workspace select dev
terraform workspace show
```

### 29.6 Import 与重构

```bash
terraform import '资源地址' '远端资源ID'
terraform plan -generate-config-out=generated.tf
terraform plan -replace='资源地址'
terraform plan -refresh-only
```

### 29.7 测试与图

```bash
terraform test
terraform graph > graph.dot
terraform providers schema -json > provider-schema.json
```

---

## 30. 上线检查清单

### 30.1 代码

- [ ] `terraform fmt -check -recursive` 通过；
- [ ] `terraform validate` 通过；
- [ ] Terraform 与 Provider 有版本约束；
- [ ] `.terraform.lock.hcl` 已提交并审查；
- [ ] 变量有类型、描述和必要校验；
- [ ] Module Source 使用固定版本；
- [ ] 没有明文凭据；
- [ ] 没有无依据的 `ignore_changes` 和 `depends_on`；
- [ ] 重构使用 `moved`，不会误重建。

### 30.2 State 与 Backend

- [ ] 生产使用远程 State；
- [ ] Backend 支持并启用锁；
- [ ] State 静态和传输加密；
- [ ] 对象存储开启版本控制；
- [ ] State 权限最小化；
- [ ] 已验证恢复步骤；
- [ ] State、Plan 和 `.terraform/` 未提交 Git。

### 30.3 执行

- [ ] 目标账号、Region、Workspace 和 State Key 已确认；
- [ ] Plan 来源 Commit 已确认；
- [ ] Apply 执行的正是已审批 Plan；
- [ ] Replace、Destroy 和权限扩大已逐项确认；
- [ ] 关键数据已有备份；
- [ ] CI 使用短期身份；
- [ ] 同一 State 的流水线已互斥；
- [ ] 变更后业务验证已安排。

---

## 31. 学习路线

建议按这个顺序学习：

1. `init → validate → plan → apply → destroy`；
2. Resource、Data Source、Variable、Local、Output；
3. 引用、函数、`for`、`count` 和 `for_each`；
4. Provider 版本与锁文件；
5. State、Lock 和 Remote Backend；
6. Module 开发和版本管理；
7. Import、`moved`、`removed` 和漂移处理；
8. Terraform Test、静态检查和安全扫描；
9. CI/CD、OIDC、审批和策略控制；
10. 多账号、多环境和平台级 Module 设计。

每个阶段都应完成一个小实验。建议先用 `terraform_data`，再管理非关键云资源，最后进入生产基础设施。

---

## 32. 官方资料

- [Terraform 官方文档](https://developer.hashicorp.com/terraform/docs)
- [Terraform 安装](https://developer.hashicorp.com/terraform/install)
- [Terraform Language](https://developer.hashicorp.com/terraform/language)
- [Terraform CLI](https://developer.hashicorp.com/terraform/cli)
- [Provider Registry](https://registry.terraform.io/browse/providers)
- [Module Registry](https://registry.terraform.io/browse/modules)
- [State](https://developer.hashicorp.com/terraform/language/state)
- [Backend](https://developer.hashicorp.com/terraform/language/backend)
- [Module](https://developer.hashicorp.com/terraform/language/modules)
- [Import](https://developer.hashicorp.com/terraform/language/import)
- [Terraform Test](https://developer.hashicorp.com/terraform/cli/commands/test)
- [Terraform GitHub Releases](https://github.com/hashicorp/terraform/releases)

涉及具体 Resource 参数、Import ID、超时和升级兼容性时，应优先查看对应 Provider 的当前 Registry 文档，不要只依赖本文示例。
