# Ansible 使用指南（ansible-core 2.14+）

## 1. 文档概述

### 解决什么问题

本指南帮助你从零搭建 Ansible 控制端，用 Inventory、ad-hoc 命令和 Playbook 管理多台 Linux 主机，完成安装软件、下发配置、启停服务等常见运维自动化任务。

### 适合哪些读者

- 有一定 Linux 与 SSH 基础，能独立登录远程机执行命令
- 想用声明式方式批量管理服务器，而不是手写 shell 脚本逐台操作
- 需要一份可检索、可照着敲的实操手册（非概念科普）

### 阅读后能获得什么

- 理解 Ansible 核心对象：Inventory、Module、Playbook、Role、Handler、Var、Fact
- 能安装并验证控制端，配置免密 SSH 与 `ansible.cfg`
- 会写 Inventory / Playbook / Role，并用 Jinja2 模板下发配置
- 能完成一个「批量安装 nginx → 配置站点 → 启动服务」的完整示例
- 掌握常见报错排查、Vault 基础与干跑等常用实践

### 版本说明

本文以 **Ansible 2.14+ / ansible-core** 为准。自 Ansible 2.10 起，核心能力拆为 `ansible-core`，大量模块与插件以 **Collections**（集合）形式分发；日常安装的 `ansible` 包通常已包含常用集合。文中模块名（如 `ansible.builtin.copy`）采用 FQCN（Fully Qualified Collection Name）写法，也兼容短名（如 `copy`），建议新项目统一用 FQCN。

---

## 2. 前置条件

### 环境要求

| 角色 | 要求 |
|------|------|
| Control Node（控制端） | Linux / macOS；Python 3.9+（以你安装的 ansible-core 版本要求为准） |
| Managed Node（被管端） | Linux；可通过 SSH 登录；建议安装 Python 3（多数模块需要） |
| 网络 | 控制端能 SSH 到被管端（默认 22 端口） |

### 软件及版本

- **ansible-core ≥ 2.14**（推荐通过 pip 或发行版包安装）
- OpenSSH 客户端（控制端）、OpenSSH 服务端（被管端）
- 可选：`sshpass`（仅演示密码登录时需要；生产环境不推荐）

### 必备基础知识

- 会用 `ssh`、公钥登录
- 了解 YAML 缩进（空格，不用 Tab）
- 熟悉 `systemctl`、包管理器（`apt` / `yum` / `dnf`）的基本用法

### 需要你本地准备的信息

运行文末完整示例前，请自行替换：

- **【需要确认】** 被管主机 IP / 主机名
- **【需要确认】** SSH 用户名（如 `ubuntu` / `centos` / `root`）
- **【需要确认】** 是否已有 sudo 权限、是否免密 sudo

---

## 3. 核心概念

**先记住结论：** Ansible 是「控制端通过 SSH（默认）把任务推到被管端执行」的自动化工具；你描述「期望状态」，模块尽量做到**幂等**（多次执行结果一致）。

### 3.1 角色与组件一览

| 术语 | 一句话解释 |
|------|------------|
| Control Node | 安装并运行 `ansible` / `ansible-playbook` 的机器 |
| Managed Node | 被管理的目标主机，通常无需安装 Ansible Agent |
| Inventory | 主机清单：有哪些机器、如何分组、每组/每机有哪些变量 |
| Module | 执行单一动作的单元（如 `copy`、`service`、`apt`） |
| Task | Playbook 里「调用某个模块 + 参数」的一条步骤 |
| Play | 一组针对某批主机执行的 Task 集合 |
| Playbook | 由一个或多个 Play 组成的 YAML 剧本文件 |
| Handler | 被 `notify` 触发的特殊 Task，通常用于重启服务，默认在 Play 末尾执行一次 |
| Role | 按约定目录组织的可复用任务包（tasks、handlers、templates、vars 等） |
| Var | 变量，用于参数化配置 |
| Fact | Ansible 自动采集的主机事实（OS、IP、内存等），存在 `ansible_facts` |
| Idempotency（幂等） | 同一任务执行多次，系统最终状态应相同；已满足则报告 `ok`/`changed=false` |

