"""Controlled-provider regressions, not real-model quality evidence."""
import asyncio
import json
from copy import deepcopy
import httpx
import pytest
from sqlalchemy import select
from app.agent import work_once
from app.answer_quality import risk_summary, risk_priority_summary, validate_business_answer
from app.errors import AppError
from app.models import Run, Snapshot
from app.operations import details
from app.data import inventory
from app.providers import DeepSeekProvider
from app.tool_projection import project_tool
from app.claim_support import render_claims
from app.schemas import AnswerClaim
from conftest import register, create_run, request_body
from test_enterprise import use_scenario


def test_legacy_default_focus_preserves_idempotency(client, app):
    from app.data import canonical_hash
    project = register(client)['projects'][0]['id']
    body = request_body()
    run = create_run(client, project, body=body)
    with app.state.factory() as db:
        stored = db.get(Run, run['run_id'])
        assert 'focus' not in stored.request['options']
        assert stored.request_hash == canonical_hash(body)
    body['options']['focus'] = 'general'
    assert create_run(client, project, body=body)['run_id'] == run['run_id']
    body['options']['focus'] = 'risk_scan'
    assert client.post(f'/api/v1/projects/{project}/runs', json=body,
                       headers={'Idempotency-Key': 'test-run-key'}).status_code == 409


class ScanProvider:
    def __init__(self, fault=None, always=False, usage=100):
        self.fault, self.always, self.usage = fault, always, usage
        self.finals = 0
        self.outputs = []
        self.final_messages = []

    async def complete(self, messages, final=False):
        outputs = [json.loads(m['content']) for m in messages if m['role'] == 'tool']
        meta = {'usage': {'total_tokens': self.usage}, 'cost': None}
        if not outputs and not final:
            name = 'get_inventory' if self.fault == 'no-scan' else 'compute_risks'
            return {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'scan', 'function': {'name': name, 'arguments': '{}'}}]}, meta
        self.outputs = outputs
        if not final:
            return {'role': 'assistant', 'content': '已核查，请整理结果'}, meta
        self.finals += 1
        self.final_messages = messages
        report = next((o['data'] for o in outputs if o['kind'] == 'risks'), None)
        expected = risk_summary(report) if report else None
        answer = {'answer': '已核查当前范围。数据缺口与零消耗分开记录，请按证据核实。',
                  'evidence_ids': [e for o in outputs for e in o['evidence_ids']], 'insufficient_evidence': True, 'risk_summary': expected}
        catalog = [f for o in outputs for f in o.get('fact_catalog', [])]
        claims = [AnswerClaim(kind='fact', text=f['text'], fact_ids=[f['fact_id']], evidence_ids=f['evidence_ids']) for f in catalog[:6]]
        draft_mode = any('任务模式为 draft_action' in (m.get('content') or '') for m in messages if m['role'] == 'system')
        if draft_mode:
            answer['task_draft'] = {'title': '复核异常来源', 'steps': ['核对物资与消耗记录', '记录未解决信息并交复核']}
            claims += [AnswerClaim(kind='suggestion', text=step, evidence_ids=answer['evidence_ids'][:1]) for step in answer['task_draft']['steps']]
        if claims:
            answer['claims'] = [c.model_dump() for c in claims]
            answer['answer'] = render_claims(claims)
            answer['evidence_ids'] = list(dict.fromkeys(e for c in claims for e in c.evidence_ids))
        if self.always or self.finals == 1:
            if self.fault == 'counts':
                answer['risk_summary'] = {**expected, 'data_quality': 3, 'zero_consumption': 0}
            elif self.fault == 'code':
                answer['answer'] = '请核实MAT-P004的库存。'
            elif self.fault == 'jargon':
                answer['answer'] = '覆盖值coverage_days需核实。'
            elif self.fault == 'draft-field':
                answer['answer'] = '请查看task_draft确认待办。'
            elif self.fault == 'priority-count':
                answer['answer'] = '高关注 2 条，中关注 6 条。'
            elif self.fault == 'citation':
                answer['evidence_ids'] = []
        return {'role': 'assistant', 'content': json.dumps(answer, ensure_ascii=False)}, meta


def setup(client, app, monkeypatch, provider):
    use_scenario(monkeypatch)
    app.state.settings.llm_provider = 'deepseek'
    project = register(client)['projects'][0]['id']
    body = request_body('请核查全部异常', item_ids=[])
    body['options']['focus'] = 'risk_scan'
    run = create_run(client, project, body=body)
    work_once(app.state.factory, app.state.settings, provider)
    return project, client.get('/api/v1/runs/' + run['run_id']).json()


