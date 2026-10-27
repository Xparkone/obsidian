# CI/CD 生产加固设计

> 文档状态：设计。尚未在目标集群启用准入、镜像复制或告警。
>
> 核对日期：2026-10-27
>
> 本文设计第 4.12 章通过之后的五件加固。日常发布步骤仍以 [可落地的 CI/CD 发布流程](可落地CI-CD发布流程.md) 为准。第 4.12.7 章的七行证据还没齐时，不实施本文。

## 1. 文档概述

### 1.1 解决什么问题

当前流程能把同一枚镜像指纹从预发送到生产，也能在流水线里验签、扫描和审批。还有五个口子没有封住：

1. 签名只在流水线里检查。有人绕过 Git，把别的镜像写进集群，集群仍会拉取。
2. 生产是否真能对外服务，靠人看 15 分钟。人离开屏幕，失败的发布会留在线上。
3. 预发和生产共用一个 Harbor 项目。能推预发的机器人，也能覆盖生产项目里的镜像。
4. 有人用 `kubectl` 或 Argo CD 界面改了生产，自我修复会改回去，但没有人收到「发生过偏离」的通知。
5. GitOps 令牌、Harbor 机器人和签名私钥会过期。过期当天发布才会失败，没有提前轮换的责任人。

### 1.2 适合哪些读者

负责把这条发布链路从「能上生产」收成「绕不开生产门禁」的平台工程师和发布负责人。

### 1.3 读完能得到什么

- 五件加固各自封住哪一个口子，以及它们的先后顺序。
- 每件加固的通过标准。没达到标准，就不进入下一件。
- 明确不做金丝雀、多集群和飞书审批。那些不在本设计里。

## 2. 前置条件

开始实施前，[可落地的 CI/CD 发布流程](可落地CI-CD发布流程.md) 第 4.12.7 章的七行都已有证据。尤其是：

- 流水线已经用固定私钥给镜像指纹签名，公钥可核对。
- 生产合并有第二个批准人，作者不能自批。
- 预发和生产使用同一枚 `sha256`。
- 回滚演练做过，并且知道要先关自动同步。

【需要确认】Kyverno 是否已安装。没安装时，第 4.1 章先只记录策略，不要把未验证的准入控制器直接设成 `Enforce`。通知渠道用现有的告警入口，不新建审批系统。

## 3. 核心概念

五件事的顺序不能颠倒。前一件没通过，后一件会建立在错误的镜像地址或错误的失败信号上。

```text
第 4.12 章已经成立
        |
        v
镜像分项目：预发仓库只给预发用，生产仓库只接收验过的指纹
        |
        v
复制签名：生产仓库里的同一枚指纹也要能验签
        |
        v
准入改为强制：生产 Pod 只能拉生产仓库里验过签的镜像
        |
        v
发布后检查：同步成功后自动打业务请求，失败就按回滚流程撤回
        |
        v
偏离告警：集群和 Git 不一致超过 5 分钟就通知
        |
        v
凭据台账：到期前 14 天轮换，并做一次成功的拉取或签名
```

三个词在后文里的意思：

- **晋级**：把已经在预发跑通的那枚指纹复制到生产镜像仓库，不重新构建。
- **准入**：Kubernetes 在创建 Pod 之前做的检查。检查失败，Pod 不会被创建。
- **偏离**：集群里的实际对象和 Git 里写的不一致。Argo CD 里显示为 `OutOfSync`。

## 4. 实现步骤

这里的步骤是设计落地顺序。每一步都写清做什么、为什么、怎样算通过。

### 4.1 预发和生产分成两个镜像项目

**做什么：**

Harbor 使用两个项目，权限分开。

| 项目 | 谁可以推 | 谁可以拉 | 谁不能做 |
|---|---|---|---|
| `apps-staging` | CI 推送机器人 | 预发节点上的拉取机器人 | 删除镜像；推送到生产项目 |
| `apps-prod` | 只在晋级时使用的复制机器人 | 生产节点上的拉取机器人 | CI 日常构建机器人推送；拉取机器人推送 |

CI 仍然只构建一次，镜像先进入 `apps-staging`，标签仍是完整提交号。预发 GitOps 引用：

```text
harbor.example.com/apps-staging/demo-api@sha256:<指纹>
```

预发健康检查通过之后，`open-prod-mr` 先把这枚指纹复制到生产项目，再开生产 GitOps 合并申请。生产清单引用：

```text
harbor.example.com/apps-prod/demo-api@sha256:<同一枚指纹>
```

复制用按指纹复制，不按标签复制：

```bash
skopeo copy \
  "docker://harbor.example.com/apps-staging/demo-api@sha256:<指纹>" \
  "docker://harbor.example.com/apps-prod/demo-api@sha256:<指纹>"
```

