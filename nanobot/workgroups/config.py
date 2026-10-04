"""Operator-owned configuration for workgroup execution."""

from pydantic import Field

from nanobot.config_base import Base


class WorkgroupsConfig(Base):
    enable: bool = False
    storage_dir: str = ""
    allowed_workspace_roots: list[str] = Field(default_factory=list)
    codex_command: str = "codex"
    opencode_command: str = "opencode"
    codex_model: str = ""
    opencode_model: str = ""
    task_timeout: int = Field(default=1800, ge=10, le=14400)
