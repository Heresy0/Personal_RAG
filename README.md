# Personal_RAG

个人知识库与可选 MCP 长期记忆。PostgreSQL + pgvector 保存元数据、历史版本、父子分块和向量；Markdown 保存原文，Codex 负责理解和回答。

从 `D:/code/Enterprise_knowladge` 只读提取通用解析、保守清洗、中文分词，并改写 RRF 和父块组织逻辑。没有企业运行时依赖。来源清单见 [EXTRACTION.json](docs/EXTRACTION.json)。

## 首次启动（Windows / PowerShell 7）

```powershell
cd D:\code\Personal_RAG
.\scripts\setup.ps1
```

脚本创建本项目 `.venv` 和随机数据库密码，启动独立 `personal-rag` Compose 项目的 PostgreSQL（仅监听 `127.0.0.1:55432`）、独立数据卷，初始化表并生成管理项目的 MCP 配置。不会读取企业凭据或更改企业容器。

已有安装只需：

```powershell
docker compose up -d --wait postgres
.venv\Scripts\python.exe -m personal_rag.cli status
```

服务端使用本地 STDIO MCP，由 Codex 按需启动；无需单独运行 Web 服务器。PostgreSQL 需要保持运行。

## 专用知识库管理项目

在 Codex 的添加项目/打开文件夹入口选择 **`D:\code\Personal_RAG\knowledge_workspace`**。
该目录已有 `AGENTS.md`、使用说明和 `.codex/config.toml`，使用 manager 连接，默认读写、可访问全部资料空间。
配置须在可信项目中加载；已打开的会话请重启/新开会话，并确认出现 `personal_memory` 工具。

日常直接说：

- “记一下，今天学了 Python 装饰器，明天继续理解闭包。”
- “查找之前处理鉴权问题的记录。”
- “根据本周原始记录做学习和工作复盘。”

空间：`inbox`、`learning`、`work`、`life`、`general`、`project-项目名`。空间名称使用英文、数字、下划线和连字符。
人工编辑/附件导入请放 `knowledge_workspace/vault/<空间>/`，然后调用 `sync_notes`。
支持 MD、TXT、DOCX、文本 PDF。扫描 PDF 会明确报错，尚未接 OCR。Markdown 顶部的 HTML 注释包含稳定 ID，不要手动复制这个 ID 创建新笔记。

## 其他项目按需启用

生成一个默认只读、初始关闭的受限连接：

```powershell
.venv\Scripts\python.exe -m personal_rag.cli connect my-project
# 需要用户指令下写入时：
.venv\Scripts\python.exe -m personal_rag.cli connect another-project --write
```

生成两份文件：

- `config/connections/my-project.toml`：由服务读取的范围和权限上限，默认仅 `general`、`project-my-project`。
- `connections/my-project.codex.toml`：合并到目标项目 `.codex/config.toml` 的连接配置；不覆盖已有内容。

再将 `connections/AGENTS.example.md` 的规则合并到目标项目说明。生成操作只写 Personal_RAG，不自动修改其他项目。

新会话先 `memory_status`。说“本次开启长期记忆”后设 `read`；说“关闭长期记忆”后设 `off`。有写权限的连接才可设 `readwrite`。
**off** 阻止该连接后续读写；**read** 仅查询；**readwrite** 可在授权空间记录/追加。
读取连接根本不发布 capture/append 工具。管理员工具只在 manager 连接发布。

模式按每个 MCP 进程/连接隔离。客户端若共享同一个 MCP 进程，模式也会共享；这是进程模式，不能伪称绑定到某个未知聊天 ID。
如需从工具目录完全移除，把目标项目配置的 `enabled` 改成 `false` 后重启会话。
关闭不撤回已经进入聊天上下文的资料，也不取消已经开始的请求。

这是本地 MCP 集成，未安装为 Codex 插件市场包，未自动注册全局连接。云端聊天不会自动获得本机服务。

## 模型

