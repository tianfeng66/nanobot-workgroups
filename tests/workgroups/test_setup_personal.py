"""Installation repairs removed CLI paths without overwriting valid customization."""
import importlib.util
import sys
from pathlib import Path

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.config.schema import Config


@pytest.mark.parametrize('valid_custom_command', [False, True])
def test_setup_repairs_only_missing_cli_paths(tmp_path, monkeypatch, valid_custom_command):
    script = Path(__file__).resolve().parents[2] / 'scripts' / 'setup_personal.py'
    spec = importlib.util.spec_from_file_location('setup_personal', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / 'scripts').mkdir()
    monkeypatch.setattr(module, '__file__', str(tmp_path / 'scripts' / 'setup_personal.py'))
    monkeypatch.setattr('nanobot.config.loader._current_config_path', None)
    (tmp_path / 'personal-data').mkdir()
    (tmp_path / 'bin').mkdir()
    for name in ('codex', 'opencode'):
        (tmp_path / 'bin' / f'{name}.exe').write_bytes(b'fixture; never executed')
    config_path = tmp_path / 'personal-data' / 'config.json'
    config = Config()
    command = sys.executable if valid_custom_command else str(tmp_path / 'removed-desktop-version' / 'codex.exe')
    config.tools.workgroups.codex_command = command
    config.tools.workgroups.opencode_command = command
    config.tools.workgroups.codex_model = 'custom-model'
    config.tools.workgroups.storage_dir = str(tmp_path / 'my-data')
    save_config(config, config_path)
    module.main()
    saved = load_config(config_path)
    assert saved.tools.workgroups.codex_command == (command if valid_custom_command else str(tmp_path / 'bin' / 'codex.exe'))
    assert saved.tools.workgroups.opencode_command == (command if valid_custom_command else str(tmp_path / 'bin' / 'opencode.exe'))
    assert saved.tools.workgroups.codex_model == 'custom-model'
    assert saved.tools.workgroups.storage_dir == str(tmp_path / 'my-data')
