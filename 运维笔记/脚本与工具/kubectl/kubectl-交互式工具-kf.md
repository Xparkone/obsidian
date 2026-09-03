#!/usr/bin/env bash
# kf - fzf 驱动的交互式 kubectl 操作台
# 依赖: kubectl, fzf (>=0.30)
# 安装: cp kf /usr/local/bin/kf && chmod +x /usr/local/bin/kf

set -euo pipefail
command -v fzf     &>/dev/null || { echo "需要安装 fzf: brew install fzf 或 apt install fzf"; exit 1; }
command -v kubectl &>/dev/null || { echo "需要安装 kubectl"; exit 1; }

K="kubectl"
NS="${KF_NS:-}"          # 可通过环境变量预设 namespace
CTX="${KF_CTX:-}"        # 可通过环境变量预设 context
SHELL_CMD="${KF_SHELL:-sh}"

# ─── 颜色 ────────────────────────────────────────────────────
C_HEADER=$'\033[1;36m'
C_RESET=$'\033[0m'

# ─── fzf 公共选项 ────────────────────────────────────────────
FZF_COMMON=(
  --ansi
  --layout=reverse
  --border=rounded
  --info=inline
  --bind='ctrl-r:reload(eval "$FZF_RELOAD_CMD")'
  --bind='ctrl-/:toggle-preview'
  --bind='alt-j:preview-down'
  --bind='alt-k:preview-up'
)

ns_flag() { [[ -n "$NS" ]] && echo "-n $NS" || echo "-A"; }

# ─── 选择 Context ────────────────────────────────────────────
pick_ctx() {
  local cur
  cur=$($K config current-context 2>/dev/null || echo "none")
  CTX=$(
    $K config get-contexts --no-headers \
      | awk '{print ($1=="*") ? "\033[32m" $2 " (current)\033[0m" : $2}' \
      | fzf "${FZF_COMMON[@]}" \
          --prompt="Context > " \
          --header="当前: $cur  |  Enter 切换  Esc 返回" \
          --height=40% \
      | awk '{print $1}'
  ) || return 0
  [[ -n "$CTX" ]] && $K config use-context "$CTX" && echo "→ 已切换到 $CTX"
}

# ─── 选择 Namespace ──────────────────────────────────────────
pick_ns() {
  NS=$(
    $K get ns --no-headers -o custom-columns='NAME:.metadata.name,STATUS:.status.phase' \
      | fzf "${FZF_COMMON[@]}" \
          --prompt="Namespace > " \
          --header="当前: ${NS:-all}  |  Enter 选择  Esc 返回" \
          --height=50% \
          --preview="$K get pod -n {1} --no-headers 2>/dev/null | head -30 || echo '(无 Pod)'" \
          --preview-window=right:50% \
      | awk '{print $1}'
  ) || return 0
  echo "→ Namespace 已设为: $NS"
}

# ─── Pod 浏览器（主界面）────────────────────────────────────
pod_browser() {
  local ns_arg
  ns_arg=$(ns_flag)

  # 构建 reload 命令（供 ctrl-r 使用）
  export FZF_RELOAD_CMD="$K get pod $ns_arg --no-headers \
    -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.containerStatuses[0].ready,STATUS:.status.phase,RESTARTS:.status.containerStatuses[0].restartCount,NODE:.spec.nodeName,IP:.status.podIP' \
    2>/dev/null | column -t"

  local selected
  selected=$(
    eval "$FZF_RELOAD_CMD" \
      | fzf "${FZF_COMMON[@]}" \
          --prompt="Pod > " \
          --header="${C_HEADER}Namespace: ${NS:-ALL}  |  enter:进入shell  ctrl-l:日志  ctrl-d:删除  ctrl-y:yaml  ctrl-e:events  ctrl-r:刷新${C_RESET}" \
          --preview="$K describe pod \$(echo {} | awk '{print \$2}') -n \$(echo {} | awk '{print \$1}') 2>/dev/null | head -60" \
          --preview-window=right:55%:wrap \
          --expect=ctrl-l,ctrl-d,ctrl-y,ctrl-e,ctrl-n \
          --height=90%
  ) || return 0

  [[ -z "$selected" ]] && return 0

  local key pod_ns pod_name
  key=$(echo "$selected"      | head -1)
  pod_ns=$(echo "$selected"   | tail -1 | awk '{print $1}')
  pod_name=$(echo "$selected" | tail -1 | awk '{print $2}')

  case "$key" in
    ctrl-l) pod_logs  "$pod_name" "$pod_ns" ;;
    ctrl-d) pod_del   "$pod_name" "$pod_ns" ;;
    ctrl-y) pod_yaml  "$pod_name" "$pod_ns" ;;
    ctrl-e) pod_event "$pod_name" "$pod_ns" ;;
    *)      pod_exec  "$pod_name" "$pod_ns" ;;
  esac
}