### 3.2 工作原理（简化）

1. 读取 Inventory，确定目标主机与变量
2. 通过连接插件（默认 `ssh`）登录被管端
3. 将模块代码与参数传到被管端执行（或走本地连接）
4. 汇总每台机器的 `ok` / `changed` / `failed` / `unreachable` 结果

### 3.3 适用场景

- 批量装包、改配置、启服务、建用户、发文件
- 多环境配置一致性（开发 / 测试 / 生产差异用变量表达）
- 与 CI 结合做发布前检查、基础设施基线固化

不适合或需谨慎的场景：强实时交互、需要复杂事务回滚的长流程（应拆小、配校验与补偿）。

---

## 4. 实现步骤

按顺序完成：安装 → 免密与配置 → Inventory → ad-hoc 验证 → 写 Playbook → 变量与模板 → Handlers → Roles → 实践技巧。每步包含：**做什么 / 为什么 / 预期结果**。

### 4.1 安装与环境

#### 步骤 1：在控制端安装 Ansible

**做什么：** 用 pip（推荐跨发行版一致）或系统包管理器安装。

**为什么：** 控制端需要 `ansible`、`ansible-playbook`、`ansible-galaxy`、`ansible-vault` 等命令。

**pip 方式（推荐在虚拟环境中）：**

```bash
python3 -m venv ~/venvs/ansible
source ~/venvs/ansible/bin/activate
pip install -U pip
pip install "ansible-core>=2.14"
# 若需要完整社区集合集合包，可再装：
# pip install "ansible>=9.0"
ansible --version
```

**包管理器方式（简要）：**

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y ansible-core
# 部分发行版包名仍为 ansible
# sudo apt install -y ansible

# RHEL / Rocky / Alma（需启用合适仓库，具体源【需要确认】）
sudo dnf install -y ansible-core
```

**macOS（Homebrew）：**

```bash
brew install ansible
ansible --version
```

**预期结果：** 输出类似：

```text
ansible [core 2.16.x]
  ...
  python version = 3.x.x
  jinja version = 3.x.x
```

看到 `core 2.14` 及以上即可继续。

#### 步骤 2：确认被管端 Python 与 SSH

**做什么：** 从控制端 SSH 登录被管端，确认 Python 可用。

```bash
ssh <USER>@<HOST> 'python3 --version'
```

**为什么：** 绝大多数模块在远端用 Python 执行；极少数如 `raw`/`script` 例外。

**预期结果：** 打印 `Python 3.x.x`。若无 Python 3，需先用 `raw` 模块装 Python，或改用具备 Python 的镜像。【需要确认】目标机是否已预装 Python 3。

---

### 4.2 免密与连接

#### 步骤 3：配置 SSH 公钥登录

**做什么：** 生成密钥（若尚无）并拷到被管端。

```bash
# 若还没有密钥
ssh-keygen -t ed25519 -C "ansible-control" -f ~/.ssh/id_ed25519 -N ""

# 拷贝公钥（交互输入一次密码）
ssh-copy-id -i ~/.ssh/id_ed25519.pub <USER>@<HOST>

# 验证免密
ssh -i ~/.ssh/id_ed25519 <USER>@<HOST> 'echo ok'
```

**为什么：** Ansible 默认走 SSH；免密是批量自动化的前提。

**预期结果：** 第二次 SSH 不再提示密码，直接输出 `ok`。

#### 步骤 4：编写 `ansible.cfg`

**做什么：** 在项目根目录创建配置，固定 Inventory 路径、并行数、become 等。

**为什么：** 避免每次命令行写一长串参数，并统一团队行为。

```ini
# ansible.cfg（放在项目根，优先于用户级/全局配置）
[defaults]
inventory = ./inventory
remote_user = ubuntu          # 【需要确认】改成你的 SSH 用户
private_key_file = ~/.ssh/id_ed25519
host_key_checking = True      # 生产建议 True；实验室可临时 False
interpreter_python = auto_silent
forks = 10
timeout = 30
# 建议收集 facts；若 playbook 明确 gather_facts: false 可跳过
gathering = implicit
retry_files_enabled = False

