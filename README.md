# nanobot-workgroups

把 Codex CLI 和 OpenCode 放进个人工作群组：创建项目群、保存共享记忆、派发任务，并查看真实执行结果。

基于 [HKUDS/nanobot](https://github.com/HKUDS/nanobot) 的独立衍生项目，保留上游 MIT 许可证与版权声明。不是 OpenAI、OpenCode 或 nanobot 官方产品。

## 下载使用（Windows x64）

1. 从 [Releases](https://github.com/tianfeng66/nanobot-workgroups/releases) 下载源码安装包，或使用 **Code → Download ZIP**，解压到固定目录，例如 `D:\Apps\nanobot-workgroups`。不要在压缩包内运行。
2. 双击 **`install.cmd`**。自动下载 Python 3.12、Codex CLI、OpenCode 和 Python 依赖，无需预装 Python、Node.js 或 Codex 桌面应用。
3. 双击 **`login-codex.cmd`** 或 **`login-opencode.cmd`**，通过官方流程登录自己的模型账号。用哪个成员，就连接哪个。
4. 双击桌面的 **“nanobot 个人工作台”**，或者安装目录里的 **`打开工作台.vbs`**。自动后台启动并登录，以独立应用窗口打开；不需要打开终端。没有 Edge / Chrome 时使用默认浏览器。
5. 创建群组，在任务开头写 `@codex` 或 `@opencode` 并提交。

**下载应用不包含模型额度。** 订阅登录消耗账号额度，API Key 登录按厂商规则计费。账号、密钥和群组数据留在使用者自己的电脑，仓库不含作者的登录与资料。

OpenCode 登录后在 `personal-data/workgroups/runtime/xdg-config/opencode/opencode.json` 选定模型，例如：

```json
{"model": "openai/gpt-6-sol"}
```

这是 ChatGPT 登录示例；其他提供方填写相应 `provider/model`，以账号实际可用模型为准。

## 功能

- 桌面应用入口：自动启动、自动本机登录、复用已有服务；关闭应用窗口后，后台任务继续执行。
- 独立项目群、成员、共享记忆、任务记录。
- 真实 CLI 执行，显示排队、运行、完成、失败与取消，保存结果和日志。
- 前序任务依赖：Codex 实现后由 OpenCode 检查，前序成功才继续。
- 持久队列；重启保留排队任务，执行中断的任务不会自动重放。
- 主要运行数据跟随安装目录。放在 D 盘即可保存在 D 盘，没有 D 盘也能使用。
- 切换群组保留当前页面中的任务和记忆草稿；失败任务支持编辑后重新提交。
- 资料收件箱：导入文字、文档或图片，用模型生成带分类与标签的 Markdown 笔记。
- 个人资料问答：本地检索相关原文，再生成带资料编号的回答。
- 任务跟进：生成可检查的项目计划，按步骤接力执行，保存检查点、暂停与处理卡点。

任务顺序执行。本版本是本地项目工作群组，尚未接入飞书或 Telegram 群消息。

## 示例

> @codex 创建一个 Python 命令行待办工具，支持添加和查看任务，验证运行结果。

然后选择 OpenCode，指定上一个任务为前序：

> 检查前序实现，指出缺陷并验证。

## 个人资料与项目工作台

桌面入口直接打开个人工作台。也可在浏览器中打开 `http://127.0.0.1:8877/assistant`；未登录时显示登录页，点击“打开桌面应用”即可通过已安装的桌面入口进入。

需要在其他浏览器登录时，展开“在当前浏览器登录”，输入本机 `personal-data/workgroups/dashboard.token` 文件中的访问码。访问码请自行保管。本机登录有效期为 30 天，桌面入口可随时重新登录；模型账号仍只需按官方流程连接。网页服务未运行时，先双击桌面入口。

### 资料收件箱

上传资料并导入，或者把文件放在页面显示的收件箱目录中，再点“导入收件箱”。导入仅在本机提取文字；点击“用模型整理”才会使用所选成员，生成摘要、分类、标签与 Markdown 笔记。图片整理会将图片交给所选模型识别。可以在页面阅读摘要、下载原文和笔记。

勾选“自动整理新资料”后，后台每 10 秒检查一次收件箱，为未整理的新资料排队。默认关闭；关闭后已排队的任务仍继续，可在工作群组中取消。相同内容不重复索引，原文件保留。修改过的资料保存新版本，历史问答继续引用当时的原文副本。

支持 UTF-8 TXT/Markdown、文字 PDF、DOCX、HTML 摘录以及 PNG/JPG/WebP。单文件最多 8 MB、文字最多 120000 字符、PDF 最多 80 页。加密 PDF 先解密，扫描 PDF 先导出为图片。模型摘要只接收文字前 48000 字符，超长摘要会提示范围；不保证图片文字识别完全准确。

数据在 `personal-data/workgroups/assistant` 下：`inbox` 是收件箱，`sources` 是原文副本，`library` 是笔记目录。可将 `library` 作为 Obsidian 笔记目录使用。安装在 D 盘时这些资料也在 D 盘。

### 个人资料问答

输入问题后，可以先点“本地检索”，查看带原文行号的摘录，不调用模型。点“根据资料回答”后，会选择最多 8 份相关资料，让成员给出带 `[资料 1]` 等编号的回答；展开引用可核对摘录与下载原文。没有相关资料时不发起模型调用。

检索采用本地中文词组和英文关键词匹配，尚未接入向量数据库；问题尽量使用资料中的名称或关键词。回答只基于选中的摘录，资料不足时仍可能无法回答。整理和问答会创建独立工作群组，结果、错误与实际执行日志均可查看。

### 任务跟进

选择项目工作群组并填写目标，点击“生成计划”。此时只生成 1–12 个步骤，检查步骤要求和成员后，再点击“检查后开始执行”。例如让 Codex 实现工具，再由 OpenCode 验证。

每一步完成后才派发下一步。CLI 报错、任务取消、运行中断或成员报告未完成时，计划会停在卡点。补充检查点、检查实际文件后，可重试当前步骤；成功步骤不会自动重放。重试失败步骤可能重复其已有的部分操作，需要先核对文件。暂停只停止派发后续步骤，已经派发的步骤继续运行。

计划、步骤与检查点写入本地数据库，重启后保留；模型报告完成仍需结合日志和实际产物检查。点击“查看执行日志与结果”可查看对应任务。

当前没有每日简报、任务模板、模型费用统计、手机远程入口或飞书/Telegram 群消息功能。

## 要求

- Windows 10/11 x64，可访问 GitHub、Python 包源及模型服务的网络。ARM64、Linux、macOS 暂无一键安装。
- 安装器下载版本锁定、SHA-256 校验的官方 CLI。
- 服务仅监听 `127.0.0.1:8877`，无需公网服务器。
- Codex 使用 `workspace-write` 沙箱。OpenCode 外部目录限制属于应用权限，不是操作系统隔离。
- 首次运行在独立 Codex 配置中启用 Windows `unelevated` 原生沙箱，适合无需管理员配置的后台执行。已配置的沙箱模式会保留；需要更强隔离时可按[官方说明](https://developers.openai.com/codex/windows)配置 `elevated`。
- 访问已有项目：在 `personal-data/config.json` 的 `tools.workgroups.allowedWorkspaceRoots` 加入根目录，再重启。

配置与故障排查：[使用说明](README-PERSONAL.md)。上游说明：[README-UPSTREAM.md](README-UPSTREAM.md)。

## 更新已有安装

先等待任务结束，关闭网页服务，并重启电脑以退出独立运行的后台队列进程。下载新版本并解压，用新源码覆盖原安装目录，保留 `personal-data`、`bin`、`.python`、`.venv` 和 `.uv-cache`，然后重新运行 `install.cmd`。安装器会保留现有配置和登录资料。重新启动后继续处理排队任务。

变更记录：[CHANGELOG.md](CHANGELOG.md)。

## 开发验证

```powershell
.\install.ps1 -Dev
.\.venv\Scripts\python.exe -m pytest tests/workgroups tests/config/test_config_paths.py tests/tools/test_tool_loader.py -q
.\.venv\Scripts\python.exe -m ruff check nanobot/workgroups nanobot/agent/tools/workgroups.py scripts/setup_personal.py
```

自动测试使用模拟 CLI，不消耗模型额度。真实调用需要使用者登录验证。

## English

A Windows local workgroup dashboard based on nanobot, delegating project tasks to Codex CLI and OpenCode with persistent queues, shared group memory and task dependencies.

Extract the source ZIP, run `install.cmd`, authenticate your own account via `login-codex.cmd` or `login-opencode.cmd`, then open the installed desktop shortcut or `打开工作台.vbs`. It starts the server in the background and signs into the local workspace automatically. Model calls consume your own quota or API balance. The installer keeps runtimes and application data in the installation directory and verifies pinned official CLI downloads. Windows x64 only for the one-click installer.
