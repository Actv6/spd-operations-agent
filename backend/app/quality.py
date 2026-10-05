"""Human feedback is append-only and never edits the answer it evaluates."""
from typing import Annotated
from fastapi import Depends, Header
from sqlalchemy import select
from .models import Analysis, AnalysisFeedback, Run
from .auth import require_project
from .catalog import lock_project
from .data import canonical_hash
from .errors import AppError
from .versions import iso
from .quality_schemas import FeedbackWrite, FeedbackView, FeedbackList


def feedback_view(row):
    return {'id': row.id, 'rating': row.rating, 'comment': row.comment, 'created_at': iso(row.created_at)}


def register_routes(app, db_dep, user_dep):
    def own_analysis(db, user, analysis_id):
        row = db.get(Analysis, analysis_id)
        if not row:
            raise AppError('NOT_FOUND', '核查记录不存在或不可访问', 404)
        require_project(db, user.id, row.project_id)
        run = db.get(Run, row.run_id)
        return row, run

    @app.get('/api/v1/analyses/{analysis_id}/feedback', response_model=FeedbackList)
    def list_feedback(analysis_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        row, run = own_analysis(db, user, analysis_id)
        rows = db.scalars(select(AnalysisFeedback).where(AnalysisFeedback.analysis_id == row.id,
                         AnalysisFeedback.actor_id == user.id).order_by(AnalysisFeedback.created_at.desc())).all()
        return {'items': [feedback_view(r) for r in rows], 'can_submit': run.actor_id == user.id}

    @app.post('/api/v1/analyses/{analysis_id}/feedback', response_model=FeedbackView)
    def create_feedback(analysis_id: str, body: FeedbackWrite,
                        idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
                        user=Depends(user_dep), db=Depends(db_dep)):
        analysis, run = own_analysis(db, user, analysis_id)
        if run.actor_id != user.id:
            raise AppError('FORBIDDEN', '仅可评价本人发起的核查', 403)
        lock_project(db, analysis.project_id)
        db.expire_all()
        # Recheck permissions after waiting for the project serialization lock.
        require_project(db, user.id, analysis.project_id)
        request_hash = canonical_hash(body.model_dump())
        old = db.scalar(select(AnalysisFeedback).where(AnalysisFeedback.actor_id == user.id,
                        AnalysisFeedback.analysis_id == analysis.id, AnalysisFeedback.idempotency_key == idempotency_key))
        if old:
            if old.request_hash != request_hash:
                raise AppError('IDEMPOTENCY_CONFLICT', '重复请求内容不同，请重新提交', 409)
            return feedback_view(old)
        source = analysis.body
        row = AnalysisFeedback(analysis_id=analysis.id, actor_id=user.id, idempotency_key=idempotency_key,
              request_hash=request_hash, **body.model_dump(), context={
                  'run_id': run.id, 'snapshot_set_id': run.snapshot_id, 'generation_mode': source.get('generation_mode'),
                  'ruleset_version': source.get('ruleset_version'), 'model_release_id': source.get('model_release_id'),
                  'knowledge_release_id': source.get('knowledge_release_id'),
                  'prompt_releases': sorted({m['prompt_release'] for m in source.get('provider_metadata', {}).get('calls', []) if m.get('prompt_release')}),
                  'analysis_hash': canonical_hash(source)})
        db.add(row)
        db.commit()
        return feedback_view(row)
