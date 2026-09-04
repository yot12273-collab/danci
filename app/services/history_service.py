# -*- coding: utf-8 -*-
"""查询历史服务：记录 / 列表 / 单删 / 清空。"""
from __future__ import annotations

from sqlmodel import Session, func, select

from ..database import session_scope
from ..models import SearchHistory
from ..schemas.common import AppError, ERR_NOT_FOUND


def record(session: Session, query: str, lemma: str | None) -> None:
    """在已有 session 内记录一条历史（按输入原文去重，新记录插入到最前）。"""
    # 删除同 query 的旧记录，实现“按输入原文去重”
    for old in session.exec(
        select(SearchHistory).where(SearchHistory.query == query)
    ).all():
        session.delete(old)
    session.add(SearchHistory(query=query, lemma=lemma))


def list_history(page: int = 1, page_size: int = 20) -> dict:
    with session_scope() as session:
        total = session.exec(
            select(func.count()).select_from(SearchHistory)
        ).one()
        rows = session.exec(
            select(SearchHistory)
            .order_by(SearchHistory.searched_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        items = [
            {
                "id": h.id,
                "query": h.query,
                "lemma": h.lemma,
                "searched_at": h.searched_at.isoformat() if h.searched_at else None,
            }
            for h in rows
        ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def delete_history(history_id: int) -> None:
    with session_scope() as session:
        h = session.get(SearchHistory, history_id)
        if h is None:
            raise AppError(ERR_NOT_FOUND, "历史记录不存在", http_status=404)
        session.delete(h)


def clear_history() -> None:
    with session_scope() as session:
        for h in session.exec(select(SearchHistory)).all():
            session.delete(h)
