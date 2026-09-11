# -*- coding: utf-8 -*-
"""
quiz_service.py —— 闪卡抽查服务（互动式测试 + 自动纠错）

从指定标签取词，生成双向测试卡片序列：
- 首轮 Fisher–Yates 洗牌（每词恰好出现一次、顺序彻底随机）
- 循环补足 target 时采用「冷却窗口」防重：同一词两次出现之间至少间隔
  标签总单词量 30% 的其他单词（gap = int(n * 0.30)）
- 中译英（zh2en）：生成拼写填空槽位 slots（长度 + 约 20% 提示字母）
- 英译中（en2zh）：生成 4 选项（1 正确 + 3 干扰，语义去重）与 answer_index
"""
from __future__ import annotations

import random
from collections import deque

from sqlmodel import select

from ..database import session_scope
from ..models import Tag, TagWord, Word
from ..schemas.common import AppError, ERR_NOT_FOUND, ERR_VALIDATION
from .dictionary import dictionary

MODE_EN2ZH = "en2zh"
MODE_ZH2EN = "zh2en"
MODE_MIX = "mix"
N_OPTIONS = 4  # 选择题选项数（1 正确 + 3 干扰）


def _pick_direction(mode: str) -> str:
    """依模式决定出题方向；mix 时逐卡随机。"""
    if mode == MODE_MIX:
        return random.choice((MODE_EN2ZH, MODE_ZH2EN))
    return mode


def _build_slots(word: str) -> list[str]:
    """生成拼写填空槽位：长度=单词长度，提示字母/连字符锁定，其余待填。

    仅字母位参与遮挡；非字母（连字符 `-`、撇号 `'`）原样保留且锁定。
    """
    alpha = [i for i, c in enumerate(word) if c.isalpha()]
    k = max(1, round(len(alpha) * 0.20)) if alpha else 0
    shown = set(random.sample(alpha, k))
    slots: list[str] = []
    for i, c in enumerate(word):
        if not c.isalpha():      # 连字符 / 撇号：原样锁定
            slots.append(c)
        elif i in shown:         # 提示字母：锁定
            slots.append(c)
        else:                    # 待填位
            slots.append("")
    return slots


def _meaning_body(m: str) -> str:
    """剥离词性前缀（如 "n. "），只留中文释义主体，用于语义去重。"""
    return m.split(" ", 1)[1] if " " in m else m


def _build_options(words: list[Word], correct: Word,
                   global_meanings: list[str]) -> tuple[list[str], int]:
    """生成英译中选项：1 正确 + 3 干扰，语义去重，打乱后返回 (options, answer_index)。

    干扰项来源优先级：标签库其他单词 → 全局词库 → 系统词典兜底。
    """
    correct_text = correct.short_meaning or "（暂无释义）"
    seen = {_meaning_body(correct_text)}
    distractors: list[str] = []

    def add(candidates) -> None:
        for m in candidates:
            if len(distractors) >= N_OPTIONS - 1:
                return
            if not m:
                continue
            b = _meaning_body(m)
            if b in seen:        # 语义重复 / 近义 → 跳过
                continue
            seen.add(b)
            distractors.append(m)

    # ① 标签内其他单词
    tag_pool = [w.short_meaning for w in words
                if w.id != correct.id and w.short_meaning]
    random.shuffle(tag_pool)
    add(tag_pool)

    # ② 全局词库兜底
    if len(distractors) < N_OPTIONS - 1:
        gpool = list(global_meanings)
        random.shuffle(gpool)
        add(gpool)

    # ③ 系统词典兜底
    while len(distractors) < N_OPTIONS - 1:
        fb = dictionary.random_short_meaning(seen)
        if fb is None:
            break
        seen.add(_meaning_body(fb))
        distractors.append(fb)

    options = [correct_text] + distractors[:N_OPTIONS - 1]
    random.shuffle(options)  # Fisher–Yates 打乱选项
    return options, options.index(correct_text)