pod_exec() {
  local pod="$1" ns="$2"
  echo "→ exec into $pod ($ns)"
  # 依次尝试 bash → sh，避免 which 在 distroless/minimal 容器里不存在
  local sh="sh"
  for candidate in bash sh; do
    if $K exec -n "$ns" "$pod" -- "$candidate" -c "exit 0" >/dev/null 2>&1; then
      sh="$candidate"
      break
    fi
  done
  echo "  shell: $sh"
  $K exec -it -n "$ns" "$pod" -- "$sh"
}

pod_logs() {
  local pod="$1" ns="$2"
  # 选容器（多容器时）
  local containers
  containers=$($K get pod -n "$ns" "$pod" \
    -o jsonpath='{range .spec.containers[*]}{.name}{"\n"}{end}' 2>/dev/null)
  local container=""
  local count
  count=$(echo "$containers" | grep -c . || true)
  if [[ $count -gt 1 ]]; then
    container=$(echo "$containers" | fzf --prompt="选择容器 > " --height=30% --border) || return 0
    container="-c $container"
  fi

  local lines
  lines=$(printf "20\n50\n100\n200\nall" \
    | fzf --prompt="显示行数 > " --height=30% --border) || lines=50
  [[ "$lines" == "all" ]] && lines=""

  echo "→ logs $pod $container"
  if [[ -z "$lines" ]]; then
    $K logs -n "$ns" "$pod" $container -f
  else
    $K logs -n "$ns" "$pod" $container --tail="$lines" -f
  fi
}

pod_del() {
  local pod="$1" ns="$2"
  echo ""
  read -r -p "⚠ 确认删除 Pod '$pod' (ns=$ns)? [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { echo "已取消"; return 0; }
  $K delete pod -n "$ns" "$pod"
  echo "✔ 已删除"
}

pod_yaml() {
  local pod="$1" ns="$2"
  $K get pod -n "$ns" "$pod" -o yaml \
    | fzf --ansi --disabled --no-mouse \
        --prompt="$pod yaml > " \
        --preview-window=hidden \
        --bind='ctrl-c:abort' \
        --height=90%
}

pod_event() {
  local pod="$1" ns="$2"
  $K get events -n "$ns" \
    --field-selector="involvedObject.name=$pod" \
    --sort-by='.lastTimestamp' \
    | fzf --ansi --disabled --no-mouse \
        --prompt="events > " \
        --height=60%
}

