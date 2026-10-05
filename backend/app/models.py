import time
import uuid
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=uid)
    email = Column(String(254), unique=True, nullable=False)
    display_name = Column(String(50), nullable=False)
    password_hash = Column(Text, nullable=False)


class Organization(Base):
    __tablename__ = "organizations"
    id = Column(String(36), primary_key=True, default=uid)
    name = Column(String(100), nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id = Column(String(36), primary_key=True, default=uid)
    org_id = Column(String(36), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(100), nullable=False)
    source_hospital = Column(String(30), nullable=False, default="SIM-HA")
    synthetic = Column(Boolean, nullable=False, default=True)


class Membership(Base):
    __tablename__ = "memberships"
    user_id = Column(String(36), ForeignKey("users.id"), primary_key=True)
    project_id = Column(String(36), ForeignKey("projects.id"), primary_key=True)
    role = Column(String(30), nullable=False, default="demo_owner")
    permission_version = Column(Integer, nullable=False, default=1)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    expires_at = Column(Float, nullable=False)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key = Column(String(64), primary_key=True)
    count = Column(Integer, nullable=False, default=1)
    expires_at = Column(Float, nullable=False)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    as_of = Column(String(40), nullable=False)
    source_hash = Column(String(64), nullable=False)
    facts = Column(JSON, nullable=False)
    created_at = Column(Float, nullable=False, default=time.time)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("project_id", "external_id", name="uq_document_project_version"),)
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    external_id = Column(String(100), nullable=False)
    title = Column(String(200), nullable=False)
    version = Column(String(30), nullable=False)
    status = Column(String(30), nullable=False)
    effective_from = Column(String(10), nullable=False)
    effective_until = Column(String(10), nullable=True)
    source_hash = Column(String(64), nullable=False)
    source_path = Column(String(300), nullable=False)
    content = Column(Text, nullable=False)
    synthetic = Column(Boolean, nullable=False, default=True)


class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(String(36), primary_key=True, default=uid)
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False, index=True)
    chapter = Column(String(300), nullable=False)
    start_offset = Column(Integer, nullable=False)
    end_offset = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)


