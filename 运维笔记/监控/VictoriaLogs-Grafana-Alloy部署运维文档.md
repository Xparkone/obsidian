# VictoriaLogs + Grafana + Alloy 日志平台部署运维文档

## 1. 部署目标

本方案在一台 CentOS/Linux 服务器上通过 Docker Compose 部署以下组件：

- VictoriaLogs：日志存储与查询，保留 30 天。
- Grafana：日志查询与可视化。
- Grafana Alloy：采集 Docker 容器标准输出，以及宿主机二进制/Omnibus GitLab 的文件日志。
- VictoriaLogs Grafana Datasource：让 Grafana 使用 LogsQL 查询 VictoriaLogs。

当前服务访问关系：

```text
Docker stdout/stderr ─┐
                     ├─> Alloy ─> VictoriaLogs ─> Grafana
/var/log/gitlab ─────┘
```

内部端口：

| 服务 | 容器端口 | 宿主机监听 | 用途 |
| --- | ---: | --- | --- |
| VictoriaLogs | 9428 | `127.0.0.1:9428` | 健康检查和本机查询 |
| Alloy | 12345 | `127.0.0.1:12345` | Alloy UI 和健康状态 |
| Grafana | 3000 | `0.0.0.0:3001` | Web 页面 |

当前 Grafana 地址：

```text
http://118.195.216.215:3001/
```

## 2. 当前目录结构

部署根目录为 `/root/docker`：

```text
/root/docker/
├── .env
├── docker-compose.yaml
├── alloy/
│   └── config.alloy
├── grafana/
│   └── provisioning/
│       ├── dashboards/
│       └── datasources/
│           └── victorialogs.yml
├── secrets/
│   └── grafana_admin_password.txt
└── data/
    ├── alloy/
    ├── grafana/
    └── victorialogs/
```

创建目录：

```bash
mkdir -p /root/docker/{alloy,secrets}
mkdir -p /root/docker/data/{alloy,grafana,victorialogs}
mkdir -p /root/docker/grafana/provisioning/{datasources,dashboards}
```

## 3. 固定镜像版本

创建 `/root/docker/.env`：

```dotenv
LOKI_IMAGE=grafana/loki:3.7.2
ALLOY_IMAGE=grafana/alloy:v1.18.0
GRAFANA_IMAGE=grafana/grafana:13.1.0
VICTORIALOGS_IMAGE=victoriametrics/victoria-logs:v1.50.0
```

说明：当前 Compose 未使用 `LOKI_IMAGE`，保留该变量不影响运行。VictoriaLogs 从 v1.25.0 起，镜像标签不再包含 `-victorialogs` 后缀。

## 4. Grafana 管理员密码

不要使用 `123456` 等弱密码，也不要把真实密码提交到 Git。

```bash
cd /root/docker
chmod 700 secrets
read -s -p "设置 Grafana 管理员密码: " GRAFANA_PASSWORD
echo
printf '%s' "$GRAFANA_PASSWORD" > secrets/grafana_admin_password.txt
unset GRAFANA_PASSWORD
chmod 600 secrets/grafana_admin_password.txt
```

该密码仅用于数据库首次初始化。Grafana 已初始化后，如需修改密码：

```bash
docker compose exec grafana \
  grafana cli admin reset-admin-password '新的强密码'
```

## 5. Docker Compose 配置

创建 `/root/docker/docker-compose.yaml`：

```yaml
name: victorialogs-logging

services:
  victorialogs:
    image: ${VICTORIALOGS_IMAGE}
    command:
      - -storageDataPath=/victoria-logs-data
      - -retentionPeriod=30d
      - -httpListenAddr=:9428
    restart: unless-stopped
    volumes:
      - ./data/victorialogs:/victoria-logs-data
    ports:
      - "127.0.0.1:9428:9428"
    networks: [logging]
    logging: &local-logging
      driver: local
      options:
        max-size: "20m"
        max-file: "3"

  alloy:
    image: ${ALLOY_IMAGE}
    command:
      - run
      - --server.http.listen-addr=0.0.0.0:12345
      - --storage.path=/var/lib/alloy/data
      - /etc/alloy/config.alloy
    restart: unless-stopped
    user: "0:0"
    volumes:
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - ./data/alloy:/var/lib/alloy/data
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /var/log/gitlab:/var/log/gitlab:ro
    ports:
      - "127.0.0.1:12345:12345"
    depends_on: [victorialogs]
    networks: [logging]
    logging: *local-logging

  grafana:
    image: ${GRAFANA_IMAGE}
    restart: unless-stopped
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD__FILE: /run/secrets/grafana_admin_password
      GF_USERS_ALLOW_SIGN_UP: "false"
    secrets: [grafana_admin_password]
    volumes:
      - ./data/grafana:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    ports:
      - "3001:3000"
    depends_on: [victorialogs]
    networks: [logging]
    logging: *local-logging

networks:
  logging:
    driver: bridge

secrets:
  grafana_admin_password:
    file: ./secrets/grafana_admin_password.txt
```

