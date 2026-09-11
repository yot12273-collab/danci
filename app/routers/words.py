# -*- coding: utf-8 -*-
"""单词相关接口（均按当前登录账号隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..dependencies import CurrentUser, get_current_user
from ..schemas.common import ok
from ..schemas.word import WordCreate, WordSetTags
from ..services import word_service

router = APIRouter(prefix="/api/words", tags=["words"], dependencies=[Depends(get_current_user)])


@router.get("/analyze")
def analyze(word: str = Query("", max_length=100), user: CurrentUser = Depends(get_current_user)):
    """查词：NLP 分析 + 中文释义（并写入当前用户历史）。"""
    return ok(word_service.analyze_word(word, user.id))


@router.get("")
def list_words(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    tag_id: int | None = Query(None),
    q: str | None = Query(None),
    user: CurrentUser = Depends(get_current_user),
):
    """生词库列表（支持按标签过滤 / 词根搜索 / 分页，仅返回当前账号数据）。"""
    return ok(word_service.list_words(page, page_size, tag_id, q, user.id))


@router.post("")
def add_word(body: WordCreate, user: CurrentUser = Depends(get_current_user)):
    """手动添加单词（归属当前账号）。"""
    return ok(word_service.add_word(body.word, body.tag_ids, user.id))


@router.delete("/{word_id}")
def delete_word(word_id: int, user: CurrentUser = Depends(get_current_user)):
    """删除单词（仅限当前账号单词）。"""
    return ok(word_service.delete_word(word_id, user.id))


@router.put("/{word_id}/tags")
def set_tags(word_id: int, body: WordSetTags, user: CurrentUser = Depends(get_current_user)):
    """覆盖式设置单词标签（单词与标签均须归属当前账号）。"""
    return ok(word_service.set_word_tags(word_id, body.tag_ids, user.id))
