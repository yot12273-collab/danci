# -*- coding: utf-8 -*-
"""
nlp_engine.py —— 英语单词词法分析引擎（NLP 核心）

职责：
1. 合法性校验：判断输入的英文单词是否存在（乱码 / 拼写错误给出明确报错）；
2. 形态追踪：识别变形词（复数、过去式、现在分词等）并还原词根原形，绝不误判为错误；
3. 全形态展示：列出原形的常见时态与词缀变化；
4. 形近词推荐：基于编辑距离推荐拼写相似 / 易混淆的单词；
5. 搜索链接：生成外部词典 / 搜索引擎的跳转地址。

依赖：
- lemminflect  ：词形还原与屈折变化生成（包内自带词表，无需下载）
- pyspellchecker：单词合法性校验与形近词过滤（内置词频词典，无需联网下载）

本模块不依赖 Web 框架与数据库，可独立 import 复用与单元测试。
"""
from __future__ import annotations

from typing import Optional

import lemminflect
from spellchecker import SpellChecker


class InvalidWordError(ValueError):
    """单词非法时抛出，message 为面向用户的友好提示。"""


# ---------- 词性（Universal POS）中文标签 ----------
UPOS_LABELS = {
    "NOUN": "名词",
    "VERB": "动词",
    "ADJ": "形容词",
    "ADV": "副词",
    "AUX": "助动词",
    "PROPN": "专有名词",
    "PRON": "代词",
    "DET": "限定词",
    "ADP": "介词",
    "CCONJ": "连词",
    "SCONJ": "从属连词",
    "PART": "小品词",
    "INTJ": "感叹词",
    "NUM": "数词",
}

# ---------- 屈折形态（Penn Treebank 标签）中文标签 ----------
TAG_LABELS = {
    "VB": "原形",
    "VBD": "过去式",
    "VBG": "现在分词 / 动名词",
    "VBN": "过去分词",
    "VBP": "非第三人称单数现在时",
    "VBZ": "第三人称单数",
    "NN": "单数",
    "NNS": "复数",
    "JJ": "原级",
    "JJR": "比较级",
    "JJS": "最高级",
    "RB": "副词原级",
    "RBR": "副词比较级",
    "RBS": "副词最高级",
}

# 词形变化表展示顺序（值越小越靠前；动词时态在前、复数在后，贴合需求描述）
_TAG_ORDER = {
    "VB": 0, "VBD": 1, "VBN": 2, "VBZ": 3, "VBG": 4, "VBP": 5,
    "NN": 6, "NNS": 7,
    "JJ": 8, "JJR": 9, "JJS": 10,
    "RB": 11, "RBR": 12, "RBS": 13,
}

# 还原词根时按此顺序优先尝试。
# 说明：名词排最前，让“cats/studies”这类以 s 结尾、名词/动词都存在的词默认按“复数”理解；
# 配合“优先还原”逻辑，running/ran 仍正确归到动词。
_UPOS_ORDER = ("NOUN", "VERB", "ADJ", "ADV", "AUX", "PROPN",
               "PRON", "DET", "ADP", "CCONJ", "SCONJ", "PART", "INTJ", "NUM")

# 常见易混淆词对照表（补充“易混淆”需求；仅收录纯字母词，保证可回查）
CONFUSABLES = {
    "affect": ["effect"], "effect": ["affect"],
    "their": ["there"], "there": ["their"],
    "than": ["then"], "then": ["than"],
    "accept": ["except"], "except": ["accept"],
    "advice": ["advise"], "advise": ["advice"],
    "principal": ["principle"], "principle": ["principal"],
    "complement": ["compliment"], "compliment": ["complement"],
    "desert": ["dessert"], "dessert": ["desert"],
    "stationary": ["stationery"], "stationery": ["stationary"],
    "lose": ["loose"], "loose": ["lose"],
    "weather": ["whether"], "whether": ["weather"],
    "quite": ["quiet"], "quiet": ["quite"],
    "aloud": ["allowed"], "allowed": ["aloud"],
}

