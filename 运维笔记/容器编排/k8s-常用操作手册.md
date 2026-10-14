# Kubernetes 常用操作参考手册

> 最后更新：2026-06-16
> 📎 本篇为生活化速查；系统化故障排查方法论见 [[K8s-故障排查方法论]]

---

## 一、标签（Labels）

标签是附加到 K8s 对象（Pod、Node、Service 等）上的键值对，用于标识和选择资源。

### 设置标签

```bash
# 给节点打标签
kubectl label nodes <node-name> <key>=<value>

# 给 Pod 打标签
kubectl label pods <pod-name> <key>=<value>

# 给命名空间打标签
kubectl label ns <namespace> <key>=<value>
```

### 查看标签

```bash
# 查看所有节点的标签
kubectl get nodes --show-labels

# 查看特定 Pod 的标签
kubectl get pods <pod-name> --show-labels

# 按标签筛选
kubectl get pods -l <key>=<value>
kubectl get nodes -l <key>=<value>

# 多条件筛选
kubectl get pods -l 'env=prod,app=nginx'
kubectl get pods -l 'env in (prod,staging)'
kubectl get pods -l 'env notin (dev)'
```

### 删除标签

```bash
# 删除标签（key 后面跟 - ）
kubectl label nodes <node-name> <key>-
```

### 修改标签

```bash
# 覆盖已有标签
kubectl label nodes <node-name> <key>=<new-value> --overwrite
```

### 在 YAML 中使用

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-app
  labels:
    app: nginx
    env: production
    tier: frontend
spec:
  # 节点选择器（基于标签）
  nodeSelector:
    disktype: ssd
```

---

## 二、节点选择器（NodeSelector）

```yaml
spec:
  nodeSelector:
    gpu: "true"
    region: us-east-1
```

```bash
# 给节点打标签以便 nodeSelector 匹配
kubectl label nodes <node> gpu=true
```

---

## 三、亲和性（Affinity）

比 nodeSelector 更灵活，支持硬性/软性规则和表达式匹配。

### 3.1 节点亲和性（Node Affinity）

```yaml
spec:
  affinity:
    nodeAffinity:
      # 硬性要求（必须满足）
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: kubernetes.io/os
                operator: In
                values:
                  - linux
              - key: gpu-type
                operator: In
                values:
                  - nvidia
      # 软性偏好（尽量满足）
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 1
          preference:
            matchExpressions:
              - key: zone
                operator: In
                values:
                  - zone-a
```

### 3.2 Pod 亲和性（Pod Affinity）

让 Pod 调度到已经有特定标签 Pod 的节点上。

```yaml
spec:
  affinity:
    podAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
              - key: app
                operator: In
                values:
                  - cache
          topologyKey: kubernetes.io/hostname   # 同主机
```

### 3.3 Pod 反亲和性（Pod Anti-Affinity）

让 Pod 远离有特定标签 Pod 的节点（常用于高可用分散部署）。

```yaml
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
              - key: app
                operator: In
                values:
                  - web-server
          topologyKey: kubernetes.io/hostname   # 不同主机
```

### topologyKey 常用值

| 值 | 含义 |
|---|------|
| `kubernetes.io/hostname` | 同一/不同节点 |
| `topology.kubernetes.io/zone` | 同一/不同可用区 |
| `topology.kubernetes.io/region` | 同一/不同区域 |

---

## 四、污点与容忍（Taints & Tolerations）

### 4.1 污点（Taints）

污点标记在节点上，拒绝不符合条件的 Pod 调度。

```bash
# 给节点添加污点
kubectl taint nodes <node-name> <key>=<value>:<effect>

