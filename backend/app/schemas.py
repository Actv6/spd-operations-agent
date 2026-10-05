from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(DTO):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def email_format(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("邮箱格式无效")
        return value


class Registration(Credentials):
    display_name: str = Field(min_length=1, max_length=50)

    @field_validator("display_name")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("姓名不能为空")
        return value.strip()


class Context(DTO):
    snapshot_set_id: str | None
    item_ids: list[str] = Field(max_length=50)
    department_ids: list[str] = Field(max_length=50)
    analysis_id: str | None


class Options(DTO):
    window_days: Literal[14]
    focus: Literal["general", "risk_scan"] = "general"


class RunRequest(DTO):
    schema_version: Literal["1"]
    mode: Literal["analyze", "follow_up", "draft_action"]
    question: str = Field(min_length=1, max_length=2000)
    session_id: str | None
    parent_run_id: str | None
    context: Context
    options: Options

    @field_validator("question")
    @classmethod
    def question_nonblank(cls, v):
        if not v.strip():
            raise ValueError("问题不能为空")
        return v.strip()


class InventoryArgs(DTO):
    item_ids: list[str] = Field(default_factory=list, max_length=50, description="只接受 scoped_inventory_catalog 中的 item_id；不是物资名称或 MAT 业务编码。空数组表示本次已选物资范围，不表示越过授权。")
    department_ids: list[str] = Field(default_factory=list, max_length=50, description="只接受 scoped_inventory_catalog 中的 department_id；空数组表示本次已授权科室范围。")


class SearchArgs(DTO):
    query: str = Field(min_length=1, max_length=2000)


class TaskProposal(DTO):
    title: str = Field(min_length=1, max_length=160)
    steps: list[str] = Field(min_length=1, max_length=8)

    @field_validator("title")
    @classmethod
    def title_valid(cls, value):
        if not value.strip():
            raise ValueError("blank title")
        return value.strip()

    @field_validator("steps")
    @classmethod
    def steps_valid(cls, values):
        if any(not v.strip() or len(v) > 500 for v in values):
            raise ValueError("invalid step")
        return [v.strip() for v in values]


class RiskSummary(DTO):
    scanned_positions: int = Field(ge=0)
    skipped_estimates: int = Field(ge=0)
    data_quality: int = Field(ge=0)
    zero_consumption: int = Field(ge=0)
    findings: int = Field(ge=0)


class AnswerClaim(DTO):
    kind: Literal['fact', 'policy', 'suggestion', 'unknown']
    text: str = Field(min_length=1, max_length=1500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    fact_ids: list[str] = Field(default_factory=list, max_length=1)

    @field_validator('text')
    @classmethod
    def single_paragraph(cls, value):
        if not value.strip() or '\n' in value or '\r' in value:
            raise ValueError('claim must be a nonblank single paragraph')
        return value


class ClaimView(AnswerClaim):
    id: str
    verification: Literal['tool_exact', 'document_quote', 'unverified']
    evidence_ids: list[str] = Field(max_length=20)
    fact_ids: list[str] = Field(max_length=1)


class ReasonPosition(DTO):
    item_id: str
    department_id: str
    name: str
    department_name: str


class ReasonGroup(DTO):
    reason: str
    label: str
    count: int = Field(ge=0)
    positions: list[ReasonPosition]
    evidence_ids: list[str]


class ModelAnswer(DTO):
    answer: str = Field(min_length=1, max_length=6000)
    evidence_ids: list[str] = Field(max_length=20)
    insufficient_evidence: bool
    task_draft: TaskProposal | None = None
    risk_summary: RiskSummary | None = None
    claims: list[AnswerClaim] = Field(default_factory=list, max_length=20)


class UserView(DTO):
    id: str
    email: str
    display_name: str


class ProjectView(DTO):
    id: str
    name: str
    synthetic: bool


class MeView(DTO):
    user: UserView
    projects: list[ProjectView]
    capabilities: list[str]


class ErrorView(DTO):
    code: str
    message: str
    details: dict = Field(default_factory=dict)
    trace_id: str
    retryable: bool = False


class InventoryItem(DTO):
    item_id: str
    name: str
    display_code: str = ""
    specification: str = ""
    department_id: str
    department_name: str = ""
    unit: str
    available: str | None
    daily_average: str | None
    coverage_days: str | None
    observed_days: int
    quality_issues: list[str]
    source_rows: list[str]
    snapshot_at: str


class DashboardView(DTO):
    project: ProjectView
    snapshot_set_id: str
    as_of: str
    inventory: list[InventoryItem]
    stats: dict[str, int]
    generation_mode: Literal["mock", "model"]
    provider_configured: bool
    retrieval_mode: Literal["lexical"]


class KnowledgeHit(DTO):
    chunk_id: str
    document_id: str
    document_external_id: str
    title: str
    version: str
    chapter: str
    start_offset: int
    end_offset: int
    excerpt: str
    source_hash: str
    source_path: str
    synthetic: bool
    score: float


class KnowledgeSearchView(DTO):
    items: list[KnowledgeHit]
    retrieval_mode: Literal["lexical"]


class KnowledgeDocumentView(DTO):
    document_id: str
    title: str
    version: str
    effective_from: str
    effective_until: str | None
    currently_valid: bool
    chunk_count: int
    source_hash: str


class KnowledgeDocumentsView(DTO):
    items: list[KnowledgeDocumentView]
    retrieval_mode: Literal["lexical"]


class KnowledgeDocumentDetail(KnowledgeDocumentView):
    content: str


class HumanReviewSummary(DTO):
    status: Literal['pending', 'confirmed', 'error', 'insufficient']
    required: bool
    reasons: list[str]
    blocked: bool
    stale_reasons: list[str]
    revision: int


class RunView(DTO):
    human_review: HumanReviewSummary | None = None
    schema_version: Literal["1"] = "1"
    run_id: str
    question: str
    session_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    revision: int
    mode: Literal["analyze", "follow_up", "draft_action"] = "analyze"
    snapshot_set_id: str
    as_of: str
    current_step: str
    analysis_id: str | None
    parent_run_id: str | None = None
    context: Context | None = None
    draft_id: str | None = None
    task_id: str | None = None
    error: ErrorView | None
    updated_at: str
    trace_id: str
    generation_mode: Literal["mock", "model"]
    options: Options | None = None


class EvidenceView(DTO):
    evidence_id: str
    source_kind: Literal["tool", "document"]
    source_version: str
    title: str
    location: dict
    excerpt: str
    hash: str
    as_of: str
    synthetic: bool
    facts: dict | None = None
    currently_valid: bool = True


class RiskPrioritySummary(DTO):
    high: int = Field(ge=0)
    medium: int = Field(ge=0)


class RiskFindingView(DTO):
    id: str
    item_id: str
    department_id: str
    name: str
    department_name: str
    kind: Literal['quality', 'low_coverage', 'expiry']
    priority: Literal['high', 'medium']
    summary: str
    source_rows: list[str]


class AnalysisView(DTO):
    analysis_id: str
    run_id: str
    project_id: str
    snapshot_set_id: str
    as_of: str
    ruleset_version: str
    knowledge_release_id: list[str]
    model_release_id: str | None
    generation_mode: Literal["mock", "model", "rules_only"]
    retrieval_mode: Literal["lexical"]
    answer: str
    insufficient_evidence: bool
    citations: list[EvidenceView]
    inventory: list[InventoryItem]
    warnings: list[str]
    provider_metadata: dict
    risk_summary: RiskSummary | None = None
    risk_priority_summary: RiskPrioritySummary | None = None
    risk_findings: list[RiskFindingView] | None = None
    claims: list[ClaimView] | None = None
    reason_breakdown: list[ReasonGroup] | None = None


class EventView(DTO):
    schema_version: Literal["1"] = "1"
    run_id: str
    cursor: str
    type: str
    step: str | None
    occurred_at: str
    payload: dict


class EventsView(DTO):
    items: list[EventView]
    next_cursor: str
    has_more: bool
    run_status: str


class RiskFinding(DTO):
    id: str
    item_id: str
    department_id: str
    name: str
    department_name: str
    kind: Literal["quality", "low_coverage", "expiry"]
    priority: Literal["high", "medium"]
    summary: str
    source_rows: list[str]


class RiskReport(DTO):
    snapshot_set_id: str
    as_of: str
    ruleset_version: str
    scanned_positions: int
    skipped_estimates: int
    estimate_gap_counts: dict[str, int]
    thresholds: dict[str, int]
    findings: list[RiskFinding]


class BatchView(DTO):
    id: str
    product_id: str
    department_id: str
    expiry_date: str
    days_to_expiry: int
    on_hand: str
    frozen: str
    reserved: str
    available: str | None
    status: str
    unit: str


class ConsumptionDay(DTO):
    date: str
    quantity: str | None
    status: str
    source_rows: list[str]


class ConsumptionView(DTO):
    item_id: str
    department_id: str
    unit: str
    days: list[ConsumptionDay]
    observed_days: int
    daily_average: str | None
    quality_issues: list[str]


class ItemDetails(DTO):
    snapshot_set_id: str
    as_of: str
    batches: list[BatchView]
    consumption: list[ConsumptionView]


class DraftConfirm(TaskProposal):
    revision: int = Field(ge=1)
    due_date: str

    @field_validator("due_date")
    @classmethod
    def date_valid(cls, value):
        from datetime import date
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("invalid date")
        return value


class RevisionRequest(DTO):
    revision: int = Field(ge=1)


class TaskUpdate(RevisionRequest):
    status: Literal["todo", "in_progress", "completed", "cancelled"]
    result: str = Field(default="", max_length=3000)


class DraftView(DTO):
    review_blockers: list[dict[str, str]] = Field(default_factory=list)
    id: str
    run_id: str
    analysis_id: str
    snapshot_set_id: str
    title: str
    steps: list[str]
    revision: int
    status: str
    task_id: str | None
    stale_reason: str | None


class TaskHistory(DTO):
    status: str
    result: str
    at: str
    actor_id: str


class TaskView(DTO):
    review_blockers: list[dict[str, str]] = Field(default_factory=list)
    id: str
    draft_id: str
    title: str
    steps: list[str]
    due_date: str
    status: Literal["todo", "in_progress", "completed", "cancelled"]
    result: str
    revision: int
    analysis_id: str
    run_id: str
    history: list[TaskHistory]
    updated_at: str
