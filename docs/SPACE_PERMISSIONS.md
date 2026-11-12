# 读写空间权限（0.4.0）

每个连接有三个独立约束：模式上限、读写空间范围、管理权限。本次请求的space只能缩小范围，不能绕过连接权限。off禁止读写；read禁止写入；readwrite仍需分别通过空间检查。

普通插件新安装默认：

```toml
name = "plugin-memory"
read_spaces = ["*"]
write_spaces = ["*"]
maximum_mode = "readwrite"
initial_mode = "off"
admin = false
```

`*`自动包含现有和未来空间，不授予管理权限。未指定space的查询、时间线检索覆盖全部可读空间，指定时只查目标空间。保存必须选择一个可写空间；未明确分类时由助手选择合适空间或inbox。追加按原笔记空间检查写权限，并校验版本，不要求调用方拥有读取正文权限；无读取权限时写入回执仅包含ID、空间、版本等，不返回正文、标题或文件路径。引用已有笔记作为source_ids仍要求有读取来源的权限。

可以独立限制：

```toml
read_spaces = ["learning", "work"]
write_spaces = ["inbox"]
```

空列表`[]`表示不允许任何空间。审计、历史版本读取仍要求admin=true及全部空间读取权限；同步、归档、清理仍要求管理权限，并受写空间范围限制。普通插件即使拥有两个`*`，也不会发布管理工具。

## 兼容旧配置

旧的`spaces`仍支持，作为未明确指定的新字段的回退值：

- 只有`spaces`：读写范围都沿用原列表，不自动扩大。
- 同时指定新旧字段：read_spaces/write_spaces分别优先；缺少的一侧回退spaces。
- 显式空列表不会回退；所有字段都缺少则读写均为空，按拒绝访问处理。
- 原有Policy位置参数继续有效；memory_status保留spaces作为read_spaces的兼容别名，并增加read_spaces、write_spaces、admin。

重新运行安装脚本会保留已有配置，不擅自扩大旧连接范围。现有用户若要全库读写，先升级后端，再将本机`config/connections/plugin-memory.toml`改成上面的新配置，退出旧MCP连接后重新启动。不要让旧后端加载仅含新字段的配置。

新安装可用`install-plugin.ps1 -ReadSpaces learning -WriteSpaces inbox`独立限制，`-Spaces`继续作为两者共用的默认值；`-ReadOnly`同时设置模式上限read和空写入范围。手动项目连接生成器仍保留原有有限范围，不随普通插件默认值扩大。

## 升级

先备份数据库、vault、.env和本机连接配置。执行：

```powershell
git pull
.\scripts\setup-docker.ps1 -Image ghcr.io/heresy0/personal_rag:0.4.0
```

新用户再运行`install-plugin.ps1`。已有用户按需修改原连接配置，新开会话加载。全空间读写意味着所有使用该插件连接的项目都能访问同一知识库；需要限制的项目使用单独连接和有限列表。连接权限不是同一操作系统用户之间的安全沙箱。
