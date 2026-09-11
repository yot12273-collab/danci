# -*- coding: utf-8 -*-
"""一次性数据迁移：本地 SQLite data/app.db → 托管 Postgres（Neon）。

原则：
1. 「显式 id + 外键关系」原样搬移，全部归属账号 1；迁移后重置 Postgres 自增序列，
   避免后续插入与显式 id 冲突；
2. 只做「目标库为空 → 追加」的安全迁移：目标表已有数据即中止，绝不重复写入或覆盖；
3. users / sessions 不迁移（账号已由 seed_users 建好且密码正确；会话属临时态，重新登录即可）。

用法（连接串含密码，走环境变量，绝不写入文件/入库）：
    DATABASE_URL="postgresql://user:pass@host/db?sslmode=require" python .ai-skills/migrate_to_neon.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import psycopg2
from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "app.db"

# 迁移顺序按外键依赖：主表 → 从表。列为「源列名」（源/目标同构）。
# users、sessions 不迁移（见文件头说明）。
TABLES: list[tuple[str, list[str]]] = [
    ("tags", ["id", "name", "color", "created_at", "user_id"]),
    ("words", ["id", "lemma", "primary_pos", "phonetic", "translation",
               "short_meaning", "created_at", "updated_at", "user_id"]),
    ("tag_words", ["id", "tag_id", "word_id", "created_at"]),
    ("recite_plans", ["id", "tag_id", "plan_type", "param", "total_words",
                      "chunk_size", "total_chunks", "interval_seconds",
                      "created_at", "updated_at", "shuffle_chunk",
                      "sequence_list", "current_sequence_index", "show_next_button"]),
    ("recite_plan_words", ["id", "plan_id", "seq", "word_id"]),
    ("search_history", ["id", "query", "lemma", "searched_at", "user_id"]),
]

# 布尔列：SQLite 存 0/1 整数，Postgres BOOLEAN 必须传 Python bool，否则类型不匹配报错
_BOOL_COLS = {"recite_plans": {"shuffle_chunk", "show_next_button"}}


def _pg_conn(url: str):
    """从连接串建立 psycopg2 连接（解析 query 中的 sslmode/channel_binding）。"""
    p = urlparse(url)
    q = parse_qs(p.query)
    kwargs = dict(
        host=p.hostname, port=p.port or 5432, dbname=p.path.lstrip("/"),
        user=p.username, password=p.password,
    )
    for k in ("sslmode", "channel_binding"):
        if k in q:
            kwargs[k] = q[k][0]
    return psycopg2.connect(**kwargs)


def _migrate(src: sqlite3.Connection, cur) -> dict[str, int]:
    """按序搬移各表，返回 {表名: 写入行数}。"""
    written: dict[str, int] = {}

    # 预检：SQLite 不强制 VARCHAR 长度，Postgres 会强制；words.primary_pos 上限已从 16 放宽到 64
    cur.execute("ALTER TABLE words ALTER COLUMN primary_pos TYPE VARCHAR(64)")

    for table, cols in TABLES:
        rows = src.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY id").fetchall()
        # 跳过无归属的孤儿历史（user_id 为 NULL，任何账号都不可见，无迁移价值）
        if table == "search_history":
            rows = [r for r in rows if r["user_id"] is not None]
        if not rows:
            written[table] = 0
            print(f"  {table}: 0 行，跳过")
            continue

        bool_cols = _BOOL_COLS.get(table, set())
        values = [
            tuple(bool(r[c]) if c in bool_cols else r[c] for c in cols)
            for r in rows
        ]
        colstr = ",".join(cols)
        # 多行批量插入：execute_values 把 page_size 行合并为单条 INSERT ... VALUES (...),(...)，
        # 把 7000+ 次网络往返压缩到 ~15 次，否则跨洋逐行往返会慢到分钟级
        execute_values(
            cur,
            f"INSERT INTO {table} ({colstr}) VALUES %s",
            values,
            page_size=500,
        )
        written[table] = len(values)
        print(f"  {table}: 写入 {len(values)} 行", flush=True)

    return written


def _reset_sequences(cur) -> None:
    """把各表自增序列推进到当前最大 id，防止未来插入撞主键。"""
    for table in ("tags", "words", "tag_words", "recite_plans",
                  "recite_plan_words", "search_history"):
        cur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}','id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
        )


def _verify(src: sqlite3.Connection, cur, written: dict[str, int]) -> int:
    """迁移后校验：目标行数 == 源行数（不含被跳过的孤儿历史），外键无悬空。"""
    failed = 0

    def check(cond, label, extra=""):
        nonlocal failed
        print(("  PASS  " if cond else "  FAIL  ") + label + (f"  -> {extra}" if extra else ""))
        if not cond:
            failed += 1

    print("\n[校验] 行数比对（源 → 目标）")
    for table, _cols in TABLES:
        src_n = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if table == "search_history":
            src_n = src.execute(
                "SELECT COUNT(*) FROM search_history WHERE user_id IS NOT NULL"
            ).fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        dst_n = cur.fetchone()[0]
        check(dst_n == src_n, f"{table}: {src_n} -> {dst_n}",
              f"expect {src_n}, got {dst_n}")

    print("\n[校验] 外键完整性（目标库无悬空引用）")
    fk_checks = [
        ("tag_words.tag_id -> tags.id",
         "SELECT COUNT(*) FROM tag_words tw LEFT JOIN tags t ON tw.tag_id=t.id WHERE t.id IS NULL"),
        ("tag_words.word_id -> words.id",
         "SELECT COUNT(*) FROM tag_words tw LEFT JOIN words w ON tw.word_id=w.id WHERE w.id IS NULL"),
        ("recite_plans.tag_id -> tags.id",
         "SELECT COUNT(*) FROM recite_plans rp LEFT JOIN tags t ON rp.tag_id=t.id WHERE t.id IS NULL"),
        ("recite_plan_words.plan_id -> recite_plans.id",
         "SELECT COUNT(*) FROM recite_plan_words rpw LEFT JOIN recite_plans rp ON rpw.plan_id=rp.id WHERE rp.id IS NULL"),
        ("recite_plan_words.word_id -> words.id",
         "SELECT COUNT(*) FROM recite_plan_words rpw LEFT JOIN words w ON rpw.word_id=w.id WHERE w.id IS NULL"),
    ]
    for label, sql in fk_checks:
        cur.execute(sql)
        n = cur.fetchone()[0]
        check(n == 0, label, f"{n} 条悬空")

    return failed


def main() -> int:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("错误：未设置 DATABASE_URL 环境变量")
        return 1
    if not SRC.exists():
        print(f"错误：源库不存在 {SRC}")
        return 1

    src = sqlite3.connect(str(SRC))
    src.row_factory = sqlite3.Row
    pg = _pg_conn(url)
    cur = pg.cursor()

    try:
        # 安全检查：目标表必须为空，杜绝重复迁移 / 覆盖
        for table, _cols in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            n = cur.fetchone()[0]
            if n > 0:
                print(f"中止：目标表 {table} 已有 {n} 行，拒绝重复迁移（需先清空目标库）")
                return 1

        written = _migrate(src, cur)
        _reset_sequences(cur)
        pg.commit()
        print("\n迁移已提交 [成功]")
    except Exception as e:
        pg.rollback()
        print("\n迁移失败，已整体回滚 [失败]")
        print(f"  {type(e).__name__}: {str(e)[:400]}")
        return 1
    finally:
        cur.close()
        pg.close()
        src.close()

    # 校验（独立连接，只读）
    src2 = sqlite3.connect(str(SRC))
    src2.row_factory = sqlite3.Row
    pg2 = _pg_conn(url)
    cur2 = pg2.cursor()
    failed = _verify(src2, cur2, written)
    cur2.close()
    pg2.close()
    src2.close()

    print(f"\n结果：{'全部校验通过' if failed == 0 else f'{failed} 项校验失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