### 5.1 关键挂载说明

挂载格式为：

```text
宿主机路径:容器内路径:权限
```

- `/var/run/docker.sock`：让 Alloy 通过 Docker API 自动发现容器并读取 stdout/stderr。即使设置只读，该 socket 仍属于高权限资源，只能挂载给可信镜像。
- `/var/log/gitlab`：让容器内 Alloy 读取同一宿主机的 GitLab 日志文件。
- `./data/alloy`：保存文件读取位置，避免 Alloy 重启后重复采集。
- `./data/grafana`、`./data/victorialogs`：持久化 Grafana 与 VictoriaLogs 数据。

如果 GitLab 位于另一台服务器，本机 bind mount 无法读取远程文件，必须在 GitLab 服务器部署 Alloy，再通过受保护的网络写入 VictoriaLogs。

## 6. Alloy 采集配置

创建 `/root/docker/alloy/config.alloy`：

```alloy
logging {
  level = "info"
}

discovery.docker "local" {
  host = "unix:///var/run/docker.sock"
}

discovery.relabel "containers" {
  targets = discovery.docker.local.targets

  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }
}

loki.source.docker "containers" {
  host          = "unix:///var/run/docker.sock"
  targets       = discovery.docker.local.targets
  relabel_rules = discovery.relabel.containers.rules
  forward_to    = [loki.write.victorialogs.receiver]
}

loki.write "victorialogs" {
  endpoint {
    url = "http://victorialogs:9428/insert/loki/api/v1/push"
  }
}

loki.source.file "gitlab" {
  targets = [
    {
      __path__ = "/var/log/gitlab/**/*.log",
      job      = "gitlab",
    },
    {
      __path__ = "/var/log/gitlab/**/current",
      job      = "gitlab",
    },
  ]

  forward_to = [loki.write.victorialogs.receiver]

  file_match {
    enabled = true
  }
}
```

该配置采集：

1. 当前 Docker daemon 管理的所有容器标准输出和标准错误。
2. `/var/log/gitlab` 下的 `*.log` 文件。
3. GitLab runit 服务使用的无扩展名 `current` 文件。

不会自动采集 `/var/log/messages`、`/var/log/secure`、systemd journal 或其他普通文件。如需采集，必须继续增加 `loki.source.file` 或 journal 采集组件。

## 7. Grafana 数据源插件

Grafana 需要安装 `victoriametrics-logs-datasource`。国内服务器直接配置 `GF_INSTALL_PLUGINS` 可能因网络阻塞整个启动流程，因此推荐手动下载、持久化安装。

### 7.1 获取最新版本并下载

在能访问 GitHub 的机器执行：

```bash
PLUGIN_VERSION=$(
  wget -qO- \
    https://api.github.com/repos/VictoriaMetrics/victorialogs-datasource/releases/latest |
  grep '"tag_name"' |
  head -1 |
  cut -d'"' -f4
)

echo "$PLUGIN_VERSION"

wget \
  "https://github.com/VictoriaMetrics/victorialogs-datasource/releases/download/${PLUGIN_VERSION}/victoriametrics-logs-datasource-${PLUGIN_VERSION}.tar.gz" \
  -O /tmp/victoriametrics-logs-datasource.tar.gz
```

如果使用中转机：

```bash
scp /tmp/victoriametrics-logs-datasource.tar.gz \
  root@118.195.216.215:/tmp/
```

### 7.2 解压到 Grafana 持久化目录

```bash
mkdir -p /root/docker/data/grafana/plugins
tar -xzf /tmp/victoriametrics-logs-datasource.tar.gz \
  -C /root/docker/data/grafana/plugins
chown -R 472:0 /root/docker/data/grafana/plugins
```

检查：

