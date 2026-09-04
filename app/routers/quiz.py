# -*- coding: utf-8 -*-
"""闪卡抽查接口。"""
from __future__ import annotations

from fastapi import APIRouter

from ..schemas.common import ok
from ..schemas.quiz import QuizRequest
from ..services import quiz_service

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


@router.post("")
def start_quiz(body: QuizRequest):
    """发起一场抽查，返回完整卡片序列（无状态）。"""
    return ok(quiz_service.start_quiz(body.tag_id, body.target, body.mode))
