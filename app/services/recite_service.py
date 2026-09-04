# -*- coding: utf-8 -*-
"""
recite_service.py —— 切片式自动计时背诵服务（按标签隔离 · 自由选份 · 智能判定）

核心逻辑：
1. 制定计划：取「指定标签下」的全部单词洗牌一次后固化到快照表，按「数量 / 比例」均分为 N 份；
2. 分组持久化：快照表 recite_plan_words 固化洗牌后的固定词序，份 = 按 seq 连续切片，
   因此同一标签计划内任何单词最多出现在一份中，且跨会话分组结构恒定不变（艾宾浩斯间隔复习）；
3. 自由选份：不维护「完成进度」。前端可任意点击任一份开始背诵，也支持反复重背同一份；
4. 防重复保证：快照顺序固定、份之间是不重叠的连续切片，天然杜绝重复分发。

智能判定（save_plan）：
参数分两类——「内容参数」(plan_type, param) 决定抽取与分块；「行为参数」
(interval_seconds, shuffle_chunk, sequence_list) 仅影响背诵过程表现。以内容参数为指纹比对——
- 无计划            → 全新创建（洗牌 + 分块）；
- 内容指纹一致      → 局部更新：仅改写行为参数（间隔 / 打乱开关 / 背诵序列），保留既有分块与复习进度（绝不删除）；
- 内容指纹变化      → 彻底重置：删除旧计划及其快照，重新抽取、洗牌、分块。

背诵序列（无限循环播放）：
用户可自定义「份序号」播放顺序（如 1 2 1 2 3，空格分隔，兼容多个连续空格），
留空自动降级为默认 [1..N]。进入下一份时对指针取模 (idx+1) % len 实现无限循环，
永不因序列耗尽而结束——「结束本次背诵」完全由用户手动触发。
"""
from __future__ import annotations

import json
import math
import random
import re

from sqlmodel import select

from ..database import session_scope
from ..models import Tag, TagWord, Word
from ..models.recite import (
    PLAN_TYPE_COUNT,
    PLAN_TYPE_RATIO,
    RecitePlan,
    RecitePlanWord,
)
from ..schemas.common import (
    AppError,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)
from ..utils.time import utcnow
from .word_service import batch_details

# 轮播间隔允许范围（秒）
INTERVAL_MIN = 1
INTERVAL_MAX = 600


def _chunk_counts(session, plan: RecitePlan) -> list[dict]:
    """按快照实际词序统计每份的实际词数。

    词库删词会导致快照行级联缺失（seq 出现空洞），故需按 seq 分组真实统计，
    而非直接用 chunk_size 推算——保证前端「第 N 份 (X词)」显示的是可背的实词数。
    返回 [{"index": 1, "word_count": 30}, ...]，index 从 1 起。
    """
    seqs = session.exec(
        select(RecitePlanWord.seq)
        .where(RecitePlanWord.plan_id == plan.id)
        .order_by(RecitePlanWord.seq)
    ).all()
    counts: dict[int, int] = {}
    for s in seqs:
        idx = s // plan.chunk_size
        counts[idx] = counts.get(idx, 0) + 1
    return [
        {"index": i + 1, "word_count": counts.get(i, 0)}
        for i in range(plan.total_chunks)
    ]


def _parse_sequence(raw: str, total_chunks: int) -> list[int]:
    """解析「空格分隔的背诵序列」，空串自动降级为默认 [1..total_chunks]。

    规则：
    - 用正则 \\s+ 分割（兼容多个连续空格、换行、制表符）；
    - 每一项必须是整数，且落在 [1, total_chunks] 区间（越界或非数字即抛 422），
      杜绝生成指向「不存在切片」的序列；
    - 允许重复（如 1 2 1 2 3），这是无限循环复习的核心。
    """
    text = (raw or "").strip()
    if not text:
        # 默认降级：按当前总份数生成顺序序列
        return list(range(1, total_chunks + 1))

    seq: list[int] = []
    for part in re.split(r"\s+", text):
        if not part.isdigit():
            raise AppError(
                ERR_VALIDATION,
                f"背诵序列包含非法项：{part!r}，仅支持空格分隔的整数",
                http_status=422,
            )
        n = int(part)
        if n < 1 or n > total_chunks:
            raise AppError(
                ERR_VALIDATION,
                f"背诵序列项需在 1~{total_chunks} 之间，得到 {n}",
                http_status=422,
            )
        seq.append(n)
    return seq


