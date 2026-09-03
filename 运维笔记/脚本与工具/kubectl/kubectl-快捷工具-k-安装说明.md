## 安装

```bash
# 复制到 PATH
sudo cp k /usr/local/bin/k && sudo chmod +x /usr/local/bin/k

# 或放到用户目录（无 sudo）
mkdir -p ~/.local/bin && cp k ~/.local/bin/k && chmod +x ~/.local/bin/k
```

---

## 功能速览

|命令|等价于|说明|
|---|---|---|
|`k po -n prod`|`kubectl get pod -n prod -o wide`|列出 Pod|
|`k exec aims -n default`|自动匹配 Pod → exec|模糊匹配进入 shell|
|`k log uni-aims -f -n 5`|`kubectl logs ... -f --tail=5`|跟踪日志|
|`k gpu`|自定义|各节点 GPU 分配 + Pod 占用（支持 NVIDIA/Iluvatar/MetaX）|
|`k scale my-dep 3 -n prod`|`kubectl scale --replicas=3`|扩缩容|
|`k restart my-dep -n prod`|`kubectl rollout restart`|滚动重启并等待|
|`k ns prod`|`kubectl config set-context --current --namespace`|切换默认 namespace|
|`k ctx dev-cluster`|`kubectl config use-context`|切换 context|
|`k event -n prod`|`kubectl get events --sort-by=lastTimestamp`|最近事件|

---

## 特性说明

- **模糊匹配**：`exec` / `log` / `del` 支持关键字匹配，安装 `fzf` 后自动用交互式选择
- **GPU 视图** (`k gpu`)：Python3 解析 JSON，同时适配 `nvidia.com/gpu`、`iluvatar.com/gpu`、`metax-tech.com/gpu`、`birentech.com/gpu`
- **透传**：未识别的子命令直接透传给 `kubectl`，如 `k get sts -n prod`
- `-n <ns>` 可放在命令任意位置