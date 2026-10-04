# nanobot-workgroups

把 Codex CLI 和 OpenCode 放进个人工作群组：创建项目群、保存共享记忆、派发任务，并查看真实执行结果。

基于 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 的独立衍生项目，保留上游 MIT 许可证与版权声明。不是 OpenAI、OpenCode 或 nanobot 官方产品。

## 下载使用（Windows x64）

1. 从 [Releases](https://github.com/tianfeng66/nanobot-workgroups/releases) 下载源码安装包，或使用 **Code → Download ZIP**，解压到固定目录，例如 `D:\Apps\nanobot-workgroups`。不要在压缩包内运行。
2. 双击 **`install.cmd`**。自动下载 Python 3.12、Codex CLI、OpenCode 和 Python 依赖，无需预装 Python、Node.js 或 Codex 桌面应用。
3. 双击 **`login-codex.cmd`** 或 **`login-opencode.cmd`**，通过官方流程登录自己的模型账号。用哪个成员，就连接哪个。
4. 双击 **`start.cmd`**。浏览器自动打开工作群组；保持服务终端运行。
5. 创建群组，在任务开头写 `@codex` 或 `@opencode` 并提交。

**下载应用不包含模型额度。** 订阅登录消耗账号额度，API Key 登录按厂商规则计费。账号、密钥和群组数据留在使用者自己的电脑，仓库不含作者的登录与资料。

OpenCode 登录后在 `personal-data/workgroups/runtime/xdg-config/opencode/opencode.json` 选定模型，例如：

```json
{"model": "openai/gpt-6-sol"}
```

这是 ChatGPT 登录示例；其他提供方填写相应 `provider/model`，以账号实际可用模型为准。

## 功能

- 独立项目群、成员、共享记忆、任务记录。
- 真实 CLI 执行，显示排队、运行、完成、失败与取消，保存结果和日志。
- 前序任务依赖：Codex 实现后由 OpenCode 检查，前序成功才继续。
- 持久队列；重启保留排队任务，执行中断的任务不会自动重放。
- 主要运行数据跟随安装目录。放在 D 盘即可保存在 D 盘，没有 D 盘也能使用。

任务顺序执行。本版本是本地项目工作群组，尚未接入飞书或 Telegram 群消息。

## 示例

> @codex 创建一个 Python 命令行待办工具，支持添加和查看任务，验证运行结果。

然后选择 OpenCode，指定上一个任务为前序：

> 检查前序实现，指出缺陷并验证。

## 要求

- Windows 10/11 x64，可访问 GitHub、Python 包源及模型服务的网络。ARM64、Linux、macOS 暂无一键安装。
- 安装器下载版本锁定、SHA-256 校验的官方 CLI。
- 服务仅监听 `127.0.0.1:8877`，无需公网服务器。
- Codex 使用 `workspace-write` 沙箱。OpenCode 外部目录限制属于应用权限，不是操作系统隔离。
- 访问已有项目：在 `personal-data/config.json` 的 `tools.workgroups.allowedWorkspaceRoots` 加入根目录，再重启。

配置与故障排查：[使用说明](README-PERSONAL.md)。上游说明：[README-UPSTREAM.md](README-UPSTREAM.md)。

## 开发验证

```powershell
.\install.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest tests/workgroups tests/config/test_config_paths.py tests/tools/test_tool_loader.py -q
.\.venv\Scripts\python.exe -m ruff check nanobot/workgroups nanobot/agent/tools/workgroups.py scripts/setup_personal.py
```

自动测试使用模拟 CLI，不消耗模型额度。真实调用需要使用者登录验证。

## English

A Windows local workgroup dashboard based on nanobot, delegating project tasks to Codex CLI and OpenCode with persistent queues, shared group memory and task dependencies.

Extract the source ZIP, run `install.cmd`, authenticate your own account via `login-codex.cmd` or `login-opencode.cmd`, then run `start.cmd`. Model calls consume your own quota or API balance. The installer keeps runtimes and application data in the installation directory and verifies pinned official CLI downloads. Windows x64 only for the one-click installer.
