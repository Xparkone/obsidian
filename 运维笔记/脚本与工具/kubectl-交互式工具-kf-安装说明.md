```bash
sudo cp kf /usr/local/bin/kf && sudo chmod +x /usr/local/bin/kf
```

---

## 界面结构

```
kf              # 主菜单
kf po [ns]      # 直接进 Pod 浏览器
kf dep [ns]     # 直接进 Deployment 浏览器
kf node         # Node 浏览器
kf event [ns]   # Event 浏览器
kf gpu          # GPU 资源视图
kf ctx / kf ns  # 切换 context / namespace
```

---

## 快捷键汇总

**Pod 浏览器**

|键|动作|
|---|---|
|`Enter`|exec 进入 shell（自动选 bash/sh）|
|`Ctrl-L`|日志（多容器选择 → 选行数 → `-f` 跟踪）|
|`Ctrl-D`|删除 Pod（带确认）|
|`Ctrl-Y`|查看 YAML|
|`Ctrl-E`|查看该 Pod 的 Events|
|`Ctrl-R`|刷新列表|
|`Ctrl-/`|切换 preview 面板|
|`Alt-J/K`|preview 上下滚动|

**Deployment 浏览器**

|键|动作|
|---|---|
|`Enter`|rollout restart（带确认）|
|`Ctrl-S`|交互式扩缩容|
|`Ctrl-I`|查看当前镜像|
|`Ctrl-Y`|查看 YAML|

**Node 浏览器**

|键|动作|
|---|---|
|`Enter`|`describe node` → less|
|`Ctrl-P`|列出该节点上所有 Pod|

---

## 环境变量预设

```bash
export KF_NS=prod        # 默认 namespace
export KF_CTX=rke2-prod  # 默认 context
```