# ─── Deployment 浏览器 ───────────────────────────────────────
deploy_browser() {
  local ns_arg
  ns_arg=$(ns_flag)

  export FZF_RELOAD_CMD="$K get deploy $ns_arg --no-headers \
    -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,READY:.status.readyReplicas,DESIRED:.spec.replicas,AVAILABLE:.status.availableReplicas' \
    2>/dev/null | column -t"

  local selected
  selected=$(
    eval "$FZF_RELOAD_CMD" \
      | fzf "${FZF_COMMON[@]}" \
          --prompt="Deployment > " \
          --header="${C_HEADER}enter:restart  ctrl-s:scale  ctrl-i:镜像  ctrl-y:yaml  ctrl-r:刷新${C_RESET}" \
          --preview="$K describe deploy \$(echo {} | awk '{print \$2}') -n \$(echo {} | awk '{print \$1}') 2>/dev/null | head -60" \
          --preview-window=right:55%:wrap \
          --expect=ctrl-s,ctrl-i,ctrl-y \
          --height=90%
  ) || return 0

  [[ -z "$selected" ]] && return 0

  local key dep_ns dep_name
  key=$(echo "$selected"      | head -1)
  dep_ns=$(echo "$selected"   | tail -1 | awk '{print $1}')
  dep_name=$(echo "$selected" | tail -1 | awk '{print $2}')

  case "$key" in
    ctrl-s) deploy_scale   "$dep_name" "$dep_ns" ;;
    ctrl-i) deploy_image   "$dep_name" "$dep_ns" ;;
    ctrl-y)
      $K get deploy -n "$dep_ns" "$dep_name" -o yaml \
        | fzf --ansi --disabled --no-mouse --height=90% ;;
    *)
      echo "→ rollout restart $dep_name"
      read -r -p "确认滚动重启? [y/N] " ans
      [[ "$ans" =~ ^[Yy]$ ]] || return 0
      $K rollout restart deploy/"$dep_name" -n "$dep_ns"
      $K rollout status  deploy/"$dep_name" -n "$dep_ns"
      ;;
  esac
}

deploy_scale() {
  local dep="$1" ns="$2"
  local cur
  cur=$($K get deploy -n "$ns" "$dep" -o jsonpath='{.spec.replicas}')
  echo "当前副本数: $cur"
  read -r -p "新副本数: " num
  [[ "$num" =~ ^[0-9]+$ ]] || { echo "无效数字"; return 1; }
  $K scale deploy/"$dep" -n "$ns" --replicas="$num"
  $K rollout status deploy/"$dep" -n "$ns"
}

deploy_image() {
  local dep="$1" ns="$2"
  $K get deploy -n "$ns" "$dep" \
    -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{"\t"}{.image}{"\n"}{end}' \
    | column -t \
    | fzf --ansi --disabled --no-mouse --prompt="镜像 > " --height=40%
}

# ─── Node 浏览器 ─────────────────────────────────────────────
node_browser() {
  export FZF_RELOAD_CMD="$K get node --no-headers \
    -o custom-columns='NAME:.metadata.name,STATUS:.status.conditions[-1].type,ROLES:.metadata.labels.kubernetes\\.io/role,AGE:.metadata.creationTimestamp,VERSION:.status.nodeInfo.kubeletVersion' \
    2>/dev/null | column -t"

  local selected
  selected=$(
    eval "$FZF_RELOAD_CMD" \
      | fzf "${FZF_COMMON[@]}" \
          --prompt="Node > " \
          --header="${C_HEADER}enter:describe  ctrl-p:列出Pod  ctrl-r:刷新${C_RESET}" \
          --preview="$K describe node \$(echo {} | awk '{print \$1}') 2>/dev/null | head -80" \
          --preview-window=right:60%:wrap \
          --expect=ctrl-p \
          --height=90%
  ) || return 0

  [[ -z "$selected" ]] && return 0

  local key node_name
  key=$(echo "$selected"       | head -1)
  node_name=$(echo "$selected" | tail -1 | awk '{print $1}')

  case "$key" in
    ctrl-p)
      $K get pod -A --field-selector="spec.nodeName=$node_name" \
        | fzf --ansi --disabled --no-mouse \
            --prompt="$node_name pods > " \
            --height=60%
      ;;
    *)
      $K describe node "$node_name" | less
      ;;
  esac
}

