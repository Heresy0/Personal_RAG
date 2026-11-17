# Personal_RAG

个人知识库与可选 MCP 长期记忆。PostgreSQL + pgvector 保存元数据、历史版本、父子分块和向量；Markdown 保存原文，Codex 负责理解和回答。

当前后端版本 **0.5.0**、插件版本 **0.3.2**：插件新增本机 MCP 桥接层，让工具加载独立于 Docker 启停，后端断开后按请求重建连接，不自动重放写入。保留[QQ与163新邮件增量收集](docs/MAIL_COLLECTOR.md)、[原图与识别文字关联](docs/IMAGE_NOTES.md)、读写空间权限及审计；不自动OCR。后端镜像与插件包独立升级。

## 套件组成与选择

本仓库统一提供知识库、Codex 插件、邮件收集及可选的微信会话绑定适配器。使用者克隆仓库并拉取 Docker 镜像，无需安装包；每人独立配置和保存自己的资料。

| 组件 | 运行方式 | 是否必需 |
| --- | --- | --- |
| PostgreSQL + pgvector、知识库 MCP | Docker Compose，后端镜像 `0.5.0` | 必需 |
| 个人知识库插件 `0.3.2` | 安装到自己的 Codex，其他项目按需选择 | 推荐 |
| 知识库管理项目 | 在 Codex 打开 `knowledge_workspace` | 推荐 |
| QQ / 163 增量邮件采集 | 可选 Compose 服务，见[邮件说明](docs/MAIL_COLLECTOR.md) | 可选 |
| OpenClaw → Codex → 知识库 | Windows 配置脚本、扫码登录、独立启停，见[微信接入说明](docs/OPENCLAW.md) | 可选 |

建议先完成下面的 Docker 与插件安装，确认查询和保存正常，再启用邮件或微信。组件关系、资料流向和备份边界见[架构说明](docs/ARCHITECTURE.md)。本次新增微信适配器和文档不改变后端镜像；OpenClaw 不包含在知识库 Docker 镜像中。

微信接入：先运行 `scripts/setup-openclaw.ps1` 生成本机配置，填写模型及可选 Codex 路径，再次运行完成安装；之后执行 `scripts/openclaw.ps1 login` 扫码、`scripts/openclaw.ps1 start` 启动。另有 `status` 与 `stop`。需要 Node.js 24+、Python 3.12+ 和已登录的 Codex；默认使用独立的 `output/openclaw` 与端口 `19890`，已有手工实验环境保持原样。完整步骤及验收边界见[微信接入说明](docs/OPENCLAW.md)。

手机与电脑共用原聊天可选[桌面会话投递模式](integrations/openclaw-desktop/README.md)，配置 `mode=desktop`、原会话 ID 和工作目录。提供本机持久队列、去重、执行结果匹配与回传恢复，并支持登录 Windows 后自动启动；不保证关机期间尚未收到的消息。桌面模式继承原会话权限，不等同于独立 MCP 普通连接的权限隔离。

## 在其他项目会话中选择插件

已提供本地桌面插件 **个人知识库 / Personal Memory**，支持查询、原样保存和总结后存入。总结内容不设固定模板，学习、工作、生活都使用同一入口。

准备 Docker Desktop（Linux容器）、PowerShell 7 和 Codex。Docker Desktop保持运行。首次安装在PowerShell 7中执行：

```powershell
git clone https://github.com/Heresy0/Personal_RAG.git
cd Personal_RAG
.\scripts\setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.5.0
.\scripts\install-plugin.ps1
```

安装脚本会通过 `codex plugin marketplace add` 注册本仓库插件源，再安装 `personal-memory@personal-rag`。脚本优先查找PATH中的CLI，再查找Windows桌面端附带的CLI；其他位置可通过 `-CodexPath` 指定。也可先用 `-SkipRegistration` 配置本机路径，再从桌面插件目录添加本仓库插件源。

重启Codex或新开本地项目会话，在输入框 **＋号/插件选择器** 中搜索 **个人知识库**；也可使用插件/技能提及入口。客户端若尚未刷新目录，先到插件页检查 Personal RAG 来源下是否已安装。此插件通过个人/仓库插件源分发，未提交通用公共插件目录审核。

直接说：

- “查询我以前记录的相关内容。”
- “把这段内容原样存下来。”
- “总结刚才的讨论并存入知识库，不用固定模板。”
- “把这张原图和核对后的识别文字一起存入知识库。”
- “查询这段识别文字，并展示对应原图。”

原样保存保留正文空白、换行和代码，标题/时间等作为独立元数据。总结由当前Codex完成，标记为summary；仅说“总结一下”时不会写入。保存成功才返回笔记ID，失败不会冒称成功。