```bash
find /root/docker/data/grafana/plugins \
  -maxdepth 2 -name plugin.json -print
```

## 8. Grafana 数据源自动配置

创建 `/root/docker/grafana/provisioning/datasources/victorialogs.yml`：

```yaml
apiVersion: 1

datasources:
  - name: VictoriaLogs
    uid: victorialogs
    type: victoriametrics-logs-datasource
    access: proxy
    url: http://victorialogs:9428
    isDefault: true
    editable: true
```

这里必须使用 Compose 服务名 `victorialogs`。在 Grafana 容器中，`127.0.0.1` 指向 Grafana 自己，不能用于访问 VictoriaLogs。

## 9. 权限处理

Grafana 容器以 UID 472 运行，数据目录必须可写：

```bash
chown -R 472:0 /root/docker/data/grafana
chmod -R u+rwX,g+rwX /root/docker/data/grafana
```

不要使用 `chmod -R 777`。

如果 CentOS 的 SELinux 为 `Enforcing`，可按需给普通 bind mount 添加 `:Z` 或共享目录添加 `:z`。例如：

```yaml
- ./data/grafana:/var/lib/grafana:Z
- ./grafana/provisioning:/etc/grafana/provisioning:ro,Z
- /var/log/gitlab:/var/log/gitlab:ro,z
```

不要随意给 `/var/lib/docker/containers` 添加 `:Z`，以免改变 Docker 自身目录的 SELinux 标签。

## 10. 启动部署

```bash
cd /root/docker

# 检查环境变量和最终配置
docker compose config

# 拉取镜像
docker compose pull

# 启动
docker compose up -d

# 查看状态
docker compose ps
```

预期状态：

```text
alloy          Up   127.0.0.1:12345->12345/tcp
grafana        Up   0.0.0.0:3001->3000/tcp
victorialogs   Up   127.0.0.1:9428->9428/tcp
```

## 11. 部署验证

### 11.1 VictoriaLogs

```bash
curl -fsS http://127.0.0.1:9428/health
```

预期：

```text
OK
```

### 11.2 Alloy

```bash
curl -fsS http://127.0.0.1:12345/-/ready
docker compose logs --tail=100 alloy
```

确认 Docker socket：

```bash
docker compose exec alloy test -S /var/run/docker.sock \
  && echo "Docker socket 已挂载"
```

确认 GitLab 文件可见：

```bash
docker compose exec alloy \
  sh -c 'find /var/log/gitlab -maxdepth 2 -type f | head -30'
```

### 11.3 Grafana

```bash
curl -fsS http://127.0.0.1:3001/api/health
```

预期包含：

```json
{
  "database": "ok",
  "version": "13.1.0"
}
```

公网验证：

```bash
curl -I http://118.195.216.215:3001/login
```

### 11.4 查询 Docker 日志

```bash
curl -fsS -G \
  http://127.0.0.1:9428/select/logsql/query \
  --data-urlencode 'query=*' \
  --data-urlencode 'limit=5'
```

### 11.5 查询 GitLab 日志

```bash
curl -fsS -G \
  http://127.0.0.1:9428/select/logsql/query \
  --data-urlencode 'query=job:="gitlab"' \
  --data-urlencode 'limit=5'
```

## 12. Grafana 常用 LogsQL

在 Grafana 中进入 `Explore`，选择 `VictoriaLogs` 数据源。

全部日志：

```logsql
*
```

全部 GitLab 日志：

```logsql
job:="gitlab"
```

GitLab Rails：

```logsql
job:="gitlab" AND filename:~"gitlab-rails"
```

排除频繁的 metrics 请求：

```logsql
job:="gitlab" AND NOT _msg:="/-/metrics"
```

HTTP 4xx/5xx：

```logsql
job:="gitlab" AND _msg:~"Completed (4|5)[0-9]{2}"
```

结构化错误：

```logsql
job:="gitlab" AND level:~"(?i)error|fatal"
```

指定容器：

```logsql
container:="victorialogs-logging-alloy-1"
```

### `unknown` 与 `missing _msg field`

- `unknown`：日志没有标准级别字段，Grafana 无法归类为 info/error 等，不代表异常。
- `missing _msg field`：部分 GitLab JSON 日志只有结构化字段，没有 VictoriaLogs 推荐的 `_msg` 字段；其他字段仍然可查询，不表示日志丢失。
- `Started GET "/-/metrics"`、`Completed 200 OK`：通常是 GitLab 内部监控请求，属于正常日志。

