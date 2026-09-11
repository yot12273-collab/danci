# -*- coding: utf-8 -*-
"""
服务层隔离功能自检（.ai-skills/test_owner_isolation_func.py）

在「已迁移的 app.db 副本」上直接调用服务层，验证按账号隔离的读写路径：
1. 账号 1 能看到存量数据，账号 2 看到空；
2. 账号 2 建同名标签 / 导入同词根不冲突（各归各）；
3. 越权访问他人标签 / 单词一律 404。

用法：python .ai-skills/test_owner_isolation_func.py   （退出码 0 = 全通过）
只读写临时副本，绝不触碰 data/app.db 本体。
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine

import app.database as database
from app.config import settings
from app.schemas.common import AppError
from app.services import tag_service, word_service


def main() -> int:
    src = Path(settings.db_path)
    if not src.exists():
        print("SKIP：data/app.db 不存在")
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
        dst = Path(td) / "func_test.db"
        shutil.copy2(src, dst)

        saved_engine = database.engine
        temp_engine = create_engine(f"sqlite:///{dst.as_posix()}")
        database.engine = temp_engine
        try:
            # ---- 1. 列表隔离 ----
            tags1 = tag_service.list_tags(1)
            tags2 = tag_service.list_tags(2)
            ok(len(tags1) >= 1, "账号 1 能看到存量标签", len(tags1))
            ok(len(tags2) == 0, "账号 2 标签为空", len(tags2))

            w1 = word_service.list_words(1, 10, None, None, 1)
            w2 = word_service.list_words(1, 10, None, None, 2)
            ok(w1["total"] >= 1, "账号 1 能看到存量单词", w1["total"])
            ok(w2["total"] == 0, "账号 2 单词为空", w2["total"])

            # ---- 2. 同名标签 / 同词根不冲突 ----
            name1 = tags1[0]["name"]
            new_tag2 = tag_service.create_tag(name1, None, 2)
            ok(new_tag2["id"] != tags1[0]["id"], "账号 2 建同名标签成功（各归各）")
            ok(len(tag_service.list_tags(2)) == 1, "账号 2 现有 1 个标签")

            lemma1 = word_service.list_words(1, 1, None, None, 1)["items"][0]["lemma"]
            before2_total = word_service.list_words(1, 5, None, None, 2)["total"]
            add2 = word_service.add_word(lemma1, [], 2)
            ok(add2["id"] is not None, "账号 2 导入同词根成功")
            after2_total = word_service.list_words(1, 5, None, None, 2)["total"]
            ok(after2_total == before2_total + 1, "账号 2 单词独立新增，不并入账号 1", f"{before2_total}->{after2_total}")

            # ---- 3. 越权访问一律 404 ----
            tag1_id = tags1[0]["id"]
            word1_id = word_service.list_words(1, 1, None, None, 1)["items"][0]["id"]
            for fn, label in [
                (lambda: tag_service.list_tag_words(tag1_id, 2), "账号 2 看账号 1 标签词列表"),
                (lambda: tag_service.delete_tag(tag1_id, 2), "账号 2 删账号 1 标签"),
                (lambda: word_service.delete_word(word1_id, 2), "账号 2 删账号 1 单词"),
                (lambda: word_service.set_word_tags(word1_id, [], 2), "账号 2 改账号 1 单词标签"),
            ]:
                try:
                    fn()
                    ok(False, label + " -> 404", "未抛异常")
                except AppError as e:
                    ok(e.http_status == 404, label + " -> 404", e.http_status)

            # ---- 4. 账号 2 把词挂到账号 1 的标签应被拒 ----
            try:
                word_service.add_word("test", [tag1_id], 2)
                ok(False, "账号 2 挂词到账号 1 标签 -> 404", "未抛异常")
            except AppError as e:
                ok(e.http_status == 404, "账号 2 挂词到账号 1 标签 -> 404", e.http_status)
        finally:
            database.engine = saved_engine
            temp_engine.dispose()

    print(f"\nRESULT: {'全通过' if failed == 0 else f'{failed} 项失败'}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
