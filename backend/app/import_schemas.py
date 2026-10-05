from typing import Literal
from pydantic import Field
from .schemas import DTO, InventoryItem


IMPORT_MAX_BYTES = 10 * 1024 * 1024


class ImportFiles(DTO):
    inventory: str = Field(max_length=IMPORT_MAX_BYTES)
    batches: str = Field(max_length=IMPORT_MAX_BYTES)
    consumption: str = Field(max_length=IMPORT_MAX_BYTES)


class ImportRequest(DTO):
    publication_revision: int = Field(default=0, ge=0)
    catalog_hash: str | None = Field(default=None, min_length=64, max_length=64)
    base_snapshot_id: str = Field(min_length=1, max_length=36)
    as_of: str = Field(min_length=10, max_length=40)
    files: ImportFiles


class ImportPublish(DTO):
    acknowledge_warnings: bool = False


class ImportIssue(DTO):
    file: str
    row: int | None
    severity: Literal['error', 'warning']
    message: str


class ImportChange(DTO):
    details: list[str]
    name: str
    department: str
    kind: Literal['added', 'removed', 'changed', 'unchanged']
    before_available: str | None
    after_available: str | None
    unit: str


class ImportSummary(DTO):
    id: str
    as_of: str
    status: Literal['invalid', 'ready', 'published']
    base_snapshot_id: str
    snapshot_id: str | None
    created_at: str
    actor_name: str
    published_at: str | None
    published_by: str | None
    error_count: int
    warning_count: int
    positions: int


class ImportView(ImportSummary):
    issues: list[ImportIssue]
    inventory: list[InventoryItem]
    changes: list[ImportChange]
    stale: bool


class ImportList(DTO):
    items: list[ImportSummary]
    can_publish: bool


class ImportTemplate(DTO):
    publication_revision: int = 0
    catalog_hash: str | None = None
    base_snapshot_id: str
    as_of: str
    files: ImportFiles
