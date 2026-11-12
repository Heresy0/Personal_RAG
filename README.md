# Personal_RAG

个人知识库与可选 MCP 长期记忆。PostgreSQL + pgvector 保存元数据、历史版本、父子分块和向量；Markdown 保存原文，Codex 负责理解和回答。

## 在其他项目会话中选择插件

已提供本地桌面插件 **个人知识库 / Personal Memory**，支持查询、原样保存和总结后存入。总结内容不设固定模板，学习、工作、生活都使用同一入口。

先在PowerShell 7中初始化后端，再安装：

```powershell
.\scripts\setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.3.0
.\scripts\install-plugin.ps1
```

安装脚本会通过 `codex plugin marketplace add` 注册本仓库插件源，再安装 `personal-memory@personal-rag`。脚本优先查找PATH中的CLI，再查找Windows桌面端附带的CLI；其他位置可通过 `-CodexPath` 指定。也可先用 `-SkipRegistration` 配置本机路径，再从桌面插件目录添加本仓库插件源。

重启Codex或新开本地项目会话，在输入框 **＋号/插件选择器** 中搜索 **个人知识库**；也可使用插件/技能提及入口。客户端若尚未刷新目录，先到插件页检查 Personal RAG 来源下是否已安装。此插件通过个人/仓库插件源分发，未提交通用公共插件目录审核。

直接说：

- “查询我以前记录的相关内容。”
- “把这段内容原样存下来。”
- “总结刚才的讨论并存入知识库，不用固定模板。”

原样保存保留正文空白、换行和代码，标题/时间等作为独立元数据。总结由当前Codex完成，标记为summary；仅说“总结一下”时不会写入。保存成功才返回笔记ID，失败不会冒称成功。

普通插件连接初始off，最高读写，默认允许general、inbox、learning、work、life；没有管理工具。明确的查询或保存请求可临时开启所需模式，完成后恢复原模式，除非用户要求持续开启。插件选择本身不授权自动保存聊天。

本机路径配置位于 `%USERPROFILE%/.config/personal-rag/plugin.json`，只保存知识库目录和连接名称，不含密钥。插件即使安装到Codex缓存目录，也能找到自己的后端；不依赖当前开发项目路径。不需要在每个项目复制MCP配置。

限制到更少资料空间或只读时，可在首次安装指定：

```powershell
.\scripts\install-plugin.ps1 -Spaces general,inbox -ReadOnly
```

重复安装保留已有连接权限；可编辑 `config/connections/plugin-memory.toml` 调整本机允许空间，重启连接后生效。默认不包含project-*空间，需要时明确加入。此范围按连接控制，不自动猜测当前会话属于哪个项目；同一MCP进程共享模式。

插件入口在 `plugins/personal-memory`，目录清单在 `.agents/plugins/marketplace.json`。朋友可克隆仓库执行相同安装步骤；每个人使用自己的数据库、笔记和模型配置，不共享作者的个人知识库。

## Docker 安装（无需本机 Python）

准备 Docker Desktop、PowerShell 7 和 Codex。克隆或下载本仓库后，在项目根目录执行：

```powershell
.\scripts\setup-docker.ps1
```

脚本默认从 GitHub Container Registry 拉取 `ghcr.io/heresy0/personal_rag:0.3.0`，启动独立 PostgreSQL，初始化数据库并生成 Docker 版管理 MCP 配置。已有管理配置会先备份。然后在 Codex 添加 `knowledge_workspace` 项目并新开会话，无需自己构建镜像。

也可单独拉取：

```powershell
docker pull ghcr.io/heresy0/personal_rag:0.3.0
```

需要本地构建时使用 `.\scripts\setup-docker.ps1 -Build`。可在 `.env` 中设置 `PERSONAL_RAG_IMAGE` 指定其他镜像或固定digest。

容器保留 STDIO MCP：Codex 执行 `docker compose run --rm --no-deps -T mcp ...`；PostgreSQL 常驻，MCP 容器随连接启动，连接结束后删除。普通使用无需把 MCP 服务暴露到网络端口。

原文持久化在宿主机 `knowledge_workspace/vault`，数据库保存在原有命名卷。镜像构建只允许源码与依赖进入上下文，`.env`、个人资料和本机连接配置都在运行时从宿主机读取，不进入镜像。

给其他项目生成默认关闭的受限连接：

```powershell
.\scripts\connect-docker.ps1 -Name my-project
# 如需读写：加 -Write
```

把生成的 `connections/my-project.codex.toml` 合并到目标项目配置，并合并 `connections/AGENTS.example.md` 的规则。

如果收到已经构建的镜像文件，先导入再跳过构建：

```powershell
docker load -i personal-rag-0.1.0-linux-amd64.tar.gz
.\scripts\setup-docker.ps1 -SkipBuild -Image personal-rag:0.1.0
```

镜像文件仅包含应用，仍需本仓库的 Compose、配置模板和管理说明；PostgreSQL 镜像首次启动时单独拉取。当前导出验收平台为 Linux/amd64（Windows Docker Desktop 使用 Linux 容器）。公开镜像和版本见 [GitHub Packages](https://github.com/Heresy0/Personal_RAG/pkgs/container/personal_rag)。

macOS/Linux 可手动创建 `.env`（参考模板，填写随机数据库密码及一致的 DATABASE_URL）后运行：

```sh
mkdir -p knowledge_workspace/vault
# Linux 绑定目录需匹配宿主机 UID/GID；可在 .env 设置 PERSONAL_RAG_UID/GID。
docker compose -f compose.yaml -f compose.docker.yaml pull mcp
docker compose -f compose.yaml -f compose.docker.yaml up -d --wait postgres
docker compose -f compose.yaml -f compose.docker.yaml run --rm --no-deps -T mcp init
```

MCP 客户端的 command 为 `docker`，args 使用上述 Compose 文件的绝对路径及 `run --rm --no-deps -T mcp --connection /connections/manager.toml mcp`。macOS/ARM 未在本机验收。

更改 `.env` 的模型配置后重启 MCP 连接即可加载。已录入的笔记需要运行容器版 `sync` 补建向量。容器返回的原文路径为 `/data/vault/...`，宿主机对应 `knowledge_workspace/vault/...`；按 note_id 调用 read_note 获取全文。

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

本节是可选的手动 MCP 接入方式；使用前面的插件安装方式即可在＋号选择，无需逐项目配置。云端聊天不会自动获得本机服务。

## 模型

新安装默认 `PERSONAL_RAG_EMBEDDING_PROVIDER=disabled`，关键词检索仍可用。
`.env` 配置 `openai-compatible` 后启用向量；URL 是完整 embeddings 端点，如兼容接口的 `/v1/embeddings`。
配置维度须与模型输出、数据库一致；更换模型后运行 `sync` 重新生成向量。更改维度应新建数据库迁移。
rerank 使用完整 `/rerank` 接口地址，接受 `model/query/documents/top_n` 并返回 `results[index,relevance_score]`。
重排失败会明确标记 fallback；向量服务失败会报告错误，不默默伪装成语义搜索成功。

本次用户授权复用企业项目模型设置，已通过 `scripts/import_model_config.py` 只读导入必要的 embedding/rerank 项到本项目 `.env`。不配置主生成模型；记录理解、总结与问答由 Codex 完成。
`.env` 不进入版本控制。启用云模型会将对应片段发送给供应商，并产生其 API 费用。

## 数据与可靠性

0.3.0新增[写入审计与历史版本](docs/WRITE_AUDIT.md)：记录知识写入成功、失败、拒绝与前后版本；管理会话可查询，普通项目插件不暴露全库日志。已有部署请先备份，再运行 `scripts/setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.3.0` 完成数据库迁移。

- `notes`：稳定 ID、空间、日期、标签、来源、修订号与文件哈希。
- `note_versions`：记录写入/同步后的历史正文及元数据。
- `write_audit`：每次写入尝试与同事务提交的变更事件，保留结果、连接、操作ID和前后版本；归档与清理也保留历史。
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
