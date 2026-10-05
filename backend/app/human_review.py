"""Human decisions are separate from immutable model answers and tool evidence."""
from typing import Annotated
from fastapi import Depends, Header
from sqlalchemy import select
from .models import (Run, Analysis, Evidence, Document, AnalysisFeedback,
                     HumanReviewState, HumanReviewRecord)
from .auth import require_project
from .catalog import lock_project, editable
from .data import snapshot_for, canonical_hash, inventory
from .knowledge import active
from .operations import risks
from .versions import iso, publication_revision
from .errors import AppError
from .review_schemas import HumanReviewWrite, HumanReviewView

TERMINAL = {'succeeded', 'failed', 'cancelled'}


def context(db, run):
    analysis = db.scalar(select(Analysis).where(Analysis.run_id == run.id))
    body = analysis.body if analysis else {}
    evidence = list(db.scalars(select(Evidence).where(Evidence.run_id == run.id).order_by(Evidence.id)))
    records = list(db.scalars(select(HumanReviewRecord).where(HumanReviewRecord.run_id == run.id)
                            .order_by(HumanReviewRecord.revision.desc())))
    feedback = list(db.scalars(select(AnalysisFeedback).where(
        AnalysisFeedback.analysis_id == analysis.id, AnalysisFeedback.rating == 'needs_correction')
        .order_by(AnalysisFeedback.created_at, AnalysisFeedback.id))) if analysis else []
    handled = {fid for row in records for fid in row.handled_feedback_ids}
    pending = [f for f in feedback if f.id not in handled]
    stale = []
    current_snapshot = snapshot_for(db, run.project_id)
    if current_snapshot.id != run.snapshot_id:
        stale.append('已有新数据版本，请基于最新数据重新核查')
    documents = []
    for e in evidence:
        if e.body['source_kind'] == 'document':
            doc = db.get(Document, e.body['location']['document_id'], populate_existing=True)
            valid = bool(doc and doc.project_id == run.project_id and active(doc) and doc.source_hash == e.body['hash'])
            documents.append([e.id, doc.source_hash if doc else None, doc.status if doc else None, valid])
            if not valid and '引用资料已失效，请核实当前制度' not in stale:
                stale.append('引用资料已失效，请核实当前制度')
    snapshot = snapshot_for(db, run.project_id, run.snapshot_id)
    scope = run.request['context']
    report = risks(snapshot, scope.get('item_ids', []), scope.get('department_ids', []))
    reasons = []
    if any(f['priority'] == 'high' for f in report['findings']):
        reasons.append('范围内存在高关注项')
    if any(f['kind'] == 'quality' for f in report['findings']):
        reasons.append('数据质量需要核实')
    if body.get('insufficient_evidence'):
        reasons.append('AI标记依据不足')
    if not body.get('claims'):
        reasons.append('缺少逐条结论核验，需人工核查')
    if run.request.get('mode') == 'draft_action':
        reasons.append('业务待办须先复核结论')
    if run.status in {'failed', 'cancelled'}:
        reasons.append('AI未完成，可记录人工核查结论')
    if pending:
        reasons.append('存在未处理的纠错反馈')
    last = records[0] if records else None
    status = 'error' if pending else last.status if last else 'pending'
    analysis_hash = canonical_hash(body) if analysis else None
    if last and last.analysis_hash != analysis_hash:
        stale.append('原核查内容已变化，请重新复核')
    if stale and status == 'confirmed':
        status = 'pending'
    token = canonical_hash({'run_id': run.id, 'run_status': run.status, 'snapshot_id': run.snapshot_id,
        'snapshot_hash': snapshot.source_hash, 'current_snapshot_id': current_snapshot.id,
        'publication_revision': publication_revision(db, run.project_id), 'analysis_hash': analysis_hash,
        'documents': documents, 'evidence': [[e.id, canonical_hash(e.body)] for e in evidence],
        'feedback_ids': [f.id for f in feedback]})
    summary = {'status': status, 'required': bool(reasons), 'reasons': reasons,
        'blocked': bool(stale or status in {'error', 'insufficient'} or reasons and status != 'confirmed'),
        'stale_reasons': stale, 'revision': last.revision if last else 0}
    return summary, token, analysis_hash, evidence, records, pending


def summary(db, run):
    return context(db, run)[0]


