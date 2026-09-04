# -*- coding: utf-8 -*-
"""用户表（账号体系）。"""
from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from ..utils.time import utcnow


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(max_length=64, unique=True, index=True)
    password_hash: str = Field(max_length=128)
    created_at: datetime = Field(default_factory=utcnow)
