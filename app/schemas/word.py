# -*- coding: utf-8 -*-
"""单词相关请求体模型。"""
from __future__ import annotations

from pydantic import BaseModel


class WordCreate(BaseModel):
    """手动添加单词。"""
    word: str
    tag_ids: list[int] = []


class WordSetTags(BaseModel):
    """覆盖式设置单词的标签。"""
    tag_ids: list[int] = []
