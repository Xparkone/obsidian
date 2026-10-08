# Rancher 部署文档

> 场景:将 Rancher 多集群管理平台部署进一套**已有的 K8s v1.30 集群**(腾讯云 3 节点),通过集群内已有的 `app-ingress-nginx` 控制器以 NodePort 方式对公网暴露。
> 本文档基于 2026-09-29 实际部署记录整理,所有命令均已实测验证。

---

## 1. 架构与方案概述

- **部署形态**:Helm 装入现有集群的 `cattle-system` 命名空间(方案"装进现有集群"),`replicas=1`
- **暴露方式**:集群已有的 `app-ingress-nginx` 控制器,Service 为 LoadBalancer 类型但 EXTERNAL-IP 恒为 `<pending>`(裸金属/云主机集群无云 LB 控制器),**实际生效的是 NodePort:HTTP=6553,HTTPS=65101**
- **公网访问**:腾讯云公网 IP `119.45.194.198` + 安全组放通 `65101/6553`,域名使用免费泛域名服务 `119.45.194.198.sslip.io`(自动解析回该 IP)
- **TLS**:Rancher 自签名证书(由 cert-manager 签发给 sslip.io 域名),浏览器访问需信任一次

```
浏览器 ──HTTPS──▶ 119.45.194.198:65101(安全组)
                    │  NodePort(由 Cilium eBPF 提供,非 iptables)
                    ▼
        app-ingress-nginx-controller(default 命名空间)
                    │  Ingress 规则 host=119.45.194.198.sslip.io(TLS 终止)
                    ▼
              svc/rancher ──▶ pod/rancher(cattle-system)
```

纳管其他集群时,下行集群的 **cattle-cluster-agent 主动向外回连** `119.45.194.198:65101` 建立隧道(方向:集群 → Rancher,无需给集群开入站)。

---

## 2. 环境信息(实测值)

| 项 | 值 | 备注 |
| --- | --- | --- |
| K8s 版本 | v1.30.0 | kubeadm 集群,docker CRI |
| 节点 | vm-16-7-ubuntu(control-plane,10.206.16.7)、vm-16-10-ubuntu(10.206.16.10)、gpu(10.206.16.2) | 均 Ubuntu 22.04 |
| CNI | **Cilium(kube-proxy 替代模式)** | NodePort 由 eBPF 实现,`ss`/`iptables` 看不到对应监听与规则,属正常 |
| 集群公网入口 | 119.45.194.198(绑定在 vm-16-7) | 安全组管入向 |
| Ingress 控制器 | `app-ingress-nginx`(IngressClass 名 `app-ingress-nginx`,非默认类) | 预先部署于 `default` 命名空间 |
| 控制器 NodePort | 80→**6553**,443→**65101** | |
| Rancher | chart `rancher-2.15.2` / app `v2.15.2`,`replicas=1` | 仓库 `rancher-stable` |
| cert-manager | 1.x,`cert-manager` 命名空间 | Rancher 的前提依赖 |
| 访问地址 | **https://119.45.194.198.sslip.io:65101** | server-url 同此 |

> ⚠️ **版本兼容性提醒**:Rancher v2.15 官方支持矩阵要求 K8s ≥1.34(v2.15 移除了 1.33 支持)。当前 K8s v1.30 下实测可正常运行,但属于官方未验证组合。后续若要升级 Rancher,请先将集群升级至 1.34+,或将 Rancher chart 固定在支持 1.30 的 2.12.x 版本。

---

## 3. 前提条件

1. 一台能管理集群的机器,具备:`kubectl`(cluster-admin kubeconfig)+ `helm` 3.x
2. 集群节点可拉取镜像:`rancher/*`、`jetstack/cert-manager-*`(内网受限时需提前导入到节点或配置私有仓库/镜像加速)
3. 腾讯云安全组:放通 `65101`(HTTPS,必须)、`6553`(HTTP→HTTPS 跳转,可选),源 IP 建议收敛为办公网出口,不要长期 `0.0.0.0/0`

---

## 4. 安装步骤

### 4.1 安装 cert-manager(Rancher 证书依赖)

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo add rancher-stable https://releases.rancher.com/server-charts/stable
helm repo update

helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --set crds.enabled=true
```

### 4.2 安装 Rancher

```bash
kubectl create namespace cattle-system

helm install rancher rancher-stable/rancher \
  --namespace cattle-system \
  --set hostname=119.45.194.198.sslip.io \
  --set replicas=1 \
  --set bootstrapPassword='<12位以上强口令>' \
  --set ingress.ingressClassName=app-ingress-nginx
