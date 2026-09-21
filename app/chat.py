# app/chat.py — LLM 调用(非流式)
import time

from openai import OpenAI

from .config import loader


def chat(messages, model=None, cfg=None):
    """调 LLM，返回回复文本"""
    cfg = cfg or loader.load_models()
    conf = cfg.get_model(model)          # env 覆写 key 已在 get_model 里做
    client = OpenAI(
        api_key=conf.api_key,
        base_url=conf.base_url,
        timeout=30,
    )
    start = time.time()
    resp = client.chat.completions.create(
        model=conf.model,
        messages=messages,
    )
    cost = time.time() - start
    usage = resp.usage
    print(f"[llm] {conf.name} 耗时{cost:.2f}s | tokens: 输入{usage.prompt_tokens} + 输出{usage.completion_tokens}")
    return resp.choices[0].message.content
