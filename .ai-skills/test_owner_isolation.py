# -*- coding: utf-8 -*-
"""
数据隔离迁移自检（.ai-skills/test_owner_isolation.py）

在「真实 app.db 的副本」上跑真实迁移逻辑（database.init_db），验证：
1. tags / words 补出 user_id 列，存量行全部归属账号「1」；
2. 旧全局唯一索引 ix_tags_name / ix_words_lemma 被移除，换为复合唯一 uq_tag_user_name / uq_word_user_lemma；
3. 依赖表（tag_words / recite_plans / recite_plan_words）数据零丢失；
4. 迁移幂等：重复执行不报错、不改动数据。

用法：python .ai-skills/test_owner_isolation.py   （退出码 0 = 全通过）
绝不触碰 data/app.db 本体，只读副本。
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

# 保证从任意目录运行时都能 import app（项目根加入 sys.path）
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine

import app.database as database
from app.config import settings


def _schema_snapshot(con: sqlite3.Connection) -> dict:
    """采集 tags / words 的列、索引与行数，供前后比对。"""
    def cols(t):
        return [r[1] for r in con.execute(f"PRAGMA table_info({t})").fetchall()]

    def indexes(t):
        return {
            r[0]: (r[1] or "")
            for r in con.execute(
                f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='{t}'"
            ).fetchall()
        }

    def count(t):
        return con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]

    return {
        "tags_cols": cols("tags"),
        "words_cols": cols("words"),
        "tags_idx": indexes("tags"),
        "words_idx": indexes("words"),
        "counts": {t: count(t) for t in
                   ["tags", "words", "tag_words", "recite_plans", "recite_plan_words"]},
    }


def main() -> int:
    src = Path(settings.db_path)
    if not src.exists():
        print("SKIP：data/app.db 不存在，无法迁移自检")
        return 0

    failed = 0
    def ok(cond, label, extra=None):
        nonlocal failed
        if cond:
            print("  PASS  " + label)
        else:
            failed += 1
            print("  FAIL  " + label + (f"  -> {extra}" if extra is not None else ""))

    with tempfile.TemporaryDirectory() as td:
        dst = Path(td) / "migrate_test.db"
        shutil.copy2(src, dst)

        # 记录迁移前快照（依赖表行数、旧唯一索引是否在）
        before_con = sqlite3.connect(dst)
        before = _schema_snapshot(before_con)
        before_con.close()

        # 把 database.engine 重定向到副本，跑真实 init_db（含全部迁移 + create_all）
        saved_engine = database.engine
        temp_engine = create_engine(f"sqlite:///{dst.as_posix()}")
        database.engine = temp_engine
        try:
            database.init_db()
            database.init_db()  # 幂等性：再跑一次
        finally:
            database.engine = saved_engine
            temp_engine.dispose()  # 释放连接池，否则 Windows 下无法删除临时文件

        con = sqlite3.connect(dst)
        after = _schema_snapshot(con)

        # 1. user_id 列已补
        ok("user_id" in after["tags_cols"], "tags 补出 user_id 列", after["tags_cols"])
        ok("user_id" in after["words_cols"], "words 补出 user_id 列", after["words_cols"])

        # 2. 存量数据全部归属账号「1」
        if "user_id" in after["tags_cols"]:
            non_one = con.execute(
                "SELECT COUNT(*) FROM tags WHERE user_id IS NULL OR user_id != (SELECT id FROM users WHERE username='1')"
            ).fetchone()[0]
            ok(non_one == 0, "tags 存量行全部归属账号 1", f"异常 {non_one} 行")
        if "user_id" in after["words_cols"]:
            non_one = con.execute(
                "SELECT COUNT(*) FROM words WHERE user_id IS NULL OR user_id != (SELECT id FROM users WHERE username='1')"
            ).fetchone()[0]
            ok(non_one == 0, "words 存量行全部归属账号 1", f"异常 {non_one} 行")

        # 3. 旧全局唯一索引移除、复合唯一索引就位
        ok("ix_tags_name" not in after["tags_idx"], "旧全局唯一 ix_tags_name 已移除")
        ok("ix_words_lemma" not in after["words_idx"], "旧全局唯一 ix_words_lemma 已移除")
        ok("uq_tag_user_name" in after["tags_idx"], "复合唯一 uq_tag_user_name 已建")
        ok("uq_word_user_lemma" in after["words_idx"], "复合唯一 uq_word_user_lemma 已建")

        # 4. 依赖表数据零丢失
        for t in ["tags", "words", "tag_words", "recite_plans", "recite_plan_words"]:
            ok(after["counts"][t] == before["counts"][t],
               f"{t} 行数不变", f"{before['counts'][t]} -> {after['counts'][t]}")

        # 5. 复合唯一索引确实生效：同一账号插入重名词根应被拒
        try:
            uid = con.execute("SELECT id FROM users WHERE username='1'").fetchone()[0]
            con.execute("INSERT INTO tags (name, user_id, created_at) VALUES ('__dup_probe__', ?, datetime('now'))", (uid,))
            con.execute("INSERT INTO tags (name, user_id, created_at) VALUES ('__dup_probe__', ?, datetime('now'))", (uid,))
            con.commit()
            ok(False, "复合唯一约束生效（同账号重名被拒）", "未触发约束")
        except sqlite3.IntegrityError:
            con.rollback()
            ok(True, "复合唯一约束生效（同账号重名被拒）")

        con.close()

    print(f"\nRESULT: {'全通过' if failed == 0 else f'{failed} 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
