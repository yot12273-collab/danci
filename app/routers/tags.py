# -*- coding: utf-8 -*-
"""标签相关接口（均按当前登录账号隔离）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import CurrentUser, get_current_user
from ..schemas.common import ok
from ..schemas.tag import TagCreate, TagUpdate
from ..services import tag_service

router = APIRouter(prefix="/api/tags", tags=["tags"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_tags(user: CurrentUser = Depends(get_current_user)):
    return ok(tag_service.list_tags(user.id))


@router.post("")
def create_tag(body: TagCreate, user: CurrentUser = Depends(get_current_user)):
    return ok(tag_service.create_tag(body.name, body.color, user.id))


@router.put("/{tag_id}")
def update_tag(tag_id: int, body: TagUpdate, user: CurrentUser = Depends(get_current_user)):
    return ok(tag_service.update_tag(tag_id, body.name, body.color, user.id))


@router.delete("/{tag_id}")
def delete_tag(tag_id: int, user: CurrentUser = Depends(get_current_user)):
    return ok(tag_service.delete_tag(tag_id, user.id))


@router.get("/{tag_id}/words")
def list_tag_words(tag_id: int, user: CurrentUser = Depends(get_current_user)):
    return ok(tag_service.list_tag_words(tag_id, user.id))