[privilege_escalation]
become = True
become_method = sudo
become_user = root
# become_ask_pass = False     # 若 sudo 要密码，改为 True 并在运行时 -K

[ssh_connection]
pipelining = True             # 减少 SSH 往返，提升性能（需 sudoers 允许）
# ssh_args = -o ControlMaster=auto -o ControlPersist=60s
```

**预期结果：** 在项目目录执行 `ansible --version` 时，能看到 `config file = .../ansible.cfg`。

#### 连接插件简述

| 插件 | 用途 |
|------|------|
| `ssh`（默认） | 通过 SSH 管理 Linux/类 Unix |
| `local` | 在控制端本机执行（`hosts: localhost` + `connection: local`） |
| `paramiko` | 纯 Python SSH，特殊环境备用 |
| `winrm` / `psrp` | Windows 主机（本文不展开） |

指定方式示例：在 Inventory 主机变量写 `ansible_connection=local`，或在 Play 里写 `connection: local`。

---

### 4.3 Inventory（主机清单）

#### 步骤 5：用 INI 写静态 Inventory

**做什么：** 定义主机与分组。

```ini
# inventory/hosts.ini
[web]
web1 ansible_host=192.168.1.11
web2 ansible_host=192.168.1.12

[db]
db1 ansible_host=192.168.1.21

[app:children]
web
db

[web:vars]
ansible_user=ubuntu
http_port=80
```

**YAML 等价写法：**

```yaml
# inventory/hosts.yml
all:
  children:
    web:
      hosts:
        web1:
          ansible_host: 192.168.1.11
        web2:
          ansible_host: 192.168.1.12
      vars:
        ansible_user: ubuntu
        http_port: 80
    db:
      hosts:
        db1:
          ansible_host: 192.168.1.21
    app:
      children:
        web:
        db:
```

**为什么：** 分组让 Play 可以只打 `web` 或 `db`；`ansible_host` 把别名与真实 IP 解耦。

**预期结果：**

```bash
ansible-inventory -i inventory/hosts.ini --list
ansible-inventory -i inventory/hosts.ini --graph
```

能看到分组树与变量。

#### host_vars / group_vars

约定目录（与 Inventory 同级或 Inventory 目录旁，Ansible 会自动加载）：

```text
group_vars/
  web.yml          # 或 web/vars.yml
host_vars/
  web1.yml
```

```yaml
# group_vars/web.yml
nginx_worker_processes: 2
site_name: example.local
```

```yaml
# host_vars/web1.yml
nginx_worker_processes: 4   # 覆盖组变量
```

#### 动态 Inventory（概念）

当主机来自云 API、CMDB、Kubernetes 等时，用可执行脚本或 Inventory 插件（如 `amazon.aws.aws_ec2`）在运行时生成清单，而不是手写 IP。入门阶段先掌握静态 Inventory；需要时再查对应 collection 的 Inventory 插件文档。

常用连接相关主机变量：

| 变量 | 含义 |
|------|------|
| `ansible_host` | 真实地址 |
| `ansible_user` | SSH 用户 |
| `ansible_port` | SSH 端口 |
| `ansible_ssh_private_key_file` | 私钥路径 |
| `ansible_python_interpreter` | 远端 Python 路径 |

---

### 4.4 临时命令（ad-hoc）

#### 步骤 6：用 ad-hoc 验证连通并做一次性操作

**做什么：** `ansible <pattern> -m <module> -a <args>`。

**为什么：** 快速探测、应急变更、验证 Inventory；复杂流程应写 Playbook。

```bash
# 连通性（ICMP 不是真 ping，实际是探测 Python/模块通道）
ansible web -i inventory/hosts.ini -m ansible.builtin.ping

