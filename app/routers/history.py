# -*- coding: utf-8 -*-
"""查询历史相关接口。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..schemas.common import ok
from ..services import history_service

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
):
    return ok(history_service.list_history(page, page_size))


@router.delete("/{history_id}")
def delete_history(history_id: int):
    return ok(history_service.delete_history(history_id))


@router.delete("")
def clear_history():
    return ok(history_service.clear_history())
