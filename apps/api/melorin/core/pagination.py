from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from melorin.core.limits import MAX_OFFSET

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class PageParams:
    def __init__(self, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0, le=MAX_OFFSET)):
        self.limit, self.offset = limit, offset
