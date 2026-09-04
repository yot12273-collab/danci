# -*- coding: utf-8 -*-
"""标签-单词关联表（多对多）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ..utils.time import utcnow


class TagWord(SQLModel, table=True):
    __tablename__ = "tag_words"
    __table_args__ = (UniqueConstraint("tag_id", "word_id", name="uq_tag_word"),)

    id: int | None = Field(default=None, primary_key=True)
    tag_id: int = Field(foreign_key="tags.id", index=True, ondelete="CASCADE")
    word_id: int = Field(foreign_key="words.id", index=True, ondelete="CASCADE")
    created_at: datetime = Field(default_factory=utcnow)
