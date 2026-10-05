"""V1.2 bounded support, raw failure and controlled graph regressions."""
import json
from copy import deepcopy
from pathlib import Path
import pytest
from sqlalchemy import select
from app.claim_support import (fact_catalog, reason_breakdown, row_reasons,
                               render_claims, validate_claims, validate_reason_text)
from app.schemas import ModelAnswer, AnswerClaim
from app.errors import AppError
from app.data import inventory, snapshot_for
from app.models import Run, Analysis, Evidence
from app.agent import work_once
from conftest import create_run, register, request_body
from test_enterprise import use_scenario
from test_m21 import ScanProvider, setup


def rows():
    return [dict(item_id='cup',department_id='lab',name='反应杯',department_name='检验科',display_code='MAT-0006',
                 quality_issues=['MISSING_CONSUMPTION_DAYS'],daily_average=None),
            dict(item_id='tube',department_id='lab',name='采样管',department_name='检验科',display_code='MAT-0007',
                 quality_issues=['STALE_SNAPSHOT'],daily_average='3'),
            dict(item_id='low',department_id='lab',name='低频耗材',department_name='检验科',display_code='MAT-0005',
                 quality_issues=[],daily_average='0')]


@pytest.mark.parametrize('text', [
    '2个因14日消耗记录缺日（数据质量原因）', '对2个缺日物资核对每日记录',
    '缺日共两个位置', '**缺日**：２个组合', '旧快照有二个位置', '零消耗共两项',
])
def test_wrong_reason_count_variants(text):
    with pytest.raises(AppError) as exc:
        validate_reason_text(text, rows())
    assert exc.value.body['code'] == 'QUALITY_REASON_MISATTRIBUTION'


@pytest.mark.parametrize('text', ['缺日1个位置；旧快照1个位置；零消耗1个位置。',
                                '反应杯缺日；采样管旧快照。', '采样管不是缺日，反应杯缺日。'])
def test_correct_counts_objects_and_local_negation(text):
    validate_reason_text(text, rows())


def test_object_guard_in_suggestion_and_ambiguous_departments():
    with pytest.raises(AppError) as exc:
        validate_reason_text('建议对采样管的缺日补齐记录。', rows())
    assert exc.value.body['code'] == 'QUALITY_REASON_OBJECT_MISMATCH'
    values = rows() + [dict(rows()[0], department_id='surgery',department_name='手术室',quality_issues=[])]
    validate_reason_text('检验科反应杯缺日。', values)
    with pytest.raises(AppError):
        validate_reason_text('反应杯缺日。', values)


def test_overlap_counts_and_item_species_are_not_unique_position_total():
    values = rows()
    values[0]['quality_issues'].append('STALE_SNAPSHOT')
    values.append(dict(values[0],department_id='surgery',department_name='手术室'))
    groups = {g['reason']:g for g in reason_breakdown(values + [values[0]], 'e1')}
    assert groups['MISSING_CONSUMPTION_DAYS']['count'] == 2
    assert groups['STALE_SNAPSHOT']['count'] == 3
    assert groups['ZERO_CONSUMPTION']['count'] == 1
    validate_reason_text('缺日1种物资。缺日2个位置。', values)
    assert 'ZERO_CONSUMPTION' not in row_reasons(dict(values[2],quality_issues=['STALE_SNAPSHOT']))


def supported():
    catalog = [{'fact_id':'f-one','text':'反应杯 · 检验科：14日消耗缺日。','evidence_ids':['e1']}]
    sources = {'e1':{'source_kind':'tool'}, 'e2':{'source_kind':'document','excerpt':'缺失记录不得补零，应先核对原始台账。'}}
    claim = AnswerClaim(kind='fact',text=catalog[0]['text'],fact_ids=['f-one'],evidence_ids=['e1'])
    answer = ModelAnswer(answer=render_claims([claim]),claims=[claim],evidence_ids=['e1'],insufficient_evidence=False)
    return answer, catalog, sources


