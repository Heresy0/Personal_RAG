# 可选：微信 → OpenClaw → Codex → Personal_RAG

先按主 README 用 Docker 启动知识库并安装个人知识库插件，再使用下方 Windows 配置脚本接入微信。无需安装包。只需桌面查询、保存或邮件收集时，可以跳过本页。

## 推荐：配置脚本

前提：Windows、PowerShell 7、Node.js 24+（含 npm）、Python 3.12+，以及已登录自己的 Codex。Docker 数据库应已启动，个人知识库插件应已指向本仓库。脚本不会启动共享 Docker 引擎或安装系统服务。

在仓库根目录执行：

```powershell
.\scripts\setup-openclaw.ps1
```

首次只生成被 Git 忽略的 `config/openclaw.local.json`，不会安装或启动网关。编辑它，将 `model` 填为自己可用的 OpenClaw 模型 ID（`提供商/模型名`）；`codexPath` 通常可留空，脚本会查找 PATH 与桌面端附带的 `codex.exe`。发现失败时填写完整 exe 路径。

```json
{
  "model": "openai/替换为自己可用的模型名",
  "codexPath": "",
  "runtimeDir": "output/openclaw",
  "port": 19890
}
```

模型名称必须自己确认；此示例的中文提示不是可用模型名。不需要在配置中填 Codex 登录凭据或额外回答模型密钥。Embedding / Rerank 继续由知识库的 `.env` 单独配置。

填写后继续：

```powershell
.\scripts\setup-openclaw.ps1
.\scripts\openclaw.ps1 login
.\scripts\openclaw.ps1 start
.\scripts\openclaw.ps1 status
```

setup 检查 Docker 数据库、普通插件连接、Node 版本和 Codex 登录状态，安装锁定版本的依赖与官方 Codex 插件，生成隔离配置、随机网关令牌并应用会话绑定补丁。安装阶段按明确包名单构建所需依赖，不全局启用所有 npm 生命周期脚本；官方安装策略拒绝时会停止，不绕过策略。

login 显示微信二维码；扫码成功后自动从本运行目录的账号状态读取扫码本人，仅将其设为所有者，不需要手工寻找用户 ID。如果目录有多个账号，使用 `openclaw.ps1 login -Account <账号ID>` 明确选择，脚本不会猜测。

start 隐藏运行网关并等待就绪，默认最长等待 240 秒；超时会保留进程和日志，应先用 status 查看，不要连续重复启动。状态中的 `Ready=True` 只表示网关就绪，仍需在微信验证回复和知识库操作。

停止时运行：

```powershell
.\scripts\openclaw.ps1 stop
```

停止操作检查 PID、Node 路径、入口文件及专用 profile，只停止这个受管网关。登录、绑定、原始会话和知识库数据保留。重复 setup 保留令牌、所有者、官方插件记录和账号；默认目录 `output/openclaw` 与端口 `19890`，不会接管旧手工环境 `output/openclaw-lab:19889`，也不修改全局 Codex 配置。脚本退出后恢复终端原有的环境变量。

本机验证覆盖临时目录配置、模拟 CLI 的登录/启停全流程、PID 重用拒绝及补丁校验；自动脚本本身尚未在另一个真实微信账号上完成扫码验收。底层适配器的真实手机绑定、历史续接和重启路由已有验证。建议朋友首次完成下面的个人验收。

配置改动需要停止网关后重跑 setup；如果要换端口，应先用旧配置停止，再修改。不会随 `git pull` 自动升级依赖、重启进程或迁移旧手工状态。

下面保留手工安装方式，使用配置脚本时可直接跳到“绑定自己的已有会话”。不要在同一个目录混用两套安装流程，也不要让两个消费者同时读取同一机器人账号。

## 已验证版本与范围

| 组件 | 验证版本 |
| --- | --- |
| OpenClaw、官方 Codex 插件 | `2026.11.3` |
| 腾讯微信插件 | `@tencent-weixin/openclaw-weixin@2.4.10` |
| 本仓库绑定适配器 | `2.4.10+personal-rag-bindings.3` |
| Node.js | 本机 `24.22.1`，适配脚本要求 24+ |
| Codex CLI | 本机 `0.167.0-alpha.4.1`，其他版本需单独验证 |

还需要 PowerShell 7、Python 3.12+（只用于补丁脚本）、已登录且可运行 App Server 的 Codex。知识库仍运行在 Docker；OpenClaw、微信登录和 Codex App Server 运行在使用者自己的电脑，不包含在知识库镜像中。升级上述组件后必须重新验证，不自动套用其他版本补丁。

## 独立目录与安装

在仓库根目录的 PowerShell 中准备隔离运行目录。以下只创建自己的新环境；已有环境不要重复初始化或覆盖配置。

```powershell
$clawRoot = Join-Path (Get-Location) 'output/openclaw-lab'
New-Item -ItemType Directory -Force "$clawRoot/runtime", "$clawRoot/state", "$clawRoot/workspace", "$clawRoot/logs" | Out-Null
npm install --prefix "$clawRoot/runtime" --save-exact openclaw@2026.11.3 @tencent-weixin/openclaw-weixin@2.4.10
if ($LASTEXITCODE -ne 0) { throw 'OpenClaw dependencies failed to install' }
$env:OPENCLAW_STATE_DIR = "$clawRoot/state"
$env:OPENCLAW_CONFIG_PATH = "$clawRoot/state/openclaw.json"
$env:OPENCLAW_NO_RESPAWN = '1'
$env:npm_config_cache = "$clawRoot/npm-cache"
$clawEntry = "$clawRoot/runtime/node_modules/openclaw/openclaw.mjs"
node $clawEntry --profile personal-rag-lab plugins install @openclaw/codex@2026.11.3 --pin
```