# 示例
kubectl taint nodes node1 gpu=true:NoSchedule
kubectl taint nodes node2 env=prod:NoExecute
kubectl taint nodes node3 dedicated=critical:PreferNoSchedule
```

**Effect 三种类型：**

| Effect | 行为 |
|--------|------|
| `NoSchedule` | 新 Pod 不会被调度到该节点 |
| `PreferNoSchedule` | 尽量不调度到该节点（软性） |
| `NoExecute` | 新 Pod 不调度，且驱逐已存在的 Pod |

### 查看污点

```bash
kubectl describe nodes <node-name> | grep Taints
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
```

### 删除污点

```bash
# 删除指定污点
kubectl taint nodes <node-name> <key>=<value>:<effect>-

# 删除某个 key 的所有污点
kubectl taint nodes <node-name> <key>-

# 示例
kubectl taint nodes node1 gpu=true:NoSchedule-
```

### 4.2 容忍（Tolerations）

Pod 通过容忍来"接受"节点的污点。

```yaml
spec:
  tolerations:
    - key: "gpu"
      operator: "Equal"
      value: "true"
      effect: "NoSchedule"
    - key: "env"
      operator: "Equal"
      value: "prod"
      effect: "NoExecute"
      tolerationSeconds: 3600   # 被驱逐前允许停留的时间
```

**operator 类型：**

- `Equal`：key/value/effect 都匹配
- `Exists`：只需 key 匹配，不检查 value（value 字段为空）

```yaml
# Exists 示例：容忍 GPU 为任意值的污点
tolerations:
  - key: "gpu"
    operator: "Exists"
    effect: "NoSchedule"

# 容忍所有污点
tolerations:
  - operator: "Exists"
```

### 常见场景

| 场景 | 节点污点 | Pod 容忍 |
|------|---------|----------|
| GPU 专用节点 | `gpu=true:NoSchedule` | `key:gpu, operator:Equal, value:true` |
| 生产环境隔离 | `env=prod:NoSchedule` | `key:env, operator:Equal, value:prod` |
| 系统组件专用 | `node-role.kubernetes.io/master:NoSchedule` | (DaemonSet 等自动容忍) |
| 临时维护 | `maintenance=true:NoExecute` | 无容忍的 Pod 会被驱逐 |

---

## 五、Ingress

### 5.1 基本 Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /v1
            pathType: Prefix
            backend:
              service:
                name: api-v1-service
                port:
                  number: 80
          - path: /v2
            pathType: Prefix
            backend:
              service:
                name: api-v2-service
                port:
                  number: 80
```

### 5.2 TLS Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tls-ingress
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.example.com
        - www.example.com
      secretName: example-tls
  rules:
    - host: api.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: api-service
                port:
                  number: 443
```

### 5.3 常用 Nginx Ingress 注解

```yaml
metadata:
  annotations:
    # 路径重写
    nginx.ingress.kubernetes.io/rewrite-target: /$2
    # SSL 重定向
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    # 上传大小限制
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    # 超时设置
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
    # CORS
    nginx.ingress.kubernetes.io/enable-cors: "true"
    # 白名单
    nginx.ingress.kubernetes.io/whitelist-source-range: "10.0.0.0/8,172.16.0.0/12"
    # 限流
    nginx.ingress.kubernetes.io/limit-rps: "10"
    # 基础认证
    nginx.ingress.kubernetes.io/auth-type: basic
    nginx.ingress.kubernetes.io/auth-secret: basic-auth
    # 自定义错误页
    nginx.ingress.kubernetes.io/custom-http-errors: "404,502"
```

### 5.4 查看 Ingress

```bash
kubectl get ingress
kubectl get ingress -A          # 所有命名空间
kubectl describe ingress <name>
kubectl get ingress <name> -o yaml
```

### 5.5 pathType

| 类型 | 说明 |
|------|------|
| `Prefix` | 前缀匹配（如 `/api` 匹配 `/api/v1`） |
| `Exact` | 精确匹配（需完全一致） |
| `ImplementationSpecific` | 由 Ingress Controller 决定 |

---

## 六、kubectl 常用命令

### 6.1 资源查看

```bash
# 查看节点
kubectl get nodes
kubectl get nodes -o wide                    # 显示更多信息
kubectl describe node <name>

