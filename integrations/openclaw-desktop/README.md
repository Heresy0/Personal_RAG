# 本机桌面原会话模式

微信是同一条桌面 Codex 会话的输入和回复入口。此插件不运行自己的 Codex App Server，不创建分支；使用 `codex queue --thread UUID --message ...` 投递，并只读匹配原会话日志中的任务结果。电脑端可以继续使用同一条会话。

## 配置

先完成 Docker、个人知识库插件和 `setup-openclaw.ps1` 初始化。在被忽略的 `config/openclaw.local.json` 中设置：

```json
{
  "mode": "desktop",
  "model": "",
  "codexPath": "",
  "runtimeDir": "output/openclaw",
  "port": 19890,
  "desktopThreadId": "填写自己的原会话UUID",
  "desktopWorkspace": "填写这条会话的绝对工作目录",
  "desktopCodexHome": "",
  "desktopAutoOpen": true
}
```

`model` 在此模式不用于生成回答，沿用原会话模型。`desktopCodexHome` 默认当前用户的 `.codex`。setup 会只读核对原会话 ID、工作目录、是否已归档及日志文件边界，不修改 Codex 索引、会话文件或项目 MCP 配置。

先在这条桌面会话中启用个人知识库插件并验证查询/保存，再接入微信。全局插件安装检查并不代表目标桌面会话已启用相同工具。

```powershell
.\scripts\setup-openclaw.ps1
.\scripts\openclaw.ps1 login
.\scripts\openclaw.ps1 start
.\scripts\openclaw.ps1 status
```

初次扫码后自动设置扫码本人为所有者。此模式使用本机固定绑定，不需要 `/codex bind`。微信中 `/wxdesk` 显示绑定和最近任务。启动后遇到待处理消息，默认会通过 `codex://threads/<UUID>` 打开原聊天；`desktopAutoOpen=false` 时由用户自行打开原会话。投递不使用 `--resume`，避免让另一 daemon 接管写入；由桌面端恢复原聊天。成功入队不等于已执行，桌面未开始时仍保持队列状态。

**桌面模式继承原会话的工具与权限。**它不能像独立 App Server 一样用子进程参数替换桌面会话的 MCP 配置。尤其 `knowledge_workspace` 默认有管理连接；需要普通读写范围时，应在桌面会话中先明确配置并核实普通连接。脚本只提示这个差别，不自动改管理项目，不宣称桌面模式仍强制 `admin=false`。

## 登录 Windows 后自动恢复

首次配置和扫码验收完成后，可注册当前用户的登录任务：

```powershell
.\scripts\openclaw-autostart.ps1 enable
.\scripts\openclaw-autostart.ps1 status
# 取消自动启动，不停止当前运行的网关：
.\scripts\openclaw-autostart.ps1 disable
```

任务仅在当前用户登录 Windows 后以普通权限运行，不设置 Windows 自动登录、不保存密码。它启动本仓库网关；共享 Docker 引擎已经运行时，仅请求本项目 PostgreSQL 启动，不启动企业容器或共享 Docker Desktop。引擎未运行时等待，收到的消息继续保留在队列中。用户应自行设置 Docker Desktop 登录后启动，或手动启动它。

`desktopThreadId`、目录、微信登录和任务状态保存在本机文件/数据库，重启后读取相同值；无需每次重新绑定。微信或 Codex 认证过期、会话被删除/归档、目录迁移时仍需处理相应错误。实际网络连接会重建，不是保持重启前的进程连接。

PID 在重启后可能被其他程序复用。启动检查会忽略已经不属于本组件的旧 PID，并检查端口；停止操作仍严格核对 Node、入口、profile 和 `gateway run`，不会结束这个其他程序。

## 持久队列和恢复规则

本运行目录的 `desktop-queue.sqlite` 使用 SQLite WAL 与 FULL 同步。收到授权文字并成功落盘后才回复确认；上游消息 ID 按机器人账号及联系人隔离去重，正文不修剪空白。当前只支持文字，图片和附件明确拒绝入队。

| 状态 | 意义与恢复方式 |
| --- | --- |
| `pending` | 已落盘，等待知识库数据库就绪；可以取消 |
| `dispatching` | 正在投递；若此时进程中断，恢复为 `uncertain` |
| `queued` | Codex 接受了队列请求，尚未确认开始；不重复投递 |
| `running` | 在原会话找到本任务标记，继续匹配对应 turn |
| `completed` | 已保存结果，等待回传；回传失败只重试发送结果 |
| `delivered` | 回传已由微信发送适配器确认 |
| `uncertain` | 不确定是否已经投递；继续核对原会话，绝不自动重发 |
| `failed` / `paused` | 原任务中断，或权限、目录、绑定改变；不自动执行 |
| `cancelled` / `reviewed` | 已取消未投递任务，或用户核对后解除不确定任务等待 |

每个运行目录依次处理任务。电脑输入由桌面 Codex 自己排队；本插件不发送中断或 steer 命令。`uncertain` 会阻止后续微信任务投递，避免乱序执行。查看并处理：

```text
/wxdesk
/wxdesk result <任务ID>
/wxdesk cancel <任务ID>
/wxdesk acknowledge <任务ID> confirm
```

最后一条只用于在电脑核对 `uncertain` / `failed` 后解除本地等待，**不会撤回、停止或重发原桌面任务**。如确需重新执行，由用户核对后重新发送请求，不承诺任意外部操作“恰好一次”。微信回传时崩溃仍可能重复回传某个结果片段，但不会因此再次执行 Codex 任务。

## 从独立模式切换

已有 `/codex bind` 原生绑定时，先在微信 `/codex detach`，再停止对应网关、修改配置并重新 setup。脚本只读检查原生绑定，发现未解除时拒绝切换，不直接修改 OpenClaw 的绑定数据库。保留的 `app-server` 模式仍可使用。

旧手工目录 `output/openclaw-lab` 不由新脚本自动迁移。不要复制作者的微信状态或让两个网关消费同一账号；切换前停止旧消费者，新受管目录首次使用自己的二维码登录。后续正常重启不需要重新扫码。

## 保障边界与备份

- 只保障已经被本机插件收到并持久化的消息。电脑关机期间微信是否补发、补发多少，不作保证；没有云端接收器。
- 不自动判断过期请求是否仍适合执行。只应绑定用户认可用于日常查询和记录的会话；积压消息包含原始接收时间，涉及副作用的请求仍按桌面原会话审批。
- 桌面未就绪时保留任务，绝不改用独立 App Server 抢占原会话。账号、工具权限和真实执行结果需要在自己的电脑验收。
- 私下备份本机配置、整个受管运行目录（包括 SQLite 的 WAL 配套文件，或停机后备份）、Codex 会话和知识库数据库/vault。运行目录、二维码、日志和队列不进入 Git 或 Docker 镜像。

测试包括确定性队列/恢复/去重/Unicode日志/取消并发测试、只读会话目录核对及隔离 OpenClaw 加载；真实微信投递与 Windows 实际重启恢复须另外完成，不能用网关 ready 或命令退出码代替。
