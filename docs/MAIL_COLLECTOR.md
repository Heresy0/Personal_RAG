# QQ与163新邮件增量收集（0.5.0）

独立可选的IMAP收信进程，主动连接QQ和163，不需要公网域名、SMTP或远程API，不改变原有本地插件。真实邮箱需要你自行在本机填写地址和客户端授权码；测试不等于已完成QQ/163真实账号登录验收。

## 收什么、从何时开始

- 只监控配置中已启用的`@qq.com`和`@163.com`个人邮箱的INBOX。垃圾箱、发件箱和其他文件夹不扫描；本版不支持Foxmail别名、企业邮箱或自定义服务器。
- 每个来源第一次成功连接时，以收件箱UIDVALIDITY、UIDNEXT建立基线，仅保存状态，不搜索、下载或索引已有邮件正文。界定的是**首次成功建立基线之后**，不是填写配置或生成授权码的时刻。
- 后续通过限定上、下界的UID搜索发现新增邮件，不使用UNSEEN/未读条件。历史邮件即使未读，也不会补采。新搬入但服务器INTERNALDATE早于启用时间的旧邮件，在下载正文前跳过；发件人自行填写的Date头不用于判定新旧。
- 已建立基线后，重启、断网、暂停再恢复都续用原游标，不重新忽略积压的新邮件。服务器已删除且尚未下载的邮件无法恢复，会标记missing，而不会宣称收集完成。
- 服务器UIDVALIDITY变化、UIDNEXT回退或来源ID对应的账号身份改变时停止该来源，不自动重建游标或回扫历史。不要删除状态表或随意改ID排错；确认需要新基线时先备份，再明确配置新的来源ID。

IMAP使用TLS证书验证、993端口、EXAMINE只读选择及BODY.PEEK读取；不调用STORE/CLOSE/EXPUNGE、删除、移动、标记已读或发送邮件。供应商授权码本身可能有更广权限，但本程序只执行上述只读收信命令。协议依据：[IMAP标准](https://www.rfc-editor.org/rfc/rfc3501)。

## 本机配置

先备份PostgreSQL、整个vault、.env和连接配置，然后在仓库根目录执行：

```powershell
git pull
.\scripts\setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.5.0
.\scripts\setup-mail.ps1
```

setup-mail只创建本机`config/mail.toml`并补充.env的授权码变量，不连接邮箱、不启动收信。已有配置和授权码保留，来源默认enabled=false。以下文件均留在本机，不提交Git，也不进入镜像。

编辑`config/mail.toml`：

```toml
[[accounts]]
id = "qq-main"
provider = "qq"
username = "你的完整QQ邮箱地址@qq.com"
auth_code_env = "PERSONAL_RAG_MAIL_QQ_AUTH_CODE"
enabled = true

[[accounts]]
id = "163-main"
provider = "163"
username = "你的完整163邮箱地址@163.com"
auth_code_env = "PERSONAL_RAG_MAIL_163_AUTH_CODE"
enabled = true
```

在两个邮箱网页设置中开启IMAP服务，分别生成客户端授权码，填进本机.env：

```dotenv
PERSONAL_RAG_MAIL_QQ_AUTH_CODE=在本机填写QQ客户端授权码
PERSONAL_RAG_MAIL_163_AUTH_CODE=在本机填写163客户端授权码
```

不要使用登录密码，不把授权码发到聊天或写入仓库。QQ官方步骤见[生成授权码](https://help.mail.qq.com/detail/106/985)；网易设置可从[网易邮箱帮助中心](https://help.mail.163.com/)进入。只准备一个账号时，另一个保持enabled=false。密码或授权码轮换后保留id和地址，并重建mail容器加载新环境变量。

## 建立基线并收取测试新邮件

首次先运行一次：

```powershell
docker compose -f compose.yaml -f compose.docker.yaml -f compose.mail.yaml --profile mail run --rm --no-deps -T mail mail-poll
```

两个来源各自返回initialized才表示基线已建立；认证失败的来源尚未启用，其他账号可独立成功。此时不会导入旧邮件。保持系统时间准确，启用时间还用于检查服务器收件时间。

随后向两个邮箱分别发送一封带唯一测试文字的新邮件，再运行mail-poll。预期saved增加，旧邮件未出现，网页端已读/未读状态不变。运行以下命令启用常驻收信，默认每60秒轮询、单账号每轮最多处理50封：

```powershell
docker compose -f compose.yaml -f compose.docker.yaml -f compose.mail.yaml --profile mail up -d mail
```

查看状态和日志：

```powershell
docker compose -f compose.yaml -f compose.docker.yaml -f compose.mail.yaml --profile mail run --rm --no-deps -T mail mail-status
docker compose -f compose.yaml -f compose.docker.yaml -f compose.mail.yaml --profile mail logs --tail 50 mail
```

mail-status显示数据库历史游标及队列计数，不代表进程一定正在运行；用Compose ps/logs核实。日志只输出来源ID、计数、结果与错误类别，不输出授权码、邮件正文或原始服务器异常消息。

暂停收集用同一组Compose参数执行`stop mail`。修改地址、开关或.env后，使用同一组参数执行`up -d --force-recreate mail`加载配置；不要用restart期待.env自动刷新。只重建mail，不操作mcp或原企业服务。

## 如何入库及查询

- 邮件正文、主题、发件人、收件人、时间、附件文件名和原件位置保存为inbox中的original笔记，由正常检索链路索引，不生成AI总结，不执行邮件中的指令。
- `vault/inbox/.mail/<来源ID>/<UIDVALIDITY>/<UID>/`保存完整original.eml、附件文件副本、manifest.json和用于幂等重试的capture.json。目录隐藏，不被sync重复导入。原邮件保留所有原始内容，附件副本仅归档，不自动OCR、解压、执行或索引附件正文。
- 图片附件仍需“AI识别→人工核对→原图和最终文字关联保存”；授权处理时先从归档副本复制到目标空间.incoming，再用capture_note的image_paths保存，source_ids可关联原邮件笔记ID。不要把已归档附件误称为已识别入库。
- 邮件原件上限25MiB；超限在正文下载前记录失败，其他新邮件继续处理。超长正文不静默截断；若超过笔记长度或分块限制会保留已下载原件并记录失败。
- 按来源ID、UIDVALIDITY和UID去重；同一封邮件进入不同账号可各保留一份来源，不单凭Message-ID合并。失败任务单独重试，不阻塞新邮件；新任务优先，失败任务在后续有处理额度时重试。
- 如果笔记已提交但邮件处理状态写回失败，下次使用同一request_id和持久化内容快照重试，不重复建笔记。原件或快照哈希不符时停止该邮件，不静默替换原件。
- 原有write_audit记录笔记写入，mail_sources/mail_items/mail_events记录收集基线、进度和失败。备份需同时包含数据库和整个vault，不能只备份邮件正文笔记。
- 若现有embedding配置启用，邮件正文会按该配置发送给模型供应商并产生费用；不调用主生成模型。未启用embedding时仍可使用关键词检索。

例如在已开启个人知识库的会话中说：“查一下今天收到的报价邮件，列出发件人、收件时间和原始记录。”只有配置允许读取inbox的连接才能查询这些记录。

## 验收边界

回归使用模拟邮箱和本地TLS IMAP服务器，验证EXAMINE、BODY.PEEK、历史跳过、增量、失败重试及已读标记不变，不使用真实授权码、不连接真实QQ/163、不调用外部模型。首次实际使用仍需按上述测试新邮件步骤，验证各自账号的授权、网络及供应商服务状态。
