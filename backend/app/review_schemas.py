from typing import Literal
from pydantic import Field, field_validator, model_validator
from .schemas import DTO, InventoryItem, HumanReviewSummary

ReviewStatus = Literal['pending', 'confirmed', 'error', 'insufficient']


class HumanReviewWrite(DTO):
    revision: int = Field(ge=0)
    source_token: str = Field(min_length=64, max_length=64)
    status: ReviewStatus
    conclusion: str = Field(min_length=1, max_length=2000)
    basis: str = Field(min_length=1, max_length=2000)
    next_step: str = Field(default='', max_length=1000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    handled_feedback_ids: list[str] = Field(default_factory=list)

    @field_validator('conclusion', 'basis', 'next_step')
    @classmethod
    def trim(cls, value):
        return value.strip()

    @model_validator(mode='after')
    def validate_content(self):
        if not self.conclusion or not self.basis:
            raise ValueError('Conclusion and basis required')
        if self.status in {'error', 'insufficient'} and not self.next_step:
            raise ValueError('Next step required')
        for values in [self.evidence_ids, self.handled_feedback_ids]:
            if len(values) != len(set(values)):
                raise ValueError('Duplicate references')
        return self


class HumanReviewRecord(DTO):
    id: str
    revision: int
    status: ReviewStatus
    conclusion: str
    basis: str
    next_step: str
    evidence_ids: list[str]
    handled_feedback_ids: list[str]
    actor_id: str
    actor_name: str
    self_review: bool
    created_at: str
    snapshot_set_id: str
    analysis_hash: str | None
    source_token: str


class ReviewFeedback(DTO):
    id: str
    comment: str
    created_at: str


class ReviewEvidence(DTO):
    evidence_id: str
    title: str
    source_kind: Literal['tool', 'document']


class HumanReviewView(HumanReviewSummary):
    run_id: str
    project_id: str
    snapshot_set_id: str
    inventory: list[InventoryItem]
    can_submit: bool
    source_token: str
    manual_only: bool
    items: list[HumanReviewRecord]
    pending_feedback: list[ReviewFeedback]
    available_evidence: list[ReviewEvidence]
