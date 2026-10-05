"""Author development evaluation. Reads generated files; no .env or provider calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.claim_support import fact_catalog,reason_breakdown,render_claims,validate_claims,validate_reason_text,RELEASE
from app.data import inventory,AS_OF,canonical_hash
from app.operations import risks
from app.schemas import ModelAnswer,AnswerClaim,TaskProposal
from app.errors import AppError

ROOT=Path(__file__).resolve().parents[2]
DATASET=Path(__file__).with_name('v12_quality_dataset.json')
ORIGINAL=ROOT/'docs/verification/v11-live-20261004/round/target-project.json'


def inputs():
    facts={}
    for name in ['inventory_snapshots','inventory_batches','consumption_daily','products','departments']:
        data=json.loads((ROOT/'data/scenario'/f'{name}.json').read_text())
        facts[name]=[r for r in data if name=='products' or r['hospital_id']=='SIM-HA']
    return SimpleNamespace(id='offline-v12-snapshot',as_of=AS_OF,facts=facts)


def evaluate():
    snapshot=inputs();rows=inventory(snapshot);raw=DATASET.read_bytes();dataset=json.loads(raw)
    original_raw=ORIGINAL.read_bytes();original=json.loads(original_raw)
    report=risks(snapshot);catalog=fact_catalog('risks',report,rows,'offline-e1')
    results=[]
    for case in dataset['reasons'] + [{'id':'R-original-live','text':original['analysis']['answer'],'error':'QUALITY_REASON_MISATTRIBUTION'}]:
        error=None
        try: validate_reason_text(case['text'],rows)
        except AppError as exc: error=exc.body['code']
        results.append({**case,'actual_error':error,'passed':error==case['error']})
    sources={'offline-e1':{'source_kind':'tool'},'offline-e2':{'source_kind':'document','excerpt':'缺失记录不得补零，应先核对原始台账。'}}
    for case in dataset['claims']:
        f=catalog[0];claim=AnswerClaim(kind='fact',text=f['text'],evidence_ids=f['evidence_ids'],fact_ids=[f['fact_id']])
        a=ModelAnswer(answer=render_claims([claim]),claims=[claim],evidence_ids=['offline-e1'],insufficient_evidence=False)
        fault=case['fault']
        if fault=='wrong-text': a.claims[0].text='所有物资风险均已排除。'
        if fault=='wrong-id': a.claims[0].fact_ids=['another-run-fact']
        if fault=='wrong-source': a.claims[0].evidence_ids=['offline-e2']
        if fault=='foreign-source': a.claims[0].evidence_ids=['other-project-evidence']
        if fault=='no-claims': a.claims=[]
        if fault=='extra-prose': a.answer+='\n\n已完成采购。'
        if fault=='unused-source': a.evidence_ids.append('offline-e2')
        if fault in {'quote','fake-quote','tool-as-policy'}:
            a.claims.append(AnswerClaim(kind='policy',text='缺失记录不得补零' if fault=='quote' else '缺失记录必须补零',evidence_ids=['offline-e2']))
            if fault=='tool-as-policy': a.claims[-1].evidence_ids=['offline-e1'];a.claims[-1].text=f['text']
        if fault in {'suggestion','ungrounded'}:
            a.claims.append(AnswerClaim(kind='suggestion',text='核对原始台账',evidence_ids=['offline-e1'] if fault=='suggestion' else []))
        if fault=='unknown': a.claims.append(AnswerClaim(kind='unknown',text='是否存在未同步记录需确认。'))
        if fault=='draft-bypass': a.task_draft=TaskProposal(title='核查',steps=['未经关联的操作'])
        if fault in {'quote','fake-quote','tool-as-policy','suggestion','ungrounded','unknown'}:
            a.answer=render_claims(a.claims);a.evidence_ids=list(dict.fromkeys(e for c in a.claims for e in c.evidence_ids))
        error=None;views=[]
        try: views=validate_claims(a,catalog,sources)
        except AppError as exc: error=exc.body['code']
        results.append({**case,'actual_error':error,'verification':[c['verification'] for c in views],'passed':error==case['error']})
    return {'kind':'offline_author_development','quality_contract':RELEASE,'dataset_version':dataset['version'],
            'dataset_sha256':hashlib.sha256(raw).hexdigest(),'scenario_sha256':canonical_hash(snapshot.facts),
            'original_sha256':hashlib.sha256(original_raw).hexdigest(),'original_unchanged':ORIGINAL.read_bytes()==original_raw,
            'provider_calls':0,'business_database_used':False,'blind_test':False,
            'reason_breakdown':reason_breakdown(rows,'offline-e1'),
            'results':results,'passed':sum(r['passed'] for r in results),'total':len(results),
            'limitations':['作者开发及已曝光回归，非独立盲测','建议来源关联不证明语义支持','规则未覆盖任意自然语言','无真实模型或业务验收']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=evaluate();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['passed','total','provider_calls','original_sha256']},ensure_ascii=False))
    sys.exit(0 if result['passed']==result['total'] and result['original_unchanged'] else 1)