# 查看事实摘要
ansible web -m ansible.builtin.setup -a 'filter=ansible_distribution*'

# 执行命令（非幂等，谨慎）
ansible web -m ansible.builtin.command -a 'uptime'
ansible web -m ansible.builtin.shell -a 'echo $HOME && ls /tmp | wc -l'

# 文件与目录
ansible web -m ansible.builtin.file -a 'path=/opt/app state=directory owner=root mode=0755' --become

# 拷贝文件
ansible web -m ansible.builtin.copy -a 'src=./motd dest=/etc/motd' --become

# 包管理（按发行版选模块）
ansible web -m ansible.builtin.apt -a 'name=nginx state=present update_cache=yes' --become   # Debian/Ubuntu
ansible web -m ansible.builtin.dnf -a 'name=nginx state=present' --become                     # RHEL 系新版本
# 旧环境也可能用 yum 模块

# 服务
ansible web -m ansible.builtin.service -a 'name=nginx state=started enabled=yes' --become

# 用户
ansible web -m ansible.builtin.user -a 'name=deploy state=present groups=sudo' --become
```

**预期结果（ping）：**

```text
web1 | SUCCESS => {
    "changed": false,
    "ping": "pong"
}
```

#### 何时用 ad-hoc vs Playbook

| 用 ad-hoc | 用 Playbook |
|-----------|-------------|
| 探活、查 facts、一次性排查 | 多步骤、需复用、需评审 |
| 紧急重启单个服务 | 要幂等、要版本管理 |
| 快速验证模块参数 | 含模板、handler、条件与循环 |

---

### 4.5 Playbook 详解

#### 步骤 7：写第一个 Playbook

**做什么：** 用 YAML 描述「对哪些主机、以什么身份、执行哪些任务」。

```yaml
# playbooks/site.yml
---
- name: Configure web servers
  hosts: web
  become: true
  gather_facts: true

  vars:
    package_name: nginx

  tasks:
    - name: Ensure nginx is installed (Debian family)
      ansible.builtin.apt:
        name: "{{ package_name }}"
        state: present
        update_cache: true
      when: ansible_facts['os_family'] == 'Debian'
      tags: [packages]

    - name: Ensure nginx is installed (RedHat family)
      ansible.builtin.dnf:
        name: "{{ package_name }}"
        state: present
      when: ansible_facts['os_family'] == 'RedHat'
      tags: [packages]

    - name: Ensure nginx is running and enabled
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true
      tags: [service]
```

**运行：**

```bash
ansible-playbook -i inventory/hosts.ini playbooks/site.yml
# 干跑
ansible-playbook -i inventory/hosts.ini playbooks/site.yml --check
# 只跑带 tags 的任务
ansible-playbook -i inventory/hosts.ini playbooks/site.yml --tags packages
# 限制主机
ansible-playbook -i inventory/hosts.ini playbooks/site.yml --limit web1
```

**预期结果：** 首次可能大量 `changed`；再次执行多为 `ok`，体现幂等。

#### YAML 结构要点

- 文件以 `---` 开头（可选但常见）
- Play 是列表项（`- name: ...`）
- `hosts`、`tasks` 是 Play 级关键字
- 缩进必须一致（通常 2 空格）

#### become（提权）

```yaml
become: true
become_user: root
become_method: sudo
```

命令行：`--become` / `-b`，若 sudo 要密码加 `-K`（`--ask-become-pass`）。

#### 条件 `when`

```yaml
- name: Only on Ubuntu
  ansible.builtin.debug:
    msg: "Ubuntu host"
  when: ansible_facts['distribution'] == 'Ubuntu'
```

多条件可用列表（隐式 AND）或用 `and` / `or`。

#### 循环 `loop`

```yaml
- name: Create several directories
  ansible.builtin.file:
    path: "/opt/{{ item }}"
    state: directory
    mode: "0755"
  loop:
    - app
    - data
    - logs