复制后在生产项目里用同一把私钥再签一次。cosign 的签名存在镜像所在的那个仓库里。只复制镜像、不在生产仓库签名，准入会认为生产镜像没有签名。

```bash
cosign sign --key env://COSIGN_PRIVATE_KEY --yes \
  "harbor.example.com/apps-prod/demo-api@sha256:<指纹>"
cosign verify --key cosign.pub \
  "harbor.example.com/apps-prod/demo-api@sha256:<指纹>"
```

两个项目都启用标签不可变。复制机器人没有删除权限。

**为什么：** 构建凭证和生产运行凭证分开之后，泄漏的 CI 密码不能覆盖已经在生产项目里的镜像。指纹不变，所以预发验证过的内容就是生产拉取的内容。

**预期结果：** 用 CI 推送机器人向 `apps-prod` 推送被拒绝。生产 Deployment 的镜像行以 `harbor.example.com/apps-prod/` 开头，并且 `@sha256:` 与预发验证过的指纹相同。`cosign verify` 对生产仓库里的这枚指纹成功。

【需要确认】`skopeo` 与 `cosign` 的版本，以及复制机器人账号名。账号名含 `$` 时，GitLab 变量要关闭 Expand variable reference。

### 4.2 集群拒绝未签名或仓库不对的镜像

**做什么：** 用 Kyverno 在 `demo-staging` 和 `demo-prod` 检查新建和更新的 Pod。先把策略设为 `Audit`，观察至少一次完整发布没有误拦，再改成 `Enforce`。

规则只有两条：

1. `demo-staging` 里的业务镜像必须来自 `harbor.example.com/apps-staging/`。
2. `demo-prod` 里的业务镜像必须来自 `harbor.example.com/apps-prod/`，并且用 GitOps 仓库里的那把公钥验签通过。

策略骨架：

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: demo-api-signed-image
spec:
  validationFailureAction: Audit
  background: true
  rules:
    - name: prod-image-must-be-signed
      match:
        any:
          - resources:
              kinds: ["Pod"]
              namespaces: ["demo-prod"]
      verifyImages:
        - imageReferences:
            - "harbor.example.com/apps-prod/demo-api*"
          attestors:
            - entries:
                - keys:
                    publicKeys: |-
                      # 换成 GitOps 仓库中的 cosign.pub，不要另造一把公钥
                      -----BEGIN PUBLIC KEY-----
                      【需要确认】
                      -----END PUBLIC KEY-----
```

`Audit` 期间看 Kyverno 的 PolicyReport。一次预发发布和一次生产发布都没有误报之后，把 `validationFailureAction` 改成 `Enforce`。这个修改本身走 Git 合并。

**为什么：** 流水线验签挡的是正常发布路径。准入挡的是绕过 Git 的路径。两把公钥如果不是同一把，签过名的镜像仍会被拒绝，所以公钥只维护一份。

**预期结果：**

- `Enforce` 之后，在 `demo-prod` 创建一个使用 `apps-staging` 镜像或未签名镜像的 Pod，创建失败，事件里能看到策略名 `demo-api-signed-image`。
- 正常生产发布的 Pod 能创建，Argo CD 仍是 `Synced Healthy`。

【需要确认】集群里 Kyverno 的版本是否支持 `verifyImages`。不支持时，先不要改成 `Enforce`，在设计备注里记下版本缺口。

### 4.3 同步成功后自动做发布检查

**做什么：** 在生产 GitOps 的 overlay 里加一个 Argo CD PostSync Job。同步成功后它才运行。它做两件检查，任一失败则 Job 失败，应用健康变为 `Degraded`：

1. 集群内请求 `http://demo-api.demo-prod.svc/healthz`，要求 HTTP 200。
2. 当前就绪 Pod 的镜像等于 Deployment 上的 `apps-prod/demo-api@sha256:<指纹>`。

Job 使用单独的 ServiceAccount，只能 `get` 本命名空间的 Deployment 和 Pod。检查容器镜像使用钉死的指纹，不使用 `latest`。Job 成功后由 Hook 删除，避免留下完成的 Job 占着历史。

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: demo-api-verify
  annotations:
    argocd.argoproj.io/hook: PostSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: demo-api-verify
      containers:
        - name: verify
          image: harbor.example.com/apps-prod/release-verify@sha256:【需要确认】
          env:
            - name: EXPECTED_IMAGE
              value: harbor.example.com/apps-prod/demo-api@sha256:由本次晋级写入
