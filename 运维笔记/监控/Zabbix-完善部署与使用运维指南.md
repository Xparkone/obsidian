# Zabbix 完善部署与使用运维指南

> 适用基线：Zabbix 7.0 LTS、Ubuntu 24.04 LTS、PostgreSQL、Nginx。文档也给出 Docker Compose 替代路径。
>
> 本文是通用 Runbook，不代表已经在某个真实环境完成部署。主机名、IP、域名、密码、证书、数据库容量、通知地址和阈值必须在落地前替换并经过变更评审。

## 1. 部署目标与架构

Zabbix 由 Server、Frontend、Database、Agent/Agent 2、Proxy 以及可选的 Java gateway、Web service、SNMP trap 进程组成。Server 负责采集调度、触发器计算和事件；Frontend 负责配置与展示；Database 保存配置、历史、趋势和事件。

```text
被监控主机/网络设备
  ├─ Agent 2（主动或被动） ─┐
  ├─ SNMP / IPMI / HTTP / JMX ─┼─> Zabbix Server ─> PostgreSQL
  └─ Zabbix Proxy（跨网络时） ─┘          │
                                         ├─> Frontend(Nginx+PHP-FPM)
                                         ├─> Email/飞书/钉钉/Webhook
                                         └─> Web service（报表，可选）
```

| 组件 | 作用 | 是否必须 |
| --- | --- | --- |
| Zabbix Server | 轮询、接收数据、计算触发器、生成事件 | 是 |
| PostgreSQL | 配置、历史、趋势、事件和审计数据存储 | 是 |
| Frontend | Web 配置、仪表盘、问题和报表 | 是（生产强烈建议） |
| Agent 2 | 采集 Linux/Windows 主机，可扩展插件 | 监控主机时通常需要 |
| Proxy | 在分支/隔离网络采集后转发 | 跨网络或大规模时使用 |
| Java gateway | JMX 监控 | 按需 |
| Web service | 计划报表和无头浏览器渲染 | 按需 |
| SNMP traps | 接收设备主动发送的 Trap | 按需 |

### 1.1 采集模式

| 模式 | 连接方向 | 适合场景 | 关键检查 |
| --- | --- | --- | --- |
| 被动 Agent | Server/Proxy → Agent:10050 | Server 能访问主机 | 防火墙和 `Server=` 来源限制 |
| 主动 Agent | Agent → Server/Proxy:10051 | NAT、云主机、跨网段 | `ServerActive=`、`Hostname=` 精确匹配 |
| Proxy | Agent/设备 → Proxy，Proxy → Server | 分支网络、降低跨地域连接数 | Proxy 数据库、队列和缓存 |
| SNMP | Server/Proxy → 161；Trap → 162 | 交换机、防火墙、UPS | SNMPv3、Trap 解析和事件映射 |

## 2. 版本、容量与端口规划

### 2.1 版本策略

- 本文以 7.0 LTS 为基线；7.4 是当前官方文档中的最新稳定大版本，切换时必须同时切换仓库、软件包、镜像和兼容矩阵。
- 固定大版本和小版本，避免 `latest` 漂移；升级前先做测试环境和数据库备份。
- 使用 Zabbix 官方仓库，不要混用发行版自带的旧包。

### 2.2 参考容量

官方示例中，约 1,000 个监控指标可从 2 vCPU/8 GiB 起步，约 10,000 个指标可从 4 vCPU/16 GiB 起步；实际容量取决于采集间隔、保留周期、触发器、数据库和历史写入量，必须压测后定型。

| 规模 | Server | PostgreSQL | 存储建议 |
| --- | --- | --- | --- |
| 实验/小规模 | 2 vCPU、4–8 GiB | 可同机 | SSD，预留 30 天增长量 |
| 中小生产 | 4–8 vCPU、16 GiB | 独立或托管 | SSD/NVMe，异地备份 |
| 大规模 | Server、DB、Frontend 分离，可增加 Proxy | 独立高性能实例 | 依据写入量、RPO/RTO 和保留周期设计 |