# ─── Event 浏览器 ────────────────────────────────────────────
event_browser() {
  local ns_arg
  ns_arg=$(ns_flag)
  $K get events $ns_arg --sort-by='.lastTimestamp' \
    --no-headers \
    -o custom-columns='NS:.metadata.namespace,TIME:.lastTimestamp,TYPE:.type,REASON:.reason,OBJ:.involvedObject.name,MSG:.message' \
    2>/dev/null \
    | fzf "${FZF_COMMON[@]}" \
        --prompt="Event > " \
        --header="${C_HEADER}Namespace: ${NS:-ALL}  (Warning 排前)${C_RESET}" \
        --height=90% \
        --preview="echo {} | tr -s ' ' | cut -d' ' -f6-" \
        --preview-window=bottom:3:wrap \
        --color='hl:red,hl+:red' \
    || true
}

# ─── GPU 视图 ────────────────────────────────────────────────
gpu_view() {
  (
    echo "=== 节点 GPU Allocatable ==="
    $K get nodes -o json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
vendors = ['nvidia.com/gpu','iluvatar.com/gpu','metax-tech.com/gpu','birentech.com/gpu']
print(f'NODE                           VENDOR                     CAP  ALLOC')
print('-'*70)
for n in data['items']:
  name = n['metadata']['name']
  alloc = n['status'].get('allocatable', {})
  cap   = n['status'].get('capacity', {})
  for v in vendors:
    if v in cap:
      print(f'{name:<31} {v:<26} {cap[v]:>4} {alloc.get(v,\"?\"):>6}')
"
    echo ""
    echo "=== Pod GPU 使用 ==="
    $K get pod -A -o json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
vendors = ['nvidia.com/gpu','iluvatar.com/gpu','metax-tech.com/gpu','birentech.com/gpu']
print(f'NAMESPACE            POD                                      GPU  VENDOR')
print('-'*90)
for p in data['items']:
  ns = p['metadata']['namespace']
  name = p['metadata']['name']
  for c in p['spec'].get('containers', []):
    for v in vendors:
      lim = c.get('resources', {}).get('limits', {}).get(v)
      if lim:
        print(f'{ns:<21} {name:<41} {lim:>4}  {v}')
"
  ) | fzf --ansi --disabled --no-mouse \
        --prompt="GPU > " \
        --header="${C_HEADER}GPU 资源视图  (只读)${C_RESET}" \
        --height=90% \
    || true
}

# ─── 主菜单 ──────────────────────────────────────────────────
main_menu() {
  while true; do
    local ctx_cur ns_cur
    ctx_cur=$($K config current-context 2>/dev/null || echo "?")
    ns_cur="${NS:-all}"

    local choice
    choice=$(printf \
      "🔍 Pod 浏览器\n🚀 Deployment 浏览器\n🖥  Node 浏览器\n⚡ Event 浏览器\n📊 GPU 资源视图\n──────────────\n🌐 切换 Context  (当前: $ctx_cur)\n📁 切换 Namespace (当前: $ns_cur)\n❌ 退出" \
      | fzf "${FZF_COMMON[@]}" \
          --prompt="kf > " \
          --header="${C_HEADER}kubectl fzf 操作台  |  ctx: $ctx_cur  ns: $ns_cur${C_RESET}" \
          --height=50% \
          --no-multi \
          --bind='esc:abort' \
    ) || break

    case "$choice" in
      *Pod*)        pod_browser    ;;
      *Deployment*) deploy_browser ;;
      *Node*)       node_browser   ;;
      *Event*)      event_browser  ;;
      *GPU*)        gpu_view       ;;
      *Context*)    pick_ctx       ;;
      *Namespace*)  pick_ns        ;;
      *退出*)        break          ;;
    esac
  done
}

# ─── 入口 ────────────────────────────────────────────────────
# 支持直接子命令跳过菜单
case "${1:-}" in
  po|pod)     NS="${2:-$NS}" pod_browser    ;;
  dep|deploy) NS="${2:-$NS}" deploy_browser ;;
  node)                      node_browser   ;;
  event)      NS="${2:-$NS}" event_browser  ;;
  gpu)                       gpu_view       ;;
  ctx|context)               pick_ctx       ;;
  ns|namespace)              pick_ns        ;;
  *)                         main_menu      ;;
esac