# 外部词典 / 搜索引擎跳转模板（{word} 为占位符）
SEARCH_ENGINES = [
    {"name": "Bing 必应", "url": "https://www.bing.com/search?q={word}+meaning"},
    {"name": "剑桥词典", "url": "https://dictionary.cambridge.org/search/english/?q={word}"},
    {"name": "韦氏词典", "url": "https://www.merriam-webster.com/dictionary/{word}"},
    {"name": "有道词典", "url": "https://dict.youdao.com/result?word={word}&lang=en"},
    {"name": "Google", "url": "https://www.google.com/search?q={word}+definition"},
]

_ALPHABET = "abcdefghijklmnopqrstuvwxyz"

# ---------- 拼写检查器（单例，复用内置词表） ----------
_spell = SpellChecker(language="en")

# 预热：预先构建编辑距离索引，避免首个请求变慢
try:
    _spell.correction("example")
except Exception:
    pass


def _is_known(word: str) -> bool:
    """判断单词是否存在于词典词表中。"""
    return word in _spell.known([word])


def _freq(word: str) -> float:
    """返回单词词频（浮点概率，用于形近词排序），失败返回 0.0。"""
    try:
        return float(_spell.word_usage_frequency(word))
    except Exception:
        return 0.0


def _edits1(word: str) -> set:
    """生成与 word 编辑距离为 1 的所有候选（删除/换位/替换/插入），参考 Norvig 算法。"""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [L + R[1:] for L, R in splits if R]
    transposes = [L + R[1] + R[0] + R[2:] for L, R in splits if len(R) > 1]
    replaces = [L + c + R[1:] for L, R in splits if R for c in _ALPHABET]
    inserts = [L + c + R for L, R in splits for c in _ALPHABET]
    return set(deletes + transposes + replaces + inserts)


def _pick_lemma(lemma_map: dict, word: str) -> Optional[tuple]:
    """
    从 getAllLemmas 的结果中挑选最可能的 (词根, 词性)。
    策略：优先返回“真正发生还原”的词根（lemma != word）；同类按 _UPOS_ORDER 排序。
    """
    best: Optional[tuple] = None
    for upos in _UPOS_ORDER:
        for v in lemma_map.get(upos, ()):
            v = str(v)
            if v != word:
                return v, upos  # 发生了还原，直接采用
            if best is None:
                best = (v, upos)
    return best


def _pos_label_for(word: str, lemma_map: dict, pos: Optional[str]) -> str:
    """
    计算词性中文标签。原形且一词多性时（如 run 既是名词又是动词），
    如实列出所有词性，避免断言成单一词性造成误导。
    """
    labels: list = []
    for upos in _UPOS_ORDER:
        values = lemma_map.get(upos, ())
        if any(str(v) == word for v in values):
            lbl = UPOS_LABELS.get(upos, upos)
            if lbl not in labels:
                labels.append(lbl)
    if labels:
        return " / ".join(labels)
    return UPOS_LABELS.get(pos or "", "")


def _detect_form(word: str, base: str, upos: Optional[str]) -> Optional[tuple]:
    """
    判断 word 是 base 的哪种屈折形态，返回 (词性, 形态标签)。
    优先在已确定的词性下查找，避免把复数误判为三单等。
    """
    order = [upos] if upos else []
    order += [p for p in ("NOUN", "VERB", "ADJ", "ADV") if p != upos]
    for p in order:
        try:
            inflections = lemminflect.getAllInflections(base, upos=p)
        except Exception:
            continue
        for tag, values in inflections.items():
            if word in {str(v) for v in values}:
                return p, tag
    return None


def _build_forms(base: str) -> list:
    """生成词根的全形态变化表（原形/过去式/过去分词/三单/现在分词/复数等）。"""
    forms: list = []
    seen: set = set()
    for upos in ("VERB", "NOUN", "ADJ", "ADV"):
        try:
            inflections = lemminflect.getAllInflections(base, upos=upos)
        except Exception:
            continue
        for tag, values in inflections.items():
            if not values:
                continue
            value = str(list(values)[0])
            key = (upos, tag)
            if key in seen:
                continue
            seen.add(key)
            forms.append({
                "upos": upos,
                "upos_label": UPOS_LABELS.get(upos, upos),
                "tag": tag,
                "label": TAG_LABELS.get(tag, tag),
                "value": value,
            })
    forms.sort(key=lambda f: _TAG_ORDER.get(f["tag"], 99))
    return forms