最后一步使用 OpenClaw 官方插件安装流程，按实际提示查看和确认能力。安装策略拒绝时应查看原因，不使用绕过策略的参数。npm 生命周期脚本如需批准，只按对应版本依赖的实际构建要求逐项处理，不全局放开所有依赖。

始终在设置了上述环境变量的终端执行后续命令；新终端需重新设置。不要直接操作已有 OpenClaw 默认目录，更不要复制他人的状态目录。手工环境默认端口 `19889`。使用补丁的 `--lab-root` 指定仓库 `output` 下的其他目录时，同时用 `--port` 指定对应网关端口；默认停止检查仍使用 `19889`。

## 配置自己的接入

参考同目录下的 [配置示例](../integrations/openclaw-weixin-bindings/openclaw.example.json)，**合并到官方安装流程生成的本机配置中，保留插件安装记录**。示例不是可直接运行的配置：先替换所有占位符，路径使用绝对路径和 `/`，由 JSON 编辑器确保转义正确。

- `LAB_ROOT`：刚创建的隔离目录。
- `CODEX_EXECUTABLE`：自己的 `codex.exe` 完整路径；`codex --version` 应正常，先在桌面或 CLI 完成自己的登录。
- `MEMORY_LAUNCHER`：本仓库 `plugins/personal-memory/scripts/start-memory.ps1` 的绝对路径。它读取你安装插件时生成的本机路径配置，仍启动 Docker 知识库。
- `GATEWAY_TOKEN`：本机生成的随机令牌，不发到聊天、不提交仓库。
- `MODEL_ID`：本机 Codex 可用、OpenClaw 对应支持的模型 ID；不要照抄作者的账号配置。
- `WEIXIN_OWNER_ID`：自己扫码登录后状态中对应的联系人 ID。先留空数组 `commands.ownerAllowFrom`，登录后再填写；不要填写机器人账号 ID或其他人的 ID。

示例同时配置了 OpenClaw 的 MCP 接入与 Codex App Server 子进程的 MCP 参数，避免恢复历史会话时误用该会话原有的管理连接。`homeScope=user` 使用自己的 Codex 登录与会话目录；它不是新的独立 Codex 账号，但不会要求复制或修改全局配置。

当前普通 MCP 默认关闭，读写范围沿用你自己的 `plugin-memory` 配置，没有管理权限。示例只投射状态、模式、查询、全文、时间线及新建笔记。图片和附件不在这套微信文字接入的验收范围内。

## 应用适配器、登录与启动

确保仅这个实验 Gateway 已停止，再在仓库根目录执行（有 `.venv` 时也可用其 Python）：

```powershell
python integrations/openclaw-weixin-bindings/apply.py
python integrations/openclaw-weixin-bindings/apply.py --apply
node $clawEntry --profile personal-rag-lab plugins registry --refresh --json
node $clawEntry --profile personal-rag-lab channels login --channel openclaw-weixin
```

补丁默认只预检，校验精确版本和上游文件指纹，使用隔离运行目录中的 esbuild 编译，不下载或改写其他项目。重复应用会被拒绝；回滚说明见[适配器 README](../integrations/openclaw-weixin-bindings/README.md)。不要在作者已经打过补丁的运行目录再执行应用。

自己扫描新二维码并确认登录，将扫码本人加入 `commands.ownerAllowFrom`，然后启动：

```powershell
node $clawEntry --profile personal-rag-lab gateway run
```

首次启动可能需要数分钟，检查 `http://127.0.0.1:19889/readyz` 返回 200，再在手机发送测试消息。该命令前台运行，停止时使用 Ctrl+C；不要同时运行另一个消费者读取同一机器人账号。沿用旧 codex-weixin 时须先停旧消费者，但保留原目录和配置以便切换。

## 绑定自己的已有会话

在手机微信发送 `/codex threads`，选择自己的闲置会话或预先建立的测试分支：

```text
/codex bind <自己的会话ID> --cwd <自己的工作目录>
```

若收到绑定授权提示，复制回复中的完整“同意本次绑定”命令；包含末尾的动作字符，不要截断。授权完成后再发普通问题。可以用 `/codex binding` 检查，或 `/codex detach` 解除。不要复制作者的会话 ID 或绑定确认值。

绑定会话拥有既有上下文；它不会自动把聊天写入知识库。需要时明确要求“查询知识库……”或“把这段内容原样保存到知识库……”，以工具返回的 ID 和版本作为保存结果。

独立 App Server 不能避免两个客户端同时写同一会话的冲突；优先使用测试分支，不接管正在工作的会话。权限维持 `guardian`、`on-request`、`workspace-write`，不为通过测试切换无限制模式。

## 验收、升级与备份

先验证真实手机收发，再绑定、提问一个仅原历史知道的问题，确认实际进入目标会话；随后验证知识库查询和保存、网关重启后继续路由。解绑也需要在自己的环境验证。源码函数测试不能代替真实微信验收。

本机已通过手机同意绑定、继承历史、重启后路由及知识库查询和保存验证；真实手机解绑尚未执行。其他人仍需完成自己的扫码、认证和验收。没有自动安装开机自启或系统服务，电脑休眠、关闭或网络中断会影响连接。

升级前私下备份自己的 `state`、工作目录、配置及锁定依赖；同时按主 README 备份知识库数据库和 vault。`output/`、`.env`、本机连接配置、二维码和凭据不应提交 Git。当前运行环境不随 `git pull` 自动重启或升级。
