# -*- coding: utf-8 -*-
"""背诵计划相关数据模型（切片式自动计时背诵 · 按标签隔离 · 自由选份）。

设计要点：
1. 「计划主表」recite_plans 记录方案参数与分组结构；每个标签最多一条计划（tag_id 唯一）；
2. 「单词快照表」recite_plan_words 固化创建时「该标签下」的词序，
   份之间按 seq 连续切片，从而保证同一计划内任何单词绝不重复分发；
3. 分组持久化：快照词序固定不变，重启后同标签看到的仍是同一套切片（艾宾浩斯间隔复习）；
4. 无完成态：不维护进度字段，前端自由点击任一份 / 反复重背，由用户全权掌控；
5. 级联删除：删除标签 → 其计划与快照一并删除（依赖全局 PRAGMA foreign_keys=ON）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from ..utils.time import utcnow

# ---------- 方案类型常量 ----------
PLAN_TYPE_COUNT = "count"   # 按数量分
PLAN_TYPE_RATIO = "ratio"   # 按比例分


class RecitePlan(SQLModel, table=True):
    """背诵计划主表：记录方案参数与分组结构（按标签隔离，无完成态）。"""

    __tablename__ = "recite_plans"
    # 一个标签最多一条计划（含未重置的计划）
    __table_args__ = (UniqueConstraint("tag_id", name="uq_recite_tag"),)

    id: int | None = Field(default=None, primary_key=True)
    # 归属标签：删标签时级联删除该标签的背诵分组
    tag_id: int = Field(foreign_key="tags.id", index=True, ondelete="CASCADE")
    # 方案类型：count（按数量）/ ratio（按比例）
    plan_type: str = Field(max_length=8)
    # 设定参数：数量为整数（如 100）；比例为百分数（如 10 表示 10%，可带小数）
    param: float
    # 制定计划时该标签下单词总数（快照值，固定不变，用于前端展示与校验）
    total_words: int
    # 每份单词数（最后一份可能不足）
    chunk_size: int
    # 总份数 N
    total_chunks: int
    # 轮播时间间隔（秒）
    interval_seconds: int = Field(default=5)
    # 切片内是否打乱：True=每次进入某份背诵时前端随机洗牌；False=严格按快照固定顺序（行为参数）
    shuffle_chunk: bool = Field(default=False)
    # 背诵期间是否显示「下一个」按钮：True=常规态显示；False=常规态隐藏，仅尾词强制显示「进入下一份」（行为参数）
    show_next_button: bool = Field(default=True)
    # 背诵序列：JSON 数组字符串（如 "[1,2,3]"），记录「进入下一份」时按此顺序无限循环（行为参数）。
    # 留空时由服务层降级为默认 [1..total_chunks]；此处始终存储为具体的 JSON 序列。
    sequence_list: str = Field(default="")
    # 当前进行到的序列索引（0 起）：进入下一份时取模递增 (idx+1) % len，实现无限循环。
    current_sequence_index: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RecitePlanWord(SQLModel, table=True):
    """计划单词快照表：固化创建时的词序，份之间按 seq 连续切片，保证不重复。"""

    __tablename__ = "recite_plan_words"
    __table_args__ = (UniqueConstraint("plan_id", "seq", name="uq_plan_seq"),)

    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="recite_plans.id", index=True, ondelete="CASCADE")
    # 计划内全局顺序（0 起），创建时洗牌后固定写入
    seq: int
    # 单词引用；词库删词时该快照行级联删除（该词不再参与后续背诵）
    word_id: int = Field(foreign_key="words.id", index=True, ondelete="CASCADE")
