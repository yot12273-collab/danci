# -*- coding: utf-8 -*-
"""数据库引擎与会话管理（SQLModel / SQLAlchemy 2.0 + SQLite）。"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event, inspect
from sqlmodel import Session, SQLModel, create_engine

from .config import settings

# SQLite 单文件；check_same_thread=False 允许在线程池中复用连接
engine = create_engine(
    # 用 as_posix() 保证 Windows 路径的斜杠方向正确，SQLAlchemy 才能正确解析
    f"sqlite:///{settings.db_path.as_posix()}",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    """每个连接开启外键约束与 WAL 日志，保证级联删除与并发读写。"""
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def _migrate_recite_tables() -> None:
    """轻量迁移：背诵模型历经多代结构，需按列结构识别并重建/补列。

    - 旧 v1「全局背诵」：recite_plans 无 tag_id 列（含 done_chunks/status）；
    - v2「按标签」：含 tag_id，但仍有 done_chunks/status 进度列；
    - v3「自由选份」：移除 done_chunks/status，仅保留分组结构；
    - v4「自由选份 + 行为参数」：在 v3 基础上新增 shuffle_chunk 列（切片内打乱开关）；
    - v5「自由选份 + 背诵序列」：在 v4 基础上新增 sequence_list / current_sequence_index 两列；
    - v6「自由选份 + 按钮显隐」：在 v5 基础上新增 show_next_button 列（背诵期间是否显示「下一个」）。

    规则：
    1. 检测到旧进度列（done_chunks / status）时删除背诵两张表，交由 create_all 按最新结构重建；
    2. v3 缺 shuffle_chunk 列时，用 ALTER TABLE 就地补列（默认 0），保留既有计划与分组；
    3. v4 缺背诵序列列时，用 ALTER TABLE 就地补列（sequence_list 默认空串、指针默认 0）；
    4. v5 缺按钮显隐列时，用 ALTER TABLE 就地补列（show_next_button 默认 1）；
    5. 已是 v6 结构或表不存在时直接返回，幂等、无副作用。
    """
    insp = inspect(engine)
    if "recite_plans" not in insp.get_table_names():
        return  # 表不存在，create_all 会直接新建

    cols = {c["name"] for c in insp.get_columns("recite_plans")}

    # 旧进度列仍存在（v1 / v2）→ 删表重建
    if "done_chunks" in cols or "status" in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP TABLE IF EXISTS recite_plan_words")
            conn.exec_driver_sql("DROP TABLE IF EXISTS recite_plans")
        return

    # v3 缺新增的行为参数列 → 就地补列，避免丢失既有分组
    if "shuffle_chunk" not in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE recite_plans ADD COLUMN shuffle_chunk BOOLEAN NOT NULL DEFAULT 0"
            )

    # v4 缺背诵序列两列 → 就地补列，保留既有计划（序列留空由服务层降级为默认 [1..N]）
    if "sequence_list" not in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE recite_plans ADD COLUMN sequence_list TEXT NOT NULL DEFAULT ''"
            )
    if "current_sequence_index" not in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE recite_plans ADD COLUMN current_sequence_index INTEGER NOT NULL DEFAULT 0"
            )

    # v5 缺「显示下一个按钮」列 → 就地补列（默认 1=显示）
    if "show_next_button" not in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE recite_plans ADD COLUMN show_next_button BOOLEAN NOT NULL DEFAULT 1"
            )


def init_db() -> None:
    """建表（幂等）。需先导入 models 以注册所有表模型。"""
    from . import models  # noqa: F401  确保模型已注册到 metadata

    _migrate_recite_tables()
    SQLModel.metadata.create_all(engine)


@contextmanager
def session_scope():
    """会话上下文管理器：业务层统一使用，正常提交、异常回滚，并关闭会话。"""
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