```

四个关键点:

- **`hostname` 必须是 DNS 域名,不能是 IP**(Ingress 规范限制)。没有域名就用 sslip.io:`<IP>.sslip.io` 会被公共 DNS 解析回该 IP
- **`bootstrapPassword` 用 12 位以上强口令**,公网环境禁用弱口令
- **`ingress.ingressClassName` 必须与集群实际的 IngressClass 一致**;先查再填:

  ```bash
  kubectl get ingressclass
  # 当前集群为 app-ingress-nginx(若你的集群 IngressClass 标记了 default,此参数可省略)
  ```
- 若第一次忘填 class,装完补救(即本次实际采用的路径):

  ```bash
  helm upgrade rancher rancher-stable/rancher -n cattle-system \
    --reuse-values --set ingress.ingressClassName=app-ingress-nginx
  ```

### 4.3 等待组件就绪

```bash
kubectl -n cattle-system rollout status deploy/rancher      # 约 2~3 分钟
kubectl -n cattle-system get certificate                    # tls-rancher-ingress READY=True
kubectl -n cattle-system get ingress rancher                # CLASS 应为 app-ingress-nginx
```

> 启动初期若看到少量 `helm-operation-*` Pod 报 Error(提示 webhook no endpoints),属 Rancher 自身装 webhook/fleet 的**启动竞态**,后续重试会自动成功,残留的错误 Pod 可忽略或删除。

### 4.4 三级验证

```bash
# ① 集群内:nginx -> rancher 链路(返回 200 即通)
SVCIP=$(kubectl -n default get svc app-ingress-nginx-controller -o jsonpath='{.spec.clusterIP}')
curl -sk -o /dev/null -w '%{http_code}\n' -H 'Host: 119.45.194.198.sslip.io' https://$SVCIP/

# ② 节点:NodePort 65101(注意:Cilium 集群不能用 127.0.0.1 测 NodePort,要用节点 IP)
curl -sk -o /dev/null -w '%{http_code}\n' --resolve 119.45.194.198.sslip.io:65101:10.206.16.7 https://119.45.194.198.sslip.io:65101/

# ③ 公网(任一外网机器):验证安全组 + 全链路
curl -sk -o /dev/null -w '%{http_code}\n' --connect-timeout 6 https://119.45.194.198.sslip.io:65101/
```

### 4.5 修正 server-url(必须,否则纳管集群会掉坑)

chart 的 hostname 不带端口,导致默认 server-url 是 `https://119.45.194.198.sslip.io`,而实际入口必须走 NodePort `65101`。直接改 Rancher 的 setting CR:

```bash
kubectl patch settings.management.cattle.io server-url --type=merge \
  -p '{"value":"https://119.45.194.198.sslip.io:65101"}'

# 确认
kubectl get settings.management.cattle.io server-url -o jsonpath='{.value}{"\n"}'
```

不改的后果:以后"导入集群"生成的 `kubectl apply -f https://.../v3/import/xxx.yaml` 链接缺端口,agent 永远连不上。

---

## 5. 首次登录

1. 浏览器打开 `https://119.45.194.198.sslip.io:65101`(自签名证书,点"继续访问")
2. 输入安装时设置的 `bootstrapPassword`
3. 设置 admin 正式密码(强口令)
4. 确认 server-url(应已是 `https://119.45.194.198.sslip.io:65101`)
5. 首页出现 **local** 集群(即宿主集群,自动纳管,无需导入)

---

## 6. 纳管其他集群(Import Existing)

**前提**:被管集群的节点能够**访问** `119.45.194.198:65101`(agent 反向隧道,方向是集群 → Rancher;被管集群无需入站放行,但需能出网/路由到 Rancher;且要能拉取 `rancher/rancher-agent` 镜像)。

步骤:

1. Rancher 控制台 → Cluster Management → **Create** → **Import Existing**
2. 复制生成的命令,在被管集群执行:
   ```bash
   kubectl apply -f https://119.45.194.198.sslip.io:65101/v3/import/<cluster-id>.yaml
   ```
   (自签名证书场景按页面提示使用 `--insecure-skip-tls-verify` 版本)
3. 等待 `cattle-cluster-agent` Pod Running,集群状态变 Active。

---

## 7. 安全加固清单

- [ ] admin 使用强口令;`bootstrapPassword` 不再使用弱口令的历史一次到位
- [ ] 安全组 65101/6553 源 IP 收敛为办公网出口段
- [ ] 多用户场景:创建普通账号,日常操作不用 admin;可对接 LDAP/AD/OIDC(Authentication 页面)
- [ ] 定期关注 Rancher 安全公告并升级版本(升级前先核 K8s 版本矩阵)

