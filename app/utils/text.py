# -*- coding: utf-8 -*-
"""文本工具：英文单词提取、过滤。"""
from __future__ import annotations

import re

# 匹配英文单词（含 don't / teacher's 等撇号形态）
TOKEN_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")

# 常见停用词（docx 导入时过滤，提升生词质量）
STOPWORDS = frozenset(
    "a an the is are was were be been being am of and or to in on at for with by "
    "from as it its this that these those i you he she we they me my your his her "
    "our their do does did have has had not no yes but if then than so such can could "
    "may might must shall should will would what which who whom when where why how "
    "there here all any some one two both each every other another".split()
)


def extract_words(text: str) -> list[str]:
    """
    从文本中提取英文单词：正则匹配（天然过滤中文/数字/标点）→ 小写归一
    → 长度过滤 → 停用词过滤。返回去重前的单词列表。
    """
    tokens = (t.lower() for t in TOKEN_RE.findall(text))
    return [t for t in tokens if len(t) >= 2 and t not in STOPWORDS]
