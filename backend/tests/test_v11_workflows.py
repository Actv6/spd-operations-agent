from copy import deepcopy
import pytest
from sqlalchemy import select, func
from app.agent import work_once
from app.models import Analysis, AnalysisFeedback, Document, Membership, KnowledgeChange, Evidence
from conftest import register, create_run


def analyzed(client, app):
    me = register(client)
    run = create_run(client, me['projects'][0]['id'])
    work_once(app.state.factory, app.state.settings)
    result = client.get('/api/v1/runs/' + run['run_id']).json()
    return me, result['analysis_id']


def test_feedback_immutable_idempotent_and_scoped(client, app):
    me, aid = analyzed(client, app)
    path = f'/api/v1/analyses/{aid}/feedback'
    before = client.get('/api/v1/analyses/' + aid).json()
    data = {'rating': 'needs_correction', 'comment': '引用没有支持具体责任人，请复核。'}
    headers = {'Idempotency-Key': 'feedback-case-001'}
    first = client.post(path, json=data, headers=headers)
    assert first.status_code == 200, first.text
    assert client.post(path, json=data, headers=headers).json() == first.json()
    assert client.post(path, json={**data, 'comment': '不同内容'}, headers=headers).status_code == 409
    assert client.post(path, json={'rating': 'needs_correction', 'comment': ' '}, headers=headers).status_code == 422
    assert client.get('/api/v1/analyses/' + aid).json() == before
    assert client.get(path).json()['items'] == [first.json()]
    with app.state.factory() as db:
        row = db.scalar(select(AnalysisFeedback))
        assert row.context['snapshot_set_id'] == before['snapshot_set_id']
        assert row.context['analysis_hash'] and row.context['generation_mode'] == 'mock'
    outsider = register(client, 'outsider@example.test')
    assert client.get(path).status_code == 404
    assert client.post(path, json=data, headers=headers).status_code == 404
    with app.state.factory() as db:
        db.add(Membership(user_id=outsider['user']['id'], project_id=me['projects'][0]['id'], role='viewer'))
        db.commit()
    assert client.get(path).json() == {'items': [], 'can_submit': False}
    assert client.post(path, json=data, headers=headers).status_code == 403


DOCUMENT = {'title': '验收用缺日核查指引', 'version': '1', 'content': '# 缺日核查\n缺失记录需要先核对原始台账，不可默认补零。\n', 'source_note': '授权生成的本地验收资料'}


def preview(client, project, doc=DOCUMENT):
    result = client.post(f'/api/v1/projects/{project}/knowledge/preview', json=doc)
    assert result.status_code == 200, result.text
    return result.json()


def publish(client, project, doc=DOCUMENT, key='knowledge-case-001', pre=None):
    pre = pre or preview(client, project, doc)
    body = {**doc, 'catalog_token': pre['catalog_token'], 'preview_hash': pre['preview_hash']}
    return client.post(f'/api/v1/projects/{project}/knowledge/publish', json=body, headers={'Idempotency-Key': key}), body


def test_knowledge_preview_publication_retirement_preserves_evidence(client, app):
    me, aid = analyzed(client, app)
    project = me['projects'][0]['id']
    with app.state.factory() as db:
        history = deepcopy(db.get(Analysis, aid).body)
        docs_before = db.scalar(select(func.count()).select_from(Document))
        evidence_before = [(e.id, deepcopy(e.body)) for e in db.scalars(select(Evidence)).all()]
    pre = preview(client, project)
    with app.state.factory() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == docs_before
    response, body = publish(client, project, pre=pre)
    assert response.status_code == 200, response.text
    published = response.json()
    assert client.post(f'/api/v1/projects/{project}/knowledge/publish', json=body, headers={'Idempotency-Key': 'knowledge-case-001'}).json() == published
    assert client.post(f'/api/v1/projects/{project}/knowledge/preview', json=DOCUMENT).status_code == 409
    assert client.post(f'/api/v1/projects/{project}/knowledge/preview', json={**DOCUMENT, 'version': '2'}).status_code == 409
    path = f'/api/v1/projects/{project}/knowledge/manage'
    state = client.get(path).json()
    retirement = {'catalog_token': state['catalog_token'], 'reason': '修订版本前停用'}
    retired = client.post(f"/api/v1/knowledge/documents/{published['document_id']}/retire", json=retirement, headers={'Idempotency-Key': 'retire-case-001'})
    assert retired.status_code == 200, retired.text
    assert client.post(f"/api/v1/knowledge/documents/{published['document_id']}/retire", json=retirement, headers={'Idempotency-Key': 'retire-case-001'}).json() == retired.json()
    original = client.get('/api/v1/knowledge/documents/' + published['document_id']).json()
    assert original['content'] == DOCUMENT['content'] and not original['currently_valid']
    hits = client.get(f'/api/v1/projects/{project}/knowledge/search?q=缺失记录').json()['items']
    assert all(h['document_id'] != published['document_id'] for h in hits)
    next_doc = {**DOCUMENT, 'version': '2'}
    assert publish(client, project, next_doc, 'knowledge-case-002')[0].status_code == 200
    with app.state.factory() as db:
        assert db.get(Analysis, aid).body == history
        assert [(e.id, e.body) for e in db.scalars(select(Evidence)).all()] == evidence_before
        assert db.scalar(select(func.count()).select_from(KnowledgeChange)) == 3


