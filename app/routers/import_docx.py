# -*- coding: utf-8 -*-
"""docx 批量导入接口。"""
from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from ..schemas.common import ok
from ..services import docx_service

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("/docx")
async def upload_docx(file: UploadFile = File(...)):
    """上传 docx，返回任务 id，前端轮询进度。"""
    data = await file.read()
    job_id = docx_service.create_job(data, file.filename or "upload.docx")
    return ok({"job_id": job_id, "status": "queued"})


@router.get("/{job_id}")
def get_job_status(job_id: str):
    """查询导入任务进度。"""
    return ok(docx_service.get_job(job_id))
