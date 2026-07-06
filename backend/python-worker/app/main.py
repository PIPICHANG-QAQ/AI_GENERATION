"""Python worker 应用入口。

本入口故意保持很薄：Java 主后端是唯一业务后端，Python 只注册 OCR、AI、导出等必要 worker 路由。
"""

from app.worker_base import app

# 导入路由模块会把兼容 API 和 /worker/* 注册到共享 FastAPI app。
from app import worker_routes as _worker_routes  # noqa: F401

__all__ = ["app"]