# 查看 Pod
kubectl get pods
kubectl get pods -A                          # 所有命名空间
kubectl get pods -o wide
kubectl get pods -w                          # watch 模式
kubectl describe pod <name>

# 查看 Service
kubectl get svc
kubectl get svc -A
kubectl describe svc <name>

# 查看 Deployment
kubectl get deploy
kubectl get deploy -A
kubectl describe deploy <name>

# 查看配置
kubectl get configmap
kubectl get secret
kubectl get pv,pvc                         # 持久卷
```

### 6.2 资源操作

```bash
# 创建/应用
kubectl apply -f <file.yaml>
kubectl apply -f <dir/>
kubectl apply -k <kustomize-dir/>

# 删除
kubectl delete -f <file.yaml>
kubectl delete pod <name>
kubectl delete deploy <name>
kubectl delete svc <name>
kubectl delete pod <name> --grace-period=0 --force   # 强制删除

# 编辑
kubectl edit deploy <name>
kubectl edit svc <name>

# 扩缩容
kubectl scale deploy <name> --replicas=5
```

### 6.3 Pod 操作

```bash
# 查看日志
kubectl logs <pod-name>
kubectl logs <pod-name> -c <container-name>    # 多容器
kubectl logs <pod-name> --tail=100
kubectl logs <pod-name> -f                     # follow
kubectl logs <pod-name> --since=1h             # 最近1小时

# 进入容器
kubectl exec -it <pod-name> -- /bin/bash
kubectl exec -it <pod-name> -c <container> -- /bin/sh
kubectl exec <pod-name> -- <command>           # 执行单条命令

# 端口转发
kubectl port-forward <pod-name> 8080:80
kubectl port-forward svc/<svc-name> 8080:80

# 复制文件
kubectl cp <pod-name>:/path/file ./local-file
kubectl cp ./local-file <pod-name>:/path/file

# 调试
kubectl run debug --rm -it --image=busybox --restart=Never -- sh
kubectl debug <pod-name> -it --image=busybox --target=<container>
```

### 6.4 节点操作

```bash
# 查看节点资源使用
kubectl top nodes
kubectl top pods
kubectl top pods -A

# 驱逐节点上的 Pod（节点维护）
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# 恢复节点调度
kubectl uncordon <node-name>

# 标记节点不可调度（不驱逐已有 Pod）
kubectl cordon <node-name>
```

### 6.5 名称空间

```bash
kubectl get ns
kubectl create ns <name>
kubectl delete ns <name>

# 设置默认命名空间
kubectl config set-context --current --namespace=<name>

# 查看当前上下文
kubectl config current-context
kubectl config get-contexts
```

### 6.6 事件与状态

```bash
kubectl get events --sort-by='.lastTimestamp'
kubectl get events -A --sort-by='.lastTimestamp'
kubectl get events --field-selector involvedObject.name=<pod-name>

# 查看所有资源
kubectl api-resources
kubectl api-versions

# 查看资源 YAML 示例
kubectl explain pod
kubectl explain pod.spec
kubectl explain deploy.spec.template.spec.affinity
```

### 6.7 输出格式

```bash
kubectl get pods -o wide              # 宽格式
kubectl get pods -o yaml              # YAML
kubectl get pods -o json              # JSON
kubectl get pods -o jsonpath='{.items[*].status.podIP}'
kubectl get pods -o custom-columns=NAME:.metadata.name,IP:.status.podIP
```

---

## 七、Deployment 参考

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx-deploy
  labels:
    app: nginx
spec:
  replicas: 3
  selector:
    matchLabels:
      app: nginx
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:1.25
          ports:
            - containerPort: 80
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
          livenessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 5
```

---

## 八、Service 参考

