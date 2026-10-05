from typing import Literal
from pydantic import Field, field_validator, model_validator
from .schemas import DTO, KnowledgeDocumentView


class FeedbackWrite(DTO):
    rating: Literal['helpful', 'needs_correction']
    comment: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def validate_comment(self):
        self.comment = self.comment.strip()
        if self.rating == 'needs_correction' and not self.comment:
            raise ValueError('Correction feedback needs a reason')
        return self


class FeedbackView(FeedbackWrite):
    id: str
    created_at: str


class FeedbackList(DTO):
    items: list[FeedbackView]
    can_submit: bool


class KnowledgeWrite(DTO):
    title: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=30)
    content: str = Field(min_length=1, max_length=50000)
    source_note: str = Field(min_length=1, max_length=1000)

    @field_validator('title', 'version', 'source_note')
    @classmethod
    def clean(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid text')
        return value.strip()

    @field_validator('content')
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('Invalid document')
        return value


class KnowledgePublish(KnowledgeWrite):
    catalog_token: str = Field(min_length=64, max_length=64)
    preview_hash: str = Field(min_length=64, max_length=64)


class KnowledgeRetire(DTO):
    catalog_token: str = Field(min_length=64, max_length=64)
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator('reason')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Reason required')
        return value.strip()


class KnowledgePreview(DTO):
    catalog_token: str
    preview_hash: str
    source_hash: str
    chunk_count: int
    excerpts: list[str]
    effective_from: str


class KnowledgeChangeView(DTO):
    id: str
    document_id: str
    title: str
    version: str
    action: str
    reason: str
    created_at: str


class KnowledgeManagement(DTO):
    items: list[KnowledgeDocumentView]
    can_manage: bool
    catalog_token: str
    history: list[KnowledgeChangeView]


class KnowledgeMutation(DTO):
    document_id: str
    change_id: str
