"""Offline author-authored quality evaluation; no .env, provider or business DB."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import answer_quality
from app.schemas import ModelAnswer
from app.errors import AppError
from app.db import make_engine, session_factory
from app.models import Base, Organization, Project, Document, Chunk
from app.knowledge import search, chunks
from evaluate_v11_offline import CASES, SUMMARY, COUNTS

DATASET = Path(__file__).with_name('quality_close_dataset.json')


def evaluate(split='dev'):
    raw = DATASET.read_bytes()
    dataset = json.loads(raw)
    guards = []
    cases = [dict(id=name, answer=text, error=expected) for name, text, expected in CASES] + dataset['guards']
    for case in cases:
        actual = None
        try:
            answer_quality.validate_business_answer(ModelAnswer(answer=case['answer'], evidence_ids=[],
                insufficient_evidence=True, risk_summary=SUMMARY), SUMMARY, [], expected_priority_counts=COUNTS)
            if hasattr(answer_quality, 'validate_answer_scope'):
                answer_quality.validate_answer_scope(case.get('question', ''), case['answer'])
        except AppError as exc:
            actual = exc.body['code']
        guards.append({**case, 'actual_error': actual, 'passed': actual == case['error']})
    engine = make_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    results = []
    with session_factory(engine)() as db:
        db.add(Organization(id='org', name='离线质量评测'))
        db.flush()
        for pid in ['p', 'other']:
            db.add(Project(id=pid, org_id='org', name=pid))
        db.flush()
        for row in dataset['documents']:
            db.add(Document(id=row['id'], project_id=row['project'], external_id=row['id'], title=row['title'],
                version='1', content=row['content'], status=row['status'], effective_from=row['start'],
                effective_until=row['end'], source_path=row['id'], source_hash=hashlib.sha256(row['content'].encode()).hexdigest()))
            db.flush()
            for chapter, a, b, excerpt in chunks(row['content']):
                db.add(Chunk(document_id=row['id'], chapter=chapter, start_offset=a, end_offset=b, text=excerpt))
        db.flush()
        for case in dataset['queries']:
            if split != 'all' and case['split'] != split:
                continue
            hits = search(db, 'p', case['query'], on=dataset['on'], limit=3)
            ids = list(dict.fromkeys(h['document_id'] for h in hits))
            offsets_ok = all(db.get(Document, h['document_id']).content[h['start_offset']:h['end_offset']] == h['excerpt'] for h in hits)
            scope_ok = all(db.get(Document, h['document_id']).project_id == 'p' and
                db.get(Document, h['document_id']).status == 'approved_demo' and
                db.get(Document, h['document_id']).effective_from <= dataset['on'] and
                (db.get(Document, h['document_id']).effective_until is None or db.get(Document, h['document_id']).effective_until >= dataset['on']) for h in hits)
            passed = (set(case['expected']) <= set(ids) if case['expected'] else not ids) and offsets_ok and scope_ok
            results.append({**case, 'actual': ids, 'top1': bool(case['expected']) and bool(ids) and ids[0] in case['expected'],
                'irrelevant_hits': [i for i in ids if i not in case['expected']], 'offsets_ok': offsets_ok, 'scope_ok': scope_ok, 'passed': passed})
    engine.dispose()
    metrics = {}
    for group in sorted({r['split'] for r in results}):
        rows = [r for r in results if r['split'] == group]
        targets = [r for r in rows if r['expected']]
        empty = [r for r in rows if not r['expected']]
        metrics[group] = dict(total=len(rows), passed=sum(r['passed'] for r in rows),
            target_queries=len(targets), recall_at_3=sum(set(r['expected']) <= set(r['actual']) for r in targets)/max(1,len(targets)),
            top1_rate=sum(r['top1'] for r in targets)/max(1,len(targets)), no_match_queries=len(empty),
            false_positive_queries=sum(bool(r['actual']) for r in empty), irrelevant_hits=sum(len(r['irrelevant_hits']) for r in rows),
            scope_failures=sum(not r['scope_ok'] for r in rows), offset_failures=sum(not r['offsets_ok'] for r in rows))
    return dict(kind='offline_author_quality_close',dataset_version=dataset['version'],dataset_hash=hashlib.sha256(raw).hexdigest(),
        provider_calls=0,business_database_used=False,blind_test=False, split=split,
        limitations=['作者开发集与作者保留集，非独立盲测', '无真实模型或通用语义证明', '无关召回单列，不算精准检索通过'],
        guards=guards,retrieval=results,metrics=metrics,guard_passed=sum(r['passed'] for r in guards),guard_total=len(guards))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--split', choices=['dev','author_holdout','all'], default='dev')
    args = parser.parse_args()
    report = evaluate(args.split)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['metrics','guard_passed','guard_total']},ensure_ascii=False))
    sys.exit(0 if all(r['passed'] for r in report['guards'] + report['retrieval']) else 1)
