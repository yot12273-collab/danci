# -*- coding: utf-8 -*-
"""查询历史表。"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.time import utcnow


class SearchHistory(SQLModel, table=True):
    __tablename__ = "search_history"

    id: int | None = Field(default=None, primary_key=True)
    query: str = Field(max_length=64, index=True)
    lemma: str | None = Field(default=None, max_length=64)
    searched_at: datetime = Field(default_factory=utcnow, index=True)
