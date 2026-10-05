import re
import unicodedata
from typing import Literal
from pydantic import Field, field_validator, ValidationInfo
from .schemas import DTO

CatalogKind = Literal['products', 'departments']


class CatalogWrite(DTO):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    specification: str = Field(default='', max_length=200)
    base_unit: str = Field(default='', max_length=30)
    active: bool = True

    @field_validator('code', 'name', 'specification', 'base_unit')
    @classmethod
    def clean(cls, value, info: ValidationInfo):
        value = unicodedata.normalize('NFKC', value).strip()
        if len(value) > {'code': 100, 'name': 100, 'specification': 200, 'base_unit': 30}[info.field_name]:
            raise ValueError('规范化后的字段长度超过限制')
        if any(unicodedata.category(c).startswith('C') for c in value):
            raise ValueError('字段不能包含控制字符')
        return value

    @field_validator('code')
    @classmethod
    def code_valid(cls, value):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}', value):
            raise ValueError('编码须以字母或数字开头，只含字母、数字、点、横线或下划线')
        return value.upper()

    @field_validator('name', 'base_unit')
    @classmethod
    def plain_text(cls, value):
        if value.startswith(('=', '+', '-', '@')):
            raise ValueError('名称或单位不能以公式符号开头')
        return value

    @field_validator('name')
    @classmethod
    def name_required(cls, value):
        if not value:
            raise ValueError('名称不能为空')
        return value


class CatalogUpdate(CatalogWrite):
    revision: int = Field(ge=1)


class CatalogView(CatalogWrite):
    specification: str
    base_unit: str
    active: bool
    id: str
    kind: CatalogKind
    revision: int
    unit_locked: bool
    updated_at: str


class CatalogHistory(DTO):
    actor_id: str | None = None
    at: str
    actor: str
    action: str
    before: dict
    after: dict


class CatalogDetail(CatalogView):
    history: list[CatalogHistory]


class CatalogList(DTO):
    items: list[CatalogView]
    can_edit: bool
    catalog_hash: str
