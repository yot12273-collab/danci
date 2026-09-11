# -*- coding: utf-8 -*-
"""数据库引擎与会话管理（SQLModel / SQLAlchemy 2.0 + SQLite）。"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import event, inspect
from sqlmodel import Session, SQLModel, create_engine

from .config import settings


def _normalize_db_url(url: str) -> str:
    """补全 Postgres 驱动后缀：Supabase / Neon 通常给 postgresql:// 或 postgres://，
    SQLAlchemy 需要显式驱动（+psycopg2），此处统一改写，避免「无法确定 DBAPI」报错。"""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://"):]
    return url


# 数据库方言：设置了 DATABASE_URL 走托管 Postgres（Render 持久化），否则本地 SQLite（开发）。
# 托管 Postgres 每次部署为全新库，由 create_all 按最新模型直接建表，无需就地迁移。
_IS_POSTGRES = bool(settings.database_url)

if _IS_POSTGRES:
    # 托管 Postgres：外键约束默认强制；pool_pre_ping 规避空闲断连（Supabase/Neon 会回收空闲连接）
    engine = create_engine(_normalize_db_url(settings.database_url), pool_pre_ping=True)
else:
    # SQLite 单文件；check_same_thread=False 允许在线程池中复用连接
    engine = create_engine(
        # 用 as_posix() 保证 Windows 路径的斜杠方向正确，SQLAlchemy 才能正确解析
        f"sqlite:///{settings.db_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _record):
        """每个连接开启外键约束与 WAL 日志（SQLite 专属；Postgres 无需且不支持 PRAGMA）。"""
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


def _migrate_search_history_table() -> None:
    """给已存在的 search_history 表补 user_id 列。

    create_all 不会对旧库的既有表补列，而 data/app.db 是已存在库，故需
    ALTER TABLE 就地补列。规则：表不存在则交由 create_all 建最新结构；表存在但
    缺 user_id 列时补一列可空 INTEGER（旧历史归为无主数据，不被任何账号看到）。
    """
    insp = inspect(engine)
    if "search_history" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("search_history")}
    if "user_id" not in cols:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE search_history ADD COLUMN user_id INTEGER"
            )


# 存量数据（迁移前无 user_id 的标签 / 单词 / 分组）统一归属的账号用户名。
# 与用户确认：现有 3 标签 / 3469 词 / 1 份背诵分组全部划给账号「1」。
LEGACY_OWNER_USERNAME = "1"


def _legacy_owner_id(conn) -> int:
    """解析存量数据归属账号的用户 id；账号「1」不存在时回退 id=1（由 seed_users 兜底创建）。"""
    row = conn.exec_driver_sql(
        f"SELECT id FROM users WHERE username = '{LEGACY_OWNER_USERNAME}' LIMIT 1"
    ).fetchone()
    return int(row[0]) if row else 1


def _migrate_owner_tables() -> None:
    """给 tags / words 表补 user_id 列，把「全局唯一」改造为「按账号隔离」。

    旧版 tags / words 无归属字段，name / lemma 全局唯一（所有账号共用一套数据）。
    改造需两步：
    1. 补可空 user_id 列，并把存量行统一归属账号「1」（LEGACY_OWNER_USERNAME）；
    2. 删除 name / lemma 的全局唯一索引，改为 (user_id, name) / (user_id, lemma) 复合唯一，
       否则 A 账号已建「英语」标签会挡住 B 账号再建同名标签。

    SQLite 无法就地改唯一约束，这里用「加列 + 删旧唯一索引 + 建复合唯一索引」三步完成，
    不重建表、不动主键与外键引用，最稳妥；幂等（已含 user_id 列时直接跳过）。
    """
    insp = inspect(engine)
    table_names = set(insp.get_table_names())
    # 两张表都不存在（全新库）→ 交由 create_all 按最新模型建表，无需迁移
    if "tags" not in table_names and "words" not in table_names:
        return

    with engine.begin() as conn:
        owner = _legacy_owner_id(conn)

        if "tags" in table_names:
            cols = {c["name"] for c in insp.get_columns("tags")}
            if "user_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE tags ADD COLUMN user_id INTEGER")
                conn.exec_driver_sql("DROP INDEX IF EXISTS ix_tags_name")
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_tag_user_name ON tags(user_id, name)"
                )
                conn.exec_driver_sql(f"UPDATE tags SET user_id = {owner}")

        if "words" in table_names:
            cols = {c["name"] for c in insp.get_columns("words")}
            if "user_id" not in cols:
                conn.exec_driver_sql("ALTER TABLE words ADD COLUMN user_id INTEGER")
                conn.exec_driver_sql("DROP INDEX IF EXISTS ix_words_lemma")
                conn.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_word_user_lemma ON words(user_id, lemma)"
                )
                conn.exec_driver_sql(f"UPDATE words SET user_id = {owner}")


def init_db() -> None:
    """建表（幂等）。需先导入 models 以注册所有表模型。"""
    from . import models  # noqa: F401  确保模型已注册到 metadata

    # SQLite 旧库需就地迁移（加列 / 换唯一索引）；托管 Postgres 为全新库，直接建表即可
    if not _IS_POSTGRES:
        _migrate_search_history_table()
        _migrate_recite_tables()
        _migrate_owner_tables()
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
