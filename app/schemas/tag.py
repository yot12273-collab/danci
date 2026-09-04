# -*- coding: utf-8 -*-
"""标签相关请求体模型。"""
from __future__ import annotations

from pydantic import BaseModel


class TagCreate(BaseModel):
    name: str
    color: str | None = None


class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
