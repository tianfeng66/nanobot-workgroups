"""Local workgroup dashboard, agent worker, and isolated login helpers."""

from __future__ import annotations

import argparse
import hmac
import json
import secrets
import subprocess
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nanobot.config.loader import load_config, set_config_path
from nanobot.workgroups.service import WorkgroupService
from nanobot.workgroups.worker import run_worker


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


def serve(service: WorkgroupService, config_path: Path, port: int, open_browser: bool = False) -> None:
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

        def do_GET(self) -> None:
            if self.headers.get("Host") != host:
                self.send_json({"error": "Invalid host"}, 403)
                return
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/" and hmac.compare_digest(query.get("token", [""])[0], token):
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"workgroups={token}; HttpOnly; SameSite=Strict; Path=/")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return
            if not self.authorized():
                self.send_json({"error": "请从启动脚本输出的登录链接打开工作群组"}, 401)
                return
            if url.path == "/":
                data = Path(__file__).with_name("dashboard.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)
            elif url.path == "/api/state":
                selected = query.get("group", [""])[0]
                try:
                    self.send_json({"groups": service.groups(), "tasks": service.tasks(selected) if selected else [],
                                    "backends": service.backends(), "storage": str(service.root),
                                    "allowed_roots": [str(p) for p in service.allowed_roots]})
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, 400)
            else:
                self.send_json({"error": "Not found"}, 404)

        def do_POST(self) -> None:
            if self.headers.get("Host") != host or not self.authorized():
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
                if not 0 < length <= 300000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                route = urlparse(self.path).path
                if route == "/api/groups":
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
                else:
                    self.send_json({"error": "Not found"}, 404)
                    return
                self.send_json(result)
            except (ValueError, TypeError, OSError, ValidationError) as exc:
                self.send_json({"error": str(exc)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
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
