"""应用级配置：<应用目录>/config.json。API key 只放在这里（或环境变量），不进书文件夹。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .fsutil import read_json, write_json

# src/ligaotai/config.py → parents[2] 是仓库根目录
APP_DIR = Path(__file__).resolve().parents[2]
CONFIG_NAME = "config.json"
KEY_ENV = "LIGAOTAI_API_KEY"
MASK = "…"


class TierConfig(BaseModel):
    """一档模型。批量档抽场景卡，综合档做需要通盘考虑的判断。"""

    model: str = "deepseek-flash"
    thinking: Literal["on", "off", "default"] = "off"  # default = 不传，按接口自己的默认
    effort: str = ""  # 思考强度（reasoning_effort），空 = 不传
    json_mode: bool = True  # 传 response_format={"type": "json_object"}
    max_tokens: int = Field(8192, ge=256)


def _batch_tier() -> TierConfig:
    return TierConfig(thinking="off")


def _synth_tier() -> TierConfig:
    return TierConfig(thinking="on", effort="high", max_tokens=32768)


class AppConfig(BaseModel):
    library_dir: str = ""
    api_base: str = "https://api.deepseek.com"
    api_key: str = ""
    concurrency: int = Field(8, ge=1, le=64)
    timeout: float = Field(120, gt=0)  # 单次调用超时（秒）
    price_input: float = Field(0.30, ge=0)  # 美元 / 百万输入 token，默认按 deepseek-flash 高峰价（偏保守）
    price_output: float = Field(1.20, ge=0)  # 美元 / 百万输出 token
    batch: TierConfig = Field(default_factory=_batch_tier)
    synth: TierConfig = Field(default_factory=_synth_tier)


def load_config(app_dir: Path = APP_DIR) -> AppConfig:
    return AppConfig(**read_json(Path(app_dir) / CONFIG_NAME, {}))


def save_config(cfg: AppConfig, app_dir: Path = APP_DIR) -> None:
    write_json(Path(app_dir) / CONFIG_NAME, cfg.model_dump())


def library_path(cfg: AppConfig, app_dir: Path = APP_DIR) -> Path:
    return Path(cfg.library_dir) if cfg.library_dir else Path(app_dir) / "书库"


def effective_key(cfg: AppConfig) -> str:
    return cfg.api_key or os.environ.get(KEY_ENV, "")


def mask_key(key: str) -> str:
    if not key:
        return ""
    return key[:3] + MASK + key[-4:] if len(key) > 10 else MASK


def public_config(cfg: AppConfig, app_dir: Path = APP_DIR) -> dict:
    """给界面看的配置：key 只露头尾。"""
    key = effective_key(cfg)
    data = cfg.model_dump()
    data["api_key"] = mask_key(key)
    data["has_key"] = bool(key)
    data["key_from_env"] = bool(key) and not cfg.api_key
    data["library_path"] = str(library_path(cfg, app_dir))
    return data


def apply_update(old: AppConfig, new: AppConfig) -> AppConfig:
    """界面提交的配置里，key 是空的或还是打码的样子，就沿用原来的 key。"""
    if not new.api_key or MASK in new.api_key:
        return new.model_copy(update={"api_key": old.api_key})
    return new
