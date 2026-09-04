# -*- coding: utf-8 -*-
"""单词服务：查词编排（NLP + 中文词典）、生词库 CRUD。"""
from __future__ import annotations

import json

from sqlmodel import func, select

from ..database import session_scope
from ..models import Tag, TagWord, Word
from ..schemas.common import AppError, ERR_INVALID_WORD, ERR_NOT_FOUND
from . import nlp_engine
from .dictionary import dictionary
from .history_service import record


def _enrich(nlp: dict) -> dict:
    """根据词根补充中文释义、音标、主词性。"""
    lemma = nlp["base"]
    trans = dictionary.lookup(lemma)
    return {
        "phonetic": trans["phonetic"] if trans else None,
        "translations": trans["translations"] if trans else [],
        "short_meaning": trans["short_meaning"] if trans else None,
        "primary_pos": nlp.get("pos_label") or None,
    }


def _tags_of(session, word_id: int) -> list[dict]:
    rows = session.exec(
        select(Tag).join(TagWord).where(TagWord.word_id == word_id)
    ).all()
    return [{"id": t.id, "name": t.name, "color": t.color} for t in rows]


def _analyze(raw: str, record_history: bool) -> dict:
    """查词核心：NLP 分析 + 中文释义补全，返回完整详情（供搜索与背诵复用）。

    record_history=False 时不写查询历史，供背诵轮播复用（避免污染历史记录）。
    返回结构与搜索完全一致：{base, phonetic, translations, short_meaning,
    pos_label, highlight, forms, similar, links, is_saved, tags, ...}
    """
    try:
        nlp = nlp_engine.analyze(raw)
    except nlp_engine.InvalidWordError as exc:
        raise AppError(ERR_INVALID_WORD, str(exc), http_status=400) from exc

    enrich = _enrich(nlp)
    lemma = nlp["base"]

    with session_scope() as session:
        word = session.exec(select(Word).where(Word.lemma == lemma)).first()
        is_saved = word is not None
        tags = _tags_of(session, word.id) if word else []
        if record_history:
            record(session, raw, lemma)

    return {
        **nlp,
        "phonetic": enrich["phonetic"],
        "translations": enrich["translations"],
        "short_meaning": enrich["short_meaning"],
        "is_saved": is_saved,
        "tags": tags,
    }


def analyze_word(raw: str) -> dict:
    """查词入口：NLP 分析 + 中文释义，并写入查询历史。"""
    return _analyze(raw, record_history=True)


def detail_for_word(raw: str) -> dict:
    """查词详情入口（背诵复用）：返回与搜索完全一致的详情，但不写查询历史。"""
    return _analyze(raw, record_history=False)


def batch_details(lemmas: list[str]) -> list[dict]:
    """批量生成多个单词的完整搜索详情（背诵批量预加载，不写历史）。

    一次调用为「一份」内的所有词根生成与 analyze_word 完全一致的结构，
    前端据此只发一次网络请求即可拿到整份数据，避免逐词请求造成高频连接；
    内部只开一个数据库会话批量取收藏态与标签，减少开销。
    对单个词根分析失败（极端情况）时跳过该词，不拖垮整份。
    """
    results: list[dict] = []
    if not lemmas:
        return results

    with session_scope() as session:
        # 批量取已收藏的 Word（按词根映射），避免逐词查询
        saved = {
            w.lemma: w
            for w in session.exec(select(Word).where(Word.lemma.in_(lemmas))).all()
        }
        for lemma in lemmas:
            try:
                nlp = nlp_engine.analyze(lemma)
            except nlp_engine.InvalidWordError:
                continue  # 生词库中的词理应合法；异常则跳过，保证整份可用
            enrich = _enrich(nlp)
            base = nlp["base"]
            word = saved.get(base)
            is_saved = word is not None
            tags = _tags_of(session, word.id) if word else []
            results.append({
                **nlp,
                "phonetic": enrich["phonetic"],
                "translations": enrich["translations"],
                "short_meaning": enrich["short_meaning"],
                "is_saved": is_saved,
                "tags": tags,
            })
    return results


