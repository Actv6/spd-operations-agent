from typing import Literal
from pydantic import Field, field_validator
from .schemas import DTO


class ActivationView(DTO):
    id: str
    revision: int
    snapshot_id: str
    previous_snapshot_id: str | None
    action: str
    actor_name: str
    reason: str
    created_at: str


class VersionItem(DTO):
    id: str
    as_of: str
    created_at: str | None
    actor_name: str
    positions: int
    validation: str
    current: bool


class VersionList(DTO):
    items: list[VersionItem]
    history: list[ActivationView]
    current_snapshot_id: str
    revision: int
    can_restore: bool


class VersionChange(DTO):
    key: str
    name: str
    department: str
    kind: Literal['added', 'removed', 'changed', 'unchanged']
    details: list[str]
    before_available: str | None
    after_available: str | None
    before_average: str | None
    after_average: str | None
    before_unit: str | None
    after_unit: str | None


class VersionComparison(DTO):
    from_id: str
    to_id: str
    from_as_of: str
    to_as_of: str
    revision: int
    current_snapshot_id: str
    changes: list[VersionChange]


class RestoreRequest(DTO):
    target_snapshot_id: str = Field(min_length=1, max_length=36)
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=5, max_length=500)

    @field_validator('reason')
    @classmethod
    def clean_reason(cls, value):
        value = value.strip()
        if len(value) < 5 or any(ord(c) < 32 and c not in '\n\t' for c in value):
            raise ValueError('请填写至少5字的回退原因')
        return value