def _sequence_of(p: RecitePlan) -> list[int]:
    """安全读取计划内存储的序列 JSON；为空/损坏时降级为默认 [1..total_chunks]。"""
    try:
        arr = json.loads(p.sequence_list or "[]")
        if isinstance(arr, list) and arr:
            return [int(x) for x in arr]
    except (ValueError, TypeError):
        pass
    return list(range(1, p.total_chunks + 1))


def _plan_to_dict(session, p: RecitePlan) -> dict:
    """把计划模型序列化为前端使用的摘要字典（含每份分组信息与背诵序列）。"""
    return {
        "id": p.id,
        "tag_id": p.tag_id,
        "plan_type": p.plan_type,
        "param": p.param,
        "total_words": p.total_words,
        "chunk_size": p.chunk_size,
        "total_chunks": p.total_chunks,
        "interval_seconds": p.interval_seconds,
        "shuffle_chunk": p.shuffle_chunk,
        "show_next_button": p.show_next_button,
        "sequence_list": _sequence_of(p),
        "current_sequence_index": p.current_sequence_index,
        "chunks": _chunk_counts(session, p),
    }


def _compute_chunks(plan_type: str, param: float, total: int) -> tuple[int, int]:
    """按方案类型计算 (每份单词数 chunk_size, 总份数 total_chunks)。"""
    if plan_type == PLAN_TYPE_COUNT:
        # 按数量：必须是整数，且落在 [1, total] 区间
        if param != int(param):
            raise AppError(ERR_VALIDATION, "按数量分时，单次数量需为整数", http_status=422)
        count = int(param)
        if count < 1 or count > total:
            raise AppError(ERR_VALIDATION, f"单次数量需在 1~{total} 之间", http_status=422)
        chunk_size = count
    elif plan_type == PLAN_TYPE_RATIO:
        # 按比例：百分数，落在 (0, 100] 区间，可带小数
        if param <= 0 or param > 100:
            raise AppError(ERR_VALIDATION, "单次比例需在 0~100（%）之间", http_status=422)
        chunk_size = max(1, round(total * param / 100))
    else:
        raise AppError(ERR_VALIDATION, "不支持的方案类型", http_status=422)

    total_chunks = math.ceil(total / chunk_size)
    return chunk_size, total_chunks


def _get_tag(session, tag_id: int) -> Tag:
    """校验标签存在；不存在则 404。"""
    tag = session.get(Tag, tag_id)
    if tag is None:
        raise AppError(ERR_NOT_FOUND, "标签不存在", http_status=404)
    return tag


def _get_active_plan(session, tag_id: int) -> RecitePlan:
    """取指定标签下的唯一计划；标签或计划不存在则 404。"""
    _get_tag(session, tag_id)
    plan = session.exec(
        select(RecitePlan).where(RecitePlan.tag_id == tag_id)
    ).first()
    if plan is None:
        raise AppError(ERR_NOT_FOUND, "该标签暂无背诵计划，请先制定", http_status=404)
    return plan


def _build_plan(session, tag_id: int, plan_type: str, param: float, interval_seconds: int, shuffle_chunk: bool, sequence: str, show_next_button: bool = True) -> dict:
    """在当前会话内完成「抽取词库 → 洗牌 → 分块 → 写入」，返回计划摘要。

    供「全新创建」与「彻底重置（内容变动）」两处复用；任何校验失败抛出 AppError，
    由外层 session_scope 回滚，绝不留下半成品数据。背诵序列在此解析并固化写入主表。
    """
    # 取该标签下全部单词 id（仅当前标签词库）
    word_ids = session.exec(
        select(Word.id)
        .join(TagWord)
        .where(TagWord.tag_id == tag_id)
        .order_by(Word.id)
    ).all()
    total = len(word_ids)
    if total == 0:
        raise AppError(ERR_VALIDATION, "该标签下暂无单词，无法制定背诵计划", http_status=422)

    # 计算每份大小与总份数
    chunk_size, total_chunks = _compute_chunks(plan_type, param, total)

    # 解析背诵序列（空串降级为默认 [1..N]；越界/非法项在此抛 422，回滚整次创建）
    seq = _parse_sequence(sequence, total_chunks)

    # 洗牌一次并固定顺序（保证份之间不重复、顺序随机）
    shuffled = list(word_ids)
    random.shuffle(shuffled)

    # 写入主表
    plan = RecitePlan(
        tag_id=tag_id,
        plan_type=plan_type,
        param=param,
        total_words=total,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        interval_seconds=interval_seconds,
        shuffle_chunk=shuffle_chunk,
        show_next_button=show_next_button,
        sequence_list=json.dumps(seq),   # 固化后的序列 JSON（非空）
        current_sequence_index=0,        # 新计划从头开始
    )
    session.add(plan)
    session.flush()  # 立即拿到 plan.id 供快照表外键使用

    # 写入单词快照（seq = 洗牌后的顺序下标）
    for seq, wid in enumerate(shuffled):
        session.add(RecitePlanWord(plan_id=plan.id, seq=seq, word_id=wid))

    return _plan_to_dict(session, plan)