```yaml
# ClusterIP（集群内部访问）
apiVersion: v1
kind: Service
metadata:
  name: nginx-svc
spec:
  type: ClusterIP
  selector:
    app: nginx
  ports:
    - port: 80
      targetPort: 80
      protocol: TCP

---
# NodePort（节点端口暴露）
apiVersion: v1
kind: Service
metadata:
  name: nginx-nodeport
spec:
  type: NodePort
  selector:
    app: nginx
  ports:
    - port: 80
      targetPort: 80
      nodePort: 30080

---
# LoadBalancer（云环境 LB）
apiVersion: v1
kind: Service
metadata:
  name: nginx-lb
spec:
  type: LoadBalancer
  selector:
    app: nginx
  ports:
    - port: 80
      targetPort: 80
```

---

## 九、ConfigMap & Secret

```bash
# ConfigMap
kubectl create configmap <name> --from-file=<file>
kubectl create configmap <name> --from-literal=key=value
kubectl get configmap <name> -o yaml

# Secret
kubectl create secret generic <name> --from-literal=password=xxx
kubectl create secret docker-registry <name> --docker-server=x --docker-username=x --docker-password=x
kubectl create secret tls <name> --cert=cert.pem --key=key.pem
```

```yaml
# 在 Pod 中使用 ConfigMap
spec:
  containers:
    - name: app
      envFrom:
        - configMapRef:
            name: my-config
      env:
        - name: SINGLE_KEY
          valueFrom:
            configMapKeyRef:
              name: my-config
              key: single-key
      volumeMounts:
        - name: config-vol
          mountPath: /etc/config
  volumes:
    - name: config-vol
      configMap:
        name: my-config
```

---

## 十、PV & PVC（持久化存储）

```yaml
# PersistentVolume
apiVersion: v1
kind: PersistentVolume
metadata:
  name: my-pv
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  nfs:
    path: /data
    server: 192.168.1.100

---
# PersistentVolumeClaim
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: my-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
```

```yaml
# Pod 挂载 PVC
spec:
  containers:
    - name: app
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: my-pvc
```

---

## 十一、RBAC 基础

```yaml
# ServiceAccount
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-sa

---
# Role
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: default
  name: pod-reader
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]

---
# RoleBinding
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: read-pods
  namespace: default
subjects:
  - kind: ServiceAccount
    name: my-sa
roleRef:
  kind: Role
  name: pod-reader
  apiGroup: rbac.authorization.k8s.io
```

---

## 十二、快速参考卡片

| 操作 | 命令 |
|------|------|
| 查看所有 Pod | `kubectl get pods -A` |
| 查看 Pod 详情 | `kubectl describe pod <name>` |
| 查看日志 | `kubectl logs <pod> -f --tail=100` |
| 进入容器 | `kubectl exec -it <pod> -- /bin/bash` |
| 创建资源 | `kubectl apply -f <file.yaml>` |
| 删除资源 | `kubectl delete -f <file.yaml>` |
| 扩容 | `kubectl scale deploy <name> --replicas=N` |
| 滚动重启 | `kubectl rollout restart deploy <name>` |
| 回滚 | `kubectl rollout undo deploy <name>` |
| 端口转发 | `kubectl port-forward svc/<name> 8080:80` |
| 给节点打标签 | `kubectl label node <node> key=val` |
| 给节点加污点 | `kubectl taint node <node> key=val:NoSchedule` |
| 查看节点污点 | `kubectl describe node <node> \| grep Taints` |
| 驱逐节点 | `kubectl drain <node> --ignore-daemonsets` |
| 禁止调度 | `kubectl cordon <node>` |
| 恢复调度 | `kubectl uncordon <node>` |
| 查看事件 | `kubectl get events --sort-by='.lastTimestamp'` |

---

## 十三、常用别名（~/.bashrc 或 ~/.zshrc）

```bash
alias k='kubectl'
alias kg='kubectl get'
alias kgp='kubectl get pods'
alias kgn='kubectl get nodes'
alias kgs='kubectl get svc'
alias kd='kubectl describe'
alias kdp='kubectl describe pod'
alias kdel='kubectl delete'
alias kaf='kubectl apply -f'
alias kl='kubectl logs'
alias klf='kubectl logs -f'
alias kex='kubectl exec -it'
alias kns='kubectl config set-context --current --namespace'
```