"""Quality-close regressions: actual lexical retrieval and controlled providers."""
import json
import pytest
from sqlalchemy import select
from app.answer_quality import no_advice_requested, validate_answer_scope
from app.errors import AppError
from app.agent import work_once
from app.models import Run, Analysis, Document
from app.knowledge import search
from app.knowledge import scoring_text, retrieval_topics
from conftest import register, create_run, request_body
from test_m21 import ScanProvider
from test_enterprise import use_scenario


def test_whole_window_zero_expansion_preserves_words_and_missing_day_distinction():
    text = '完整14日消耗记录全部为零时不能估算'
    normalized = scoring_text(text)
    assert '消耗记录全部为零' in normalized
    assert '零消耗' in retrieval_topics(scoring_text('14日都是零记录'))
    assert '零消耗' not in retrieval_topics(scoring_text('两天缺失，建议补零记录'))


@pytest.mark.parametrize('query', ['有几天的用量没填咋办', '用量漏填怎么办', '消耗少填了要补零吗'])
def test_colloquial_missing_on_full_scenario_preserves_sources(client, app, monkeypatch, query):
    use_scenario(monkeypatch)
    project = register(client)['projects'][0]['id']
    with app.state.factory() as db:
        hits = search(db, project, query, limit=3)
        assert hits and hits[0]['document_external_id'] == 'OPS-KB-MISSING-v1'
        for hit in hits:
            doc = db.get(Document, hit['document_id'])
            assert doc.content[hit['start_offset']:hit['end_offset']] == hit['excerpt']
            assert hit['source_hash'] == doc.source_hash
        assert search(db, 'other-project', query) == []


@pytest.mark.parametrize('question', ['只回答日期、状态和不能补零的原因', '只说缺失的日期', '不要处理建议', '不给建议'])
def test_explicit_limits(question):
    assert no_advice_requested(question)
    validate_answer_scope(question, '9月22日和24日为缺失。不能补零，不应直接发布快照。')
    with pytest.raises(AppError) as exc:
        validate_answer_scope(question, '9月22日和24日缺失。建议补齐后发布快照。')
    assert exc.value.body['code'] == 'ANSWER_SCOPE_VIOLATION'


@pytest.mark.parametrize('text', ['不能补零但建议核对台账。', '不应发布，但请核实缺失日期。', '**行动清单**\n核对台账', '应当人工核对记录。'])
def test_negation_does_not_mask_affirmative_advice(text):
    with pytest.raises(AppError):
        validate_answer_scope('不要处理建议', text)


def test_regular_question_and_negative_explanation_allowed():
    validate_answer_scope('缺日怎么办', '建议核对台账。')
    validate_answer_scope('不要建议', '不建议直接发布，不需要核对其他物资。')


@pytest.mark.parametrize('always', [False, True])
def test_scope_guard_in_followup_preserves_parent_and_usage(client, app, monkeypatch, always):
    use_scenario(monkeypatch)
    app.state.settings.llm_provider = 'deepseek'
    project = register(client)['projects'][0]['id']
    parent = create_run(client, project, 'scope-parent', request_body('核查当前范围', item_ids=[]))
    work_once(app.state.factory, app.state.settings, ScanProvider())
    parent = client.get('/api/v1/runs/'+parent['run_id']).json()
    before = client.get('/api/v1/analyses/'+parent['analysis_id']).json()
    body = request_body('只回答日期、状态和不能补零的原因，不给处理建议', item_ids=[], snapshot_set_id=parent['snapshot_set_id'], analysis_id=parent['analysis_id'])
    body.update(mode='follow_up',parent_run_id=parent['run_id'],session_id=parent['session_id'])
    child = create_run(client, project, 'scope-child', body)
    class RestrictedProvider(ScanProvider):
        async def complete(self, messages, final=False):
            message, meta = await super().complete(messages, final)
            if message.get('tool_calls'):
                message['tool_calls'][0]['function'].update(name='get_consumption', arguments='{"item_ids":["SIM-P006"]}')
            if final:
                payload = json.loads(message['content'])
                if always or self.finals == 1:
                    payload['answer'] += '\n\n建议补齐记录并发布新快照。'
                message['content'] = json.dumps(payload,ensure_ascii=False)
            return message, meta
    provider = RestrictedProvider()
    work_once(app.state.factory,app.state.settings,provider)
    result = client.get('/api/v1/runs/'+child['run_id']).json()
    assert provider.finals == 2
    assert result['snapshot_set_id'] == parent['snapshot_set_id']
    with app.state.factory() as db:
        run = db.get(Run,child['run_id'])
        assert sum(m['usage']['total_tokens'] for m in run.checkpoint['metadata']) == (400 if always else 300)
        assert run.request['parent_run_id'] == parent['run_id']
        assert len(run.checkpoint['final_outputs']) == 2
        assert '建议补齐记录' in run.checkpoint['final_outputs'][0]['content']
    if always:
        assert result['status'] == 'failed' and result['analysis_id'] is None
        assert result['error']['code'] == 'ANSWER_SCOPE_VIOLATION'
    else:
        assert result['status'] == 'succeeded'
        analysis = client.get('/api/v1/analyses/'+result['analysis_id']).json()
        assert sum(m['usage']['total_tokens'] for m in analysis['provider_metadata']['calls']) == 400
        assert analysis['provider_metadata']['retrieval_release'] == 'lexical-quality-3'
    assert client.get('/api/v1/analyses/'+parent['analysis_id']).json() == before
    assert client.get(f'/api/v1/projects/{project}/tasks').json() == []


def test_correction_stops_at_budget_and_retains_bad_output(client, app, monkeypatch):
    use_scenario(monkeypatch)
    app.state.settings.llm_provider = 'deepseek'
    app.state.settings.max_run_tokens = 350
    project = register(client)['projects'][0]['id']
    run = create_run(client,project,body=request_body('不要处理建议',item_ids=[]))
    class BadProvider(ScanProvider):
        async def complete(self,messages,final=False):
            msg, meta = await super().complete(messages,final)
            if final:
                data = json.loads(msg['content']); data['answer'] = '建议补齐记录。'
                msg['content'] = json.dumps(data,ensure_ascii=False)
            return msg, meta
    provider = BadProvider()
    work_once(app.state.factory,app.state.settings,provider)
    result = client.get('/api/v1/runs/'+run['run_id']).json()
    assert result['status'] == 'failed' and not result['analysis_id']
    assert result['error']['code'] == 'TOKEN_BUDGET_EXCEEDED'
    with app.state.factory() as db:
        state = db.get(Run,run['run_id']).checkpoint
        assert sum(m['usage']['total_tokens'] for m in state['metadata']) == 400
        assert len(state['final_outputs']) == 2
        assert any('建议补齐记录' in (m.get('content') or '') for m in provider.final_messages)
        assert db.scalar(select(Analysis).where(Analysis.run_id==run['run_id'])) is None
