# -*- coding: utf-8 -*-
"""数据模型注册：导入全部表模型，供 SQLModel.metadata.create_all 使用。"""
from .recite import RecitePlan, RecitePlanWord
from .search_history import SearchHistory
from .session import Session
from .tag import Tag
from .tag_word import TagWord
from .user import User
from .word import Word

__all__ = [
    "Tag",
    "Word",
    "TagWord",
    "SearchHistory",
    "RecitePlan",
    "RecitePlanWord",
    "User",
    "Session",
]