新安装默认 `PERSONAL_RAG_EMBEDDING_PROVIDER=disabled`，关键词检索仍可用。
`.env` 配置 `openai-compatible` 后启用向量；URL 是完整 embeddings 端点，如兼容接口的 `/v1/embeddings`。
配置维度须与模型输出、数据库一致；更换模型后运行 `sync` 重新生成向量。更改维度应新建数据库迁移。
rerank 使用完整 `/rerank` 接口地址，接受 `model/query/documents/top_n` 并返回 `results[index,relevance_score]`。
重排失败会明确标记 fallback；向量服务失败会报告错误，不默默伪装成语义搜索成功。

本次用户授权复用企业项目模型设置，已通过 `scripts/import_model_config.py` 只读导入必要的 embedding/rerank 项到本项目 `.env`。不配置主生成模型；记录理解、总结与问答由 Codex 完成。
`.env` 不进入版本控制。启用云模型会将对应片段发送给供应商，并产生其 API 费用。

## 数据与可靠性

- `notes`：稳定 ID、空间、日期、标签、来源、修订号与文件哈希。
- `note_versions`：记录写入/同步后的历史正文及元数据。
- `chunks`：检索子块及 pgvector 向量；`parents`：按章节组织的原文父块。
- 来源类型 `original` / `summary`，AI 整理稿通过 `source_ids` 链接原始笔记。
- 关键词 BM25 仅在授权空间和日期范围内构建；向量查询同样先加范围条件；RRF 0.6/0.4 融合，可选重排，父块返回受12000字符预算限制。
- 初版向量用精确检索，无 HNSW。关键词候选上限5万块，超过时要求缩小范围，不静默截断全库。
- 追加使用 expected_revision 防止旧版本覆盖。capture 的 request_id 为 UUID，重试沿用以避免重复。
- 文件改变/缺失后，旧索引内容停止返回；需管理同步。保留头部 ID 的改名可保持身份，无头部文件只有内容未变且唯一匹配时才识别改名。
- `sync --prune` 清除缺失原件的活动索引；单文件失败会记录错误，该轮不执行 prune。
- archive 移入 `.trash`，检索移除；恢复可将原文件移回原空间并 sync。
- Markdown 文件系统与 PostgreSQL 不是一个跨系统事务。普通失败有补偿；断电或提交结果未知时保留文件，使用 sync 对账恢复，不能宣称跨系统原子提交。
- scope 是服务端工具访问约束，不是同一操作系统用户之间的安全沙箱。本机用户有权限改连接配置或直接访问数据库时，可以改变范围。不要把 manager 配置分发给普通项目。

## 命令行与检查

```powershell
.venv\Scripts\python.exe -m personal_rag.cli capture --title "学习记录" --body "今天学习闭包" --space learning
.venv\Scripts\python.exe -m personal_rag.cli search "闭包"
.venv\Scripts\python.exe -m personal_rag.cli sync --prune
.venv\Scripts\python.exe scripts/check.py
```

`check.py` 创建并清理独立 `personal_rag_test_*` 数据库，验证真实 PostgreSQL/pgvector 和 MCP STDIO。测试用确定性向量，不计真实语义准确率。
`scripts/live_smoke.py` 是显式付费真实模型小样本验收（2批 embedding、1次 rerank），不会在普通测试中启动，数据位于临时测试库并在结束后清理。

## 备份

同时备份 `.env`、vault 原文/附件和 PostgreSQL。示例在本项目容器内生成导出，再复制到本项目 output：

```powershell
docker compose exec -T postgres pg_dump -U personal_rag -d personal_rag -Fc -f /tmp/personal-rag.dump
docker compose cp postgres:/tmp/personal-rag.dump ./output/personal-rag.dump
```

保留独立备份副本；同步软件不代替历史备份。恢复先使用新数据库验证，避免覆盖现有资料。

官方接入依据：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp)、[项目说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[pgvector](https://github.com/pgvector/pgvector)。
