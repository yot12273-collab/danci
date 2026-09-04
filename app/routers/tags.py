# -*- coding: utf-8 -*-
"""标签相关接口。"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas.common import ok
from ..schemas.tag import TagCreate, TagUpdate
from ..services import tag_service

router = APIRouter(prefix="/api/tags", tags=["tags"])


@router.get("")
def list_tags():
    return ok(tag_service.list_tags())


@router.post("")
def create_tag(body: TagCreate):
    return ok(tag_service.create_tag(body.name, body.color))


@router.put("/{tag_id}")
def update_tag(tag_id: int, body: TagUpdate):
    return ok(tag_service.update_tag(tag_id, body.name, body.color))


@router.delete("/{tag_id}")
def delete_tag(tag_id: int):
    return ok(tag_service.delete_tag(tag_id))


@router.get("/{tag_id}/words")
def list_tag_words(tag_id: int):
    return ok(tag_service.list_tag_words(tag_id))
