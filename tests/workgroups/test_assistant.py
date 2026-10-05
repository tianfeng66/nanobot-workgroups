"""Inbox durability, evidence-backed answers and explicitly reviewed project execution."""
import base64
import http.client
import json
import socket
import threading

import pytest

from nanobot.workgroups.__main__ import create_server, note_page
from nanobot.workgroups.assistant import AssistantService
from nanobot.workgroups.config import WorkgroupsConfig
from nanobot.workgroups.service import WorkgroupService
from nanobot.workgroups.worker import build_prompt, command_for


@pytest.fixture
def assistant(tmp_path, monkeypatch):
    monkeypatch.setattr('nanobot.config.loader._current_config_path', tmp_path / 'config.json')
    service = WorkgroupService(WorkgroupsConfig(enable=True, storage_dir=str(tmp_path / 'groups')))
    return AssistantService(service)


def complete_summary(assistant, document):
    queued = assistant.summarize(document['id'], 'codex')
    assistant.service.finish(queued['task_id'], 'completed', json.dumps({
        'title': '智能体笔记', 'category': '技术研究', 'summary': 'Codex 负责实现，OpenCode 负责检查。',
        'tags': ['智能体', '开发'], 'text': '',
    }, ensure_ascii=False))
    assistant.tick()
    return assistant.document(document['id'])


def make_plan(assistant):
    group = assistant.service.create('项目组')
    plan = assistant.create_plan(group['id'], '完成并检查工具', 'codex')
    assistant.service.finish(plan['task_id'], 'completed', json.dumps({'steps': [
        {'title': '实现', 'instruction': '实现并验证', 'backend': 'codex'},
        {'title': '检查', 'instruction': '读取前序并检查', 'backend': 'opencode'},
    ]}))
    assistant.tick()
    return assistant.plan(plan['id'])


def test_inbox_deduplicates_and_writes_obsidian_note_without_moving_original(assistant):
    document = assistant.upload('智能体.md', '# 方案\nCodex 实现，OpenCode 检查。'.encode())
    assert assistant.upload('副本.md', '# 方案\nCodex 实现，OpenCode 检查。'.encode())['id'] == document['id']
    assert len(assistant.state()['documents']) == 1
    saved = complete_summary(assistant, document)
    assert saved['status'] == 'ready'
    assert (assistant.root / 'inbox' / '智能体.md').exists()
    assert 'Codex 负责实现' in (assistant.root / 'library' / (document['id'] + '.md')).read_text(encoding='utf-8')
    note = (assistant.root / 'library' / (document['id'] + '.md')).read_text(encoding='utf-8')
    assert '## 提取文字' not in note and '# 方案' not in note
    assert assistant.document(document['id'])['content'].startswith('# 方案')
    restarted = AssistantService(assistant.service)
    assert restarted.document(document['id'])['summary'] == saved['summary']


def test_changed_source_keeps_old_citation_snapshot_and_indexes_new_version(assistant):
    old = assistant.upload('notes.md', b'Project uses SQLite.')
    complete_summary(assistant, old)
    (assistant.root / 'inbox' / 'notes.md').write_text('Project now uses PostgreSQL.', encoding='utf-8')
    assistant.scan()
    assert assistant.document(old['id'])['status'] == 'superseded'
    assert 'SQLite' in open(assistant.document(old['id'])['source'], encoding='utf-8').read()
    assert assistant.search('PostgreSQL')[0]['id'] != old['id']
    assert not assistant.search('SQLite')
    with pytest.raises(ValueError):
        assistant.summarize(old['id'], 'codex')
    (assistant.root / 'inbox' / 'notes.md').write_bytes(b'Project uses SQLite.')
    assistant.scan()
    assert assistant.search('SQLite')[0]['id'] == old['id']
    assert assistant.document(old['id'])['status'] == 'ready'
    assert not assistant.search('PostgreSQL')


