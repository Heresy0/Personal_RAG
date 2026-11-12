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
