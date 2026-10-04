"""Durable group/task store; execution belongs to the worker, never to the UI."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict, cast

from nanobot.config.paths import get_data_dir
from nanobot.workgroups.config import WorkgroupsConfig

BACKENDS = ("codex", "opencode")
TERMINAL = ("completed", "failed", "cancelled", "interrupted")


class GroupRecord(TypedDict):
    id: str
    name: str
    workspace: str
    members: list[str]
    memory: str
    created: float


class TaskRecord(TypedDict):
    id: str
    group_id: str
    backend: str
    prompt: str
    status: str
    result: str
    error: str
    dependency: str | None
    created: float
    started: float | None
    finished: float | None
    cancel_requested: int


class WorkgroupService:
    def __init__(self, config: WorkgroupsConfig):
        self.config = config
        self.root = Path(config.storage_dir).expanduser().resolve() if config.storage_dir else get_data_dir() / "workgroups"
        self.root.mkdir(parents=True, exist_ok=True)
        self.allowed_roots = [Path(p).expanduser().resolve() for p in config.allowed_workspace_roots] or [self.root / "projects"]
        for directory in ("projects", "tasks", "runtime", "tmp"):
            (self.root / directory).mkdir(exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, workspace TEXT NOT NULL,
                    members TEXT NOT NULL, memory TEXT NOT NULL DEFAULT '', created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id),
                    backend TEXT NOT NULL, prompt TEXT NOT NULL, status TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    dependency TEXT REFERENCES tasks(id), created REAL NOT NULL,
                    started REAL, finished REAL, cancel_requested INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS task_group ON tasks(group_id, created);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "groups.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def check_workspace(self, workspace: str | Path) -> Path:
        path = Path(workspace).expanduser().resolve()
        if not any(path.is_relative_to(root) for root in self.allowed_roots):
            raise ValueError("Project directory is outside configured allowedWorkspaceRoots")
        return path

    def create(self, name: str, workspace: str = "", members: list[str] | None = None) -> GroupRecord:
        name = name.strip()
        members = members if members is not None else list(BACKENDS)
        if not name or len(name) > 100:
            raise ValueError("Group name must contain 1–100 characters")
        if not members or len(members) != len(set(members)) or any(m not in BACKENDS for m in members):
            raise ValueError("Members must be a non-empty unique list of codex/opencode")
        group_id = uuid.uuid4().hex
        path = self.check_workspace(workspace or self.root / "projects" / group_id)
        path.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("INSERT INTO groups(id,name,workspace,members,created) VALUES(?,?,?,?,?)",
                       (group_id, name, str(path), json.dumps(members), time.time()))
        return self.group(group_id)

    def group(self, group_id: str) -> GroupRecord:
        with self.connect() as db:
            row = db.execute("SELECT * FROM groups WHERE id=?", (group_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown group")
        group = dict(row)
        group["members"] = json.loads(group["members"])
        # Rows come only from our schema and validated mutation methods.
        return cast(GroupRecord, group)

    def groups(self) -> list[GroupRecord]:
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM groups ORDER BY created DESC")]
        return [self.group(group_id) for group_id in ids]

    def set_memory(self, group_id: str, memory: str) -> GroupRecord:
        self.group(group_id)
        if len(memory) > 16000:
            raise ValueError("Group memory exceeds 16000 characters")
        with self.connect() as db:
            db.execute("UPDATE groups SET memory=? WHERE id=?", (memory, group_id))
        return self.group(group_id)

    def submit(self, group_id: str, backend: str, prompt: str, dependency: str = "") -> TaskRecord:
        group = self.group(group_id)
        self.check_workspace(str(group["workspace"]))
        if backend not in group["members"]:
            raise ValueError("This backend is not a member of the group")
        prompt = prompt.strip()
        if not prompt or len(prompt) > 64000:
            raise ValueError("Task must contain 1–64000 characters")
        if dependency and self.task(dependency)["group_id"] != group_id:
            raise ValueError("Predecessor task must belong to the same group")
        task_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO tasks(id,group_id,backend,prompt,status,dependency,created) VALUES(?,?,?,?,?,?,?)",
                       (task_id, group_id, backend, prompt, "queued", dependency or None, time.time()))
        return self.task(task_id)

    def task(self, task_id: str) -> TaskRecord:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown task")
        return cast(TaskRecord, dict(row))

    def tasks(self, group_id: str) -> list[TaskRecord]:
        self.group(group_id)
        with self.connect() as db:
            return [cast(TaskRecord, dict(row)) for row in db.execute("SELECT * FROM tasks WHERE group_id=? ORDER BY created DESC LIMIT 100", (group_id,))]

    def cancel(self, task_id: str) -> TaskRecord:
        self.task(task_id)
        with self.connect() as db:
            db.execute("UPDATE tasks SET cancel_requested=1 WHERE id=? AND status NOT IN ('completed','failed','cancelled','interrupted')", (task_id,))
            db.execute("UPDATE tasks SET status='cancelled',finished=? WHERE id=? AND status='queued'", (time.time(), task_id))
        return self.task(task_id)

    def claim(self) -> TaskRecord | None:
        # Only the process holding worker.lock may call this. All groups share a
        # serial writer queue, including groups that point at the same project.
        with self.connect() as db:
            for row in db.execute("SELECT * FROM tasks WHERE status='queued' ORDER BY created"):
                task = cast(TaskRecord, dict(row))
                if task["dependency"]:
                    parent = db.execute("SELECT status FROM tasks WHERE id=?", (task["dependency"],)).fetchone()
                    if parent[0] not in TERMINAL:
                        continue
                    if parent[0] != "completed":
                        db.execute("UPDATE tasks SET status='failed',error='Predecessor did not complete',finished=? WHERE id=?", (time.time(), task["id"]))
                        continue
                db.execute("UPDATE tasks SET status='running',started=? WHERE id=?", (time.time(), task["id"]))
                return task
        return None

    def finish(self, task_id: str, status: str, result: str = "", error: str = "") -> None:
        with self.connect() as db:
            db.execute("UPDATE tasks SET status=?,result=?,error=?,finished=? WHERE id=?",
                       (status, result[-32000:], error[-4000:], time.time(), task_id))

    def recover(self) -> None:
        # Never automatically replay a task that may already have changed files.
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='interrupted',error='Worker restarted; inspect files before resubmitting',finished=? WHERE status='running'", (time.time(),))

    def executable(self, backend: str) -> str:
        command = self.config.codex_command if backend == "codex" else self.config.opencode_command
        resolved = shutil.which(command)
        if not resolved:
            raise ValueError(f"{backend} executable not found; configure {backend}Command")
        if os.name == "nt" and Path(resolved).suffix.lower() in (".cmd", ".bat", ".ps1"):
            raise ValueError(f"Configure the native {backend}.exe instead of a shell wrapper")
        return resolved

    def backends(self) -> list[dict[str, object]]:
        results = []
        for backend in BACKENDS:
            try:
                path = self.executable(backend)
                results.append({"name": backend, "available": True, "command": path})
            except ValueError as exc:
                results.append({"name": backend, "available": False, "error": str(exc)})
        return results

    def child_environment(self) -> dict[str, str]:
        env = os.environ.copy()
        paths = {
            "NANOBOT_HOME": get_data_dir(),
            "CODEX_HOME": self.root / "runtime" / "codex",
            "XDG_DATA_HOME": self.root / "runtime" / "xdg-data",
            "XDG_CONFIG_HOME": self.root / "runtime" / "xdg-config",
            "XDG_CACHE_HOME": self.root / "runtime" / "xdg-cache",
            "XDG_STATE_HOME": self.root / "runtime" / "xdg-state",
            "OPENCODE_CONFIG_DIR": self.root / "runtime" / "xdg-config" / "opencode",
            "TEMP": self.root / "tmp", "TMP": self.root / "tmp",
            "TMPDIR": self.root / "tmp",
            "PIP_CACHE_DIR": self.root / "runtime" / "cache" / "pip",
            "UV_CACHE_DIR": self.root / "runtime" / "cache" / "uv",
            "TIKTOKEN_CACHE_DIR": self.root / "runtime" / "cache" / "tiktoken",
            "npm_config_cache": self.root / "runtime" / "cache" / "npm",
            "BUN_INSTALL_CACHE_DIR": self.root / "runtime" / "cache" / "bun",
        }
        for key, path in paths.items():
            path.mkdir(parents=True, exist_ok=True)
            env[key] = str(path)
        env["PYTHONUTF8"] = "1"
        env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
        env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"permission": {"external_directory": "deny"}})
        return env

    def start_worker(self, config_path: Path) -> None:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with (self.root / "worker.log").open("ab") as log:
            subprocess.Popen([sys.executable, "-m", "nanobot.workgroups", "--config", str(config_path), "worker"],
                             stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                             env=self.child_environment(), creationflags=flags)
