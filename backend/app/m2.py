"""M2 API: deterministic read surfaces and human-confirmed personal tasks."""
import time
from fastapi import Depends, Query
from sqlalchemy import select, update
from .models import Run, Analysis, TaskDraft, PersonalTask, Document
from .schemas import RiskReport, ItemDetails, DraftView, DraftConfirm, RevisionRequest, TaskUpdate, TaskView, RunView
from .auth import require_project
from .data import snapshot_for, canonical_hash
from .knowledge import active
from .operations import details, risks
from .errors import AppError
from .agent import iso
from .catalog import lock_project
from .human_review import blockers


def conversation(db, run, limit=12):
    chain = []
    while run:
        chain.append(run)
        if len(chain) >= limit:
            break
        parent_id = run.request.get('parent_run_id')
        run = db.get(Run, parent_id) if parent_id else None
    return list(reversed(chain))


def bind_parent(db, user, project_id, body):
    if body.mode == 'analyze':
        if body.parent_run_id or body.session_id or body.context.analysis_id:
            raise AppError('INVALID_PARENT', '新核查不能指定历史会话', 422)
        return None
    if not body.parent_run_id:
        raise AppError('INVALID_PARENT', '追问和草稿需要指定原核查', 422)
    parent = db.get(Run, body.parent_run_id)
    if not parent or parent.project_id != project_id or parent.actor_id != user.id:
        raise AppError('NOT_FOUND', '原核查不存在或不可访问', 404)
    if parent.status != 'succeeded':
        raise AppError('PARENT_NOT_READY', '请等待原核查成功后继续', 409)
    if len(conversation(db, parent, 12)) >= 12:
        raise AppError('CONVERSATION_LIMIT', '会话已达12轮，请基于当前数据新建核查', 409)
    analysis = db.scalar(select(Analysis).where(Analysis.run_id == parent.id))
    scope = parent.request['context']
    if (body.session_id and body.session_id != parent.session_id or
        body.context.snapshot_set_id and body.context.snapshot_set_id != parent.snapshot_id or
        body.context.analysis_id and body.context.analysis_id != analysis.id or
        body.context.item_ids and body.context.item_ids != scope['item_ids'] or
        body.context.department_ids and body.context.department_ids != scope['department_ids']):
        raise AppError('FOLLOW_UP_SCOPE_CONFLICT', '追问须沿用原物资、科室与快照；变更范围请新建核查', 409)
    body.context.snapshot_set_id = parent.snapshot_id
    body.context.item_ids = scope['item_ids']
    body.context.department_ids = scope['department_ids']
    body.context.analysis_id = analysis.id
    body.session_id = parent.session_id
    return parent


