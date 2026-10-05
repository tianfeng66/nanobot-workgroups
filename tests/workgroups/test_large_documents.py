"""Large binary uploads, complete coverage, bounded merging and durable checkpoints."""
import hashlib
import http.client
import io
import json
import socket
import threading
from urllib.parse import quote

import pytest

from nanobot.workgroups.__main__ import create_server, note_page
from nanobot.workgroups.assistant import MAX_FILE, AssistantService
from nanobot.workgroups.config import WorkgroupsConfig
from nanobot.workgroups.service import WorkgroupService
from nanobot.workgroups.summaries import CHUNK_CHARS
from nanobot.workgroups.worker import build_prompt


@pytest.fixture
def large_assistant(tmp_path, monkeypatch):
    monkeypatch.setattr('nanobot.config.loader._current_config_path', tmp_path / 'config.json')
    return AssistantService(WorkgroupService(WorkgroupsConfig(enable=True, storage_dir=str(tmp_path / 'groups'))))


def large_pdf():
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    for number in range(1, 82):
        page = writer.add_blank_page(width=200, height=200)
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 20 100 Td (Budget page {number}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    # A valid embedded stream simulates a large PDF's binary assets.
    attachment = DecodedStreamObject()
    attachment.set_data(b'asset' * (2 * 1024 * 1024))
    writer._add_object(attachment)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_binary_upload_accepts_over_8mb_and_80_pages_with_auth_and_size_guards(large_assistant, tmp_path, monkeypatch):
    monkeypatch.setattr(large_assistant.service, 'start_worker', lambda *_: None)
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        port = available.getsockname()[1]
    server = create_server(large_assistant.service, tmp_path / 'config.json', port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = (large_assistant.service.root / 'dashboard.token').read_text().strip()
    def upload(payload, filename='长资料.pdf', authenticated=True, origin=None, length=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        headers = {'Content-Type': 'application/octet-stream'}
        if authenticated:
            headers['Cookie'] = 'workgroups=' + token
        if origin:
            headers['Origin'] = origin
        if length is not None:
            headers['Content-Length'] = str(length)
        connection.request('POST', '/api/assistant/upload-file?filename=' + quote(filename, safe=''), payload, headers)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result
    try:
        assert upload(b'x', authenticated=False)[0] == 403
        assert upload(b'x', origin='https://evil.example')[0] == 403
        assert upload(b'x', '../escape.txt')[0] == 400
        assert upload(b'', length=MAX_FILE + 1)[0] == 400
        payload = large_pdf()
        assert len(payload) > 8 * 1024 * 1024
        status, document = upload(payload)
        assert status == 200 and document['status'] == 'indexed'
        assert 'Budget page 81' in document['content'] and '[第 81 页]' in document['content']
        assert hashlib.sha256(open(document['source'], 'rb').read()).hexdigest() == hashlib.sha256(payload).hexdigest()
        assert large_assistant.settings()['limits']['file_bytes'] == MAX_FILE
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def finish_active(assistant, document_id):
    document = assistant.document(document_id)
    job = next(job for job in assistant.summary_jobs(document_id) if job['status'] == 'processing')
    prompt = assistant.service.task(document['task_id'])['prompt']
    assert len(prompt) <= 64000
    if job['kind'] == 'part':
        result = {'summary': f"本段证据 SECTION-{job['position']}，覆盖字符 {job['start_char']}–{job['end_char']}。"}
    elif job['kind'] == 'merge':
        children = json.loads(job['children'])
        jobs = assistant.summary_jobs(document_id)
        evidence = [json.loads(jobs[index]['result'])['summary'] for index in children]
        assert all(value in prompt for value in evidence)
        result = {'summary': '\n'.join(evidence)}
    else:
        assert 'SECTION-6' in prompt
        result = {'title': '全文笔记', 'category': '资料', 'tags': ['测试'], 'text': '',
                  'summary': '## 核心要点\n末尾的 TAIL_FACT=9876 也已覆盖。'}
    assistant.service.finish(document['task_id'], 'completed', json.dumps(result, ensure_ascii=False))
    AssistantService(assistant.service).tick()


def test_hierarchical_summary_covers_tail_beyond_old_limits_and_saves_every_part(large_assistant):
    content = ''.join(f'CHAPTER-{index}\n' + '正文' * (CHUNK_CHARS // 2) + '\n' for index in range(7)) + 'TAIL_FACT=9876'
    document = large_assistant.upload('long.md', content.encode())
    queued = large_assistant.summarize(document['id'], 'codex')
    parts = [job for job in large_assistant.summary_jobs(document['id']) if job['kind'] == 'part']
    assert len(parts) >= 7
    assert ''.join(document['content'][job['start_char']:job['end_char']] for job in parts) == content
    assert large_assistant.summarize(document['id'], 'codex')['task_id'] == queued['task_id']
    observed_tail = False
    while large_assistant.document(document['id'])['status'] == 'processing':
        current = large_assistant.document(document['id'])
        observed_tail |= 'TAIL_FACT=9876' in build_prompt(large_assistant.service, large_assistant.service.task(current['task_id']))
        finish_active(large_assistant, document['id'])
    saved = large_assistant.document(document['id'])
    assert saved['status'] == 'ready' and observed_tail
    assert saved['progress']['completed_parts'] == len(parts)
    assert saved['progress']['completed_calls'] == saved['progress']['calls']
    note = (large_assistant.root / 'library' / (document['id'] + '.md')).read_text(encoding='utf-8')
    assert '分段阅读笔记' in note and 'SECTION-6' in note and 'TAIL_FACT=9876' in note
    assert '查看逐段笔记'.encode() in note_page(saved)


def test_pause_and_worker_interruption_resume_without_repeating_completed_parts(large_assistant):
    document = large_assistant.upload('resume.md', ('正文' * CHUNK_CHARS).encode())
    first = large_assistant.summarize(document['id'], 'codex')
    large_assistant.service.finish(first['task_id'], 'completed', json.dumps({'summary': '第一段已完成'}))
    large_assistant.tick()
    paused_task = large_assistant.document(document['id'])['task_id']
    paused = large_assistant.cancel_summary(document['id'])
    assert paused['progress']['completed_parts'] == 1 and paused['progress']['resumable']
    assert large_assistant.service.task(paused_task)['cancel_requested'] == 1
    restarted = AssistantService(large_assistant.service)
    resumed = restarted.summarize(document['id'], 'opencode')
    assert resumed['task_id'] != paused_task
    assert restarted.summary_jobs(document['id'])[0]['task_id'] == first['task_id']
    assert restarted.service.task(resumed['task_id'])['backend'] == 'opencode'
    restarted.service.claim()
    restarted.service.recover()
    restarted.tick()
    assert restarted.document(document['id'])['status'] == 'error'
    retried = restarted.summarize(document['id'], 'opencode')
    assert retried['progress']['completed_parts'] == 1 and retried['task_id'] != resumed['task_id']
