# -*- coding: utf-8 -*-
"""标签服务：CRUD + 标签下单词列表。"""
from __future__ import annotations

from sqlmodel import func, select

from ..database import session_scope
from ..models import Tag, TagWord, Word
from ..schemas.common import AppError, ERR_CONFLICT, ERR_NOT_FOUND, ERR_VALIDATION


def _word_count(session, tag_id: int) -> int:
    return session.exec(
        select(func.count()).select_from(TagWord).where(TagWord.tag_id == tag_id)
    ).one()


def list_tags() -> list[dict]:
    with session_scope() as session:
        tags = session.exec(select(Tag).order_by(Tag.created_at.desc())).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "color": t.color,
                "word_count": _word_count(session, t.id),
            }
            for t in tags
        ]


def _validate_name(session, name: str, exclude_id: int | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise AppError(ERR_VALIDATION, "标签名不能为空", http_status=422)
    if len(name) > 64:
        raise AppError(ERR_VALIDATION, "标签名过长（最多 64 字符）", http_status=422)
    stmt = select(Tag).where(Tag.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Tag.id != exclude_id)
    if session.exec(stmt).first():
        raise AppError(ERR_CONFLICT, "标签名已存在", http_status=409)
    return name


def create_tag(name: str, color: str | None = None) -> dict:
    with session_scope() as session:
        name = _validate_name(session, name)
        tag = Tag(name=name, color=color)
        session.add(tag)
        session.flush()
        return {"id": tag.id, "name": tag.name, "color": tag.color}


def update_tag(tag_id: int, name: str | None = None, color: str | None = None) -> dict:
    with session_scope() as session:
        tag = session.get(Tag, tag_id)
        if tag is None:
            raise AppError(ERR_NOT_FOUND, "标签不存在", http_status=404)
        if name is not None:
            tag.name = _validate_name(session, name, exclude_id=tag_id)
        if color is not None:
            tag.color = color
        session.flush()
        return {"id": tag.id, "name": tag.name, "color": tag.color}


def delete_tag(tag_id: int) -> None:
    with session_scope() as session:
        tag = session.get(Tag, tag_id)
        if tag is None:
            raise AppError(ERR_NOT_FOUND, "标签不存在", http_status=404)
        session.delete(tag)


def list_tag_words(tag_id: int) -> list[dict]:
    with session_scope() as session:
        tag = session.get(Tag, tag_id)
        if tag is None:
            raise AppError(ERR_NOT_FOUND, "标签不存在", http_status=404)
        words = session.exec(
            select(Word)
            .join(TagWord)
            .where(TagWord.tag_id == tag_id)
            .order_by(Word.lemma)
        ).all()
        return [
            {"id": w.id, "lemma": w.lemma, "primary_pos": w.primary_pos, "short_meaning": w.short_meaning}
            for w in words
        ]