```

#### 注册 `register` 与失败处理

```yaml
- name: Check config syntax
  ansible.builtin.command: nginx -t
  register: nginx_test
  changed_when: false
  failed_when: nginx_test.rc != 0

- name: Show stderr on failure path
  ansible.builtin.debug:
    var: nginx_test.stderr
  when: nginx_test.rc != 0

- name: Ignore non-critical failure
  ansible.builtin.command: /usr/local/bin/optional-tool
  register: optional
  failed_when: false
  # 或：ignore_errors: true
```

常用关键字：`ignore_errors`、`failed_when`、`changed_when`、`any_errors_fatal`、`block` / `rescue` / `always`。

#### tags

给任务打标签后，可用 `--tags` / `--skip-tags` 选择性执行，适合大型 Playbook 分段验证。

---

### 4.6 变量与模板

#### 变量来源（优先级从低到高，简化记忆）

角色默认 `defaults` < Inventory 组变量 < Inventory 主机变量 < Play `vars` / `vars_files` < `-e` 额外变量（最高之一）

> 完整优先级表很长，实践原则：**默认值放 role defaults；环境差异放 group_vars/host_vars；临时覆盖用 `-e`。**

#### vars / vars_files / -e

```yaml
vars:
  site_name: demo.local

vars_files:
  - vars/web.yml
```

```bash
ansible-playbook site.yml -e 'site_name=prod.example.com'
ansible-playbook site.yml -e @extra.yml
```

#### Jinja2 与 `template` 模块

**模板文件** `templates/index.html.j2`：

```html
<!DOCTYPE html>
<html>
<head><title>{{ site_name }}</title></head>
<body>
  <h1>Welcome to {{ site_name }}</h1>
  <p>Managed by Ansible on {{ ansible_facts['hostname'] }}</p>
</body>
</html>
```

**任务：**

```yaml
- name: Deploy index page from template
  ansible.builtin.template:
    src: index.html.j2
    dest: /var/www/html/index.html
    mode: "0644"
  notify: Reload nginx
```

常用语法：`{{ var }}`、`{% if %}`、`{% for %}`、过滤器如 `{{ http_port | default(80) }}`。

---

### 4.7 Handlers 与通知

Handler 是「被通知才运行」的任务，同一 Handler 在一个 Play 中即使被多次 notify，默认也只在末尾执行一次。

```yaml
tasks:
  - name: Deploy nginx site config
    ansible.builtin.template:
      src: site.conf.j2
      dest: /etc/nginx/conf.d/site.conf
    notify: Reload nginx

handlers:
  - name: Reload nginx
    ansible.builtin.service:
      name: nginx
      state: reloaded
```

要点：

- `notify` 的名称必须与 Handler 的 `name` 一致
- 仅当任务报告 `changed` 时才会 notify
- 强制立即执行可用 `meta: flush_handlers`（一般少用）

---

### 4.8 Roles 与目录规范

#### 步骤 8：用 ansible-galaxy 初始化 Role

```bash
ansible-galaxy role init nginx --init-path roles/
# 或在 roles 目录下：ansible-galaxy init nginx
```

典型目录：

```text
roles/nginx/
  defaults/main.yml    # 可被覆盖的默认变量
  vars/main.yml        # 角色内部变量（优先级较高，慎用）
  tasks/main.yml       # 主任务入口
  handlers/main.yml
  templates/
  files/
  meta/main.yml        # 依赖、作者信息
  README.md
```

在 Playbook 中引用：

```yaml
- name: Apply nginx role
  hosts: web
  become: true
  roles:
    - role: nginx
      vars:
        site_name: example.local
```

或在 `tasks` 中：

```yaml
- name: Include nginx role
  ansible.builtin.include_role:
    name: nginx
