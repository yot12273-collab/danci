# -*- coding: utf-8 -*-
"""账号认证接口：登录 / 登出 / 当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel

from ..dependencies import CurrentUser, get_current_user
from ..schemas.common import ok
from ..services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    """登录请求体。"""

    username: str
    password: str


@router.post("/login")
def login(body: LoginIn):
    """登录：校验账号密码，返回 token 与用户信息。"""
    return ok(auth_service.login(body.username, body.password))


@router.post("/logout")
def logout(
    authorization: str | None = Header(default=None),
    _user: CurrentUser = Depends(get_current_user),
):
    """登出：删除当前会话 token。"""
    token = ""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[len("Bearer "):].strip()
    auth_service.logout(token)
    return ok()


@router.get("/me")
def me(user: CurrentUser = Depends(get_current_user)):
    """返回当前登录用户（前端启动时校验 token 是否仍有效）。"""
    return ok({"id": user.id, "username": user.username})