### 2.3 端口

| 端口 | 协议 | 用途 |
| ---: | --- | --- |
| 10050 | TCP | Server/Proxy 访问被动 Agent |
| 10051 | TCP | 主动 Agent、Proxy、sender |
| 80/443 | TCP | Frontend（生产只开放 HTTPS） |
| 161 | UDP/TCP | SNMP 轮询 |
| 162 | UDP | SNMP Trap |
| 5432 | TCP | Server/Frontend → PostgreSQL |
| 10052 | TCP | Server → Java gateway（可选） |
| 12345 | TCP | Server → Web service（按实际配置） |

5432、10050、10051 不应无条件暴露公网；防火墙规则要写明来源 CIDR，并从真实客户端验证。

## 3. 部署前检查

### 3.1 变量表

```bash
export ZBX_FQDN='zabbix.example.com'
export ZBX_SERVER_IP='10.10.10.20'
export ZBX_DB_HOST='10.10.10.21'
export ZBX_TZ='Asia/Shanghai'
```

真实密码不要写入 shell 历史、Git、工单或交接文档；使用交互式提示或权限为 600 的临时文件。

### 3.2 只读预检

```bash
cat /etc/os-release
uname -m
timedatectl status
df -hT
free -h
getent hosts "$ZBX_FQDN" "$ZBX_DB_HOST"
sudo ss -lntup | egrep ':(80|443|5432|10050|10051)\\b' || true
apt-cache policy zabbix-server-pgsql zabbix-frontend-php zabbix-agent2 postgresql nginx
```

确认操作系统、架构、时钟、DNS、路由、防火墙、TLS 证书、备份 RPO/RTO、通知接收人和维护窗口后再安装。

## 4. 原生包部署：Ubuntu 24.04 + PostgreSQL + Nginx

### 4.1 系统依赖

```bash
sudo apt update
sudo apt install -y ca-certificates curl wget gnupg lsb-release \\
  nginx postgresql postgresql-contrib php-fpm php-pgsql php-gd \\
  php-bcmath php-mbstring php-xml php-ldap php-json php-cli
```

Ubuntu 24.04 的 PHP 主版本通常为 8.3；socket 和配置路径以 `ls /run/php/`、`php -v` 的实际结果为准。

### 4.2 Zabbix 官方仓库与软件包

```bash
cd /tmp
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest_7.0+ubuntu24.04_all.deb
sudo dpkg -i zabbix-release_latest_7.0+ubuntu24.04_all.deb
sudo apt update
sudo apt install -y zabbix-server-pgsql zabbix-frontend-php \\
  zabbix-nginx-conf zabbix-sql-scripts zabbix-agent2
```

按需安装 Agent 2 插件：

```bash
sudo apt install -y zabbix-agent2-plugin-postgresql \\
  zabbix-agent2-plugin-mongodb zabbix-agent2-plugin-mssql
```

### 4.3 初始化 PostgreSQL

```bash
sudo systemctl enable --now postgresql
sudo -u postgres psql -c 'select version();'
sudo -u postgres createuser --pwprompt zabbix
sudo -u postgres createdb -O zabbix zabbix
zcat /usr/share/zabbix-sql-scripts/postgresql/server.sql.gz \\
  | sudo -u zabbix psql zabbix
sudo -u postgres psql -d zabbix -c 'select * from dbversion;'
```

如使用 TimescaleDB，必须按目标版本官方说明安装兼容扩展并导入对应 schema，不要直接套用普通 PostgreSQL 命令。

### 4.4 Server 配置

编辑 `/etc/zabbix/zabbix_server.conf`：

```ini
DBHost=localhost
DBName=zabbix
DBUser=zabbix
DBPassword=<数据库密码>
CacheSize=128M
HistoryCacheSize=64M
HistoryIndexCacheSize=32M
ValueCacheSize=64M
Timeout=4
```