def _make_card(w: Word, mode: str, words: list[Word],
               global_meanings: list[str]) -> dict:
    """按题型组装卡片：zh2en 填 slots，en2zh 填 options + answer_index。"""
    direction = _pick_direction(mode)
    card = {
        "word_id": w.id,
        "lemma": w.lemma,
        "phonetic": w.phonetic,
        "primary_pos": w.primary_pos,
        "short_meaning": w.short_meaning,
        "direction": direction,
    }
    if direction == MODE_ZH2EN:
        card["slots"] = _build_slots(w.lemma)
        card["options"] = None
        card["answer_index"] = None
    else:
        card["options"], card["answer_index"] = _build_options(words, w, global_meanings)
        card["slots"] = None
    return card


def _generate_cards(words: list[Word], target: int, mode: str,
                    global_meanings: list[str]) -> list[dict]:
    """生成 target 张卡片序列：首轮洗牌 + 冷却窗口 30% 间隔防重。"""
    n = len(words)
    gap = int(n * 0.30)  # 30% 防重间隔（向下取整；如 400 → 120）

    if gap == 0:
        # 单词太少（<4 个），30% 不足 1，退化为无间隔随机
        seq = [random.choice(words) for _ in range(target)]
    else:
        # ① 首轮 Fisher–Yates 洗牌：保证每词恰好出现一次且顺序彻底随机
        order = words[:]
        for i in range(n - 1, 0, -1):
            j = random.randrange(i + 1)
            order[i], order[j] = order[j], order[i]
        seq = list(order)

        # ② 冷却窗口循环补足 target：候选 = 全集 − 最近 gap 个已抽词
        recent = deque(w.id for w in order[-gap:])  # 用首轮末尾 gap 个词初始化窗口
        while len(seq) < target:
            pool = [w for w in words if w.id not in recent]  # 候选 = 全集 − 冷却窗口
            w = random.choice(pool if pool else words)        # 兜底防池空
            seq.append(w)
            recent.append(w.id)
            if len(recent) > gap:                             # 窗口长度保持 ≤ gap
                recent.popleft()

    return [_make_card(w, mode, words, global_meanings) for w in seq[:target]]


def start_quiz(tag_id: int, target: int | None, mode: str, user_id: int) -> dict:
    """发起一场抽查：取标签下所有单词，生成完整题目序列（无状态、不落库）。"""
    with session_scope() as session:
        # 标签须归属当前账号；不存在（含他人标签）统一 404
        tag = session.exec(
            select(Tag).where(Tag.id == tag_id, Tag.user_id == user_id)
        ).first()
        if tag is None:
            raise AppError(ERR_NOT_FOUND, "标签不存在", http_status=404)
        tag_name = tag.name  # 会话内先读取，避免 commit 后属性过期无法访问

        words = session.exec(
            select(Word)
            .join(TagWord)
            .where(TagWord.tag_id == tag_id, Word.user_id == user_id)
            .order_by(Word.lemma)
        ).all()
        if not words:
            raise AppError(ERR_VALIDATION, "该标签下暂无单词，无法测试", http_status=422)

        # 当前账号词库释义池（en2zh 干扰项兜底用，绝不泄露他人单词释义）
        global_meanings = session.exec(
            select(Word.short_meaning).where(
                Word.short_meaning.is_not(None), Word.user_id == user_id
            )
        ).all()

        n = len(words)
        if target is None:
            target = n  # 未指定题数：默认抽查一遍（与单词数相等）
        if target < 1:
            raise AppError(ERR_VALIDATION, "目标题数至少为 1", http_status=422)

        cards = _generate_cards(words, target, mode, global_meanings)

    return {
        "tag_id": tag_id,
        "tag_name": tag_name,
        "word_count": n,
        "total": len(cards),
        "mode": mode,
        "cards": cards,
    }
