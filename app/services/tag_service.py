# -*- coding: utf-8 -*-
"""标签服务：CRUD + 标签下单词列表（严格按登录账号隔离）。"""
from __future__ import annotations

from sqlmodel import Session, func, select

from ..database import session_scope
from ..models import Tag, TagWord, Word
from ..schemas.common import AppError, ERR_CONFLICT, ERR_NOT_FOUND, ERR_VALIDATION


def _word_count(session, tag_id: int) -> int:
    return session.exec(
        select(func.count()).select_from(TagWord).where(TagWord.tag_id == tag_id)
    ).one()


def _get_owned_tag(session: Session, tag_id: int, user_id: int) -> Tag:
    """按「id + user_id」取当前账号的标签；不存在（含他人标签）统一 404，杜绝越权访问。"""
    tag = session.exec(
        select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
    ).first()
    if tag is None:
        raise AppError(ERR_NOT_FOUND, "标签不存在", http_status=404)
    return tag


def list_tags(user_id: int) -> list[dict]:
    """列出当前账号的全部标签。"""
    with session_scope() as session:
        tags = session.exec(
            select(Tag).where(Tag.user_id == user_id).order_by(Tag.created_at.desc())
        ).all()
        return [
            {
                "id": t.id,
                "name": t.name,
                "color": t.color,
                "word_count": _word_count(session, t.id),
            }
            for t in tags
        ]


def _validate_name(session: Session, name: str, user_id: int, exclude_id: int | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise AppError(ERR_VALIDATION, "标签名不能为空", http_status=422)
    if len(name) > 64:
        raise AppError(ERR_VALIDATION, "标签名过长（最多 64 字符）", http_status=422)
    # 重名校验仅在「当前账号内」进行（跨账号允许同名）
    stmt = select(Tag).where(Tag.name == name, Tag.user_id == user_id)
    if exclude_id is not None:
        stmt = stmt.where(Tag.id != exclude_id)
    if session.exec(stmt).first():
        raise AppError(ERR_CONFLICT, "标签名已存在", http_status=409)
    return name


def create_tag(name: str, color: str | None, user_id: int) -> dict:
    with session_scope() as session:
        name = _validate_name(session, name, user_id)
        tag = Tag(name=name, color=color, user_id=user_id)
        session.add(tag)
        session.flush()
        return {"id": tag.id, "name": tag.name, "color": tag.color}


def update_tag(tag_id: int, name: str | None, color: str | None, user_id: int) -> dict:
    with session_scope() as session:
        tag = _get_owned_tag(session, tag_id, user_id)
        if name is not None:
            tag.name = _validate_name(session, name, user_id, exclude_id=tag_id)
        if color is not None:
            tag.color = color
        session.flush()
        return {"id": tag.id, "name": tag.name, "color": tag.color}


def delete_tag(tag_id: int, user_id: int) -> None:
    with session_scope() as session:
        tag = _get_owned_tag(session, tag_id, user_id)
        session.delete(tag)


def list_tag_words(tag_id: int, user_id: int) -> list[dict]:
    with session_scope() as session:
        _get_owned_tag(session, tag_id, user_id)
        words = session.exec(
            select(Word)
            .join(TagWord)
            .where(TagWord.tag_id == tag_id, Word.user_id == user_id)
            .order_by(Word.lemma)
        ).all()
        return [
            {"id": w.id, "lemma": w.lemma, "primary_pos": w.primary_pos, "short_meaning": w.short_meaning}
            for w in words
        ]
