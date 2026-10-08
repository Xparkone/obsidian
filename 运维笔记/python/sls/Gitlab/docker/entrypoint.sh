#!/bin/sh
set -eu

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"

rm -f /etc/nginx/conf.d/default.conf

# 同一容器内 API 听 127.0.0.1:8000，nginx 对外听 80。
# 每份报表的 token 写在 reports/.tokens/<时间戳>，访问 HTML 时 auth_request 校验。
cat > /etc/nginx/conf.d/default.conf << NGINX
log_format nochq '\$remote_addr - \$request_method \$uri \$status';

server {
    listen 80;
    server_name _;
    root /app/reports;
    charset utf-8;
    autoindex off;
    access_log /var/log/nginx/access.log nochq;
    gzip on;
    gzip_types text/css application/javascript application/json;

    location = /healthz {
        access_log off;
        default_type text/plain;
        return 200 "ok";
    }

    location = /internal/auth {
        internal;
        proxy_pass http://${API_HOST}:${API_PORT};
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI \$orig_uri;
        proxy_set_header X-Report-Token \$orig_token;
    }

    location /api/ {
        proxy_pass http://${API_HOST}:${API_PORT};
        proxy_read_timeout 120s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Api-Token \$http_x_api_token;
    }

    location ^~ /.tokens/ {
        deny all;
        return 404;
    }

    location ~ /\\. {
        deny all;
        return 404;
    }

    error_page 401 = @denied;
    location @denied {
        default_type text/plain;
        charset utf-8;
        return 401 "unauthorized: token missing or invalid";
    }

    location ~ "^/[0-9]{8}-[0-9]{6}(?:-[0-9]+)?\\.html\$" {
        set \$orig_uri \$request_uri;
        set \$orig_token \$arg_token;
        auth_request /internal/auth;
        add_header Cache-Control "no-store" always;
    }

    location / {
        return 404;
    }
}
NGINX

python /app/server.py &
i=0
while [ "$i" -lt 100 ]; do
    if curl -sf "http://${API_HOST}:${API_PORT}/healthz" >/dev/null; then
        break
    fi
    i=$((i + 1))
    sleep 0.1
done
if ! curl -sf "http://${API_HOST}:${API_PORT}/healthz" >/dev/null; then
    echo "api failed to start" >&2
    exit 1
fi

exec nginx -g "daemon off;"
