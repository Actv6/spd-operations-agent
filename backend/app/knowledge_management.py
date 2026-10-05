"""Manual, version-preserving knowledge publication. No provider or filesystem writes."""
import hashlib
from typing import Annotated
from fastapi import Depends, Header
from sqlalchemy import select, func
from .auth import require_project
from .catalog import editable, lock_project
from .models import Document, Chunk, KnowledgeChange, uid
from .knowledge import chunks, active, today
from .data import canonical_hash
from .errors import AppError
from .versions import iso
from .quality_schemas import (KnowledgeWrite, KnowledgePublish, KnowledgeRetire,
                              KnowledgePreview, KnowledgeManagement, KnowledgeMutation)


def catalog_token(db, project_id):
    rows = db.execute(select(Document.id, Document.title, Document.version, Document.status,
                      Document.effective_from, Document.effective_until, Document.source_hash)
                      .where(Document.project_id == project_id).order_by(Document.id)).all()
    return canonical_hash({'date': today(), 'documents': [list(r) for r in rows]})


def authorize(db, user, project_id):
    project = require_project(db, user.id, project_id)
    if not editable(db, user.id, project_id):
        raise AppError('FORBIDDEN', '当前账号没有知识维护权限', 403)
    return project


def validate_document(db, project_id, body):
    existing = db.scalars(select(Document).where(Document.project_id == project_id, Document.title == body.title)).all()
    if any(d.version == body.version for d in existing):
        raise AppError('IMMUTABLE_VERSION', '该名称与版本已存在，请使用新版本号', 409)
    if any(d.status == 'approved_demo' and (d.effective_until is None or d.effective_until >= today()) for d in existing):
        raise AppError('KNOWLEDGE_CONFLICT', '存在同名有效或待生效版本，请先核实并停用旧版本', 409)
    parts = list(chunks(body.content))
    if not parts:
        raise AppError('EMPTY_DOCUMENT', '资料需要包含可检索的正文，不能只有标题', 422)
    return parts


def old_mutation(db, project_id, actor_id, key, request_hash):
    old = db.scalar(select(KnowledgeChange).where(KnowledgeChange.project_id == project_id,
                    KnowledgeChange.actor_id == actor_id, KnowledgeChange.idempotency_key == key))
    if old and old.request_hash != request_hash:
        raise AppError('IDEMPOTENCY_CONFLICT', '重复请求内容不同，请重新提交', 409)
    return old


def mutation_view(row):
    return {'document_id': row.document_id, 'change_id': row.id}


def register_routes(app, db_dep, user_dep):
    @app.get('/api/v1/projects/{project_id}/knowledge/manage', response_model=KnowledgeManagement)
    def manage(project_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        docs = db.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.title, Document.version)).all()
        counts = dict(db.execute(select(Chunk.document_id, func.count()).join(Document)
                      .where(Document.project_id == project_id).group_by(Chunk.document_id)).all())
        history = db.execute(select(KnowledgeChange, Document).join(Document)
                     .where(KnowledgeChange.project_id == project_id).order_by(KnowledgeChange.created_at.desc()).limit(100)).all()
        return {'can_manage': editable(db, user.id, project_id), 'catalog_token': catalog_token(db, project_id),
                'items': [{'document_id': d.id, 'title': d.title, 'version': d.version, 'effective_from': d.effective_from,
                           'effective_until': d.effective_until, 'currently_valid': active(d),
                           'chunk_count': counts.get(d.id, 0), 'source_hash': d.source_hash} for d in docs],
                'history': [{'id': h.id, 'document_id': d.id, 'title': d.title, 'version': d.version,
                             'action': h.action, 'reason': h.reason, 'created_at': iso(h.created_at)} for h, d in history]}

    @app.post('/api/v1/projects/{project_id}/knowledge/preview', response_model=KnowledgePreview)
    def preview(project_id: str, body: KnowledgeWrite, user=Depends(user_dep), db=Depends(db_dep)):
        authorize(db, user, project_id)
        parts = validate_document(db, project_id, body)
        return {'catalog_token': catalog_token(db, project_id), 'preview_hash': canonical_hash(body.model_dump()),
                'source_hash': hashlib.sha256(body.content.encode()).hexdigest(), 'chunk_count': len(parts),
                'excerpts': [p[3] for p in parts[:3]], 'effective_from': today()}

    @app.post('/api/v1/projects/{project_id}/knowledge/publish', response_model=KnowledgeMutation)
    def publish(project_id: str, body: KnowledgePublish,
                idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
                user=Depends(user_dep), db=Depends(db_dep)):
        authorize(db, user, project_id)
        lock_project(db, project_id)
        authorize(db, user, project_id)
        request_hash = canonical_hash({'action': 'publish', **body.model_dump()})
        old = old_mutation(db, project_id, user.id, idempotency_key, request_hash)
        if old:
            return mutation_view(old)
        data = KnowledgeWrite(**body.model_dump(include=set(KnowledgeWrite.model_fields)))
        if body.catalog_token != catalog_token(db, project_id) or body.preview_hash != canonical_hash(data.model_dump()):
            raise AppError('KNOWLEDGE_PREVIEW_STALE', '目录或正文已变化，请重新预览后发布', 409)
        parts = validate_document(db, project_id, data)
        doc_id = uid()
        doc = Document(id=doc_id, project_id=project_id, external_id='manual-' + doc_id,
              title=data.title, version=data.version, content=data.content, status='approved_demo',
              effective_from=today(), effective_until=None, source_hash=hashlib.sha256(data.content.encode()).hexdigest(),
              source_path='manual/' + doc_id, synthetic=True)
        db.add(doc)
        db.flush()
        for chapter, start, end, text in parts:
            db.add(Chunk(document_id=doc_id, chapter=chapter, start_offset=start, end_offset=end, text=text))
        change = KnowledgeChange(project_id=project_id, document_id=doc_id, actor_id=user.id,
                 idempotency_key=idempotency_key, request_hash=request_hash, action='publish', reason=data.source_note)
        db.add(change)
        db.commit()
        return mutation_view(change)

    @app.post('/api/v1/knowledge/documents/{document_id}/retire', response_model=KnowledgeMutation)
    def retire(document_id: str, body: KnowledgeRetire,
               idempotency_key: Annotated[str, Header(min_length=8, max_length=100)],
               user=Depends(user_dep), db=Depends(db_dep)):
        doc = db.get(Document, document_id)
        if not doc:
            raise AppError('NOT_FOUND', '资料不存在或不可访问', 404)
        authorize(db, user, doc.project_id)
        lock_project(db, doc.project_id)
        authorize(db, user, doc.project_id)
        db.refresh(doc)
        request_hash = canonical_hash({'action': 'retire', 'document_id': document_id, **body.model_dump()})
        old = old_mutation(db, doc.project_id, user.id, idempotency_key, request_hash)
        if old:
            return mutation_view(old)
        if body.catalog_token != catalog_token(db, doc.project_id):
            raise AppError('KNOWLEDGE_PREVIEW_STALE', '目录已变化，请刷新后重新确认', 409)
        if doc.status == 'retired':
            raise AppError('KNOWLEDGE_ALREADY_RETIRED', '资料已停用', 409)
        doc.status = 'retired'
        change = KnowledgeChange(project_id=doc.project_id, document_id=doc.id, actor_id=user.id,
                 idempotency_key=idempotency_key, request_hash=request_hash, action='retire', reason=body.reason)
        db.add(change)
        db.commit()
        return mutation_view(change)