@pytest.mark.parametrize('filename', ['../escape.md', 'C:\\escape.md', 'nested\\escape.md', 'auth.json'])
def test_upload_cannot_write_arbitrary_paths_or_unsupported_files(assistant, filename):
    with pytest.raises(ValueError):
        assistant.upload(filename, b'example')


def test_word_html_and_pdf_extraction_have_readable_content(assistant, tmp_path):
    from docx import Document
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    docx = Document()
    docx.add_paragraph('项目预算为 300 元。')
    docx_path = tmp_path / 'input.docx'
    docx.save(docx_path)
    assert '300' in assistant.upload('input.docx', docx_path.read_bytes())['content']
    html = assistant.upload('web.html', b'<h1>Budget</h1><p>300</p><script>ignore-this</script>')
    assert 'Budget' in html['content'] and 'ignore-this' not in html['content']
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 20 100 Td (Budget 300) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    pdf = tmp_path / 'input.pdf'
    writer.write(pdf)
    assert 'Budget 300' in assistant.upload('input.pdf', pdf.read_bytes())['content']
    assert assistant.upload('broken.pdf', b'not a PDF')['status'] == 'error'
    writer.encrypt('test-password')
    writer.write(pdf)
    encrypted = assistant.upload('encrypted.pdf', pdf.read_bytes())
    assert encrypted['status'] == 'error' and '已加密' in encrypted['error']


