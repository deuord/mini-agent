# 配置模型:定义 models.yaml 的结构,pydantic 校验

from pydantic import BaseModel


class ModelConfig(BaseModel):
    """单个模型的配置"""

    name: str
    provider: str = "openai_compat"
    base_url: str
    api_key: str
    model: str


class Settings(BaseModel):
    """models.yaml 顶层结构"""

    default: str
    models: list[ModelConfig]

    def get_model(self, name: str | None = None) -> ModelConfig:
        """按名称取模型配置,不传则取默认模型"""
        target = name or self.default
        for m in self.models:
            if m.name == target:
                return m
        raise ValueError(f"模型 {target!r} 未在 models.yaml 中配置")
