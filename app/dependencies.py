# -*- coding: utf-8 -*-
"""FastAPI 依赖：从请求头解析当前登录用户。"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header
from sqlmodel import select

from .database import session_scope
from .models import Session, User
from .schemas.common import AppError, ERR_UNAUTHORIZED


@dataclass
class CurrentUser:
    """当前登录用户（轻量对象，避免返回跨会话过期的 ORM 实例）。"""

    id: int
    username: str


def _extract_token(authorization: str | None) -> str | None:
    """从 Authorization 头解析 Bearer token，缺失或非法返回 None。"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
        if token:
            return token
    return None


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """校验 token 并返回当前用户；未登录或 token 失效抛 401。"""
    token = _extract_token(authorization)
    if token is None:
        raise AppError(ERR_UNAUTHORIZED, "请先登录", http_status=401)
    with session_scope() as session:
        row = session.exec(select(Session).where(Session.token == token)).first()
        if row is None:
            raise AppError(ERR_UNAUTHORIZED, "登录已失效，请重新登录", http_status=401)
        user = session.get(User, row.user_id)
        if user is None:
            raise AppError(ERR_UNAUTHORIZED, "登录已失效，请重新登录", http_status=401)
        # 会话关闭前取出字段，避免 SQLAlchemy 对象提交后过期导致访问报错
        return CurrentUser(id=user.id, username=user.username)