```

#### Collections 简述

```bash
ansible-galaxy collection install community.general
ansible-galaxy collection list
```

Playbook 里用 FQCN，例如 `community.general.docker_container`。`requirements.yml` 可锁定集合版本，便于团队复现。

---

### 4.9 常用实践

#### 幂等性注意点

- 优先用模块（`copy`/`template`/`apt`/`service`），少用 `shell`/`command`
- 必须用 `command` 时，配合 `creates` / `removes` / `changed_when`
- 模板与配置变更通过 Handler 重启，避免每次无条件重启

#### 敏感信息：ansible-vault 基础

```bash
# 加密文件
ansible-vault create group_vars/web/vault.yml
ansible-vault edit group_vars/web/vault.yml
ansible-vault encrypt_string 'SuperSecret' --name 'db_password'

# 运行时提供密码
ansible-playbook site.yml --ask-vault-pass
ansible-playbook site.yml --vault-password-file ~/.vault_pass.txt
```

不要把明文密码提交到 Git；Vault 密码文件也不要入库。

#### 并行与性能

- `forks`：同时管理的主机数（`ansible.cfg` 或 `-f 20`）
- `pipelining = True`：减少 SSH 连接开销
- 不需要 facts 的 Play 设 `gather_facts: false`
- 用 `--limit` 缩小范围做灰度

#### 干跑与限主机

```bash
ansible-playbook site.yml --check --diff   # 干跑 + 显示文件差异（部分模块支持）
ansible-playbook site.yml --limit 'web:&staging'
ansible-playbook site.yml --list-hosts
ansible-playbook site.yml --list-tasks
ansible-playbook site.yml --syntax-check
```

---

## 5. 完整示例

场景：**批量在 `web` 组主机安装 nginx，用模板部署站点首页与站点配置，启动并设为开机自启。**

示例代码也放在本仓库 `examples/nginx-site/`，可直接复制修改后运行。

### 5.1 目录结构

```text
examples/nginx-site/
  ansible.cfg
  inventory/hosts.ini
  group_vars/web/vars.yml
  site.yml
  roles/nginx/
    defaults/main.yml
    tasks/main.yml
    handlers/main.yml
    templates/index.html.j2
    templates/site.conf.j2
```

### 5.2 关键文件内容

**`ansible.cfg`**

```ini
[defaults]
inventory = ./inventory/hosts.ini
interpreter_python = auto_silent
host_key_checking = True
retry_files_enabled = False
forks = 10

[privilege_escalation]
become = True
become_method = sudo
```

**`inventory/hosts.ini`**

```ini
[web]
# 【需要确认】改成你的真实 IP / 用户
web1 ansible_host=192.168.1.11 ansible_user=ubuntu
# web2 ansible_host=192.168.1.12 ansible_user=ubuntu
```

**`group_vars/web/vars.yml`**

```yaml
site_name: demo.local
site_root: /var/www/demo
listen_port: 80
```

**`roles/nginx/defaults/main.yml`**

```yaml
site_name: example.local
site_root: /var/www/html
listen_port: 80
nginx_package: nginx
nginx_service: nginx
```

**`roles/nginx/tasks/main.yml`**

```yaml
---
- name: Install nginx (Debian family)
  ansible.builtin.apt:
    name: "{{ nginx_package }}"
    state: present
    update_cache: true
  when: ansible_facts['os_family'] == 'Debian'

- name: Install nginx (RedHat family)
  ansible.builtin.dnf:
    name: "{{ nginx_package }}"
    state: present
  when: ansible_facts['os_family'] == 'RedHat'

- name: Ensure site root exists
  ansible.builtin.file:
    path: "{{ site_root }}"
    state: directory
    owner: root
    group: root
    mode: "0755"

- name: Deploy index page
  ansible.builtin.template:
    src: index.html.j2
    dest: "{{ site_root }}/index.html"
    mode: "0644"

- name: Deploy site config
  ansible.builtin.template:
    src: site.conf.j2
    dest: "/etc/nginx/conf.d/{{ site_name }}.conf"
    mode: "0644"
  notify: Reload nginx

- name: Ensure nginx is started and enabled
  ansible.builtin.service:
    name: "{{ nginx_service }}"
    state: started
    enabled: true
