"""Regression contracts for cancellation, event failures and retained context."""
import json
import subprocess
import sys
import threading
import time

import pytest

from nanobot.workgroups import worker
from nanobot.workgroups.config import WorkgroupsConfig
from nanobot.workgroups.service import WorkgroupService


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr('nanobot.config.loader._current_config_path', tmp_path / 'config.json')
    return WorkgroupService(WorkgroupsConfig(enable=True, storage_dir=str(tmp_path / 'groups')))


def test_large_prompt_can_be_cancelled_before_cli_reads_stdin(service, monkeypatch):
    group = service.create('取消大任务')
    task = service.submit(group['id'], 'codex', 'x' * 64000)
    task = service.claim()
    processes = []
    original_popen = subprocess.Popen

    def capture_process(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(worker.subprocess, 'Popen', capture_process)
    monkeypatch.setattr(worker, 'command_for', lambda *_: (
        [sys.executable, '-c', 'import time; time.sleep(60)'], task['prompt'].encode()))
    thread = threading.Thread(target=worker.execute, args=(service, task), daemon=True)
    thread.start()
    deadline = time.monotonic() + 3
    while not processes and time.monotonic() < deadline:
        time.sleep(.02)
    try:
        service.cancel(task['id'])
        thread.join(timeout=3)
        assert not thread.is_alive(), 'Writing a large stdin prompt blocked cancellation'
        assert service.task(task['id'])['status'] == 'cancelled'
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
        thread.join(timeout=3)


def test_opencode_failure_preserves_reason_and_partial_result(service, monkeypatch):
    group = service.create('错误事件')
    task = service.submit(group['id'], 'opencode', '执行任务')
    task = service.claim()
    events = [{'type': 'text', 'part': {'text': '正在处理'}},
              {'type': 'error', 'error': {'name': 'APIError', 'data': {'message': 'quota exceeded'}}}]
    script = 'import sys; print(sys.argv[1]); sys.exit(1)'
    monkeypatch.setattr(worker, 'command_for', lambda *_: (
        [sys.executable, '-c', script, '\n'.join(json.dumps(event) for event in events)], None))
    worker.execute(service, task)
    saved = service.task(task['id'])
    assert saved['status'] == 'failed'
    assert 'quota exceeded' in saved['error']
    assert '正在处理' in saved['result']


def test_queued_backlog_does_not_remove_recent_completed_context(service):
    group = service.create('上下文')
    completed = service.submit(group['id'], 'codex', '完成设计')
    service.finish(completed['id'], 'completed', '使用 PostgreSQL 保存数据')
    for _ in range(101):
        service.submit(group['id'], 'opencode', '等待处理')
    task = service.submit(group['id'], 'codex', '继续实现')
    assert '使用 PostgreSQL 保存数据' in worker.build_prompt(service, task)
