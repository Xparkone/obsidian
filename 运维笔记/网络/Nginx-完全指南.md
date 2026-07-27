# Nginx 完全指南

> Nginx (engine x) 是高性能的 HTTP 和反向代理服务器，也是 IMAP/POP3/SMTP 代理服务器。  
> 官网：https://nginx.org | 文档：https://nginx.org/en/docs/

---

## 一、是什么

Nginx 是一个**事件驱动**的异步非阻塞 Web 服务器，核心优势：

| 特性 | 说明 |
|------|------|
| 高并发 | 单机轻松支撑数万并发连接（C10K/C100K） |
| 低内存 | 每个连接仅占用少量内存 |
| 反向代理 | 最常用的反向代理和负载均衡器 |
| 静态文件 | 极致性能的静态文件服务 |
| 模块化 | 丰富的第三方模块生态 |

**典型使用场景**：反向代理、负载均衡、静态资源服务、SSL 终端、WebSocket 代理、HTTP 缓存、限流、访问控制。

---

## 二、安装

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install nginx -y

# CentOS/RHEL
sudo yum install nginx -y
# 或
sudo dnf install nginx -y

# macOS
brew install nginx

# Docker
docker run -d --name nginx -p 80:80 nginx:alpine

# 验证安装
nginx -v
nginx -t          # 测试配置文件语法
```

---

## 三、核心命令

```bash
nginx                  # 启动
nginx -s stop          # 快速停止
nginx -s quit          # 优雅停止（处理完当前请求）
nginx -s reload        # 热重载配置（不中断服务）
nginx -s reopen        # 重新打开日志文件
nginx -t               # 检查配置文件语法
nginx -T               # 检查配置并打印所有配置
nginx -V               # 查看编译参数和版本
systemctl start nginx  # systemd 启动
systemctl enable nginx # 开机自启
```

---

## 四、配置文件结构

```bash
# 主配置文件
/etc/nginx/nginx.conf

# 站点配置目录
/etc/nginx/conf.d/        # 通用配置
/etc/nginx/sites-enabled/  # 已启用站点（Ubuntu）
/etc/nginx/sites-available/ # 可用站点（Ubuntu）
```

### nginx.conf 基本结构

```nginx
# 全局块
user nginx;
worker_processes auto;        # 工作进程数，auto = CPU 核心数
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

# events 块
events {
    worker_connections 1024;  # 每个 worker 最大连接数
    use epoll;                # Linux 推荐 epoll
    multi_accept on;          # 一次接受多个连接
}

