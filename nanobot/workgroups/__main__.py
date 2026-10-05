"""Local workgroup dashboard, agent worker, and isolated login helpers."""

from __future__ import annotations

import argparse
import base64
import hmac
import json
import re
import secrets
import subprocess
import webbrowser
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from urllib.parse import parse_qs, quote, urlparse

from markdown_it import MarkdownIt
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nanobot.config.loader import load_config, set_config_path
from nanobot.workgroups.assistant import MAX_FILE, AssistantService
from nanobot.workgroups.service import WorkgroupService
from nanobot.workgroups.worker import run_worker, tail


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateInput(Input):
    name: str = Field(min_length=1, max_length=100)
    workspace: str = ""
    members: list[str] | None = None


class SubmitInput(Input):
    group_id: str
    backend: str
    prompt: str = Field(min_length=1, max_length=64000)
    dependency: str = ""


class MemoryInput(Input):
    group_id: str
    memory: str = Field(max_length=16000)


class CancelInput(Input):
    task_id: str


class LoginInput(Input):
    token: str = Field(min_length=1, max_length=200)
    next: str = '/assistant'


class UploadInput(Input):
    filename: str = Field(min_length=1, max_length=200)
    content: str


class AssistantSettingsInput(Input):
    automatic: bool
    backend: str


class SummaryInput(Input):
    document_id: str
    backend: str


class QuestionInput(Input):
    question: str = Field(min_length=1, max_length=2000)
    backend: str


class PlanInput(Input):
    group_id: str
    goal: str = Field(min_length=1, max_length=6000)
    backend: str


class PlanControlInput(Input):
    plan_id: str
    action: str
    notes: str = Field(default='', max_length=8000)


def note_page(document: dict) -> bytes:
    if not document['summary']:
        raise ValueError('资料尚未整理，请先点击“用模型整理”')
    # Raw HTML and embedded images are data, never executable markup or requests.
    markdown = MarkdownIt('commonmark', {'html': False}).enable('table').disable('image')
    template = Template(Path(__file__).with_name('note.html').read_text(encoding='utf-8'))
    return template.substitute(
        title=escape(document['title']), category=escape(document['category']),
        tags=escape(' · '.join(document['tags'])), body=markdown.render(document['summary']),
        source=escape(Path(document['origin']).name), document_id=quote(document['id'], safe=''),
    ).encode('utf-8')


