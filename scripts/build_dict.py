# -*- coding: utf-8 -*-
"""
build_dict.py —— 将 ECDICT 的 StarDict 词典裁剪为轻量 SQLite 中文词典。

用法：
    python scripts/build_dict.py <stardict目录> [输出db路径]

示例（先解压 ecdict-stardict-28.zip）：
    python scripts/build_dict.py tmp/stardict-ecdict-2.4.2 data/dict.sqlite

输出表结构：
    entries(word TEXT PRIMARY KEY, phonetic TEXT, definition TEXT)
"""
from __future__ import annotations

import re
import sqlite3
import struct
import sys
from pathlib import Path

# 只保留单个纯英文单词（过滤短语、含空格/重音字符的地名等）
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z']*$")
PHONETIC_RE = re.compile(r"^\*\[(.*?)\]")

_BATCH = 10000


def parse_idx(idx_bytes: bytes):
    """解析 StarDict .idx：word\0 + 32 位大端 offset + 32 位大端 size。"""
    i, n = 0, len(idx_bytes)
    while i < n:
        j = idx_bytes.index(b"\x00", i)
        word = idx_bytes[i:j].decode("utf-8", "ignore")
        off, sz = struct.unpack(">II", idx_bytes[j + 1:j + 9])
        yield word, off, sz
        i = j + 9


def build(idx_path: Path, dict_path: Path, out_path: Path) -> None:
    idx = idx_path.read_bytes()
    dct = dict_path.read_bytes()

    conn = sqlite3.connect(str(out_path))
    conn.execute("DROP TABLE IF EXISTS entries")
    conn.execute(
        "CREATE TABLE entries (word TEXT PRIMARY KEY, phonetic TEXT, definition TEXT)"
    )

    rows: list = []
    total = kept = 0
    for word, off, sz in parse_idx(idx):
        total += 1
        if not WORD_RE.match(word):
            continue
        blob = dct[off:off + sz].decode("utf-8", "ignore")
        lines = blob.split("\n")
        phonetic = None
        if lines and lines[0].lstrip().startswith("*["):
            m = PHONETIC_RE.match(lines[0].strip())
            phonetic = m.group(1) if m else lines[0].strip()
            lines = lines[1:]
        definition = "\n".join(l.strip() for l in lines if l.strip())
        if not definition:
            continue
        rows.append((word, phonetic, definition))
        kept += 1
        if len(rows) >= _BATCH:
            conn.executemany("INSERT OR IGNORE INTO entries VALUES (?,?,?)", rows)
            rows = []
            print(f"  已扫描 {total} 条，保留 {kept} 条 ...")

    if rows:
        conn.executemany("INSERT OR IGNORE INTO entries VALUES (?,?,?)", rows)

    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    print(f"完成：共扫描 {total} 条，保留 {kept} 条 -> {out_path}")


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "tmp/stardict-ecdict-2.4.2")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "data/dict.sqlite")
    # 用 glob 定位实际文件名，避免 .stem 把 "2.4.2" 截成 "2.4"
    idx_path = next(src.glob("*.idx"))
    dict_path = next(src.glob("*.dict"))
    build(idx_path, dict_path, out)
