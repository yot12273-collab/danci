# -*- coding: utf-8 -*-
"""单词相关接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..schemas.common import ok
from ..schemas.word import WordCreate, WordSetTags
from ..services import word_service

router = APIRouter(prefix="/api/words", tags=["words"])


@router.get("/analyze")
def analyze(word: str = Query("", max_length=100)):
    """查词：NLP 分析 + 中文释义（并写入历史）。"""
    return ok(word_service.analyze_word(word))


@router.get("")
def list_words(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    tag_id: int | None = Query(None),
    q: str | None = Query(None),
):
    """生词库列表（支持按标签过滤 / 词根搜索 / 分页）。"""
    return ok(word_service.list_words(page, page_size, tag_id, q))


@router.post("")
def add_word(body: WordCreate):
    """手动添加单词。"""
    return ok(word_service.add_word(body.word, body.tag_ids))


@router.delete("/{word_id}")
def delete_word(word_id: int):
    """删除单词。"""
    return ok(word_service.delete_word(word_id))


@router.put("/{word_id}/tags")
def set_tags(word_id: int, body: WordSetTags):
    """覆盖式设置单词标签。"""
    return ok(word_service.set_word_tags(word_id, body.tag_ids))
