"""Entry point for the Windows shortcut; errors remain visible without a terminal."""
import contextlib
import os
import sys
from pathlib import Path


def main():
    if sys.argv[1:] not in ([], ['nanobot-workgroups://open'], ['nanobot-workgroups://open/']):
        raise ValueError('Unsupported desktop launch request')
    project = Path(__file__).resolve().parent.parent
    data = project / 'personal-data'
    data.mkdir(exist_ok=True)
    os.environ['NANOBOT_HOME'] = str(data)
    os.environ['PYTHONUTF8'] = '1'
    with (data / 'desktop-launcher.log').open('a', encoding='utf-8') as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            from setup_personal import main as setup

            from nanobot.config.loader import load_config, set_config_path
            from nanobot.workgroups.desktop import open_desktop
            from nanobot.workgroups.service import WorkgroupService
            setup()
            config_path = data / 'config.json'
            set_config_path(config_path)
            open_desktop(WorkgroupService(load_config(config_path).tools.workgroups), config_path)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if os.name == 'nt':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(exc), 'nanobot 工作台启动失败', 0x10)
        else:
            raise
