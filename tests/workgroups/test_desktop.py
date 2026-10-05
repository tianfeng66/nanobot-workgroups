"""Browser login and real Windows background launch/shortcut contracts."""
import http.client
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.workgroups.__main__ import create_server
from nanobot.workgroups.desktop import ensure_server, server_ready
from nanobot.workgroups.service import WorkgroupService


@pytest.fixture
def desktop_service(tmp_path, monkeypatch):
    config_path = tmp_path / 'config.json'
    monkeypatch.setattr('nanobot.config.loader._current_config_path', config_path)
    config = Config()
    config.tools.workgroups.enable = True
    config.tools.workgroups.storage_dir = str(tmp_path / 'groups')
    save_config(config, config_path)
    return WorkgroupService(config.tools.workgroups), config_path


def test_browser_login_keeps_private_routes_guarded_and_rejects_cross_origin(desktop_service):
    service, config_path = desktop_service
    server = create_server(service, config_path, 0)
    # create_server accepts zero for test binding; its host guard needs the bound port.
    server.server_close()
    port = server.server_port
    server = create_server(service, config_path, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = (service.root / 'dashboard.token').read_text().strip()

    def request(method, path, payload=None, cookie='', origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        headers = {'Content-Type': 'application/json', 'Cookie': cookie}
        if origin:
            headers['Origin'] = origin
        connection.request(method, path, json.dumps(payload).encode() if payload else None, headers)
        response = connection.getresponse()
        result = response.status, response.read(), response.getheader('Set-Cookie')
        connection.close()
        return result

    try:
        status, page, _ = request('GET', '/assistant')
        assert status == 200 and '登录'.encode() in page and 'nanobot-workgroups://open'.encode() in page
        assert token.encode() not in page
        assert request('GET', '/api/assistant/state')[0] == 401
        assert request('POST', '/auth/login', {'token': token}, origin='https://evil.example')[0] == 403
        assert request('POST', '/auth/login', {'token': 'wrong'})[0] == 401
        status, result, cookie = request('POST', '/auth/login', {'token': token, 'next': 'https://evil.example'})
        assert status == 200 and json.loads(result)['next'] == '/assistant'
        assert 'HttpOnly' in cookie and 'SameSite=Strict' in cookie and 'Max-Age=2592000' in cookie
        assert request('GET', '/api/assistant/state', cookie=cookie.split(';')[0])[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows background processes and Job cleanup')
def test_desktop_starts_real_server_and_reuses_it_without_duplicate_worker(desktop_service, monkeypatch):
    import socket

    from nanobot.workgroups.windows_job import WindowsJob
    service, config_path = desktop_service
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        port = available.getsockname()[1]
    processes = []
    spawn = subprocess.Popen
    job = WindowsJob()

    def tracked_spawn(*args, **kwargs):
        process = spawn(*args, **kwargs)
        job.attach(int(process._handle))
        processes.append(process)
        return process

    monkeypatch.setattr('nanobot.workgroups.desktop.subprocess.Popen', tracked_spawn)
    try:
        assert ensure_server(service, config_path, port) is True
        assert server_ready(service, port)
        assert ensure_server(service, config_path, port) is False
        assert len(processes) == 1
        assert (service.root / 'desktop-server.log').exists()
    finally:
        job.terminate()
        job.close()
        for process in processes:
            process.wait(timeout=15)


def test_desktop_does_not_reuse_a_service_with_different_credentials(desktop_service):
    service, config_path = desktop_service
    server = create_server(service, config_path, 0)
    server.server_close()
    port = server.server_port
    server = create_server(service, config_path, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    (service.root / 'dashboard.token').write_text('different-client-credential')
    try:
        with pytest.raises(RuntimeError, match='端口'):
            ensure_server(service, config_path, port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows desktop shortcuts')
def test_windows_shortcut_points_to_hidden_launcher_in_installation_with_spaces(tmp_path):
    root = tmp_path / 'installation with spaces'
    (root / 'scripts').mkdir(parents=True)
    (root / '.venv/Scripts').mkdir(parents=True)
    (root / '.venv/Scripts/pythonw.exe').write_bytes(b'not executed')
    desktop = tmp_path / 'desktop'
    desktop.mkdir()
    installer = root / 'scripts/install_desktop.ps1'
    shutil.copy2(Path(__file__).resolve().parents[2] / 'scripts/install_desktop.ps1', installer)
    env = {key: value for key, value in os.environ.items() if key.upper() != 'PSMODULEPATH'}
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                             str(installer), '-DesktopDirectory', str(desktop), '-NoProtocol'],
                            env=env, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    links = list(desktop.glob('*.lnk'))
    assert len(links) == 1 and links[0].name == 'nanobot 个人工作台.lnk'
    # Read the actual shell shortcut; do not merely assert installer source text.
    inspect = "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($args[0]); @{target=$s.TargetPath; arguments=$s.Arguments; directory=$s.WorkingDirectory} | ConvertTo-Json -Compress"
    script = tmp_path / 'inspect.ps1'
    script.write_text(inspect, encoding='utf-8-sig')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-File', str(script), str(links[0])],
                            env=env, capture_output=True, timeout=15)
    assert result.returncode == 0
    values = json.loads(result.stdout.decode('utf-8-sig'))
    assert Path(values['target']) == root / '.venv/Scripts/pythonw.exe'
    assert values['arguments'] == '"' + str(root / 'scripts/desktop_launcher.py') + '"'
    assert Path(values['directory']) == root