def _similar_words(base: str, limit: int = 5) -> list:
    """基于编辑距离 + 常见易混淆表推荐形近词；距离 1 不足时补距离 2。"""
    result: list = []

    # 1) 常见易混淆词优先
    for w in CONFUSABLES.get(base, []):
        if w not in result:
            result.append(w)

    # 2) 编辑距离 1 的候选，过滤真实单词并按词频降序
    candidates = {c for c in _spell.known(_edits1(base)) if c != base}
    for w in sorted(candidates, key=_freq, reverse=True):
        if w not in result:
            result.append(w)
        if len(result) >= limit:
            return result[:limit]

    # 3) 距离 1 不够，补充距离 2（仅当确实需要时，控制计算量）
    edits2: set = set()
    for e in _edits1(base):
        edits2 |= _edits1(e)
    candidates2 = {c for c in _spell.known(edits2) if c != base and c not in result}
    for w in sorted(candidates2, key=_freq, reverse=True):
        if w not in result:
            result.append(w)
        if len(result) >= limit:
            break

    return result[:limit]


def build_links(word: str) -> list:
    """根据目标单词生成外部搜索引擎跳转链接。"""
    return [
        {"name": e["name"], "url": e["url"].format(word=word)}
        for e in SEARCH_ENGINES
    ]


def analyze(raw: str) -> dict:
    """
    核心分析入口：输入原始字符串，返回结构化结果，非法时抛 InvalidWordError。
    """
    word = (raw or "").strip().lower()

    # --- 基础合法性校验 ---
    if not word:
        raise InvalidWordError("请输入一个英文单词")
    if len(word) > 50:
        raise InvalidWordError("单词过长，请检查输入")
    if any(ch.isspace() for ch in word):
        raise InvalidWordError("一次只能查询一个单词，请勿输入空格或短语")
    if not word.isalpha():
        raise InvalidWordError(f"“{word}”包含非法字符，请输入纯英文字母")

    # --- 词形还原 ---
    lemma_map = lemminflect.getAllLemmas(word)
    picked = _pick_lemma(lemma_map, word)

    # --- 合法性校验 + 确定词根 ---
    base: Optional[str] = None
    pos: Optional[str] = None

    if _is_known(word):
        if picked and picked[0] != word and _is_known(picked[0]):
            base, pos = picked[0], picked[1]
        else:
            base = word
            pos = picked[1] if picked else None
    elif picked and _is_known(picked[0]):
        base, pos = picked[0], picked[1]
    else:
        suggestion = _spell.correction(word)
        msg = f"未找到单词 “{word}”"
        if suggestion and suggestion != word:
            msg += f"，你是否想输入 “{suggestion}”？"
        raise InvalidWordError(msg)

    # --- 识别输入的屈折形态 ---
    form_tag: Optional[str] = None
    if base == word:
        form_label = "原形"
    else:
        detected = _detect_form(word, base, pos)
        if detected:
            _, form_tag = detected
            form_label = TAG_LABELS.get(form_tag, form_tag)
        else:
            form_label = "变形"

    # --- 高亮提示文本 ---
    if base == word:
        pos_label = _pos_label_for(word, lemma_map, pos)
        highlight = f"{word} 是原形" + (f"（{pos_label}）" if pos_label else "")
    else:
        pos_label = UPOS_LABELS.get(pos or "", "")
        highlight = f"{word} 是 {base} 的{form_label}"

    return {
        "valid": True,
        "input": word,
        "base": base,
        "pos": pos,
        "pos_label": pos_label,
        "form_tag": form_tag,
        "form_label": form_label,
        "highlight": highlight,
        "forms": _build_forms(base),
        "similar": _similar_words(base),
        "links": build_links(base),
    }
