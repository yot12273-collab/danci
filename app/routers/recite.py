# -*- coding: utf-8 -*-
"""背诵计划相关接口（按标签隔离 · 自由选份 · 严格按登录账号隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..dependencies import CurrentUser, get_current_user
from ..schemas.common import ok
from ..schemas.recite import RecitePlanCreate
from ..services import recite_service

router = APIRouter(prefix="/api/recite", tags=["recite"], dependencies=[Depends(get_current_user)])


@router.get("/plan")
def get_plan(tag_id: int = Query(..., ge=1), user: CurrentUser = Depends(get_current_user)):
    """查询指定标签的计划及分组结构（无计划时 data 为 null）。"""
    return ok(recite_service.get_plan(tag_id, user.id))


@router.post("/plan")
def save_plan(body: RecitePlanCreate, tag_id: int = Query(..., ge=1), user: CurrentUser = Depends(get_current_user)):
    """智能保存指定标签的背诵计划：新建 / 仅改行为参数（局部更新）/ 改内容参数（彻底重置）。"""
    return ok(
        recite_service.save_plan(
            tag_id,
            body.plan_type,
            body.param,
            body.interval_seconds,
            body.shuffle_chunk,
            body.sequence,
            body.show_next_button,
            user.id,
        )
    )


@router.post("/advance")
def advance_sequence(tag_id: int = Query(..., ge=1), user: CurrentUser = Depends(get_current_user)):
    """背诵序列无限循环路由：当前指针取模前进一位，返回下一个切片序号。

    无强制终点——指针永远在 [0, len) 内回绕（1->2->3->1…），
    「结束」只由前端底部「结束本次背诵」按钮触发。
    """
    return ok(recite_service.advance_sequence(tag_id, user.id))


@router.delete("/plan")
def reset_plan(tag_id: int = Query(..., ge=1), user: CurrentUser = Depends(get_current_user)):
    """中止/重置指定标签的计划（分组清空）。"""
    return ok(recite_service.reset_plan(tag_id, user.id))


@router.get("/chunk")
def get_chunk(
    tag_id: int = Query(..., ge=1),
    index: int = Query(..., ge=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    seed: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
):
    """获取指定标签第 index 份（1 起）的单词详情切片（分批拉取，默认 10 词一批）。"""
    return ok(recite_service.get_chunk(tag_id, index, offset=offset, limit=limit, seed=seed, user_id=user.id))
