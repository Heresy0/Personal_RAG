# 读写空间权限0.4.0验收 · 2026-11-12

- 完整回归59项通过：保留既有审计/检索/原样保存测试，增加旧配置回退、新字段优先、空范围、错误配置、读写独立限制、只写回执不泄露正文、通配空间、管理权限独立以及安装脚本测试。
- `personal-rag:permissions-test`通过14项Docker/MCP检查；实际已安装的0.2.0插件缓存启动该后端，通过13项检查，包含未来空间写入、跨空间搜索、read_spaces/write_spaces状态与管理工具不暴露。插件缓存与后端版本独立，启动脚本不变。
- 所有验收使用临时数据库和资料目录，外部模型调用0；企业源码5个提取文件及38个容器基线只读核对一致。
- 新安装普通插件默认read_spaces/write_spaces均为["*"]，admin=false，初始off；已有连接不自动扩大权限。旧spaces同时回退到读写两侧，新字段可分别覆盖，显式[]禁止该侧访问。详见[读写空间权限](SPACE_PERMISSIONS.md)。
- 本机升级前数据库、原文、.env与连接配置已备份至Git忽略目录`output/pre-permissions-upgrade-20261112-202355/`。
- [GHCR发布43217944381](https://github.com/Heresy0/Personal_RAG/actions/runs/43217944381)成功，公开镜像`ghcr.io/heresy0/personal_rag:0.4.0`提交为`7fbfdae`，摘要`sha256:05a60c3fef879b4d28f86daf6b66983528e5854aa12a7097067d8ad066d95802`。匿名拉取验证通过，公开镜像再次通过13项隔离插件验收。
- 本机已拉取并初始化0.4.0，notes/parents/chunks及原件指纹保持一致；本机plugin-memory配置已按用户授权改为两个["*"]、admin=false、initial_mode=off。实际缓存插件对本机后端的工具发现和权限状态验证通过；退出旧连接后重新加载生效。

# 写入审计0.3.0验收 · 2026-11-12

- `scripts/check.py`：50项通过。覆盖成功/失败/拒绝、原样正文与完整元数据版本、幂等重试、并发冲突、事务回滚、同步部分失败、归档/清理、直接SQL变更、旧库迁移与重复初始化、已提交但响应失败、数据库/应急目录不可用，以及管理MCP查询和权限。
- `scripts/check_docker.py`：最终源码镜像 `personal-rag:audit-test` 的14项真实Docker/STDIO检查通过，新增审计查询、历史版本读取、失败写入记录。
- `scripts/check_plugin.py`：从本机已安装的0.2.0插件缓存启动，11项通过。插件与后端版本独立，启动脚本不变，原样保存、自由总结和查询继续可用。
- 全部使用独立临时数据库及资料目录，外部模型调用0；完整版本在PostgreSQL，应急目录有独立宿主机挂载并被Git忽略。发布前检查65个可发布文件，未包含本机环境密钥或用户资料。
- 企业项目只读核验：5个提取源文件哈希及38个基线容器一致；其他新增容器仅观察，不操作。
- 旧库升级须先备份，再执行setup-docker指定0.3.0镜像，脚本运行init迁移；不追溯伪造升级前审计。详见[写入审计](WRITE_AUDIT.md)。GHCR由v0.3.0标签触发官方发布工作流。
- [GHCR发布43202424223](https://github.com/Heresy0/Personal_RAG/actions/runs/43202424223)成功，镜像 `ghcr.io/heresy0/personal_rag:0.3.0`，提交 `08d9a95`，摘要 `sha256:84a0374344696dbaf08d3d3a0819818570b440162bc5b2d15b04f35b08fc7488`；匿名拉取权限已验证，实际发布镜像再次通过14项Docker/MCP验收。
- 本机升级前已备份至忽略目录 `output/pre-audit-upgrade-20261112-184043/`；setup拉取0.3.0并迁移成功。升级前后notes/parents/chunks及原件指纹一致，审计触发器与当前版本基线完整。已有MCP进程需退出后新开会话加载新版。

# 首版验收 · 2026-11-12

已在 D:/code/Personal_RAG 完成独立部署，未在 Codex 侧自动创建新聊天或变更其他项目配置。

## 本机状态

- 独立容器 `personal-rag-postgres-1`，PostgreSQL + pgvector，端口 `127.0.0.1:55432`。
- 独立数据库 `personal_rag`，已初始化 notes、note_versions、parents、chunks。
- 管理工作区 `knowledge_workspace`，已有说明与项目级 MCP 配置。
- 外部连接生成器已准备，外部连接初始 off，服务端限制允许空间和最高读写权限。
- 用户授权后，只读复制企业项目的 embedding/rerank 必需配置到本项目 .env；未配置主生成模型。

## 验证结果

`scripts/check.py`：33项通过，包含：

- Markdown结构、中文分词、RRF、路径边界、权限上限和工具暴露。
- 真实 PostgreSQL/pgvector 入库与检索，版本历史、幂等写入、旧版本冲突。
- 手动编辑、稳定ID改名、无ID文件唯一内容匹配改名、删除与回收。
- embedding 模型标识变化后的重建，模型故障和索引失败保留旧记录。
- 空间隔离与时间线分页。
- 真实 MCP STDIO 握手、关闭/只读切换、禁止提权，以及管理连接记录、读取、追加、检索和归档。

测试使用独立 personal_rag_test_* 数据库与临时资料目录，结束后清理，确定性测试向量不代表真实语义准确率。

`scripts/live_smoke.py`：真实模型小样本验收通过。

- embedding：`text-embedding-v4`，1024维；2批请求（记录、查询）。
- rerank：`qwen3-rerank`；1次请求，返回 success。
- pgvector 实际写入、检索命中、原文读取均通过。
- 生成主模型调用0。费用未知，以服务商实际账单为准。
- 合成记录仅在独立临时数据库，已清理；未将示例冒充个人经历。

`scripts/verify_isolation.py`：5份提取源码与来源指纹一致，原38个运行中容器的ID和镜像保持一致，新增仅本项目 PostgreSQL 容器。该核验不声称检查企业每个文件或数据库行。

`pip check` 通过，已输出 requirements.lock.txt。原始测试报告与只读基线在被忽略的 output/。

## 使用前最后一步

在 Codex 中添加 `D:/code/Personal_RAG/knowledge_workspace` 为项目，并新开会话加载项目配置。应用内加载后的工具发现尚需在该新会话核验；当前聊天不会自动刷新工具目录。

其他项目通过 `personal-rag connect <名称>` 生成受限连接，手动合并配置后新开会话。服务端模式按MCP连接/进程隔离；若客户端共享进程则共享模式，不将其宣称为强制聊天ID隔离。

本版没有 Web 界面、OCR、后台监视文件变动或插件市场安装包。人工编辑后使用 sync；笔记软件可直接打开 vault。

## Docker 版补充验收 · 2026-11-12

- 已构建 Linux/amd64 镜像 `personal-rag:0.1.0`；MCP仍使用STDIO，由Codex通过Compose启动。
- 新增 Dockerfile、严格构建上下文允许清单、Compose覆盖文件、免本机Python安装脚本与跨项目配置脚本。
- 以非root身份运行；镜像内未包含 `.env`、Git目录、宿主机知识库。依赖检查通过。
- Docker安装脚本及生成的TOML配置已实际验证；已有管理配置先备份，再生成Docker版配置。
- 原33项回归通过；`scripts/check_docker.py` 的11项端到端检查通过，包括真实容器STDIO握手、数据库初始化、记录、检索、全文、追加、宿主机持久化、关闭模式、只读工具、权限上限和空间隔离。测试未调用外部模型。
- 容器验收使用临时数据库与临时挂载目录，结束后清理。首次验收发现Compose 2.31的run -v未覆盖已有挂载；改为明确Compose文件覆盖后通过，遗留的两份合成Markdown及探针已核对内容并清理。
- 原生管理配置可从 knowledge_workspace/.codex/ 下的备份恢复。Docker版返回容器路径，宿主机原件仍在 knowledge_workspace/vault；可用read_note获取全文。
- 本机导出脚本为 `scripts/export_image.py`，压缩镜像位于被Git忽略的output；镜像尚未上传公共镜像仓库，macOS/ARM尚未在本机验证。

## GHCR 公开发布验收 · 2026-11-12

- 已发布 `ghcr.io/heresy0/personal_rag:0.1.0`、`latest` 和 `sha-d6a737165eb494d1be92d9a4e1cffbf047c638dd`，Linux/amd64。
- 镜像包公开且关联本仓库；匿名读取0.1.0与latest清单成功，两者摘要一致：`sha256:e86d18930d5d577326def51720e89fe448d7838e802b8de407e549562ecd2893`。
- 使用临时空Docker凭据配置完整拉取成功；未复用本机GitHub凭据，也不要求朋友登录GHCR。
- 默认安装脚本实际通过：拉取镜像、启动已有独立数据库、初始化表、生成Docker管理连接配置。发布镜像的11项MCP端到端检查全部通过，外部模型调用0。
- 首次发布在附带attestation的清单阶段被拒绝，失败运行保留：[43195119503](https://github.com/Heresy0/Personal_RAG/actions/runs/43195119503)。调整为明确的Linux/amd64单平台后，[43195519864](https://github.com/Heresy0/Personal_RAG/actions/runs/43195519864) 发布成功。
- 工作流只在推送v*标签或显式手动触发时发布，使用短期GITHUB_TOKEN及contents:read/packages:write权限，不保存个人访问令牌。
- 上节“尚未上传公共镜像仓库”是发布前状态；当前使用方式见README的Docker安装。

## 通用插件0.2.0验收 · 2026-11-12

- 新增portable插件 `plugins/personal-memory`，仓库目录源 `.agents/plugins/marketplace.json`；显示名称“个人知识库”，支持查询、原样保存和自由总结后存入，不定义开发/学习/生活固定模板。
- Codex CLI实际安装成功：`personal-memory@personal-rag`，version=0.2.0，installed=true、enabled=true；实际缓存目录与源码目录分离。
- 本机用户配置只保存知识库根目录和连接名称；独立plugin-memory连接初始off、非admin，默认general/inbox/learning/work/life，可在本机收窄。安装器重跑保留现有连接权限。
- 原样保存修正：capture不再strip正文；元数据解码只处理头部CR，正文换行不被归一化。数据库正文与Markdown元数据头之后的正文保留原始UTF-8字节；索引清洗不回写正文。
- 技能验证通过。完整37项回归通过；安装脚本更新后对应3项再次通过。
- `scripts/check_plugin.py` 从**已安装的缓存启动脚本**运行，11项真实MCP检查通过：缓存启动、工具发现、初始关闭、无管理工具、原样字节、幂等重试、自由总结、来源关联、查询、宿主机持久化、关闭阻止写入。测试用临时数据库和临时资料目录，外部模型调用0。
- 镜像 `ghcr.io/heresy0/personal_rag:0.2.0` 已由[43198289475](https://github.com/Heresy0/Personal_RAG/actions/runs/43198289475)发布成功，已实际拉取并用于缓存插件验收；0.2.0匿名镜像清单请求通过。
- 本机管理入口已切至0.2.0；0.1.0镜像与既有数据保留。未更改原企业项目源码和服务。
- 插件已完成运行时安装与缓存MCP核验。当前聊天工具目录不会自动刷新；需重启客户端或新开本地会话，从＋号/插件选择器搜索“个人知识库”。本轮未通过操作当前Codex界面确认菜单渲染，不将CLI安装状态冒称为已观察到的UI结果。
- 通过个人/仓库目录源安装，不代表提交或获批通用公共插件目录。Windows + PowerShell 7 + Docker Desktop为已验收环境。
