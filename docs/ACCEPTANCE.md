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
