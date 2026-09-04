# -*- coding: utf-8 -*-
"""账号认证服务：密码哈希、登录/登出、预置账号。"""
from __future__ import annotations

import hashlib
import secrets

from sqlmodel import select

from ..database import session_scope
from ..models import Session, User
from ..schemas.common import AppError, ERR_AUTH_FAILED

# PBKDF2 迭代次数（标准库实现，无需新增依赖）
_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """PBKDF2-SHA256 加盐哈希，返回 "salt_hex$hash_hex"。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    """恒时比较校验密码，避免时序侧信道。"""
    try:
        salt_hex, hash_hex = stored.split("$", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), _ITERATIONS
    )
    return secrets.compare_digest(dk.hex(), hash_hex)


def _new_token() -> str:
    """生成 32 字节随机不透明 token（16 进制 64 字符）。"""
    return secrets.token_hex(32)


def login(username: str, password: str) -> dict:
    """校验账号密码并创建会话，返回 {token, user_id, username}。"""
    with session_scope() as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if user is None or not verify_password(password, user.password_hash):
            raise AppError(ERR_AUTH_FAILED, "账号或密码错误", http_status=401)
        token = _new_token()
        session.add(Session(token=token, user_id=user.id))
        return {"token": token, "user_id": user.id, "username": user.username}


def logout(token: str) -> None:
    """删除会话 token（登出，幂等）。"""
    if not token:
        return
    with session_scope() as session:
        row = session.exec(select(Session).where(Session.token == token)).first()
        if row is not None:
            session.delete(row)


def seed_users() -> None:
    """幂等预置 5 个账号：用户名 1~5，密码同名。已存在则跳过。"""
    with session_scope() as session:
        for username in ("1", "2", "3", "4", "5"):
            exists = session.exec(
                select(User).where(User.username == username)
            ).first()
            if exists is None:
                session.add(User(username=username, password_hash=hash_password(username)))
