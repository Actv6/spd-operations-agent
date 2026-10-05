"""Deterministic guard/controlled provider tests, never real-model acceptance."""
import json
import pytest
from app.answer_quality import validate_business_answer
from app.schemas import ModelAnswer
from app.errors import AppError
from test_m21 import ScanProvider, setup

SUMMARY = dict(scanned_positions=24, skipped_estimates=3, data_quality=2, zero_consumption=1, findings=8)


@pytest.mark.parametrize('text', [
    '高关注共2条，中关注共6条', '高关注两条，中关注六条',
    '**高关注**：共有 **２** 项', '2条属于高关注', '中优先级合计六个',
    '优先核实（两项）', '高关注数量为二个',
])
def test_count_paraphrases_rejected(text):
    answer = ModelAnswer(answer=text, evidence_ids=[], insufficient_evidence=True, risk_summary=SUMMARY)
    with pytest.raises(AppError) as exc:
        validate_business_answer(answer, SUMMARY, [], expected_priority_counts={'high': 3, 'medium': 5})
    assert exc.value.body['code'] == 'RISK_PRIORITY_COUNT_MISMATCH'


@pytest.mark.parametrize('text', ['高关注共三条，中关注五条', '**高关注**：３项', '3条属于高关注', '优先核实效期，详见分级清单。'])
def test_correct_counts_and_no_counts_allowed(text):
    answer = ModelAnswer(answer=text, evidence_ids=[], insufficient_evidence=True, risk_summary=SUMMARY)
    validate_business_answer(answer, SUMMARY, [], expected_priority_counts={'high': 3, 'medium': 5})


def test_search_absence_is_not_nonexistence():
    for text in ['本项目知识库中不存在适用制度。', '不存在适用资料。']:
        with pytest.raises(AppError) as exc:
            validate_business_answer(ModelAnswer(answer=text, evidence_ids=[], insufficient_evidence=True), None, [])
        assert exc.value.body['code'] == 'KNOWLEDGE_ABSENCE_OVERCLAIM'
    validate_business_answer(ModelAnswer(answer='本次未检索到适用资料。', evidence_ids=[], insufficient_evidence=True), None, [])


@pytest.mark.parametrize('always', [False, True])
def test_new_guard_in_real_graph_with_controlled_provider(client, app, monkeypatch, always):
    class Variant(ScanProvider):
        async def complete(self, messages, final=False):
            message, meta = await super().complete(messages, final)
            if final and (always or self.finals == 1):
                payload = json.loads(message['content'])
                payload['answer'] = '高关注共两条，中关注六条'
                message['content'] = json.dumps(payload, ensure_ascii=False)
            return message, meta
    provider = Variant()
    _, run = setup(client, app, monkeypatch, provider)
    assert provider.finals == 2
    if always:
        assert run['status'] == 'failed' and run['analysis_id'] is None
        assert run['error']['code'] == 'RISK_PRIORITY_COUNT_MISMATCH'
    else:
        assert run['status'] == 'succeeded'
        result = client.get('/api/v1/analyses/' + run['analysis_id']).json()
        assert result['risk_priority_summary'] == {'high': 3, 'medium': 5}
        assert len(result['risk_findings']) == 8
        assert sum(m['usage']['total_tokens'] for m in result['provider_metadata']['calls']) == 400
