# -*- coding: utf-8 -*-
"""查询历史服务：记录 / 列表 / 单删 / 清空。"""
from __future__ import annotations

from sqlmodel import Session, func, select

from ..database import session_scope
from ..models import SearchHistory
from ..schemas.common import AppError, ERR_NOT_FOUND


def record(session: Session, query: str, lemma: str | None, user_id: int) -> None:
    """在已有 session 内记录一条历史（按 (user_id, query) 去重，新记录插入到最前）。"""
    # 删除同用户同 query 的旧记录，实现“按输入原文去重”
    for old in session.exec(
        select(SearchHistory).where(
            SearchHistory.user_id == user_id, SearchHistory.query == query
        )
    ).all():
        session.delete(old)
    session.add(SearchHistory(user_id=user_id, query=query, lemma=lemma))


def list_history(page: int = 1, page_size: int = 20, user_id: int | None = None) -> dict:
    with session_scope() as session:
        count_stmt = select(func.count()).select_from(SearchHistory)
        stmt = select(SearchHistory)
        if user_id is not None:
            count_stmt = count_stmt.where(SearchHistory.user_id == user_id)
            stmt = stmt.where(SearchHistory.user_id == user_id)
        total = session.exec(count_stmt).one()
        rows = session.exec(
            stmt.order_by(SearchHistory.searched_at.desc())
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


def delete_history(history_id: int, user_id: int) -> None:
    with session_scope() as session:
        h = session.exec(
            select(SearchHistory).where(
                SearchHistory.id == history_id, SearchHistory.user_id == user_id
            )
        ).first()
        if h is None:
            raise AppError(ERR_NOT_FOUND, "历史记录不存在", http_status=404)
        session.delete(h)


def clear_history(user_id: int) -> None:
    with session_scope() as session:
        for h in session.exec(
            select(SearchHistory).where(SearchHistory.user_id == user_id)
        ).all():
            session.delete(h)
