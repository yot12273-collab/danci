# -*- coding: utf-8 -*-
"""闪卡抽查请求体模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QuizRequest(BaseModel):
    """发起一场抽查。

    - target 为 None 时默认等于标签下单词总数（抽查一遍）；
    - mode 可选 en2zh（英译中）/ zh2en（中译英）/ mix（混合）。
    """

    tag_id: int
    target: int | None = Field(default=None, ge=1, le=2000)
    mode: Literal["en2zh", "zh2en", "mix"] = "en2zh"