def test_images_are_attached_to_native_cli_summary_tasks(assistant, monkeypatch):
    monkeypatch.setattr(assistant.service, 'executable', lambda _: 'native.exe')
    document = assistant.upload('capture.png', base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jR0kAAAAASUVORK5CYII='))
    document = assistant.summarize(document['id'], 'codex')
    task = assistant.service.task(document['task_id'])
    args, _ = command_for(assistant.service, task, assistant.root)
    assert args[args.index('--image') + 1] == document['source']


def test_new_document_and_question_do_not_receive_other_documents_or_group_memory(assistant):
    first = assistant.upload('first.md', '无关资料：火星种植实验。'.encode())
    complete_summary(assistant, first)
    second = assistant.upload('second.md', '预算方案：预算 300 元，分两阶段实施。'.encode())
    queued = assistant.summarize(second['id'], 'codex')
    task = assistant.service.task(queued['task_id'])
    assistant.service.set_memory(task['group_id'], '无关的火星研究结果')
    prompt = build_prompt(assistant.service, task)
    assert '预算 300 元' in prompt and '火星' not in prompt and 'Codex 负责实现' not in prompt
    question = assistant.ask('预算方案', 'codex')
    assert '火星' not in build_prompt(assistant.service, assistant.service.task(question['task_id']))


def test_pdf_print_footers_are_removed_but_original_page_numbers_and_body_are_preserved(assistant, tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    for number in (1, 2):
        page = writer.add_blank_page(width=300, height=400)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        lines = ['2026/10/5 11:21 Printed article', f'Part {number}', 'Context', 'Important repeated evidence',
                 f'Budget {number * 300}', 'End of body', '2026/10/5 11:21 Printed article', f'https://example.com/article {number}/2']
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 20 350 Td ' + ' 0 -20 Td '.join(f'({line}) Tj' for line in lines) + ' ET').encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    path = tmp_path / 'printed.pdf'
    writer.write(path)
    document = assistant.upload('printed.pdf', path.read_bytes())
    assert '[第 1 页]' in document['content'] and '[第 2 页]' in document['content']
    assert 'Budget 600' in document['content']
    assert document['content'].count('Important repeated evidence') == 2
    assert 'https://example.com/article' not in document['content'] and '11:21' not in document['content']
    # An existing import gets the same improved extraction when re-organized.
    with assistant.service.connect() as db:
        db.execute('UPDATE documents SET content=? WHERE id=?', ('old extraction without pages', document['id']))
    queued = assistant.summarize(document['id'], 'codex')
    assert '[第 2 页]' in assistant.service.task(queued['task_id'])['prompt']


def test_readable_note_renders_tables_and_never_executes_document_html_or_loads_images():
    page = note_page({'id': 'test', 'title': '<script>title</script>', 'category': '资料', 'tags': ['学习'],
                     'origin': 'article.pdf', 'summary': '## 关键事实\n\n| 对象 | 数量 |\n| --- | --- |\n| 样本 | 52 |\n\n<script>alert(1)</script>\n\n![tracking](https://example.com/track.png)\n\n[unsafe](javascript:alert(1))'}).decode()
    assert '<table>' in page and '<h2>关键事实</h2>' in page
    assert '<script>' not in page and '&lt;script&gt;' in page
    assert 'src="https://example.com/track.png"' not in page and 'href="javascript:' not in page


def test_automatic_inbox_is_opt_in_and_does_not_duplicate_queued_summaries(assistant):
    assistant.upload('one.md', '个人智能体用于资料整理'.encode())
    assistant.tick()
    assert assistant.service.groups() == []
    assistant.configure(True, 'codex')
    assistant.tick()
    assistant.tick()
    document = assistant.state()['documents'][0]
    assert document['status'] == 'processing'
    assert len(assistant.service.tasks(assistant.service.task(document['task_id'])['group_id'])) == 1


def test_chinese_retrieval_answers_keep_original_evidence_and_reject_fake_citations(assistant):
    assistant.upload('方案.md', '个人智能体方案\nCodex 负责开发。\nOpenCode 负责检查。'.encode())
    matches = assistant.search('智能体方案有哪些')
    assert matches and '2: Codex' in matches[0]['excerpt']
    question = assistant.ask('智能体方案有哪些', 'codex')
    assistant.service.finish(question['task_id'], 'completed', json.dumps({'answer': 'Codex 开发，OpenCode 检查。[资料 1]', 'citations': [1]}))
    assistant.tick()
    assert assistant.state()['questions'][0]['status'] == 'ready'
    bad = assistant.ask('智能体方案有哪些', 'codex')
    assistant.service.finish(bad['task_id'], 'completed', json.dumps({'answer': '编造资料', 'citations': [999]}))
    assistant.tick()
    assert assistant.state()['questions'][0]['status'] == 'error'
    missing = assistant.ask('智能体方案有哪些', 'codex')
    assistant.service.finish(missing['task_id'], 'completed', json.dumps({'answer': '没有引用标记', 'citations': [1]}))
    assistant.tick()
    assert assistant.state()['questions'][0]['status'] == 'error'
    with pytest.raises(ValueError, match='未找到'):
        assistant.ask('kangaroo', 'codex')


def test_plan_requires_review_persists_checkpoints_and_runs_steps_in_order(assistant):
    plan = make_plan(assistant)
    assistant.tick()
    assert plan['status'] == 'ready'
    assert all(step['task_id'] is None for step in assistant.plan(plan['id'])['steps'])
    assistant.control_plan(plan['id'], 'start', '使用中文界面')
    assistant.tick()
    active = assistant.plan(plan['id'])
    first = active['steps'][0]['task_id']
    assert active['steps'][1]['task_id'] is None
    assert '使用中文界面' in assistant.service.task(first)['prompt']
    assistant.service.finish(first, 'completed', json.dumps({'completed': True, 'report': '已实现并测试'}))
    restarted = AssistantService(assistant.service)
    restarted.tick()
    second = restarted.plan(plan['id'])['steps'][1]['task_id']
    assert assistant.service.task(second)['dependency'] == first
    assistant.service.finish(second, 'completed', json.dumps({'completed': True, 'report': '检查通过'}))
    restarted.tick()
    assert restarted.plan(plan['id'])['status'] == 'completed'


def test_unfinished_step_blocks_plan_and_retry_preserves_preceding_success(assistant):
    plan = make_plan(assistant)
    assistant.control_plan(plan['id'], 'start', '')
    assistant.tick()
    first = assistant.plan(plan['id'])['steps'][0]['task_id']
    assistant.service.finish(first, 'completed', json.dumps({'completed': True, 'report': '实现成功'}))
    assistant.tick()
    second = assistant.plan(plan['id'])['steps'][1]['task_id']
    assistant.service.finish(second, 'completed', json.dumps({'completed': False, 'report': '测试失败，需要处理'}))
    assistant.tick()
    assert assistant.plan(plan['id'])['status'] == 'blocked'
    assistant.control_plan(plan['id'], 'retry', '先处理测试失败')
    assistant.tick()
    repaired = assistant.plan(plan['id'])
    assert repaired['steps'][0]['task_id'] == first
    assert repaired['steps'][1]['task_id'] != second
    assert assistant.service.task(repaired['steps'][1]['task_id'])['dependency'] == first


def test_pause_stops_next_dispatch_without_replaying_completed_work(assistant):
    plan = make_plan(assistant)
    assistant.control_plan(plan['id'], 'start', '')
    assistant.tick()
    first = assistant.plan(plan['id'])['steps'][0]['task_id']
    assistant.control_plan(plan['id'], 'pause', '')
    assistant.service.finish(first, 'completed', json.dumps({'completed': True, 'report': '实现成功'}))
    assistant.tick()
    assert assistant.plan(plan['id'])['steps'][1]['task_id'] is None
    assistant.control_plan(plan['id'], 'start', '')
    assistant.tick()
    assert assistant.plan(plan['id'])['steps'][0]['task_id'] == first
    assert assistant.plan(plan['id'])['steps'][1]['task_id']


def test_assistant_http_upload_authorization_and_source_download(assistant, monkeypatch, tmp_path):
    monkeypatch.setattr(assistant.service, 'start_worker', lambda *_: None)
    with socket.socket() as available:
        available.bind(('127.0.0.1', 0))
        port = available.getsockname()[1]
    server = create_server(assistant.service, tmp_path / 'config.json', port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = (assistant.service.root / 'dashboard.token').read_text().strip()
    last_headers = {}
    def request(method, path, body=None, cookie=True, origin=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
        headers = {'Content-Type': 'application/json'}
        if cookie:
            headers['Cookie'] = 'workgroups=' + token
        if origin:
            headers['Origin'] = origin
        connection.request(method, path, json.dumps(body).encode() if body is not None else None, headers)
        response = connection.getresponse()
        last_headers.clear()
        last_headers.update(response.getheaders())
        data = response.read()
        status = response.status
        connection.close()
        return status, data
    try:
        assert request('GET', '/api/assistant/state', cookie=False)[0] == 401
        assert request('POST', '/api/assistant/scan', {}, origin='https://evil.example')[0] == 403
        status, data = request('POST', '/api/assistant/upload', {'filename': 'budget.txt', 'content': base64.b64encode(b'Budget 300').decode()})
        assert status == 200
        document = json.loads(data)
        assert request('GET', '/api/assistant/source?id=' + document['id'])[1] == b'Budget 300'
        assert '-source.txt' in last_headers['Content-Disposition']
        assert "filename*=UTF-8''" in last_headers['Content-Disposition']
        assert request('GET', '/note?id=' + document['id'])[0] == 400
        complete_summary(assistant, document)
        assert 'Codex 负责实现'.encode() in request('GET', '/note?id=' + document['id'])[1]
        assert request('GET', '/note?id=' + document['id'], cookie=False)[0] == 200
        assert '访问码'.encode() in request('GET', '/note?id=' + document['id'], cookie=False)[1]
        assert request('GET', '/api/assistant/note?id=' + document['id'])[0] == 200
        assert '-note.md' in last_headers['Content-Disposition']
        assert request('GET', '/api/assistant/source?id=' + document['id'])[1] == b'Budget 300'
        assert request('GET', '/api/assistant/source?id=../../config.json')[0] == 400
        assert request('POST', '/api/assistant/upload', {'filename': 'budget.txt', 'content': '%%%bad'})[0] == 400
        assert request('GET', '/assistant')[0] == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