缓存值只是小规模起点；应根据日志中的 cache utilisation、数据库压力和内存余量调整。

```bash
sudo chown root:zabbix /etc/zabbix/zabbix_server.conf
sudo chmod 640 /etc/zabbix/zabbix_server.conf
```

### 4.5 Nginx、PHP-FPM 与时区

编辑 `/etc/zabbix/nginx.conf`，替换域名和 PHP socket：

```nginx
server {
    listen 8080;
    server_name zabbix.example.com;
    root /usr/share/zabbix;
    index index.php;

    location / { try_files $uri $uri/ =404; }
    location ~ \\.php$ {
        fastcgi_pass unix:/run/php/php8.3-fpm.sock;
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    }
}
```

在 PHP-FPM 的 `php.ini` 设置：

```ini
date.timezone = Asia/Shanghai
memory_limit = 256M
post_max_size = 16M
upload_max_filesize = 2M
max_execution_time = 300
max_input_time = 300
```

检查并启动：

```bash
sudo nginx -t
sudo systemctl enable --now php8.3-fpm nginx
sudo systemctl restart php8.3-fpm nginx
```

生产环境在 Nginx 前配置 TLS、管理网 ACL、访问日志轮转和安全响应头；不要把 8080 直接暴露公网。

### 4.6 启动 Server 与 Agent 2

```bash
sudo systemctl enable --now zabbix-server zabbix-agent2
sudo systemctl restart zabbix-server zabbix-agent2
sudo systemctl status zabbix-server zabbix-agent2 --no-pager
sudo journalctl -u zabbix-server -n 100 --no-pager
sudo tail -n 100 /var/log/zabbix/zabbix_server.log
```

“启动成功”至少要同时满足：服务 active、日志无数据库错误、Frontend 可访问、UI 中 Server 状态正常、测试主机有新数据。

## 5. Frontend 首次初始化

打开 `http://<Frontend>/` 或正式 HTTPS 域名，向导中填写 PHP 前置检查、PostgreSQL 地址/库名/用户/密码、Server 地址和时区。默认账号通常是 `Admin`，默认密码是 `zabbix`；首次登录后立即改密、启用 MFA（若认证源支持），并创建个人管理员账号。

```bash
curl -fsS -I https://zabbix.example.com/
sudo ss -lntp | egrep ':(80|443|8080)\\b'
sudo -u postgres psql -d zabbix -c 'select count(*) from hosts;'
```

HTTP 200 只证明 Web 层响应；还要检查 UI 的系统信息、队列、数据库和 Server 状态。

## 6. Agent 2 部署与主机注册

### 6.1 Linux Agent 2

```bash
cd /tmp
wget https://repo.zabbix.com/zabbix/7.0/ubuntu/pool/main/z/zabbix-release/zabbix-release_latest_7.0+ubuntu24.04_all.deb
sudo dpkg -i zabbix-release_latest_7.0+ubuntu24.04_all.deb
sudo apt update
sudo apt install -y zabbix-agent2
```

编辑 `/etc/zabbix/zabbix_agent2.conf`：

```ini
Server=10.10.10.20
ServerActive=10.10.10.20:10051
Hostname=<与前端 Host name 完全一致>
RefreshActiveChecks=60
Timeout=3
```

```bash
sudo systemctl enable --now zabbix-agent2
sudo systemctl restart zabbix-agent2
sudo systemctl status zabbix-agent2 --no-pager
sudo ss -lntp | grep ':10050'
```

### 6.2 Windows Agent 2

使用官方 MSI/Agent 2 包安装，填写 `Server`、`ServerActive`、`Hostname` 和 TLS 参数。安装后确认 Windows 服务 Running，并从 Server 或 Proxy 用 `zabbix_get` 验证。

### 6.3 前端注册

