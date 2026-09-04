# -*- coding: utf-8 -*-
"""
docx_service.py —— Word 文档导入服务

流程：
1. 校验文件类型（.docx）与大小；
2. 后台线程解析段落 + 表格中的文本，提取英文单词（过滤中文/标点、去重）；
3. 逐个做词法还原（非法词跳过）；
4. 以文件名创建标签，单词按词根批量入库并关联该标签；
5. 通过内存 JobManager 暴露“排队 / 处理中 / 完成 / 失败”的进度，前端轮询。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from pathlib import Path

from docx import Document
from sqlmodel import select

from ..config import settings
from ..database import session_scope
from ..models import Tag, TagWord, Word
from ..schemas.common import (
    AppError,
    ERR_FILE_TOO_LARGE,
    ERR_NOT_FOUND,
    ERR_UNSUPPORTED_TYPE,
)
from ..utils.text import extract_words
from . import nlp_engine
from .dictionary import dictionary

logger = logging.getLogger(__name__)

# 内存任务表（本机单进程足够；如需多进程可替换为 Redis）
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _update(job_id: str, **kw) -> None:
    with _lock:
        _jobs[job_id].update(kw)


def create_job(file_bytes: bytes, filename: str) -> str:
    """创建导入任务并启动后台线程，返回 job_id。"""
    if not (filename or "").lower().endswith(".docx"):
        raise AppError(ERR_UNSUPPORTED_TYPE, "仅支持 .docx 文件", http_status=415)
    if len(file_bytes) > settings.max_upload_size:
        raise AppError(ERR_FILE_TOO_LARGE, "文件过大（上限 10MB）", http_status=413)

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {"status": "queued", "progress": {}, "filename": filename}
    threading.Thread(target=_process, args=(job_id, file_bytes, filename), daemon=True).start()
    return job_id


def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise AppError(ERR_NOT_FOUND, "任务不存在", http_status=404)
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "error": job.get("error"),
    }


def _extract_docx_text(file_bytes: bytes) -> list[str]:
    """解析 docx，返回段落与表格单元格中的全部文本。"""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name
    try:
        doc = Document(tmp_path)
        texts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    texts.append(cell.text)
        return texts
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _process(job_id: str, file_bytes: bytes, filename: str) -> None:
    _update(job_id, status="processing")
    try:
        texts = _extract_docx_text(file_bytes)

        # 1) 提取英文单词并去重
        raw_words: set[str] = set()
        for text in texts:
            raw_words.update(extract_words(text))
        scanned = len(raw_words)
        _update(job_id, progress={"filename": filename, "scanned": scanned})

        # 2) 词法还原 + 收集主词性
        # 兜底策略：词法校验失败（词库缺失/损坏、词未收录、无法还原）时不丢弃该词，
        # 直接以原始词形入库，保证“有效”绝不因词库问题归零。
        lemma_infos: dict[str, str | None] = {}
        skipped = 0
        fallback = 0
        for w in raw_words:
            try:
                nlp = nlp_engine.analyze(w)
                lemma_infos.setdefault(nlp["base"], nlp.get("pos_label"))
            except nlp_engine.InvalidWordError:
                fallback += 1
                lemma_infos.setdefault(w, None)
        valid = len(lemma_infos)
        if fallback:
            logger.warning(
                "docx 导入：%d 个词词法校验失败，已按原始词形兜底入库（避免“有效”归零）", fallback
            )
        _update(job_id, progress={
            "filename": filename, "scanned": scanned,
            "valid": valid, "skipped": skipped,
        })

        # 3) 入库：以文件名建标签，单词批量入库并关联
        tag_name = Path(filename).stem or "未命名"
        inserted = duplicates = 0
        with session_scope() as session:
            tag = session.exec(select(Tag).where(Tag.name == tag_name)).first()
            if tag is None:
                tag = Tag(name=tag_name)
                session.add(tag)
                session.flush()

            for lemma, pos_label in lemma_infos.items():
                trans = dictionary.lookup(lemma)
                word = session.exec(select(Word).where(Word.lemma == lemma)).first()
                if word is None:
                    word = Word(
                        lemma=lemma,
                        primary_pos=pos_label,
                        phonetic=trans["phonetic"] if trans else None,
                        short_meaning=trans["short_meaning"] if trans else None,
                        translation=json.dumps(trans["translations"], ensure_ascii=False)
                        if trans else None,
                    )
                    session.add(word)
                    session.flush()
                    inserted += 1
                else:
                    duplicates += 1
                # 关联标签（已存在则跳过）
                exists = session.exec(
                    select(TagWord).where(TagWord.tag_id == tag.id, TagWord.word_id == word.id)
                ).first()
                if exists is None:
                    session.add(TagWord(tag_id=tag.id, word_id=word.id))
            tag_id = tag.id

        _update(job_id, status="done", progress={
            "filename": filename, "scanned": scanned, "valid": valid,
            "inserted": inserted, "duplicates": duplicates, "skipped": skipped,
            "tag_name": tag_name, "tag_id": tag_id,
        })
    except Exception as exc:  # noqa: BLE001 —— 后台任务需兜底所有异常
        _update(job_id, status="error", error=str(exc))