class Run(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("actor_id", "project_id", "idempotency_key", name="uq_run_idempotency"),)
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    snapshot_id = Column(String(36), ForeignKey("snapshots.id"), nullable=False)
    session_id = Column(String(36), nullable=False, default=uid)
    idempotency_key = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    request = Column(JSON, nullable=False)
    provider = Column(String(20), nullable=False)
    status = Column(String(30), nullable=False, default="queued", index=True)
    revision = Column(Integer, nullable=False, default=1)
    current_step = Column(String(50), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    lease_until = Column(Float, nullable=True)
    fence = Column(String(36), nullable=True)
    checkpoint = Column(JSON, nullable=False, default=dict)
    error = Column(JSON, nullable=True)
    event_seq = Column(Integer, nullable=False, default=0)
    created_at = Column(Float, nullable=False, default=time.time)
    updated_at = Column(Float, nullable=False, default=time.time)


class RunEvent(Base):
    __tablename__ = "run_events"
    run_id = Column(String(36), ForeignKey("agent_runs.id"), primary_key=True)
    cursor = Column(Integer, primary_key=True)
    type = Column(String(50), nullable=False)
    step = Column(String(50), nullable=True)
    occurred_at = Column(Float, nullable=False, default=time.time)
    payload = Column(JSON, nullable=False)


class Evidence(Base):
    __tablename__ = "evidence"
    id = Column(String(36), primary_key=True, default=uid)
    run_id = Column(String(36), ForeignKey("agent_runs.id"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    body = Column(JSON, nullable=False)


class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(String(36), primary_key=True, default=uid)
    run_id = Column(String(36), ForeignKey("agent_runs.id"), nullable=False, unique=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    body = Column(JSON, nullable=False)


class TaskDraft(Base):
    __tablename__ = "task_drafts"
    id = Column(String(36), primary_key=True, default=uid)
    run_id = Column(String(36), ForeignKey("agent_runs.id"), nullable=False, unique=True)
    analysis_id = Column(String(36), ForeignKey("analyses.id"), nullable=False)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    snapshot_id = Column(String(36), ForeignKey("snapshots.id"), nullable=False)
    content = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    revision = Column(Integer, nullable=False, default=1)
    confirmation_hash = Column(String(64), nullable=True)
    created_at = Column(Float, nullable=False, default=time.time)


class PersonalTask(Base):
    __tablename__ = "personal_tasks"
    id = Column(String(36), primary_key=True, default=uid)
    draft_id = Column(String(36), ForeignKey("task_drafts.id"), nullable=False, unique=True)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    title = Column(String(160), nullable=False)
    steps = Column(JSON, nullable=False)
    due_date = Column(String(10), nullable=False)
    status = Column(String(20), nullable=False, default="todo")
    result = Column(Text, nullable=False, default="")
    revision = Column(Integer, nullable=False, default=1)
    history = Column(JSON, nullable=False)
    created_at = Column(Float, nullable=False, default=time.time)
    updated_at = Column(Float, nullable=False, default=time.time)


class DataImport(Base):
    __tablename__ = "data_imports"
    __table_args__ = (UniqueConstraint("actor_id", "project_id", "idempotency_key", name="uq_import_idempotency"),)
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    base_snapshot_id = Column(String(36), ForeignKey("snapshots.id"), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    as_of = Column(String(40), nullable=False)
    status = Column(String(20), nullable=False)
    facts = Column(JSON, nullable=False)
    report = Column(JSON, nullable=False)
    snapshot_id = Column(String(36), ForeignKey("snapshots.id"), nullable=True)
    published_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    published_at = Column(Float, nullable=True)
    created_at = Column(Float, nullable=False, default=time.time)


class CatalogEntry(Base):
    __tablename__ = "project_catalog"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "code", name="uq_catalog_code"),
        UniqueConstraint("project_id", "kind", "source_id", name="uq_catalog_source"),
        UniqueConstraint("project_id", "kind", "department_name_key", name="uq_catalog_department_name"),
    )
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    source_id = Column(String(100), nullable=False)
    code = Column(String(100), nullable=False)
    name = Column(String(100), nullable=False)
    department_name_key = Column(String(100), nullable=True)
    specification = Column(String(200), nullable=False, default="")
    base_unit = Column(String(30), nullable=False, default="")
    active = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=1)
    source_metadata = Column(JSON, nullable=False, default=dict)
    history = Column(JSON, nullable=False, default=list)
    updated_at = Column(Float, nullable=False, default=time.time)


class SnapshotActivation(Base):
    __tablename__ = "snapshot_activations"
    __table_args__ = (
        UniqueConstraint("project_id", "revision", name="uq_activation_revision"),
        UniqueConstraint("project_id", "actor_id", "idempotency_key", name="uq_activation_request"),
    )
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(36), ForeignKey("projects.id"), nullable=False, index=True)
    snapshot_id = Column(String(36), ForeignKey("snapshots.id"), nullable=False)
    previous_snapshot_id = Column(String(36), ForeignKey("snapshots.id"), nullable=True)
    revision = Column(Integer, nullable=False)
    action = Column(String(30), nullable=False)
    actor_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    actor_name = Column(String(50), nullable=False)
    reason = Column(String(500), nullable=False)
    idempotency_key = Column(String(100), nullable=True)
    request_hash = Column(String(64), nullable=True)
    created_at = Column(Float, nullable=False, default=time.time)


class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedback'
    __table_args__ = (UniqueConstraint('actor_id', 'analysis_id', 'idempotency_key', name='uq_feedback_request'),)
    id = Column(String(36), primary_key=True, default=uid)
    analysis_id = Column(String(36), ForeignKey('analyses.id'), nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    rating = Column(String(30), nullable=False)
    comment = Column(String(1000), nullable=False)
    context = Column(JSON, nullable=False)
    created_at = Column(Float, nullable=False, default=time.time)


class KnowledgeChange(Base):
    __tablename__ = 'knowledge_changes'
    __table_args__ = (UniqueConstraint('project_id', 'actor_id', 'idempotency_key', name='uq_knowledge_request'),)
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(36), ForeignKey('projects.id'), nullable=False, index=True)
    document_id = Column(String(36), ForeignKey('documents.id'), nullable=False)
    actor_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    action = Column(String(30), nullable=False)
    reason = Column(String(1000), nullable=False)
    created_at = Column(Float, nullable=False, default=time.time)


class HumanReviewState(Base):
    __tablename__ = 'human_review_states'
    run_id = Column(String(36), ForeignKey('agent_runs.id'), primary_key=True)
    revision = Column(Integer, nullable=False, default=0)


class HumanReviewRecord(Base):
    __tablename__ = 'human_review_records'
    __table_args__ = (
        UniqueConstraint('run_id', 'revision', name='uq_human_review_revision'),
        UniqueConstraint('run_id', 'actor_id', 'idempotency_key', name='uq_human_review_request'),
    )
    id = Column(String(36), primary_key=True, default=uid)
    run_id = Column(String(36), ForeignKey('agent_runs.id'), nullable=False, index=True)
    actor_id = Column(String(36), ForeignKey('users.id'), nullable=False)
    actor_name = Column(String(50), nullable=False)
    revision = Column(Integer, nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(30), nullable=False)
    conclusion = Column(String(2000), nullable=False)
    basis = Column(String(2000), nullable=False)
    next_step = Column(String(1000), nullable=False)
    evidence_ids = Column(JSON, nullable=False)
    handled_feedback_ids = Column(JSON, nullable=False)
    self_review = Column(Boolean, nullable=False)
    snapshot_set_id = Column(String(36), ForeignKey('snapshots.id'), nullable=False)
    analysis_hash = Column(String(64), nullable=True)
    source_token = Column(String(64), nullable=False)
    created_at = Column(Float, nullable=False, default=time.time)