## 13. 常见故障

### 13.1 Compose 提示镜像变量为空

症状：

```text
service has neither an image nor a build context specified
```

处理：检查 `/root/docker/.env`，然后运行：

```bash
docker compose config
```

### 13.2 Docker Hub 超时

症状：

```text
Client.Timeout exceeded while awaiting headers
```

处理：配置可靠的 Docker Hub mirror、Docker daemon 网络代理，或在境外/联网机器同步镜像到国内私有仓库。降低并发也有帮助：

```json
{
  "registry-mirrors": ["https://你的镜像加速地址"],
  "max-concurrent-downloads": 2,
  "max-download-attempts": 5
}
```

### 13.3 Grafana 密码文件不存在

症状：

```text
bind source path does not exist: ...grafana_admin_password.txt
```

处理：创建密码文件并设置 `600` 权限，见第 4 节。

### 13.4 Alloy 配置文件被误建为目录

症状：

```text
not a directory: Are you trying to mount a directory onto a file
```

确认：

```bash
file /root/docker/alloy/config.alloy
```

必须是普通文件，而不是目录。

### 13.5 Grafana 数据目录不可写

症状：

```text
GF_PATHS_DATA='/var/lib/grafana' is not writable
Permission denied
```

处理：

```bash
chown -R 472:0 /root/docker/data/grafana
chmod -R u+rwX,g+rwX /root/docker/data/grafana
```

### 13.6 Grafana 端口存在但连接被重置

如果日志卡在插件下载：

```text
Installing plugin pluginId=victoriametrics-logs-datasource
```

不要通过 `GF_INSTALL_PLUGINS` 在线安装。移除该变量，先让 Grafana 启动，再按照第 7 节手动安装插件。

### 13.7 Alloy 无法连接 Docker socket

症状：

```text
dial unix /var/run/docker.sock: connect: no such file or directory
```

处理：在 Alloy volumes 中添加：

```yaml
- /var/run/docker.sock:/var/run/docker.sock:ro
```

然后重建 Alloy：

```bash
docker compose up -d --force-recreate alloy
```

### 13.8 GitLab 查询无数据

依次检查：

```bash
test -d /var/log/gitlab && echo OK
docker compose exec alloy find /var/log/gitlab -maxdepth 2 -type f | head
docker compose logs --since=10m alloy | grep -Ei 'error|permission|failed'
```

GitLab 的主要服务日志除了 `*.log`，还包括 `**/current`，两类都必须配置。

## 14. 日常运维

状态与日志：

```bash
cd /root/docker
docker compose ps
docker compose logs --tail=100 victorialogs
docker compose logs --tail=100 alloy
docker compose logs --tail=100 grafana
```

修改 Alloy 配置后先验证：

```bash
docker compose exec alloy \
  /bin/alloy validate /etc/alloy/config.alloy
docker compose restart alloy
```

停止与启动：

```bash
docker compose stop
docker compose start
```

更新固定版本时：

```bash
vi .env
docker compose pull
docker compose up -d
```

升级前应备份 `data/` 和配置文件。

## 15. 安全建议

1. 立即更换已经公开或过弱的 Grafana 管理员密码。
2. 公网 `3001` 只允许可信来源 IP，最好使用 Nginx/Caddy HTTPS 反向代理，然后将 Grafana 重新绑定到 `127.0.0.1`。
3. VictoriaLogs `9428` 当前只监听本机，保持该设置；不要在无认证的情况下暴露到公网。
4. Alloy `12345` 当前只监听本机，保持该设置。
5. Docker socket 权限很高，不要给不可信容器挂载。
6. 不要把 `secrets/`、`data/`、插件压缩包或真实密码提交到 Git。
7. 定期检查磁盘：

```bash
df -h
du -sh /root/docker/data/*
docker system df
```

## 16. 当前配置备份

排障过程中已创建过以下备份：

```text
/root/docker/docker-compose.yaml.bak-20260805-plugin
/root/docker/docker-compose.yaml.bak-20260805-docker-sock
/root/docker/alloy/config.alloy.bak-20260805-gitlab-current
```

恢复前必须先比较差异，不建议直接覆盖当前配置：

```bash
diff -u docker-compose.yaml.bak-20260805-docker-sock docker-compose.yaml
diff -u alloy/config.alloy.bak-20260805-gitlab-current alloy/config.alloy
```
