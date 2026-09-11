# -*- coding: utf-8 -*-
"""docx 批量导入接口（导入词与任务均归属当前登录账号）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from ..dependencies import CurrentUser, get_current_user
from ..schemas.common import ok
from ..services import docx_service

router = APIRouter(prefix="/api/import", tags=["import"], dependencies=[Depends(get_current_user)])


@router.post("/docx")
async def upload_docx(file: UploadFile = File(...), user: CurrentUser = Depends(get_current_user)):
    """上传 docx，返回任务 id，前端轮询进度（导入内容归属当前账号）。"""
    data = await file.read()
    job_id = docx_service.create_job(data, file.filename or "upload.docx", user.id)
    return ok({"job_id": job_id, "status": "queued"})


@router.get("/{job_id}")
def get_job_status(job_id: str, user: CurrentUser = Depends(get_current_user)):
    """查询导入任务进度（仅限本账号发起的任务）。"""
    return ok(docx_service.get_job(job_id, user.id))