def create_server(service: WorkgroupService, config_path: Path, port: int) -> ThreadingHTTPServer:
    assistant = AssistantService(service)
    token_file = service.root / "dashboard.token"
    if not token_file.exists():
        token_file.write_text(secrets.token_urlsafe(32), encoding="ascii")
    token = token_file.read_text(encoding="ascii").strip()
    host = f"127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass  # Request paths may contain the initial login token.

        def send_json(self, value: object, status: int = 200) -> None:
            data = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def authorized(self) -> bool:
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except ValueError:
                return False
            return "workgroups" in cookie and hmac.compare_digest(cookie["workgroups"].value, token)

        def send_page(self, page: str, data: bytes | None = None) -> None:
            if data is None:
                data = Path(__file__).with_name(page).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(data)

        def login_cookie(self) -> str:
            return f'workgroups={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000'

        def do_GET(self) -> None:
            if self.headers.get("Host") != host:
                self.send_json({"error": "Invalid host"}, 403)
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in ('/favicon.ico', '/app-icon.png'):
                filename, content_type = ('icon-transparent.ico', 'image/x-icon') if url.path == '/favicon.ico' else ('icon.png', 'image/png')
                data = Path(__file__).with_name(filename).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(data)
                return
            if url.path == "/" and hmac.compare_digest(query.get("token", [""])[0], token):
                self.send_response(303)
                destination = query.get('next', ['/'])[0]
                self.send_header("Location", destination if destination in ('/', '/assistant') else '/')
                self.send_header("Set-Cookie", self.login_cookie())
                self.send_header("Cache-Control", "no-store")
                self.send_header('Referrer-Policy', 'no-referrer')
                self.end_headers()
                return
            if url.path == '/login' or (url.path in ('/', '/assistant', '/task', '/note') and not self.authorized()):
                self.send_page('login.html')
                return
            if not self.authorized():
                self.send_json({"error": "请登录个人工作台", "login_url": "/login"}, 401)
                return
            if url.path in ("/", "/assistant", '/task'):
                page = {'/': 'dashboard.html', '/assistant': 'assistant.html', '/task': 'task.html'}[url.path]
                self.send_page(page)
            elif url.path == "/api/state":
                selected = query.get("group", [""])[0]
                try:
                    self.send_json({"groups": service.groups(), "tasks": service.tasks(selected) if selected else [],
                                    "backends": service.backends(), "storage": str(service.root),
                                    "allowed_roots": [str(p) for p in service.allowed_roots]})
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, 400)
            elif url.path == '/api/assistant/state':
                self.send_json(assistant.state())
            elif url.path == '/note':
                try:
                    self.send_page('note.html', note_page(assistant.document(query.get('id', [''])[0])))
                except (ValueError, OSError) as exc:
                    self.send_json({'error': str(exc)}, 400)
            elif url.path == '/api/task':
                try:
                    self.send_json(service.task(query.get('id', [''])[0]))
                except ValueError as exc:
                    self.send_json({'error': str(exc)}, 400)
            elif url.path == '/api/task-log':
                try:
                    task = service.task(query.get('id', [''])[0])
                    filename = query.get('file', [''])[0]
                    if filename not in ('events.jsonl', 'stderr.log', 'result.md'):
                        raise ValueError('Unknown log')
                    self.send_json({'text': tail(service.root / 'tasks' / task['id'] / filename)})
                except ValueError as exc:
                    self.send_json({'error': str(exc)}, 400)
            elif url.path == '/api/assistant/search':
                self.send_json(assistant.search(query.get('q', [''])[0][:2000]))
            elif url.path in ('/api/assistant/source', '/api/assistant/note'):
                try:
                    document = assistant.document(query.get('id', [''])[0])
                    path = Path(document['source']) if url.path.endswith('/source') else assistant.root / 'library' / (document['id'] + '.md')
                    # Database paths originate only from the fixed internal source store.
                    if not path.resolve().is_relative_to(assistant.root.resolve()):
                        raise ValueError('Invalid document path')
                    data = path.read_bytes()
                    self.send_response(200)
                    original = url.path.endswith('/source')
                    label = '原始资料' if original else '整理笔记'
                    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', document['title'])[:100] + '-' + label + path.suffix
                    fallback = document['id'] + ('-source' if original else '-note') + path.suffix
                    self.send_header('Content-Type', 'application/octet-stream')
                    self.send_header('Content-Disposition', f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}')
                    self.send_header('Content-Length', str(len(data)))
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(data)
                except (ValueError, OSError) as exc:
                    self.send_json({'error': str(exc)}, 400)
            else:
                self.send_json({"error": "Not found"}, 404)

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            if self.headers.get("Host") != host or (route != '/auth/login' and not self.authorized()):
                self.send_json({"error": "Unauthorized"}, 403)
                return
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                self.send_json({"error": "Cross-origin request denied"}, 403)
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.send_json({"error": "Expected application/json"}, 400)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 12 * 1024 * 1024 if route == '/api/assistant/upload' else 300000
                if route == '/auth/login':
                    limit = 2048
                if not 0 < length <= limit:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                if route == '/auth/login':
                    request = LoginInput.model_validate(data)
                    if not hmac.compare_digest(request.token.strip(), token):
                        self.send_json({'error': '访问码不正确，请使用桌面入口或核对本机访问码。'}, 401)
                        return
                    payload = json.dumps({'next': request.next if request.next in ('/', '/assistant') else '/assistant'}).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(payload)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Set-Cookie', self.login_cookie())
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                elif route == "/api/groups":
                    request = CreateInput.model_validate(data)
                    result = service.create(request.name, request.workspace, request.members)
                elif route == "/api/tasks":
                    request = SubmitInput.model_validate(data)
                    result = service.submit(request.group_id, request.backend, request.prompt, request.dependency)
                    service.start_worker(config_path)
                elif route == "/api/memory":
                    request = MemoryInput.model_validate(data)
                    result = service.set_memory(request.group_id, request.memory)
                elif route == "/api/cancel":
                    request = CancelInput.model_validate(data)
                    result = service.cancel(request.task_id)
                elif route == '/api/assistant/upload':
                    request = UploadInput.model_validate(data)
                    if len(request.content) > (MAX_FILE * 4 // 3 + 4):
                        raise ValueError('单文件最多 8 MB')
                    result = assistant.upload(request.filename, base64.b64decode(request.content, validate=True))
                elif route == '/api/assistant/scan':
                    Input.model_validate(data)
                    result = assistant.scan()
                elif route == '/api/assistant/settings':
                    request = AssistantSettingsInput.model_validate(data)
                    result = assistant.configure(request.automatic, request.backend)
                    service.start_worker(config_path)
                elif route == '/api/assistant/summarize':
                    request = SummaryInput.model_validate(data)
                    result = assistant.summarize(request.document_id, request.backend)
                    service.start_worker(config_path)
                elif route == '/api/assistant/ask':
                    request = QuestionInput.model_validate(data)
                    result = assistant.ask(request.question, request.backend)
                    service.start_worker(config_path)
                elif route == '/api/assistant/plan':
                    request = PlanInput.model_validate(data)
                    result = assistant.create_plan(request.group_id, request.goal, request.backend)
                    service.start_worker(config_path)
                elif route == '/api/assistant/plan-control':
                    request = PlanControlInput.model_validate(data)
                    result = assistant.control_plan(request.plan_id, request.action, request.notes)
                    service.start_worker(config_path)
                else:
                    self.send_json({"error": "Not found"}, 404)
                    return
                self.send_json(result)
            except (ValueError, TypeError, OSError, ValidationError) as exc:
                self.send_json({"error": str(exc)}, 400)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def serve(service: WorkgroupService, config_path: Path, port: int, open_browser: bool = False) -> None:
    server = create_server(service, config_path, port)
    token = (service.root / 'dashboard.token').read_text(encoding='ascii').strip()
    host = f'127.0.0.1:{port}'
    service.start_worker(config_path)  # Resume queued work when the dashboard restarts.
    print(f"工作群组登录链接：http://{host}/?token={token}", flush=True)
    print(f"数据目录：{service.root}\nCtrl+C 关闭网页服务。执行队列独立运行。", flush=True)
    if open_browser:
        webbrowser.open(f"http://{host}/?token={token}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="nanobot personal workgroups")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("mode", choices=["serve", "worker", "codex-login", "opencode-login", "doctor"])
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    set_config_path(args.config)
    config = load_config(args.config)
    if not config.tools.workgroups.enable:
        parser.error("Enable tools.workgroups in your nanobot config")
    service = WorkgroupService(config.tools.workgroups)
    if args.mode == "worker":
        run_worker(service)
    elif args.mode == "serve":
        serve(service, args.config, args.port, args.open_browser)
    elif args.mode == "doctor":
        print(json.dumps({"storage": str(service.root), "backends": service.backends()}, ensure_ascii=False, indent=2))
    else:
        backend = "codex" if args.mode == "codex-login" else "opencode"
        command = [service.executable(backend)] + (["login"] if backend == "codex" else ["auth", "login"])
        raise SystemExit(subprocess.call(command, env=service.child_environment()))


if __name__ == "__main__":
    main()
