# -*- coding: utf-8 -*-
"""统一响应封装与业务错误码定义。"""
from __future__ import annotations

from typing import Any

# ---------- 业务错误码 ----------
OK = 0
ERR_INVALID_WORD = 40001      # 单词非法 / 未找到
ERR_BAD_PARAM = 40002         # 查询参数缺失或格式错误
ERR_NOT_FOUND = 40401         # 资源不存在
ERR_CONFLICT = 40901          # 冲突（重名 / 已存在）
ERR_FILE_TOO_LARGE = 41301    # 上传文件过大
ERR_UNSUPPORTED_TYPE = 41501  # 文件类型不支持
ERR_VALIDATION = 42201        # 请求体校验失败
ERR_INTERNAL = 50001          # 服务器内部错误
ERR_DICT_UNAVAILABLE = 50301  # 词典不可用


class AppError(Exception):
    """业务异常：携带业务错误码与 HTTP 状态码，由全局异常处理器转为统一响应。"""

    def __init__(self, code: int, message: str, http_status: int = 400):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


def ok(data: Any = None, message: str = "ok") -> dict:
    """构造成功响应体。"""
    return {"code": OK, "message": message, "data": data}


def fail(code: int, message: str, data: Any = None) -> dict:
    """构造失败响应体。"""
    return {"code": code, "message": message, "data": data}
