# OpenClaw 微信会话绑定适配器

为本机隔离实验的 `@tencent-weixin/openclaw-weixin@2.4.10` 增加会话绑定接口。适配器源码独立保存，不包含微信凭据、Codex 配置或第三方源码。

当前适配基线为 OpenClaw `2026.11.3`。仅支持微信私聊；不模拟群聊、话题或子线程。

其他使用者先按主 README 部署 Docker 知识库，再参照[独立微信接入步骤](../../docs/OPENCLAW.md)。本目录只分发适配器、配置示例和测试，不包含作者的运行环境、安装包或任何登录状态。

## 实现范围

- `bindings.resolveCommandConversation`：定位 `/codex bind`、恢复及解绑命令所在的微信联系人。
- `conversationBindings`：声明支持绑定当前私聊，使用 OpenClaw 原生存储，不建立独立的会话映射文件。
- `messaging.resolveInboundConversation` 与 `resolveDeliveryTarget`：普通消息与回复使用同一联系人标识，保留微信 ID 大小写。
- 微信不支持原生绑定授权按钮，因此仅针对这类按钮附加 `/wxbind <一次性动作值>` 文字选项。用户明确同意或拒绝后，调用 SDK 的原生授权接口；不自动批准、不持久化“始终允许”。确认限制为原机器人账号和联系人，30分钟有效、防重放；重启中尚未确认的请求须重新发起。
- 账号、所有者鉴权、原生绑定写入和 Codex 执行仍由 OpenClaw 负责。补丁不放宽所有者权限，不改个人知识库权限。
- 普通文本也通过微信插件原有的 ingress 授权计算，避免因省略 `CommandAuthorized` 被 Codex 绑定处理器静默跳过；未授权联系人和没有保存所有者的旧账号仍无法获得执行授权。

绑定键由 OpenClaw 组合通道、机器人账号和联系人；同一人的其他账号、其他人的私聊不能共享一条绑定。需要同时满足命令和普通消息的标识解析，才能称为绑定生效。

## 本机应用与回滚

脚本固定操作本仓库忽略目录下的 `output/openclaw-lab/runtime/node_modules/@tencent-weixin/openclaw-weixin`。不修改旧 codex-weixin、Codex 全局配置或已安装的个人知识库插件。

上面是手工环境的默认路径。配置脚本使用独立的 `output/openclaw`，通过 `--lab-root <本仓库output下的目录> --port <端口>` 明确目标。`--verify` 只读核对部署清单与文件指纹，允许在网关运行时检查；应用和回滚仍须停对应网关。其他使用者推荐直接运行仓库的 `scripts/setup-openclaw.ps1` 与 `scripts/openclaw.ps1`，见[配置脚本说明](../../docs/OPENCLAW.md)。

先停止实验 Gateway，再执行：

```powershell
node --test integrations/openclaw-weixin-bindings/*.test.mjs
python integrations/openclaw-weixin-bindings/apply.py
python integrations/openclaw-weixin-bindings/apply.py --apply
```

默认只预检；应用前检查包名、精确版本及六份上游文件 SHA-256，拒绝覆盖未知版本或重复补丁。源码和编译产物共十二个文件，备份及补丁清单留在 `output/openclaw-lab/backups`。编译使用隔离环境已有的 esbuild。

Python 要求 3.12+；Node.js 要求 24+，优先使用隔离目录的 `tools/node/node.exe`，没有时使用 PATH 中的 Node。普通函数测试可以独立运行；三个 SDK/调度测试及一个 ingress 测试需要指定 `OPENCLAW_TEST_BINDING_CORE`、`OPENCLAW_TEST_CONVERSATION_SDK`、`OPENCLAW_TEST_REPLY_SDK`、`OPENCLAW_TEST_WEIXIN_AUTH` 对应本机已安装模块路径，未指定时会明确跳过，不代表完整集成验证通过。

应用后刷新实验插件注册表并启动实验 Gateway。不要同时运行两个进程消费同一机器人账号。

回滚时停止实验 Gateway，传入实际生成的备份目录：

```powershell
.venv/Scripts/python.exe integrations/openclaw-weixin-bindings/apply.py --rollback output/openclaw-lab/backups/<本次备份目录>
```

回滚会核对已部署文件指纹，拒绝覆盖部署后的额外修改；只恢复六份上游文件并移除本适配器的六份源码/产物。微信登录和绑定数据不删除。

## 使用与验收

在微信中发送 `/codex threads` 查看可见会话；对闲置会话或用户确认的测试分支执行：

```text
/codex bind <thread-id> --cwd <工作目录>
/codex binding
/codex detach
```

首次绑定若显示 `Plugin bind approval required`，复制回复中的“同意本次绑定”命令发送。收到绑定确认后，下一条普通消息才应进入目标 Codex 会话；未确认前不要把测试聊天的回复当成原历史已恢复。

优先从已有会话建立测试分支，避免通过独立 Codex App Server 同时写入一个正在使用的原会话。插件补丁不能消除独立 App Server 的并行写入限制。

必须分别验证：命令绑定成功、下一条普通消息进入目标 native thread、能依据原历史回答、解绑后回到普通聊天、重新绑定和 Gateway 重启后继续路由，以及普通 Personal_RAG MCP 权限仍为 `admin=false`。本地函数测试通过不等于真实微信收发及历史续接验收通过。

目前不自动升级第三方插件，也不推送此本机补丁到上游；升级 OpenClaw 或微信插件后须重新检查 SDK 接口和消息路由。

## 本机验证结果（2026-11-13）

补丁 `.3` 通过 15 项 Node 测试、4 项 Python 测试及 SDK 类型检查。手机明确确认绑定后，实验网关重启，普通微信消息进入从闲置会话建立的 Codex 测试分支，且未调用工具或读取文件便正确回答原历史问题；用户确认收到了相同回复。原 10 个配置/凭据文件与原始会话日志指纹保持一致。

Personal_RAG 查询、单条测试记录写入及读回已验证；普通插件仍为 `admin=false`，默认模式 `off`。真实手机解绑尚未执行，目前保留测试分支绑定。不包含开机自启或全天候运行保障。
