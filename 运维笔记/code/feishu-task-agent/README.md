# feishu-task-agent

飞书消息驱动的多 Agent 服务：`feishu-task-agent start` 一条命令启动，
基于 lark-oapi 官方 SDK 的 **WebSocket 长连接**接收消息，无需公网域名/内网穿透。

## 工作原理

```
飞书用户 --@机器人--> 飞书云端 --(长连接)--> 本服务 --前缀路由--> agents/* --回复--> 飞书
```

- 单聊直接发消息、群聊 @机器人，都会触发 `im.message.receive_v1` 事件。
- 消息按 `/前缀` 路由到对应 agent：`/echo xxx`→ echo，`/task xxx`→ task。
- **不带前缀的消息默认走 task agent**；无法识别的 `/前缀` 回帮助列表（`/help`）。
- 加新 agent：在 `agent/agents/` 新建文件，继承 `Agent` 并 `register(XxxAgent())` 即可。

## 飞书开放平台配置清单（首次使用前）

在 <https://open.feishu.cn/app> 找到 lark-cli 使用的那个自建应用（复用其凭证）：

1. **应用能力**：添加「机器人」。
2. **事件订阅**：订阅方式选「使用长连接接收事件」，添加事件 `im.message.receive_v1`（接收消息）。
3. **权限**（权限管理 → 开通后需发布新版本生效）：
   - `im:message` 相关（接收/读取消息）
   - `im:message:send_as_bot`（以应用身份发消息，回复用）
   - 任务相关：搜索 `task`，勾选任务读写权限（`/task` 命令创建待办用）
4. 发布后版本生效，机器人即可在单聊/群聊中使用。

## 凭证来源（按优先级）

1. 环境变量 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`
2. 复用 `lark-cli` 的配置（`~/.lark-cli/config.json` 中的 appId；
   appSecret 自动从 lark-cli 的 Keychain 加密存储中解密——首次运行若弹出
   钥匙串授权窗口，点「始终允许」即可）

自检：`feishu-task-agent doctor`（验证凭证 + 获取 tenant_access_token）。

## 安装与启动

```bash
pipx install -e <本仓库路径>     # 安装到全局
feishu-task-agent doctor        # 检查凭证与连通性
feishu-task-agent agents        # 列出已注册 agent
feishu-task-agent start         # 启动服务（前台运行，Ctrl+C 停止）
```

## 常驻运行（可选）

长连接进程退出即离线。需要常驻可写到 launchd（示例 plist 略）：把
`feishu-task-agent start` 注册为 LaunchAgent，标准输出/错误重定向到日志文件即可。

## 内置 agent

| 前缀 | 说明 |
|---|---|
| `/echo <文本>` | 原样回显（连通性测试用） |
| `/task <事项>` | 通过 tenant token 调 `/open-apis/task/v2/tasks` 创建飞书任务 |
| `/help` | 列出所有可用 agent |
