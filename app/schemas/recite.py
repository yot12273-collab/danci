# -*- coding: utf-8 -*-
"""背诵计划请求体模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RecitePlanCreate(BaseModel):
    """制定/保存背诵计划（目标标签 tag_id 通过查询参数传入）。

    - plan_type：count（按数量）/ ratio（按比例）；
    - param：按数量时为整数（1~该标签词数）；按比例时为百分数（0<param<=100，可小数）；
    - interval_seconds：轮播时间间隔（秒，1~600）；
    - shuffle_chunk：切片内是否打乱（True=每次进入某份时前端随机洗牌）；
    - sequence：背诵序列（空格分隔的份序号，如 "1 2 1 2 3"）；留空由服务层降级为默认 [1..N]；
    - show_next_button：背诵期间是否显示「下一个」按钮（False=常规态隐藏，仅尾词强制显示）。
    """

    plan_type: Literal["count", "ratio"]
    param: float = Field(..., gt=0)
    interval_seconds: int = Field(default=5, ge=1, le=600)
    shuffle_chunk: bool = Field(default=False)
    sequence: str = Field(default="", max_length=500)
    show_next_button: bool = Field(default=True)
