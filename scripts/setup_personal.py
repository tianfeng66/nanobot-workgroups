"""Initialize a portable personal instance without overwriting its settings."""

import json
import shutil
from pathlib import Path

from nanobot.config.loader import load_config, save_config, set_config_path


def main():
    project = Path(__file__).resolve().parent.parent
    data = project / "personal-data"
    data.mkdir(exist_ok=True)
    config_path = data / "config.json"
    set_config_path(config_path)
    if not config_path.exists():
        config = load_config(config_path)
        config.agents.defaults.workspace = str(data / "workspace")
        config.agents.defaults.timezone = "Asia/Shanghai"
        config.tools.workgroups.enable = True
        config.tools.workgroups.storage_dir = str(data / "workgroups")
        config.tools.workgroups.allowed_workspace_roots = [str(data / "workspace"), str(data / "workgroups" / "projects")]
        native_codex = project / "bin" / "codex.exe"
        config.tools.workgroups.codex_command = str(native_codex) if native_codex.exists() else shutil.which("codex") or "codex"
        native_opencode = project / "bin" / "opencode.exe"
        config.tools.workgroups.opencode_command = str(native_opencode) if native_opencode.exists() else "opencode"
        save_config(config, config_path)
    else:
        config = load_config(config_path)
        native_codex = project / "bin" / "codex.exe"
        if config.tools.workgroups.codex_command == "codex" and native_codex.exists():
            config.tools.workgroups.codex_command = str(native_codex)
            save_config(config, config_path)
        native_opencode = project / "bin" / "opencode.exe"
        if config.tools.workgroups.opencode_command == "opencode" and native_opencode.exists():
            config.tools.workgroups.opencode_command = str(native_opencode)
            save_config(config, config_path)
    for name in ("workspace", "logs", "tmp", "cache"):
        (data / name).mkdir(exist_ok=True)
    workspace = data / "workspace"
    soul = workspace / "SOUL.md"
    if not soul.exists():
        soul.write_text("# 个人工作助理\n使用中文沟通。帮助用户创建工作群组，并把用户授权的任务交给 Codex 或 OpenCode。\n"
                        "通过 workgroup 工具创建群组、提交任务、查询实际结果和保存项目约定。\n"
                        "提交成功只代表任务排队，查询到完成结果后才能说任务已完成。\n", encoding="utf-8")
    print(json.dumps({"config": str(config_path), "data": str(data)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
