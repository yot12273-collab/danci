# -*- coding: utf-8 -*-
"""应用配置：路径、上传限制、在线词典密钥等。"""
from __future__ import annotations

import os
from pathlib import Path

# 项目根目录（app 包的上一级，即 vocab-app/）
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

# 确保数据目录存在（SQLite 文件需要父目录）
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    app_name = "英语词汇学习助手"
    version = "1.3.0"

    # 主业务数据库连接串：本地开发不设置（用下方 SQLite 文件）；
    # 部署到 Render 时设置 DATABASE_URL 指向托管 Postgres（Supabase / Neon 等），
    # 数据由此持久化，不再受 Render 临时文件系统清空影响。
    database_url: str = os.getenv("DATABASE_URL", "")

    # 业务数据库（SQLite 本地路径）/ 中文词典数据库路径
    db_path: Path = DATA_DIR / "app.db"
    dict_db_path: Path = DATA_DIR / "dict.sqlite"

    # 静态资源目录
    static_dir: Path = STATIC_DIR

    # docx 上传限制（字节）
    max_upload_size: int = 10 * 1024 * 1024  # 10MB

    # 在线词典（可选兜底）：有道智云密钥，未配置则仅使用本地词典
    youdao_app_key: str = os.getenv("YOUDAO_APP_KEY", "")
    youdao_app_secret: str = os.getenv("YOUDAO_APP_SECRET", "")


settings = Settings()