在 **Data collection → Hosts** 创建主机：

1. `Host name` 与 Agent `Hostname=` 精确一致；`Visible name` 只用于展示。
2. 添加 Agent interface，地址填真实可达 IP/DNS。
3. 绑定官方 Linux/Windows 模板和 Host groups。
4. 用宏设置主机级阈值，使用标签标记 `env`、`service`、`team`、`severity`。
5. 按要求启用 PSK 或证书加密。

```bash
zabbix_get -s <agent-ip> -p 10050 -k agent.ping
zabbix_get -s <agent-ip> -p 10050 -k system.hostname
```

返回 `1` 或主机名只覆盖两个 key；还要确认 Latest data 时间戳持续更新，并测试 Trigger 的 Problem/OK。

## 7. Proxy、SNMP 与扩展组件

### 7.1 Proxy

Proxy 适合分支、隔离网络和边缘采集。Proxy 使用独立数据库，不能与 Server 共用同一数据库；Proxy、Agent 和前端的名称、模式、TLS 必须一致。

```bash
sudo apt install -y zabbix-proxy-sqlite3 zabbix-agent2
sudoedit /etc/zabbix/zabbix_proxy.conf
```

```ini
Server=10.10.10.20
Hostname=<与前端 Proxy 名称完全一致>
ProxyMode=0
DBName=/var/lib/zabbix/zabbix_proxy.db
ConfigFrequency=60
DataSenderFrequency=1
TLSConnect=psk
TLSPSKIdentity=<非敏感标识>
TLSPSKFile=/etc/zabbix/proxy.psk
```

```bash
sudo chown zabbix:zabbix /etc/zabbix/proxy.psk
sudo chmod 600 /etc/zabbix/proxy.psk
sudo systemctl enable --now zabbix-proxy
sudo journalctl -u zabbix-proxy -n 100 --no-pager
```

创建同名 Proxy 后，把主机的“Monitored by proxy”切换过去，并检查最后配置时间和数据延迟。

### 7.2 SNMP

SNMPv3 优先；SNMPv2c 仅用于隔离网络兼容场景。Trap 必须依次验证设备发送、UDP 162 到达、接收进程/文件、解析规则、主机匹配和事件通知。

```bash
sudo ss -lunp | grep ':162'
sudo tcpdump -ni <interface> udp port 162
```

抓到 UDP 包只能证明网络到达，不能证明已解析并入库。

### 7.3 JMX、Web service 和自定义脚本

JMX 监控使用 Java gateway；计划报表使用 Web service 和受支持的浏览器；UserParameter、远程命令和外部脚本默认关闭，启用前逐项审核、限制参数和文件权限。

## 8. 模板、业务探针与告警

### 8.1 模板与标签

优先官方模板，通过继承、宏和标签复用配置。建议标签：

```text
env=prod|staging|dev
service=<服务名>
team=<责任团队>
severity=warning|high|disaster
```

### 8.2 监控对象

- Linux：CPU load、内存、swap、文件系统、inode、磁盘延迟、网络错误、进程和 systemd 服务。
- Windows：服务、事件日志、磁盘、IIS、SQL Server 和系统资源。
- 网络设备：接口、CPU、内存、电源、风扇、温度、链路状态。
- HTTP/业务：状态码、响应时间、关键 JSON 字段、证书有效期、错误率；不要只检查 TCP 端口。

### 8.3 告警动作

在 **Alerts → Media types** 配置 SMTP、Webhook、飞书/钉钉等。密钥和 Webhook URL 使用 Secret/宏或外部密钥管理。

```text
env=prod AND severity in (high, disaster) -> 值班群/电话
service=database -> DBA 群
severity=warning -> 工单或工作日邮件
```

Trigger 使用 `for` 过滤抖动，设置明确恢复条件和依赖关系；维护窗口使用 Maintenance，不要长期禁用 Trigger。验收时用测试主机产生可恢复事件，验证 Problem、去重、通知、恢复、静默和升级。

