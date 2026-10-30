# -*- coding: utf-8 -*-
"""logger.py - Ghi nhật ký hoạt động (file + console), xoay vòng theo ngày dung lượng hợp lý."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from config import LOG_DIR

_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_configured = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    global _configured
    root = logging.getLogger("kho")
    if _configured:
        return root
    root.setLevel(level)
    root.propagate = False

    fmt = logging.Formatter(_FMT, datefmt="%Y-%m-%d %H:%M:%S")

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    sh.setLevel(logging.WARNING)
    root.addHandler(sh)

    fh = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    root.addHandler(fh)

    # Ghi riêng log đồng bộ để dễ chẩn đoán
    sync_fh = logging.handlers.RotatingFileHandler(
        LOG_DIR / "sync.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    sync_fh.setFormatter(fmt)
    logging.getLogger("kho.sync").addHandler(sync_fh)
    logging.getLogger("kho.sync").propagate = True

    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        setup_logging()
    return logging.getLogger(f"kho.{name}")
