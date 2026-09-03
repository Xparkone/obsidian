```
#!/usr/bin/env bash
# [[[[[[[[k -]]]]]]]] kubectl 快捷操作工具
# 安装: cp k /usr/local/bin/k && chmod +x /usr/local/bin/k
# 依赖: kubectl, fzf (可选，用于模糊搜索)

set -euo pipefail

K="kubectl"
NS_FLAG=""
FZF_AVAILABLE=$(command -v fzf &>/dev/null && echo "yes" || echo "no")

# ─── 颜色 ────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'
BLU='\033[0;34m'; CYN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYN}▸ $*${NC}"; }
ok()    { echo -e "${GRN}✔ $*${NC}"; }
warn()  { echo -e "${YEL}⚠ $*${NC}"; }
err()   { echo -e "${RED}✘ $*${NC}" >&2; }

# ─── 帮助 ────────────────────────────────────────────────────
usage() {
cat <<EOF
${CYN}k${NC} - kubectl 快捷操作

${YEL}资源查看${NC}
  k po  [ns] [grep]        列出 Pod（支持模糊过滤）
  k dep [ns] [grep]        列出 Deployment
  k svc [ns] [grep]        列出 Service
  k node                   列出节点（含资源分配）
  k gpu                    查看各节点 GPU 资源
  k all [ns]               列出 ns 下常用资源

${YEL}Pod 操作${NC}
  k exec  <pod|grep> [ns]  进入 Pod shell（自动匹配）
  k log   <pod|grep> [ns] [-f] [-n N]  查看日志
  k desc  <pod|grep> [ns]  describe Pod
  k del   <pod|grep> [ns]  删除 Pod（需确认）

${YEL}Deployment 操作${NC}
  k restart <dep> [ns]     滚动重启
  k scale   <dep> <N> [ns] 扩缩容
  k img     <dep> [ns]     查看当前镜像版本
  k rollout <dep> [ns]     查看滚动历史

${YEL}集群操作${NC}
  k ctx [name]             查看/切换 context
  k ns  [name]             查看/切换 namespace
  k top-po [ns]            Pod 资源使用
  k top-node               节点资源使用
  k event [ns] [grep]      查看 Event

${YEL}快捷 apply / edit${NC}
  k apply <file>           kubectl apply -f
  k edit  <res> <name> [ns] 编辑资源
  k kust  <dir>            kubectl apply -k

${YEL}选项${NC}
  -n <ns>   指定 namespace（可放在任意位置）
  -A        所有 namespace

${YEL}示例${NC}
  k po -n kube-system
  k exec aims -n default
  k log uni-aims-hub -n prod -f
  k scale my-deploy 3 -n prod
  k gpu
EOF
}

# ─── 解析全局 -n / -A ────────────────────────────────────────
ALL_NS=""
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n) NS_FLAG="-n $2"; shift 2 ;;
    -n=*) NS_FLAG="-n ${1#-n=}"; shift ;;
    -A|--all-namespaces) ALL_NS="-A"; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- "${ARGS[@]+"${ARGS[@]}"}"

NS() { echo "${NS_FLAG:-${1:+-n $1}}"; }

# ─── 辅助：按名称模糊匹配 Pod ────────────────────────────────
find_pod() {
  local grep_str="$1"
  local ns_arg="${2:-$NS_FLAG}"
  local pods
  pods=$($K get pod $ns_arg $ALL_NS --no-headers -o custom-columns='NAME:.metadata.name,NS:.metadata.namespace' 2>/dev/null \
    | grep "$grep_str" | awk '{print $1}')
  local count
  count=$(echo "$pods" | grep -c . || true)
  if [[ $count -eq 0 ]]; then
    err "没有找到匹配 '$grep_str' 的 Pod"
    exit 1
  elif [[ $count -eq 1 ]]; then
    echo "$pods"
  elif [[ "$FZF_AVAILABLE" == "yes" ]]; then
    echo "$pods" | fzf --prompt="选择 Pod > " --height=40%
  else
    warn "找到多个 Pod，请选择："
    select p in $pods; do [[ -n "$p" ]] && echo "$p" && break; done
  fi
}

find_deploy() {
  local grep_str="$1"
  local ns_arg="${2:-$NS_FLAG}"
  local deps
  deps=$($K get deploy $ns_arg $ALL_NS --no-headers -o custom-columns='NAME:.metadata.name' 2>/dev/null \
    | grep "$grep_str")
  local count
  count=$(echo "$deps" | grep -c . || true)
  if [[ $count -eq 1 ]]; then
    echo "$deps"
  elif [[ "$FZF_AVAILABLE" == "yes" ]]; then
    echo "$deps" | fzf --prompt="选择 Deployment > " --height=40%
  else
    select d in $deps; do [[ -n "$d" ]] && echo "$d" && break; done
  fi
}

# ─── 命令分发 ────────────────────────────────────────────────
CMD="${1:-help}"; shift || true

case "$CMD" in

# ── 资源列表 ──────────────────────────────────────────────────

po|pod|pods)
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"; GREP="${2:-}"
  if [[ -n "$GREP" ]]; then
    $K get pod $NS_ARG $ALL_NS -o wide | { head -1; grep "$GREP"; }
  else
    $K get pod $NS_ARG $ALL_NS -o wide
  fi
  ;;

dep|deploy|deployment)
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"; GREP="${2:-}"
  if [[ -n "$GREP" ]]; then
    $K get deploy $NS_ARG $ALL_NS | { head -1; grep "$GREP"; }
  else
    $K get deploy $NS_ARG $ALL_NS
  fi
  ;;

svc|service)
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  $K get svc $NS_ARG $ALL_NS
  ;;

node|nodes)
  $K get node -o wide
  echo ""
  $K describe nodes | grep -A5 "Allocated resources"
  ;;

gpu)
  info "节点 GPU 资源 (requests / limits / allocatable)"
  echo ""
  # 显示 GPU allocatable
  $K get nodes -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
rows = []
for n in data['items']:
  name = n['metadata']['name']
  alloc = n['status'].get('allocatable', {})
  cap   = n['status'].get('capacity', {})
  gpu_alloc = alloc.get('nvidia.com/gpu') or alloc.get('iluvatar.com/gpu') or alloc.get('metax-tech.com/gpu') or '-'
  gpu_cap   = cap.get('nvidia.com/gpu')   or cap.get('iluvatar.com/gpu')   or cap.get('metax-tech.com/gpu')   or '-'
  rows.append((name, gpu_cap, gpu_alloc))
print(f'{'NODE':<30} {'GPU-CAP':>8} {'GPU-ALLOC':>10}')
print('-'*52)
for r in rows:
  print(f'{r[0]:<30} {r[1]:>8} {r[2]:>10}')
" 2>/dev/null || $K get nodes -o custom-columns='NODE:.metadata.name,GPU-NVIDIA:.status.allocatable.nvidia\.com/gpu,GPU-ILU:.status.allocatable.iluvatar\.com/gpu'
  echo ""
  info "Pod GPU 使用 (所有 namespace)"
  $K get pod -A -o json | python3 -c "
import json, sys
data = json.load(sys.stdin)
vendors = ['nvidia.com/gpu', 'iluvatar.com/gpu', 'metax-tech.com/gpu', 'birentech.com/gpu']
print(f'{'NAMESPACE':<20} {'POD':<45} {'GPU':>5} {'TYPE':<25}')
print('-'*100)
for p in data['items']:
  ns = p['metadata']['namespace']
  name = p['metadata']['name']
  for c in p['spec'].get('containers', []):
    for v in vendors:
      lim = c.get('resources', {}).get('limits', {}).get(v)
      if lim:
        print(f'{ns:<20} {name:<45} {lim:>5} {v:<25}')
" 2>/dev/null
  ;;

all)
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  $K get pod,deploy,svc,ingress,sts,cm,pvc $NS_ARG 2>/dev/null || \
  $K get pod,deploy,svc,sts $NS_ARG
  ;;

# ── Pod 操作 ──────────────────────────────────────────────────

exec)
  POD_GREP="${1:-}"; shift || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  [[ -z "$POD_GREP" ]] && { err "需要提供 pod 名称或关键字"; exit 1; }
  POD=$(find_pod "$POD_GREP" "$NS_ARG")
  info "进入 Pod: $POD"
  SHELL=$( $K exec $NS_ARG "$POD" -- which bash 2>/dev/null && echo bash || echo sh )
  $K exec -it $NS_ARG "$POD" -- $SHELL
  ;;

log|logs)
  POD_GREP="${1:-}"; shift || true
  # 解析 log 特有选项
  FOLLOW=""; TAIL=""
  REMAINING=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -f|--follow) FOLLOW="-f"; shift ;;
      -n) TAIL="--tail=$2"; shift 2 ;;
      --tail=*) TAIL="$1"; shift ;;
      *) REMAINING+=("$1"); shift ;;
    esac
  done
  NS_ARG="${NS_FLAG:-${REMAINING[0]:+-n ${REMAINING[0]}}}"
  [[ -z "$POD_GREP" ]] && { err "需要提供 pod 名称或关键字"; exit 1; }
  POD=$(find_pod "$POD_GREP" "$NS_ARG")
  info "日志: $POD $FOLLOW $TAIL"
  $K logs $NS_ARG "$POD" $FOLLOW $TAIL
  ;;

desc|describe)
  RES="${1:-pod}"; shift || true
  NAME="${1:-}"; shift || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  if [[ -z "$NAME" ]]; then
    $K describe "$RES" $NS_ARG
  else
    $K describe "$RES" $NS_ARG "$NAME"
  fi
  ;;

del|delete)
  POD_GREP="${1:-}"; shift || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  [[ -z "$POD_GREP" ]] && { err "需要提供 pod 名称或关键字"; exit 1; }
  POD=$(find_pod "$POD_GREP" "$NS_ARG")
  warn "即将删除 Pod: $POD"
  read -r -p "确认删除? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { info "已取消"; exit 0; }
  $K delete pod $NS_ARG "$POD"
  ok "已删除 $POD"
  ;;

# ── Deployment 操作 ───────────────────────────────────────────

restart)
  DEP="${1:-}"; shift || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  [[ -z "$DEP" ]] && { err "需要提供 deployment 名称"; exit 1; }
  MATCHED=$(find_deploy "$DEP" "$NS_ARG")
  info "滚动重启: $MATCHED"
  $K rollout restart deploy/$MATCHED $NS_ARG
  $K rollout status deploy/$MATCHED $NS_ARG
  ;;

scale)
  DEP="${1:-}"; REPLICAS="${2:-}"; shift 2 || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  [[ -z "$DEP" || -z "$REPLICAS" ]] && { err "用法: k scale <deploy> <replicas> [ns]"; exit 1; }
  MATCHED=$(find_deploy "$DEP" "$NS_ARG")
  info "扩缩容: $MATCHED → $REPLICAS 副本"
  $K scale deploy/$MATCHED --replicas="$REPLICAS" $NS_ARG
  $K rollout status deploy/$MATCHED $NS_ARG
  ;;

img|image)
  DEP="${1:-}"; shift || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  [[ -z "$DEP" ]] && { err "需要提供 deployment 名称"; exit 1; }
  MATCHED=$(find_deploy "$DEP" "$NS_ARG")
  $K get deploy/$MATCHED $NS_ARG -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{"\t"}{.image}{"\n"}{end}'
  ;;

rollout)
  DEP="${1:-}"; shift || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  [[ -z "$DEP" ]] && { err "需要提供 deployment 名称"; exit 1; }
  MATCHED=$(find_deploy "$DEP" "$NS_ARG")
  $K rollout history deploy/$MATCHED $NS_ARG
  ;;

# ── 集群操作 ──────────────────────────────────────────────────

ctx|context)
  if [[ -z "${1:-}" ]]; then
    $K config get-contexts
  else
    $K config use-context "$1"
    ok "已切换到 context: $1"
  fi
  ;;

ns|namespace)
  if [[ -z "${1:-}" ]]; then
    $K get ns
  else
    $K config set-context --current --namespace="$1"
    ok "当前 namespace 已设为: $1"
  fi
  ;;

top-po|top-pod)
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  $K top pod $NS_ARG $ALL_NS --sort-by=cpu 2>/dev/null || $K top pod $NS_ARG $ALL_NS
  ;;

top-node)
  $K top node
  ;;

event|events)
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"; GREP="${2:-}"
  if [[ -n "$GREP" ]]; then
    $K get events $NS_ARG $ALL_NS --sort-by='.lastTimestamp' | { head -1; grep "$GREP"; }
  else
    $K get events $NS_ARG $ALL_NS --sort-by='.lastTimestamp' | tail -40
  fi
  ;;

# ── apply / edit ──────────────────────────────────────────────

apply)
  FILE="${1:-}"; shift || true
  [[ -z "$FILE" ]] && { err "需要提供文件路径"; exit 1; }
  $K apply -f "$FILE" "$@"
  ;;

edit)
  RES="${1:-}"; NAME="${2:-}"; shift 2 || true
  NS_ARG="${NS_FLAG:-${1:+-n $1}}"
  [[ -z "$RES" || -z "$NAME" ]] && { err "用法: k edit <resource> <name> [ns]"; exit 1; }
  $K edit "$RES"/"$NAME" $NS_ARG
  ;;

kust|kustomize)
  DIR="${1:-.}"
  $K apply -k "$DIR"
  ;;

# ── help ──────────────────────────────────────────────────────

help|--help|-h|"")
  usage
  ;;

*)
  # 透传给 kubectl
  $K "$CMD" "$@" ${NS_FLAG:-} ${ALL_NS:-}
  ;;

esac

```