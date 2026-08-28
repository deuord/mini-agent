# OpenAI 兼容协议实现:DeepSeek 及所有兼容 OpenAI 协议的模型都走这个

from typing import AsyncIterator

from openai import AsyncOpenAI

from config.schema import ModelConfig
from llm.base import LLMClient


class OpenAICompatClient(LLMClient):
    def __init__(self, config: ModelConfig):
        self._client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key)
        self._model = config.model

    async def chat(self, messages: list[dict]) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return resp.choices[0].message.content or ""

    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