@pytest.mark.parametrize('fault,error', [
    ('wrong-text','CLAIM_FACT_MISMATCH'), ('wrong-id','CLAIM_FACT_MISMATCH'),
    ('wrong-source','CLAIM_FACT_MISMATCH'), ('foreign-source','CLAIM_CITATION_INVALID'),
    ('no-claims','CLAIMS_REQUIRED'), ('extra-prose','CLAIM_ANSWER_MISMATCH'),
    ('unused-source','CLAIM_CITATION_COVERAGE'), ('draft-bypass','CLAIM_DRAFT_MISMATCH'),
])
def test_fact_and_prose_cannot_bypass_support(fault,error):
    answer,catalog,sources = supported()
    if fault=='wrong-text': answer.claims[0].text='采样管缺日。'
    if fault=='wrong-id': answer.claims[0].fact_ids=['other-run-fact']
    if fault=='wrong-source': answer.claims[0].evidence_ids=['e2']
    if fault=='foreign-source': answer.claims[0].evidence_ids=['other-project']
    if fault=='no-claims': answer.claims=[]
    if fault=='extra-prose': answer.answer+='\n\n已完成采购。'
    if fault=='unused-source': answer.evidence_ids.append('e2')
    if fault=='draft-bypass':
        from app.schemas import TaskProposal
        answer.task_draft=TaskProposal(title='核查',steps=['未经关联的操作'])
    with pytest.raises(AppError) as exc: validate_claims(answer,catalog,sources)
    assert exc.value.body['code']==error


def test_quote_matching_is_distinct_from_semantic_support():
    answer,catalog,sources=supported()
    quote=AnswerClaim(kind='policy',text='缺失记录不得补零',evidence_ids=['e2'])
    answer.claims.append(quote);answer.evidence_ids.append('e2');answer.answer=render_claims(answer.claims)
    views=validate_claims(answer,catalog,sources)
    assert [v['verification'] for v in views]==['tool_exact','document_quote']
    quote.text='缺失记录必须补零'
    with pytest.raises(AppError) as exc: validate_claims(answer,catalog,sources)
    assert exc.value.body['code']=='CLAIM_QUOTE_MISMATCH'
    quote.text=catalog[0]['text'];quote.evidence_ids=['e1']
    with pytest.raises(AppError): validate_claims(answer,catalog,sources)


def test_suggestion_and_unknown_never_receive_fact_verified_label():
    answer,catalog,sources=supported()
    suggestion=AnswerClaim(kind='suggestion',text='核对原始台账',evidence_ids=['e1'])
    unknown=AnswerClaim(kind='unknown',text='是否存在尚未同步记录需要确认。')
    answer.claims += [suggestion,unknown];answer.answer=render_claims(answer.claims);answer.insufficient_evidence=True
    views=validate_claims(answer,catalog,sources)
    assert [v['verification'] for v in views]==['tool_exact','unverified','unverified']
    answer.insufficient_evidence=False
    with pytest.raises(AppError) as exc: validate_claims(answer,catalog,sources)
    assert exc.value.body['code']=='CLAIM_UNKNOWN_STATUS'
    answer.insufficient_evidence=True;suggestion.evidence_ids=[]
    with pytest.raises(AppError) as exc: validate_claims(answer,catalog,sources)
    assert exc.value.body['code']=='CLAIM_SUGGESTION_UNGROUNDED'


def test_original_live_failure_rejected_without_changing_artifact(client, app, monkeypatch):
    use_scenario(monkeypatch)
    project=register(client)['projects'][0]['id']
    path=Path(__file__).resolve().parents[2]/'docs/verification/v11-live-20261004/round/target-project.json'
    before=path.read_bytes();text=json.loads(before)['analysis']['answer']
    with app.state.factory() as db:
        actual=inventory(snapshot_for(db,project))
    with pytest.raises(AppError): validate_reason_text(text,actual)
    assert path.read_bytes()==before


@pytest.mark.parametrize('always',[False,True])
@pytest.mark.parametrize('fault,error',[('count','QUALITY_REASON_MISATTRIBUTION'),
                                       ('object','QUALITY_REASON_OBJECT_MISMATCH'),
                                       ('fact','CLAIM_FACT_MISMATCH'), ('missing','CLAIMS_REQUIRED')])
