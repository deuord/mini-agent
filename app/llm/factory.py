# LLM 客户端工厂:按配置路由 provider,单例复用

from config.loader import get_settings
from llm.base import LLMClient
from llm.openai_compat import OpenAICompatClient

_client: LLMClient | None = None


def get_llm_client(model_name: str | None = None) -> LLMClient:
    """获取 LLM 客户端(默认模型单例)。

    目前只有 openai_compat 一种 provider;后期加新 provider 在这里按
    config.provider 路由即可。
    """
    global _client
    if _client is None:
        cfg = get_settings().get_model(model_name)
        _client = OpenAICompatClient(cfg)
    return _client