```

检查脚本的通过条件写死在镜像里，不从发布请求里接收任意镜像地址。`EXPECTED_IMAGE` 由 GitOps 清单写明，和 Deployment 使用同一枚指纹。

Job 失败时，发布负责人按原文档第 4.11 章撤回。不要在 Job 里直接改 Deployment。

人看 15 分钟仍然保留，作为自动检查之外的业务观察。自动检查通过、人工观察结论是「维持」，这次发布才算完成。

**为什么：** `Synced` 只说明声明已经应用到集群。PostSync 把「进程应答」和「跑的是这枚指纹」变成同步结果的一部分。失败会停在 `Degraded`，不会被当成一次成功发布。

**预期结果：** 故意把健康检查路径改错时，应用变为 `Degraded`，Pod 镜像仍是旧的成功版本或已按第 4.11 章撤回。恢复路径后，下一次同步的 Job 成功，应用回到 `Healthy`。

### 4.4 偏离超过 5 分钟就通知

**做什么：** 给 `demo-api-prod` 配置 Argo CD 通知。条件是应用处于 `OutOfSync` 连续超过 5 分钟。通知里带上应用名、命名空间、Git 修订和应用链接。5 分钟内的短暂偏离不发，避免正常同步过程中的抖动。

通知送到现有告警通道。它只告知「Git 和集群不一致」，不提供批准按钮，也不触发同步。

收到通知后的处理：

1. 看 Diff，确认是谁改的、改了哪个字段。
2. 这是一次未进 Git 的修改：当天把正确状态写回 Git，或让自我修复改回 Git。发布单记下发生过偏离。
3. 这是紧急回滚：确认自动同步已经关掉，并按第 4.11 章在当天补上 Git revert。

【需要确认】Argo CD Notifications 的安装方式和告警通道。触发器名称随版本可能不同，实施时用「`sync.status == OutOfSync` 持续 5 分钟」这个条件核对官方示例，不要照抄过期的触发器名字。

**为什么：** 自我修复会把手工修改盖掉，但如果没有通知，没人知道生产被改过。通知把偏离变成一次可追查的事件。

**预期结果：** 在测试环境用 `kubectl annotate` 给生产 Deployment 加一个无关注解。5 分钟内收到一条通知。不要在生产的真实流量上做这个试验。试验结束后，Git 与集群重新一致。

### 4.5 凭据到期前轮换

**做什么：** 在平台仓库放一份台账，只记录名称、用途、到期日和责任人，不记录秘密本身。

| 凭据 | 用在哪 | 到期前谁换 |
|---|---|---|
| CI 推送机器人 | 只推 `apps-staging` | 平台 |
| 复制机器人 | 把指纹复制到 `apps-prod` 并签名时拉取 | 平台 |
| 预发拉取机器人 | `demo-staging` 的 `harbor-pull` | 平台 |
| 生产拉取机器人 | `demo-prod` 的 `harbor-pull` | 平台 |
| GitOps 项目令牌 | 开 GitOps 合并申请 | 平台 |
| 签名私钥 | CI 变量 `COSIGN_PRIVATE_KEY` | 平台，公钥同时更新到 GitOps 和 Kyverno |

到期前 14 天轮换。顺序固定为四步：签发新凭据，让消费者改用新凭据，做一次成功的推送或拉取，再作废旧凭据。生产拉取秘密替换后，用新秘密拉取当前正在运行的那枚指纹，成功之后再作废旧秘密。

签名私钥轮换要多一步：新发布改用新私钥签名，Kyverno 在旧 Pod 还在时同时信任新旧两把公钥。全部运行中的生产 Pod 都已用新签名重建之后，再从策略里去掉旧公钥。

**为什么：** 机器人账号和令牌过期时，表现是全站拉不到镜像或开不出合并申请，和一次故障很像。提前轮换把这件事变成一次有验证的变更。

**预期结果：** 台账里每一行都有到期日和责任人。至少演练过一次「签发、替换、验证、作废」。旧凭据作废后，用旧凭据推送或拉取失败，用新凭据成功。

## 5. 完整示例

下面用一次已经在预发跑通的指纹，走完加固后的生产路径。指纹用 `<指纹>` 表示，实施时换成 `image-digest.txt` 里的值。

1. 预发 Deployment 镜像是 `harbor.example.com/apps-staging/demo-api@sha256:<指纹>`，状态为 `Synced Healthy`。
2. 发布负责人在同一条流水线点击 `open-prod-mr`。
3. 该 Job 执行 `skopeo copy`，把这枚指纹复制到 `apps-prod`，再用同一私钥签名，并执行 `cosign verify`。验签失败则 Job 失败，不创建生产合并申请。
4. 生产合并申请只把生产 overlay 的镜像改成 `harbor.example.com/apps-prod/demo-api@sha256:<指纹>`。第二个批准人合并。
5. Kyverno 以 `Enforce` 放行这个 Pod。来源或签名不对的 Pod 不会出现。
6. Argo CD 同步后运行 PostSync Job。健康检查返回 200，就绪 Pod 的镜像与 Deployment 一致。应用保持 `Healthy`。
7. 发布负责人完成 15 分钟观察，发布单结论写「维持」。若 Job 失败或观察结论是撤回，走第 4.11 章，不在 Job 里改镜像。

发布单在原有字段之外增加三行：

```text
生产镜像: harbor.example.com/apps-prod/demo-api@sha256:<指纹>
生产仓库验签: 通过或失败
PostSync Job: 成功或失败
```

## 6. 常见问题与排查

### 6.1 预发能跑，生产 Pod 创建失败

现象：生产合并已完成，Argo CD 同步报错，Pod 没有起来。

可能原因：生产镜像还在 `apps-staging`；复制成功但生产仓库没有签名；Kyverno 里的公钥和签名私钥不是一对。

解决方法：对生产镜像执行 `cosign verify --key cosign.pub`。失败就先补签名，不要把策略改回 `Audit` 来让 Pod 起来。公钥以 GitOps 仓库里的 `cosign.pub` 为准。

### 6.2 复制成功，验签仍失败

现象：`skopeo copy` 成功，`cosign verify` 在生产仓库失败，在预发仓库成功。

可能原因：签名对象留在预发仓库，没有在生产仓库重新签名。

解决方法：对生产仓库里的同一枚指纹执行 `cosign sign`，然后再 verify。确认指纹字符串两边一致。

### 6.3 PostSync Job 失败，但手工访问是通的

现象：应用 `Degraded`，从集群外访问返回 200。

可能原因：Job 访问的是集群内服务名，网络策略挡住了 Job 所在的 Pod；`EXPECTED_IMAGE` 和 Deployment 镜像字符串不一致，差在仓库前缀或指纹大小写。

解决方法：看 Job 日志。网络被拒绝时，给这个 ServiceAccount 单独放行到 `demo-api` 的 80 端口。字符串不一致时，以 Deployment 的镜像字段为准修改 Git，不在集群里改 Job。

### 6.4 正常发布也收到偏离通知

现象：每次同步都收到 `OutOfSync`。

可能原因：通知没有等待 5 分钟；有状态字段或由控制器写回的注解被算进 Diff。

解决方法：确认条件是持续 5 分钟。若某个注解总会被别的控制器改写，把它加入 Argo CD 的忽略差异，而不是关掉通知。【需要确认】现网是否已有 `ignoreDifferences`。

### 6.5 轮换拉取秘密后，新 Pod 拉不到镜像

现象：旧 Pod 仍在运行，新 Pod 是 `ImagePullBackOff`。

可能原因：新秘密已写入，旧机器人已作废，但新机器人没有生产项目的拉取权限；或者秘密里的用户名被 `$` 截断。

解决方法：用新秘密在一个临时 Pod 里拉取当前指纹。成功之前不作废旧机器人。用户名与 Harbor 页面逐字核对。

## 7. 注意事项与最佳实践

- 第 4.12.7 章没有证据之前，不实施本章。本章五步按第 3 章的顺序做，不并行打开 `Enforce` 和镜像改名。
- `Audit` 至少覆盖一次真实的预发发布和一次生产发布，再改成 `Enforce`。
- 公钥、策略、生产镜像前缀都在 Git 里。修改它们走合并申请。
- PostSync Job 只读。它不能调用 Argo CD 同步，也不能修改 Deployment。
- 偏离通知不是审批。批准生产仍然只发生在 GitOps 合并申请上。
- 本设计不做这些事：按百分比切流量的金丝雀、多集群、多区域、飞书或钉钉审批。外部审批以后如果要加，未批准的指纹仍然不能进入 Argo CD 正在跟踪的生产分支。

## 8. 总结

这五件加固在现有「构建一次、同一枚指纹、Git 合并才发布」之上，补上仓库隔离、集群验签、自动发布检查、偏离通知和凭据轮换。生产仍然由 Argo CD 按 Git 同步，失败仍然按原回滚流程撤回。

建议的实施顺序：

1. 确认第 4.12.7 章七行证据都在。
2. 拆分 Harbor 项目，打通按指纹复制和在生产仓库签名。
3. Kyverno 先 `Audit`，一次真实发布无误报后改为 `Enforce`。
4. 加上 PostSync 检查，并演练一次失败后的撤回。
5. 打开 5 分钟偏离通知，在测试环境做一次注解试验。
6. 建立凭据台账，完成一次轮换演练。
