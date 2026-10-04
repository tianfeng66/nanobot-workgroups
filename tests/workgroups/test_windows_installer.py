"""Exercise cache recovery through the real Windows installer and a local download."""
import hashlib
import json
import os
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows PowerShell installer')


@pytest.mark.parametrize('damaged_cache', [False, True])
def test_installer_recovers_from_incomplete_archive(tmp_path, damaged_cache):
    archive = tmp_path / 'payload.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('uv.exe', b'test executable; never executed')
    payload = archive.read_bytes()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            body = payload if damaged_cache or len(requests) > 1 else payload[:20]
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        installer = Path(__file__).resolve().parents[2] / 'install.ps1'
        (tmp_path / 'install.ps1').write_bytes(installer.read_bytes())
        (tmp_path / 'scripts').mkdir()
        (tmp_path / 'scripts' / 'windows-tools.json').write_text(json.dumps({'tools': [{
            'name': 'uv', 'version': 'fixture', 'output': 'uv.exe', 'entry': 'uv.exe',
            'url': f'http://127.0.0.1:{server.server_port}/tool.zip',
            'sha256': hashlib.sha256(payload).hexdigest(),
        }]}), encoding='ascii')
        cache = tmp_path / '.uv-cache' / 'uv-fixture.zip'
        if damaged_cache:
            cache.parent.mkdir()
            cache.write_bytes(payload[:20])
        # A PowerShell 7 parent can leak its modules into Windows PowerShell 5.
        env = {key: value for key, value in os.environ.items()
               if key.upper() not in ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'PSMODULEPATH')}

        def install():
            return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                   '-File', str(tmp_path / 'install.ps1'), '-ToolsOnly'],
                                  env=env, capture_output=True, timeout=45)

        if not damaged_cache:
            assert install().returncode != 0
            assert not cache.exists(), 'Incomplete download must not become the cached archive'
        result = install()
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        assert cache.read_bytes() == payload
        assert (tmp_path / 'bin' / 'uv.exe').read_bytes() == b'test executable; never executed'
        assert not cache.with_suffix('.zip.partial').exists()
        count = len(requests)
        assert install().returncode == 0
        assert len(requests) == count, 'A verified cache must avoid another download'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