def view(db, run, user):
    state, token, _, evidence, records, pending = context(db, run)
    return {**state, 'run_id': run.id, 'project_id': run.project_id, 'snapshot_set_id': run.snapshot_id, 'source_token': token,
        'inventory': inventory(snapshot_for(db, run.project_id, run.snapshot_id), run.request['context'].get('item_ids', []), run.request['context'].get('department_ids', [])),
        'can_submit': editable(db, user.id, run.project_id) and run.status in TERMINAL,
        'manual_only': run.status != 'succeeded',
        'available_evidence': [{'evidence_id': e.id, 'title': e.body['title'], 'source_kind': e.body['source_kind']} for e in evidence],
        'pending_feedback': [{'id': f.id, 'comment': f.comment, 'created_at': iso(f.created_at)} for f in pending],
        'items': [{**{k: getattr(r, k) for k in ['id', 'revision', 'status', 'conclusion', 'basis', 'next_step',
            'evidence_ids', 'handled_feedback_ids', 'actor_id', 'actor_name', 'self_review', 'snapshot_set_id',
            'analysis_hash', 'source_token']}, 'created_at': iso(r.created_at)} for r in records]}


def blockers(db, run):
    # Descendant success does not clear an unresolved ancestor's decision.
    result, seen = [], set()
    while run and run.id not in seen:
        seen.add(run.id)
        state = summary(db, run)
        if state['blocked']:
            result.append({'run_id': run.id, 'message': '核查 #' + run.id[:8] + '：' +
                ('；'.join(state['stale_reasons']) if state['stale_reasons'] else
                 '请先处理纠错反馈并完成人工复核')})
        parent_id = run.request.get('parent_run_id')
        run = db.get(Run, parent_id) if parent_id else None
    return result


def register_routes(app, db_dep, user_dep, get_run):
    @app.get('/api/v1/runs/{run_id}/human-review', response_model=HumanReviewView)
    def read(run_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        return view(db, get_run(db, user, run_id), user)

    @app.post('/api/v1/runs/{run_id}/human-review', response_model=HumanReviewView)
    def write(run_id: str, body: HumanReviewWrite,
              idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
              user=Depends(user_dep), db=Depends(db_dep)):
        run = get_run(db, user, run_id)
        lock_project(db, run.project_id)
        db.expire_all()
        require_project(db, user.id, run.project_id)
        if not editable(db, user.id, run.project_id):
            raise AppError('FORBIDDEN', '当前账号没有人工复核权限', 403)
        db.refresh(run)
        request_hash = canonical_hash(body.model_dump())
        previous = db.scalar(select(HumanReviewRecord).where(HumanReviewRecord.run_id == run.id,
            HumanReviewRecord.actor_id == user.id, HumanReviewRecord.idempotency_key == idempotency_key))
        if previous:
            if previous.request_hash != request_hash:
                raise AppError('IDEMPOTENCY_CONFLICT', '重复请求的复核内容不同', 409)
            return view(db, run, user)
        if run.status not in TERMINAL:
            raise AppError('RUN_NOT_TERMINAL', '请等待运行结束或取消后再记录人工结论', 409)
        current, token, analysis_hash, evidence, _, pending = context(db, run)
        if body.revision != current['revision']:
            raise AppError('REVISION_CONFLICT', '复核记录已变化，请刷新后重新核对', 409)
        if body.source_token != token:
            raise AppError('REVIEW_SOURCE_CHANGED', '数据、依据或反馈已变化，请刷新后重新核对', 409)
        allowed = {e.id for e in evidence}
        if not set(body.evidence_ids) <= allowed:
            raise AppError('REVIEW_EVIDENCE_SCOPE', '复核依据必须属于本次核查', 422)
        if set(body.handled_feedback_ids) != {f.id for f in pending}:
            raise AppError('REVIEW_FEEDBACK_REQUIRED', '请明确处理全部待复核纠错反馈', 409)
        if body.status == 'confirmed' and current['stale_reasons']:
            raise AppError('REVIEW_SOURCE_STALE', '来源已变化，请记录问题并基于最新数据重新核查', 409)
        head = db.get(HumanReviewState, run.id)
        if not head:
            head = HumanReviewState(run_id=run.id, revision=0)
            db.add(head)
        head.revision += 1
        db.add(HumanReviewRecord(run_id=run.id, actor_id=user.id, actor_name=user.display_name,
            revision=head.revision, idempotency_key=idempotency_key, request_hash=request_hash,
            **{k: getattr(body, k) for k in ['status', 'conclusion', 'basis', 'next_step', 'evidence_ids', 'handled_feedback_ids']},
            self_review=user.id == run.actor_id, snapshot_set_id=run.snapshot_id,
            analysis_hash=analysis_hash, source_token=token))
        db.commit()
        return view(db, run, user)
