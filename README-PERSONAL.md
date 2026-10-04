# 工作群组使用说明

先按 [README](README.md) 安装，建议放在 D 盘固定目录。安装后不要直接移动目录：Python 环境和配置记录绝对路径。迁移时重新安装，再导入数据、更新项目路径。

## 模型与账号

使用者登录自己的账号。安装器不导入其他应用的登录，不包含作者的认证。

```powershell
.\start-personal.ps1 -Mode CodexLogin
.\start-personal.ps1 -Mode OpenCodeLogin
.\start-personal.ps1 -Mode Doctor
```

Codex 支持 ChatGPT 登录或 API Key。OpenCode 用登录向导连接提供方，然后在 `personal-data/workgroups/runtime/xdg-config/opencode/opencode.json` 配置模型，例如：

```json
{"model": "openai/gpt-6-sol"}
```

也可在 `personal-data/config.json` 设置 `tools.workgroups.opencodeModel`（`provider/model`）与 `codexModel`。请选账号实际支持的模型。

Doctor 的 `available` 只表示检测到 CLI，不证明登录或模型可用。建群、保存记忆、查看结果不消耗模型额度，执行任务消耗用量。nanobot 自然语言派单另需配置主模型；网页直接派单无需主模型。

## 数据目录

```text
安装目录/
  .python/                         下载的 Python
  .venv/                           应用环境
  .uv-cache/                       安装缓存与校验下载
  bin/                             官方 CLI
  personal-data/
    config.json                    配置
    workspace/                     nanobot 工作区与记忆
    sessions/                      nanobot 会话
    workgroups/
      groups.sqlite3               群组、记忆、队列与结果
      dashboard.token              网页认证
      projects/<group-id>/          项目目录
      tasks/<task-id>/              日志与 result.md
      runtime/codex/               Codex 认证与会话
      runtime/xdg-data/opencode/   OpenCode 认证与数据库
      runtime/xdg-config/opencode/ OpenCode 模型配置
      runtime/xdg-cache/           OpenCode 缓存
      runtime/cache/               子进程缓存
      tmp/                         临时文件
```

系统、浏览器和插件可能有自己的缓存。发布源码时不包含运行目录，备份认证需妥善保管。

## 项目与端口

给配置的 `tools.workgroups.allowedWorkspaceRoots` 添加授权根目录，再重启。默认只允许本实例的 `workspace` 与 `workgroups/projects`，解析路径后检查包含关系。

更换端口：

```powershell
.\start-personal.ps1 -Port 8878
```

服务终端需保持运行。关闭终端会关闭网页，独立队列中的任务继续。本版本未安装系统服务或开机自启。不要重复启动占用同一端口的服务。

## 故障排查

- 下载失败：确认 GitHub 与 Python 包源可用。如有代理，在终端中设置 `HTTPS_PROXY` 和 `HTTP_PROXY` 再安装。
- 校验失败：删除报错指定 ZIP 后重新安装，不要关闭校验。
- 未登录、401、令牌失效：运行相应登录入口。
- 模型不可用、额度不足：检查额度、选择支持的模型。
- 网络失败：从普通 Windows 终端启动，检查模型服务和代理。
- 端口占用：关闭已有服务，或用 `-Port` 更换端口。
- 项目目录不允许：添加到 `allowedWorkspaceRoots`。
- worker 重启后任务中断：先检查文件再提交，不会自动回滚或重放执行到一半的任务。

Codex 未启用审批或沙箱绕过。OpenCode 应用权限不能替代操作系统隔离。只授权你愿意由执行成员修改的项目。

登录说明：[Codex](https://developers.openai.com/codex/auth)、[OpenCode](https://opencode.ai/docs/providers/)。上游：[HKUDS/nanobot](https://github.com/HKUDS/nanobot)。
