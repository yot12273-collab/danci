# -*- coding: utf-8 -*-
"""标签表（按账号隔离：标签归属 user_id，重名仅在账号内唯一）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ..utils.time import utcnow


class Tag(SQLModel, table=True):
    __tablename__ = "tags"
    # 同一账号内标签名唯一（跨账号允许重名）；这是数据隔离的数据库级兜底
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True, ondelete="CASCADE")
    name: str = Field(max_length=64)
    color: str | None = Field(default=None, max_length=16)
    created_at: datetime = Field(default_factory=utcnow)