普通插件连接初始off，最高读写，默认可读写全部空间（read_spaces/write_spaces均为["*"]）；没有管理工具。明确的查询或保存请求可临时开启所需模式，完成后恢复原模式，除非用户要求持续开启。插件选择本身不授权自动保存聊天。

### Docker 启停与旧会话连接恢复

0.3.2 在本机 PowerShell 中维护 MCP 连接和固定工具目录，首次握手不等待 Docker；只有实际调用工具时才启动隔离的 Docker MCP 后端。Docker 未运行时，工具返回明确的后端不可用错误，工具目录仍保留。Docker 恢复后，再次调用 `memory_status` 会按需重建后端，无需反复关闭、开启插件。不自动启动共享 Docker Desktop 或企业项目容器；知识库数据库仍须运行。

后端重建后以连接配置的 `initial_mode` 为准，默认恢复 `off`，需要按查询或保存意图重新开启。执行中断的写入不会自动重发，也不承诺未收到响应等于没有写入：`capture_note` 重试沿用同一个 `request_id` 和全部参数，追加操作先读取版本核对。不会因自动恢复而放开管理权限或扩大空间范围。

升级：拉取仓库后执行 `codex plugin add personal-memory@personal-rag --json`。从 0.3.1 升级时，已经持有旧进程的会话可能需要一次连接刷新或重启客户端以采用新桥接层；升级后 Docker 启停不再要求切换插件。若客户端本身没有加载新版本、用户禁用插件、配置文件缺失或权限配置变化，则仍需要处理对应配置，不能由后端恢复替代。

排查日志在 `logs/plugin/bridge-*.jsonl`，仅记录启动、连接代次及错误类别，不保存正文、工具参数、返回内容、凭据或后端 stderr。普通知识写入审计仍由原后端记录。本机桥接层只提供普通读写工具；管理项目的直接 MCP 连接不受此改动影响。

Windows 上，MCP 宿主可能只传入最小环境，缺少 `ProgramData` / `ProgramFiles` 会使 Docker 无法发现 Compose，即使引擎已运行也可能报 `unknown flag: --project-directory` 并导致初始化连接关闭。桥接层使用 Windows 标准目录 API 为后端子进程补齐这些路径，不修改系统环境、用户配置或 Docker 引擎。

### 图片记录：AI识别、人工核对、关联保存

个人日常使用采用以下流程，暂不在项目内部增加OCR模型或后台自动识别服务。将图片放进vault不会自动提取文字，扫描版PDF也不会自动OCR。

1. **AI识别**：在支持图片输入的Codex/ChatGPT会话中上传图片，让AI提取文字或理解内容；模糊、缺失及不确定的内容要明确标注，不凭上下文补成确定事实。
2. **人工核对**：先展示识别稿，由你核对金额、日期、编号、单位等细节，并提供修正或确认。没有核对确认时先不入库；如果你已经提供核对后的最终稿并明确要求保存，可直接进入下一步。
3. **关联保存**：确认后明确要求把原图和最终文字一起保存。助手先确认原始文件在连接电脑上实际可访问，再保留原始字节并用capture_note的image_paths关联保存，识别稿标记summary。保存的是AI识别后经你核对的文字，不冒称后台OCR或绝对准确的原文。
4. **查询回看**：以后按文字检索，使用结果中的images调用read_note_image查看对应原图，必要时回看并修正文字。只有保存成功且能读取关联原图，才确认图文均已保存。

可以分两次说：

> 识别这张图片中的文字，不确定处标注出来，先让我核对，暂不保存。

> 我已核对，金额改为128元，其他内容正确。把修正后的文字和这张原图一起保存到life。

以后再说：“查找这张图片里的消费记录，并展示对应原图。”以上仅为用语示例，不强制固定记录模板。

无法取得原文件时，助手应明确说明；不能用缩略图、重新编码图片代替原图，也不能只保存文字就宣称图文均已入库。手机远程会话的附件是否传到电脑仍需实测。格式、大小与备份说明见[原图保存说明](docs/IMAGE_NOTES.md)。

本机路径配置位于 `%USERPROFILE%/.config/personal-rag/plugin.json`，只保存知识库目录和连接名称，不含密钥。插件即使安装到Codex缓存目录，也能找到自己的后端；不依赖当前开发项目路径。不需要在每个项目复制MCP配置。

限制到更少资料空间或只读时，可在首次安装指定：

```powershell
.\scripts\install-plugin.ps1 -Spaces general,inbox -ReadOnly
```

重复安装保留已有连接权限；可编辑 `config/connections/plugin-memory.toml` 调整本机允许空间，重启连接后生效。新安装默认自动包含project-*等未来空间；旧配置仍沿用原范围。此范围按连接控制，不自动猜测当前会话属于哪个项目；同一MCP进程共享模式。