def _delete_plan(session, plan: RecitePlan) -> None:
    """显式删除计划的快照与主表（不依赖外键级联，杜绝孤儿快照）。"""
    for rpw in session.exec(
        select(RecitePlanWord).where(RecitePlanWord.plan_id == plan.id)
    ).all():
        session.delete(rpw)
    session.delete(plan)


def get_plan(tag_id: int) -> dict | None:
    """查询指定标签的计划及分组结构；无计划时返回 None。"""
    with session_scope() as session:
        _get_tag(session, tag_id)
        plan = session.exec(
            select(RecitePlan).where(RecitePlan.tag_id == tag_id)
        ).first()
        return _plan_to_dict(session, plan) if plan else None


def save_plan(tag_id: int, plan_type: str, param: float, interval_seconds: int, shuffle_chunk: bool = False, sequence: str = "", show_next_button: bool = True) -> dict:
    """智能保存背诵计划：新建 / 局部更新（仅改行为参数）/ 彻底重置（改内容参数）。

    参数划分为两类：
    - 内容参数 = (plan_type, param)：决定「抽取哪些词、如何分块」，变动即需彻底重置；
    - 行为参数 = (interval_seconds, shuffle_chunk, sequence_list, show_next_button)：只影响背诵过程表现，变动仅局部更新。

    判定核心：以「方案类型 + 内容参数」为指纹，与本地已有记录比对——
    - 情况 A（内容未变）：仅行为参数（间隔 / 打乱开关 / 背诵序列 / 按钮显隐）变化，只更新这些项，
      保留全部既有分块与进度（绝不删除）；其中「背诵序列变化」会把进行索引重置回 0；
    - 情况 B（内容已变）：删除旧计划及其快照，重新抽取、洗牌、分块（序列一并重建）；
    - 无计划：全新创建。

    返回计划摘要（含 chunks 分组 / 背诵序列 / 进行索引 / 按钮显隐），并附 action 标记
    （created / updated / reset），供前端区分提示与切面。整个过程单会话内完成，
    异常即整体回滚，绝不产生半成品。
    """
    # 校验间隔
    if not (INTERVAL_MIN <= interval_seconds <= INTERVAL_MAX):
        raise AppError(
            ERR_VALIDATION,
            f"时间间隔需在 {INTERVAL_MIN}~{INTERVAL_MAX} 秒之间",
            http_status=422,
        )

    param = float(param)
    shuffle_chunk = bool(shuffle_chunk)
    show_next_button = bool(show_next_button)
    sequence = sequence or ""

    with session_scope() as session:
        _get_tag(session, tag_id)
        existing = session.exec(
            select(RecitePlan).where(RecitePlan.tag_id == tag_id)
        ).first()

        # 情况 A：已存在且内容指纹一致 → 仅更新行为参数，保留分块与进度
        if existing is not None and existing.plan_type == plan_type and existing.param == param:
            # 解析新序列（空串降级默认 [1..N]），对比既有序列决定是否重置进行索引
            new_seq = _parse_sequence(sequence, existing.total_chunks)
            if new_seq != _sequence_of(existing):
                existing.sequence_list = json.dumps(new_seq)
                existing.current_sequence_index = 0   # 序列变了 → 从头开始新循环
            existing.interval_seconds = interval_seconds
            existing.shuffle_chunk = shuffle_chunk
            existing.show_next_button = show_next_button
            existing.updated_at = utcnow()
            return {"action": "updated", **_plan_to_dict(session, existing)}

        # 情况 B：已存在但内容指纹变化 → 先彻底删除旧计划与快照，再重建
        action = "created"
        if existing is not None:
            _delete_plan(session, existing)
            action = "reset"

        result = _build_plan(session, tag_id, plan_type, param, interval_seconds, shuffle_chunk, sequence, show_next_button)
        return {"action": action, **result}