## 9. 数据保留、数据库维护与备份

### 9.1 保留周期

在 **Data collection → Hosts/Templates → History and trend storage period** 设置历史和趋势周期。历史数据粒度高、增长快；趋势适合长期图表。周期必须依据磁盘、合规和查询需求计算。

### 9.2 PostgreSQL 检查

```bash
sudo -u postgres psql -d zabbix -c "select pg_size_pretty(pg_database_size('zabbix'));"
sudo -u postgres psql -d zabbix -c "select state,count(*) from pg_stat_activity group by state;"
```

启用并检查 autovacuum；慢查询、大表膨胀和 checkpoint 压力由 DBA 结合 PostgreSQL 版本治理，不要照搬网上参数。

### 9.3 备份与恢复演练

```bash
install -d -m 700 /var/backups/zabbix
sudo -u postgres pg_dump -Fc zabbix > /var/backups/zabbix/zabbix-$(date +%F).dump
chmod 600 /var/backups/zabbix/*.dump
```

隔离库恢复：

```bash
createdb -O zabbix zabbix_restore_test
pg_restore --exit-on-error -d zabbix_restore_test /var/backups/zabbix/zabbix-<日期>.dump
psql -d zabbix_restore_test -c 'select * from dbversion;'
```

同时备份 `/etc/zabbix/`（脱敏后）、Frontend 自定义配置、证书/PSK（按密钥管理规范）、外部脚本和部署清单。备份文件应加密并放到独立故障域。

## 10. 升级与回滚

升级前记录包版本、配置差异、模板导出、数据库备份、维护窗口和回滚负责人：

```bash
zabbix_server --version
zabbix_agent2 --version
apt-cache policy zabbix-server-pgsql
sudo -u postgres pg_dump -Fc zabbix > /var/backups/zabbix/pre-upgrade.dump
```

小版本升级：

```bash
sudo apt update
sudo apt install --only-upgrade 'zabbix*'
sudo systemctl restart zabbix-server zabbix-agent2 php8.3-fpm nginx
sudo journalctl -u zabbix-server -n 100 --no-pager
```

数据库迁移通常不是简单降级包即可回滚；失败时依据官方升级说明和已验证备份恢复方案处理，不能让旧二进制直接连接已迁移的生产库。

## 11. Docker Compose 替代部署

适合实验、演示和容器化隔离场景；生产还要设计持久卷、备份、镜像供应链、TLS、资源限制和升级演练。

```bash
git clone https://github.com/zabbix/zabbix-docker.git
cd zabbix-docker
git checkout 7.0
docker compose -f ./compose_pgsql.yaml up -d
docker compose -f ./compose_pgsql.yaml ps
docker compose -f ./compose_pgsql.yaml logs -f zabbix-server-pgsql
```

固定到具体 7.0.x 镜像，避免 `latest` 漂移。停止时不要误用 `docker compose down -v`；它会删除卷，删除前必须完成独立备份并获得审批。

## 12. 验收清单

### 12.1 基础设施

- [ ] OS、Zabbix、PHP、Nginx、PostgreSQL 版本已记录。
- [ ] NTP、DNS、TLS、防火墙和数据库 ACL 已验证。
- [ ] 5432、10050、10051 未暴露到不必要网络。
- [ ] 数据库备份已执行并完成隔离恢复抽测。

### 12.2 Zabbix

- [ ] Server、Agent 2、Nginx、PHP-FPM 为 active。
- [ ] Frontend 登录成功，Server 状态绿色，队列无持续堆积。
- [ ] 测试主机 Latest data 持续刷新。
- [ ] Trigger 能产生 Problem、通知和恢复事件。
- [ ] 维护窗口、静默、分组和责任人路由有效。

### 12.3 端到端证据

