# -*- coding: utf-8 -*-
"""单词表（生词库，按账号隔离：词根仅在同一账号内去重）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ..utils.time import utcnow


class Word(SQLModel, table=True):
    __tablename__ = "words"
    # 同一账号内词根唯一（跨账号允许重复导入同一词）；数据隔离的数据库级兜底
    __table_args__ = (UniqueConstraint("user_id", "lemma", name="uq_word_user_lemma"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    lemma: str = Field(max_length=64)
    # 主要词性标签：可能是多个词性拼接（如「名词 / 动词 / 形容词 / 副词」），放宽到 64
    primary_pos: str | None = Field(default=None, max_length=64)
    phonetic: str | None = Field(default=None, max_length=64)
    # 完整释义（JSON 字符串，存所有词性条目）
    translation: str | None = Field(default=None)
    # 列表展示用简短释义（最常用词性 + 中文）
    short_meaning: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
