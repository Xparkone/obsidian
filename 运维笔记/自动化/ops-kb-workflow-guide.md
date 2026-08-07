# 运维个人知识库助手（Dify 工作流）使用说明

## 1. 文档概述

- **解决什么问题**：把原「问题分类 + 知识库 + 聊天机器人」模板，改成面向运维 / 计算机的个人知识库问答。
- **适合谁**：已有本地 Markdown 笔记（如 `~/Documents/gpt/gpt/`），并使用 **Dify** 高级聊天工作流的人。
- **读完能做什么**：导入工作流、绑定知识库与模型、按分类提问，并把经验整理成可入库笔记。

**平台结论**：原文件与优化版均为 **Dify**（`kind: app` + `mode: advanced-chat`），不是 n8n / Coze / 飞书。

## 2. 前置条件

- 可访问的 Dify 实例（云版或自建）【需要确认：版本建议 ≥ 原导出兼容的 0.7.x 工作流格式】
- 已配置可用的 LLM（原工作流使用 `openai_api_compatible` + `deepseek-v4-pro`）【需要确认：模型名以你实例为准】
- 本地知识文档目录（可选但推荐）：`/Users/lijiaxuan/Documents/gpt/gpt/`

## 3. 核心概念

| 概念 | 说明 |
|------|------|
| 问题分类 | Dify Question Classifier 按运维主题分流 |
| 知识检索 | Knowledge Retrieval 节点检索你上传到 Dify 的知识库 |
| 运维核心库 | Linux / 网络 / UFW / 排障 / Ansible 等 |
| 平台工程库 | GitLab / Docker / K8s / Helm / Istio / 数据库等 |
| 知识沉淀 | 不写盘，只生成 Markdown，由你粘贴到本地目录 |

工作流文件位置：

- 主副本：`/Users/lijiaxuan/Documents/gpt/gpt/workflows/ops-personal-kb-chatbot.yml`
- 导入便捷副本：`/Users/lijiaxuan/Downloads/chrome/ops-personal-kb-chatbot.yml`
- 同目录旁：`/Users/lijiaxuan/Downloads/chrome/workflows/ops-personal-kb-chatbot.yml`
- 原文件（未改）：`/Users/lijiaxuan/Downloads/chrome/问题分类 + 知识库 + 聊天机器人.yml`

## 4. 实现步骤

### 4.1 导入工作流

1. 打开 Dify → **工作室** → **导入 DSL**（或「从 DSL 创建」）。
2. 选择 `ops-personal-kb-chatbot.yml`。
3. 若提示缺少插件 `langgenius/openai_api_compatible`，按提示安装，或把各节点模型改成你已有的 Provider。

**预期结果**：出现应用「运维个人知识库助手」，画布含：开始 → 运维主题分类 → 两条知识检索 → 三个 LLM → 三个回复。

### 4.2 创建并上传知识库【需要确认】

优化版 **故意清空了** `dataset_ids`（原文件里的 ID 属于他人/旧实例，导入后无效）。请新建知识库并绑定：

**建议拆成两个库（也可先合成一个，两个检索节点都绑同一个）：**

| 知识库建议名 | 建议上传的本地文档 |
|--------------|-------------------|
| 运维核心 | `docs/automation/*.md`、`docs/network-security/*.md` |
| 平台工程 | `docs/cicd/*.md`、`docs/cloud-native/*.md`、`docs/databases/*.md` |

操作：

1. Dify → **知识库** → 创建 → 上传上述 `.md`（可按目录分批）。
2. 分段建议：按标题/Markdown 标题切分；TopK 已设为 6，分数阈值约 0.3（可按召回效果调）。
3. 回到工作流：
   - 节点 **知识检索·运维核心** → 选择「运维核心」库
   - 节点 **知识检索·平台工程** → 选择「平台工程」库（或同一库）

**预期结果**：检索节点不再报空知识库；试问「UFW 放行 SSH」能命中 `ufw-usage-guide.md` 相关片段。

### 4.3 配置模型与 API【需要确认】

检查以下节点的模型是否可用（名称以你实例为准）：

- 运维主题分类
- LLM·运维核心
- LLM·平台工程
- LLM·知识入库整理

若不用 DeepSeek：统一改成你的 Provider / 模型即可。  
**不要**把 API Key 写进 YAML 或本说明；在 Dify「模型供应商」里配置。

### 4.4 发布与试用

1. 保存 → 发布。
2. 试用问题示例：
   - `UFW 怎么只允许指定 IP 访问 SSH？`
   - `tcpdump 如何按主机过滤 HTTP？`
   - `把上面答案整理成可入库笔记`

## 5. 分类体系与节点逻辑

```
开始
  └─ 运维主题分类
        ├─ Linux / 网络 / 防火墙 / 排障 / Ansible / 其它
        │     → 知识检索·运维核心 → LLM·运维核心 → 回复
        ├─ 容器·K8s / CI·CD·GitLab / 数据库
        │     → 知识检索·平台工程 → LLM·平台工程 → 回复
        └─ 知识沉淀·笔记整理
              → LLM·知识入库整理 → 回复（Markdown，需手动落盘）
```

提示词要点：先结论 → 可执行命令 → **标注知识库来源**；未命中则标 `【通用知识·未命中知识库】`。

## 6. 与本地 `gpt` 文档如何配合

1. **权威语料仍在本地**：`/Users/lijiaxuan/Documents/gpt/gpt/*.md`（及 `examples/`）。
2. **Dify 知识库是检索副本**：文档更新后需在 Dify 中重新上传/同步该文件。
3. **入库路径**：聊天里说「整理成笔记」→ 复制输出 → 存到例如 `~/Documents/gpt/gpt/<主题>-notes.md` → 再同步进 Dify。
4. 工作流 **不能直接写本地磁盘**（Dify 云端无权限）；自动落盘需另做同步脚本或自建 Agent【需要确认是否要做】。

## 7. 常见问题与排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| 导入失败 / 缺插件 | 无 `openai_api_compatible` | 安装插件或改模型 Provider |
| 检索无结果 | 未绑定知识库或未上传文档 | 给两个检索节点选 dataset |
| 答非所问 | 分段/阈值不当 | 调 TopK、阈值；检查文档是否上传 |
| 分类总进「其它」 | 问题表述过短 | 补关键词；或调分类 instructions |
| 回答过短 | 旧模板 max_tokens=512 | 新版已改为 2048，确认未改回 |

## 8. 注意事项与最佳实践

- 原 YAML **请保留**，便于对比回滚。
- 原文件中的知识库 ID、若环境里还有其它密钥/Webhook，**不要**提交到公开仓库。
- 生产排障回答务必二次核验命令与环境（发行版、权限、是否生产）。
- 若只想维护一个知识库：两个检索节点都绑同一库即可，分类仍有助于走不同提示词。

## 9. 总结与下一步

已交付可导入的运维向 Dify 工作流与本说明。建议你接下来：

1. 导入 DSL 并绑定模型  
2. 上传 `gpt/` 下文档到知识库并挂到两个检索节点  
3. 用 UFW / tcpdump / Ansible / GitLab 各测一问，按召回效果微调阈值  

若需要「聊天后自动写入飞书文档 / 本地仓库」的自动化，可另开需求（当前工作流仅生成 Markdown 文本）。
