``` bash
#!/usr/bin/env bash
#
# deploy-rancher.sh — 在已有 K8s 集群上一键部署 Rancher(幂等,可重复执行)
#
# 基于 2026-09-29 实测踩坑整理,自动处理:
#   - hostname 必须为 DNS 名(裸 IP 自动套 sslip.io 泛域名)
#   - 自动探测集群 IngressClass 并绑定(chart 生成的 Ingress 默认不带 class)
#   - 上次安装失败残留的 failed release 自动清理(--no-hooks,规避 post-delete 钩子假死)
#   - 自动探测 Ingress 控制器 443 的 NodePort,据此修正 server-url 与访问地址
#   - 装完三级验证(rollout / Certificate / HTTP 200)
#
# 用法:
#   ./deploy-rancher.sh                 # 常规执行(默认全自动探测)
#   DRY_RUN=true ./deploy-rancher.sh    # 只探测与打印计划,不改集群
#
# 可用环境变量覆盖(均有合理默认):
#   PUBLIC_IP            公网 IP(默认 curl ifconfig.me 自动探测)
#   RANCHER_HOSTNAME     访问域名(默认 <PUBLIC_IP>.sslip.io;有自己的域名就显式指定。
#                        注意:不能用裸 IP,裸 IP 会自动转换为 <IP>.sslip.io;
#                        不要用变量名 HOSTNAME,它与 shell 内置变量冲突)
#   BOOTSTRAP_PASSWORD   首次登录密码(全新安装时默认随机生成;重复执行不会重置)
#   NAMESPACE            安装命名空间(默认 cattle-system)
#   REPLICAS             副本数(默认 1)
#   INGRESS_CLASS        IngressClass 名(默认自动探测)
#   INSTALL_INGRESS_NGINX  集群没有 IngressClass 时自动安装 ingress-nginx 并设为默认类
#                          (默认 true;设 false 则恢复为报错退出)
#   CHART_VERSION        rancher chart 版本 pin(默认最新 stable,如 "2.15.2")
#   CERT_MANAGER_VERSION cert-manager chart 版本 pin(默认最新)
#   NODE_PORT_HTTPS      控制器 443 的 NodePort(默认自动探测;不需要修正端口可设 443)
#
set -euo pipefail

# ------------------------------ 配置 ------------------------------
PUBLIC_IP="${PUBLIC_IP:-}"
RANCHER_HOSTNAME="${RANCHER_HOSTNAME:-}"
BOOTSTRAP_PASSWORD="${BOOTSTRAP_PASSWORD:-}"
NAMESPACE="${NAMESPACE:-cattle-system}"
REPLICAS="${REPLICAS:-1}"
INGRESS_CLASS="${INGRESS_CLASS:-}"
INSTALL_INGRESS_NGINX="${INSTALL_INGRESS_NGINX:-true}"
CHART_VERSION="${CHART_VERSION:-}"
CERT_MANAGER_VERSION="${CERT_MANAGER_VERSION:-}"
NODE_PORT_HTTPS="${NODE_PORT_HTTPS:-}"
DRY_RUN="${DRY_RUN:-false}"

log()  { echo -e "\033[1;34m[deploy-rancher]\033[0m $*"; }
warn() { echo -e "\033[1;33m[警告]\033[0m $*" >&2; }
die()  { echo -e "\033[1;31m[错误]\033[0m $*" >&2; exit 1; }
run()  { if [[ "$DRY_RUN" == "true" ]]; then log "DRY_RUN 跳过: $*"; else eval "$*"; fi }

# 清理处于非 deployed 状态的残留 release(failed-install 的钩子资源一并删除)
# 用法: cleanup_release <release> <namespace>;返回 0 表示发生了清理
cleanup_release() {
  local rel="$1" ns="$2" st
  helm status "$rel" -n "$ns" >/dev/null 2>&1 || return 1
  st=$(helm status "$rel" -n "$ns" -o json 2>/dev/null | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4 || echo unknown)
  if [[ "$st" != "deployed" && "$st" != "pending-install" ]]; then
    warn "残留 release ${rel}(ns=${ns})状态异常(${st}),执行清理后重装(--no-hooks 规避钩子假死)"
    run "helm uninstall '$rel' -n '$ns' --no-hooks || true"
    run "kubectl -n '$ns' delete job -l app.kubernetes.io/instance='$rel' --ignore-not-found || true"
    return 0
  fi
  return 1
}

# ------------------------------ 前置检查 ------------------------------
command -v kubectl >/dev/null || die "未找到 kubectl"
command -v helm    >/dev/null || die "未找到 helm(需要 helm 3.x)"
kubectl get nodes >/dev/null 2>&1 || die "kubectl 无法连接集群(检查 kubeconfig)"

K8S_VERSION=$(kubectl version -o json 2>/dev/null | grep -o '"gitVersion": "v[0-9.]*"' | tail -1 | grep -o 'v[0-9.]*' || true)
log "集群连接正常,K8s 版本: ${K8S_VERSION:-未知}"
case "${K8S_VERSION:-}" in
  v1.34*|v1.35*|v1.36*) : ;;
  v1.3[0-3]*) warn "Rancher v2.15+ 官方矩阵要求 K8s ≥1.34,当前 ${K8S_VERSION} 为未验证组合;建议设置 CHART_VERSION=2.12.x" ;;
esac

# ------------------------------ 探测 公网 IP / 域名 ------------------------------
if [[ -z "$PUBLIC_IP" ]]; then
  PUBLIC_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || true)
fi
[[ -z "$RANCHER_HOSTNAME" && -n "$PUBLIC_IP" ]] && RANCHER_HOSTNAME="${PUBLIC_IP}.sslip.io"
[[ -n "$RANCHER_HOSTNAME" ]] || die "无法自动探测公网 IP 与域名,请显式指定 RANCHER_HOSTNAME=xxx 或 PUBLIC_IP=x.x.x.x"
if [[ "$RANCHER_HOSTNAME" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  RANCHER_HOSTNAME="${RANCHER_HOSTNAME}.sslip.io"
  log "hostname 是裸 IP(Ingress 只接受 DNS 名),已自动转换为: ${RANCHER_HOSTNAME}"
fi

# ------------------------------ 探测 IngressClass ------------------------------
if [[ -z "$INGRESS_CLASS" ]]; then
  INGRESS_CLASS=$(kubectl get ingressclass \
    -o jsonpath='{.items[?(@.metadata.annotations.ingressclass\.kubernetes\.io/is-default-class=="true")].metadata.name}' 2>/dev/null | awk '{print $1}' || true)
  if [[ -z "$INGRESS_CLASS" ]]; then
    INGRESS_CLASS=$(kubectl get ingressclass -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    [[ -n "$INGRESS_CLASS" ]] && warn "集群未标记默认 IngressClass,自动选用第一个: ${INGRESS_CLASS}(不对请用 INGRESS_CLASS= 覆盖)"
  fi
fi
if [[ -z "$INGRESS_CLASS" ]]; then
  if [[ "$INSTALL_INGRESS_NGINX" == "true" ]]; then
    log "集群中没有 IngressClass,自动安装 ingress-nginx(设 INSTALL_INGRESS_NGINX=false 可关闭此行为)"
    # ingress-nginx 的镜像托管在 registry.k8s.io,其存储后端 *.pkg.dev 在国内常被阻断。
    # 在小镜像上实测一次拉取;失败则整站改用 daocloud 的 k8s 镜像(镜像名/tag/digest 与上游一致)。
    K8S_IMG_REG="registry.k8s.io"
    if command -v docker >/dev/null 2>&1; then
      if ! timeout 90 docker pull -q registry.k8s.io/pause:3.10 >/dev/null 2>&1; then
        K8S_IMG_REG="k8s.m.daocloud.io"
        warn "registry.k8s.io 拉取失败(后端 *.pkg.dev 被阻断),ingress-nginx 镜像改用 ${K8S_IMG_REG}"
      fi
    fi
    if [[ "$DRY_RUN" != "true" ]]; then
      helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx >/dev/null 2>&1 || true
      helm repo update >/dev/null
      cleanup_release ingress-nginx ingress-nginx || true
      REG_ARGS=""
      if [[ "$K8S_IMG_REG" != "registry.k8s.io" ]]; then
        # chart 4.12+ 起镜像仓库收敛到 global.image.registry;per-image 的 registry 参数
        # 对旧版 chart 生效、对新版无害(未使用的 values 被忽略),故同时下发
        REG_ARGS="--set global.image.registry=$K8S_IMG_REG --set controller.image.registry=$K8S_IMG_REG --set admissionWebhooks.patch.image.registry=$K8S_IMG_REG"
      fi
      # shellcheck disable=SC2086
      helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
        --namespace ingress-nginx --create-namespace \
        --set controller.ingressClassResource.default=true \
        $REG_ARGS
      kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=300s \
        || die "ingress-nginx 控制器未就绪,检查: kubectl -n ingress-nginx get pods"
    fi
    INGRESS_CLASS="nginx"
  else
    die "集群中没有 IngressClass,请先安装 Ingress Controller,或显式指定 INGRESS_CLASS"
  fi
fi
log "IngressClass: ${INGRESS_CLASS}"

# ------------------------------ 清理失败安装残留 ------------------------------
if helm status rancher -n "$NAMESPACE" >/dev/null 2>&1; then
  REL_STATUS=$(helm status rancher -n "$NAMESPACE" -o json 2>/dev/null | grep -o '"status":"[^"]*"' | head -1 | cut -d'"' -f4 || echo unknown)
  log "检测到已有 rancher release,状态: ${REL_STATUS}"
  if [[ "$REL_STATUS" != "deployed" && "$REL_STATUS" != "pending-install" ]]; then
    warn "残留 release 状态异常(${REL_STATUS}),执行清理(--no-hooks 规避 post-delete 钩子假死)"
    run "helm uninstall rancher -n '$NAMESPACE' --no-hooks || true"
    run "kubectl -n '$NAMESPACE' delete job rancher-post-delete --ignore-not-found || true"
    UPGRADE_MODE=false
  else
    UPGRADE_MODE=true   # 已安装:保留原参数,仅补齐 class 并做验证,不会重置密码
  fi
else
  UPGRADE_MODE=false
fi

# ------------------------------ helm 仓库 & cert-manager ------------------------------
log "添加/更新 helm 仓库"
if [[ "$DRY_RUN" != "true" ]]; then
  helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || true
  helm repo add rancher-stable https://releases.rancher.com/server-charts/stable >/dev/null
  helm repo update >/dev/null
fi

CERT_VER_ARG=""; [[ -n "$CERT_MANAGER_VERSION" ]] && CERT_VER_ARG="--version $CERT_MANAGER_VERSION"
if kubectl get deployment -n cert-manager cert-manager >/dev/null 2>&1; then
  log "cert-manager 已存在,跳过安装"
else
  log "安装 cert-manager(Rancher 证书依赖)"
  run "helm upgrade --install cert-manager jetstack/cert-manager --namespace cert-manager --create-namespace --set crds.enabled=true $CERT_VER_ARG"
fi

# ------------------------------ 安装 / 升级 Rancher ------------------------------
CHART_VER_ARG=""; [[ -n "$CHART_VERSION" ]] && CHART_VER_ARG="--version $CHART_VERSION"

if [[ "$UPGRADE_MODE" == "true" ]]; then
  CUR_CLASS=$(kubectl get ingress -n "$NAMESPACE" rancher -o jsonpath='{.spec.ingressClassName}' 2>/dev/null || true)
  if [[ "$CUR_CLASS" != "$INGRESS_CLASS" ]]; then
    warn "现有 Ingress class='${CUR_CLASS:-<空>}' 与期望不符,补齐 ingressClassName"
    run "helm upgrade rancher rancher-stable/rancher -n '$NAMESPACE' --reuse-values --set ingress.ingressClassName='$INGRESS_CLASS' $CHART_VER_ARG"
  else
    log "已安装且 Ingress class 正确,进入验证阶段"
  fi
else
  if [[ -z "$BOOTSTRAP_PASSWORD" ]]; then
    BOOTSTRAP_PASSWORD=$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)
    GENERATED_PW=true
  fi
  log "安装 Rancher → namespace=${NAMESPACE} hostname=${RANCHER_HOSTNAME} replicas=${REPLICAS}"
  run "kubectl create namespace '$NAMESPACE' --dry-run=client -o yaml | kubectl apply -f -"
  # shellcheck disable=SC2086
  run "helm upgrade --install rancher rancher-stable/rancher \
        --namespace '$NAMESPACE' \
        --set hostname='$RANCHER_HOSTNAME' \
        --set replicas='$REPLICAS' \
        --set bootstrapPassword='$BOOTSTRAP_PASSWORD' \
        --set ingress.ingressClassName='$INGRESS_CLASS' \
        $CHART_VER_ARG"
fi

# ------------------------------ 等待就绪 ------------------------------
if [[ "$DRY_RUN" != "true" ]]; then
  log "等待 rancher 就绪(首次启动约 2~3 分钟,含系统组件自举)..."
  kubectl -n "$NAMESPACE" rollout status deploy/rancher --timeout=420s || die "rancher 部署超时,请执行: kubectl -n $NAMESPACE logs deploy/rancher --tail=50"
  kubectl -n "$NAMESPACE" wait --for=jsonpath='{.status.conditions[?(@.type=="Ready")].status}'=True certificate --all --timeout=120s 2>/dev/null \
    || warn "Certificate 未在预期时间内 Ready( tls.secret 可能稍后由 cert-manager 补齐)"
fi

# ------------------------------ 探测 NodePort 并修正 server-url ------------------------------
if [[ -z "$NODE_PORT_HTTPS" ]]; then
  NODE_PORT_HTTPS=$(kubectl get svc -A 2>/dev/null | awk '/ingress/ && /controller/ && /(NodePort|LoadBalancer)/' \
    | grep -o '443:[0-9]*' | head -1 | cut -d: -f2 || true)
fi
if [[ -n "$NODE_PORT_HTTPS" && "$NODE_PORT_HTTPS" != "443" ]]; then
  ACCESS_URL="https://${RANCHER_HOSTNAME}:${NODE_PORT_HTTPS}"
  log "控制器 443 经 NodePort ${NODE_PORT_HTTPS} 暴露,访问地址应带端口: ${ACCESS_URL}"
else
  ACCESS_URL="https://${RANCHER_HOSTNAME}"
fi

if [[ "$DRY_RUN" != "true" ]]; then
  CUR_URL=$(kubectl get settings.management.cattle.io server-url -o jsonpath='{.value}' 2>/dev/null || true)
  if [[ -z "$CUR_URL" ]]; then
    log "server-url 未设置,写入 → ${ACCESS_URL}"
    run "kubectl patch settings.management.cattle.io server-url --type=merge -p '{\"value\":\"${ACCESS_URL}\"}' || true"
  elif [[ "$UPGRADE_MODE" == "true" ]]; then
    log "检测到已有 server-url: ${CUR_URL}(重复执行不覆盖既有配置)"
    ACCESS_URL="$CUR_URL"
  elif [[ "$CUR_URL" != "$ACCESS_URL" ]]; then
    log "修正 server-url: ${CUR_URL} → ${ACCESS_URL}(缺端口会导致纳管集群的 agent 连不上)"
    run "kubectl patch settings.management.cattle.io server-url --type=merge -p '{\"value\":\"${ACCESS_URL}\"}' || true"
  else
    log "server-url 已正确: ${CUR_URL}"
  fi
fi

# ------------------------------ 验证 ------------------------------
if [[ "$DRY_RUN" != "true" ]]; then
  NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || true)
  SKIP_VERIFY_TLS_HOST="${ACCESS_URL#https://}"
  HOSTPORT="${SKIP_VERIFY_TLS_HOST}"
  if [[ -n "$NODE_IP" && -n "$NODE_PORT_HTTPS" ]]; then
    # 注意:Cilium(kube-proxy 替代)集群不能用 127.0.0.1 测 NodePort,必须用节点 IP
    CODE=$(curl -sk -o /dev/null -w '%{http_code}' --connect-timeout 5 --resolve "${HOSTPORT}:${NODE_IP}" "$ACCESS_URL/" || echo "000")
    [[ "$CODE" == "200" ]] && log "节点级验证通过(${NODE_IP} → ${CODE})" || warn "节点级验证返回 ${CODE},若集群入口方式不同请人工确认"
  fi
  PUB_CODE=$(curl -sk -o /dev/null -w '%{http_code}' --connect-timeout 6 "$ACCESS_URL/" 2>/dev/null || echo "000")
  if [[ "$PUB_CODE" == "200" ]]; then
    log "公网访问验证通过(${ACCESS_URL} → ${PUB_CODE})"
  else
    warn "公网访问未通(返回 ${PUB_CODE})。请检查:① 云安全组是否放通 ${NODE_PORT_HTTPS:-443} ② 域名解析 ③ 回环检测不可靠时换外网机器重试"
  fi
fi

# ------------------------------ 输出汇总 ------------------------------
echo
log "===================== 部署完成 ====================="
echo "  访问地址:        ${ACCESS_URL}"
echo "  K8s 版本:        ${K8S_VERSION:-未知}"
echo "  IngressClass:    ${INGRESS_CLASS}"
[[ "${GENERATED_PW:-false}" == "true" ]] && echo "  bootstrap 密码:  ${BOOTSTRAP_PASSWORD}  (请立即保存,登录后马上改 admin 密码!)" || true
cat <<'EOF'

后续提醒:
  1. 浏览器打开访问地址(自签名证书,点"继续访问"),用 bootstrap 密码登录后设置 admin 强口令
  2. 云安全组建议将入口端口源 IP 收敛为办公网出口,勿长期 0.0.0.0/0
  3. local 集群已自动纳管;纳管其他集群请用 Cluster Management → Import Existing
     (前提:被管集群能回连上述地址,且能拉取 rancher/rancher-agent 镜像)
  4. 清理 Rancher 自举产生的一次性 Pod:
     kubectl -n cattle-system delete pod --field-selector=status.phase=Succeeded
EOF
```