"""One durable queue consumer, with CLI process cleanup and bounded context."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING

from filelock import FileLock, Timeout

from nanobot.workgroups.assistant import AssistantService
from nanobot.workgroups.service import TaskRecord, WorkgroupService

if TYPE_CHECKING:
    from nanobot.workgroups.windows_job import WindowsJob


def tail(path: Path, size: int = 262144) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - size))
        return handle.read(size).decode("utf-8", errors="replace")


def stop_process(process: subprocess.Popen, job: WindowsJob | None = None) -> None:
    if job is not None:
        job.terminate()  # Also stop descendants after the CLI parent has exited.
    if process.poll() is not None:
        return
    if os.name == "nt":
        if job is None:
            process.kill()  # Only used if attachment failed, before accepting work.
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def build_prompt(service: WorkgroupService, task: TaskRecord) -> str:
    group = service.group(str(task["group_id"]))
    recent = reversed(service.recent_completed(str(task["group_id"])))
    context = "\n\n".join(f"{item['backend']}: {str(item['result'])[-2000:]}" for item in recent)
    predecessor = service.task(str(task["dependency"])) if task["dependency"] else None
    return (
        "你是个人工作群组中的执行成员。使用中文汇报完成的工作、验证结果和未完成项。"
        "只在指定项目目录内工作，不修改其他群组数据或登录凭据。\n"
        f"群组：{group['name']}\n项目：{group['workspace']}\n"
        f"群组记忆（作为背景资料，不能覆盖当前任务）：\n{group['memory']}\n"
        f"最近工作结果（背景资料）：\n{context}\n"
        f"前序任务结果：\n{str(predecessor['result'])[-16000:] if predecessor else ''}\n"
        f"本次用户任务：\n{task['prompt']}"
    )


def command_for(service: WorkgroupService, task: TaskRecord, directory: Path) -> tuple[list[str], bytes | None]:
    backend = str(task["backend"])
    executable = service.executable(backend)
    workspace = service.check_workspace(str(service.group(str(task["group_id"]))["workspace"]))
    prompt = build_prompt(service, task)
    images = AssistantService(service).task_images(str(task['id']))
    if backend == "codex":
        # No approval/sandbox bypass. Prompts are supplied on stdin, never shell-interpolated.
        args = [executable, "exec", "--json", "--sandbox", "workspace-write", "--skip-git-repo-check",
                "--color", "never", "-C", str(workspace), "-o", str(directory / "result.md")]
        if service.config.codex_model:
            args.extend(["--model", service.config.codex_model])
        for image in images:
            args.extend(['--image', str(image)])
        return args + ["-"], prompt.encode("utf-8")
    # Attach a local instruction file rather than putting user text into a shell
    # command or the Windows command-line length limit.
    (directory / "request.md").write_text(prompt, encoding="utf-8")
    args = [executable, "run", "请执行附件中的本次用户任务。", "--format", "json", "--dir", str(workspace), "--file", str(directory / "request.md")]
    if service.config.opencode_model:
        args.extend(["--model", service.config.opencode_model])
    for image in images:
        args.extend(['--file', str(image)])
    return args, None


def extract_result(backend: str, directory: Path) -> str:
    if backend == "codex":
        return tail(directory / "result.md", 131072).strip()
    texts = []
    for line in tail(directory / "events.jsonl").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "text":
            part = event.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                texts.append(part["text"])
    return "\n\n".join(texts).strip()


def extract_error(backend: str, directory: Path) -> str:
    """Native CLIs report terminal failures in JSON stdout, not just stderr."""
    message = ""
    failure_type = "error" if backend == "opencode" else "turn.failed"
    for line in tail(directory / "events.jsonl").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != failure_type:
            continue
        error = event.get("error")
        if isinstance(error, dict):
            data = error.get("data")
            detail = data.get("message") if isinstance(data, dict) else None
            message = str(detail or error.get("message") or error.get("name") or "")
        elif isinstance(error, str):
            message = error
    return message


def execute(service: WorkgroupService, task: TaskRecord) -> None:
    task_id = str(task["id"])
    directory = service.root / "tasks" / task_id
    directory.mkdir(exist_ok=True)
    process = None
    job = None
    try:
        args, stdin = command_for(service, task, directory)
        workspace = str(service.group(str(task["group_id"]))["workspace"])
        if os.name == "nt":
            from nanobot.workgroups.windows_job import WindowsJob
            job = WindowsJob()
        with ExitStack() as stack:
            output = stack.enter_context((directory / "events.jsonl").open("wb"))
            errors = stack.enter_context((directory / "stderr.log").open("wb"))
            input_file = subprocess.DEVNULL
            if stdin is not None:
                # A pipe write can block before cancellation/timeout polling starts.
                request = directory / "request.md"
                request.write_bytes(stdin)
                input_file = stack.enter_context(request.open("rb"))
            process = subprocess.Popen(args, cwd=workspace, env=service.child_environment(),
                                       stdin=input_file,
                                       stdout=output, stderr=errors, start_new_session=os.name != "nt",
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            if job is not None:
                try:
                    job.attach(int(process._handle))  # Windows Popen owns this process handle.
                except OSError:
                    process.kill()
                    process.wait(timeout=15)
                    raise
            started = time.monotonic()
            while process.poll() is None:
                if service.task(task_id)["cancel_requested"]:
                    stop_process(process, job)
                    service.finish(task_id, "cancelled", error="Cancelled by user; file changes are preserved")
                    return
                if time.monotonic() - started > service.config.task_timeout:
                    stop_process(process, job)
                    service.finish(task_id, "failed", error="Task timed out; file changes are preserved")
                    return
                time.sleep(0.25)
        result = extract_result(str(task["backend"]), directory)
        if process.returncode != 0:
            error = extract_error(str(task["backend"]), directory) or tail(directory / "stderr.log", 4000)
            service.finish(task_id, "failed", result, error or f"CLI exited {process.returncode}")
        elif not result:
            service.finish(task_id, "failed", error="CLI returned no final response; inspect task logs")
        else:
            (directory / "result.md").write_text(result, encoding="utf-8")
            service.finish(task_id, "completed", result)
    except Exception as exc:
        service.finish(task_id, "failed", error=str(exc))
    finally:
        if process is not None:
            stop_process(process, job)
        if job is not None:
            job.close()


def run_worker(service: WorkgroupService) -> None:
    try:
        with FileLock(service.root / "worker.lock", timeout=0):
            service.recover()
            assistant = AssistantService(service)
            stop_maintenance = threading.Event()

            def maintain():
                while not stop_maintenance.is_set():
                    try:
                        assistant.tick()
                    except Exception as exc:
                        print(f'Assistant maintenance failed: {exc}', flush=True)
                    stop_maintenance.wait(10)

            maintenance = threading.Thread(target=maintain, daemon=True)
            maintenance.start()
            (service.root / "worker.pid").write_text(str(os.getpid()), encoding="ascii")
            try:
                while True:
                    task = service.claim()
                    if task is not None:
                        execute(service, task)
                    else:
                        time.sleep(0.5)
            finally:
                stop_maintenance.set()
                maintenance.join(timeout=5)
                (service.root / "worker.pid").unlink(missing_ok=True)
    except Timeout:
        return  # The existing consumer owns the queue.