```bash
zabbix_get -s <agent-ip> -k agent.ping
curl -fsS https://zabbix.example.com/ >/dev/null
sudo -u postgres psql -d zabbix -c \\
  "select count(*) from events where clock > extract(epoch from now()-interval '10 minutes');"
```

端到端验收必须同时观察 UI、Server 日志、数据库事件、通知接收端和恢复通知；端口监听或 HTTP 200 不是监控成功的充分条件。

## 13. 常见故障排查

### 13.1 Server 启动失败

```bash
sudo systemctl status zabbix-server --no-pager
sudo journalctl -u zabbix-server -b --no-pager
sudo tail -n 200 /var/log/zabbix/zabbix_server.log
sudo -u zabbix psql -h <db-host> -U zabbix -d zabbix -c 'select 1;'
```

重点检查数据库密码、`DBHost`、`pg_hba.conf`、schema、版本迁移、SELinux/AppArmor 和磁盘空间。

### 13.2 Frontend 数据库错误

检查 PHP `pgsql` 扩展、FPM socket、Nginx error log、数据库 ACL 和 Frontend 配置。登录页可打开不代表后台查询正常。

### 13.3 Agent 灰色或无数据

1. 前端 Host name 与 Agent `Hostname=` 是否完全一致。
2. 被动模式是否可达 10050；主动模式是否可达 10051。
3. `ServerActive=`、TLS 模式、PSK identity 和文件权限是否一致。
4. Agent 日志是否有 active checks、DNS、权限或 UserParameter 错误。

```bash
sudo journalctl -u zabbix-agent2 -n 100 --no-pager
nc -vz <server-ip> 10051
nc -vz <agent-ip> 10050
```

### 13.4 队列堆积或数据延迟

检查 UI 队列、Server 日志、数据库 CPU/IO、poller/trapper 数量、采集超时、Proxy 缓存和丢包。不要只提高进程数，过度并发可能压垮 PostgreSQL。

### 13.5 告警未发送

确认 Trigger 已产生事件、Action 条件匹配、用户 Media 生效、时间段允许发送、媒体类型无错误、Webhook/SMTP 网络可达。保留事件 ID、日志和接收端响应作为证据。

### 13.6 SNMP Trap 无事件

逐层检查设备配置、UDP 162、接收文件/进程、解析规则、主机接口和事件映射。抓包到达不等于已解析入库。

## 14. 日常运维命令速查

```bash
systemctl status zabbix-server zabbix-agent2 nginx postgresql --no-pager
journalctl -u zabbix-server -f
journalctl -u zabbix-agent2 -f
ss -lntup | egrep ':(80|443|5432|10050|10051)\\b'
ps -ef | grep '[z]abbix'
zabbix_get -s <agent-ip> -k agent.ping
sudo -u postgres psql -d zabbix -c "select pg_size_pretty(pg_database_size('zabbix'));"
```

## 15. 参考资料与版本边界

- [Zabbix 7.0 安装要求](https://www.zabbix.com/documentation/7.0/en/manual/installation/requirements)
- [Zabbix 7.0 从软件包安装](https://www.zabbix.com/documentation/7.0/en/manual/installation/install_from_packages)
- [Ubuntu 24.04 + PostgreSQL + Nginx 官方安装向导](https://www.zabbix.com/ru/download?components=server_frontend_agent_2&db=pgsql&os_distribution=ubuntu&os_version=24.04&ws=nginx&zabbix=7.0)
- [Zabbix Web 界面安装](https://www.zabbix.com/documentation/7.0/en/manual/installation/frontend)
- [Zabbix 容器安装](https://www.zabbix.com/documentation/7.0/en/manual/installation/containers)
- [Zabbix Docker 官方仓库](https://github.com/zabbix/zabbix-docker)

正式部署前重新选择目标操作系统、数据库和 Web server，核对官方生成的命令；本文地址、端口、缓存、保留周期、阈值和示例域名均不应直接视为生产配置。