---

## 8. 故障排查 FAQ(本次实测踩坑记录)

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `spec.rules[0].host: Invalid value: "x.x.x.x": must be a DNS name, not an IP address` | `hostname` 填了 IP,Ingress 只接受 DNS 名 | 改用 `<IP>.sslip.io` 泛域名重装 |
| `cannot re-use a name that is still in use` | 上一次 `helm install` 失败留下了 failed 状态的 release 记录 | `helm list -n cattle-system -a` 确认后 `helm uninstall rancher -n cattle-system` 再重装 |
| 卸载报 `job rancher-post-delete failed: BackoffLimitExceeded` | 卸载后清理钩子等不到从未成功部署的 Rancher,重试到上限 | `helm uninstall rancher -n cattle-system --no-hooks` 跳过钩子;再 `kubectl -n cattle-system delete job rancher-post-delete --ignore-not-found` |
| Ingress `ADDRESS` 一直空,页面 404/default backend | Ingress `CLASS` 为 `<none>`,未绑定到集群实际的 IngressClass | `helm upgrade --reuse-values --set ingress.ingressClassName=<实际类名>` |
| `curl 127.0.0.1:65101` 不通但服务正常 | Cilium kube-proxy 替代模式不为回环提供 NodePort | 改用节点内网 IP 或公网 IP 测试 |
| `ss`/`iptables` 找不到 65101 监听/规则 | 同上,eBPF 接管转发 | 正常现象,勿当故障 |
| 控制器 Service `EXTERNAL-IP` 恒为 `<pending>` | 无云 LB 控制器,LoadBalancer 永不兑现 | 预期行为,直接使用 NodePort 端口访问 |
| Certificate 一直不 Ready | cert-manager 未安装或异常 | 检查 `kubectl get pods -n cert-manager` 后重装 4.1 |
| 纳管集群生成的 import 链接连不上 | server-url 缺端口 | 执行 4.5 的 patch,再重新生成 |

---

## 9. 日常运维

**升级 Rancher**

```bash
helm repo update
# 先确认目标 chart 版本支持你集群的 K8s 版本(当前 v1.30 请勿越过 2.12.x;或先升集群到 ≥1.34)
helm upgrade rancher rancher-stable/rancher -n cattle-system \
  --version <chart版本> --reuse-values
```

**备份**

- 方式一(推荐):装 `rancher-backup` operator(Apps 市场),定期快照到 S3/MinIO
- 方式二(兜底):对宿主集群 etcd 做定时快照;Rancher 状态全部存于宿主集群 etcd

**卸载**

```bash
helm uninstall rancher -n cattle-system            # 若卡 post-delete 钩子,加 --no-hooks
kubectl -n cattle-system delete job rancher-post-delete --ignore-not-found
```

> 注:卸载 Rancher **不影响**被管集群的业务运行,只会断开管理隧道;被管集群里的 `cattle-system` 命名空间与 webhook 需另行清理。

---

## 10. 常用命令速查

```bash
# 组件状态
kubectl -n cattle-system get pods
kubectl -n cattle-system rollout status deploy/rancher

# Rancher 日志
kubectl -n cattle-system logs deploy/rancher --tail=100

# 查看/修改 server-url
kubectl get settings.management.cattle.io server-url -o jsonpath='{.value}{"\n"}'
kubectl patch settings.management.cattle.io server-url --type=merge -p '{"value":"..."}'

# 找回 bootstrap 密码(如当时未显式设置)
kubectl get secret -n cattle-system bootstrap-secret \
  -o go-template='{{.data.bootstrapPassword|base64decode}}{{"\n"}}'

# 查看安装时传入的参数(含 bootstrapPassword,注意保密)
helm get values rancher -n cattle-system -a
```

---

## 11. 部署变更记录

| 日期 | 操作 | 结果 |
| --- | --- | --- |
| 2026-09-29 | 首次 `helm install`(hostname=IP) | 失败:Ingress 校验拒绝 IP 形式 host |
| 2026-09-29 | hostname 改为 `119.45.194.198.sslip.io` 重装 | 报 name in use → 卸载残留 release;卸载清理钩子报 BackoffLimitExceeded → `--no-hooks` 清除后重装成功 |
| 2026-09-29 | Rancher v2.15.2 Running,但 Ingress CLASS 为空 | `helm upgrade --reuse-values --set ingress.ingressClassName=app-ingress-nginx` 修复,三级验证全部 200 |
| 2026-09-29 | 修正 server-url 为带端口形式 | `https://119.45.194.198.sslip.io:65101` |
