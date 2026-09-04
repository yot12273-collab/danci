# -*- coding: utf-8 -*-
"""时间工具：统一使用 UTC（存 naive 时间，便于 SQLite 读写）。"""
from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """返回不带时区信息的 UTC 当前时间（规避 Python 3.12+ 对 utcnow 的弃用）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)
