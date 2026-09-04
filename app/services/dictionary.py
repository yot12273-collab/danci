# -*- coding: utf-8 -*-
"""
dictionary.py —— 中文释义服务

主路径：本地 SQLite 词典（由 scripts/build_dict.py 从 ECDICT 裁剪生成），离线、稳定、零延迟。
注：config.py 已预留有道智云密钥配置（YOUDAO_APP_KEY/SECRET），如需在线兜底，
    可在 lookup 未命中时接入在线翻译（当前仅本地词典，稳定优先）。

降级矩阵：
- 词典库不存在  -> available=False，lookup 返回 None（前端显示“暂无中文释义”）
- 词条未命中    -> 尝试首字母大写（专有名词），仍未命中返回 None
"""
from __future__ import annotations

import random
import re
import sqlite3
import threading
from pathlib import Path

from ..config import settings

# ECDICT 词性缩写 → 中文
POS_CN = {
    "n.": "名词", "na.": "名词", "n": "名词",
    "v.": "动词", "vt.": "及物动词", "vi.": "不及物动词",
    "a.": "形容词", "adj.": "形容词", "ad.": "副词", "adv.": "副词",
    "prep.": "介词", "conj.": "连词", "pron.": "代词",
    "num.": "数词", "art.": "冠词", "int.": "感叹词", "interj.": "感叹词",
    "aux.": "助动词", "abbr.": "缩写", "det.": "限定词",
}

_POS_RE = re.compile(r"^([A-Za-z]+\.)\s*(.*)$")
_CAT_RE = re.compile(r"^(\[[^\]]+\])\s*(.*)$")


class DictionaryService:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        # 每个线程独立连接，避免 SQLite 连接跨线程使用报错
        self._local = threading.local()

    @property
    def available(self) -> bool:
        """本地词典是否已构建。"""
        return self.db_path.exists()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path))
            self._local.conn = conn
        return conn

    def _parse_definition(self, definition: str) -> list[dict]:
        """把 ECDICT 的 definition 文本（每行“词性. 释义”）解析为结构化条目。"""
        entries: list[dict] = []
        for line in definition.split("\n"):
            line = line.strip()
            if not line:
                continue
            m = _POS_RE.match(line)
            if m:
                pos, meaning = m.group(1), m.group(2).strip()
                if meaning:
                    entries.append({
                        "pos": pos,
                        "pos_label": POS_CN.get(pos.lower(), pos),
                        "meaning": meaning,
                    })
                continue
            m = _CAT_RE.match(line)
            if m:
                cat, meaning = m.group(1), m.group(2).strip()
                if meaning:
                    entries.append({"pos": cat, "pos_label": cat, "meaning": meaning})
        return entries

    def lookup(self, lemma: str) -> dict | None:
        """
        查询单词的中文释义。命中返回
        {"phonetic": str, "translations": [...], "short_meaning": str}；未命中返回 None。
        """
        if not self.available:
            return None
        try:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT phonetic, definition FROM entries WHERE word=?", (lemma,)
            ).fetchone()
            # 专有名词兜底：尝试首字母大写
            if row is None and lemma and lemma.islower():
                row = conn.execute(
                    "SELECT phonetic, definition FROM entries WHERE word=?",
                    (lemma.capitalize(),),
                ).fetchone()
        except Exception:
            return None

        if row is None:
            return None

        entries = self._parse_definition(row[1])
        if not entries:
            return None

        # 清理音标：ECDICT 音标行为 "*[音标]   -K5"，去掉 "*[" 前缀与词频后缀
        phonetic = row[0]
        if phonetic:
            m = re.match(r"^\*\[(.*?)\]", phonetic)
            if m:
                phonetic = m.group(1)

        # 简短释义：取首个词性条目，过长则截断，保证列表展示整洁
        short = entries[0]
        meaning = short["meaning"]
        if len(meaning) > 60:
            meaning = meaning[:60] + "…"
        short_meaning = f"{short['pos']} {meaning}" if short.get("pos") else meaning
        return {
            "phonetic": phonetic,
            "translations": entries,
            "short_meaning": short_meaning,
        }

    def random_short_meaning(self, exclude_bodies: set[str] | None = None) -> str | None:
        """随机取一条中文释义（选择题干扰项兜底），避开语义重复集合。

        通过随机 OFFSET 定位词条，避免 ORDER BY RANDOM() 对百万行表全量排序。
        """
        if not self.available:
            return None
        try:
            conn = self._get_conn()
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            if not total:
                return None
            for _ in range(30):  # 最多尝试 30 次，避开无释义 / 重复词条
                off = random.randint(0, total - 1)
                row = conn.execute(
                    "SELECT word, definition FROM entries LIMIT 1 OFFSET ?", (off,)
                ).fetchone()
                if row is None:
                    continue
                entries = self._parse_definition(row[1])
                if not entries:
                    continue
                short = entries[0]
                meaning = short["meaning"]
                if len(meaning) > 60:
                    meaning = meaning[:60] + "…"
                sm = f"{short['pos']} {meaning}" if short.get("pos") else meaning
                body = sm.split(" ", 1)[1] if " " in sm else sm
                if exclude_bodies and body in exclude_bodies:
                    continue
                return sm
        except Exception:
            return None
        return None


# 全局单例
dictionary = DictionaryService(settings.dict_db_path)
