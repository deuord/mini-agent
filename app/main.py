# app/main.py — LLM 对话测试入口（chat 逻辑已拆到 app/chat.py）
import sys

from .config import loader
from .chat import chat


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    cfg = loader.load_models()
    reply = chat([{"role": "user", "content": "你好，请用一句话介绍自己"}],
                 model=name, cfg=cfg)
    print("AI:", reply)


if __name__ == "__main__":
    main()