也可以分别设置，例如首次安装时使用 `install-plugin.ps1 -ReadSpaces learning -WriteSpaces inbox`。未指定空间的查询覆盖所有可读空间；每次保存到一个可写空间。`space`负责访问范围，标签用于细分主题和项目。完整规则见[读写空间权限](docs/SPACE_PERMISSIONS.md)。

插件入口在 `plugins/personal-memory`，目录清单在 `.agents/plugins/marketplace.json`。朋友可克隆仓库执行相同安装步骤；每个人使用自己的数据库、笔记和模型配置，不共享作者的个人知识库。

## 已有安装升级

先备份PostgreSQL、vault、`.env`、本机连接配置及应急日志，再在已有仓库目录执行：

```powershell
git pull
.\scripts\setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.5.0
```

必须显式指定镜像版本：本机`.env`可能固定了旧的`PERSONAL_RAG_IMAGE`，仅执行git pull不会替换镜像或更新已运行的MCP进程。setup会拉取镜像、执行幂等数据库初始化并更新本机镜像设置，不删除已有数据。

已有连接范围会保留。若要从旧的有限空间切换到普通插件全库读写，升级后将本机`config/connections/plugin-memory.toml`设置为：

```toml
name = "plugin-memory"
read_spaces = ["*"]
write_spaces = ["*"]
maximum_mode = "readwrite"
initial_mode = "off"
admin = false
```

此配置允许所有使用该连接的项目访问全部现有和未来空间，不授予管理工具。需要限制访问时保留有限列表；旧`spaces`配置仍兼容，不会因升级自动扩大。

升级后须重新启动MCP连接。新开会话不保证刷新，客户端可能复用旧进程；若仍返回旧状态，可等其他工作结束后完全退出并重开Codex。让助手调用`memory_status`核对`read_spaces`、`write_spaces`、`admin`；不要仅凭＋号中能选到插件就认为运行的是新版。

## Docker 安装（无需本机 Python）

准备 Docker Desktop、PowerShell 7 和 Codex。克隆或下载本仓库后，在项目根目录执行：

```powershell
.\scripts\setup-docker.ps1
```

脚本默认从 GitHub Container Registry 拉取 `ghcr.io/heresy0/personal_rag:0.5.0`，启动独立 PostgreSQL，初始化数据库并生成 Docker 版管理 MCP 配置。已有管理配置会先备份。然后在 Codex 添加 `knowledge_workspace` 项目并新开会话，无需自己构建镜像。

## 可选：QQ与163新邮件收集

更新后运行 `.\scripts\setup-mail.ps1`，在本机`config/mail.toml`填写邮箱地址并启用，在.env填写对应客户端授权码。默认不连接邮箱、不启动收集；不要把授权码发到聊天或提交Git。

首次成功运行mail-poll仅记录各账号的INBOX游标，**不导入已有邮件正文**。之后只增量读取新邮件，使用EXAMINE及BODY.PEEK，不改变已读状态；重启保留游标，失败单独重试。原始邮件和附件归档到vault隐藏目录，正文笔记进入inbox；附件正文不自动解析、图片不自动OCR。

收信通过可选的compose.mail.yaml服务常驻，不需要公网域名、不提供SMTP发送，不改变现有MCP插件。具体配置、首次基线、测试新邮件、启动与排错步骤见[邮件收集说明](docs/MAIL_COLLECTOR.md)。

## Docker运行方式

也可单独拉取：

```powershell
docker pull ghcr.io/heresy0/personal_rag:0.5.0
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
mkdir -p knowledge_workspace/vault logs
# Linux 绑定目录需匹配宿主机 UID/GID；可在 .env 设置 PERSONAL_RAG_UID/GID。
docker compose -f compose.yaml -f compose.docker.yaml pull mcp
docker compose -f compose.yaml -f compose.docker.yaml up -d --wait postgres
docker compose -f compose.yaml -f compose.docker.yaml run --rm --no-deps -T mcp init
```

MCP 客户端的 command 为 `docker`，args 使用上述 Compose 文件的绝对路径及 `run --rm --no-deps -T mcp --connection /connections/manager.toml mcp`。macOS/ARM 未在本机验收。

更改 `.env` 的模型配置后重启 MCP 连接即可加载。已录入的笔记需要运行容器版 `sync` 补建向量。容器返回的原文路径为 `/data/vault/...`，宿主机对应 `knowledge_workspace/vault/...`；按 note_id 调用 read_note 获取全文。

从 `D:/code/Enterprise_knowladge` 只读提取通用解析、保守清洗、中文分词，并改写 RRF 和父块组织逻辑。没有企业运行时依赖。来源清单见 [EXTRACTION.json](docs/EXTRACTION.json)。

## 可选：原生 Python 安装（Windows / PowerShell 7）

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
该目录提供 `AGENTS.md` 和使用说明，安装脚本生成 `.codex/config.toml`，使用 manager 连接，默认读写、可访问全部资料空间。
配置须在可信项目中加载；已打开的会话请重启/新开会话，并确认出现 `personal_memory` 工具。

日常直接说：

- “记一下，今天学了 Python 装饰器，明天继续理解闭包。”
- “查找之前处理鉴权问题的记录。”
- “根据本周原始记录做学习和工作复盘。”

空间：`inbox`、`learning`、`work`、`life`、`general`、`project-项目名`。空间名称使用英文、数字、下划线和连字符。
人工编辑/附件导入请放 `knowledge_workspace/vault/<空间>/`，然后调用 `sync_notes`。
支持 MD、TXT、DOCX、文本 PDF。扫描 PDF 会明确报错，尚未接 OCR。Markdown 顶部的 HTML 注释包含稳定 ID，不要手动复制这个 ID 创建新笔记。

图片附件支持PNG、JPEG、WebP，最多5张、每张10MiB。由当前Codex识图并核对文字，再将实际可访问的原图暂存到目标空间的.incoming，调用capture_note的image_paths关联保存。检索结果包含images，read_note_image返回经哈希验证的原图。手机端原文件能否传到电脑需实际确认，详见[原图保存说明](docs/IMAGE_NOTES.md)。

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

0.4.1将同步嵌入请求拆成每批最多10段，适配text-embedding-v4的[批量上限](https://help.aliyun.com/en/model-studio/embedding-interfaces-compatible-with-openai)。大于10个分块的资料会分多次请求，不需要手动拆成多篇笔记。模型返回非成功状态时，MCP会提供HTTP状态码和本批数量，不暴露供应商响应正文或密钥。HTTP 400也可能来自其他输入或配置问题，不能仅凭状态码断定原因。

本次用户授权复用企业项目模型设置，已通过 `scripts/import_model_config.py` 只读导入必要的 embedding/rerank 项到本项目 `.env`。不配置主生成模型；记录理解、总结与问答由 Codex 完成。
`.env` 不进入版本控制。启用云模型会将对应片段发送给供应商，并产生其 API 费用。

## 常见问题

- **管理会话能查到，普通插件查不到**：先看连接的`read_spaces`，以及记录所属空间；旧连接可能保留有限范围。查询无结果不等于原文不存在。
- **升级后仍显示旧的五个空间**：运行中的MCP进程未刷新。先核对`memory_status`，待方便时重启Codex；不要反复修改数据库或重复保存。
- **提示索引片段为0**：该数字是本次查询的授权空间和日期范围内的候选数，不一定是全库总数。请核对连接权限、日期和资料是否同步。
- **保存返回模型HTTP错误**：先在管理项目查看写入审计，核对是否已提交。旧版长笔记可能触发嵌入批量限制，请升级0.4.1并重新加载连接。capture重试沿用同一个request_id和相同内容；若是committed_error或started/unknown，先对照变更事件和原件，避免重复记录。
- **想核查修改历史**：在管理项目请求“查看最近写入审计”或“读取这条笔记第N版”。普通插件没有全库审计、历史版本、同步及归档工具，详见[审计说明](docs/WRITE_AUDIT.md)。

## 数据与可靠性

0.4.0支持[读写空间权限分离](docs/SPACE_PERMISSIONS.md)：普通插件新安装默认全空间读写，保持admin=false；旧spaces配置继续生效，不自动扩大已有权限。

0.3.0新增[写入审计与历史版本](docs/WRITE_AUDIT.md)：记录知识写入成功、失败、拒绝与前后版本；管理会话可查询，普通项目插件不暴露全库日志。已有部署请先备份，再运行 `scripts/setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.5.0` 完成数据库迁移。

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

同时备份 `.env`、本机连接配置、vault原文/附件、PostgreSQL和应急日志（Docker为`logs/`，原生默认`knowledge_workspace/logs/`）。数据库导出包含审计和历史版本，但不包含原文附件和应急文件。示例在本项目容器内生成导出，再复制到本项目output（先确保该目录存在）：

```powershell
New-Item -ItemType Directory -Force output | Out-Null
docker compose exec -T postgres pg_dump -U personal_rag -d personal_rag -Fc -f /tmp/personal-rag.dump
docker compose cp postgres:/tmp/personal-rag.dump ./output/personal-rag.dump
```

保留独立备份副本；同步软件不代替历史备份。恢复先使用新数据库验证，避免覆盖现有资料。

官方接入依据：[Codex MCP](https://learn.chatgpt.com/docs/extend/mcp)、[项目说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[pgvector](https://github.com/pgvector/pgvector)。
