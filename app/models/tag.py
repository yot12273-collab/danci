# -*- coding: utf-8 -*-
"""标签表。"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.time import utcnow


class Tag(SQLModel, table=True):
    __tablename__ = "tags"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=64, unique=True, index=True)
    color: str | None = Field(default=None, max_length=16)
    created_at: datetime = Field(default_factory=utcnow)