@pytest.mark.parametrize('fault', ['counts', 'priority-count', 'code', 'jargon', 'citation', 'draft-field'])
def test_one_correction_keeps_usage_and_full_evidence(client, app, monkeypatch, fault):
    p = ScanProvider(fault)
    _, run = setup(client, app, monkeypatch, p)
    assert run['status'] == 'succeeded', run
    result = client.get('/api/v1/analyses/' + run['analysis_id']).json()
    assert result['risk_summary'] == dict(scanned_positions=24, skipped_estimates=3, data_quality=2, zero_consumption=1, findings=8)
    assert p.finals == 2 and len(result['provider_metadata']['calls']) == 4
    assert run['options']['focus'] == 'risk_scan'
    assert all('source_rows' not in json.dumps(o['data']) for o in p.outputs)
    assert result['citations'][0]['facts']['risks']['findings'][0]['source_rows']


@pytest.mark.parametrize('fault,code', [('counts','RISK_SUMMARY_MISMATCH'), ('priority-count','RISK_PRIORITY_COUNT_MISMATCH'), ('code','ANSWER_CODE_INVALID'), ('jargon','ANSWER_LANGUAGE_INVALID'), ('citation','RISK_CITATION_REQUIRED'), ('draft-field','ANSWER_LANGUAGE_INVALID')])
def test_persistent_quality_error_is_failure(client, app, monkeypatch, fault, code):
    p = ScanProvider(fault, always=True)
    _, run = setup(client, app, monkeypatch, p)
    assert run['status'] == 'failed' and run['error']['code'] == code and not run['analysis_id'], run
    assert p.finals == 2


def test_full_scan_required(client, app, monkeypatch):
    _, run = setup(client, app, monkeypatch, ScanProvider('no-scan'))
    assert run['status'] == 'failed' and run['error']['code'] == 'RISK_SCAN_REQUIRED'


def test_priority_counts_are_derived_from_scan_and_mismatch_is_rejected():
    report = {"findings": [
        {"priority": "high"}, {"priority": "high"}, {"priority": "high"},
        *[{"priority": "medium"} for _ in range(5)],
    ]}
    counts = risk_priority_summary(report)
    assert counts == {"high": 3, "medium": 5}
    from app.schemas import ModelAnswer
    summary = {"scanned_positions": 8, "skipped_estimates": 0, "data_quality": 0, "zero_consumption": 0, "findings": 8}
    good = ModelAnswer(answer="高关注 3 条，中关注 5 条。", evidence_ids=[], insufficient_evidence=True, risk_summary=summary)
    validate_business_answer(good, summary, [], expected_priority_counts=counts)
    bad = ModelAnswer(answer="高关注 2 条，中关注 6 条。", evidence_ids=[], insufficient_evidence=True, risk_summary=summary)
    with pytest.raises(AppError) as error:
        validate_business_answer(bad, summary, [], expected_priority_counts=counts)
    assert error.value.body["code"] == "RISK_PRIORITY_COUNT_MISMATCH"


def test_final_context_acknowledges_actual_expiry_screening(client, app, monkeypatch):
    provider = ScanProvider()
    _, run = setup(client, app, monkeypatch, provider)
    assert run['status'] == 'succeeded'
    notes = '\n'.join(m.get('content') or '' for m in provider.final_messages if m['role'] == 'system')
    assert '是否覆盖全部许可范围：是' in notes
    assert '扫描结果不等于已读取逐批明细' in notes


def test_partial_scan_not_described_as_full_scope(client, app, monkeypatch):
    class PartialScan(ScanProvider):
        async def complete(self, messages, final=False):
            result, meta = await super().complete(messages, final)
            if result.get('tool_calls'):
                result['tool_calls'][0]['function']['arguments'] = '{"item_ids":["SIM-P005"]}'
            return result, meta
    use_scenario(monkeypatch)
    app.state.settings.llm_provider = 'deepseek'
    project = register(client)['projects'][0]['id']
    run = create_run(client, project, body=request_body('核查低频耗材', item_ids=[]))
    provider = PartialScan()
    work_once(app.state.factory, app.state.settings, provider)
    assert client.get('/api/v1/runs/'+run['run_id']).json()['status'] == 'succeeded'
    note = next(m['content'] for m in provider.final_messages if m['role']=='system' and '是否覆盖全部许可范围' in m['content'])
    assert '否，仅工具所查范围' in note


def test_budget_stop_keeps_usage(client, app, monkeypatch):
    app.state.settings.max_run_tokens = 4000
    _, run = setup(client, app, monkeypatch, ScanProvider(usage=4001))
    assert run['error']['code'] == 'TOKEN_BUDGET_EXCEEDED'
    with app.state.factory() as db:
        assert db.get(Run, run['run_id']).checkpoint['metadata'][0]['usage']['total_tokens'] == 4001


def test_input_limit_before_network(app):
    settings = app.state.settings.model_copy(update={'deepseek_api_key': 'test-key', 'max_input_chars': 4000})
    def no_network(_):
        pytest.fail('oversized input must not be sent')
    p = DeepSeekProvider(settings, httpx.MockTransport(no_network))
    with pytest.raises(AppError) as exc:
        asyncio.run(p.complete([{'role': 'user', 'content': '甲' * 5000}]))
    assert exc.value.body['code'] == 'CONTEXT_BUDGET_EXCEEDED'