def reset_plan(tag_id: int) -> None:
    """中止/重置指定标签：删除其计划主表及单词快照。

    显式先删快照、再删主表，不依赖数据库外键级联——即使外键约束未开启，
    也不会残留孤儿快照数据（避免下次建计划时因 plan_id 复用导致 seq 冲突）。
    """
    with session_scope() as session:
        _get_tag(session, tag_id)
        plan = session.exec(
            select(RecitePlan).where(RecitePlan.tag_id == tag_id)
        ).first()
        if plan is None:
            return
        _delete_plan(session, plan)


def advance_sequence(tag_id: int) -> dict:
    """背诵序列无限循环路由：将 current_sequence_index 前进一位（取模回绕）。

    核心公式 (current_sequence_index + 1) % len(sequence_list)，实现 1->2->3->1->2->3
    的无限循环；绝不因序列耗尽而结束计划——「结束本次背诵」完全由用户手动触发。
    返回下一个切片序号及更新后的指针，前端据此加载对应切片并立即开始倒计时。
    """
    with session_scope() as session:
        plan = _get_active_plan(session, tag_id)

        seq = _sequence_of(plan)
        if not seq:
            # 理论不会发生（创建/更新时必生成非空序列），兜底生成默认序列
            seq = list(range(1, plan.total_chunks + 1))

        # 取模递增：指针在 [0, len) 内无限回绕
        idx = (plan.current_sequence_index + 1) % len(seq)
        plan.current_sequence_index = idx
        plan.updated_at = utcnow()

        chunk_index = seq[idx]
        sequence_list = seq
        total_chunks = plan.total_chunks

    return {
        "chunk_index": chunk_index,           # 下一个切片序号（1 起）
        "current_sequence_index": idx,        # 更新后的进行索引
        "sequence_list": sequence_list,       # 当前生效序列（供前端展示）
        "total_chunks": total_chunks,
    }


def get_chunk(tag_id: int, index: int) -> dict:
    """取指定标签第 index 份（1 起）的完整单词详情，供前端一次性批量预加载。

    任意份均可取（自由选份 / 反复重背），不存在「下一份」限制；
    前端调用一次即拿到本份全部词的完整信息（释义/词形时态/形近词等），
    轮播时无需再逐词请求后端。
    """
    with session_scope() as session:
        plan = _get_active_plan(session, tag_id)

        # 份序号越界校验
        if index < 1 or index > plan.total_chunks:
            raise AppError(
                ERR_VALIDATION,
                f"份序号需在 1~{plan.total_chunks} 之间",
                http_status=422,
            )

        # 本份区间 [offset, offset + chunk_size)，按 seq 精确切片（无视删词产生的空洞）
        offset = (index - 1) * plan.chunk_size
        word_ids = session.exec(
            select(RecitePlanWord.word_id)
            .where(
                RecitePlanWord.plan_id == plan.id,
                RecitePlanWord.seq >= offset,
                RecitePlanWord.seq < offset + plan.chunk_size,
            )
            .order_by(RecitePlanWord.seq)
        ).all()

        # 按快照顺序还原词根列表（被删词已级联移除，直接跳过）
        lemmas: list[str] = []
        if word_ids:
            word_map = {
                w.id: w
                for w in session.exec(select(Word).where(Word.id.in_(word_ids))).all()
            }
            lemmas = [word_map[wid].lemma for wid in word_ids if wid in word_map]

        interval_seconds = plan.interval_seconds
        total_chunks = plan.total_chunks

    # 批量生成完整搜索详情（独立会话，不写历史）
    words = batch_details(lemmas) if lemmas else []

    return {
        "chunk_index": index,              # 第几份（1 起）
        "chunk_total": len(words),         # 本份实际词数（可能因删词略少于 chunk_size）
        "total_chunks": total_chunks,
        "interval_seconds": interval_seconds,
        "words": words,                    # 完整详情列表（与搜索结构一致），顺序已固定
    }
