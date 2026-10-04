"""Optional instance home override without changing the user's system home."""

import os
from pathlib import Path


def get_instance_home() -> Path:
    override = os.environ.get("NANOBOT_HOME")
    return Path(override).expanduser().resolve() if override else Path.home() / ".nanobot"
