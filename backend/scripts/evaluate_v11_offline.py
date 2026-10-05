"""Standalone developer-authored challenge set. No provider, .env, or business DB access."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.answer_quality import validate_business_answer
from app.schemas import ModelAnswer
from app.errors import AppError
from app.db import make_engine, session_factory
from app.models import Base, Organization, Project, Document, Chunk
from app.knowledge import search, chunks

SUMMARY = dict(scanned_positions=24, skipped_estimates=3, data_quality=2, zero_consumption=1, findings=8)
COUNTS = {'high': 3, 'medium': 5}
CASES = [
    ('wrong_plain', '高关注2条，中关注6条', 'RISK_PRIORITY_COUNT_MISMATCH'),
    ('wrong_modifier', '高关注共有两项', 'RISK_PRIORITY_COUNT_MISMATCH'),
    ('wrong_fullwidth', '**中关注**：共６条', 'RISK_PRIORITY_COUNT_MISMATCH'),
    ('wrong_reverse', '二项属于高关注', 'RISK_PRIORITY_COUNT_MISMATCH'),
    ('correct_chinese', '高关注三条，中关注五条', None),
    ('correct_markdown', '**高关注**：共有３项', None),
    ('no_count', '请按清单优先核实效期。', None),
    ('absence_overclaim', '本项目知识库中不存在适用制度。', 'KNOWLEDGE_ABSENCE_OVERCLAIM'),
    ('bounded_absence', '本次未检索到适用制度。', None),
    ('unknown_code', '请核查MAT-UNKNOWN。', 'ANSWER_CODE_INVALID'),
    ('field_leak', '请查看coverage_days。', 'ANSWER_LANGUAGE_INVALID'),
]
DOCS = [
    ('gap', '消耗缺日核查', '消耗缺失记录不能补零，需要核对原始台账。', 'approved_demo', '2000-01-01', None, 'p'),
    ('expiry', '临期物资核查', '批次效期临近时核对到期日期和可用数量。', 'approved_demo', '2000-01-01', None, 'p'),
    ('old', '过期旧制度', '旧制度要求缺失记录默认补零。', 'retired', '2000-01-01', None, 'p'),
    ('future', '未来制度', '未来暗号的消耗核查规则。', 'approved_demo', '2099-01-01', None, 'p'),
    ('private', '其他项目资料', '隔离暗号属于其他项目。', 'approved_demo', '2000-01-01', None, 'other'),
]
QUERIES = [
    ('exact', '消耗缺日核查', ['gap']),
    ('paraphrase', '消耗记录缺了怎么办', ['gap']),
    ('expiry', '批次快到期了', ['expiry']),
    ('no_match', '量子飞船曲率引擎', []),
    ('future_filter', '未来暗号', []),
    ('project_filter', '隔离暗号', []),
    # Deliberate lexical limitation: keep the miss in reports; do not tune it away.
    ('colloquial_gap', '有几天的用量没填咋办', ['gap']),
]


def evaluate():
    guard = []
    for name, text, expected in CASES:
        actual = None
        try:
            validate_business_answer(ModelAnswer(answer=text, evidence_ids=[], insufficient_evidence=True,
                                      risk_summary=SUMMARY), SUMMARY, [], expected_priority_counts=COUNTS)
        except AppError as exc:
            actual = exc.body['code']
        guard.append({'case': name, 'text': text, 'expected_error': expected, 'actual_error': actual, 'passed': expected == actual})
    engine = make_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    retrieval = []
    with session_factory(engine)() as db:
        db.add(Organization(id='org', name='离线挑战集'))
        db.flush()
        for pid in ['p', 'other']:
            db.add(Project(id=pid, org_id='org', name=pid))
        db.flush()
        for key, title, content, status, start, end, project in DOCS:
            db.add(Document(id=key, project_id=project, external_id=key, title=title, version='1', content=content,
                   status=status, effective_from=start, effective_until=end, source_path=key,
                   source_hash=hashlib.sha256(content.encode()).hexdigest()))
            db.flush()
            for chapter, a, b, excerpt in chunks(content):
                db.add(Chunk(document_id=key, chapter=chapter, start_offset=a, end_offset=b, text=excerpt))
        db.flush()
        for name, query, expected in QUERIES:
            hits = search(db, 'p', query, on='2026-10-01', limit=3)
            actual = list(dict.fromkeys(h['document_id'] for h in hits))
            offsets_valid = all(db.get(Document, h['document_id']).content[h['start_offset']:h['end_offset']] == h['excerpt'] for h in hits)
            passed = (set(expected) <= set(actual) if expected else not actual) and offsets_valid
            retrieval.append({'case': name, 'query': query, 'expected_documents': expected,
                              'actual_documents': actual, 'offsets_valid': offsets_valid, 'passed': passed})
    engine.dispose()
    return {'kind': 'offline_guard_and_lexical_challenge', 'dataset_version': 'v11-dev-1',
            'dataset_hash': hashlib.sha256(json.dumps([CASES, DOCS, QUERIES], ensure_ascii=False).encode()).hexdigest(),
            'provider_calls': 0, 'business_database_used': False, 'blind_test': False,
            'limitations': ['作者自建开发挑战集，不是独立业务盲测', '不测真实模型输出、句子蕴含、生产时延或价格', '词法口语漏召回保留为失败'],
            'guards': guard, 'retrieval': retrieval,
            'summary': {'guard_passed': sum(c['passed'] for c in guard), 'guard_total': len(guard),
                        'retrieval_passed': sum(c['passed'] for c in retrieval), 'retrieval_total': len(retrieval)}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report['summary'], ensure_ascii=False))
    sys.exit(0 if all(c['passed'] for c in report['guards'] + report['retrieval']) else 1)
