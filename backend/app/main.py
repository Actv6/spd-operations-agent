import time
from typing import Annotated
from fastapi import FastAPI, Request, Response, Depends, Header, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, delete, update, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .config import Settings
from .db import make_engine, session_factory
from .models import User, Organization, Project, Membership, LoginSession, Run, RunEvent, Evidence, Analysis, Document, Chunk, TaskDraft, PersonalTask, uid
from .schemas import Registration, Credentials, RunRequest, MeView, DashboardView, RunView, AnalysisView, EvidenceView, EventsView, ErrorView, KnowledgeSearchView, KnowledgeDocumentsView, KnowledgeDocumentDetail
from .auth import current_user, require_project, me_view, issue_session, hasher, verify_password, DUMMY_HASH, digest, csrf_token, validate_csrf, rate_limit
from .data import seed_snapshot, snapshot_for, inventory, canonical_hash
from .knowledge import ingest, search, active
from .agent import iso, add_event, TERMINAL
from .errors import AppError


def create_app(settings=None):
    settings = settings or Settings()
    app = FastAPI(title="SPD Operations API", version="v1.3", responses={status: {"model": ErrorView} for status in [401, 403, 404, 409, 422, 429, 503]})
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    app.state.factory, app.state.settings, app.state.engine = factory, settings, engine

    @app.exception_handler(AppError)
    async def app_error(_, exc):
        return JSONResponse(exc.body, status_code=exc.status, headers={"Retry-After": str(settings.rate_window_seconds)} if exc.status == 429 else {})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_, exc):
        # Pydantic's raw errors include rejected passwords and request bodies: never return them.
        error = AppError("VALIDATION_ERROR", "请求字段不符合接口约束", 422)
        error.body["details"] = {"fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}
        return JSONResponse(error.body, status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_, exc):
        return JSONResponse(AppError("DEPENDENCY_UNAVAILABLE", "数据库暂不可用", 503, True).body, status_code=503)

    @app.middleware("http")
    async def security(request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            try:
                validate_csrf(request, settings)
            except AppError as exc:
                return JSONResponse(exc.body, status_code=exc.status)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def db_dep():
        with factory() as db:
            yield db

    def user_dep(request: Request, db=Depends(db_dep)):
        return current_user(db, request.cookies.get("spd_session"))

    def auth_rate(request, email):
        # Do not trust user-supplied X-Forwarded-For in the local API.
        rate_limit(factory, settings, "auth-ip", request.client.host if request.client else "unknown")
        rate_limit(factory, settings, "auth-account", email)

    def get_run(db, actor, run_id):
        run = db.get(Run, run_id)
        if not run:
            raise AppError("NOT_FOUND", "资源不存在或不可访问", 404)
        require_project(db, actor.id, run.project_id)
        return run

    from .human_review import summary as review_summary

    def run_view(db, run):
        snapshot = snapshot_for(db, run.project_id, run.snapshot_id)
        analysis_id = db.scalar(select(Analysis.id).where(Analysis.run_id == run.id))
        draft = db.scalar(select(TaskDraft).where(TaskDraft.run_id == run.id))
        return {"schema_version": "1", "run_id": run.id, "question": run.request["question"], "session_id": run.session_id, "status": run.status, "revision": run.revision, "mode": run.request.get("mode", "analyze"), "parent_run_id": run.request.get("parent_run_id"), "context": run.request["context"],
                "snapshot_set_id": run.snapshot_id, "as_of": snapshot.as_of, "current_step": run.current_step, "analysis_id": analysis_id, "draft_id": draft.id if draft else None, "task_id": db.scalar(select(PersonalTask.id).where(PersonalTask.draft_id == draft.id)) if draft else None,
                "error": run.error, "updated_at": iso(run.updated_at), "trace_id": run.id, "options": run.request.get("options"), "generation_mode": "mock" if run.provider == "mock" else "model", "human_review": review_summary(db, run)}

    @app.get("/api/v1/health")
    def health(db=Depends(db_dep)):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": engine.dialect.name, "generation_mode": "mock" if settings.llm_provider == "mock" else "model", "provider_configured": settings.llm_provider == "mock" or bool(settings.deepseek_api_key), "retrieval_mode": "lexical", "synthetic": True}

    @app.get("/api/v1/csrf")
    def csrf(response: Response):
        token = csrf_token(settings)
        response.set_cookie("spd_csrf", token, httponly=True, secure=settings.cookie_secure, samesite="strict", max_age=86400, path="/")
        return {"token": token}

    @app.post("/api/v1/registrations", status_code=201, response_model=MeView)
    def register(body: Registration, request: Request, response: Response, db=Depends(db_dep)):
        auth_rate(request, body.email)
        user = User(email=body.email, display_name=body.display_name, password_hash=hasher.hash(body.password))
        try:
            db.add(user)
            db.flush()
            org = Organization(name=f"{body.display_name}的工作空间")
            db.add(org)
            db.flush()
            project = Project(org_id=org.id, name="澄川医院 · SPD 项目", source_hospital="SIM-HA")
            db.add(project)
            db.flush()
            db.add(Membership(user_id=user.id, project_id=project.id))
            seed_snapshot(db, project)
            ingest(db, project)
            issue_session(db, user, response, settings, request.cookies.get("spd_session"))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise AppError("ACCOUNT_EXISTS", "该邮箱已注册", 409)
        return me_view(db, user)

    @app.post("/api/v1/sessions", response_model=MeView)
    def login(body: Credentials, request: Request, response: Response, db=Depends(db_dep)):
        auth_rate(request, body.email)
        user = db.scalar(select(User).where(User.email == body.email))
        valid = verify_password(user.password_hash if user else DUMMY_HASH, body.password)
        if not user or not valid:
            raise AppError("INVALID_CREDENTIALS", "邮箱或密码不正确", 401)
        issue_session(db, user, response, settings, request.cookies.get("spd_session"))
        db.commit()
        return me_view(db, user)

    @app.delete("/api/v1/sessions/current", status_code=204)
    def logout(request: Request, response: Response, user=Depends(user_dep), db=Depends(db_dep)):
        db.execute(delete(LoginSession).where(LoginSession.token_hash == digest(request.cookies["spd_session"])))
        db.commit()
        response.delete_cookie("spd_session", path="/")

    @app.get("/api/v1/me", response_model=MeView)
    def me(user=Depends(user_dep), db=Depends(db_dep)):
        return me_view(db, user)

    @app.get("/api/v1/projects")
    def projects(user=Depends(user_dep), db=Depends(db_dep)):
        return {"items": me_view(db, user)["projects"]}

    @app.get("/api/v1/projects/{project_id}/dashboard", response_model=DashboardView)
    def dashboard(project_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        project = require_project(db, user.id, project_id)
        snapshot = snapshot_for(db, project_id)
        rows = inventory(snapshot)
        docs = db.scalars(select(Document).where(Document.project_id == project_id)).all()
        active_ids = [d.id for d in docs if active(d)]
        return {"project": {"id": project.id, "name": project.name, "synthetic": project.synthetic}, "snapshot_set_id": snapshot.id, "as_of": snapshot.as_of, "inventory": rows,
                "stats": {"inventory_items": len(rows), "quality_issues": sum(bool(r["quality_issues"]) for r in rows), "documents": len(docs), "active_documents": len(active_ids), "knowledge_chunks": db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id.in_(active_ids))), "runs": db.scalar(select(func.count()).select_from(Run).where(Run.project_id == project_id))},
                "generation_mode": "mock" if settings.llm_provider == "mock" else "model", "provider_configured": settings.llm_provider == "mock" or bool(settings.deepseek_api_key), "retrieval_mode": "lexical"}

    @app.get("/api/v1/projects/{project_id}/inventory")
    def get_inventory(project_id: str, snapshot_set_id: str | None = None, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        snapshot = snapshot_for(db, project_id, snapshot_set_id)
        return {"items": inventory(snapshot), "as_of": snapshot.as_of, "snapshot_set_id": snapshot.id, "synthetic": True}

    @app.get("/api/v1/projects/{project_id}/knowledge/search", response_model=KnowledgeSearchView)
    def knowledge_search(project_id: str, q: Annotated[str, Query(min_length=1, max_length=2000)], user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        return {"items": search(db, project_id, q), "retrieval_mode": "lexical"}

    def document_view(db, doc):
        return {"document_id": doc.id, "title": doc.title, "version": doc.version, "effective_from": doc.effective_from, "effective_until": doc.effective_until,
                "currently_valid": active(doc), "chunk_count": db.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)), "source_hash": doc.source_hash}

    @app.get("/api/v1/projects/{project_id}/knowledge/documents", response_model=KnowledgeDocumentsView)
    def knowledge_documents(project_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        docs = db.scalars(select(Document).where(Document.project_id == project_id).order_by(Document.title, Document.version.desc())).all()
        return {"items": [document_view(db, doc) for doc in docs], "retrieval_mode": "lexical"}

    @app.get("/api/v1/knowledge/documents/{document_id}", response_model=KnowledgeDocumentDetail)
    def knowledge_document(document_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        doc = db.get(Document, document_id)
        if not doc:
            raise AppError("NOT_FOUND", "资料不存在或不可访问", 404)
        require_project(db, user.id, doc.project_id)
        return {**document_view(db, doc), "content": doc.content}

    @app.post("/api/v1/projects/{project_id}/runs", status_code=202, response_model=RunView)
    def create_run(project_id: str, body: RunRequest, idempotency_key: Annotated[str, Header(min_length=8, max_length=100)], user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        from .m2 import bind_parent
        parent = bind_parent(db, user, project_id, body)
        request = body.model_dump()
        # Preserve pre-M2.1 idempotency hashes for requests with the legacy default.
        if request['options'].get('focus') == 'general':
            request['options'].pop('focus')
        request_hash = canonical_hash(request)
        existing = db.scalar(select(Run).where(Run.actor_id == user.id, Run.project_id == project_id, Run.idempotency_key == idempotency_key))
        if existing:
            if existing.request_hash != request_hash:
                raise AppError("IDEMPOTENCY_CONFLICT", "同一个请求键对应了不同内容", 409)
            return run_view(db, existing)
        rate_limit(factory, settings, "run-user", user.id)
        snapshot = snapshot_for(db, project_id, body.context.snapshot_set_id)
        inventory(snapshot, body.context.item_ids, body.context.department_ids)
        run = Run(project_id=project_id, actor_id=user.id, snapshot_id=snapshot.id, idempotency_key=idempotency_key, request_hash=request_hash, request=request, provider=settings.llm_provider)
        if parent:
            run.session_id = parent.session_id
        db.add(run)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            run = db.scalar(select(Run).where(Run.actor_id == user.id, Run.project_id == project_id, Run.idempotency_key == idempotency_key))
            if not run or run.request_hash != request_hash:
                raise AppError("IDEMPOTENCY_CONFLICT", "请求键冲突", 409)
        return run_view(db, run)

    @app.get("/api/v1/projects/{project_id}/runs", response_model=list[RunView])
    def list_runs(project_id: str, limit: Annotated[int, Query(ge=1, le=200)] = 50, user=Depends(user_dep), db=Depends(db_dep)):
        require_project(db, user.id, project_id)
        return [run_view(db, r) for r in db.scalars(select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc()).limit(limit))]

    @app.get("/api/v1/runs/{run_id}", response_model=RunView)
    def read_run(run_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        return run_view(db, get_run(db, user, run_id))

    @app.get("/api/v1/runs/{run_id}/events", response_model=EventsView)
    def events(run_id: str, after: Annotated[int, Query(ge=0)] = 0, limit: Annotated[int, Query(ge=1, le=200)] = 50, user=Depends(user_dep), db=Depends(db_dep)):
        run = get_run(db, user, run_id)
        rows = db.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.cursor > after).order_by(RunEvent.cursor).limit(limit + 1)).all()
        return {"items": [{"schema_version": "1", "run_id": run_id, "cursor": str(e.cursor), "type": e.type, "step": e.step, "occurred_at": iso(e.occurred_at), "payload": e.payload} for e in rows[:limit]], "next_cursor": str(rows[min(len(rows), limit) - 1].cursor) if rows else str(after), "has_more": len(rows) > limit, "run_status": run.status}

    @app.post("/api/v1/runs/{run_id}/cancel", response_model=RunView)
    def cancel(run_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        run = get_run(db, user, run_id)
        changed = db.execute(update(Run).where(Run.id == run_id, Run.status.in_(["queued", "running"])).values(status="cancelled", revision=Run.revision + 1, updated_at=time.time())).rowcount
        if changed:
            db.refresh(run)
            add_event(db, run, "run_finished", "cancelled", {"status": "cancelled", "error": None})
            db.commit()
        return run_view(db, run)

    @app.get("/api/v1/analyses/{analysis_id}", response_model=AnalysisView)
    def analysis(analysis_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        analysis = db.get(Analysis, analysis_id)
        if not analysis:
            raise AppError("NOT_FOUND", "资源不存在或不可访问", 404)
        require_project(db, user.id, analysis.project_id)
        body = {**analysis.body, "citations": [dict(c) for c in analysis.body["citations"]]}
        for c in body["citations"]:
            if c["source_kind"] == "document":
                doc = db.get(Document, c["location"]["document_id"])
                c["currently_valid"] = bool(doc and active(doc))
        return body

    @app.get("/api/v1/evidence/{evidence_id}", response_model=EvidenceView)
    def evidence(evidence_id: str, user=Depends(user_dep), db=Depends(db_dep)):
        evidence = db.get(Evidence, evidence_id)
        if not evidence:
            raise AppError("NOT_FOUND", "资源不存在或不可访问", 404)
        require_project(db, user.id, evidence.project_id)
        valid = True
        if evidence.body["source_kind"] == "document":
            doc = db.get(Document, evidence.body["location"]["document_id"])
            valid = bool(doc and active(doc))
        return {"evidence_id": evidence.id, **evidence.body, "currently_valid": valid}

    from .m2 import register_routes
    register_routes(app, db_dep, user_dep, get_run, run_view)
    from .imports import register_routes as register_import_routes
    register_import_routes(app, db_dep, user_dep)
    from .versions import register_routes as register_version_routes
    register_version_routes(app, db_dep, user_dep)
    from .catalog import register_routes as register_catalog_routes
    register_catalog_routes(app, db_dep, user_dep)
    from .quality import register_routes as register_quality_routes
    register_quality_routes(app, db_dep, user_dep)
    from .knowledge_management import register_routes as register_knowledge_routes
    register_knowledge_routes(app, db_dep, user_dep)
    from .human_review import register_routes as register_review_routes
    register_review_routes(app, db_dep, user_dep, get_run)
    return app