def register_routes(app, db_dep, user_dep, get_run, run_view):
    def owned(db, user, model, id):
        row = db.get(model, id)
        if not row or row.actor_id != user.id:
            raise AppError('NOT_FOUND', '记录不存在或不可访问', 404)
        require_project(db, user.id, row.project_id)
        return row

    def stale(db, draft):
        if snapshot_for(db, draft.project_id).id != draft.snapshot_id:
            return '已有新数据快照，请重新核查并生成草稿'
        analysis = db.get(Analysis, draft.analysis_id)
        for citation in analysis.body['citations']:
            if citation['source_kind'] == 'document':
                doc = db.get(Document, citation['location']['document_id'])
                if not doc or doc.project_id != draft.project_id or not active(doc) or doc.source_hash != citation['hash']:
                    return '原知识依据已失效，请重新核查并生成草稿'
        return None

    def task_view(db, task):
        draft = db.get(TaskDraft, task.draft_id)
        return {k: getattr(task, k) for k in ['id', 'draft_id', 'title', 'steps', 'due_date', 'status', 'result', 'revision', 'history']} | {
            'review_blockers': blockers(db, db.get(Run, draft.run_id)), 'analysis_id': draft.analysis_id, 'run_id': draft.run_id, 'updated_at': iso(task.updated_at)}

    def draft_view(db, draft):
        return {'review_blockers': blockers(db, db.get(Run, draft.run_id)), 'id': draft.id, 'run_id': draft.run_id, 'analysis_id': draft.analysis_id, 'snapshot_set_id': draft.snapshot_id,
                **draft.content, 'revision': draft.revision, 'status': draft.status,
                'task_id': db.scalar(select(PersonalTask.id).where(PersonalTask.draft_id == draft.id)), 'stale_reason': stale(db, draft)}

    @app.get('/api/v1/projects/{project_id}/risks', response_model=RiskReport)
    def risk_report(project_id: str, snapshot_set_id: str | None = None, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        return risks(snapshot_for(db, project_id, snapshot_set_id))

    @app.get('/api/v1/projects/{project_id}/item-details', response_model=ItemDetails)
    def item_details(project_id: str, item_id: str = Query(min_length=1), department_id: str | None = None, snapshot_set_id: str | None = None, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        return details(snapshot_for(db, project_id, snapshot_set_id), [item_id], [department_id] if department_id else [])

    @app.get('/api/v1/runs/{run_id}/conversation', response_model=list[RunView])
    def run_conversation(run_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        run = get_run(db, user, run_id)
        if run.actor_id != user.id:
            raise AppError('NOT_FOUND', '会话不存在或不可访问', 404)
        return [run_view(db, r) for r in conversation(db, run)]

    @app.get('/api/v1/drafts/{draft_id}', response_model=DraftView)
    def read_draft(draft_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        return draft_view(db, owned(db, user, TaskDraft, draft_id))

    @app.post('/api/v1/drafts/{draft_id}/confirm', response_model=TaskView)
    def confirm(draft_id: str, body: DraftConfirm, user=Depends(user_dep), db=Depends(db_dep)):
        draft = owned(db, user, TaskDraft, draft_id)
        lock_project(db, draft.project_id)
        db.expire_all()
        require_project(db, user.id, draft.project_id)
        db.refresh(draft)
        fingerprint = canonical_hash(body.model_dump())
        changed = db.execute(update(TaskDraft).where(TaskDraft.id == draft.id, TaskDraft.status == 'pending', TaskDraft.revision == body.revision).values(status='confirmed', revision=TaskDraft.revision + 1, confirmation_hash=fingerprint)).rowcount
        db.refresh(draft)
        if not changed:
            existing = db.scalar(select(PersonalTask).where(PersonalTask.draft_id == draft.id))
            if existing and draft.confirmation_hash == fingerprint:
                return task_view(db, existing)
            raise AppError('REVISION_CONFLICT', '草稿已处理或内容版本不一致，请刷新', 409)
        blocked = blockers(db, db.get(Run, draft.run_id))
        if blocked:
            raise AppError('HUMAN_REVIEW_REQUIRED', blocked[0]['message'], 409)
        reason = stale(db, draft)
        if reason:
            raise AppError('EVIDENCE_CHANGED', reason, 409)
        task = PersonalTask(draft_id=draft.id, project_id=draft.project_id, actor_id=user.id, title=body.title, steps=body.steps, due_date=body.due_date,
                            history=[{'status': 'todo', 'result': '已确认草稿并建立本人待办', 'at': iso(time.time()), 'actor_id': user.id}])
        db.add(task)
        db.commit()
        return task_view(db, task)

    @app.post('/api/v1/drafts/{draft_id}/reject', response_model=DraftView)
    def reject(draft_id: str, body: RevisionRequest, user=Depends(user_dep), db=Depends(db_dep)):
        draft = owned(db, user, TaskDraft, draft_id)
        changed = db.execute(update(TaskDraft).where(TaskDraft.id == draft.id, TaskDraft.status == 'pending', TaskDraft.revision == body.revision).values(status='rejected', revision=TaskDraft.revision + 1)).rowcount
        if not changed:
            raise AppError('REVISION_CONFLICT', '草稿已处理，请刷新', 409)
        db.commit()
        db.refresh(draft)
        return draft_view(db, draft)

    @app.get('/api/v1/projects/{project_id}/tasks', response_model=list[TaskView])
    def tasks(project_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        return [task_view(db, t) for t in db.scalars(select(PersonalTask).where(PersonalTask.project_id == project_id, PersonalTask.actor_id == user.id).order_by(PersonalTask.created_at.desc()))]

    @app.get('/api/v1/tasks/{task_id}', response_model=TaskView)
    def read_task(task_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        return task_view(db, owned(db, user, PersonalTask, task_id))

    @app.patch('/api/v1/tasks/{task_id}', response_model=TaskView)
    def update_task(task_id: str, body: TaskUpdate, user=Depends(user_dep), db=Depends(db_dep)):
        task = owned(db, user, PersonalTask, task_id)
        transitions = {'todo': {'in_progress', 'cancelled'}, 'in_progress': {'completed', 'cancelled'}, 'completed': {'todo'}, 'cancelled': {'todo'}}
        if body.status not in transitions[task.status]:
            raise AppError('INVALID_TRANSITION', '不支持该状态变更，请刷新任务', 409)
        if body.status == 'completed' and not body.result.strip():
            raise AppError('RESULT_REQUIRED', '完成任务必须填写处理结果', 422)
        now = time.time()
        result = body.result.strip()
        changed = db.execute(update(PersonalTask).where(PersonalTask.id == task.id, PersonalTask.revision == body.revision).values(
            status=body.status, result=result, revision=PersonalTask.revision + 1, updated_at=now,
            history=task.history + [{'status': body.status, 'result': result, 'at': iso(now), 'actor_id': user.id}])).rowcount
        if not changed:
            raise AppError('REVISION_CONFLICT', '任务已更新，请刷新后重试', 409)
        db.commit()
        db.refresh(task)
        return task_view(db, task)