# http 块
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # 日志格式
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';
    access_log /var/log/nginx/access.log main;

    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    gzip on;

    # 引入站点配置
    include /etc/nginx/conf.d/*.conf;
    include /etc/nginx/sites-enabled/*;
}
```

---

## 五、静态文件服务

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    root /var/www/html;
    index index.html index.htm;

    # 静态文件
    location / {
        try_files $uri $uri/ =404;
    }

    # 图片缓存 30 天
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|woff|woff2)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # 禁止访问隐藏文件
    location ~ /\. {
        deny all;
    }
}
```

---

## 六、反向代理

```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://localhost:8080;          # 后端地址
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 超时设置
        proxy_connect_timeout 30s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;

        # 缓冲设置
        proxy_buffering off;                       # WebSocket 建议关闭
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }
}
```

### 路径重写

```nginx
# 去除 /api 前缀
location /api/ {
    proxy_pass http://localhost:8080/;  # 注意末尾 /
    # /api/user → /user
}

# 保留前缀
location /api/ {
    proxy_pass http://localhost:8080;   # 无末尾 /
    # /api/user → /api/user
}
```

---

## 七、负载均衡

```nginx
# 定义上游服务器组
upstream backend {
    # 轮询（默认）
    server 192.168.1.10:8080;
    server 192.168.1.11:8080;
    server 192.168.1.12:8080 backup;    # 备份，其他都挂了才用
}

server {
    listen 80;
    location / {
        proxy_pass http://backend;
    }
}
```

### 负载均衡策略

```nginx
upstream backend {
    # 1. 轮询（默认）
    # server 192.168.1.10:8080;
    # server 192.168.1.11:8080;

    # 2. 加权轮询
    server 192.168.1.10:8080 weight=3;
    server 192.168.1.11:8080 weight=1;

    # 3. IP Hash（同一客户端固定到同一后端）
    ip_hash;
    # server 192.168.1.10:8080;
    # server 192.168.1.11:8080;

    # 4. 最少连接
    least_conn;
    # server 192.168.1.10:8080;
    # server 192.168.1.11:8080;

    # 5. 一致性哈希（需要 ngx_http_upstream_hash_module）
    # hash $request_uri consistent;
    # server 192.168.1.10:8080;
    # server 192.168.1.11:8080;
}
```

### 健康检查

```nginx
upstream backend {
    server 192.168.1.10:8080 max_fails=3 fail_timeout=30s;
    server 192.168.1.11:8080 max_fails=3 fail_timeout=30s;
    server 192.168.1.12:8080 down;   # 标记为下线
}
```

| 参数 | 说明 |
|------|------|
| `max_fails=3` | 30 秒内失败 3 次标记为不可用 |
| `fail_timeout=30s` | 不可用 30 秒后重新尝试 |
| `down` | 永久下线 |
| `backup` | 备用服务器 |

---

## 八、HTTPS / SSL

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    # 证书
    ssl_certificate     /etc/nginx/ssl/example.com.pem;
    ssl_certificate_key /etc/nginx/ssl/example.com.key;

    # 安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
    ssl_stapling_verify on;

    location / {
        proxy_pass http://localhost:8080;
    }
}

# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}
```

### Let's Encrypt 自动证书

```bash
# 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 自动配置证书
sudo certbot --nginx -d example.com -d www.example.com

# 自动续期（已内置定时任务）
sudo certbot renew --dry-run
```

---

## 九、WebSocket 代理

```nginx
server {
    listen 80;
    server_name ws.example.com;

    location /ws {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 86400s;   # 长连接超时
    }
}
```

---

## 十、Gzip 压缩

```nginx
http {
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;          # 最小压缩字节
    gzip_comp_level 6;             # 压缩级别 1-9（6 是平衡点）
    gzip_types
        text/plain
        text/css
        text/javascript
        application/javascript
        application/json
        application/xml
        image/svg+xml;
    gzip_proxied any;              # 对所有代理请求压缩
    gzip_disable "msie6";          # 禁用 IE6
}
```

---

## 十一、缓存

### 代理缓存

```nginx
http {
    # 缓存路径，10MB 内存索引，最大 1GB 磁盘
    proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=my_cache:10m
                     max_size=1g inactive=60m use_temp_path=off;

    server {
        location /api/ {
            proxy_cache my_cache;
            proxy_cache_valid 200 302 10m;   # 200/302 缓存 10 分钟
            proxy_cache_valid 404 1m;
            proxy_cache_key "$scheme$request_method$host$request_uri";
            proxy_cache_bypass $http_cache_control;  # 客户端强制刷新
            add_header X-Cache-Status $upstream_cache_status;

            proxy_pass http://localhost:8080;
        }
    }
}
```

### 浏览器缓存

```nginx
location ~* \.(jpg|jpeg|png|gif|ico|css|js)$ {
    expires 30d;
    add_header Cache-Control "public, max-age=2592000";
}
```

---

## 十二、限流

### 请求频率限制

```nginx
http {
    # 限流区域：binary_remote_addr 为 key，10MB 内存，每秒 10 请求
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

    # 连接数限制
    limit_conn_zone $binary_remote_addr zone=conn_limit:10m;

    server {
        location /api/ {
            limit_req zone=api_limit burst=20 nodelay;  # 突发 20，超过立即拒绝
            limit_conn conn_limit 10;                     # 每 IP 最多 10 并发
            limit_rate 100k;                              # 每连接限速 100KB/s

            proxy_pass http://localhost:8080;
        }
    }
}
```

### 下载限速

```nginx
location /downloads {
    limit_rate_after 5m;   # 前 5MB 不限速
    limit_rate 500k;       # 之后限速 500KB/s
}
```

---

## 十三、访问控制

```nginx
# IP 白名单/黑名单
location /admin {
    allow 192.168.1.0/24;
    allow 10.0.0.0/8;
    deny all;
}

# 基本认证
location /private {
    auth_basic "Restricted Area";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # 生成密码文件
    # htpasswd -c /etc/nginx/.htpasswd username
}

# 禁止特定 User-Agent
if ($http_user_agent ~* (bot|crawler|spider)) {
    return 403;
}

# 防盗链
location ~* \.(jpg|jpeg|png|gif)$ {
    valid_referers none blocked example.com *.example.com;
    if ($invalid_referer) {
        return 403;
    }
}
```

---

## 十四、跨域 CORS

```nginx
location /api/ {
    # 允许所有源
    add_header Access-Control-Allow-Origin *;

    # 或指定源
    # add_header Access-Control-Allow-Origin https://example.com;

    add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS";
    add_header Access-Control-Allow-Headers "Authorization, Content-Type";
    add_header Access-Control-Allow-Credentials true;

    if ($request_method = OPTIONS) {
        return 204;
    }

    proxy_pass http://localhost:8080;
}
```

---

## 十五、日志管理

```nginx
http {
    # 自定义日志格式
    log_format json_combined escape=json
        '{'
            '"time":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"request":"$request",'
            '"status":$status,'
            '"body_bytes":$body_bytes_sent,'
            '"request_time":$request_time,'
            '"upstream_time":"$upstream_response_time",'
            '"http_referer":"$http_referer",'
            '"http_user_agent":"$http_user_agent"'
        '}';

    access_log /var/log/nginx/access.log json_combined;

    # 错误日志级别
    error_log /var/log/nginx/error.log warn;  # debug/info/notice/warn/error/crit
}

# 日志切割（logrotate）
# /etc/logrotate.d/nginx
/var/log/nginx/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    create 640 nginx adm
    sharedscripts
    postrotate
        [ -f /var/run/nginx.pid ] && kill -USR1 `cat /var/run/nginx.pid`
    endscript
}
```

---

## 十六、常用变量

| 变量 | 说明 |
|------|------|
| `$host` | 请求 Host 头 |
| `$remote_addr` | 客户端 IP |
| `$proxy_add_x_forwarded_for` | 追加 X-Forwarded-For |
| `$request_uri` | 完整请求 URI（含参数） |
| `$uri` | 当前 URI（不含参数） |
| `$args` | 请求参数 |
| `$scheme` | http 或 https |
| `$request_method` | GET/POST/PUT 等 |
| `$status` | 响应状态码 |
| `$request_time` | 请求处理时间（秒） |
| `$upstream_response_time` | 上游响应时间 |
| `$upstream_addr` | 上游地址 |
| `$upstream_status` | 上游状态码 |
| `$http_<header>` | 任意请求头（小写，- 换 _） |

---

## 十七、性能调优

```nginx
# /etc/nginx/nginx.conf
worker_processes auto;                    # CPU 核心数
worker_rlimit_nofile 65535;               # 最大文件描述符

events {
    worker_connections 4096;              # 每个 worker 连接数
    use epoll;
    multi_accept on;
}

http {
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    keepalive_requests 100;

    # 上游 keepalive
    upstream backend {
        server localhost:8080;
        keepalive 32;                     # 保持与上游的长连接数
    }

    # 代理 keepalive
    location / {
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_pass http://backend;
    }

    # 关闭不必要日志
    access_log off;                       # 或减少日志
    # location ~* \.(jpg|png|css|js)$ {
    #     access_log off;
    # }
}
```

### 系统层面调优

```bash
# /etc/sysctl.conf
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.ip_local_port_range = 1024 65000
net.ipv4.tcp_tw_reuse = 1
fs.file-max = 65535
```

---

## 十八、Docker 部署

```bash
# 基础启动
docker run -d --name nginx -p 80:80 nginx:alpine

# 挂载配置
docker run -d --name nginx \
  -p 80:80 -p 443:443 \
  -v /path/to/nginx.conf:/etc/nginx/nginx.conf:ro \
  -v /path/to/sites:/etc/nginx/conf.d:ro \
  -v /path/to/ssl:/etc/nginx/ssl:ro \
  -v /path/to/html:/usr/share/nginx/html:ro \
  nginx:alpine

# 重载配置
docker exec nginx nginx -s reload
```

### docker-compose.yml

```yaml
version: '3.8'
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./conf.d:/etc/nginx/conf.d:ro
      - ./ssl:/etc/nginx/ssl:ro
      - ./html:/usr/share/nginx/html:ro
    restart: unless-stopped
    networks:
      - web

  app:
    image: myapp:latest
    expose:
      - "8080"
    networks:
      - web

networks:
  web:
    driver: bridge
```

---

## 十九、常见错误排查

```bash
# 检查配置语法
nginx -t

# 查看错误日志
tail -f /var/log/nginx/error.log

# 查看访问日志
tail -f /var/log/nginx/access.log

# 查看监听端口
ss -tlnp | grep nginx
netstat -tlnp | grep nginx

# 测试反向代理
curl -v -H "Host: example.com" http://localhost/
```

### 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| `502 Bad Gateway` | 后端服务挂了 | 检查后端是否启动，`proxy_pass` 地址是否正确 |
| `504 Gateway Timeout` | 后端响应超时 | 增加 `proxy_read_timeout` |
| `403 Forbidden` | 权限不足 | 检查文件权限、`autoindex` 配置 |
| `404 Not Found` | 路径不存在 | 检查 `root` 和 `try_files` |
| `413 Request Entity Too Large` | 上传文件过大 | 增加 `client_max_body_size` |
| `address already in use` | 端口被占用 | `lsof -i :80` 查占用 |
| `SSL_ERROR_RX_RECORD_TOO_LONG` | HTTP 访问 HTTPS 端口 | 加 `ssl` 参数或重定向 |

---

## 二十、配置模板速查

### 静态网站

```nginx
server {
    listen 80;
    server_name example.com;
    root /var/www/html;
    index index.html;
    location / { try_files $uri $uri/ =404; }
}
```

### 反向代理 + API

```nginx
server {
    listen 80;
    server_name api.example.com;
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

### HTTPS + 反向代理

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    location / { proxy_pass http://localhost:8080; }
}
server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}
```

### 负载均衡

```nginx
upstream app {
    server 192.168.1.10:8080 weight=3;
    server 192.168.1.11:8080 weight=1;
}
server {
    listen 80;
    location / { proxy_pass http://app; }
}
```

### WebSocket

```nginx
server {
    listen 80;
    location /ws {
        proxy_pass http://localhost:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
    }
}
```

### SPA 前端（React/Vue）

```nginx
server {
    listen 80;
    root /var/www/spa;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://localhost:8080/;
    }
}
```