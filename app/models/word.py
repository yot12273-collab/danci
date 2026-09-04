# -*- coding: utf-8 -*-
"""单词表（生词库，按词根去重）。"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.time import utcnow


class Word(SQLModel, table=True):
    __tablename__ = "words"

    id: int | None = Field(default=None, primary_key=True)
    lemma: str = Field(max_length=64, unique=True, index=True)
    primary_pos: str | None = Field(default=None, max_length=16)
    phonetic: str | None = Field(default=None, max_length=64)
    # 完整释义（JSON 字符串，存所有词性条目）
    translation: str | None = Field(default=None)
    # 列表展示用简短释义（最常用词性 + 中文）
    short_meaning: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