```

**`roles/nginx/handlers/main.yml`**

```yaml
---
- name: Reload nginx
  ansible.builtin.service:
    name: "{{ nginx_service }}"
    state: reloaded
```

**`roles/nginx/templates/index.html.j2`**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{{ site_name }}</title>
</head>
<body>
  <h1>{{ site_name }}</h1>
  <p>Host: {{ ansible_facts['hostname'] }}</p>
  <p>Deployed by Ansible.</p>
</body>
</html>
```

**`roles/nginx/templates/site.conf.j2`**

```jinja
server {
    listen {{ listen_port }};
    server_name {{ site_name }};
    root {{ site_root }};
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
```

**`site.yml`**

```yaml
---
- name: Deploy simple nginx site
  hosts: web
  become: true
  gather_facts: true
  roles:
    - nginx
```

### 5.3 执行步骤

1. **改 Inventory**：填入真实 `ansible_host` / `ansible_user`
2. **确保免密 SSH 与 sudo** 可用
3. **语法检查与干跑：**

```bash
cd examples/nginx-site
ansible-playbook site.yml --syntax-check
ansible web -m ansible.builtin.ping
ansible-playbook site.yml --check --diff
```

4. **正式执行：**

```bash
ansible-playbook site.yml
```

5. **验证：**

```bash
ansible web -m ansible.builtin.uri -a 'url=http://127.0.0.1/ return_content=yes' --become
# 或在浏览器 / curl 访问被管机 IP（注意防火墙与 listen_port）【需要确认】
```

**预期结果：** Play 结束无 `failed`；再次执行时配置相关任务多为 `ok`，仅内容变更时出现 `changed` 并触发 Reload。

---

## 6. 常见问题与排查

| 问题现象 | 可能原因 | 解决方法 |
|----------|----------|----------|
| `UNREACHABLE!` / 连接超时 | IP 错、端口错、防火墙、SSH 未启动 | `ssh -vvv USER@HOST` 先手动连通；检查 `ansible_host`/`ansible_port` |
| 权限拒绝 / 多次要密码 | 未配公钥或用户错 | `ssh-copy-id`；核对 `ansible_user` 与私钥 |
| `Missing sudo password` | become 需要密码 | 运行加 `-K`，或配置 NOPASSWD（按安全策略） |
| 模块报 Python 相关错误 | 远端无 Python3 或路径不对 | 安装 `python3`；设 `ansible_python_interpreter` |
| `couldn't resolve module/action` | 集合未安装或 FQCN 写错 | `ansible-galaxy collection install ...`；`ansible-doc -l` 查找 |
| YAML 解析错误 | Tab 缩进、冒号空格、列表横杠 | `--syntax-check`；用编辑器显示空白字符 |
| 任务总是 `changed` | 用了非幂等模块或 `changed_when` 不当 | 改用专用模块；为 command 补 `creates`/`changed_when` |
| Handler 没执行 | 任务未 `changed` 或名字不一致 | 看 notify 名与 handler `name`；确认任务确实变更 |
| apt/dnf 失败 | 源不可用、发行版选错模块 | 先 ad-hoc 手动装包验证；用 `os_family` 分支 |
| `--check` 与真实不一致 | 部分模块不完全支持 check mode | 对关键变更再在小范围真实执行验证 |

排查顺序建议：

1. `ansible all -m ping`
2. `ansible-inventory --graph` / `--host web1`
3. `ansible-playbook ... --syntax-check`
4. 加 `-vvv` 看 SSH 与模块细节
5. 缩小 `--limit` 到单机复现

---

## 7. 注意事项与最佳实践

