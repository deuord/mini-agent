# app/llm/openai_compat.py — OpenAI 兼容协议流式调用
import time

from openai import AsyncOpenAI

from ..config.loader import load_models   # llm/ 下,上两级才到 app 包
from ..obs import log_event


async def chat_stream(messages, model=None, cfg=None, tools=None):
    """流式调 LLM，逐段 yield 文本（async 生成器）"""
    cfg = cfg or load_models()
    conf = cfg.get_model(model)          # env 覆写 key 已在 get_model 里做
    client = AsyncOpenAI(
        api_key=conf.api_key,
        base_url=conf.base_url,
        timeout=30,
    )
    stream = None
    usage = None
    t0 = time.monotonic()
    try:
        kwargs = dict(
            model=conf.model,
            messages=messages,
            stream=True,
            # 流式默认不回 usage,要显式要,末尾空 choices 的 chunk 才带(DeepSeek 兼容)
            stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"]=tools
        stream = await client.chat.completions.create(
            **kwargs,
        )
        async for chunk in stream:                # 逐块读
            if chunk.usage:                       # usage 在末尾空 choices 的 chunk 上,先接住再跳过
                usage = chunk.usage
            if not chunk.choices:                 # 部分 provider 末尾会发空 choices
                continue
            yield chunk.choices[0].delta #整个 delta交给runner解析
    finally:
        log_event(
            "llm",
            model=conf.model,
            latency_ms=round((time.monotonic() - t0) * 1000),
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )
        # 先关 SSE 流再关客户端,否则字节流迭代器被 GC 强杀会报 PoolByteStream 的错
        if stream is not None:
            await stream.close()
        await client.close()