def list_words(page: int = 1, page_size: int = 20,
               tag_id: int | None = None, q: str | None = None) -> dict:
    with session_scope() as session:
        # 计数
        count_stmt = select(func.count()).select_from(Word)
        if tag_id is not None:
            count_stmt = count_stmt.join(TagWord).where(TagWord.tag_id == tag_id)
        if q:
            count_stmt = count_stmt.where(Word.lemma.contains(q.strip().lower()))
        total = session.exec(count_stmt).one()

        # 分页查询
        stmt = select(Word)
        if tag_id is not None:
            stmt = stmt.join(TagWord).where(TagWord.tag_id == tag_id)
        if q:
            stmt = stmt.where(Word.lemma.contains(q.strip().lower()))
        words = session.exec(
            stmt.order_by(Word.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        items = [
            {
                "id": w.id,
                "lemma": w.lemma,
                "primary_pos": w.primary_pos,
                "phonetic": w.phonetic,
                "short_meaning": w.short_meaning,
                "tags": _tags_of(session, w.id),
            }
            for w in words
        ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def _link_tags(session, word_id: int, tag_ids: list[int]) -> None:
    """追加关联标签（已存在的跳过，不覆盖）。"""
    for tid in dict.fromkeys(tag_ids):  # dict.fromkeys 去重且保序
        exists = session.exec(
            select(TagWord).where(TagWord.tag_id == tid, TagWord.word_id == word_id)
        ).first()
        if exists is None:
            session.add(TagWord(tag_id=tid, word_id=word_id))


def add_word(raw_word: str, tag_ids: list[int] | None = None) -> dict:
    """手动添加单词到生词库（按词根去重，重复则更新释义）。"""
    try:
        nlp = nlp_engine.analyze(raw_word)
    except nlp_engine.InvalidWordError as exc:
        raise AppError(ERR_INVALID_WORD, str(exc), http_status=400) from exc

    lemma = nlp["base"]
    enrich = _enrich(nlp)
    translation_json = json.dumps(enrich["translations"], ensure_ascii=False)

    with session_scope() as session:
        word = session.exec(select(Word).where(Word.lemma == lemma)).first()
        if word is None:
            word = Word(
                lemma=lemma,
                primary_pos=enrich["primary_pos"],
                phonetic=enrich["phonetic"],
                short_meaning=enrich["short_meaning"],
                translation=translation_json,
            )
            session.add(word)
            session.flush()
        else:
            word.primary_pos = enrich["primary_pos"]
            word.phonetic = enrich["phonetic"]
            word.short_meaning = enrich["short_meaning"]
            word.translation = translation_json
        _link_tags(session, word.id, tag_ids or [])
        word_id = word.id
    return {"id": word_id, "lemma": lemma, "short_meaning": enrich["short_meaning"]}


def delete_word(word_id: int) -> None:
    with session_scope() as session:
        word = session.get(Word, word_id)
        if word is None:
            raise AppError(ERR_NOT_FOUND, "单词不存在", http_status=404)
        session.delete(word)


def set_word_tags(word_id: int, tag_ids: list[int]) -> dict:
    """覆盖式设置单词的标签。"""
    tag_ids = list(dict.fromkeys(tag_ids))
    with session_scope() as session:
        word = session.get(Word, word_id)
        if word is None:
            raise AppError(ERR_NOT_FOUND, "单词不存在", http_status=404)
        for tid in tag_ids:
            if session.get(Tag, tid) is None:
                raise AppError(ERR_NOT_FOUND, f"标签 {tid} 不存在", http_status=404)
        # 删除旧关联
        for tw in session.exec(
            select(TagWord).where(TagWord.word_id == word_id)
        ).all():
            session.delete(tw)
        # 重建关联
        for tid in tag_ids:
            session.add(TagWord(tag_id=tid, word_id=word_id))
    return {"id": word_id, "tag_ids": tag_ids}