1. **把基础设施当代码**：Playbook/Role 进 Git；密钥与 Vault 密码不进库。
2. **先干跑再灰度**：`--check` → `--limit` 一台 → 全量。
3. **变量分层**：defaults 给默认；group_vars 表环境；`-e` 只做临时覆盖。
4. **少写 shell**：能用模块就用模块，可维护性与幂等性更好。
5. **Handler 聚合重启**：配置变更 `notify`，避免每个任务都 restart。
6. **明确发行版差异**：Debian 用 `apt`，RHEL 新版本用 `dnf`，用 facts 分支而不是假设全是 Ubuntu。
7. **集合版本锁定**：用 `requirements.yml` + `ansible-galaxy collection install -r` 保证可复现。
8. **生产关闭盲目关闭 host key checking**：`host_key_checking=False` 仅限临时实验。

---

## 8. 总结

### 核心内容回顾

- Ansible 用 Inventory 定义主机，用 Module 执行幂等操作，用 Playbook/Role 编排流程，用 Handler 在变更后触发重启/重载。
- 控制端安装 ansible-core 2.14+，配好 SSH 免密与 `ansible.cfg` 后，先用 `ping` 验证，再写 Playbook。
- 变量与 Jinja2 模板让同一套 Role 适配多环境；Vault 保护密钥。
- 完整 nginx 示例覆盖了安装、模板、Handler、Role 引用的最小闭环。

### 下一步建议

1. 把 `examples/nginx-site` 改成你的真实主机并跑通两遍（观察幂等）
2. 为应用添加 `handlers` + `template` 管理真实配置文件
3. 学习写 `requirements.yml` 管理 collections
4. 深入官方文档：[Ansible Documentation](https://docs.ansible.com/)

---

## 附录 A：常用命令速查

```bash
ansible --version
ansible-inventory -i inventory --graph
ansible web -m ansible.builtin.ping
ansible web -a 'uptime'                          # 默认 command 模块
ansible-doc ansible.builtin.copy                 # 查模块文档
ansible-playbook site.yml
ansible-playbook site.yml --check --diff
ansible-playbook site.yml --limit web1
ansible-playbook site.yml --tags packages
ansible-playbook site.yml -e 'site_name=x'
ansible-playbook site.yml -bK                    # become + 询问 sudo 密码
ansible-galaxy role init myrole
ansible-galaxy collection install -r requirements.yml
ansible-vault create secret.yml
ansible-vault edit secret.yml
```

## 附录 B：常用模块表

| 模块 | 用途 |
|------|------|
| `ansible.builtin.ping` | 连通性探测 |
| `ansible.builtin.setup` | 收集 facts |
| `ansible.builtin.command` / `shell` | 执行命令（慎用） |
| `ansible.builtin.copy` | 拷贝文件 |
| `ansible.builtin.template` | Jinja2 渲染后下发 |
| `ansible.builtin.file` | 文件/目录/权限/软链 |
| `ansible.builtin.lineinfile` / `blockinfile` | 改文本片段 |
| `ansible.builtin.apt` / `dnf` / `yum` | 包管理 |
| `ansible.builtin.service` / `systemd` | 服务管理 |
| `ansible.builtin.user` / `group` | 用户与组 |
| `ansible.builtin.get_url` | 下载文件 |
| `ansible.builtin.git` | 克隆仓库 |
| `ansible.builtin.uri` | HTTP 请求校验 |
| `ansible.builtin.debug` | 打印变量 |
| `ansible.builtin.assert` | 断言条件 |
| `ansible.builtin.include_role` / `import_tasks` | 组合复用 |

## 附录 C：推荐学习路径

1. 装好控制端 → SSH 免密 → `ping` 通一台机
2. 写 10 个 ad-hoc（包、文件、服务、用户）
3. 把 ad-hoc 改写成单个 Playbook，加 `when` / `loop`
4. 抽出 Role，加 template + handler
5. 用 group_vars 区分 staging/production
6. 引入 vault、`--check`、`--limit` 发布习惯
7. 按需学习动态 Inventory 与常用 collections

## 附录 D：文档与示例路径

| 路径 | 说明 |
|------|------|
| `docs/automation/ansible-usage-guide.md` | 本文 |
| `examples/nginx-site/` | 可运行的 nginx 站点示例 |
