FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AEGIS_DATA_DIR=/var/lib/aegis \
    AEGIS_PORT=8080

WORKDIR /app
COPY . /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 aegis \
    && mkdir -p /var/lib/aegis \
    && chown -R aegis:aegis /app /var/lib/aegis

USER aegis

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
CMD ["python", "main.py"]