def test_stale_preview_body_change_permissions_and_csrf(client, app):
    me = register(client)
    project = me['projects'][0]['id']
    pre = preview(client, project)
    changed = {**DOCUMENT, 'content': '完全不同的正文'}
    assert publish(client, project, changed, pre=pre)[0].status_code == 409
    other_doc = {**DOCUMENT, 'title': '另一个资料'}
    assert publish(client, project, other_doc, 'knowledge-other-001')[0].status_code == 200
    assert publish(client, project, pre=pre)[0].status_code == 409
    assert client.post(f'/api/v1/projects/{project}/knowledge/preview', json={**DOCUMENT, 'content': '# 只有标题'}).status_code == 422
    assert client.post(f'/api/v1/projects/{project}/knowledge/preview', json=DOCUMENT, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    with app.state.factory() as db:
        member = db.get(Membership, (me['user']['id'], project))
        member.role = 'viewer'
        db.commit()
    assert client.get(f'/api/v1/projects/{project}/knowledge/manage').json()['can_manage'] is False
    assert client.post(f'/api/v1/projects/{project}/knowledge/preview', json=DOCUMENT).status_code == 403
    assert publish(client, project, pre=pre)[0].status_code == 403
    register(client, 'other@example.test')
    assert client.get(f'/api/v1/projects/{project}/knowledge/manage').status_code == 404


def test_retire_cited_document_preserves_original_analysis(client, app):
    me, aid = analyzed(client, app)
    project = me['projects'][0]['id']
    before = client.get('/api/v1/analyses/' + aid).json()
    citation = next(c for c in before['citations'] if c['source_kind'] == 'document')
    doc_id = citation['location']['document_id']
    with app.state.factory() as db:
        raw_analysis = deepcopy(db.get(Analysis, aid).body)
        original = (db.get(Document, doc_id).content, db.get(Document, doc_id).source_hash)
    token = client.get(f'/api/v1/projects/{project}/knowledge/manage').json()['catalog_token']
    result = client.post(f'/api/v1/knowledge/documents/{doc_id}/retire', json={'catalog_token': token, 'reason': '验收停用引用资料'}, headers={'Idempotency-Key': 'retire-cited-doc'})
    assert result.status_code == 200, result.text
    now = client.get('/api/v1/evidence/' + citation['evidence_id']).json()
    assert now['excerpt'] == citation['excerpt'] and now['currently_valid'] is False
    with app.state.factory() as db:
        assert db.get(Analysis, aid).body == raw_analysis
        assert (db.get(Document, doc_id).content, db.get(Document, doc_id).source_hash) == original


def test_concurrent_publication_serializes_preview(client, app):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    me = register(client)
    project = me['projects'][0]['id']
    one = {**DOCUMENT, 'title': '并发资料一'}
    two = {**DOCUMENT, 'title': '并发资料二'}
    prepared = [(doc, preview(client, project, doc)) for doc in [one, two]]
    cookies, headers = dict(client.cookies), dict(client.headers)
    def submit(pair):
        doc, pre = pair
        with TestClient(app) as other:
            other.cookies.update(cookies)
            other.headers.update(headers)
            return publish(other, project, doc, 'concurrent-' + pre['preview_hash'][:12], pre=pre)[0].status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(submit, prepared))
    assert sorted(statuses) == [200, 409]
