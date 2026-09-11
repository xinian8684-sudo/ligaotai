"""应用级配置：<应用目录>/config.json。"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .fsutil import read_json, write_json

# src/ligaotai/config.py → parents[2] 是仓库根目录
APP_DIR = Path(__file__).resolve().parents[2]
CONFIG_NAME = "config.json"


class AppConfig(BaseModel):
    library_dir: str = ""


def load_config(app_dir: Path = APP_DIR) -> AppConfig:
    return AppConfig(**read_json(Path(app_dir) / CONFIG_NAME, {}))


def save_config(cfg: AppConfig, app_dir: Path = APP_DIR) -> None:
    write_json(Path(app_dir) / CONFIG_NAME, cfg.model_dump())


def library_path(cfg: AppConfig, app_dir: Path = APP_DIR) -> Path:
    return Path(cfg.library_dir) if cfg.library_dir else Path(app_dir) / "书库"
