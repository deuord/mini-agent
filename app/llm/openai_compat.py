# app/llm/openai_compat.py — OpenAI 兼容协议流式调用
from openai import AsyncOpenAI

from ..config.loader import load_models   # llm/ 下,上两级才到 app 包


async def chat_stream(messages, model=None, cfg=None):
    """流式调 LLM，逐段 yield 文本（async 生成器）"""
    cfg = cfg or load_models()
    conf = cfg.get_model(model)          # env 覆写 key 已在 get_model 里做
    client = AsyncOpenAI(
        api_key=conf.api_key,
        base_url=conf.base_url,
    )
    stream = None
    try:
        stream = await client.chat.completions.create(
            model=conf.model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:                # 逐块读
            if not chunk.choices:                 # 部分 provider 末尾会发空 choices
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta                       # 逐字吐出来
    finally:
        # 先关 SSE 流再关客户端,否则字节流迭代器被 GC 强杀会报 PoolByteStream 的错
        if stream is not None:
            await stream.close()
        await client.close()
