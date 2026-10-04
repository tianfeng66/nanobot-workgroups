"""Reachable contracts for persisted groups and external CLI task execution."""

import json
import sys
import threading
import time
from pathlib import Path

import pytest

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.workgroups import WorkgroupsTool
from nanobot.config.home import get_instance_home
from nanobot.config.loader import get_config_path, set_config_path
from nanobot.workgroups import worker
from nanobot.workgroups.config import WorkgroupsConfig
from nanobot.workgroups.service import WorkgroupService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.config.loader._current_config_path", tmp_path / "config.json")
    return WorkgroupService(WorkgroupsConfig(enable=True, storage_dir=str(tmp_path / "groups")))


def test_groups_memory_and_tasks_survive_restart_with_no_cross_group_context(service):
    first = service.create("网站开发")
    second = service.create("学习资料")
    service.set_memory(first["id"], "使用中文；网站色调是蓝色")
    task = service.submit(first["id"], "codex", "整理设计")
    service.finish(task["id"], "completed", "已整理网站设计")
    restarted = WorkgroupService(service.config)
    assert restarted.group(first["id"])["memory"] == "使用中文；网站色调是蓝色"
    assert restarted.tasks(second["id"]) == []
    other = restarted.submit(second["id"], "opencode", "整理资料")
    assert "网站设计" not in worker.build_prompt(restarted, other)


def test_dependency_orders_tasks_and_failed_parent_blocks_followup(service):
    group = service.create("协作组")
    first = service.submit(group["id"], "codex", "实现功能")
    followup = service.submit(group["id"], "opencode", "检查实现", first["id"])
    assert service.claim()["id"] == first["id"]
    assert service.claim() is None
    service.finish(first["id"], "completed", "新增了入口文件")
    assert service.claim()["id"] == followup["id"]
    assert "新增了入口文件" in worker.build_prompt(service, followup)
    service.finish(followup["id"], "failed", error="模型未配置")
    blocked = service.submit(group["id"], "codex", "继续", followup["id"])
    assert service.claim() is None
    assert service.task(blocked["id"])["status"] == "failed"


def test_workspace_escape_and_cross_group_dependency_are_rejected(service):
    with pytest.raises(ValueError, match="outside"):
        service.create("越界", str(service.root / "projects" / ".." / "runtime"))
    first, second = service.create("甲"), service.create("乙")
    task = service.submit(first["id"], "codex", "工作")
    with pytest.raises(ValueError, match="same group"):
        service.submit(second["id"], "opencode", "读取另一组", task["id"])


def test_recovery_marks_running_interrupted_without_replaying_and_keeps_queue(service):
    group = service.create("恢复")
    running = service.submit(group["id"], "codex", "可能修改文件")
    waiting = service.submit(group["id"], "opencode", "另一任务")
    service.claim()
    service.recover()
    assert service.task(running["id"])["status"] == "interrupted"
    assert service.claim()["id"] == waiting["id"]


def test_real_subprocess_result_persists_and_user_text_is_not_shell_code(service, monkeypatch):
    group = service.create("进程测试")
    task = service.submit(group["id"], "codex", "中文任务 `$(Remove-Item *)`")
    task = service.claim()

    def fake_command(_service, _task, directory):
        script = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.stdin.read(),encoding='utf-8')"
        return [sys.executable, "-c", script, str(directory / "result.md")], _task["prompt"].encode()

    monkeypatch.setattr(worker, "command_for", fake_command)
    worker.execute(service, task)
    result = service.task(task["id"])
    assert result["status"] == "completed"
    assert result["result"] == "中文任务 `$(Remove-Item *)`"


def test_cancel_terminates_running_cli_and_remains_cancelled(service, monkeypatch):
    group = service.create("取消")
    task = service.submit(group["id"], "codex", "长任务")
    task = service.claim()
    monkeypatch.setattr(worker, "command_for", lambda *_: ([sys.executable, "-c", "import time; time.sleep(60)"], None))
    thread = threading.Thread(target=worker.execute, args=(service, task))
    thread.start()
    time.sleep(0.5)
    service.cancel(task["id"])
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert service.task(task["id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_tool_respects_current_request_workspace(service):
    first, second = service.create("甲"), service.create("乙")
    tool = WorkgroupsTool(service.config, Path(first["workspace"]), True)
    with request_context(RequestContext(channel="websocket", chat_id="local", workspace=Path(first["workspace"]))):
        visible = json.loads(await tool.execute("list"))
        assert [group["id"] for group in visible] == [first["id"]]
        result = await tool.execute("memory", group_id=second["id"], text="不允许写入")
        assert "outside" in result
    assert service.group(second["id"])["memory"] == ""


def test_config_and_backend_data_paths_use_d_drive_override(service, monkeypatch):
    instance = service.root.parent
    monkeypatch.setenv("NANOBOT_HOME", str(instance))
    set_config_path(instance / "config.json")
    assert get_instance_home() == instance
    assert get_config_path() == instance / "config.json"
    env = service.child_environment()
    for key in ("CODEX_HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "TEMP"):
        assert Path(env[key]).is_relative_to(service.root)


def test_opencode_result_excludes_tool_events(service):
    directory = service.root / "tasks" / "event-test"
    directory.mkdir()
    events = [{"type": "tool_use", "part": {"text": "内部命令"}},
              {"type": "text", "part": {"text": "完成了工作"}}]
    (directory / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    assert worker.extract_result("opencode", directory) == "完成了工作"


def test_cli_argv_uses_stdin_and_preserves_sandbox(service, monkeypatch):
    group = service.create("参数")
    task = service.submit(group["id"], "codex", "中文任务")
    monkeypatch.setattr(service, "executable", lambda _: sys.executable)
    args, stdin = worker.command_for(service, task, service.root)
    assert args[args.index("--sandbox") + 1] == "workspace-write"
    assert stdin.decode().endswith("中文任务")
    assert "中文任务" not in args
    assert not any("bypass" in arg for arg in args)
