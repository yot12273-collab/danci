# -*- coding: utf-8 -*-
"""查询历史相关接口（按登录用户隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..dependencies import CurrentUser, get_current_user
from ..schemas.common import ok
from ..services import history_service

router = APIRouter(prefix="/api/history", tags=["history"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    user: CurrentUser = Depends(get_current_user),
):
    return ok(history_service.list_history(page, page_size, user.id))


@router.delete("/{history_id}")
def delete_history(history_id: int, user: CurrentUser = Depends(get_current_user)):
    return ok(history_service.delete_history(history_id, user.id))


@router.delete("")
def clear_history(user: CurrentUser = Depends(get_current_user)):
    return ok(history_service.clear_history(user.id))