def test_controlled_correction_failure_and_raw_retention(client,app,monkeypatch,always,fault,error):
    class Variant(ScanProvider):
        async def complete(self,messages,final=False):
            message,meta=await super().complete(messages,final)
            if final and (always or self.finals==1):
                payload=json.loads(message['content'])
                if fault=='count': payload['answer']+='\n\n2个因14日消耗记录缺日。'
                if fault=='object': payload['answer']+='\n\n建议对采样管的缺日补齐记录。'
                if fault=='fact': payload['claims'][0]['text']='已确认所有物资库存充足。'
                if fault=='missing': payload.pop('claims')
                message['content']=json.dumps(payload,ensure_ascii=False)
            return message,meta
    provider=Variant();project,run=setup(client,app,monkeypatch,provider)
    assert provider.finals==2
    with app.state.factory() as db:
        state=db.get(Run,run['run_id']).checkpoint
        assert len(state['final_outputs'])==2
        assert sum(m['usage']['total_tokens'] for m in state['metadata'])==(400 if always else 300)
    if always:
        assert run['status']=='failed' and run['error']['code']==error and run['analysis_id'] is None
    else:
        assert run['status']=='succeeded',run
        body=client.get('/api/v1/analyses/'+run['analysis_id']).json()
        assert all(c['verification']=='tool_exact' for c in body['claims'])
        assert {g['reason']:g['count'] for g in body['reason_breakdown']}=={
            'MISSING_CONSUMPTION_DAYS':1,'STALE_SNAPSHOT':1,'ZERO_CONSUMPTION':1}
        assert sum(m['usage']['total_tokens'] for m in body['provider_metadata']['calls'])==400
        from app.data import canonical_hash
        evidence=body['citations'][0]['facts']
        assert evidence['reason_breakdown_hash']==canonical_hash(evidence['reason_breakdown'])
        assert evidence['reason_breakdown']==body['reason_breakdown']
    assert client.get(f'/api/v1/projects/{project}/tasks').json()==[]


def test_history_untouched_and_fact_catalog_same_evidence_scope(client,app,monkeypatch):
    project=register(client)['projects'][0]['id']
    old=create_run(client,project,body=request_body())
    work_once(app.state.factory,app.state.settings)
    old=client.get('/api/v1/runs/'+old['run_id']).json()
    oldbody=client.get('/api/v1/analyses/'+old['analysis_id']).json()
    oldsources={c['evidence_id']:client.get('/api/v1/evidence/'+c['evidence_id']).json() for c in oldbody['citations']}
    app.state.settings.llm_provider='deepseek'
    new=create_run(client,project,'new-v12-run',request_body())
    work_once(app.state.factory,app.state.settings,ScanProvider())
    new=client.get('/api/v1/runs/'+new['run_id']).json();assert new['status']=='succeeded',new
    body=client.get('/api/v1/analyses/'+new['analysis_id']).json()
    assert body['risk_summary']['scanned_positions']==1
    with app.state.factory() as db:
        state=db.get(Run,new['run_id']).checkpoint
        assert state['quality_contract']=='v12-claims-1'
        for fact in state['fact_catalog']:
            for eid in fact['evidence_ids']:
                evidence=db.get(Evidence,eid)
                assert evidence.run_id==new['run_id'] and evidence.project_id==project
    assert client.get('/api/v1/analyses/'+old['analysis_id']).json()==oldbody
    assert {eid:client.get('/api/v1/evidence/'+eid).json() for eid in oldsources}==oldsources


def test_structured_advice_cannot_bypass_no_advice_limit(client,app,monkeypatch):
    class Advice(ScanProvider):
        async def complete(self,messages,final=False):
            msg,meta=await super().complete(messages,final)
            if final:
                payload=json.loads(msg['content'])
                claim=AnswerClaim(kind='suggestion',text='核对原始台账',evidence_ids=payload['evidence_ids'])
                payload['claims'].append(claim.model_dump())
                payload['answer']+='\n\n'+render_claims([claim])
                msg['content']=json.dumps(payload,ensure_ascii=False)
            return msg,meta
    use_scenario(monkeypatch);app.state.settings.llm_provider='deepseek'
    project=register(client)['projects'][0]['id']
    run=create_run(client,project,body=request_body('不要处理建议',item_ids=[]))
    work_once(app.state.factory,app.state.settings,Advice())
    run=client.get('/api/v1/runs/'+run['run_id']).json()
    assert run['status']=='failed' and run['error']['code']=='ANSWER_SCOPE_VIOLATION'


def test_legacy_checkpoint_is_not_relabelled_as_new_quality(client,app):
    import asyncio
    from app.agent import claim,execute,initial_state
    project=register(client)['projects'][0]['id']
    app.state.settings.llm_provider='deepseek'
    run=create_run(client,project)
    run_id,fence=claim(app.state.factory,app.state.settings)
    with app.state.factory() as db:
        row=db.get(Run,run_id);state=initial_state(db,row)
        for key in ('quality_contract','fact_catalog','reason_rows','reason_evidence_ids'): state.pop(key)
        row.checkpoint=state;db.commit()
    asyncio.run(execute(app.state.factory,app.state.settings,run_id,fence,ScanProvider()))
    result=client.get('/api/v1/runs/'+run['run_id']).json()
    assert result['status']=='succeeded',result
    body=client.get('/api/v1/analyses/'+result['analysis_id']).json()
    assert body['provider_metadata']['quality_contract']=='legacy'
    assert body['claims'] is None and body['reason_breakdown'] is None
