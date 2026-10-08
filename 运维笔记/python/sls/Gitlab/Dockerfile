# 访问日志日报：一个镜像同时跑 Flask 生成接口 + nginx 静态鉴权
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx curl \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-available/default \
    && rm -f /etc/nginx/conf.d/default.conf

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PORT=8000

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY query_perplexitybot.py server.py ./
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /app/reports

EXPOSE 80
VOLUME /app/reports

HEALTHCHECK --interval=10s --timeout=3s --retries=8 \
    CMD curl -fsS http://127.0.0.1/healthz >/dev/null

ENTRYPOINT ["/entrypoint.sh"]
