# 配置加载:读 models.yaml,做 ${环境变量} 替换,提供单例访问

import os
from pathlib import Path

import yaml

from config.schema import Settings

# 用 __file__ 定位项目根目录下的 configs/,不受启动时 cwd 影响
CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "models.yaml"


def _resolve_env(obj):
    """递归替换字符串里的 ${VAR} 为环境变量值"""
    if isinstance(obj, dict):
        return {k: _resolve_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env(v) for v in obj]
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    return obj


def load_settings() -> Settings:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    settings = Settings.model_validate(_resolve_env(raw))

    # env 未设置时快速失败,避免请求阶段才报 401 不好排查
    for m in settings.models:
        if "${" in m.api_key:
            raise RuntimeError(f"模型 {m.name} 的 api_key 环境变量未设置,请配置后再启动")

    return settings


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings
