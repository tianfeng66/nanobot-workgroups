"""Natural-language access to persistent personal workgroups."""

# pyright: reportIncompatibleMethodOverride=false
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nanobot.agent.tools.base import Tool, ToolResult
from nanobot.agent.tools.context import ToolContext
from nanobot.config.loader import get_config_path
from nanobot.security.workspace_access import current_tool_workspace
from nanobot.workgroups.config import WorkgroupsConfig
from nanobot.workgroups.service import WorkgroupService


class WorkgroupsTool(Tool):
    config_key = "workgroups"

    @classmethod
    def config_cls(cls):
        return WorkgroupsConfig

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.workgroups.enable

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        return cls(ctx.config.workgroups, Path(ctx.workspace), ctx.config.restrict_to_workspace)

    def __init__(self, config: WorkgroupsConfig, workspace: Path, restricted: bool):
        self.service = WorkgroupService(config)
        self.workspace = workspace
        self.restricted = restricted

    @property
    def name(self) -> str:
        return "workgroup"

    @property
    def description(self) -> str:
        return (
            "Create/list personal workgroups, manage their shared memory, and delegate user-authorized "
            "tasks to installed Codex/OpenCode CLIs. submit queues a task and returns its ID immediately; "
            "use status to retrieve actual completion/results. Never claim queued work has completed. "
            "A dependency task ID runs this task after the predecessor succeeds, including its result. "
            "memory replaces the group's durable notes. CLI credentials must be configured by the user."
        )

    @property
    def parameters(self):
        return {
            "type": "object", "required": ["action"], "additionalProperties": False,
            "properties": {
                "action": {"type": "string", "enum": ["create", "list", "submit", "status", "cancel", "memory"]},
                "group_id": {"type": "string"}, "task_id": {"type": "string"},
                "name": {"type": "string"}, "workspace": {"type": "string"},
                "members": {"type": "array", "items": {"type": "string", "enum": ["codex", "opencode"]}},
                "backend": {"type": "string", "enum": ["codex", "opencode"]},
                "text": {"type": "string"}, "dependency": {"type": "string"},
            },
        }

    def _check_access(self, workspace: str) -> None:
        access = current_tool_workspace(self.workspace, restrict_to_workspace=self.restricted)
        root = access.allowed_root
        if root is not None and not Path(workspace).resolve().is_relative_to(root.resolve()):
            raise ValueError("Group project is outside the current request workspace")

    async def execute(self, action: str, group_id: str = "", task_id: str = "", name: str = "",
                      workspace: str = "", members: list[str] | None = None,
                      backend: str = "codex", text: str = "", dependency: str = "") -> str:
        def operation():
            if action == "create":
                access = current_tool_workspace(self.workspace, restrict_to_workspace=self.restricted)
                target = workspace or str(access.project_path or self.workspace)
                self._check_access(target)
                return self.service.create(name, target, members)
            if action == "list":
                visible = []
                for group in self.service.groups():
                    try:
                        self._check_access(str(group["workspace"]))
                    except ValueError:
                        continue
                    visible.append(group)
                return visible
            if task_id:
                task = self.service.task(task_id)
                selected = str(task["group_id"])
            else:
                selected = group_id
            group = self.service.group(selected)
            self._check_access(str(group["workspace"]))
            if action == "submit":
                task = self.service.submit(selected, backend, text, dependency)
                self.service.start_worker(get_config_path())
                return task
            if action == "status":
                return self.service.task(task_id) if task_id else {"group": group, "tasks": self.service.tasks(selected)}
            if action == "cancel":
                return self.service.cancel(task_id)
            if action == "memory":
                return self.service.set_memory(selected, text)
            raise ValueError("Unknown action")
        try:
            return json.dumps(await asyncio.to_thread(operation), ensure_ascii=False)
        except (ValueError, OSError) as exc:
            return ToolResult.error(str(exc))
