# 写入审计（0.3.0）

## 记录范围

`capture`（原样、总结均包含）、`append`、`sync`、逐文件 `sync_file`、`archive`、逐条 `prune` 都在执行前持久化一次尝试，记录连接名、时间、操作ID、父操作ID、笔记ID、空间、请求ID、预期版本、实际前后版本及结果。失败、权限拒绝、幂等重试和无变化同步也记录。同步任务用父操作ID关联每个文件和清理结果，部分失败明确标为 partial。

数据库 `notes` 的 INSERT/UPDATE/DELETE 触发器在同一事务内保存 `change` 事件和前后完整版本；回滚时一起回滚，失败尝试另行保留。UPDATE 自动递增修订号；直接SQL成功修改也记录为 database_write。历史保留正文、标题、标签、来源、路径、归档状态等元数据。物理删除笔记仍保留历史和审计，删除事件的 after_revision 为空。检索分块是派生索引，不逐分块复制日志。

这是知识写入审计。读取、临时模式切换、配置/安装/初始化不作为笔记写入；协议层尚未进入方法的参数校验失败不在业务审计内。绕过应用直接执行的失败SQL、外部编辑器操作文件的时刻无法由本服务捕获；文件在下一次同步时记录为版本。升级前没有审计的操作不能追溯，只补当前版本基线，不伪造历史。

## 存储和结果

- `write_audit`：持久化到PostgreSQL，无正文、标题、原始参数、异常消息或密钥；失败只记异常类别。
- `note_versions`：同库保存完整版本，用审计中的笔记ID和版本号读取前后内容。
- `success`：完成；`noop`：幂等/无变化；`failure`：未发现已提交变更的失败；`denied`：权限拒绝；`partial`：同步部分失败。
- `committed_error`：已发现变更提交，但后续返回失败，不能按“未保存”处理。
- `started`：尚未完成收尾，可能进程退出或数据库不可用，不表示成功或失败。按 operation_id 检查同组 change 事件。
- `unknown`：应急日志标记收尾无法确认，不推断结果。数据库里可能仍显示 started。

开始审计无法落库时，先写应急文件，然后阻止此次业务写入。结束审计无法落库时，保留已提交的 change 事件并尝试写应急文件，结果标为 unknown。应急文件每事件独立创建、flush/fsync，避免多个MCP进程争用同一个日志文件。数据库和文件系统同时不可用时返回审计不可用错误，stderr仅含操作ID，不能保证落盘。进程被强制结束时可能只留下 started。

Docker应急目录为宿主机 `logs/`，已挂载容器 `/data/logs`；原生默认 `knowledge_workspace/logs/`，可用 `PERSONAL_RAG_AUDIT_DIR` 指定。日志与资料均被Git忽略。应急文件用于人工核对，不自动回灌数据库。

数据库与文件系统没有跨系统事务；提交结果未知时需核对原件、版本和change事件。capture重试沿用request_id；append先重新读取最新版本。不要仅因调用报错就另建重复记录。

## 使用

在知识库管理会话中说“查看最近写入审计”“查看这条笔记修改前后的版本”。管理MCP增加 `list_write_audit`（note_id/operation_id/outcome/limit/offset）及 `read_note_version`（note_id/revision）。只向管理员发布，实际读取还要求全空间管理权限；普通项目插件不能查询全库日志或历史正文。

原生命令行：

```powershell
.venv\Scripts\python.exe -m personal_rag.cli audit --limit 20
.venv\Scripts\python.exe -m personal_rag.cli audit --outcome failure
.venv\Scripts\python.exe -m personal_rag.cli audit --note-id <UUID>
.venv\Scripts\python.exe -m personal_rag.cli version <UUID> 1
```

Docker管理命令同样通过 `docker compose -f compose.yaml -f compose.docker.yaml run --rm --no-deps -T mcp audit --limit 20` 调用。

## 升级与备份

先备份PostgreSQL、vault、`.env`和已有应急日志。然后：

```powershell
git pull
.\scripts\setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.3.0
```

setup会运行幂等init迁移，保留既有数据，为当前记录补历史基线。原生部署运行 `python -m personal_rag.cli init`。旧MCP进程退出后新开会话使用新版；插件启动脚本无需改动。不要只换镜像而跳过init。回退旧程序后不要继续写入，否则旧审计客户端无法记录尝试结果。

审计默认持续保留，不自动轮换删除。完整版本包含私人资料，与原文同等保护。数据库备份包含审计和版本，另备份logs。当前数据库用户可改表，日志不是防篡改账本；本机磁盘损坏或管理员清库需依靠独立备份恢复。
