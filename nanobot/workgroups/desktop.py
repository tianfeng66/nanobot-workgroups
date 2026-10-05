"""Start the private local server once and open a browser application window."""
from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

from filelock import FileLock

from nanobot.workgroups.service import WorkgroupService


def server_ready(service: WorkgroupService, port: int) -> bool:
    token_path = service.root / 'dashboard.token'
    token = token_path.read_text(encoding='ascii').strip() if token_path.exists() else ''
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
    try:
        connection.request('GET', '/api/state', headers={'Cookie': 'workgroups=' + token})
        response = connection.getresponse()
        payload = response.read(4 * 1024 * 1024)
        if response.status != 200:
            raise RuntimeError(f'端口 {port} 已被其他服务占用，请先关闭其他实例。')
        state = json.loads(payload)
        if Path(state['storage']).resolve() != service.root:
            raise RuntimeError('此端口运行的是另一个安装目录，请先关闭另一个实例。')
        return True
    except (ConnectionRefusedError, TimeoutError, ConnectionResetError):
        return False
    finally:
        connection.close()


def ensure_server(service: WorkgroupService, config_path: Path, port: int = 8877,
                  timeout: float = 30) -> bool:
    """Return true only when this call started the server; serialize double-clicks."""
    with FileLock(service.root / 'desktop.lock', timeout=timeout + 5):
        if server_ready(service, port):
            return False
        environment = os.environ.copy()
        environment['PYTHONUTF8'] = '1'
        with (service.root / 'desktop-server.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'nanobot.workgroups', '--config', str(config_path),
                'serve', '--port', str(port)], env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if server_ready(service, port):
                return True
            if process.poll() is not None:
                raise RuntimeError('后台服务启动失败，请查看 personal-data/workgroups/desktop-server.log。')
            time.sleep(.15)
        raise RuntimeError('后台服务启动超时，请查看 personal-data/workgroups/desktop-server.log。')


def browser_executable() -> Path | None:
    # Use installed vendor browsers; no browser runtime download is required.
    for variable, relative in [('PROGRAMFILES(X86)', 'Microsoft/Edge/Application/msedge.exe'),
                               ('PROGRAMFILES', 'Microsoft/Edge/Application/msedge.exe'),
                               ('PROGRAMFILES', 'Google/Chrome/Application/chrome.exe'),
                               ('LOCALAPPDATA', 'Google/Chrome/Application/chrome.exe')]:
        if os.environ.get(variable):
            candidate = Path(os.environ[variable]) / relative
            if candidate.is_file():
                return candidate
    return None


def open_desktop(service: WorkgroupService, config_path: Path, port: int = 8877) -> None:
    ensure_server(service, config_path, port)
    token = (service.root / 'dashboard.token').read_text(encoding='ascii').strip()
    url = f'http://127.0.0.1:{port}/?' + urlencode({'token': token, 'next': '/assistant'})
    browser = browser_executable() if os.name == 'nt' else None
    if browser:
        subprocess.Popen([str(browser), '--app=' + url], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        webbrowser.open(url)