def test_projection_retains_counts_missing_days_and_null(client, app, monkeypatch):
    use_scenario(monkeypatch)
    project = register(client)['projects'][0]['id']
    with app.state.factory() as db:
        snapshot = db.scalar(select(Snapshot).where(Snapshot.project_id == project))
        rows = inventory(snapshot); raw = details(snapshot)
        projected = project_tool('consumption', raw['consumption'], rows)
        assert projected['view'] == 'summary' and projected['positions'] == len(rows) and not projected['detail_included']
        cup = next(i for i in projected['items'] if i['item_id'] == 'SIM-P006')
        assert cup['missing_dates'] == ['2026-09-22','2026-09-24'] and cup['daily_average'] is None
        assert len(json.dumps(projected)) < len(json.dumps(raw['consumption'])) / 3
        small = details(snapshot, ['SIM-P006'])['consumption']
        actual = project_tool('consumption', small, [r for r in rows if r['item_id'] == 'SIM-P006'])
        assert len(actual[0]['days']) == 14
        assert all(d['quantity'] is None for d in actual[0]['days'] if d['status'] == 'missing')
        batches = project_tool('batches', raw['batches'], rows)
        assert batches['total_batches'] == len(raw['batches']) and batches['positions'] == 24
        assert next(b for b in batches['items'] if b['item_id'] == 'SIM-P004')['expired_batches'] == 1


def test_pinned_snapshot_survives_new_publication(client, app):
    project = register(client)['projects'][0]['id']
    old = client.get(f'/api/v1/projects/{project}/dashboard').json()
    path = f'/api/v1/projects/{project}/risks?snapshot_set_id={old["snapshot_set_id"]}'
    before = client.get(path).json()
    with app.state.factory() as db:
        source = db.get(Snapshot, old['snapshot_set_id'])
        facts = deepcopy(source.facts)
        for b in facts['inventory_batches']:
            b['expiry_date'] = '2020-01-01'
        new = Snapshot(project_id=project, as_of=source.as_of, source_hash='b'*64, facts=facts, created_at=source.created_at+100)
        db.add(new); db.commit(); new_id = new.id
    assert client.get(f'/api/v1/projects/{project}/dashboard').json()['snapshot_set_id'] == new_id
    assert client.get(path).json() == before
    run = create_run(client, project, body=request_body(snapshot_set_id=old['snapshot_set_id']))
    assert run['snapshot_set_id'] == old['snapshot_set_id']
    detail = client.get(f'/api/v1/projects/{project}/item-details?item_id=SIM-P001&snapshot_set_id={old["snapshot_set_id"]}').json()
    assert detail['snapshot_set_id'] == old['snapshot_set_id']


def test_scan_followup_draft_confirm_task_flow(client, app, monkeypatch):
    project, parent = setup(client, app, monkeypatch, ScanProvider())
    body = request_body('请继续核查', item_ids=[], snapshot_set_id=parent['snapshot_set_id'], analysis_id=parent['analysis_id'])
    body.update(mode='follow_up', parent_run_id=parent['run_id'], session_id=parent['session_id'])
    child = create_run(client, project, 'm21-follow-up', body)
    work_once(app.state.factory, app.state.settings, ScanProvider())
    child = client.get('/api/v1/runs/' + child['run_id']).json()
    assert child['status'] == 'succeeded'
    body.update(mode='draft_action', parent_run_id=child['run_id'])
    body['context']['analysis_id'] = child['analysis_id']
    run = create_run(client, project, 'm21-draft', body)
    work_once(app.state.factory, app.state.settings, ScanProvider())
    run = client.get('/api/v1/runs/' + run['run_id']).json()
    assert run['status'] == 'succeeded', run
    draft = client.get('/api/v1/drafts/' + run['draft_id']).json()
    assert client.get(f'/api/v1/projects/{project}/tasks').json() == []
    confirm = dict(revision=draft['revision'], title='人工修订核查任务', steps=['仅核对当前缺口'], due_date='2026-10-01')
    url = '/api/v1/drafts/' + draft['id'] + '/confirm'
    from conftest import complete_human_reviews
    assert client.post(url, json=confirm).json()['code'] == 'HUMAN_REVIEW_REQUIRED'
    complete_human_reviews(client, parent['run_id'], child['run_id'], run['run_id'])
    task = client.post(url, json=confirm).json()
    assert client.post(url, json=confirm).json()['id'] == task['id']
    assert task['title'] == confirm['title'] and task['steps'] == confirm['steps']
    url = '/api/v1/tasks/' + task['id']
    task = client.patch(url, json=dict(revision=task['revision'], status='in_progress')).json()
    assert client.patch(url, json=dict(revision=task['revision'], status='completed')).status_code == 422
    baseline = client.get(f'/api/v1/projects/{project}/risks').json()
    task = client.patch(url, json=dict(revision=task['revision'], status='completed', result='已核对，异常仍需数据确认')).json()
    assert task['status'] == 'completed'
    assert client.get(f'/api/v1/projects/{project}/risks').json() == baseline
    assert client.patch(url, json=dict(revision=task['revision'], status='todo', result='复核重开')).json()['status'] == 'todo'
