# LLM 客户端抽象:所有 provider 实现这个接口

from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list[dict]) -> str:
        """非流式对话,返回完整回复文本

        messages 为 OpenAI 格式: [{"role": "user", "content": "..."}]
        """

    @abstractmethod
    def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式对话,逐段 yield 增量文本"""
